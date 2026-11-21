"""Sprint 3-C performance regression tests (issue #16)."""
import os
import sys
import time

import pytest
import requests

if "server" not in sys.modules:
    pytest.skip("needs the in-process test server", allow_module_level=True)

import server  # noqa: E402,F401  (in-process test server; netvision.* below is its code)
from netvision import config, database, ws  # noqa: E402
from test_data_integrity import _dev  # noqa: E402

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
IN_MEMORY = os.environ["MONGO_URL"].startswith("mongomock://")


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(config, "_SIM_OVERRIDE", False)


def test_batch_ingest_uses_no_per_sample_lookups(live, monkeypatch):
    devs = [_dev() for _ in range(40)]
    if IN_MEMORY:  # count single-document device lookups during the batch
        calls = {"n": 0}
        cls = type(database.db.devices)  # db.devices returns a new wrapper each access
        orig = cls.find_one

        async def counting(self, *a, **k):
            if self.name == "devices":
                calls["n"] += 1
            return await orig(self, *a, **k)
        monkeypatch.setattr(cls, "find_one", counting)
    samples = [{"ip": d["ip"], "reachable": True, "latency_ms": 2, "packet_loss": 0} for d in devs]
    t0 = time.time()
    r = requests.post(f"{API}/ingest", json={"samples": samples}).json()
    elapsed = time.time() - t0
    assert r["updated"] == 40 and r["unmatched"] == []
    assert elapsed < 5
    if IN_MEMORY:
        assert calls["n"] == 0, f"{calls['n']} per-sample find_one calls"
    for d in devs[:3]:
        got = requests.get(f"{API}/devices/{d['id']}").json()
        assert got["latency_ms"] == 2 and got["status"] == "online"


def test_same_device_twice_in_one_batch_sees_previous_sample(live):
    d = _dev()
    requests.post(f"{API}/ingest", json={"samples": [{"ip": d["ip"], "reachable": True, "latency_ms": 1}]})
    r = requests.post(f"{API}/ingest", json={"samples": [
        {"ip": d["ip"], "reachable": False},
        {"ip": d["ip"], "reachable": True, "latency_ms": 1, "packet_loss": 0},
    ]}).json()
    assert r["updated"] == 2
    assert requests.get(f"{API}/devices/{d['id']}").json()["status"] == "online"
    alerts = [a for a in requests.get(f"{API}/alerts?limit=1000").json() if a["device_id"] == d["id"]]
    assert alerts and all(a["state"] == "resolved" for a in alerts)  # went offline then recovered


def test_many_ingests_coalesce_into_few_broadcasts(live):
    sent = []

    class FakeWS:
        async def send_text(self, msg):
            sent.append(time.time())

    fake = FakeWS()
    ws.ws_manager.clients.add(fake)
    try:
        d = _dev()
        t0 = time.time()
        for i in range(15):
            requests.post(f"{API}/ingest", json={"samples": [{"ip": d["ip"], "latency_ms": i}]})
        time.sleep(config.BROADCAST_DEBOUNCE_SEC + 0.8)
        burst = [t for t in sent if t >= t0]
        # 15 posts -> about one coalesced snapshot per second (+ the 5s periodic tick)
        assert 1 <= len(burst) <= 4, f"{len(burst)} broadcasts for 15 ingests"
    finally:
        ws.ws_manager.clients.discard(fake)
