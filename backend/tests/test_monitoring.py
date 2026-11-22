"""Sprint 2 monitoring-accuracy regression tests (issues #9-#12).

Runs against the in-process test server (see conftest.py)."""
import asyncio
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
import server  # noqa: E402,F401  (in-process test server; netvision.* below is its code)
from netvision import config, database, monitoring  # noqa: E402

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"


def _new_device():
    n = uuid.uuid4().int
    ip = f"10.{n % 250 + 1}.{(n >> 8) % 250 + 1}.{(n >> 16) % 250 + 2}"  # unique enough; IPs must not repeat
    name = f"MON-{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/devices", json={
        "name": name, "ip": ip, "vendor": "t", "model": "t", "protocol": "ICMP", "device_type": "switch"})
    assert r.status_code == 200
    return r.json()


def _get(dev_id):
    return requests.get(f"{API}/devices/{dev_id}").json()


def _alerts(dev_id):
    return [a for a in requests.get(f"{API}/alerts?limit=1000").json() if a["device_id"] == dev_id]


def _db(collection: str):
    """Direct DB handle for arranging state (works for in-memory and real MongoDB)."""
    url = os.environ["MONGO_URL"]
    if url.startswith("mongomock://"):
        coll = getattr(database.db, collection)

        class _Sync:
            def __getattr__(self, name):
                return lambda *a, **k: asyncio.run(getattr(coll, name)(*a, **k))
        return _Sync()
    import pymongo
    return pymongo.MongoClient(url)[os.environ["DB_NAME"]][collection]


def _ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


def _ingest(sample):
    r = requests.post(f"{API}/ingest", json={"samples": [sample]})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(config, "_SIM_OVERRIDE", False)


# ---- #12: collector timestamps are normalized (history only) ---- #
def test_collector_ts_normalized_in_history(live):
    d = _new_device()
    utc = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(microsecond=0)
    kst = utc.astimezone(timezone(timedelta(hours=9)))  # same instant, +09:00 offset
    _ingest({"device_id": d["id"], "reachable": True, "ts": kst.isoformat()})
    pts = requests.get(f"{API}/devices/{d['id']}/metrics?hours=24").json()["points"]
    # history keeps the collector's time, normalized to UTC ISO
    assert any(p["ts"] == utc.isoformat() for p in pts), pts


@pytest.mark.parametrize("ts", ["garbage", "2999-01-01T00:00:00Z", _ago(hours=5)])
def test_last_seen_is_server_receive_time(live, ts):
    # a collector with a wrong clock / delayed batch must not age last_seen (no flapping)
    d = _new_device()
    _ingest({"device_id": d["id"], "reachable": True, "ts": ts})
    seen = datetime.fromisoformat(_get(d["id"])["last_seen"])
    assert abs((datetime.now(timezone.utc) - seen).total_seconds()) < 30


# ---- #9: stale detection, #10: lifecycle on recovery ---- #
def _wait_status(dev_id, status, timeout=12):  # metrics_loop ticks every 5s
    deadline = time.time() + timeout
    while time.time() < deadline and _get(dev_id)["status"] != status:
        time.sleep(0.5)
    return _get(dev_id)


def test_stale_device_goes_offline_and_recovers(live, monkeypatch):
    monkeypatch.setattr(config, "STALE_AFTER_SEC", 30)
    monkeypatch.setattr(config, "_STARTED_AT", datetime.now(timezone.utc) - timedelta(hours=1))
    d = _new_device()
    _ingest({"device_id": d["id"], "reachable": True, "latency_ms": 1, "packet_loss": 0})
    assert _get(d["id"])["status"] == "online"
    _db("devices").update_one({"id": d["id"]}, {"$set": {"last_seen": _ago(minutes=10)}})

    dev = _wait_status(d["id"], "offline")
    assert dev["status"] == "offline" and dev.get("stale") is True
    stale_alerts = [a for a in _alerts(d["id"]) if "no data from collector" in a["message"]]
    assert stale_alerts and stale_alerts[0]["state"] == "active"

    # any fresh ingest (even without reachable=true) brings a stale device back
    _ingest({"device_id": d["id"], "latency_ms": 2, "packet_loss": 0})
    dev = _get(d["id"])
    assert dev["status"] == "online" and dev.get("stale") is False
    a = [x for x in _alerts(d["id"]) if x["id"] == stale_alerts[0]["id"]][0]
    assert a["state"] == "resolved" and a["resolved_at"] and a["acknowledged"] is True


def test_restart_grace_period(live, monkeypatch):
    # backend was down: devices have old last_seen, but the process just started
    monkeypatch.setattr(config, "STALE_AFTER_SEC", 30)
    monkeypatch.setattr(config, "_STARTED_AT", datetime.now(timezone.utc))
    d = _new_device()
    _ingest({"device_id": d["id"], "reachable": True, "latency_ms": 1, "packet_loss": 0})
    _db("devices").update_one({"id": d["id"]}, {"$set": {"last_seen": _ago(minutes=10)}})
    time.sleep(6)  # at least one sweep
    assert _get(d["id"])["status"] == "online"


