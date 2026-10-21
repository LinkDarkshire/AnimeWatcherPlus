//! The session with a paired server: which of its addresses answers (the LAN
//! one first, then the internet one) and a short-lived access token, got by
//! signing the server's challenge with the device key and renewed before it
//! runs out.

use crate::connection::ServerConfig;
use crate::device::DeviceKeys;
use crate::tls;
use serde::de::DeserializeOwned;
use serde::Deserialize;
use serde_json::json;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;

/// A failed request to the server; `status` is None if it never answered.
#[derive(Debug, serde::Serialize)]
pub struct Failure {
    pub status: Option<u16>,
    pub message: String,
}

impl Failure {
    pub fn network(err: reqwest::Error) -> Self {
        Failure {
            status: None,
            message: format!("Server nicht erreichbar ({err})"),
        }
    }
}

impl From<String> for Failure {
    fn from(message: String) -> Failure {
        Failure { status: None, message }
    }
}

impl From<&str> for Failure {
    fn from(message: &str) -> Failure {
        message.to_owned().into()
    }
}

impl From<Failure> for String {
    fn from(failure: Failure) -> String {
        failure.message
    }
}

/// The response if it's a success, otherwise the server's `detail` message.
pub async fn check(
    response: Result<reqwest::Response, reqwest::Error>,
) -> Result<reqwest::Response, Failure> {
    let response = response.map_err(Failure::network)?;
    if response.status().is_success() {
        return Ok(response);
    }
    let status = response.status().as_u16();
    let text = response.text().await.unwrap_or_default();
    let message = serde_json::from_str::<serde_json::Value>(&text)
        .ok()
        .and_then(|v| v.get("detail").and_then(|d| d.as_str()).map(str::to_owned))
        .unwrap_or_else(|| format!("Der Server antwortete mit HTTP {status}"));
    Err(Failure {
        status: Some(status),
        message,
    })
}

pub async fn read_json<T: DeserializeOwned>(
    response: Result<reqwest::Response, reqwest::Error>,
) -> Result<T, Failure> {
    check(response).await?.json().await.map_err(|e| Failure {
        status: None,
        message: format!("Unerwartete Antwort vom Server ({e})"),
    })
}

/// Plain HTTP to this machine's own core (127.0.0.1).
pub fn http_client() -> reqwest::Client {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(8))
        .build()
        .expect("failed to build HTTP client")
}

pub struct Session {
    pub base: String,
    pub token: String,
    /// The HTTP client and TLS settings for `base` (pinned for the LAN).
    pub client: reqwest::Client,
    pub tls: Arc<rustls::ClientConfig>,
}

#[derive(Default)]
struct State {
    base: Option<String>,
    token: Option<(String, Instant)>,
}

pub struct Remote {
    server: std::sync::RwLock<ServerConfig>,
    lan: (reqwest::Client, Arc<rustls::ClientConfig>),
    public: (reqwest::Client, Arc<rustls::ClientConfig>),
    keys: Arc<DeviceKeys>,
    state: Mutex<State>,
}

impl Remote {
    pub fn new(server: ServerConfig, keys: Arc<DeviceKeys>) -> Self {
        // No pin (paired before the server had TLS): nothing matches, the
        // device has to be paired again.
        let pin = server.tls_fingerprint.clone().unwrap_or_default();
        let lan_tls = tls::pinned_config(tls::pinned_verifier(Some(pin.clone())));
        let public_tls = tls::public_config();
        Remote {
            server: std::sync::RwLock::new(server),
            lan: (tls::pinned_client(&pin), lan_tls),
            public: (tls::public_client(), public_tls),
            keys,
            state: Mutex::new(State::default()),
        }
    }

    /// For the LAN-only pairing port (pinned certificate).
    pub fn lan_client(&self) -> reqwest::Client {
        self.lan.0.clone()
    }

    fn connection_for(&self, base: &str) -> &(reqwest::Client, Arc<rustls::ClientConfig>) {
        if base == self.server().lan_url {
            &self.lan
        } else {
            &self.public
        }
    }

    pub fn server(&self) -> ServerConfig {
        self.server.read().unwrap().clone()
    }

    /// E.g. a newly entered internet address; the next pick uses it.
    pub fn update_server(&self, server: ServerConfig) {
        *self.server.write().unwrap() = server;
    }

    async fn answers(&self, base: &str, timeout: Duration) -> bool {
        let client = &self.connection_for(base).0;
        matches!(
            client.get(format!("{base}/health")).timeout(timeout).send().await,
            Ok(response) if response.status().is_success()
        )
    }

    async fn pick_base(&self) -> Result<String, Failure> {
        // At home the LAN address answers within milliseconds; elsewhere it
        // doesn't exist, so don't wait long for it.
        let server = self.server();
        if self.answers(&server.lan_url, Duration::from_millis(1500)).await {
            return Ok(server.lan_url);
        }
        if let Some(url) = &server.internet_url {
            if self.answers(url, Duration::from_secs(8)).await {
                return Ok(url.clone());
            }
        }
        Err(Failure {
            status: None,
            message: format!("Der Server „{}“ ist nicht erreichbar", server.name),
        })
    }

    /// The address in use and a valid access token, logging in if needed.
    pub async fn session(&self) -> Result<Session, Failure> {
        let mut state = self.state.lock().await;
        let base = match &state.base {
            Some(base) => base.clone(),
            None => {
                let base = self.pick_base().await?;
                state.base = Some(base.clone());
                base
            }
        };
        if let Some((token, expires)) = &state.token {
            if *expires > Instant::now() + Duration::from_secs(60) {
                return Ok(self.session_for(base, token.clone()));
            }
        }
        match self.login(&base).await {
            Ok((token, ttl)) => {
                state.token = Some((token.clone(), Instant::now() + Duration::from_secs(ttl)));
                Ok(self.session_for(base, token))
            }
            Err(failure) => {
                if failure.status.is_none() {
                    // Maybe the network changed (left home): pick again next time.
                    state.base = None;
                }
                Err(failure)
            }
        }
    }

    /// After a rejected token (401), or with `network` after a connection
    /// error: log in again / pick the address again on the next request.
    pub async fn invalidate(&self, network: bool) {
        let mut state = self.state.lock().await;
        state.token = None;
        if network {
            state.base = None;
        }
    }

    fn session_for(&self, base: String, token: String) -> Session {
        let (client, tls) = self.connection_for(&base).clone();
        Session {
            base,
            token,
            client,
            tls,
        }
    }

    async fn login(&self, base: &str) -> Result<(String, u64), Failure> {
        #[derive(Deserialize)]
        struct Challenge {
            nonce: String,
        }
        #[derive(Deserialize)]
        struct Token {
            token: String,
            expires_in: u64,
        }
        let device_id = self.server().device_id;
        let client = &self.connection_for(base).0;
        let challenge: Challenge = read_json(
            client
                .post(format!("{base}/api/v1/auth/challenge"))
                .json(&json!({ "device_id": device_id }))
                .send()
                .await,
        )
        .await?;
        let signature = self.keys.sign_auth(device_id, &challenge.nonce).map_err(|message| Failure {
            status: None,
            message,
        })?;
        let token: Token = read_json(
            client
                .post(format!("{base}/api/v1/auth/token"))
                .json(&json!({ "device_id": device_id, "nonce": challenge.nonce, "signature": signature }))
                .send()
                .await,
        )
        .await?;
        Ok((token.token, token.expires_in))
    }
}
