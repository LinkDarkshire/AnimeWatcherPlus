//! Where the library lives: in the app's own core ("local") or on a server.
//! Stored as connection.json in the app's config directory and read once at
//! start -- switching takes a restart.

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Serialize, Deserialize, Clone, Copy, Default, PartialEq, Eq, Debug)]
#[serde(rename_all = "snake_case")]
pub enum Mode {
    #[default]
    Local,
    Server,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct ServerConfig {
    pub name: String,
    /// The API in the server's LAN, e.g. http://192.168.1.10:8784.
    pub lan_url: String,
    /// The LAN-only pairing port, e.g. http://192.168.1.10:8785.
    pub pairing_url: String,
    /// The API through the reverse proxy, e.g. https://awp.example.com.
    #[serde(default)]
    pub internet_url: Option<String>,
    pub device_id: i64,
}

#[derive(Serialize, Deserialize, Clone, Default, Debug)]
pub struct ConnectionConfig {
    #[serde(default)]
    pub mode: Mode,
    /// The paired server; may be set while still in local mode (paired,
    /// not yet switched over).
    #[serde(default)]
    pub server: Option<ServerConfig>,
}

pub fn config_file(config_dir: &Path) -> PathBuf {
    config_dir.join("connection.json")
}

pub fn load(path: &Path) -> ConnectionConfig {
    let mut config: ConnectionConfig = std::fs::read_to_string(path)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default();
    if config.server.is_none() {
        config.mode = Mode::Local;
    }
    config
}

pub fn save(path: &Path, config: &ConnectionConfig) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(config).map_err(|e| e.to_string())?;
    let partial = path.with_extension("json.part");
    std::fs::write(&partial, text).map_err(|e| e.to_string())?;
    std::fs::rename(&partial, path).map_err(|e| e.to_string())
}

/// The local core's data directory -- the same rule as
/// core/app/config.py's `_default_data_dir` (and AWP_DATA_DIR wins there too).
pub fn core_data_dir() -> Option<PathBuf> {
    if let Some(dir) = std::env::var_os("AWP_DATA_DIR") {
        return Some(PathBuf::from(dir));
    }
    let base = if cfg!(windows) {
        std::env::var_os("APPDATA").map(PathBuf::from)
    } else {
        std::env::var_os("XDG_DATA_HOME")
            .filter(|v| !v.is_empty())
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".local").join("share")))
    }?;
    Some(base.join("AnimeWatcherPlus"))
}
