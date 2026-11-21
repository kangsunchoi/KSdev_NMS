"""Sprint 2 monitoring-accuracy regression tests (issues #9-#12).

Runs against the in-process test server (see conftest.py)."""
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

if "server" not in sys.modules:
    pytest.skip("monitoring tests need the in-process test server", allow_module_level=True)

import notify  # noqa: E402
import server  # noqa: E402

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"


def _new_device():
    ip = f"198.51.100.{uuid.uuid4().int % 250 + 2}"
    name = f"MON-{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/devices", json={
        "name": name, "ip": ip, "vendor": "t", "model": "t", "protocol": "ICMP", "device_type": "switch"})
    assert r.status_code == 200
    return r.json()


def _get(dev_id):
    return requests.get(f"{API}/devices/{dev_id}").json()


def _alerts(dev_id):
    return [a for a in requests.get(f"{API}/alerts?limit=1000").json() if a["device_id"] == dev_id]


def _ingest(sample):
    r = requests.post(f"{API}/ingest", json={"samples": [sample]})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(server, "_SIM_OVERRIDE", False)


# ---- #12: collector timestamps are normalized ---- #
def test_ts_normalized_to_utc_iso(live):
    d = _new_device()
    _ingest({"device_id": d["id"], "reachable": True, "ts": "2026-01-02T03:04:05Z"})
    assert _get(d["id"])["last_seen"] == "2026-01-02T03:04:05+00:00"
    _ingest({"device_id": d["id"], "reachable": True, "ts": "2026-01-02T12:04:05+09:00"})
    assert _get(d["id"])["last_seen"] == "2026-01-02T03:04:05+00:00"


@pytest.mark.parametrize("bad", ["garbage", "2999-01-01T00:00:00Z"])
def test_invalid_or_future_ts_falls_back_to_now(live, bad):
    d = _new_device()
    _ingest({"device_id": d["id"], "reachable": True, "ts": bad})
    seen = datetime.fromisoformat(_get(d["id"])["last_seen"])
    assert abs((datetime.now(timezone.utc) - seen).total_seconds()) < 30


# ---- #9: stale detection, #10: lifecycle on recovery ---- #
def test_stale_device_goes_offline_and_recovers(live, monkeypatch):
    monkeypatch.setattr(server, "STALE_AFTER_SEC", 30)
    d = _new_device()
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    _ingest({"device_id": d["id"], "reachable": True, "latency_ms": 1, "packet_loss": 0, "ts": old})
    assert _get(d["id"])["status"] == "online"

    deadline = time.time() + 12  # metrics_loop ticks every 5s
    while time.time() < deadline and _get(d["id"])["status"] != "offline":
        time.sleep(0.5)
    dev = _get(d["id"])
    assert dev["status"] == "offline" and dev.get("stale") is True
    stale_alerts = [a for a in _alerts(d["id"]) if "no data from collector" in a["message"]]
    assert stale_alerts and stale_alerts[0]["state"] == "active"

    # any fresh data (even without reachable=true) brings a stale device back
    _ingest({"device_id": d["id"], "latency_ms": 2, "packet_loss": 0})
    dev = _get(d["id"])
    assert dev["status"] == "online" and dev.get("stale") is False
    a = [x for x in _alerts(d["id"]) if x["id"] == stale_alerts[0]["id"]][0]
    assert a["state"] == "resolved" and a["resolved_at"] and a["acknowledged"] is True


def test_no_stale_marking_in_simulation_mode(monkeypatch):
    monkeypatch.setattr(server, "STALE_AFTER_SEC", 1)
    assert server.sim_on()
    assert server._collector_status()["collector_stale"] is False


# ---- #10: operator acknowledge vs auto-resolve are distinguishable ---- #
def test_acknowledge_sets_state(live):
    d = _new_device()
    _ingest({"device_id": d["id"], "reachable": True, "latency_ms": 1, "packet_loss": 0})
    _ingest({"device_id": d["id"], "reachable": False})
    alert = _alerts(d["id"])[0]
    assert alert["state"] == "active" and alert["acknowledged"] is False
    r = requests.post(f"{API}/alerts/{alert['id']}/acknowledge")
    assert r.json()["state"] == "acknowledged" and r.json()["acknowledged_at"]


def test_closed_alerts_kept_beyond_two_hours():
    assert server.ALERT_RETENTION_DAYS >= 1


# ---- #11: notifications never block ingestion ---- #
def test_slow_notifier_does_not_block_ingest(live, monkeypatch):
    calls = []

    def slow_send(alert):
        time.sleep(3)
        calls.append(alert["id"])

    monkeypatch.setattr(notify, "SLACK_WEBHOOK_URL", "http://notify.invalid/hook")
    monkeypatch.setattr(notify, "NOTIFY_MIN_SEVERITY", "critical")
    monkeypatch.setattr(notify, "NOTIFY_MAX_PER_MIN", 1000)
    monkeypatch.setattr(notify, "_send_sync", slow_send)
    d = _new_device()
    _ingest({"device_id": d["id"], "reachable": True, "latency_ms": 1, "packet_loss": 0})
    t0 = time.time()
    _ingest({"device_id": d["id"], "reachable": False})  # -> critical alert -> notify
    assert time.time() - t0 < 1.5, "ingest waited for the notifier"


def test_notify_storm_guard(monkeypatch):
    monkeypatch.setattr(notify, "NOTIFY_MAX_PER_MIN", 3)
    monkeypatch.setattr(notify, "_sent_times", [])
    allowed = [notify._allow_now() for _ in range(10)]
    assert allowed.count(True) == 3
