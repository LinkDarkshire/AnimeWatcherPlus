//! Commands for connecting the desktop app to a server: pairing, switching
//! between local and server data, moving the library, and the admin's
//! pairing-port calls (adding devices).

use crate::connection::{self, ConnectionConfig, Mode, ServerConfig};
use crate::device::DeviceKeys;
use crate::remote::{check, read_json, Failure, Remote};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::State;
use tokio::io::AsyncWriteExt;

const DEFAULT_API_PORT: u16 = 8784;

/// Everything the connection commands share.
pub struct Shell {
    pub config_dir: PathBuf,
    pub cache_dir: PathBuf,
    pub config: Mutex<ConnectionConfig>,
    pub keys: Arc<DeviceKeys>,
    pub client: reqwest::Client,
    /// The mode this run started in (a switch only applies after a restart).
    pub mode: Mode,
    /// Where the UI's requests go: the local core, or the proxy.
    pub port: u16,
    pub token: String,
    remote: Mutex<Option<Arc<Remote>>>,
    pairing: tokio::sync::Mutex<Option<PendingPairing>>,
}

struct PendingPairing {
    name: String,
    lan_url: String,
    pairing_url: String,
    request_id: String,
}

impl Shell {
    pub fn new(
        config_dir: PathBuf,
        cache_dir: PathBuf,
        config: ConnectionConfig,
        keys: Arc<DeviceKeys>,
        client: reqwest::Client,
        port: u16,
        token: String,
    ) -> Self {
        Shell {
            config_dir,
            cache_dir,
            mode: config.mode,
            config: Mutex::new(config),
            keys,
            client,
            port,
            token,
            remote: Mutex::new(None),
            pairing: tokio::sync::Mutex::new(None),
        }
    }

    /// The session with the paired server, made on first use.
    pub fn remote(&self) -> Result<Arc<Remote>, Failure> {
        let mut remote = self.remote.lock().unwrap();
        if let Some(existing) = remote.as_ref() {
            return Ok(existing.clone());
        }
        let server = self
            .config
            .lock()
            .unwrap()
            .server
            .clone()
            .ok_or("Kein Server gekoppelt")?;
        let created = Arc::new(Remote::new(server, self.keys.clone(), self.client.clone()));
        *remote = Some(created.clone());
        Ok(created)
    }

    fn update_config(&self, change: impl FnOnce(&mut ConnectionConfig)) -> Result<ConnectionConfig, Failure> {
        let mut config = self.config.lock().unwrap();
        let mut updated = config.clone();
        change(&mut updated);
        connection::save(&connection::config_file(&self.config_dir), &updated)?;
        *config = updated.clone();
        Ok(updated)
    }

    fn set_server(&self, server: Option<ServerConfig>) -> Result<(), Failure> {
        let keep_session = self.mode == Mode::Server;
        self.update_config(|config| {
            config.server = server.clone();
            if server.is_none() {
                config.mode = Mode::Local;
            }
        })?;
        let mut remote = self.remote.lock().unwrap();
        match (server, remote.as_ref()) {
            // The running proxy keeps its session; it just learns the change.
            (Some(server), Some(existing)) if keep_session => existing.update_server(server),
            _ => *remote = None,
        }
        Ok(())
    }
}

#[derive(Serialize)]
pub struct ConnectionInfo {
    port: u16,
    token: String,
    /// The mode this run uses.
    mode: Mode,
    /// The mode the next start will use.
    next_mode: Mode,
    server: Option<ServerConfig>,
}

#[tauri::command]
pub fn get_connection_info(shell: State<Shell>) -> ConnectionInfo {
    let config = shell.config.lock().unwrap().clone();
    ConnectionInfo {
        port: shell.port,
        token: shell.token.clone(),
        mode: shell.mode,
        next_mode: config.mode,
        server: config.server,
    }
}

// --- Pairing ---------------------------------------------------------------------

