use crate::connection::ServerConfig;
use crate::device::DeviceKeys;
use crate::remote::{http_client, Remote};
use crate::{proxy, server, tls};
use base64::{engine::general_purpose::STANDARD, Engine};
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use futures_util::StreamExt;
use serde_json::{json, Value};
use std::sync::Arc;

fn temp_dir() -> std::path::PathBuf {
    let dir = std::env::temp_dir().join(format!("awp-shell-test-{}", rand::random::<u64>()));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

#[test]
fn server_addresses_take_host_or_api_port() {
    let expect = |input: &str, lan: &str, pairing: &str| {
        assert_eq!(server::server_addresses(input).unwrap(), (lan.to_owned(), pairing.to_owned()), "{input}");
    };
    expect("192.168.1.10", "https://192.168.1.10:8784", "https://192.168.1.10:8785");
    expect(" nas.local:9000 ", "https://nas.local:9000", "https://nas.local:9001");
    expect("https://192.168.1.10:8784/", "https://192.168.1.10:8784", "https://192.168.1.10:8785");
    // An old-style http:// address still means the (now TLS) server.
    expect("http://192.168.1.10:8784", "https://192.168.1.10:8784", "https://192.168.1.10:8785");
    expect("[fd00::1]", "https://[fd00::1]:8784", "https://[fd00::1]:8785");
    expect("[fd00::1]:8784", "https://[fd00::1]:8784", "https://[fd00::1]:8785");
    assert!(server::server_addresses("").is_err());
    assert!(server::server_addresses("user@host").is_err());
    assert!(server::server_addresses("host:abc").is_err());
}

#[test]
fn pairing_proof_matches_the_server() {
    // The same vector as core/tests/integration/test_server_auth.py.
    let proof = tls::pairing_proof(
        "abcd efgh",
        "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
        " Pixel ",
        "11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo=",
    )
    .unwrap();
    assert_eq!(proof, "m4cEA6CTmxd3dKZ2gFglM1kSzoiQ9w6GWJx6O+QIB3M=");
}

#[test]
fn query_token_is_removed_before_forwarding() {
    assert_eq!(proxy::query_without_token(None), "");
    assert_eq!(proxy::query_without_token(Some("token=x")), "");
    assert_eq!(proxy::query_without_token(Some("page=2&token=x&q=a+b")), "?page=2&q=a+b");
}

#[tokio::test]
async fn proxy_without_a_paired_server_says_so() {
    // A phone before its first pairing: the proxy runs, but has nowhere to go.
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    tokio::spawn(proxy::serve(listener, Arc::new(std::sync::Mutex::new(None)), "t".into()));
    let response = http_client()
        .get(format!("http://127.0.0.1:{port}/api/v1/animes"))
        .bearer_auth("t")
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), 503);
    let body: Value = response.json().await.unwrap();
    assert_eq!(body["detail"], "Kein Server gekoppelt");
}

