//! Server mode: the UI talks to this small proxy on 127.0.0.1 exactly as it
//! talks to the local core (same per-session token), and the proxy forwards
//! everything to the server with the device's access token. That way the
//! device key and the server token never reach the web view, the UI needs no
//! special cases for CORS or mixed content (plain-HTTP LAN address from a
//! secure page), and switching between the LAN and the internet address
//! happens here, invisibly.

use crate::remote::{Failure, Remote};
use axum::body::Body;
use axum::extract::ws::{CloseFrame, Message, WebSocket, WebSocketUpgrade};
use axum::extract::{Request, State};
use axum::http::{header, HeaderMap, HeaderValue, StatusCode, Uri};
use axum::response::{IntoResponse, Response};
use axum::routing::any;
use axum::Router;
use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use tokio_tungstenite::tungstenite::Message as UpstreamMessage;
use tower_http::cors::{AllowHeaders, AllowMethods, AllowOrigin, CorsLayer};

// The UI's own requests are small JSON; snapshots go through dedicated commands.
const MAX_BODY: usize = 64 * 1024 * 1024;

// The web view's origins, as in the core (core/app/main.py).
const ORIGINS: [&str; 4] = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:5173",
];

const FORWARDED_REQUEST_HEADERS: [header::HeaderName; 5] = [
    header::CONTENT_TYPE,
    header::ACCEPT,
    header::RANGE,
    header::IF_NONE_MATCH,
    header::IF_MODIFIED_SINCE,
];

fn is_forwarded_response_header(name: &str) -> bool {
    !matches!(
        name,
        "connection" | "keep-alive" | "transfer-encoding" | "te" | "trailer" | "upgrade" | "proxy-connection"
    ) && !name.starts_with("access-control-")
}

#[derive(Clone)]
struct Proxy {
    remote: Arc<Remote>,
    token: Arc<String>,
}

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

fn query_token(query: Option<&str>) -> Option<String> {
    url::form_urlencoded::parse(query?.as_bytes())
        .find(|(key, _)| key == "token")
        .map(|(_, value)| value.into_owned())
}

/// The query string without the local token (it means nothing to the server).
pub(crate) fn query_without_token(query: Option<&str>) -> String {
    let Some(query) = query else {
        return String::new();
    };
    let mut rebuilt = url::form_urlencoded::Serializer::new(String::new());
    for (key, value) in url::form_urlencoded::parse(query.as_bytes()) {
        if key != "token" {
            rebuilt.append_pair(&key, &value);
        }
    }
    let rebuilt = rebuilt.finish();
    if rebuilt.is_empty() {
        rebuilt
    } else {
        format!("?{rebuilt}")
    }
}

impl Proxy {
    /// Bearer header, or ?token= for what can't send headers (<img>, WebSocket).
    fn authorized(&self, headers: &HeaderMap, query: Option<&str>) -> bool {
        let bearer = headers
            .get(header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.strip_prefix("Bearer "))
            .map(str::to_owned);
        bearer
            .or_else(|| query_token(query))
            .is_some_and(|token| constant_time_eq(token.as_bytes(), self.token.as_bytes()))
    }
}

fn error_response(status: StatusCode, message: &str) -> Response {
    (status, axum::Json(serde_json::json!({ "detail": message }))).into_response()
}

fn failure_response(failure: Failure) -> Response {
    let status = failure
        .status
        .and_then(|s| StatusCode::from_u16(s).ok())
        .unwrap_or(StatusCode::BAD_GATEWAY);
    error_response(status, &failure.message)
}

async fn forward(State(proxy): State<Proxy>, request: Request) -> Response {
    let (parts, body) = request.into_parts();
    let query = parts.uri.query();
    if parts.uri.path() != "/health" && !proxy.authorized(&parts.headers, query) {
        return error_response(StatusCode::UNAUTHORIZED, "invalid or missing token");
    }
    let Ok(body) = axum::body::to_bytes(body, MAX_BODY).await else {
        return error_response(StatusCode::PAYLOAD_TOO_LARGE, "Anfrage zu groß");
    };
    let target = format!("{}{}", parts.uri.path(), query_without_token(query));

    let mut retried = false;
    loop {
        let session = match proxy.remote.session().await {
            Ok(session) => session,
            Err(failure) => return failure_response(failure),
        };
        let mut upstream = proxy
            .remote
            .client
            .request(parts.method.clone(), format!("{}{}", session.base, target))
            .bearer_auth(&session.token)
            .body(body.clone());
        for name in &FORWARDED_REQUEST_HEADERS {
            if let Some(value) = parts.headers.get(name) {
                upstream = upstream.header(name, value);
            }
        }
        match upstream.send().await {
            // The token ran out early (e.g. the server restarted): log in again.
            Ok(response) if response.status() == StatusCode::UNAUTHORIZED && !retried => {
                proxy.remote.invalidate(false).await;
            }
            Ok(response) => return relay(response),
            // Never reached the server (e.g. left the LAN): pick the address
            // again. Only on connect errors -- anything later might have run.
            Err(err) if err.is_connect() && !retried => {
                proxy.remote.invalidate(true).await;
            }
            Err(err) => return failure_response(Failure::network(err)),
        }
        retried = true;
    }
}

