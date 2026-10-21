//! Android: seals the device key file with an AES key from the Android
//! Keystore (KeyVaultPlugin.kt in the Android project), so it can only be
//! read on this phone.

use crate::device::Sealer;
use base64::{engine::general_purpose::STANDARD, Engine};
use serde::Deserialize;
use serde_json::json;
use tauri::plugin::{Builder, PluginHandle, TauriPlugin};
use tauri::{Manager, Wry};

pub struct KeyVault(PluginHandle<Wry>);

#[derive(Deserialize)]
struct Data {
    data: String,
}

impl KeyVault {
    fn call(&self, command: &str, data: &[u8]) -> Result<Vec<u8>, String> {
        let out: Data = self
            .0
            .run_mobile_plugin(command, json!({ "data": STANDARD.encode(data) }))
            .map_err(|e| format!("Android Keystore: {e}"))?;
        STANDARD.decode(out.data).map_err(|e| e.to_string())
    }
}

impl Sealer for KeyVault {
    fn seal(&self, data: &[u8]) -> Result<Vec<u8>, String> {
        self.call("seal", data)
    }

    fn open(&self, sealed: &[u8]) -> Result<Vec<u8>, String> {
        self.call("open", sealed)
    }
}

pub fn init() -> TauriPlugin<Wry> {
    Builder::new("keyvault")
        .setup(|app, api| {
            let handle = api.register_android_plugin("com.animewatcherplus.app", "KeyVaultPlugin")?;
            app.manage(std::sync::Arc::new(KeyVault(handle)));
            Ok(())
        })
        .build()
}
