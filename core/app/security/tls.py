"""The server's own TLS certificate and how devices pin it.

In the LAN, devices talk to the server directly. A self-signed certificate
encrypts that traffic; devices don't trust it because of a CA but because
they pin its fingerprint when they are paired. That pin is authenticated by
the pairing code without the code ever being sent: the device proves it knows
the code with an HMAC over the certificate fingerprint it saw (and its key
and name), keyed with a deliberately slow scrypt hash of the code. Someone
sitting between device and server (with their own certificate) can neither
make a valid proof nor brute-force the short code from a captured one within
the code's few minutes.

Devices reaching the server from the internet go through the reverse proxy
and its regular (e.g. Let's Encrypt) certificate.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
from functools import lru_cache
from pathlib import Path

import structlog
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.config import Settings
from app.security.store import normalize_code

logger = structlog.get_logger(__name__)

PAIR_PROOF_PREFIX = b"AnimeWatcherPlus pair v1\n"
# scrypt cost: ~0.1 s per guess and 32 MiB of memory -- fine for the few
# codes a pairing checks, hopeless for trying 31^8 codes in five minutes.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1


def cert_paths(settings: Settings) -> tuple[Path, Path]:
    folder = settings.data_dir / "tls"
    return folder / "server.crt", folder / "server.key"


def ensure_certificate(settings: Settings) -> tuple[Path, Path]:
    """The server's certificate and key, made on first start. Kept in the
    data directory: a new certificate means every device has to be paired
    again."""
    cert_path, key_path = cert_paths(settings)
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, settings.server_name[:64] or "AnimeWatcherPlus")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        # Pinned, not checked against a CA: the dates hardly matter.
        .not_valid_after(now + dt.timedelta(days=365 * 30))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("animewatcherplus")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    key_path.chmod(0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    logger.info("tls_certificate_created", fingerprint=fingerprint_of(cert_path))
    return cert_path, key_path


def fingerprint_of(cert_path: Path) -> str:
    """SHA-256 of the certificate (DER), lowercase hex -- what devices pin."""
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


@lru_cache(maxsize=4)
def _cached_fingerprint(cert_path: Path, mtime: float) -> str:
    return fingerprint_of(cert_path)


def server_fingerprint(settings: Settings) -> str:
    cert_path, _ = ensure_certificate(settings)
    return _cached_fingerprint(cert_path, cert_path.stat().st_mtime)


def pairing_proof(code: str, cert_fingerprint: str, name: str, public_key: str) -> str:
    """What a device sends instead of the pairing code (base64)."""
    key = hashlib.scrypt(
        normalize_code(code).encode(),
        salt=PAIR_PROOF_PREFIX + bytes.fromhex(cert_fingerprint),
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        maxmem=64 * 1024 * 1024,
        dklen=32,
    )
    message = PAIR_PROOF_PREFIX + f"{name.strip()}\n{public_key}".encode()
    return base64.b64encode(hmac.new(key, message, hashlib.sha256).digest()).decode()


def matching_code(candidates: list[str], proof: str, cert_fingerprint: str, name: str, public_key: str) -> str | None:
    """The open code the proof was made with, if any. Slow on purpose (see
    above): call it off the event loop."""
    for code in candidates:
        if hmac.compare_digest(pairing_proof(code, cert_fingerprint, name, public_key), proof):
            return code
    return None