fn relay(response: reqwest::Response) -> Response {
    let mut builder = Response::builder().status(response.status());
    for (name, value) in response.headers() {
        if is_forwarded_response_header(name.as_str()) {
            builder = builder.header(name, value);
        }
    }
    builder
        .body(Body::from_stream(response.bytes_stream()))
        .unwrap_or_else(|_| error_response(StatusCode::BAD_GATEWAY, "Ungültige Antwort vom Server"))
}

async fn websocket(
    State(proxy): State<Proxy>,
    headers: HeaderMap,
    uri: Uri,
    upgrade: WebSocketUpgrade,
) -> Response {
    if !proxy.authorized(&headers, uri.query()) {
        return error_response(StatusCode::UNAUTHORIZED, "invalid or missing token");
    }
    upgrade.on_upgrade(move |socket| relay_websocket(proxy, socket))
}

type Upstream = tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>;

async fn connect_upstream(proxy: &Proxy) -> Result<Upstream, String> {
    let mut retried = false;
    loop {
        let session = proxy.remote.session().await?;
        let ws_base = if let Some(rest) = session.base.strip_prefix("https://") {
            format!("wss://{rest}")
        } else {
            format!("ws://{}", session.base.trim_start_matches("http://"))
        };
        let token: String = url::form_urlencoded::byte_serialize(session.token.as_bytes()).collect();
        match tokio_tungstenite::connect_async(format!("{ws_base}/ws?token={token}")).await {
            Ok((stream, _)) => return Ok(stream),
            Err(err) if !retried => {
                log::info!("server websocket refused ({err}); logging in again");
                proxy.remote.invalidate(matches!(err, tokio_tungstenite::tungstenite::Error::Io(_))).await;
                retried = true;
            }
            Err(err) => return Err(format!("server websocket: {err}")),
        }
    }
}

async fn relay_websocket(proxy: Proxy, client: WebSocket) {
    let (mut to_client, mut from_client) = client.split();
    let upstream = match connect_upstream(&proxy).await {
        Ok(upstream) => upstream,
        Err(err) => {
            log::warn!("{err}");
            // The UI reconnects after a while.
            let _ = to_client
                .send(Message::Close(Some(CloseFrame {
                    code: 1011,
                    reason: "server unavailable".into(),
                })))
                .await;
            return;
        }
    };
    let (mut to_server, mut from_server) = upstream.split();

    let downstream = async {
        while let Some(Ok(message)) = from_server.next().await {
            let forwarded = match message {
                UpstreamMessage::Text(text) => Message::Text(text.as_str().into()),
                UpstreamMessage::Binary(data) => Message::Binary(data),
                UpstreamMessage::Close(frame) => {
                    // E.g. 4401 when the token ran out: the UI reconnects
                    // and gets a fresh one through the proxy.
                    let _ = to_client
                        .send(Message::Close(frame.map(|f| CloseFrame {
                            code: f.code.into(),
                            reason: f.reason.as_str().into(),
                        })))
                        .await;
                    return;
                }
                _ => continue,
            };
            if to_client.send(forwarded).await.is_err() {
                return;
            }
        }
        let _ = to_client.send(Message::Close(None)).await;
    };
    let upstream_direction = async {
        while let Some(Ok(message)) = from_client.next().await {
            let forwarded = match message {
                Message::Text(text) => UpstreamMessage::Text(text.as_str().into()),
                Message::Binary(data) => UpstreamMessage::Binary(data),
                Message::Close(_) => break,
                _ => continue,
            };
            if to_server.send(forwarded).await.is_err() {
                return;
            }
        }
        let _ = to_server.send(UpstreamMessage::Close(None)).await;
    };
    tokio::select! {
        _ = downstream => {}
        _ = upstream_direction => {}
    }
}

/// Serves the proxy on an already bound listener (bound by the caller, so
/// the port is known before the UI asks for it).
pub async fn serve(listener: std::net::TcpListener, remote: Arc<Remote>, token: String) {
    let listener = match listener
        .set_nonblocking(true)
        .and_then(|()| tokio::net::TcpListener::from_std(listener))
    {
        Ok(listener) => listener,
        Err(err) => {
            log::error!("proxy listener: {err}");
            return;
        }
    };
    let cors = CorsLayer::new()
        .allow_origin(AllowOrigin::list(ORIGINS.map(HeaderValue::from_static)))
        .allow_methods(AllowMethods::mirror_request())
        .allow_headers(AllowHeaders::mirror_request());
    let proxy = Proxy {
        remote,
        token: Arc::new(token),
    };
    let app = Router::new()
        .route("/ws", any(websocket))
        .fallback(forward)
        .layer(cors)
        .with_state(proxy);
    if let Err(err) = axum::serve(listener, app).await {
        log::error!("proxy stopped: {err}");
    }
}
