from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db
from app.config import Settings
from app.main import create_app
from app.security import tls
from app.security.keys import auth_message
from app.services.jobs import EventBus
from app.state import AppState

API, PAIR = "http://core:8784", "http://core:8785"
PAIRING_PROOF_VECTOR = "m4cEA6CTmxd3dKZ2gFglM1kSzoiQ9w6GWJx6O+QIB3M="


class Device:
    """A test device with its own key pair, like the real apps."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.key = Ed25519PrivateKey.generate()
        self.public_key = base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        self.id: int | None = None

    def sign(self, device_id: int, nonce: str) -> str:
        return base64.b64encode(self.key.sign(auth_message(device_id, nonce))).decode()


def _pairing(app, code: str, name: str, public_key: str, fingerprint: str | None = None) -> dict:
    """What a device sends to pair: proof of the code, bound to the
    certificate it saw (by default the server's own)."""
    fingerprint = fingerprint or tls.server_fingerprint(app.state.awp.settings)
    return {"proof": tls.pairing_proof(code, fingerprint, name, public_key), "name": name, "public_key": public_key}


def _make_app(db_session, tmp_path, **settings):
    settings = Settings(data_dir=tmp_path, **settings)
    app = create_app(settings)
    app.state.awp = AppState(
        settings=settings,
        event_bus=EventBus(),
        job_queue=MagicMock(),
        provider_registry=MagicMock(),
        scanner=MagicMock(),
    )

    async def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    return app


@pytest.fixture
def server(db_session, tmp_path):
    return _make_app(db_session, tmp_path, mode="server")


def _client(app, base: str) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url=base)


async def _login(app, device: Device) -> str:
    async with _client(app, API) as api:
        nonce = (await api.post("/api/v1/auth/challenge", json={"device_id": device.id})).json()["nonce"]
        response = await api.post(
            "/api/v1/auth/token",
            json={"device_id": device.id, "nonce": nonce, "signature": device.sign(device.id, nonce)},
        )
        assert response.status_code == 200, response.text
        return response.json()["token"]


async def _setup_admin(app) -> tuple[Device, str]:
    admin = Device("Desktop")
    code = app.state.awp.security.new_setup_code()
    async with _client(app, PAIR) as pair:
        response = await pair.post("/pair/setup", json=_pairing(app, code, admin.name, admin.public_key))
    assert response.status_code == 200, response.text
    admin.id = response.json()["device_id"]
    return admin, await _login(app, admin)


# --- ports ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pairing_only_on_its_port_and_nothing_else_there(server) -> None:
    async with _client(server, API) as api, _client(server, PAIR) as pair:
        assert (await api.get("/pair/info")).status_code == 404
        assert (await pair.get("/pair/info")).json()["setup_required"] is True
        assert (await pair.get("/api/v1/animes")).status_code == 404
        assert (await pair.post("/api/v1/auth/challenge", json={"device_id": 1})).status_code == 404
        assert (await api.get("/health")).status_code == 200
        assert (await pair.get("/health")).status_code == 200


# --- first device ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_code_pairs_one_admin_once(server) -> None:
    security = server.state.awp.security
    code = security.new_setup_code()
    device = Device("Desktop")
    async with _client(server, PAIR) as pair:
        wrong = await pair.post("/pair/setup", json=_pairing(server, "AAAA-AAAA-AAAA", "x", device.public_key))
        assert wrong.status_code == 401
        ok = await pair.post("/pair/setup", json=_pairing(server, code, "Desktop", device.public_key))
        assert ok.status_code == 200 and ok.json()["is_admin"] is True
        again = await pair.post("/pair/setup", json=_pairing(server, code, "y", Device("y").public_key))
        assert again.status_code == 409


@pytest.mark.asyncio
async def test_setup_code_dies_after_too_many_wrong_guesses(server) -> None:
    code = server.state.awp.security.new_setup_code()
    device = Device("Desktop")
    async with _client(server, PAIR) as pair:
        for _ in range(5):
            await pair.post("/pair/setup", json=_pairing(server, "WRONG", "x", device.public_key))
        late = await pair.post("/pair/setup", json=_pairing(server, code, "x", device.public_key))
    assert late.status_code == 401


