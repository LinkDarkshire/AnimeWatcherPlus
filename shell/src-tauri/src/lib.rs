use rand::RngCore;
use serde::Serialize;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process::Command;
use std::sync::Mutex;
use std::time::Duration;
use tauri::{Manager, RunEvent, State};

#[cfg(debug_assertions)]
use std::path::PathBuf;

/// Sidecar supervisor (Kap. 4.3 / 8): generates a per-session bearer token,
/// spawns the Python core with a random free port, waits for `/health`, and
/// exposes the connection info to the frontend. In debug builds this
/// launches `core/.venv`'s interpreter directly (the dev workflow); in
/// release builds it spawns the PyInstaller-bundled `externalBin` sidecar
/// via tauri-plugin-shell instead (see build.bat / core/core.spec).
enum CoreChild {
    Dev(std::process::Child),
    Sidecar(tauri_plugin_shell::process::CommandChild),
}

impl CoreChild {
    fn kill(self) {
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

struct CoreProcess {
    child: Mutex<Option<CoreChild>>,
}

#[derive(Serialize, Clone)]
struct ConnectionInfo {
    port: u16,
    token: String,
}

fn find_free_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("failed to bind ephemeral port");
    listener.local_addr().expect("no local addr").port()
}

fn generate_token() -> String {
    let mut bytes = [0u8; 32]; // 256-bit token (Kap. 8)
    rand::thread_rng().fill_bytes(&mut bytes);
    bytes.iter().map(|b| format!("{:02x}", b)).collect()
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
fn spawn_core(_app: &tauri::AppHandle, port: u16, token: &str) -> CoreChild {
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
        .spawn()
        .expect("failed to spawn AnimeWatcherPlus core (is core/.venv set up? see README)");
    CoreChild::Dev(child)
}

#[cfg(not(debug_assertions))]
fn spawn_core(app: &tauri::AppHandle, port: u16, token: &str) -> CoreChild {
    use tauri_plugin_shell::ShellExt;
    let (_rx, child) = app
        .shell()
        .sidecar("core")
        .expect("failed to resolve bundled core sidecar binary")
        .args(["--host", "127.0.0.1", "--port", &port.to_string()])
        .env("AWP_SIDECAR_TOKEN", token)
        .spawn()
        .expect("failed to spawn AnimeWatcherPlus core sidecar");
    CoreChild::Sidecar(child)
}

/// Polls `/health` over a raw TCP connection (no extra HTTP-client dependency
/// needed for a single GET) until the core answers or the timeout elapses.
fn wait_for_health(port: u16, timeout: Duration) -> bool {
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

#[tauri::command]
fn get_connection_info(state: State<ConnectionInfo>) -> ConnectionInfo {
    state.inner().clone()
}

/// Reveals an anime's directory in the OS's native file manager, so a
/// misidentified/duplicate entry can be inspected or fixed by hand without
/// re-typing its (often long, network-share) path.
#[tauri::command]
fn open_folder(path: String) -> Result<(), String> {
    let result = if cfg!(target_os = "windows") {
        Command::new("explorer").arg(&path).spawn()
    } else if cfg!(target_os = "macos") {
        Command::new("open").arg(&path).spawn()
    } else {
        Command::new("xdg-open").arg(&path).spawn()
    };
    result.map(|_| ()).map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .invoke_handler(tauri::generate_handler![get_connection_info, open_folder])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // Spawning the core here (rather than before the builder exists,
            // as before) is what the release path requires: resolving the
            // bundled sidecar binary via tauri-plugin-shell needs a live
            // AppHandle, which only exists once the app is being built.
            let port = find_free_port();
            let token = generate_token();
            let child = spawn_core(app.handle(), port, &token);
            if !wait_for_health(port, Duration::from_secs(20)) {
                log::warn!("core did not answer /health within 20s; continuing anyway");
            }

            app.manage(ConnectionInfo { port, token });
            app.manage(CoreProcess {
                child: Mutex::new(Some(child)),
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                let state = app_handle.state::<CoreProcess>();
                let mut guard = state.child.lock().unwrap();
                if let Some(child) = guard.take() {
                    child.kill();
                }
            }
        });
}