/// "192.168.1.10", "nas.local:8784" or "http://192.168.1.10:8784/" -> the
/// API and pairing addresses (pairing is always the API port + 1).
pub(crate) fn server_addresses(address: &str) -> Result<(String, String), Failure> {
    let trimmed = address.trim();
    let without_scheme = trimmed
        .strip_prefix("http://")
        .or_else(|| trimmed.strip_prefix("https://"))
        .unwrap_or(trimmed);
    let authority = without_scheme.split('/').next().unwrap_or_default();
    if authority.is_empty() || authority.contains(['@', ' ', '?', '#']) {
        return Err("Ungültige Server-Adresse".into());
    }
    let (host, port) = match authority.rsplit_once(':') {
        // An IPv6 address without port ("[fd00::1]") has its colons inside brackets.
        Some((host, port)) if !port.contains(']') => {
            let port: u16 = port.parse().map_err(|_| Failure::from("Ungültiger Port"))?;
            (host, port)
        }
        _ => (authority, DEFAULT_API_PORT),
    };
    let pairing_port = port.checked_add(1).ok_or("Ungültiger Port")?;
    Ok((format!("http://{host}:{port}"), format!("http://{host}:{pairing_port}")))
}

#[derive(Serialize)]
pub struct Probe {
    server_name: String,
    version: String,
    setup_required: bool,
    lan_url: String,
    pairing_url: String,
}

/// Looks for a server at an address in the LAN.
#[tauri::command]
pub async fn server_probe(shell: State<'_, Shell>, address: String) -> Result<Probe, Failure> {
    #[derive(Deserialize)]
    struct Info {
        server_name: String,
        version: String,
        setup_required: bool,
    }
    let (lan_url, pairing_url) = server_addresses(&address)?;
    let info: Info = read_json(
        shell
            .client
            .get(format!("{pairing_url}/pair/info"))
            .timeout(Duration::from_secs(5))
            .send()
            .await,
    )
    .await
    .map_err(|failure| match failure.status {
        None => Failure::from(format!(
            "Unter {pairing_url} antwortet kein AnimeWatcherPlus-Server. Koppeln geht nur im selben Netzwerk wie der Server."
        )),
        Some(_) => failure,
    })?;
    Ok(Probe {
        server_name: info.server_name,
        version: info.version,
        setup_required: info.setup_required,
        lan_url,
        pairing_url,
    })
}

#[derive(Serialize)]
pub struct PairStatus {
    /// "paired", "pending" (an admin still has to approve) or "rejected".
    status: &'static str,
    /// Shown on both devices while waiting, to compare.
    fingerprint: Option<String>,
}

impl Shell {
    fn finish_pairing(&self, name: String, lan_url: String, pairing_url: String, device_id: i64) -> Result<(), Failure> {
        self.keys.commit_pairing()?;
        self.set_server(Some(ServerConfig {
            name,
            lan_url,
            pairing_url,
            internet_url: None,
            device_id,
        }))
    }
}

/// Pairs this device: with the setup code from the server's log (the first
/// device, which becomes admin) or with a pairing code from an admin device
/// (then the admin still has to approve, see `server_pair_status`).
#[tauri::command]
pub async fn server_pair(
    shell: State<'_, Shell>,
    lan_url: String,
    pairing_url: String,
    server_name: String,
    device_name: String,
    code: String,
    setup: bool,
) -> Result<PairStatus, Failure> {
    #[derive(Deserialize)]
    struct Paired {
        device_id: i64,
    }
    #[derive(Deserialize)]
    struct Joined {
        request_id: String,
        fingerprint: String,
    }
    if shell.mode == Mode::Server {
        return Err("Erst zur lokalen Bibliothek zurückwechseln".into());
    }
    let public_key = shell.keys.begin_pairing();
    let payload = json!({ "code": code.trim().to_uppercase(), "name": device_name.trim(), "public_key": public_key });
    if setup {
        let paired: Paired = read_json(
            shell
                .client
                .post(format!("{pairing_url}/pair/setup"))
                .json(&payload)
                .send()
                .await,
        )
        .await?;
        shell.finish_pairing(server_name, lan_url, pairing_url, paired.device_id)?;
        return Ok(PairStatus {
            status: "paired",
            fingerprint: None,
        });
    }
    let joined: Joined = read_json(
        shell
            .client
            .post(format!("{pairing_url}/pair/join"))
            .json(&payload)
            .send()
            .await,
    )
    .await?;
    *shell.pairing.lock().await = Some(PendingPairing {
        name: server_name,
        lan_url,
        pairing_url,
        request_id: joined.request_id,
    });
    Ok(PairStatus {
        status: "pending",
        fingerprint: Some(joined.fingerprint),
    })
}

