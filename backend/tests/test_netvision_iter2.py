"""Iteration 2 backend tests — 4 new MVP features for NetVision OT.

Covers:
- GET /api/devices/{id}/metrics (history endpoint)
- POST /api/alerts/bulk-acknowledge (selective + bulk-all)
- WebSocket /api/ws (initial snapshot + push ticks)
"""
import os
import json
import asyncio
import time
import pytest
import requests
import websockets

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
WS_URL = BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/ws"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture(scope="module", autouse=True)
def _seed(s):
    # ensure baseline data so we can pick a device id & open alerts
    r = s.post(f"{API}/mock/generate")
    assert r.status_code == 200, r.text
    yield


# ---------------- Device Metrics ---------------- #
class TestDeviceMetrics:
    def test_metrics_shape_default(self, s):
        dev_id = s.get(f"{API}/devices").json()[0]["id"]
        r = s.get(f"{API}/devices/{dev_id}/metrics")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["device_id"] == dev_id
        assert d["hours"] == 24
        assert isinstance(d["points"], list)
        # points may be 0 right after seed — that's OK (informational)

    def test_metrics_custom_hours_clamped(self, s):
        dev_id = s.get(f"{API}/devices").json()[0]["id"]
        # 1000 should be clamped to 168
        r = s.get(f"{API}/devices/{dev_id}/metrics", params={"hours": 1000})
        assert r.status_code == 200
        assert r.json()["hours"] == 168
        # 0 should be clamped to 1
        r2 = s.get(f"{API}/devices/{dev_id}/metrics", params={"hours": 0})
        assert r2.status_code == 200
        assert r2.json()["hours"] == 1

    def test_metrics_points_sorted_and_typed(self, s):
        dev_id = s.get(f"{API}/devices").json()[0]["id"]
        r = s.get(f"{API}/devices/{dev_id}/metrics", params={"hours": 24})
        pts = r.json()["points"]
        if not pts:
            pytest.skip("no metric samples yet; sim sample is every 60s")
        # ascending by ts
        ts_list = [p["ts"] for p in pts]
        assert ts_list == sorted(ts_list)
        for p in pts:
            for k in ["ts", "latency_ms", "packet_loss", "cpu_pct", "status"]:
                assert k in p, f"missing {k} in point"
            assert "_id" not in p

    def test_metrics_unknown_device_returns_empty(self, s):
        r = s.get(f"{API}/devices/does-not-exist/metrics")
        assert r.status_code == 200
        assert r.json()["points"] == []


# ---------------- Bulk Acknowledge ---------------- #
class TestBulkAcknowledge:
    def _open_ids(self, s):
        return [a["id"] for a in s.get(f"{API}/alerts").json() if not a["acknowledged"]]

    def test_bulk_ack_selective(self, s):
        s.post(f"{API}/mock/generate")  # reseed for open alerts
        open_ids = self._open_ids(s)
        if len(open_ids) < 2:
            pytest.skip("need at least 2 open alerts")
        target = open_ids[:2]
        r = s.post(f"{API}/alerts/bulk-acknowledge", json={"ids": target})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "acknowledged" in body
        assert body["acknowledged"] == 2
        # verify persistence
        alerts = {a["id"]: a for a in s.get(f"{API}/alerts").json()}
        for tid in target:
            assert alerts[tid]["acknowledged"] is True

    def test_bulk_ack_all_with_empty_body(self, s):
        s.post(f"{API}/mock/generate")
        open_before = len(self._open_ids(s))
        if open_before == 0:
            pytest.skip("no open alerts to bulk-ack")
        r = s.post(f"{API}/alerts/bulk-acknowledge", json={})
        assert r.status_code == 200
        assert r.json()["acknowledged"] == open_before
        assert self._open_ids(s) == []

    def test_bulk_ack_all_with_null_ids(self, s):
        s.post(f"{API}/mock/generate")
        open_before = len(self._open_ids(s))
        if open_before == 0:
            pytest.skip("no open alerts")
        r = s.post(f"{API}/alerts/bulk-acknowledge", json={"ids": None})
        assert r.status_code == 200
        assert r.json()["acknowledged"] == open_before

    def test_bulk_ack_empty_ids_list_acks_all(self, s):
        # spec says payload.ids being None or absent acks all; empty [] is falsy too
        s.post(f"{API}/mock/generate")
        open_before = len(self._open_ids(s))
        if open_before == 0:
            pytest.skip("no open alerts")
        r = s.post(f"{API}/alerts/bulk-acknowledge", json={"ids": []})
        assert r.status_code == 200
        # implementation: empty list is falsy -> acks all open
        assert r.json()["acknowledged"] == open_before


# ---------------- WebSocket ---------------- #
@pytest.mark.asyncio
async def test_ws_initial_snapshot_and_tick():
    async with websockets.connect(WS_URL, open_timeout=5) as ws:
        # initial snapshot should arrive ~immediately
        first_raw = await asyncio.wait_for(ws.recv(), timeout=3)
        first = json.loads(first_raw)
        assert first.get("type") == "tick"
        for k in ["summary", "devices", "alerts"]:
            assert k in first
        for sk in ["total", "online", "open_alerts", "health_score"]:
            assert sk in first["summary"]
        assert isinstance(first["devices"], list)
        # subsequent tick within ~7s
        second_raw = await asyncio.wait_for(ws.recv(), timeout=8)
        second = json.loads(second_raw)
        assert second.get("type") == "tick"


@pytest.mark.asyncio
async def test_ws_pushes_metric_changes_over_time():
    """Two consecutive ticks should differ (latency jiggle) for at least one device."""
    async with websockets.connect(WS_URL, open_timeout=5) as ws:
        a = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))  # initial
        b = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))  # next tick
        dev_a = {d["id"]: d.get("latency_ms") for d in a["devices"]}
        dev_b = {d["id"]: d.get("latency_ms") for d in b["devices"]}
        changed = sum(1 for k in dev_a if dev_b.get(k) != dev_a[k])
        assert changed > 0, "no devices changed across ticks — sim loop may be stuck"
