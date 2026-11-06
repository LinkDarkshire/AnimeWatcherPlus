from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.security import web
from tests.integration.test_server_auth import API, _make_app, _setup_admin

# The session cookie is Secure: browsers (and httpx) only send it over https.
WEB = "https://core:8784"
ORIGIN = {"origin": WEB}
FROM_THE_PAGE = {**ORIGIN, web.WEB_HEADER: "1"}


@pytest.fixture
def server(db_session, tmp_path):
    return _make_app(db_session, tmp_path, mode="server")


def _browser(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url=WEB)


async def _account(app, username: str, password: str, *, is_admin: bool = False) -> int:
    _, token = await _setup_admin(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=API) as api:
        response = await api.post(
            "/api/v1/web/accounts",
            json={"username": username, "password": password, "is_admin": is_admin},
            headers={"authorization": f"Bearer {token}"},
        )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _login(browser: AsyncClient, username: str, password: str):
    return await browser.post("/api/v1/web/login", json={"username": username, "password": password}, headers=ORIGIN)


@pytest.mark.asyncio
async def test_login_sets_a_strict_cookie_that_opens_the_api(server) -> None:
    await _account(server, "Anna", "correct horse")
    async with _browser(server) as browser:
        assert (await browser.get("/api/v1/animes")).status_code == 401
        response = await _login(browser, " anna ", "correct horse")
        assert response.status_code == 204
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie

        assert (await browser.get("/api/v1/animes")).status_code == 200
        me = (await browser.get("/api/v1/auth/me")).json()
        assert me["web_username"] == "anna" and me["is_admin"] is False and me["device_id"] is None
        # Not an admin: no account management.
        assert (await browser.get("/api/v1/web/accounts")).status_code == 403

        assert (await browser.post("/api/v1/web/logout", headers=ORIGIN)).status_code == 204
        assert (await browser.get("/api/v1/animes")).status_code == 401


@pytest.mark.asyncio
async def test_wrong_password_and_unknown_name_look_the_same(server) -> None:
    await _account(server, "anna", "correct horse")
    async with _browser(server) as browser:
        wrong = await _login(browser, "anna", "wrong password")
        unknown = await _login(browser, "bert", "wrong password")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


@pytest.mark.asyncio
async def test_too_many_failures_lock_the_name(server) -> None:
    await _account(server, "anna", "correct horse")
    async with _browser(server) as browser:
        for _ in range(web.MAX_FAILURES_PER_NAME):
            assert (await _login(browser, "anna", "guess")).status_code == 401
        # Even the right password waits now.
        assert (await _login(browser, "anna", "correct horse")).status_code == 429


@pytest.mark.asyncio
async def test_changes_need_the_page_header_and_origin(server) -> None:
    await _account(server, "anna", "correct horse")
    async with _browser(server) as browser:
        await _login(browser, "anna", "correct horse")
        entry = {"anidb_id": 1, "title": "X"}
        # A foreign page can make the browser send the cookie, but not the header.
        assert (await browser.post("/api/v1/wishlist", json=entry)).status_code == 403
        foreign = {"origin": "https://evil.example", web.WEB_HEADER: "1"}
        assert (await browser.post("/api/v1/wishlist", json=entry, headers=foreign)).status_code == 403
        assert (await browser.post("/api/v1/wishlist", json=entry, headers=FROM_THE_PAGE)).status_code != 403
        # Behind a reverse proxy that names itself as Host.
        proxied = {"origin": "https://awp.example", "x-forwarded-host": "awp.example", web.WEB_HEADER: "1"}
        assert (await browser.post("/api/v1/wishlist", json=entry, headers=proxied)).status_code != 403
        # Logging in from a foreign page doesn't work either.
        response = await browser.post(
            "/api/v1/web/login", json={"username": "anna", "password": "correct horse"}, headers=foreign
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_password_change_logs_out_other_browsers(server) -> None:
    await _account(server, "anna", "correct horse")
    async with _browser(server) as first, _browser(server) as second:
        await _login(first, "anna", "correct horse")
        await _login(second, "anna", "correct horse")
        wrong = await first.put(
            "/api/v1/web/password",
            json={"current_password": "nope", "new_password": "battery staple"},
            headers=FROM_THE_PAGE,
        )
        assert wrong.status_code == 401
        changed = await first.put(
            "/api/v1/web/password",
            json={"current_password": "correct horse", "new_password": "battery staple"},
            headers=FROM_THE_PAGE,
        )
        assert changed.status_code == 204
        assert (await first.get("/api/v1/animes")).status_code == 200
        assert (await second.get("/api/v1/animes")).status_code == 401
        assert (await _login(second, "anna", "battery staple")).status_code == 204


@pytest.mark.asyncio
async def test_deleting_an_account_ends_its_sessions(server) -> None:
    account_id = await _account(server, "admin", "correct horse", is_admin=True)
    async with _browser(server) as browser:
        await _login(browser, "admin", "correct horse")
        accounts = (await browser.get("/api/v1/web/accounts")).json()
        assert [a["username"] for a in accounts] == ["admin"]
        duplicate = await browser.post(
            "/api/v1/web/accounts", json={"username": "ADMIN", "password": "12345678"}, headers=FROM_THE_PAGE
        )
        assert duplicate.status_code == 409
        short = await browser.post(
            "/api/v1/web/accounts", json={"username": "bert", "password": "short"}, headers=FROM_THE_PAGE
        )
        assert short.status_code == 422
        response = await browser.delete(f"/api/v1/web/accounts/{account_id}", headers=FROM_THE_PAGE)
        assert response.status_code == 204
        assert (await browser.get("/api/v1/animes")).status_code == 401


@pytest.mark.asyncio
async def test_no_web_login_in_desktop_mode(db_session, tmp_path) -> None:
    app = _make_app(db_session, tmp_path, mode="desktop")
    async with _browser(app) as browser:
        assert (await _login(browser, "anna", "correct horse")).status_code == 404


@pytest.mark.asyncio
async def test_server_serves_the_page_for_ui_routes_only(db_session, tmp_path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>page</html>", encoding="utf-8")
    (dist / "assets" / "app-1234.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "favicon.png").write_bytes(b"png")
    app = _make_app(db_session, tmp_path, mode="server", web_ui_dir=dist)
    async with _browser(app) as browser:
        page = await browser.get("/animes/12")
        assert page.status_code == 200 and "page" in page.text
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        asset = await browser.get("/assets/app-1234.js")
        assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
        assert (await browser.get("/favicon.png")).content == b"png"
        # API routes stay API routes, and nothing outside the folder is served.
        assert (await browser.get("/api/v1/nothing-here")).status_code == 404
        assert (await browser.get("/api/v1/animes")).status_code == 401
        assert "page" in (await browser.get("/../test.db")).text