# --- login -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_with_signature_and_what_it_rejects(server) -> None:
    admin, token = await _setup_admin(server)
    other = Device("Thief")
    async with _client(server, API) as api:
        assert (await api.get("/api/v1/animes")).status_code == 401
        me = await api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.json()["is_admin"] is True and me.json()["device_name"] == "Desktop"

        # Signed with the wrong key.
        nonce = (await api.post("/api/v1/auth/challenge", json={"device_id": admin.id})).json()["nonce"]
        bad = await api.post(
            "/api/v1/auth/token", json={"device_id": admin.id, "nonce": nonce, "signature": other.sign(admin.id, nonce)}
        )
        assert bad.status_code == 401
        # The nonce was used up by that attempt, even with a correct signature now.
        replay = await api.post(
            "/api/v1/auth/token", json={"device_id": admin.id, "nonce": nonce, "signature": admin.sign(admin.id, nonce)}
        )
        assert replay.status_code == 401
        # A nonce issued for another device doesn't work either.
        assert (await api.post("/api/v1/auth/challenge", json={"device_id": 999})).status_code == 401


# --- further devices --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_join_needs_code_and_admin_approval(server) -> None:
    _, admin_token = await _setup_admin(server)
    auth = {"Authorization": f"Bearer {admin_token}"}
    phone = Device("Pixel")
    async with _client(server, PAIR) as pair:
        code = (await pair.post("/pair/codes", headers=auth)).json()["code"]
        bad = await pair.post("/pair/join", json=_pairing(server, "NOPE-NOPE", "Pixel", phone.public_key))
        assert bad.status_code == 401
        joined = await pair.post("/pair/join", json=_pairing(server, code, "Pixel", phone.public_key))
        assert joined.status_code == 200
        request_id = joined.json()["request_id"]
        # The code was single use.
        reuse = await pair.post("/pair/join", json=_pairing(server, code, "x", Device("x").public_key))
        assert reuse.status_code == 401

        assert (await pair.get(f"/pair/join/{request_id}")).json()["status"] == "pending"
        [pending] = (await pair.get("/pair/requests", headers=auth)).json()
        assert pending["name"] == "Pixel" and pending["fingerprint"] == joined.json()["fingerprint"]
        decided = await pair.post(f"/pair/requests/{request_id}", json={"approve": True}, headers=auth)
        phone.id = decided.json()["device_id"]

    phone_token = await _login(server, phone)
    async with _client(server, PAIR) as pair:
        # A normal device can't add others.
        assert (await pair.post("/pair/codes", headers={"Authorization": f"Bearer {phone_token}"})).status_code == 403


