"""Sprint 1 security regression tests (issues #2-#7).

These flip auth/ingest settings at runtime on the in-process test server, so they
only run when conftest started the backend in this process.
"""
import json
import os
import sys

import pytest
import requests
import websockets

if "server" not in sys.modules:  # running against an external server
    pytest.skip("security tests need the in-process test server", allow_module_level=True)

import auth  # noqa: E402
import server  # noqa: E402

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"
WS = BASE.replace("http://", "ws://") + "/api/ws"
INGEST = "test-ingest-token"


def bearer(role):
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
    monkeypatch.setattr(server, "_SIM_OVERRIDE", False)


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
    assert ui["community"] == server.COMMUNITY_MASK
    # UI saving the form back with the mask must not overwrite the real value
    requests.put(f"{API}/discovery", json={"community": server.COMMUNITY_MASK, "subnet": "10.0.0.0/24"})
    assert requests.get(f"{API}/discovery", headers=COLLECTOR).json()["community"] == "s3cret"
    requests.put(f"{API}/discovery", json={"community": "public"}, headers=COLLECTOR)


# ---- #2: WebSocket requires login when auth is on ---- #
async def test_ws_rejected_without_token(auth_on):
    with pytest.raises(websockets.exceptions.InvalidStatus):
        async with websockets.connect(WS, open_timeout=5):
            pass


async def test_ws_accepts_valid_token(auth_on):
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
    monkeypatch.setattr(server, "_SIM_ENV", False)          # .env says live
    monkeypatch.setattr(server, "_SIM_OVERRIDE", True)      # runtime toggled to sim
    assert requests.post(f"{API}/mock/reset").status_code == 409
    assert requests.get(f"{API}/devices").json()


def test_non_ascii_ingest_header_is_401_not_500(auth_on, ingest_token):
    r = requests.get(f"{API}/devices", headers={"X-Ingest-Token": "\xe9".encode("latin-1")})
    assert r.status_code == 401