/// Against a running server container with a fresh data directory:
/// AWP_E2E_SETUP_CODE=<code from its log> cargo test -- --ignored
#[tokio::test(flavor = "multi_thread")]
#[ignore]
async fn pairs_logs_in_and_proxies() {
    let code = std::env::var("AWP_E2E_SETUP_CODE").expect("AWP_E2E_SETUP_CODE");
    let address = std::env::var("AWP_E2E_ADDRESS").unwrap_or_else(|_| "127.0.0.1".into());
    let (lan_url, pairing_url) = server::server_addresses(&address).unwrap();
    let client = http_client();
    let key_dir = temp_dir();
    let keys = Arc::new(DeviceKeys::new(&key_dir, None));

    // Finding the server: TLS with its own certificate, captured for pinning.
    let (probe, verifier) = tls::capturing_client();
    let info: Value = probe.get(format!("{pairing_url}/pair/info")).send().await.unwrap().json().await.unwrap();
    assert_eq!(info["setup_required"], true);
    let fingerprint = verifier.seen().expect("certificate seen");
    // Any other certificate is refused once pinned.
    let impostor = tls::pinned_client(&"00".repeat(32)).get(format!("{pairing_url}/pair/info")).send().await;
    assert!(impostor.is_err());

    let public_key = keys.begin_pairing();
    let proof = tls::pairing_proof(&code, &fingerprint, "e2e", &public_key).unwrap();
    let paired: Value = tls::pinned_client(&fingerprint)
        .post(format!("{pairing_url}/pair/setup"))
        .json(&json!({ "proof": proof, "name": "e2e", "public_key": public_key }))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    let device_id = paired["device_id"].as_i64().unwrap();
    keys.commit_pairing().unwrap();
    if std::env::var_os("AWP_E2E_KEYRING").is_some() {
        assert!(!key_dir.join("device-key").exists(), "key landed in the fallback file, not the keyring");
    }

    // The signature verifies with the key the server stored.
    let signature = keys.sign_auth(device_id, "nonce").unwrap();
    let verifying = VerifyingKey::from_bytes(&STANDARD.decode(&public_key).unwrap().try_into().unwrap()).unwrap();
    let signature = Signature::from_slice(&STANDARD.decode(signature).unwrap()).unwrap();
    verifying
        .verify(format!("AnimeWatcherPlus auth v1\n{device_id}\nnonce").as_bytes(), &signature)
        .unwrap();

    let remote = Arc::new(Remote::new(
        ServerConfig {
            name: "e2e".into(),
            lan_url: lan_url.clone(),
            pairing_url: pairing_url.clone(),
            internet_url: None,
            device_id,
            tls_fingerprint: Some(fingerprint.clone()),
            folder_mappings: Vec::new(),
        },
        keys.clone(),
    ));
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let slot = Arc::new(std::sync::Mutex::new(Some(remote.clone())));
    tokio::spawn(proxy::serve(listener, slot, "local-token".into()));
    let proxy = format!("http://127.0.0.1:{port}");

    let without = client.get(format!("{proxy}/api/v1/auth/me")).send().await.unwrap();
    assert_eq!(without.status(), 401);
    let wrong = client.get(format!("{proxy}/api/v1/auth/me")).bearer_auth("nope").send().await.unwrap();
    assert_eq!(wrong.status(), 401);

    let me: Value = client
        .get(format!("{proxy}/api/v1/auth/me"))
        .bearer_auth("local-token")
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(me["mode"], "server");
    assert_eq!(me["device_id"], device_id);
    assert_eq!(me["is_admin"], true);

    // ?token= for what can't send headers, with the rest of the query kept.
    let folders = client.get(format!("{proxy}/api/v1/folders?token=local-token")).send().await.unwrap();
    assert_eq!(folders.status(), 200);

    // A token the server no longer knows is renewed transparently.
    remote.invalidate(false).await;
    let again = client.get(format!("{proxy}/api/v1/auth/me")).bearer_auth("local-token").send().await.unwrap();
    assert_eq!(again.status(), 200);

    // CORS preflight from the app's origin.
    let preflight = client
        .request(reqwest::Method::OPTIONS, format!("{proxy}/api/v1/folders"))
        .header("Origin", "tauri://localhost")
        .header("Access-Control-Request-Method", "POST")
        .header("Access-Control-Request-Headers", "authorization,content-type")
        .send()
        .await
        .unwrap();
    assert_eq!(preflight.headers()["access-control-allow-origin"], "tauri://localhost");

    // Live events through the proxy.
    let refused = tokio_tungstenite::connect_async(format!("ws://127.0.0.1:{port}/ws?token=nope")).await;
    assert!(refused.is_err());
    let (mut socket, _) = tokio_tungstenite::connect_async(format!("ws://127.0.0.1:{port}/ws?token=local-token"))
        .await
        .unwrap();
    let folder = client
        .post(format!("{proxy}/api/v1/folders"))
        .bearer_auth("local-token")
        .json(&json!({ "path": "/media", "type": "content" }))
        .send()
        .await
        .unwrap();
    assert!(folder.status().is_success(), "{}", folder.text().await.unwrap());
    let event = tokio::time::timeout(std::time::Duration::from_secs(10), socket.next())
        .await
        .expect("an event within 10s")
        .unwrap()
        .unwrap();
    assert!(event.is_text(), "{event:?}");

    // An admin's pairing-port call with the same session.
    let session = remote.session().await.unwrap();
    let pairing_code: Value = remote
        .lan_client()
        .post(format!("{pairing_url}/pair/codes"))
        .bearer_auth(&session.token)
        .send()
        .await
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(pairing_code["code"].as_str().unwrap().chars().filter(char::is_ascii_alphanumeric).count(), 8);

    // Moving the library. Server -> local first: the snapshot the local
    // core would take over on its next start.
    let snapshot_dir = temp_dir();
    let config = crate::connection::ConnectionConfig {
        mode: crate::connection::Mode::Local,
        server: Some(remote.server()),
    };
    let data_dir = temp_dir();
    // Local -> server: a stand-in for the local core serves that snapshot
    // as its export, and the shell uploads it to the server.
    let export = std::fs::read({
        let shell = server::Shell::new(
            snapshot_dir.clone(),
            snapshot_dir.clone(),
            config.clone(),
            crate::connection::Mode::Local,
            keys.clone(),
            client.clone(),
            0,
            String::new(),
        );
        server::pull_library(&shell, vec![], &data_dir).await.unwrap();
        data_dir.join("pending-import.zip")
    })
    .unwrap();
    assert_eq!(&export[..2], b"PK");
    assert_eq!(std::fs::read_to_string(data_dir.join("pending-import.json")).unwrap(), "[]");

    let local_core = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let local_port = local_core.local_addr().unwrap().port();
    local_core.set_nonblocking(true).unwrap();
    let app = axum::Router::new().route("/admin/export", axum::routing::get(move || async move { export.clone() }));
    let local_core = tokio::net::TcpListener::from_std(local_core).unwrap();
    tokio::spawn(async move { axum::serve(local_core, app).await });
    let shell = server::Shell::new(
        snapshot_dir.clone(),
        snapshot_dir.clone(),
        config,
        crate::connection::Mode::Local,
        keys.clone(),
        client.clone(),
        local_port,
        "local".into(),
    );
    let refused = server::push_library(&shell, vec![], false).await.unwrap_err();
    assert_eq!(refused.status, Some(409), "{}", refused.message);
    let imported = server::push_library(
        &shell,
        vec![server::PathMapping { source: "/media".into(), target: "/media".into() }],
        true,
    )
    .await
    .unwrap();
    assert!(imported["rows"].as_u64().unwrap() > 0, "{imported}");
    assert!(!snapshot_dir.join("upload-snapshot.zip").exists());

    keys.forget();
}