@pytest.mark.asyncio
async def test_revoked_device_is_out_at_once(server) -> None:
    admin, admin_token = await _setup_admin(server)
    auth = {"Authorization": f"Bearer {admin_token}"}
    phone = Device("Pixel")
    async with _client(server, PAIR) as pair:
        code = (await pair.post("/pair/codes", headers=auth)).json()["code"]
        request_id = (
            await pair.post("/pair/join", json=_pairing(server, code, "Pixel", phone.public_key))
        ).json()["request_id"]
        phone.id = (await pair.post(f"/pair/requests/{request_id}", json={"approve": True}, headers=auth)).json()[
            "device_id"
        ]
    phone_token = await _login(server, phone)

    async with _client(server, API) as api:
        assert (await api.delete(f"/api/v1/devices/{phone.id}", headers=auth)).status_code == 204
        assert (await api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {phone_token}"})).status_code == 401
        assert (await api.post("/api/v1/auth/challenge", json={"device_id": phone.id})).status_code == 401
        # The last admin can't lock everyone out.
        assert (await api.delete(f"/api/v1/devices/{admin.id}", headers=auth)).status_code == 409
        devices = (await api.get("/api/v1/devices", headers=auth)).json()
        assert {(d["name"], d["revoked"]) for d in devices} == {("Desktop", False), ("Pixel", True)}


@pytest.mark.asyncio
async def test_posters_need_a_token_in_server_mode(server) -> None:
    async with _client(server, API) as api:
        assert (await api.get("/api/v1/animes/1/poster")).status_code == 401
        assert (await api.get("/api/v1/animes/1/poster?token=made-up")).status_code == 401


# --- desktop mode unchanged ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_desktop_mode_has_no_pairing_and_keeps_its_token(db_session, tmp_path) -> None:
    app = _make_app(db_session, tmp_path, mode="desktop", sidecar_token="secret")
    async with _client(app, "http://127.0.0.1:8000") as api:
        assert (await api.get("/pair/info")).status_code == 404
        assert (await api.post("/api/v1/auth/challenge", json={"device_id": 1})).status_code == 404
        assert (await api.get("/api/v1/animes")).status_code == 401
        assert (await api.get("/api/v1/animes", headers={"Authorization": "Bearer secret"})).status_code == 200
        me = await api.get("/api/v1/auth/me", headers={"Authorization": "Bearer secret"})
        assert me.json()["mode"] == "desktop"


@pytest.mark.asyncio
async def test_import_and_export_only_for_admins_in_the_lan(server) -> None:
    _, admin_token = await _setup_admin(server)
    async with _client(server, API) as api, _client(server, PAIR) as pair:
        auth = {"Authorization": f"Bearer {admin_token}"}
        # Not reachable through the internet-facing API port at all.
        assert (await api.get("/admin/export", headers=auth)).status_code == 404
        assert (await api.post("/admin/import", headers=auth, content=b"x")).status_code == 404
        # In the LAN: admin only.
        assert (await pair.get("/admin/export")).status_code == 401
        bad_mapping = await pair.post("/admin/import?mappings=nope", headers=auth, content=b"x")
        assert bad_mapping.status_code == 422


# --- certificate binding ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pairing_through_someone_elses_certificate_fails(server) -> None:
    """A device that was talking to an impostor (who presents their own
    certificate) proves the code for the wrong certificate: refused, even
    though the code is right -- and the impostor never saw the code."""
    code = server.state.awp.security.new_setup_code()
    device = Device("Desktop")
    impostor = "ab" * 32
    async with _client(server, PAIR) as pair:
        relayed = await pair.post("/pair/setup", json=_pairing(server, code, "Desktop", device.public_key, impostor))
        assert relayed.status_code == 401
        assert code not in relayed.text
        direct = await pair.post("/pair/setup", json=_pairing(server, code, "Desktop", device.public_key))
        assert direct.status_code == 200


@pytest.mark.asyncio
async def test_proof_covers_name_and_key(server) -> None:
    code = server.state.awp.security.new_setup_code()
    device = Device("Desktop")
    payload = _pairing(server, code, "Desktop", device.public_key)
    async with _client(server, PAIR) as pair:
        renamed = await pair.post("/pair/setup", json={**payload, "name": "Evil"})
        assert renamed.status_code == 401
        swapped = await pair.post("/pair/setup", json={**payload, "public_key": Device("other").public_key})
        assert swapped.status_code == 401


def test_pairing_proof_vector() -> None:
    """Fixed values, checked by the app's Rust implementation too
    (shell/src-tauri/src/tls.rs)."""
    proof = tls.pairing_proof(
        "ABCD-EFGH",
        "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff",
        "Pixel",
        "11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo=",
    )
    assert proof == PAIRING_PROOF_VECTOR


def test_server_certificate_is_made_once(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path, mode="server")
    first = tls.server_fingerprint(settings)
    cert, key = tls.cert_paths(settings)
    assert cert.exists() and key.stat().st_mode & 0o777 == 0o600
    assert tls.server_fingerprint(settings) == first and len(first) == 64


@pytest.mark.asyncio
async def test_server_answers_carry_security_headers(server) -> None:
    async with _client(server, API) as api:
        response = await api.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
