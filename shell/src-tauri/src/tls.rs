//! TLS to the server. In the LAN the server has its own self-signed
//! certificate: the app pins its fingerprint when pairing, and the pin is
//! authenticated by the pairing code (see `pairing_proof`; the server side is
//! core/app/security/tls.py). From the internet the reverse proxy's regular
//! certificate is checked against the usual root CAs (webpki-roots, the same
//! on every platform -- Android's system verifier would need extra Java parts).

use base64::{engine::general_purpose::STANDARD, Engine};
use hmac::{Hmac, Mac};
use rustls::client::danger::{HandshakeSignatureValid, ServerCertVerified, ServerCertVerifier};
use rustls::crypto::{verify_tls12_signature, verify_tls13_signature, CryptoProvider};
use rustls::pki_types::{CertificateDer, ServerName, UnixTime};
use rustls::{ClientConfig, DigitallySignedStruct, SignatureScheme};
use sha2::{Digest, Sha256};
use std::sync::{Arc, Mutex};
use std::time::Duration;

const PAIR_PROOF_PREFIX: &[u8] = b"AnimeWatcherPlus pair v1\n";

fn provider() -> Arc<CryptoProvider> {
    Arc::new(rustls::crypto::aws_lc_rs::default_provider())
}

/// SHA-256 of the certificate (DER), lowercase hex.
pub fn fingerprint(cert: &[u8]) -> String {
    Sha256::digest(cert).iter().map(|b| format!("{b:02x}")).collect()
}

/// Accepts exactly the pinned certificate -- or, without a pin (finding a
/// server before pairing), any, remembering which one it saw.
#[derive(Debug)]
pub struct PinnedVerifier {
    pin: Option<String>,
    seen: Mutex<Option<String>>,
    provider: Arc<CryptoProvider>,
}

impl PinnedVerifier {
    pub fn seen(&self) -> Option<String> {
        self.seen.lock().unwrap().clone()
    }
}

impl ServerCertVerifier for PinnedVerifier {
    fn verify_server_cert(
        &self,
        end_entity: &CertificateDer<'_>,
        _intermediates: &[CertificateDer<'_>],
        _server_name: &ServerName<'_>,
        _ocsp_response: &[u8],
        _now: UnixTime,
    ) -> Result<ServerCertVerified, rustls::Error> {
        let seen = fingerprint(end_entity.as_ref());
        *self.seen.lock().unwrap() = Some(seen.clone());
        match &self.pin {
            Some(pin) if *pin != seen => Err(rustls::Error::General(
                "Das Zertifikat des Servers hat sich geändert -- das Gerät neu koppeln".into(),
            )),
            _ => Ok(ServerCertVerified::assertion()),
        }
    }

    // The handshake signatures are still checked properly: whoever answers
    // must hold the pinned certificate's private key.
    fn verify_tls12_signature(
        &self,
        message: &[u8],
        cert: &CertificateDer<'_>,
        dss: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, rustls::Error> {
        verify_tls12_signature(message, cert, dss, &self.provider.signature_verification_algorithms)
    }

    fn verify_tls13_signature(
        &self,
        message: &[u8],
        cert: &CertificateDer<'_>,
        dss: &DigitallySignedStruct,
    ) -> Result<HandshakeSignatureValid, rustls::Error> {
        verify_tls13_signature(message, cert, dss, &self.provider.signature_verification_algorithms)
    }

    fn supported_verify_schemes(&self) -> Vec<SignatureScheme> {
        self.provider.signature_verification_algorithms.supported_schemes()
    }
}

pub fn pinned_verifier(pin: Option<String>) -> Arc<PinnedVerifier> {
    Arc::new(PinnedVerifier {
        pin,
        seen: Mutex::new(None),
        provider: provider(),
    })
}

pub fn pinned_config(verifier: Arc<PinnedVerifier>) -> Arc<ClientConfig> {
    Arc::new(
        ClientConfig::builder_with_provider(provider())
            .with_safe_default_protocol_versions()
            .expect("TLS versions")
            .dangerous()
            .with_custom_certificate_verifier(verifier)
            .with_no_client_auth(),
    )
}

pub fn public_config() -> Arc<ClientConfig> {
    let roots = rustls::RootCertStore {
        roots: webpki_roots::TLS_SERVER_ROOTS.to_vec(),
    };
    Arc::new(
        ClientConfig::builder_with_provider(provider())
            .with_safe_default_protocol_versions()
            .expect("TLS versions")
            .with_root_certificates(roots)
            .with_no_client_auth(),
    )
}

fn client_with(config: Arc<ClientConfig>) -> reqwest::Client {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(8))
        .use_preconfigured_tls((*config).clone())
        .build()
        .expect("failed to build HTTP client")
}

/// For the server's LAN addresses: only the pinned certificate.
pub fn pinned_client(pin: &str) -> reqwest::Client {
    client_with(pinned_config(pinned_verifier(Some(pin.to_owned()))))
}

/// For finding a server before pairing: any certificate; `verifier.seen()`
/// tells which one it had.
pub fn capturing_client() -> (reqwest::Client, Arc<PinnedVerifier>) {
    let verifier = pinned_verifier(None);
    (client_with(pinned_config(verifier.clone())), verifier)
}

/// For the internet address (reverse proxy) and anything else public.
pub fn public_client() -> reqwest::Client {
    client_with(public_config())
}

fn normalize_code(code: &str) -> String {
    code.chars()
        .filter(|c| c.is_alphanumeric())
        .flat_map(char::to_uppercase)
        .collect()
}

/// Proof of knowing the pairing code, bound to the certificate seen, this
/// device's name and key -- sent instead of the code. Slow on purpose
/// (scrypt): run it off the async runtime.
pub fn pairing_proof(code: &str, cert_fingerprint: &str, name: &str, public_key: &str) -> Result<String, String> {
    let fingerprint_bytes: Vec<u8> = (0..cert_fingerprint.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(cert_fingerprint.get(i..i + 2).unwrap_or(""), 16))
        .collect::<Result<_, _>>()
        .map_err(|_| "ungültiger Zertifikats-Fingerabdruck".to_owned())?;
    let mut salt = PAIR_PROOF_PREFIX.to_vec();
    salt.extend_from_slice(&fingerprint_bytes);
    let params = scrypt::Params::new(15, 8, 1, 32).map_err(|e| e.to_string())?;
    let mut key = [0u8; 32];
    scrypt::scrypt(normalize_code(code).as_bytes(), &salt, &params, &mut key).map_err(|e| e.to_string())?;
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(&key).map_err(|e| e.to_string())?;
    mac.update(PAIR_PROOF_PREFIX);
    mac.update(format!("{}\n{public_key}", name.trim()).as_bytes());
    Ok(STANDARD.encode(mac.finalize().into_bytes()))
}
