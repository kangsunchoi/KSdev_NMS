"""ARP ingest API + inferred-topology debug endpoint (issue #48, steps 1-2)."""
import asyncio
import os
import sys
import uuid

import pytest
import requests

if "server" not in sys.modules:
    pytest.skip("ARP ingest tests need the in-process test server", allow_module_level=True)

import auth  # noqa: E402
import server  # noqa: E402,F401  (in-process test server; netvision.* below is its code)
from netvision import config, database  # noqa: E402

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"


def _find(collection: str, query: dict) -> list:
    """Read rows straight from the test DB (in-memory mongomock or real MongoDB)."""
    url = os.environ["MONGO_URL"]
    if url.startswith("mongomock://"):
        return asyncio.run(database.db[collection].find(query, {"_id": 0}).to_list(None))
    import pymongo
    return list(pymongo.MongoClient(url)[os.environ["DB_NAME"]][collection].find(query, {"_id": 0}))
INGEST = "test-ingest-token"
COLLECTOR = {"X-Ingest-Token": INGEST}


def bearer(role):
    return {"Authorization": f"Bearer {auth.make_token(f'u-{role}', role)}"}


def _ip(prefix="198.18"):
    n = uuid.uuid4().int
    return f"{prefix}.{n % 250 + 1}.{(n >> 8) % 250 + 2}"


def _dev(device_type="switch", **kw):
    body = {"name": f"ARP-{uuid.uuid4().hex[:6]}", "ip": _ip(), "vendor": "t", "model": "t",
            "protocol": "SNMP", "device_type": device_type, **kw}
    r = requests.post(f"{API}/devices", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _mac():
    h = uuid.uuid4().hex[:10]
    return "02:" + ":".join(h[i:i + 2] for i in range(0, 10, 2))


def _rows(source_id, ip=None):
    q = {"source_id": source_id}
    if ip:
        q["ip"] = ip
    return _find("arp_entries", q)


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)


@pytest.fixture
def ingest_token(monkeypatch):
    monkeypatch.setattr(auth, "INGEST_TOKEN", INGEST)


@pytest.fixture
def inference_on(monkeypatch):
    monkeypatch.setattr(config, "L2_INFERENCE_ENABLED", True)


# ---- ingest: normalization + upsert ---- #
def test_arp_gateway_upsert_normalizes_and_updates_last_seen():
    gw = _dev()
    host_ip, m = _ip(), _mac()
    body = {"ip": gw["ip"], "entries": [{"ip": f" {host_ip} ", "mac": m.upper().replace(":", "-"),
                                         "ifname": "Vlan10", "vlan": 10}]}
    r = requests.post(f"{API}/arp", json=body).json()
    assert r["matched"] is True and r["source_id"] == gw["id"] and r["source_type"] == "gateway"
    assert (r["accepted"], r["invalid_count"]) == (1, 0)
    rows = _rows(gw["id"])
    assert len(rows) == 1
    row = rows[0]
    assert (row["ip"], row["mac"], row["ifname"], row["vlan"]) == (host_ip, m, "Vlan10", "10")
    first = row["last_seen"]

    # same (source, ip, mac) in another spelling -> same row, newer last_seen
    m_cisco = m.replace(":", "")
    body["entries"] = [{"ip": host_ip, "mac": f"{m_cisco[:4]}.{m_cisco[4:8]}.{m_cisco[8:]}"}]
    assert requests.post(f"{API}/arp", json=body).json()["accepted"] == 1
    rows = _rows(gw["id"])
    assert len(rows) == 1 and rows[0]["last_seen"] >= first and rows[0]["first_seen"] == row["first_seen"]


def test_arp_ipv6_normalized():
    gw = _dev()
    m = _mac()
    requests.post(f"{API}/arp", json={"device_id": gw["id"], "entries": [{"ip": "2001:DB8::0:1", "mac": m}]})
    assert [r["ip"] for r in _rows(gw["id"])] == ["2001:db8::1"]


