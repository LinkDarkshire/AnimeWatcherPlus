//! The device key a desktop app logs in to a server with: an Ed25519 key
//! pair made on this machine. The server only ever sees the public half; the
//! private half stays in the OS keyring (Windows Credential Manager, macOS
//! Keychain, Secret Service on Linux), or -- where no keyring is available --
//! in a file only this user can read. The UI never gets the key, only
//! signatures over login challenges.

use base64::{engine::general_purpose::STANDARD, Engine};
use ed25519_dalek::{Signer, SigningKey};
use rand::rngs::OsRng;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

// Tests never touch the real key.
const SERVICE: &str = if cfg!(test) { "AnimeWatcherPlus-test" } else { "AnimeWatcherPlus" };
const ACCOUNT: &str = "device-key";
// Must match core/app/security/keys.py.
const AUTH_PREFIX: &str = "AnimeWatcherPlus auth v1\n";

pub struct DeviceKeys {
    fallback_file: PathBuf,
    key: Mutex<Option<SigningKey>>,
    // Made when pairing starts, kept only once the server accepted it.
    pending: Mutex<Option<SigningKey>>,
}

/// Runs a keyring call on a thread of its own, with a Tokio runtime of its
/// own: the Secret Service client needs one, and must not block (or nest
/// into) the app's runtime.
fn off_thread<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> T {
    std::thread::spawn(move || {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(1)
            .enable_all()
            .build()
            .expect("failed to start keyring runtime");
        let _guard = runtime.enter();
        f()
    })
    .join()
    .expect("keyring thread panicked")
}

fn keyring_entry() -> keyring::Result<keyring::Entry> {
    keyring::Entry::new(SERVICE, ACCOUNT)
}

fn decode(secret: &str) -> Option<SigningKey> {
    let bytes = STANDARD.decode(secret.trim()).ok()?;
    let seed: [u8; 32] = bytes.try_into().ok()?;
    Some(SigningKey::from_bytes(&seed))
}

fn write_private_file(path: &Path, content: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        // `mode` only applies to a new file.
        file.set_permissions(std::fs::Permissions::from_mode(0o600))
            .map_err(|e| e.to_string())?;
    }
    file.write_all(content.as_bytes()).map_err(|e| e.to_string())
}

impl DeviceKeys {
    pub fn new(config_dir: &Path) -> Self {
        DeviceKeys {
            fallback_file: config_dir.join("device-key"),
            key: Mutex::new(None),
            pending: Mutex::new(None),
        }
    }

    fn load(&self) -> Result<SigningKey, String> {
        let mut cached = self.key.lock().unwrap();
        if let Some(key) = cached.as_ref() {
            return Ok(key.clone());
        }
        let from_keyring = match off_thread(|| keyring_entry().and_then(|e| e.get_password())) {
            Ok(secret) => decode(&secret),
            Err(keyring::Error::NoEntry) => None,
            Err(e) => {
                log::warn!("keyring unavailable: {e}");
                None
            }
        };
        let key = from_keyring
            .or_else(|| {
                std::fs::read_to_string(&self.fallback_file)
                    .ok()
                    .and_then(|s| decode(&s))
            })
            .ok_or("Kein Geräteschlüssel vorhanden – das Gerät neu mit dem Server koppeln")?;
        *cached = Some(key.clone());
        Ok(key)
    }

    fn store(&self, key: &SigningKey) -> Result<(), String> {
        let secret = STANDARD.encode(key.to_bytes());
        let to_store = secret.clone();
        match off_thread(move || keyring_entry().and_then(|e| e.set_password(&to_store))) {
            Ok(()) => {
                let _ = std::fs::remove_file(&self.fallback_file);
                Ok(())
            }
            Err(e) => {
                log::warn!("keyring unavailable, keeping the device key in a private file: {e}");
                write_private_file(&self.fallback_file, &secret)
            }
        }
    }

    /// A fresh key pair for a new pairing; returns its public key (base64).
    pub fn begin_pairing(&self) -> String {
        let key = SigningKey::generate(&mut OsRng);
        let public = STANDARD.encode(key.verifying_key().as_bytes());
        *self.pending.lock().unwrap() = Some(key);
        public
    }

    /// The server accepted the pending key: it becomes this device's key.
    pub fn commit_pairing(&self) -> Result<(), String> {
        let key = self
            .pending
            .lock()
            .unwrap()
            .take()
            .ok_or("Keine Kopplung im Gange")?;
        self.store(&key)?;
        *self.key.lock().unwrap() = Some(key);
        Ok(())
    }

    pub fn forget(&self) {
        *self.key.lock().unwrap() = None;
        *self.pending.lock().unwrap() = None;
        let _ = off_thread(|| keyring_entry().and_then(|e| e.delete_credential()));
        let _ = std::fs::remove_file(&self.fallback_file);
    }

    /// Signs a server's login challenge (base64 signature).
    pub fn sign_auth(&self, device_id: i64, nonce: &str) -> Result<String, String> {
        let key = self.load()?;
        let message = format!("{AUTH_PREFIX}{device_id}\n{nonce}");
        Ok(STANDARD.encode(key.sign(message.as_bytes()).to_bytes()))
    }
}
