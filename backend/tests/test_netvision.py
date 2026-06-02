"""Backend API tests for NetVision OT.

Covers:
- Health / root
- Dashboard summary
- Devices CRUD
- Alerts CRUD + acknowledge
- Topology structure
- Mock generate/reset
- Simulation loop side effects
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ot-dashboard-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture(scope="session", autouse=True)
def _reset_and_seed(s):
    # Ensure clean state before tests
    r = s.post(f"{API}/mock/generate")
    assert r.status_code == 200, r.text
    yield


# --- Health ---
class TestHealth:
    def test_root(self, s):
        r = s.get(f"{API}/")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "ok"


# --- Dashboard ---
class TestDashboard:
    def test_summary_shape(self, s):
        r = s.get(f"{API}/dashboard/summary")
        assert r.status_code == 200
        d = r.json()
        for k in ["total", "online", "warning", "critical", "open_alerts",
                  "critical_alerts", "health_score", "avg_latency_ms", "avg_packet_loss"]:
            assert k in d, f"missing {k}"
        assert d["total"] == 20
        assert 0 <= d["health_score"] <= 100
        assert d["online"] + d["warning"] + d["critical"] <= d["total"]


# --- Topology ---
class TestTopology:
    def test_topology_structure(self, s):
        r = s.get(f"{API}/topology")
        assert r.status_code == 200
        d = r.json()
        assert "nodes" in d and "edges" in d
        assert len(d["nodes"]) == 20
        # edges: PLCs(5)+HMIs(3)+sensors(9) attached to parents = 17 edges
        assert len(d["edges"]) == 17
        types = [n["data"]["type"] for n in d["nodes"]]
        assert types.count("switch") == 3
        assert types.count("plc") == 5
        assert types.count("hmi") == 3
        assert types.count("sensor") == 9
        # edges reference real nodes
        ids = {n["data"]["id"] for n in d["nodes"]}
        for e in d["edges"]:
            assert e["data"]["source"] in ids
            assert e["data"]["target"] in ids


# --- Devices CRUD ---
class TestDevicesCRUD:
    def test_list_devices(self, s):
        r = s.get(f"{API}/devices")
        assert r.status_code == 200
        devs = r.json()
        assert isinstance(devs, list)
        assert len(devs) >= 20
        # _id should not be present
        for d in devs[:3]:
            assert "_id" not in d
            assert "id" in d

    def test_create_update_delete_persistence(self, s):
        payload = {
            "name": "TEST_DEVICE_01",
            "ip": "10.99.0.1",
            "vendor": "TestCo",
            "model": "TST-1",
            "protocol": "Modbus TCP",
            "device_type": "plc",
        }
        r = s.post(f"{API}/devices", json=payload)
        assert r.status_code == 200, r.text
        created = r.json()
        assert created["name"] == "TEST_DEVICE_01"
        assert created["ip"] == "10.99.0.1"
        assert "id" in created
        dev_id = created["id"]

        # GET verify
        r2 = s.get(f"{API}/devices/{dev_id}")
        assert r2.status_code == 200
        assert r2.json()["name"] == "TEST_DEVICE_01"

        # PATCH update
        r3 = s.patch(f"{API}/devices/{dev_id}", json={"name": "TEST_DEVICE_01_UPD"})
        assert r3.status_code == 200
        assert r3.json()["name"] == "TEST_DEVICE_01_UPD"

        # GET verify persistence
        r4 = s.get(f"{API}/devices/{dev_id}")
        assert r4.json()["name"] == "TEST_DEVICE_01_UPD"
        assert r4.json()["ip"] == "10.99.0.1"  # unchanged

        # DELETE
        r5 = s.delete(f"{API}/devices/{dev_id}")
        assert r5.status_code == 200

        r6 = s.get(f"{API}/devices/{dev_id}")
        assert r6.status_code == 404

    def test_update_nonexistent(self, s):
        r = s.patch(f"{API}/devices/does-not-exist", json={"name": "x"})
        assert r.status_code == 404

    def test_empty_update_rejected(self, s):
        # create temp device
        r = s.post(f"{API}/devices", json={
            "name": "TEST_EMPTY", "ip": "10.99.0.2", "vendor": "T", "model": "T",
            "protocol": "SNMP", "device_type": "switch"})
        did = r.json()["id"]
        try:
            r2 = s.patch(f"{API}/devices/{did}", json={})
            assert r2.status_code == 400
        finally:
            s.delete(f"{API}/devices/{did}")

    def test_delete_nonexistent(self, s):
        r = s.delete(f"{API}/devices/nonexistent-id")
        assert r.status_code == 404


# --- Alerts ---
class TestAlerts:
    def test_list_alerts(self, s):
        r = s.get(f"{API}/alerts")
        assert r.status_code == 200
        alerts = r.json()
        assert isinstance(alerts, list)
        for a in alerts[:3]:
            assert "_id" not in a
            for k in ["id", "device_id", "device_name", "severity", "message", "acknowledged", "timestamp"]:
                assert k in a

    def test_acknowledge_alert(self, s):
        r = s.get(f"{API}/alerts")
        alerts = r.json()
        if not alerts:
            pytest.skip("No alerts to acknowledge")
        open_alerts = [a for a in alerts if not a["acknowledged"]]
        if not open_alerts:
            pytest.skip("No open alerts")
        aid = open_alerts[0]["id"]
        r2 = s.post(f"{API}/alerts/{aid}/acknowledge")
        assert r2.status_code == 200
        assert r2.json()["acknowledged"] is True
        # GET to verify persisted
        r3 = s.get(f"{API}/alerts")
        match = [x for x in r3.json() if x["id"] == aid]
        assert match and match[0]["acknowledged"] is True

    def test_delete_alert(self, s):
        r = s.get(f"{API}/alerts")
        alerts = r.json()
        if not alerts:
            pytest.skip("No alerts")
        aid = alerts[-1]["id"]
        r2 = s.delete(f"{API}/alerts/{aid}")
        assert r2.status_code == 200
        r3 = s.get(f"{API}/alerts")
        assert all(x["id"] != aid for x in r3.json())

    def test_acknowledge_nonexistent(self, s):
        r = s.post(f"{API}/alerts/no-such-id/acknowledge")
        assert r.status_code == 404


# --- Mock generate/reset ---
class TestMock:
    def test_generate_returns_20(self, s):
        r = s.post(f"{API}/mock/generate")
        assert r.status_code == 200
        d = r.json()
        assert d["devices_created"] == 20

    def test_reset_clears(self, s):
        r = s.post(f"{API}/mock/reset")
        assert r.status_code == 200
        devs = s.get(f"{API}/devices").json()
        assert devs == []
        alerts = s.get(f"{API}/alerts").json()
        assert alerts == []
        # Restore for subsequent tests
        s.post(f"{API}/mock/generate")


# --- Simulation loop ---
class TestSimulation:
    def test_metrics_change_over_time(self, s):
        # ensure populated
        s.post(f"{API}/mock/generate")
        r1 = s.get(f"{API}/devices").json()
        snapshot1 = {d["id"]: (d["latency_ms"], d["last_seen"], d["cpu_pct"]) for d in r1}
        # simulation runs every 5s
        time.sleep(7)
        r2 = s.get(f"{API}/devices").json()
        changed = 0
        for d in r2:
            if d["id"] in snapshot1:
                if (d["latency_ms"], d["last_seen"], d["cpu_pct"]) != snapshot1[d["id"]]:
                    changed += 1
        # Expect majority of devices to have updated metrics
        assert changed >= len(r2) // 2, f"Only {changed}/{len(r2)} devices updated; sim loop may not be running"
