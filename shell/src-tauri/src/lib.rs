#[cfg(desktop)]
mod app_update;
mod connection;
#[cfg(desktop)]
mod core_process;
mod device;
#[cfg(target_os = "android")]
mod keyvault;
mod proxy;
mod remote;
mod server;
mod tls;
#[cfg(test)]
mod tests;

use rand::RngCore;
use std::net::TcpListener;
use std::process::Command;
use tauri::Manager;

fn generate_token() -> String {
    let mut bytes = [0u8; 32]; // 256-bit random token
    rand::thread_rng().fill_bytes(&mut bytes);
    bytes.iter().map(|b| format!("{:02x}", b)).collect()
}

/// Reveals an anime's directory in the OS's native file manager, so a
/// misidentified/duplicate entry can be inspected or fixed by hand without
/// re-typing its (often long, network-share) path.
///
/// Only ever opens an existing *directory*: on Windows `explorer <file>`
/// launches the file with its associated program, so passing anything else
/// through would turn this command into "run any executable".
#[tauri::command]
fn open_folder(path: String) -> Result<(), String> {
    // A folder on a server, reached over SMB (Linux/macOS file managers open
    // smb:// themselves). Still never anything executable: only directories
    // and smb:// addresses.
    let is_smb = path.get(..6).is_some_and(|p| p.eq_ignore_ascii_case("smb://"));
    if !is_smb && !std::path::Path::new(&path).is_dir() {
        return Err(format!("Ordner nicht gefunden: {path}"));
    }
    if is_smb && cfg!(target_os = "windows") {
        return Err("Unter Windows den Ordner als \\\\server\\freigabe angeben".into());
    }
    let result = if cfg!(target_os = "windows") {
        Command::new("explorer").arg(&path).spawn()
    } else if cfg!(target_os = "macos") {
        Command::new("open").arg(&path).spawn()
    } else {
        Command::new("xdg-open").arg(&path).spawn()
    };
    result.map(|_| ()).map_err(|e| e.to_string())
}

/// Opens a web page in the user's default browser -- for download links that
/// lead through an intermediate page (URL shortener, captcha) the user has to
/// click through by hand. Only http(s): anything else could start a local
/// program through the OS's URL handlers.
#[tauri::command]
fn open_url(url: String) -> Result<(), String> {
    let lowered = url.to_ascii_lowercase();
    if !(lowered.starts_with("http://") || lowered.starts_with("https://")) {
        return Err(format!("not a web address: {url}"));
    }
    let result = if cfg!(target_os = "windows") {
        Command::new("explorer").arg(&url).spawn()
    } else if cfg!(target_os = "macos") {
        Command::new("open").arg(&url).spawn()
    } else {
        Command::new("xdg-open").arg(&url).spawn()
    };
    result.map(|_| ()).map_err(|e| e.to_string())
}

/// Restarts the app (after switching the data source or installing an
/// update). Stops the core first: `restart` ends the process without the
/// exit event that otherwise does it.
#[tauri::command]
fn restart_app(app: tauri::AppHandle) {
    #[cfg(desktop)]
    core_process::stop();
    app.restart();
}

/// Stops the core before the updater installs a new version (on Windows the
/// installer can't replace a running core.exe, and the updater exits the
/// app without the exit event).
#[tauri::command]
fn stop_core() {
    #[cfg(desktop)]
    core_process::stop();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // WebKitGTK's DMA-BUF renderer shows a blank window with many GPU drivers
    // (NVIDIA in particular). Turned off unless the user decides otherwise.
    #[cfg(target_os = "linux")]
    if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
        std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    }

    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_opener::init());
    #[cfg(desktop)]
    let builder = builder
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build());
    #[cfg(mobile)]
    let builder = builder.plugin(tauri_plugin_barcode_scanner::init());
    #[cfg(target_os = "android")]
    let builder = builder.plugin(keyvault::init());

    let app = builder
        .invoke_handler(tauri::generate_handler![
            open_folder,
            open_url,
            server::get_connection_info,
            server::server_probe,
            server::server_pair,
            server::server_pair_status,
            server::server_set_internet_url,
            server::switch_mode,
            server::server_forget,
            server::server_pairing_call,
            server::server_push_library,
            server::server_pull_library,
            server::qr_svg,
            server::take_shared_text,
            server::server_set_folder_mappings,
            restart_app,
            stop_core,
            #[cfg(desktop)]
            app_update::app_update_check,
            #[cfg(desktop)]
            app_update::app_update_install,
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            let config_dir = app.path().app_config_dir()?;
            let cache_dir = app.path().app_cache_dir()?;
            let config = connection::load(&connection::config_file(&config_dir));
            #[cfg(target_os = "android")]
            let sealer: Option<std::sync::Arc<dyn device::Sealer>> = Some(
                app.state::<std::sync::Arc<keyvault::KeyVault>>().inner().clone() as std::sync::Arc<dyn device::Sealer>,
            );
            #[cfg(not(target_os = "android"))]
            let sealer = None;
            let keys = std::sync::Arc::new(device::DeviceKeys::new(&config_dir, sealer));
            let client = remote::http_client();
            let token = generate_token();
            // Phones have no core of their own: always a server, through the proxy.
            let mode = if cfg!(mobile) { connection::Mode::Server } else { config.mode };

            #[cfg(desktop)]
            let mut child = None;
            let mut proxy_listener = None;
            let port = match mode {
                #[cfg(desktop)]
                connection::Mode::Local => {
                    // The core is started here because locating the bundled
                    // sidecar binary needs the AppHandle, which only exists
                    // from this point.
                    let port = core_process::find_free_port();
                    child = Some(core_process::spawn_core(app.handle(), port, &token));
                    if !core_process::wait_for_health(port, std::time::Duration::from_secs(20)) {
                        log::warn!("core did not answer /health within 20s; continuing anyway");
                    }
                    port
                }
                _ => {
                    // Bound here, so the port is known before the UI asks.
                    let listener = TcpListener::bind("127.0.0.1:0")?;
                    let port = listener.local_addr()?.port();
                    proxy_listener = Some(listener);
                    port
                }
            };

            let shell = server::Shell::new(config_dir, cache_dir, config, mode, keys, client, port, token.clone());
            if let Some(listener) = proxy_listener {
                // Filled when a server is paired (on a phone possibly only later).
                let _ = shell.remote();
                tauri::async_runtime::spawn(proxy::serve(listener, shell.remote_slot(), token));
            }
            app.manage(shell);
            #[cfg(desktop)]
            if let Some(child) = child {
                core_process::adopt(child);
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|_app_handle, _event| {
        #[cfg(desktop)]
        if let tauri::RunEvent::Exit = _event {
            core_process::stop();
        }
    });
}