def test_whole_collector_down_raises_one_alert(live, monkeypatch):
    monkeypatch.setattr(config, "STALE_AFTER_SEC", 30)
    monkeypatch.setattr(config, "_STARTED_AT", datetime.now(timezone.utc) - timedelta(hours=1))
    a, b = _new_device(), _new_device()
    for d in (a, b):
        _ingest({"device_id": d["id"], "reachable": True, "latency_ms": 1, "packet_loss": 0})
        _db("devices").update_one({"id": d["id"]}, {"$set": {"last_seen": _ago(minutes=10)}})
    monkeypatch.setattr(config, "_LAST_INGEST_TS", _ago(minutes=10))
    _wait_status(b["id"], "offline")
    assert _get(a["id"])["status"] == "offline"
    assert not [x for x in _alerts(a["id"]) + _alerts(b["id"]) if "no data from collector" in x["message"]]
    col = [x for x in _alerts("collector") if x["state"] == "active"]
    assert len(col) == 1
    _ingest({"device_id": a["id"], "latency_ms": 1, "packet_loss": 0})  # collector back
    assert all(x["state"] == "resolved" for x in _alerts("collector"))


def test_closed_alert_purged_after_retention(monkeypatch):
    monkeypatch.setattr(config, "ALERT_RETENTION_DAYS", 1)
    old_id, new_id = str(uuid.uuid4()), str(uuid.uuid4())
    base = {"device_id": "purge-test", "device_name": "p", "severity": "warning", "message": "m",
            "acknowledged": True, "state": "resolved", "timestamp": _ago(days=10)}
    _db("alerts").insert_one({**base, "id": old_id, "resolved_at": _ago(days=2)})
    _db("alerts").insert_one({**base, "id": new_id, "resolved_at": _ago(hours=1)})  # old but just closed
    deadline = time.time() + 12
    while time.time() < deadline and any(x["id"] == old_id for x in _alerts("purge-test")):
        time.sleep(0.5)
    ids = {x["id"] for x in _alerts("purge-test")}
    assert old_id not in ids and new_id in ids


def test_no_stale_marking_in_simulation_mode(monkeypatch):
    monkeypatch.setattr(config, "STALE_AFTER_SEC", 1)
    assert config.sim_on()
    assert monitoring._collector_status()["collector_stale"] is False


# ---- #10: operator acknowledge vs auto-resolve are distinguishable ---- #
def test_acknowledge_sets_state(live):
    d = _new_device()
    _ingest({"device_id": d["id"], "reachable": True, "latency_ms": 1, "packet_loss": 0})
    _ingest({"device_id": d["id"], "reachable": False})
    alert = _alerts(d["id"])[0]
    assert alert["state"] == "active" and alert["acknowledged"] is False
    r = requests.post(f"{API}/alerts/{alert['id']}/acknowledge")
    assert r.json()["state"] == "acknowledged" and r.json()["acknowledged_at"]
    first_ack = r.json()["acknowledged_at"]
    r = requests.post(f"{API}/alerts/{alert['id']}/acknowledge")  # re-ack keeps the first time
    assert r.json()["acknowledged_at"] == first_ack
    assert requests.post(f"{API}/alerts/nope/acknowledge").status_code == 404


def test_active_critical_remains_after_ack_until_recovery(live):
    device = _new_device()
    # Resolve any outstanding collector alert before taking the baseline.
    _ingest({"device_id": device["id"], "reachable": True, "latency_ms": 10})
    baseline = requests.get(f"{API}/dashboard/summary").json()
    _ingest({"device_id": device["id"], "reachable": False})
    alert = _alerts(device["id"])[0]
    before = requests.get(f"{API}/dashboard/summary").json()
    assert before["critical_alerts"] == baseline["critical_alerts"] + 1
    ack = requests.post(f"{API}/alerts/{alert['id']}/acknowledge").json()
    after = requests.get(f"{API}/dashboard/summary").json()
    assert after["critical_alerts"] == before["critical_alerts"]
    assert after["health_score"] == before["health_score"]
    assert after["open_alerts"] == before["open_alerts"] - 1
    _ingest({"device_id": device["id"], "reachable": True, "latency_ms": 10})
    recovered = requests.get(f"{API}/dashboard/summary").json()
    assert recovered["critical_alerts"] == baseline["critical_alerts"]
    history = requests.get(f"{API}/alerts/history", params={"device_id": device["id"]}).json()
    assert history["items"][0]["state"] == "resolved"
    assert history["items"][0]["acknowledged_at"] == ack["acknowledged_at"]


def test_latency_sample_count_and_unmeasured_history(live):
    device = _new_device()
    assert device["latency_ms"] is None
    baseline = requests.get(f"{API}/dashboard/summary").json()["latency_sample_count"]
    _ingest({"device_id": device["id"], "cpu_pct": 30})
    assert _get(device["id"])["latency_ms"] is None
    assert requests.get(f"{API}/dashboard/summary").json()["latency_sample_count"] == baseline
    _ingest({"device_id": device["id"], "latency_ms": 0})
    assert _get(device["id"])["latency_ms"] == 0
    _ingest({"device_id": device["id"], "cpu_pct": 20})
    points = requests.get(f"{API}/devices/{device['id']}/metrics").json()["points"]
    assert [p["latency_ms"] for p in points] == [None, 0, None]
    assert requests.get(f"{API}/dashboard/summary").json()["latency_sample_count"] == baseline + 1


@pytest.mark.parametrize(("samples", "average", "count"), [
    ([10, None], 10, 1), ([None], None, 0), ([], None, 0), ([0, None], 0, 1),
])
def test_summary_latency_denominator(samples, average, count, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from netvision import summary

    monkeypatch.setattr(summary, "db", SimpleNamespace(alerts=SimpleNamespace(count_documents=AsyncMock(return_value=0))))
    devices = [{"latency_ms": value, "status": "online"} for value in samples]
    result = asyncio.run(summary.summarize_devices(devices))
    assert (result["avg_latency_ms"], result["latency_sample_count"]) == (average, count)


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