/// Polled while waiting for an admin to approve this device.
#[tauri::command]
pub async fn server_pair_status(shell: State<'_, Shell>) -> Result<PairStatus, Failure> {
    #[derive(Deserialize)]
    struct Status {
        status: String,
        device_id: Option<i64>,
    }
    let mut pending = shell.pairing.lock().await;
    let request = pending.as_ref().ok_or("Keine Kopplung im Gange")?;
    let status: Status = read_json(
        shell
            .client
            .get(format!("{}/pair/join/{}", request.pairing_url, request.request_id))
            .send()
            .await,
    )
    .await?;
    match (status.status.as_str(), status.device_id) {
        ("approved", Some(device_id)) => {
            let request = pending.take().expect("checked above");
            shell.finish_pairing(request.name, request.lan_url, request.pairing_url, device_id)?;
            Ok(PairStatus {
                status: "paired",
                fingerprint: None,
            })
        }
        ("rejected", _) => {
            *pending = None;
            Ok(PairStatus {
                status: "rejected",
                fingerprint: None,
            })
        }
        _ => Ok(PairStatus {
            status: "pending",
            fingerprint: None,
        }),
    }
}

/// The server's address from the internet (through the reverse proxy), or
/// none. Only https: that address goes over networks nobody controls.
#[tauri::command]
pub fn server_set_internet_url(shell: State<Shell>, url: Option<String>) -> Result<(), Failure> {
    let url = url
        .map(|u| u.trim().trim_end_matches('/').to_owned())
        .filter(|u| !u.is_empty());
    if let Some(u) = &url {
        let valid = u.strip_prefix("https://").is_some_and(|rest| !rest.is_empty() && !rest.contains(['/', '?', '#', '@', ' ']));
        if !valid {
            return Err("Die Internet-Adresse muss mit https:// beginnen, z. B. https://anime.example.com".into());
        }
    }
    let mut server = shell.config.lock().unwrap().server.clone().ok_or("Kein Server gekoppelt")?;
    server.internet_url = url;
    shell.set_server(Some(server))
}

/// Which data the next start uses. The UI restarts the app afterwards.
#[tauri::command]
pub fn switch_mode(shell: State<Shell>, mode: Mode) -> Result<(), Failure> {
    if mode == Mode::Server && shell.config.lock().unwrap().server.is_none() {
        return Err("Kein Server gekoppelt".into());
    }
    shell.update_config(|config| config.mode = mode).map(|_| ())
}

/// Removes the server and this device's key (pairing again makes a new one).
#[tauri::command]
pub fn server_forget(shell: State<Shell>) -> Result<(), Failure> {
    shell.set_server(None)?;
    shell.keys.forget();
    Ok(())
}

/// An admin's calls to the LAN-only pairing port: making pairing codes,
/// listing and deciding join requests. Only /pair/ paths.
#[tauri::command]
pub async fn server_pairing_call(
    shell: State<'_, Shell>,
    method: String,
    path: String,
    body: Option<Value>,
) -> Result<Value, Failure> {
    if !path.starts_with("/pair/") || path.contains("..") {
        return Err("Ungültiger Pfad".into());
    }
    let method = match method.as_str() {
        "GET" => reqwest::Method::GET,
        "POST" => reqwest::Method::POST,
        _ => return Err("Ungültige Methode".into()),
    };
    let remote = shell.remote()?;
    let session = remote.session().await?;
    let mut request = shell
        .client
        .request(method, format!("{}{path}", remote.server().pairing_url))
        .bearer_auth(&session.token)
        .timeout(Duration::from_secs(10));
    if let Some(body) = body {
        request = request.json(&body);
    }
    read_json(request.send().await).await.map_err(|failure| match failure.status {
        None => Failure::from("Das geht nur im selben Netzwerk wie der Server"),
        Some(_) => failure,
    })
}

// --- Moving the library ------------------------------------------------------------