def test_arp_invalid_rows_reported():
    gw = _dev()
    good = _mac()
    entries = [
        {"ip": _ip(), "mac": good},
        {"ip": "300.1.1.1", "mac": _mac()},
        {"ip": _ip(), "mac": "zz:zz:zz:zz:zz:zz"},
        {"ip": _ip()},
        {"mac": _mac()},
        {"ip": "0.0.0.0", "mac": _mac()},
        {"ip": _ip(), "mac": "00:00:00:00:00:00"},
        "not-an-object",
        {"ip": 12345, "mac": _mac()},
    ]
    r = requests.post(f"{API}/arp", json={"device_id": gw["id"], "entries": entries})
    assert r.status_code == 200, r.text
    r = r.json()
    assert r["received"] == 9 and r["accepted"] == 1 and r["invalid_count"] == 8
    assert [x["index"] for x in r["invalid"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert {x["reason"] for x in r["invalid"]} == {"invalid ip", "invalid mac", "entry must be an object"}
    assert [row["mac"] for row in _rows(gw["id"])] == [good]


def test_arp_collector_source():
    host_ip, m = _ip("198.19"), _mac()
    r = requests.post(f"{API}/arp", json={"source": "collector", "entries": [{"ip": host_ip, "mac": m}]}).json()
    assert r["matched"] is True and r["source_id"] == "collector" and r["source_type"] == "collector"
    assert [(x["ip"], x["mac"]) for x in _rows("collector", host_ip)] == [(host_ip, m)]


def test_arp_unknown_gateway_not_matched():
    r = requests.post(f"{API}/arp", json={"ip": "203.0.113.249", "entries": [{"ip": _ip(), "mac": _mac()}]})
    assert r.status_code == 200 and r.json()["matched"] is False and r.json()["accepted"] == 0
    assert requests.post(f"{API}/arp", json={"source": "nonsense", "entries": []}).status_code == 422


# ---- token rules: same as /api/fdb ---- #
def test_arp_needs_ingest_token_when_set(ingest_token):
    body = {"source": "collector", "entries": []}
    assert requests.post(f"{API}/arp", json=body).status_code == 401
    assert requests.post(f"{API}/arp", json=body, headers={"X-Ingest-Token": "wrong"}).status_code == 401
    assert requests.post(f"{API}/arp", json=body, headers=COLLECTOR).status_code == 200


def test_arp_token_works_with_auth_on(auth_on, ingest_token):
    body = {"source": "collector", "entries": []}
    assert requests.post(f"{API}/arp", json=body, headers=COLLECTOR).status_code == 200
    assert requests.post(f"{API}/arp", json=body, headers=bearer("admin")).status_code == 401


def test_arp_needs_login_when_auth_on_without_token(auth_on):
    body = {"source": "collector", "entries": []}
    assert requests.post(f"{API}/arp", json=body).status_code == 401
    assert requests.post(f"{API}/arp", json=body, headers=bearer("viewer")).status_code == 403
    assert requests.post(f"{API}/arp", json=body, headers=bearer("operator")).status_code == 200


# ---- cascade delete ---- #
def test_delete_gateway_removes_its_arp_rows_only():
    gw = _dev()
    col_ip = _ip("198.19")
    requests.post(f"{API}/arp", json={"device_id": gw["id"], "entries": [{"ip": _ip(), "mac": _mac()}]})
    requests.post(f"{API}/arp", json={"source": "collector", "entries": [{"ip": col_ip, "mac": _mac()}]})
    assert _rows(gw["id"])
    assert requests.delete(f"{API}/devices/{gw['id']}").status_code == 200
    assert _rows(gw["id"]) == []
    assert _rows("collector", col_ip), "collector rows must survive a device delete"


# ---- GET /api/topology/inferred ---- #
def test_inferred_endpoint_404_when_toggle_off(monkeypatch):
    monkeypatch.setattr(config, "L2_INFERENCE_ENABLED", False)
    r = requests.get(f"{API}/topology/inferred")
    assert r.status_code == 404 and "L2_INFERENCE_ENABLED" in r.json()["detail"]


def test_inferred_endpoint_end_to_end(inference_on):
    sw1, sw2 = _dev("switch"), _dev("switch")
    plc = _dev("plc")
    m1, m2, mplc = _mac(), _mac(), _mac()
    requests.post(f"{API}/arp", json={"source": "collector", "entries": [
        {"ip": sw1["ip"], "mac": m1}, {"ip": sw2["ip"], "mac": m2}, {"ip": plc["ip"], "mac": mplc}]})
    requests.post(f"{API}/fdb", json={"device_id": sw1["id"], "entries": [
        {"port": "Gi24", "mac": m2}, {"port": "Gi24", "mac": mplc}]})
    requests.post(f"{API}/fdb", json={"device_id": sw2["id"], "entries": [
        {"port": "Gi1", "mac": m1}, {"port": "Gi3", "mac": mplc.upper()}]})
    topo_before = requests.get(f"{API}/topology").json()

    r = requests.get(f"{API}/topology/inferred")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert {"endpoints", "links", "uplinks", "excluded", "segments", "ambiguities", "stats"} <= set(body)
    mine = {(lk["source"], lk["source_port"], lk["target"], lk["target_port"]) for lk in body["links"]
            if {lk["source"], lk["target"]} <= {sw1["id"], sw2["id"], plc["id"]}}
    a, b = sorted([sw1["id"], sw2["id"]])
    switch_link = (sw1["id"], "Gi24", sw2["id"], "Gi1") if a == sw1["id"] else (sw2["id"], "Gi1", sw1["id"], "Gi24")
    assert mine == {switch_link, (sw2["id"], "Gi3", plc["id"], None)}
    assert all(lk["kind"] == "inferred" for lk in body["links"])
    # /api/topology is untouched in this step
    assert not any(e["data"].get("kind") == "inferred" for e in requests.get(f"{API}/topology").json()["edges"])
    assert len(topo_before["edges"]) == len(requests.get(f"{API}/topology").json()["edges"])


def test_inferred_endpoint_viewer_can_read_when_auth_on(auth_on, inference_on):
    assert requests.get(f"{API}/topology/inferred").status_code == 401
    assert requests.get(f"{API}/topology/inferred", headers=bearer("viewer")).status_code == 200
