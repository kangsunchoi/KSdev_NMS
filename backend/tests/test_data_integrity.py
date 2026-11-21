"""Sprint 3 data-integrity regression tests (issues #13, #14, #15)."""
import asyncio
import os
import sys
import uuid

import pytest
import requests

if "server" not in sys.modules:
    pytest.skip("data-integrity tests need the in-process test server", allow_module_level=True)

import server  # noqa: E402

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"


def _db(collection: str):
    url = os.environ["MONGO_URL"]
    if url.startswith("mongomock://"):
        coll = getattr(server.db, collection)

        class _Sync:
            def __getattr__(self, name):
                def call(*a, **k):
                    res = getattr(coll, name)(*a, **k)
                    if name == "find":
                        return asyncio.run(res.to_list(None))
                    return asyncio.run(res)
                return call
        return _Sync()
    import pymongo
    c = pymongo.MongoClient(url)[os.environ["DB_NAME"]][collection]

    class _P:
        def __getattr__(self, name):
            if name == "find":
                return lambda *a, **k: list(c.find(*a, **k))
            return getattr(c, name)
    return _P()


def _ip():
    n = uuid.uuid4().int
    return f"172.{16 + n % 16}.{(n >> 8) % 250 + 1}.{(n >> 16) % 250 + 2}"


def _dev(**kw):
    body = {"name": f"DI-{uuid.uuid4().hex[:6]}", "ip": _ip(), "vendor": "t", "model": "t",
            "protocol": "ICMP", "device_type": "switch", **kw}
    r = requests.post(f"{API}/devices", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ---- #14: IP validation and duplicates ---- #
@pytest.mark.parametrize("bad", ["", "999.1.1.1", "10.0.0", "abc", "10.0.0.1/24"])
def test_create_rejects_invalid_ip(bad):
    r = requests.post(f"{API}/devices", json={
        "name": "BAD", "ip": bad, "vendor": "t", "model": "t", "protocol": "x", "device_type": "switch"})
    assert r.status_code == 422


def test_update_rejects_invalid_ip():
    d = _dev()
    assert requests.patch(f"{API}/devices/{d['id']}", json={"ip": "300.1.1.1"}).status_code == 422


def test_duplicate_ip_rejected():
    d = _dev()
    r = requests.post(f"{API}/devices", json={
        "name": "DUP", "ip": d["ip"], "vendor": "t", "model": "t", "protocol": "x", "device_type": "switch"})
    assert r.status_code == 409
    other = _dev()
    assert requests.patch(f"{API}/devices/{other['id']}", json={"ip": d["ip"]}).status_code == 409
    # re-saving its own IP is fine
    assert requests.patch(f"{API}/devices/{d['id']}", json={"ip": d["ip"], "vendor": "v2"}).status_code == 200


def test_ambiguous_name_is_not_matched():
    name = f"SAME-{uuid.uuid4().hex[:6]}"
    a, b = _dev(name=name), _dev(name=name)
    r = requests.post(f"{API}/ingest", json={"samples": [{"name": name, "latency_ms": 99}]}).json()
    assert r["updated"] == 0 and name in r["unmatched"]
    for d in (a, b):
        assert requests.get(f"{API}/devices/{d['id']}").json()["latency_ms"] != 99


def test_discovery_register_skips_invalid_ips():
    good = _ip()
    r = requests.post(f"{API}/discovery/register", json={"ips": ["not-an-ip", "300.1.1.1", good]}).json()
    assert r["new_ips"] == [good]


# ---- #13: one cascade for every delete path ---- #
def _attach_everything(dev, peer):
    requests.post(f"{API}/ingest", json={"samples": [{"device_id": dev["id"], "reachable": True}]})
    requests.post(f"{API}/metrics", json={"samples": [{"device_id": dev["id"], "metric_name": "t", "value": 1}]})
    requests.post(f"{API}/interfaces", json={"device_id": dev["id"], "interfaces": [{"ifindex": 1}]})
    requests.post(f"{API}/fdb", json={"device_id": dev["id"], "entries": [{"port": "p1", "mac": "aa"}]})
    requests.post(f"{API}/assets", json={"assets": [{"parent_device_id": dev["id"], "name": "io1"}]})
    requests.post(f"{API}/links", json={"links": [{"source_id": dev["id"], "neighbor_id": peer["id"]}]})
    _db("alerts").insert_one({"id": str(uuid.uuid4()), "device_id": dev["id"], "device_name": "x",
                              "severity": "warning", "message": "m", "acknowledged": False,
                              "state": "active", "timestamp": "2026-11-21T00:00:00+00:00"})


def _leftovers(dev_id):
    found = {}
    for coll, field in server._DEVICE_REF_COLLECTIONS:
        n = len(_db(coll).find({field: dev_id}))
        if n:
            found[coll] = n
    n = len(_db("links").find({"$or": [{"source_id": dev_id}, {"target_id": dev_id}]}))
    if n:
        found["links"] = n
    return found


def test_delete_device_cascades_everywhere():
    dev, peer = _dev(), _dev()
    _attach_everything(dev, peer)
    assert _leftovers(dev["id"]), "test setup should have created related data"
    assert requests.delete(f"{API}/devices/{dev['id']}").status_code == 200
    assert _leftovers(dev["id"]) == {}


def test_cleanup_cascades_everywhere():
    prefix = f"CLN{uuid.uuid4().hex[:4]}-"
    dev, peer = _dev(name=prefix + "1"), _dev()
    _attach_everything(dev, peer)
    r = requests.post(f"{API}/devices/cleanup",
                      json={"name_prefixes": [prefix], "ip_prefix": "", "dry_run": False}).json()
    assert r["deleted"] == 1
    assert _leftovers(dev["id"]) == {}


def test_mock_regenerate_leaves_no_orphans():
    assert requests.post(f"{API}/mock/generate?replace=true").status_code == 200
    ids = {d["id"] for d in requests.get(f"{API}/devices").json()}
    for coll, field in server._DEVICE_REF_COLLECTIONS:
        orphans = [x for x in _db(coll).find({}) if x.get(field) not in ids and x.get(field) != "collector"]
        assert not orphans, f"{coll} has {len(orphans)} orphan rows"
    for lk in _db("links").find({}):
        assert lk["source_id"] in ids and lk["target_id"] in ids


# ---- #15: no silent truncation ---- #
def test_device_list_not_capped_at_1000():
    tag = uuid.uuid4().hex[:6]
    rows = [{"id": f"bulk-{tag}-{i}", "name": f"BULK-{tag}-{i}", "ip": "0.0.0.0", "vendor": "t", "model": "t",
             "protocol": "x", "device_type": "sensor", "status": "online", "latency_ms": 0.0,
             "packet_loss": 0.0, "uptime_pct": 100.0, "cpu_pct": 0.0,
             "last_seen": "2026-11-21T00:00:00+00:00", "stale": False} for i in range(1010)]
    _db("devices").insert_many(rows)
    try:
        assert len(requests.get(f"{API}/devices").json()) >= 1010
        assert requests.get(f"{API}/dashboard/summary").json()["total"] >= 1010
    finally:
        _db("devices").delete_many({"id": {"$regex": f"^bulk-{tag}-"}})
