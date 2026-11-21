"""Sprint 3-B: alert history paging, live list completeness, stale recovery
via metrics/interfaces, notification storm summary (issues #24, #25)."""
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

if "server" not in sys.modules:
    pytest.skip("needs the in-process test server", allow_module_level=True)

import notify  # noqa: E402
import server  # noqa: E402
from test_data_integrity import _db, _dev  # noqa: E402

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"


def _alert_rows(device_id, n, acknowledged=False, state="active"):
    now = datetime.now(timezone.utc)
    return [{"id": str(uuid.uuid4()), "device_id": device_id, "device_name": "H", "severity": "warning",
             "message": f"m{i}", "acknowledged": acknowledged, "state": state,
             "timestamp": (now - timedelta(minutes=i)).isoformat()} for i in range(n)]


def test_history_paging_and_filters():
    dev_id = f"hist-{uuid.uuid4().hex[:6]}"
    _db("alerts").insert_many(_alert_rows(dev_id, 20) + _alert_rows(dev_id, 5, True, "resolved"))
    r = requests.get(f"{API}/alerts/history", params={"device_id": dev_id, "page_size": 10}).json()
    assert r["total"] == 25 and r["pages"] == 3 and len(r["items"]) == 10
    last = requests.get(f"{API}/alerts/history", params={"device_id": dev_id, "page_size": 10, "page": 3}).json()
    assert len(last["items"]) == 5
    res = requests.get(f"{API}/alerts/history", params={"device_id": dev_id, "state": "resolved"}).json()
    assert res["total"] == 5 and all(a["state"] == "resolved" for a in res["items"])
    assert requests.get(f"{API}/alerts/history", params={"state": "bogus"}).status_code == 422


def test_live_list_contains_every_open_alert():
    dev_id = f"open-{uuid.uuid4().hex[:6]}"
    _db("alerts").insert_many(_alert_rows(dev_id, 230))
    try:
        rows = requests.get(f"{API}/alerts").json()
        open_in_list = sum(1 for a in rows if not a["acknowledged"])
        assert open_in_list == len(_db("alerts").find({"acknowledged": False}))
    finally:
        _db("alerts").delete_many({"device_id": dev_id})


@pytest.mark.parametrize("path", ["metrics", "interfaces"])
def test_stale_device_recovers_on_metrics_or_interfaces(monkeypatch, path):
    monkeypatch.setattr(server, "_SIM_OVERRIDE", False)
    d = _dev()
    _db("devices").update_one({"id": d["id"]}, {"$set": {"status": "offline", "stale": True}})
    if path == "metrics":
        requests.post(f"{API}/metrics", json={"samples": [{"device_id": d["id"], "metric_name": "t", "value": 1}]})
    else:
        requests.post(f"{API}/interfaces", json={"device_id": d["id"], "interfaces": [{"ifindex": 1}]})
    dev = requests.get(f"{API}/devices/{d['id']}").json()
    assert dev["status"] == "online" and dev["stale"] is False


def test_real_offline_is_not_recovered_by_metrics(monkeypatch):
    monkeypatch.setattr(server, "_SIM_OVERRIDE", False)
    d = _dev()
    _db("devices").update_one({"id": d["id"]}, {"$set": {"status": "offline", "stale": False}})
    requests.post(f"{API}/metrics", json={"samples": [{"device_id": d["id"], "metric_name": "t", "value": 1}]})
    assert requests.get(f"{API}/devices/{d['id']}").json()["status"] == "offline"


def test_storm_summary_is_sent_once(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "SLACK_WEBHOOK_URL", "http://notify.invalid/hook")
    monkeypatch.setattr(notify, "_send_sync", lambda a: sent.append(a["message"]))
    monkeypatch.setattr(notify, "_suppressed", 7)
    monkeypatch.setattr(notify, "_window_start", time.monotonic() - 61)
    deadline = time.time() + 8  # metrics_loop flushes every 5s
    summaries = []
    while time.time() < deadline and not summaries:
        time.sleep(0.3)
        summaries = [m for m in sent if "more alert notification" in m]  # ignore sim alerts
    assert len(summaries) == 1 and "7 more" in summaries[0]
    assert notify._suppressed == 0


def test_recovery_survives_a_sweep_in_between(monkeypatch):
    """Recovery stamps last_seen itself, so a sweep right after it keeps the device online."""
    import asyncio
    monkeypatch.setattr(server, "_SIM_OVERRIDE", False)
    monkeypatch.setattr(server, "STALE_AFTER_SEC", 30)
    monkeypatch.setattr(server, "_STARTED_AT", datetime.now(timezone.utc) - timedelta(hours=1))
    d = _dev()
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    _db("devices").update_one({"id": d["id"]}, {"$set": {"status": "offline", "stale": True, "last_seen": old}})
    dev = requests.get(f"{API}/devices/{d['id']}").json()
    if os.environ["MONGO_URL"].startswith("mongomock://"):
        asyncio.run(server._recover_if_stale(dev))
        asyncio.run(server._stale_sweep())
        after = requests.get(f"{API}/devices/{d['id']}").json()
        assert after["status"] == "online" and after["stale"] is False


def test_live_list_is_capped_but_count_exact(monkeypatch):
    monkeypatch.setattr(server, "OPEN_ALERTS_CAP", 5)
    dev_id = f"cap-{uuid.uuid4().hex[:6]}"
    _db("alerts").insert_many(_alert_rows(dev_id, 12))
    try:
        rows = requests.get(f"{API}/alerts").json()
        assert sum(1 for a in rows if not a["acknowledged"]) == 5
        summary = requests.get(f"{API}/dashboard/summary").json()
        assert summary["open_alerts"] >= 12 and summary["alerts_truncated"] is True
    finally:
        _db("alerts").delete_many({"device_id": dev_id})
