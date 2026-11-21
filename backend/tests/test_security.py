"""Sprint 1 security regression tests (issues #2-#7).

These flip auth/ingest settings at runtime on the in-process test server, so they
only run when conftest started the backend in this process.
"""
import asyncio
import json
import os
import sys

import pytest
import requests
import websockets

if "server" not in sys.modules:  # running against an external server
    pytest.skip("security tests need the in-process test server", allow_module_level=True)

import auth  # noqa: E402
import server  # noqa: E402,F401  (in-process test server; netvision.* below is its code)
from netvision import config  # noqa: E402
from netvision.routes import discovery  # noqa: E402

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"
WS = BASE.replace("http://", "ws://") + "/api/ws"
INGEST = "test-ingest-token"


def _ensure_user(username, role):
    # Sessions are checked against the users collection (#49), so test tokens
    # need a matching user row.
    from test_data_integrity import _db
    _db("users").update_one({"username": username}, {"$set": {"username": username, "role": role}},
                            upsert=True)
    auth._invalidate_user(username)


def bearer(role):
    _ensure_user(f"u-{role}", role)
    return {"Authorization": f"Bearer {auth.make_token(f'u-{role}', role)}"}


COLLECTOR = {"X-Ingest-Token": INGEST}


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)


@pytest.fixture
def ingest_token(monkeypatch):
    monkeypatch.setattr(auth, "INGEST_TOKEN", INGEST)


@pytest.fixture
def live_mode(monkeypatch):
    monkeypatch.setattr(config, "_SIM_OVERRIDE", False)


# ---- baseline: auth off keeps legacy behavior ---- #
def test_auth_off_everything_open():
    assert requests.get(f"{API}/devices").status_code == 200
    r = requests.post(f"{API}/ingest", json={"samples": [{"ip": "203.0.113.250"}]})
    assert r.status_code == 200


# ---- #3: /api/links/* no longer bypasses login ---- #
def test_links_reset_requires_login(auth_on):
    assert requests.post(f"{API}/links/reset").status_code == 401
    assert requests.get(f"{API}/links").status_code == 401


def test_links_reset_is_admin_only(auth_on):
    assert requests.post(f"{API}/links/reset", headers=bearer("operator")).status_code == 403
    assert requests.post(f"{API}/links/reset", headers=bearer("admin")).status_code == 200


def test_viewer_can_read(auth_on):
    assert requests.get(f"{API}/devices", headers=bearer("viewer")).status_code == 200
    assert requests.get(f"{API}/devices").status_code == 401


# ---- #4: collector keeps working with login on (via ingest token) ---- #
def test_collector_reads_with_ingest_token(auth_on, ingest_token):
    assert requests.get(f"{API}/devices", headers=COLLECTOR).status_code == 200
    assert requests.get(f"{API}/discovery", headers=COLLECTOR).status_code == 200
    assert requests.put(f"{API}/discovery", json={"last_message": "t"}, headers=COLLECTOR).status_code == 200
    dev = requests.get(f"{API}/devices", headers=COLLECTOR).json()[0]
    r = requests.patch(f"{API}/devices/{dev['id']}", json={"vendor": dev["vendor"]}, headers=COLLECTOR)
    assert r.status_code == 200


def test_collector_writes_need_token(ingest_token):
    body = {"samples": [{"ip": "203.0.113.250"}]}
    assert requests.post(f"{API}/ingest", json=body).status_code == 401
    assert requests.post(f"{API}/ingest", json=body, headers={"X-Ingest-Token": "wrong"}).status_code == 401
    assert requests.post(f"{API}/ingest", json=body, headers=COLLECTOR).status_code == 200
    assert requests.post(f"{API}/fdb", json={"ip": "203.0.113.250"}, headers=COLLECTOR).status_code == 200


def test_ingest_token_grants_nothing_else(auth_on, ingest_token):
    assert requests.post(f"{API}/mock/reset", headers=COLLECTOR).status_code == 401
    assert requests.delete(f"{API}/devices/x", headers=COLLECTOR).status_code == 401
    assert requests.get(f"{API}/audit", headers=COLLECTOR).status_code == 401


