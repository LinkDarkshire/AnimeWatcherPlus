//! Desktop: updating the app itself. Normally to the latest release; with a
//! server as the data source to exactly the server's version, so app and
//! server always speak the same API -- updating the server is enough, the
//! apps follow when they connect.

use std::time::Duration;
use tauri::{AppHandle, Url};
use tauri_plugin_updater::{Update, UpdaterExt};

/// The release manifest of one version: the configured endpoint
/// (".../releases/latest/download/latest.json") pointed at that tag.
pub(crate) fn tagged_endpoint(latest: &str, version: &str) -> Result<String, String> {
    if version.is_empty() || !version.chars().all(|c| c.is_ascii_alphanumeric() || ".-+".contains(c)) {
        return Err(format!("Ungültige Version: {version}"));
    }
    let tagged = latest.replace("/releases/latest/download/", &format!("/releases/download/v{version}/"));
    if tagged == latest {
        return Err("Update-Adresse hat nicht die erwartete Form".into());
    }
    Ok(tagged)
}

fn manifest_for(app: &AppHandle, version: &str) -> Result<Url, String> {
    let latest = app
        .config()
        .plugins
        .0
        .get("updater")
        .and_then(|u| u.get("endpoints"))
        .and_then(|e| e.get(0))
        .and_then(|e| e.as_str())
        .ok_or("Kein Update-Server konfiguriert")?;
    Url::parse(&tagged_endpoint(latest, version)?).map_err(|e| e.to_string())
}

async fn find(app: &AppHandle, version: Option<&str>) -> Result<Option<Update>, String> {
    let mut builder = app.updater_builder().timeout(Duration::from_secs(15));
    if let Some(version) = version {
        builder = builder.endpoints(vec![manifest_for(app, version)?]).map_err(|e| e.to_string())?;
    }
    let updater = builder.build().map_err(|e| e.to_string())?;
    updater.check().await.map_err(|e| e.to_string())
}

/// The version an update would install (None: up to date / nothing
/// published for it). `version`: a specific one (the server's), otherwise
/// the latest release.
#[tauri::command]
pub async fn app_update_check(app: AppHandle, version: Option<String>) -> Result<Option<String>, String> {
    Ok(find(&app, version.as_deref()).await?.map(|u| u.version))
}

/// Downloads, verifies (signature) and installs the update, then restarts.
/// On Windows the installer takes over and the app ends during install.
#[tauri::command]
pub async fn app_update_install(app: AppHandle, version: Option<String>) -> Result<(), String> {
    let update = find(&app, version.as_deref())
        .await?
        .ok_or("Kein Update gefunden")?;
    let bytes = update.download(|_, _| {}, || {}).await.map_err(|e| e.to_string())?;
    // The core must not run on while the new version is installed.
    crate::core_process::stop();
    update.install(bytes).map_err(|e| e.to_string())?;
    app.restart();
}