async fn download_to(response: reqwest::Response, target: &std::path::Path) -> Result<(), Failure> {
    use futures_util::StreamExt;
    if let Some(parent) = target.parent() {
        tokio::fs::create_dir_all(parent).await.map_err(|e| e.to_string())?;
    }
    let mut file = tokio::fs::File::create(target).await.map_err(|e| e.to_string())?;
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|e| format!("Übertragung abgebrochen ({e})"))?;
        file.write_all(&chunk).await.map_err(|e| e.to_string())?;
    }
    file.flush().await.map_err(|e| e.to_string())?;
    Ok(())
}

#[derive(Deserialize, Serialize, Clone)]
pub struct PathMapping {
    pub source: String,
    pub target: String,
}

/// Local -> server: exports this app's library and imports it on the
/// server, with paths rewritten (`mappings`). A server that already has a
/// library refuses with 409 unless `force`.
#[tauri::command]
pub async fn server_push_library(
    shell: State<'_, Shell>,
    mappings: Vec<PathMapping>,
    force: bool,
) -> Result<Value, Failure> {
    push_library(&shell, mappings, force).await
}

pub(crate) async fn push_library(shell: &Shell, mappings: Vec<PathMapping>, force: bool) -> Result<Value, Failure> {
    if shell.mode != Mode::Local {
        return Err("Nur mit der lokalen Bibliothek möglich".into());
    }
    let snapshot = shell.cache_dir.join("upload-snapshot.zip");
    let result = async {
        let export = check(
            shell
                .client
                .get(format!("http://127.0.0.1:{}/admin/export", shell.port))
                .bearer_auth(&shell.token)
                .send()
                .await,
        )
        .await?;
        download_to(export, &snapshot).await?;

        let remote = shell.remote()?;
        let session = remote.session().await?;
        let file = tokio::fs::File::open(&snapshot).await.map_err(|e| e.to_string())?;
        let length = file.metadata().await.map_err(|e| e.to_string())?.len();
        let mappings = serde_json::to_string(&mappings).map_err(|e| e.to_string())?;
        read_json(
            shell
                .client
                .post(format!("{}/admin/import", remote.server().pairing_url))
                .query(&[("mappings", mappings.as_str()), ("force", if force { "true" } else { "false" })])
                .bearer_auth(&session.token)
                .header(reqwest::header::CONTENT_TYPE, "application/zip")
                .header(reqwest::header::CONTENT_LENGTH, length)
                .body(reqwest::Body::wrap_stream(tokio_util::io::ReaderStream::new(file)))
                .send()
                .await,
        )
        .await
    }
    .await;
    let _ = tokio::fs::remove_file(&snapshot).await;
    result
}

/// Server -> local: downloads the server's library for the local core,
/// which takes it over (paths rewritten by `mappings`) on its next start.
/// The current local library is kept as a backup file.
#[tauri::command]
pub async fn server_pull_library(shell: State<'_, Shell>, mappings: Vec<PathMapping>) -> Result<(), Failure> {
    let data_dir = connection::core_data_dir().ok_or("Datenordner der App nicht gefunden")?;
    pull_library(&shell, mappings, &data_dir).await
}

pub(crate) async fn pull_library(shell: &Shell, mappings: Vec<PathMapping>, data_dir: &std::path::Path) -> Result<(), Failure> {
    let remote = shell.remote()?;
    let session = remote.session().await?;
    let export = check(
        shell
            .client
            .get(format!("{}/admin/export", remote.server().pairing_url))
            .bearer_auth(&session.token)
            .send()
            .await,
    )
    .await
    .map_err(|failure| match failure.status {
        None => Failure::from("Das geht nur im selben Netzwerk wie der Server"),
        Some(_) => failure,
    })?;
    // Names as in core/app/services/snapshot.py (PENDING_SNAPSHOT/MAPPINGS).
    let partial = data_dir.join("pending-import.zip.part");
    if let Err(failure) = download_to(export, &partial).await {
        let _ = tokio::fs::remove_file(&partial).await;
        return Err(failure);
    }
    let mappings = serde_json::to_string(&mappings).map_err(|e| e.to_string())?;
    tokio::fs::write(data_dir.join("pending-import.json"), mappings)
        .await
        .map_err(|e| e.to_string())?;
    tokio::fs::rename(&partial, data_dir.join("pending-import.zip"))
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}