# ---- #5: destructive mock endpoints ---- #
def test_mock_reset_admin_only(auth_on):
    assert requests.post(f"{API}/mock/reset", headers=bearer("operator")).status_code == 403
    assert requests.post(f"{API}/mock/generate", headers=bearer("operator")).status_code == 403


def test_mock_endpoints_blocked_in_live_mode(live_mode):
    assert requests.post(f"{API}/mock/reset").status_code == 409
    assert requests.post(f"{API}/mock/generate").status_code == 409
    assert requests.get(f"{API}/devices").json(), "live-mode guard must not have wiped devices"


# ---- #7: SNMP community hidden from UI users ---- #
def test_discovery_community_masked(ingest_token):
    requests.put(f"{API}/discovery", json={"community": "s3cret"}, headers=COLLECTOR)
    ui = requests.get(f"{API}/discovery").json()
    assert ui["community"] == discovery.COMMUNITY_MASK
    # UI saving the form back with the mask must not overwrite the real value
    requests.put(f"{API}/discovery", json={"community": discovery.COMMUNITY_MASK, "subnet": "10.0.0.0/24"})
    assert requests.get(f"{API}/discovery", headers=COLLECTOR).json()["community"] == "s3cret"
    requests.put(f"{API}/discovery", json={"community": "public"}, headers=COLLECTOR)


# ---- #2: WebSocket requires login when auth is on ---- #
async def test_ws_rejected_without_token(auth_on):
    with pytest.raises(websockets.exceptions.InvalidStatus):
        async with websockets.connect(WS, open_timeout=5):
            pass


async def test_ws_accepts_valid_token(auth_on):
    await asyncio.to_thread(_ensure_user, "u-viewer", "viewer")  # sync DB helper, off this loop
    token = auth.make_token("u-viewer", "viewer")
    async with websockets.connect(f"{WS}?token={token}", open_timeout=5) as ws:
        msg = json.loads(await ws.recv())
        assert msg["type"] == "tick"


async def test_ws_open_when_auth_off():
    async with websockets.connect(WS, open_timeout=5) as ws:
        assert json.loads(await ws.recv())["type"] == "tick"


# ---- review findings ---- #
def test_fdb_assets_need_login_when_auth_on_without_token(auth_on):
    assert requests.post(f"{API}/fdb", json={"ip": "203.0.113.250"}).status_code == 401
    assert requests.post(f"{API}/assets", json={"assets": []}).status_code == 401
    assert requests.post(f"{API}/assets", json={"assets": []}, headers=bearer("operator")).status_code == 200
    # legacy collector writes stay open in this combination (existing Node-RED flows)
    assert requests.post(f"{API}/ingest", json={"samples": []}).status_code == 200


def test_sim_mode_toggle_cannot_unlock_reset(monkeypatch):
    monkeypatch.setattr(config, "_SIM_ENV", False)          # .env says live
    monkeypatch.setattr(config, "_SIM_OVERRIDE", True)      # runtime toggled to sim
    assert requests.post(f"{API}/mock/reset").status_code == 409
    assert requests.get(f"{API}/devices").json()


def test_non_ascii_ingest_header_is_401_not_500(auth_on, ingest_token):
    r = requests.get(f"{API}/devices", headers={"X-Ingest-Token": "\xe9".encode("latin-1")})
    assert r.status_code == 401


# ---- #27: device deletion is admin-only ---- #
def test_device_delete_admin_only(auth_on):
    r = requests.post(f"{API}/devices", headers=bearer("operator"), json={
        "name": "DEL-T", "ip": "203.0.113.77", "vendor": "t", "model": "t", "protocol": "ICMP",
        "device_type": "switch"})
    assert r.status_code == 200
    dev_id = r.json()["id"]
    assert requests.delete(f"{API}/devices/{dev_id}", headers=bearer("operator")).status_code == 403
    assert requests.delete(f"{API}/devices/{dev_id}", headers=bearer("admin")).status_code == 200


