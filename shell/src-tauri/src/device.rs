//! The device key the app logs in to a server with: an Ed25519 key pair made
//! on this device. The server only ever sees the public half; the private
//! half stays in the OS keyring (Windows Credential Manager, macOS Keychain,
//! Secret Service on Linux), or -- where no keyring is available -- in a file
//! only this user can read. On Android that file is in the app's private
//! storage, which no other app can read, and sealed with a key from the
//! Android Keystore (keyvault.rs) -- copied off the phone, it's useless. The UI never gets the key, only
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

/// Encrypts the key file with a key the OS keeps in secure hardware
/// (Android Keystore, see keyvault.rs).
pub trait Sealer: Send + Sync {
    fn seal(&self, data: &[u8]) -> Result<Vec<u8>, String>;
    fn open(&self, sealed: &[u8]) -> Result<Vec<u8>, String>;
}

const SEALED_PREFIX: &str = "sealed1:";

pub struct DeviceKeys {
    fallback_file: PathBuf,
    sealer: Option<std::sync::Arc<dyn Sealer>>,
    key: Mutex<Option<SigningKey>>,
    // Made when pairing starts, kept only once the server accepted it.
    pending: Mutex<Option<SigningKey>>,
}

#[cfg(desktop)]
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

#[cfg(desktop)]
mod store {
    use super::{off_thread, ACCOUNT, SERVICE};

    fn entry() -> keyring::Result<keyring::Entry> {
        keyring::Entry::new(SERVICE, ACCOUNT)
    }

    /// Ok(None): no key stored. Err: no usable keyring.
    pub fn get() -> Result<Option<String>, String> {
        match off_thread(|| entry().and_then(|e| e.get_password())) {
            Ok(secret) => Ok(Some(secret)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(e) => Err(e.to_string()),
        }
    }

    pub fn set(secret: String) -> Result<(), String> {
        off_thread(move || entry().and_then(|e| e.set_password(&secret))).map_err(|e| e.to_string())
    }

    pub fn delete() {
        let _ = off_thread(|| entry().and_then(|e| e.delete_credential()));
    }
}

#[cfg(mobile)]
mod store {
    // No OS keyring here: the private file is the store (see the module docs).
    pub fn get() -> Result<Option<String>, String> {
        Err("no keyring on this platform".into())
    }

    pub fn set(_secret: String) -> Result<(), String> {
        Err("no keyring on this platform".into())
    }

    pub fn delete() {}
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
    pub fn new(config_dir: &Path, sealer: Option<std::sync::Arc<dyn Sealer>>) -> Self {
        DeviceKeys {
            fallback_file: config_dir.join("device-key"),
            sealer,
            key: Mutex::new(None),
            pending: Mutex::new(None),
        }
    }

    fn load(&self) -> Result<SigningKey, String> {
        let mut cached = self.key.lock().unwrap();
        if let Some(key) = cached.as_ref() {
            return Ok(key.clone());
        }
        let from_keyring = match store::get() {
            Ok(secret) => secret.and_then(|s| decode(&s)),
            Err(e) => {
                log::info!("keyring unavailable: {e}");
                None
            }
        };
        let key = match from_keyring {
            Some(key) => key,
            None => self
                .read_file()?
                .ok_or("Kein Geräteschlüssel vorhanden – das Gerät neu mit dem Server koppeln")?,
        };
        *cached = Some(key.clone());
        Ok(key)
    }

    fn read_file(&self) -> Result<Option<SigningKey>, String> {
        let Ok(content) = std::fs::read_to_string(&self.fallback_file) else {
            return Ok(None);
        };
        match (content.trim().strip_prefix(SEALED_PREFIX), &self.sealer) {
            (Some(sealed), Some(sealer)) => {
                let sealed = STANDARD.decode(sealed).map_err(|e| e.to_string())?;
                let secret = sealer.open(&sealed)?;
                Ok(decode(&String::from_utf8_lossy(&secret)))
            }
            (Some(_), None) => Err("Geräteschlüssel versiegelt, aber kein Tresor verfügbar".into()),
            (None, _) => {
                let key = decode(&content);
                if let (Some(key), Some(_)) = (&key, &self.sealer) {
                    // Written before sealing existed: seal it now.
                    self.write_file(&STANDARD.encode(key.to_bytes()))?;
                }
                Ok(key)
            }
        }
    }

    fn write_file(&self, secret: &str) -> Result<(), String> {
        match &self.sealer {
            // Fail closed: never fall back to an unsealed key where sealing exists.
            Some(sealer) => {
                let sealed = sealer.seal(secret.as_bytes())?;
                write_private_file(&self.fallback_file, &format!("{SEALED_PREFIX}{}", STANDARD.encode(sealed)))
            }
            None => write_private_file(&self.fallback_file, secret),
        }
    }

    fn store(&self, key: &SigningKey) -> Result<(), String> {
        let secret = STANDARD.encode(key.to_bytes());
        match store::set(secret.clone()) {
            Ok(()) => {
                let _ = std::fs::remove_file(&self.fallback_file);
                Ok(())
            }
            Err(e) => {
                log::info!("keyring unavailable, keeping the device key in a private file: {e}");
                self.write_file(&secret)
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
        store::delete();
        let _ = std::fs::remove_file(&self.fallback_file);
    }

    /// Signs a server's login challenge (base64 signature).
    pub fn sign_auth(&self, device_id: i64, nonce: &str) -> Result<String, String> {
        let key = self.load()?;
        let message = format!("{AUTH_PREFIX}{device_id}\n{nonce}");
        Ok(STANDARD.encode(key.sign(message.as_bytes()).to_bytes()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    /// Stands in for the Android Keystore: XOR with a fixed byte.
    struct FakeVault;

    impl Sealer for FakeVault {
        fn seal(&self, data: &[u8]) -> Result<Vec<u8>, String> {
            Ok(data.iter().map(|b| b ^ 0x5a).collect())
        }
        fn open(&self, sealed: &[u8]) -> Result<Vec<u8>, String> {
            self.seal(sealed)
        }
    }

    fn dir() -> PathBuf {
        let dir = std::env::temp_dir().join(format!("awp-device-test-{}", rand::random::<u64>()));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn key_file_is_sealed_and_reads_back() {
        let dir = dir();
        let keys = DeviceKeys::new(&dir, Some(Arc::new(FakeVault)));
        let key = SigningKey::generate(&mut OsRng);
        let secret = STANDARD.encode(key.to_bytes());
        keys.write_file(&secret).unwrap();

        let content = std::fs::read_to_string(dir.join("device-key")).unwrap();
        assert!(content.starts_with(SEALED_PREFIX));
        assert!(!content.contains(&secret));
        assert_eq!(keys.read_file().unwrap().unwrap().to_bytes(), key.to_bytes());

        // Without the vault (e.g. the file copied elsewhere) it can't be read.
        assert!(DeviceKeys::new(&dir, None).read_file().is_err());
    }

    #[test]
    fn an_unsealed_key_file_gets_sealed() {
        let dir = dir();
        let key = SigningKey::generate(&mut OsRng);
        write_private_file(&dir.join("device-key"), &STANDARD.encode(key.to_bytes())).unwrap();

        let keys = DeviceKeys::new(&dir, Some(Arc::new(FakeVault)));
        assert_eq!(keys.read_file().unwrap().unwrap().to_bytes(), key.to_bytes());
        assert!(std::fs::read_to_string(dir.join("device-key")).unwrap().starts_with(SEALED_PREFIX));
    }
}
