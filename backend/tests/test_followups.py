"""Follow-ups #33 and #36: alert debounce after recovery, placeholder IPs,
name/IP policy, stored-IP normalization, RCA within one batch."""
import asyncio
import os
import sys
import uuid

import pytest
import requests

if "server" not in sys.modules:
    pytest.skip("needs the in-process test server", allow_module_level=True)

import server  # noqa: E402
from test_data_integrity import _db, _dev, _ip, _legacy  # noqa: E402

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
IN_MEMORY = os.environ["MONGO_URL"].startswith("mongomock://")


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(server, "_SIM_OVERRIDE", False)


def _alerts(dev_id):
    return [a for a in requests.get(f"{API}/alerts?limit=1000").json() if a["device_id"] == dev_id]


def _ingest(*samples):
    return requests.post(f"{API}/ingest", json={"samples": list(samples)}).json()


def test_second_outage_after_recovery_raises_new_alert(live):
    d = _dev()
    _ingest({"ip": d["ip"], "reachable": True, "latency_ms": 1, "packet_loss": 0})
    _ingest({"ip": d["ip"], "reachable": False})
    _ingest({"ip": d["ip"], "reachable": True, "latency_ms": 1, "packet_loss": 0})
    _ingest({"ip": d["ip"], "reachable": False})  # within the 60s debounce window
    states = sorted(a["state"] for a in _alerts(d["id"]))
    assert states == ["active", "resolved"], states


def test_open_alert_still_debounced(live):
    d = _dev()
    _ingest({"ip": d["ip"], "reachable": True, "latency_ms": 1, "packet_loss": 0})
    _ingest({"ip": d["ip"], "reachable": False})
    _ingest({"ip": d["ip"], "status": "online"}, {"ip": d["ip"], "status": "offline"})
    assert len([a for a in _alerts(d["id"]) if a["state"] == "active"]) <= 1


def test_placeholder_ip_spellings_never_match(live):
    _legacy("::")
    target = _dev()
    r = _ingest({"ip": "::0", "name": target["name"], "latency_ms": 7})
    assert r["updated"] == 1
    assert requests.get(f"{API}/devices/{target['id']}").json()["latency_ms"] == 7


@pytest.mark.parametrize("body", [
    {"ip": "0.0.0.0"}, {"ip": "::0"}, {"name": "   "},
])
def test_create_rejects_placeholder_ip_and_blank_name(body):
    base = {"name": f"P-{uuid.uuid4().hex[:4]}", "ip": _ip(), "vendor": "t", "model": "t",
            "protocol": "x", "device_type": "switch"}
    assert requests.post(f"{API}/devices", json={**base, **body}).status_code == 422


def test_update_rejects_placeholder_ip_and_blank_name():
    d = _dev()
    assert requests.patch(f"{API}/devices/{d['id']}", json={"ip": "0.0.0.0"}).status_code == 422
    assert requests.patch(f"{API}/devices/{d['id']}", json={"name": "  "}).status_code == 422
    r = requests.patch(f"{API}/devices/{d['id']}", json={"name": "  Trimmed  "})
    assert r.status_code == 200 and r.json()["name"] == "Trimmed"


@pytest.mark.skipif(not IN_MEMORY, reason="calls the coroutine directly on the in-memory DB")
def test_stored_ips_are_normalized_at_startup():
    n = uuid.uuid4().int
    a = _legacy(f" 10.66.{n % 250 + 1}.{(n >> 8) % 250 + 1} ")
    b = _legacy(f"FD66::{n % 4000:X}")
    taken = _dev()
    c = _legacy(taken["ip"].upper() if ":" in taken["ip"] else f" {taken['ip']}")  # collides
    host = _legacy("plc-01.local")
    asyncio.run(server._normalize_stored_ips())
    got = {d["id"]: d["ip"] for d in _db("devices").find({"id": {"$in": [a["id"], b["id"], c["id"], host["id"]]}})}
    assert got[a["id"]] == a["ip"].strip()
    assert got[b["id"]] == b["ip"].lower()
    assert got[c["id"]] == c["ip"]            # collision: left as is (logged)
    assert got[host["id"]] == "plc-01.local"  # not an IP: untouched


def test_rca_when_child_reported_before_parent_in_one_batch(live):
    parent, child = _dev(), _dev()
    _db("devices").update_one({"id": child["id"]}, {"$set": {"parent_id": parent["id"]}})
    _ingest({"ip": parent["ip"], "reachable": True, "latency_ms": 1, "packet_loss": 0},
            {"ip": child["ip"], "reachable": True, "latency_ms": 1, "packet_loss": 0})
    _ingest({"ip": child["ip"], "reachable": False}, {"ip": parent["ip"], "reachable": False})
    child_alert = [a for a in _alerts(child["id"]) if a["state"] == "active"][0]
    assert child_alert.get("correlated_to") == parent["id"]