# ---- #8: CORS default never grants credentialed cross-origin access ---- #
def test_cors_wildcard_default_has_no_credentials():
    assert server.CORS_ALLOW_ALL, "test server runs with the '*' default"
    r = requests.get(f"{API}/auth/config", headers={"Origin": "http://evil.example"})
    assert r.headers.get("access-control-allow-origin") == "*"
    assert r.headers.get("access-control-allow-credentials") is None
    pre = requests.options(f"{API}/devices", headers={
        "Origin": "http://evil.example", "Access-Control-Request-Method": "DELETE",
        "Access-Control-Request-Headers": "authorization"})
    assert pre.headers.get("access-control-allow-credentials") is None


def test_cors_warning_when_auth_on_with_wildcard(auth_on, monkeypatch, caplog):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    with caplog.at_level("WARNING"):
        auth.startup_warnings()
    assert any("CORS_ORIGINS" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("raw,expected", [
    (None, ["*"]), ("", ["*"]), (" , ", ["*"]), ("*", ["*"]), ("http://a.com,*", ["*"]),
    ("http://a.com, http://b.com ", ["http://a.com", "http://b.com"]),
    ("http://host:8080/", ["http://host:8080"]),
])
def test_parse_cors_origins(raw, expected):
    assert auth.parse_cors_origins(raw) == expected


def test_cors_warning_covers_mixed_wildcard(auth_on, monkeypatch, caplog):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.com,*")
    with caplog.at_level("WARNING"):
        auth.startup_warnings()
    assert any("CORS_ORIGINS" in r.getMessage() for r in caplog.records)


# ---- #49: role changes / deletion / password reset apply immediately ---- #
def _login_user(name, role, password="pw-123456"):
    admin = bearer("admin")
    requests.delete(f"{API}/auth/users/{name}", headers=admin)
    r = requests.post(f"{API}/auth/users", headers=admin,
                      json={"username": name, "password": password, "role": role})
    assert r.status_code == 200, r.text
    r = requests.post(f"{API}/auth/login", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _write(headers):
    return requests.put(f"{API}/discovery", json={"last_message": "rbac"}, headers=headers).status_code


def test_role_downgrade_applies_without_relogin(auth_on):
    h = _login_user("rbac-op", "operator")
    assert _write(h) == 200
    assert requests.patch(f"{API}/auth/users/rbac-op", headers=bearer("admin"),
                          json={"role": "viewer"}).status_code == 200
    assert _write(h) == 403
    assert requests.get(f"{API}/auth/me", headers=h).json()["role"] == "viewer"


def test_deleted_user_token_rejected(auth_on):
    h = _login_user("rbac-del", "operator")
    assert requests.get(f"{API}/devices", headers=h).status_code == 200
    assert requests.delete(f"{API}/auth/users/rbac-del", headers=bearer("admin")).status_code == 200
    assert requests.get(f"{API}/devices", headers=h).status_code == 401


def test_password_reset_revokes_old_sessions(auth_on):
    h = _login_user("rbac-pw", "viewer")
    assert requests.patch(f"{API}/auth/users/rbac-pw", headers=bearer("admin"),
                          json={"password": "new-pw-654321"}).status_code == 200
    assert requests.get(f"{API}/devices", headers=h).status_code == 401
    r = requests.post(f"{API}/auth/login", json={"username": "rbac-pw", "password": "new-pw-654321"})
    assert requests.get(f"{API}/devices", headers={"Authorization": f"Bearer {r.json()['token']}"}).status_code == 200


async def test_ws_rejects_deleted_user(auth_on):
    token = auth.make_token("ghost-user", "admin")  # validly signed, but no such user
    with pytest.raises(websockets.exceptions.InvalidStatus):
        async with websockets.connect(f"{WS}?token={token}", open_timeout=5):
            pass
