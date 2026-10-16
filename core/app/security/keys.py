from __future__ import annotations

import base64
import binascii

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

# What a device signs to log in: a fixed prefix (so a signature made for
# anything else can never be replayed here), its id and the server's nonce.
AUTH_MESSAGE_PREFIX = b"AnimeWatcherPlus auth v1\n"


class InvalidKey(ValueError):
    pass


def b64decode(value: str) -> bytes:
    """Base64 in either alphabet (standard or URL-safe), padding optional."""
    value = value.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(value + "=" * (-len(value) % 4), validate=True)


def parse_public_key(value: str) -> Ed25519PublicKey:
    """A raw 32-byte Ed25519 public key, base64."""
    try:
        raw = b64decode(value)
    except (binascii.Error, ValueError) as exc:
        raise InvalidKey("Öffentlicher Schlüssel ist kein gültiges Base64") from exc
    if len(raw) != 32:
        raise InvalidKey("Öffentlicher Schlüssel muss 32 Bytes lang sein (Ed25519)")
    return Ed25519PublicKey.from_public_bytes(raw)


def normalize_public_key(value: str) -> str:
    """The canonical spelling stored in the database (standard base64)."""
    key = parse_public_key(value)
    return base64.b64encode(key.public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def auth_message(device_id: int, nonce: str) -> bytes:
    return AUTH_MESSAGE_PREFIX + f"{device_id}\n{nonce}".encode()


def verify_signature(public_key: str, message: bytes, signature_b64: str) -> bool:
    try:
        signature = b64decode(signature_b64)
        parse_public_key(public_key).verify(signature, message)
    except (InvalidSignature, InvalidKey, binascii.Error, ValueError):
        return False
    return True
