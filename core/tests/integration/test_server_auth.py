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
from app.security.keys import auth_message
from app.services.jobs import EventBus
from app.state import AppState

API, PAIR = "http://core:8000", "http://core:8001"


class Device:
    """A test device with its own key pair, like the real apps."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.key = Ed25519PrivateKey.generate()
        self.public_key = base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        self.id: int | None = None

    def sign(self, device_id: int, nonce: str) -> str:
        return base64.b64encode(self.key.sign(auth_message(device_id, nonce))).decode()


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
        response = await pair.post("/pair/setup", json={"code": code, "name": admin.name, "public_key": admin.public_key})
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
        wrong = await pair.post("/pair/setup", json={"code": "AAAA-AAAA-AAAA", "name": "x", "public_key": device.public_key})
        assert wrong.status_code == 401
        ok = await pair.post("/pair/setup", json={"code": code, "name": "Desktop", "public_key": device.public_key})
        assert ok.status_code == 200 and ok.json()["is_admin"] is True
        again = await pair.post("/pair/setup", json={"code": code, "name": "y", "public_key": Device("y").public_key})
        assert again.status_code == 409


@pytest.mark.asyncio
async def test_setup_code_dies_after_too_many_wrong_guesses(server) -> None:
    code = server.state.awp.security.new_setup_code()
    device = Device("Desktop")
    async with _client(server, PAIR) as pair:
        for _ in range(5):
            await pair.post("/pair/setup", json={"code": "WRONG", "name": "x", "public_key": device.public_key})
        late = await pair.post("/pair/setup", json={"code": code, "name": "x", "public_key": device.public_key})
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
        bad = await pair.post("/pair/join", json={"code": "NOPE-NOPE", "name": "Pixel", "public_key": phone.public_key})
        assert bad.status_code == 401
        joined = await pair.post("/pair/join", json={"code": code, "name": "Pixel", "public_key": phone.public_key})
        assert joined.status_code == 200
        request_id = joined.json()["request_id"]
        # The code was single use.
        reuse = await pair.post("/pair/join", json={"code": code, "name": "x", "public_key": Device("x").public_key})
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
            await pair.post("/pair/join", json={"code": code, "name": "Pixel", "public_key": phone.public_key})
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
