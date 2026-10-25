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

/// Fonts WebKit must not use. Skia in some WebKitGTK builds (e.g. the one
/// the AppImage brings along) aborts the page's render process on certain
/// glyphs of COLRv1 color fonts -- flags and other emoji in Noto's COLRv1
/// emoji font -- and the app freezes. Those fonts are hidden from the app
/// (emoji then come from Twemoji or the monochrome Noto Emoji); the rest of
/// the system's font setup stays as it is.
#[cfg(target_os = "linux")]
fn avoid_colrv1_fonts() {
    const SYSTEM_CONFIG: &str = "/etc/fonts/fonts.conf";
    if std::env::var_os("FONTCONFIG_FILE").is_some() || !std::path::Path::new(SYSTEM_CONFIG).exists() {
        return;
    }
    let Some(cache) = std::env::var_os("XDG_CACHE_HOME")
        .map(std::path::PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| std::path::PathBuf::from(home).join(".cache")))
    else {
        return;
    };
    let file = cache.join("AnimeWatcherPlus").join(FONTS_CONF_NAME);
    let content = fonts_conf(SYSTEM_CONFIG);
    let current = std::fs::read_to_string(&file).ok();
    if current.as_deref() != Some(content.as_str()) {
        if let Some(parent) = file.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        if std::fs::write(&file, &content).is_err() {
            return;
        }
    }
    std::env::set_var("FONTCONFIG_FILE", &file);
}

#[cfg(target_os = "linux")]
const FONTS_CONF_NAME: &str = "fonts-without-colrv1.conf";

#[cfg(any(target_os = "linux", test))]
pub(crate) fn fonts_conf(system_config: &str) -> String {
    format!(
        r#"<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<!-- Written by AnimeWatcherPlus: the system's font setup without COLRv1
     color fonts, which crash some WebKit builds. -->
<fontconfig>
  <include ignore_missing="yes">{system_config}</include>
  <selectfont>
    <rejectfont>
      <glob>*COLRv1*</glob>
    </rejectfont>
  </selectfont>
</fontconfig>
"#
    )
}

/// Programs the desktop provides (file manager, browser via xdg-open),
/// started without the AppImage's own environment: its GTK modules, library
/// and data paths would be inherited by the browser or file manager, which
/// then often fail to start (links and folders "do nothing").
fn desktop_command(program: &str) -> Command {
    let mut command = Command::new(program);
    // Our font setup is for our own web view only (see avoid_colrv1_fonts).
    #[cfg(target_os = "linux")]
    if std::env::var("FONTCONFIG_FILE").is_ok_and(|f| f.ends_with(FONTS_CONF_NAME)) {
        command.env_remove("FONTCONFIG_FILE");
    }
    for (key, value) in appimage_free_env(std::env::vars()) {
        match value {
            Some(value) => command.env(key, value),
            None => command.env_remove(key),
        };
    }
    command
}

/// Changes to the environment for programs started from an AppImage:
/// None removes a variable, Some sets it. Empty outside an AppImage.
pub(crate) fn appimage_free_env(
    vars: impl Iterator<Item = (String, String)>,
) -> Vec<(String, Option<String>)> {
    let vars: Vec<(String, String)> = vars.collect();
    let Some(appdir) = vars.iter().find(|(k, _)| k == "APPDIR").map(|(_, v)| v.clone()) else {
        return Vec::new();
    };
    // Set by the AppImage's runtime hooks (linuxdeploy GTK plugin, AppRun).
    const OWN: [&str; 14] = [
        "APPDIR", "APPIMAGE", "ARGV0", "OWD", "GTK_DATA_PREFIX", "GTK_THEME", "GSETTINGS_SCHEMA_DIR",
        "GI_TYPELIB_PATH", "GIO_MODULE_DIR", "GTK_EXE_PREFIX", "GTK_PATH", "GTK_IM_MODULE_FILE",
        "GDK_PIXBUF_MODULE_FILE", "GST_PLUGIN_SYSTEM_PATH",
    ];
    let mut changes: Vec<(String, Option<String>)> = OWN.iter().map(|k| (k.to_string(), None)).collect();
    // Path lists: keep the system's entries, drop the AppImage's own.
    for (key, value) in &vars {
        if matches!(key.as_str(), "XDG_DATA_DIRS" | "LD_LIBRARY_PATH" | "PATH" | "PYTHONPATH") {
            let kept: Vec<&str> = value.split(':').filter(|p| !p.is_empty() && !p.starts_with(&appdir)).collect();
            changes.push((key.clone(), if kept.is_empty() { None } else { Some(kept.join(":")) }));
        }
    }
    changes
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
        desktop_command("xdg-open").arg(&path).spawn()
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
        desktop_command("xdg-open").arg(&url).spawn()
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
    #[cfg(target_os = "linux")]
    avoid_colrv1_fonts();

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
