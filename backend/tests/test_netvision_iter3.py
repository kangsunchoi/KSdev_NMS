"""Iteration 3 backend tests: zones, topology compound parents, metrics 404, alert debounce."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def seeded(session):
    r = session.post(f"{API}/mock/generate?replace=true")
    assert r.status_code == 200
    return r.json()


# ---- metrics 404 ---- #
class TestMetricsEndpoint:
    def test_metrics_unknown_device_returns_404(self, session, seeded):
        r = session.get(f"{API}/devices/this-id-does-not-exist-xyz/metrics")
        assert r.status_code == 404, f"expected 404 got {r.status_code} body={r.text}"

    def test_metrics_existing_device_returns_200(self, session, seeded):
        devs = session.get(f"{API}/devices").json()
        assert len(devs) > 0
        dev_id = devs[0]["id"]
        r = session.get(f"{API}/devices/{dev_id}/metrics?hours=24")
        assert r.status_code == 200
        body = r.json()
        assert body["device_id"] == dev_id
        assert body["hours"] == 24
        assert isinstance(body["points"], list)


# ---- /api/zones ---- #
class TestZones:
    def test_zones_after_generate(self, session, seeded):
        r = session.get(f"{API}/zones")
        assert r.status_code == 200
        zones = r.json()
        assert isinstance(zones, list)
        names = [z["name"] for z in zones]
        assert names == sorted(names), "zones must be alphabetically sorted"
        assert set(names) == {"Cell-A", "Cell-B", "Utilities"}, f"got {names}"
        total = sum(z["total"] for z in zones)
        assert total == 20, f"expected 20 devices total across zones, got {total}"
        for z in zones:
            for k in ("name", "total", "online", "warning", "critical"):
                assert k in z, f"missing key {k} in zone {z}"
            assert z["total"] == z["online"] + z["warning"] + z["critical"], f"zone counts don't sum: {z}"


# ---- /api/topology compound parents ---- #
class TestTopology:
    def test_topology_has_zone_compound_nodes(self, session, seeded):
        r = session.get(f"{API}/topology")
        assert r.status_code == 200
        body = r.json()
        assert "zones" in body
        assert set(body["zones"]) == {"Cell-A", "Cell-B", "Utilities"}

        zone_nodes = [n for n in body["nodes"] if n["data"].get("is_zone")]
        zone_ids = {n["data"]["id"] for n in zone_nodes}
        assert zone_ids == {"zone-Cell-A", "zone-Cell-B", "zone-Utilities"}

        device_nodes = [n for n in body["nodes"] if not n["data"].get("is_zone")]
        # all seeded devices have a zone -> all should have parent
        without_parent = [n for n in device_nodes if not n["data"].get("parent")]
        assert without_parent == [], f"all seeded devices should have parent zone, found {len(without_parent)} without"
        for n in device_nodes:
            assert n["data"]["parent"] == f"zone-{n['data']['zone']}"


# ---- Devices CRUD with zone ---- #
class TestDeviceZone:
    def test_create_device_with_zone_persists(self, session, seeded):
        payload = {
            "name": "TEST_zone_dev_1",
            "ip": "10.20.99.250",
            "vendor": "TestCo",
            "model": "ZX1",
            "protocol": "Modbus TCP",
            "device_type": "plc",
            "zone": "Cell-A",
        }
        r = session.post(f"{API}/devices", json=payload)
        assert r.status_code == 200, r.text
        created = r.json()
        assert created["zone"] == "Cell-A"
        dev_id = created["id"]

        # GET verifies persistence
        g = session.get(f"{API}/devices/{dev_id}").json()
        assert g["zone"] == "Cell-A"

        # PATCH zone -> Cell-B
        p = session.patch(f"{API}/devices/{dev_id}", json={"zone": "Cell-B"})
        assert p.status_code == 200
        assert p.json()["zone"] == "Cell-B"

        # GET listing includes zone
        listed = session.get(f"{API}/devices").json()
        match = next(d for d in listed if d["id"] == dev_id)
        assert match["zone"] == "Cell-B"

        # cleanup
        session.delete(f"{API}/devices/{dev_id}")


# ---- Alert debounce ---- #
class TestAlertDebounce:
    def test_no_duplicate_alerts_in_60s_window(self, session, seeded):
        """After mock/generate, no two unacked alerts should exist for same (device_id, severity)
        with timestamps less than 60s apart."""
        # reset to clean slate, then generate
        session.post(f"{API}/mock/reset")
        session.post(f"{API}/mock/generate?replace=true")
        # Let simulation run a bit so duplicate-prone code path is exercised
        time.sleep(8)
        alerts = session.get(f"{API}/alerts?limit=500").json()
        # Group by (device_id, severity) for unacked
        from collections import defaultdict
        groups = defaultdict(list)
        for a in alerts:
            if a["acknowledged"]:
                continue
            groups[(a["device_id"], a["severity"])].append(a["timestamp"])
        from datetime import datetime
        violations = []
        for key, ts_list in groups.items():
            ts_sorted = sorted(ts_list)
            for i in range(1, len(ts_sorted)):
                t0 = datetime.fromisoformat(ts_sorted[i-1].replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(ts_sorted[i].replace("Z", "+00:00"))
                delta = (t1 - t0).total_seconds()
                if delta < 60:
                    violations.append((key, delta))
        assert not violations, f"alert debounce violated: {violations[:5]}"
