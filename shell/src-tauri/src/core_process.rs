//! Desktop only: the app's own Python core, started and supervised by the
//! shell.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
#[cfg(debug_assertions)]
use std::path::PathBuf;
#[cfg(debug_assertions)]
use std::process::Command;
use std::sync::Mutex;
use std::time::Duration;

/// Starts and supervises the Python core: generates a per-session bearer
/// token, starts the core on a random free port, waits for `/health`, and
/// hands port and token to the frontend. With a server as the data source
/// no core runs here; the UI talks to `proxy` instead (same port/token
/// handshake). Debug builds run the core with
/// `core/.venv`'s Python; release builds start the bundled PyInstaller
/// executable (see core/core.spec).
pub enum CoreChild {
    Dev(std::process::Child),
    Sidecar(tauri_plugin_shell::process::CommandChild),
}

impl CoreChild {
    pub fn kill(self) {
        match self {
            CoreChild::Dev(mut child) => {
                let _ = child.kill();
                let _ = child.wait();
            }
            CoreChild::Sidecar(child) => {
                let _ = child.kill();
            }
        }
    }
}

/// The running core, if any. Global rather than app state: it has to be
/// stopped on every way out -- normal exit, but also `AppHandle::restart`
/// (switching data source, after an update), which ends the process without
/// any run event, and before the updater runs its installer.
static CORE: Mutex<Option<CoreChild>> = Mutex::new(None);

pub fn adopt(child: CoreChild) {
    *CORE.lock().unwrap() = Some(child);
}

pub fn stop() {
    if let Some(child) = CORE.lock().unwrap().take() {
        child.kill();
    }
}

pub fn find_free_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("failed to bind ephemeral port");
    listener.local_addr().expect("no local addr").port()
}

#[cfg(debug_assertions)]
fn core_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("core")
}

#[cfg(debug_assertions)]
fn python_executable(core_dir: &std::path::Path) -> PathBuf {
    if cfg!(windows) {
        core_dir.join(".venv").join("Scripts").join("python.exe")
    } else {
        core_dir.join(".venv").join("bin").join("python")
    }
}

#[cfg(debug_assertions)]
pub fn spawn_core(_app: &tauri::AppHandle, port: u16, token: &str) -> CoreChild {
    let core_dir = core_dir();
    let python = python_executable(&core_dir);
    let child = Command::new(python)
        .args([
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
        ])
        .current_dir(&core_dir)
        .env("AWP_SIDECAR_TOKEN", token)
        // The core ends itself if this process goes away without stopping it (crash).
        .env("AWP_PARENT_PID", std::process::id().to_string())
        .spawn()
        .expect("failed to spawn AnimeWatcherPlus core (is core/.venv set up? see README)");
    CoreChild::Dev(child)
}

#[cfg(not(debug_assertions))]
pub fn spawn_core(app: &tauri::AppHandle, port: u16, token: &str) -> CoreChild {
    use tauri_plugin_shell::ShellExt;
    let (_rx, child) = app
        .shell()
        .sidecar("core")
        .expect("failed to resolve bundled core sidecar binary")
        .args(["--host", "127.0.0.1", "--port", &port.to_string()])
        .env("AWP_SIDECAR_TOKEN", token)
        .env("AWP_PARENT_PID", std::process::id().to_string())
        .spawn()
        .expect("failed to spawn AnimeWatcherPlus core sidecar");
    CoreChild::Sidecar(child)
}

/// Polls `/health` over a raw TCP connection (no extra HTTP-client dependency
/// needed for a single GET) until the core answers or the timeout elapses.
pub fn wait_for_health(port: u16, timeout: Duration) -> bool {
    let deadline = std::time::Instant::now() + timeout;
    while std::time::Instant::now() < deadline {
        if let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) {
            let request = "GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
            if stream.write_all(request.as_bytes()).is_ok() {
                let mut response = String::new();
                if stream.read_to_string(&mut response).is_ok() && response.contains("200") {
                    return true;
                }
            }
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    false
}
