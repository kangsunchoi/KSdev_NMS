"""Device repository helpers: lookup, IP uniqueness, cascades, batch cache."""
import logging
from typing import List, Optional

from netvision.database import db
from netvision.helpers import _is_placeholder, _normalize_ip, _valid_ip

# ---------------- DEVICE DATA LIFECYCLE (issue #13) ---------------- #
# Every collection that references a device id. Keep this list as the single
# source of truth for cascades, so delete / cleanup / mock reset cannot drift.
_DEVICE_REF_COLLECTIONS = [
    ("alerts", "device_id"),
    ("device_metrics", "device_id"),
    ("device_kv", "device_id"),
    ("unified_metrics", "device_id"),
    ("device_interfaces", "device_id"),
    ("device_fdb", "device_id"),
    ("assets", "parent_device_id"),
]


async def _cascade_delete_devices(ids: List[str]) -> int:
    """Delete devices and everything that references them."""
    if not ids:
        return 0
    res = await db.devices.delete_many({"id": {"$in": ids}})
    await db.devices.update_many({"parent_id": {"$in": ids}}, {"$set": {"parent_id": None}})
    await db.links.delete_many({"$or": [{"source_id": {"$in": ids}}, {"target_id": {"$in": ids}}]})
    for coll, field in _DEVICE_REF_COLLECTIONS:
        await db[coll].delete_many({field: {"$in": ids}})
    return res.deleted_count


async def _wipe_device_data():
    """Remove all devices and all device-derived data (simulation mode only)."""
    await db.discovery_candidates.delete_many({})
    await db.devices.delete_many({})
    await db.links.delete_many({})
    for coll, _ in _DEVICE_REF_COLLECTIONS:
        await db[coll].delete_many({})


def site_query(site_id: str) -> dict:
    # Documents created before site support belong to the default site.
    return {"site_id": {"$in": [None, "default"]} if site_id == "default" else site_id}


async def _ip_taken(ip: str, exclude_id: Optional[str] = None, site_id: str = "default") -> bool:
    if not ip or _is_placeholder(ip):
        return False
    q: dict = {"ip": ip, **site_query(site_id)}
    if exclude_id:
        q["id"] = {"$ne": exclude_id}
    return await db.devices.find_one(q, {"_id": 0, "id": 1}) is not None


async def _find_device(did=None, ip=None, name=None, site_id=None):
    """Resolve a device by id, then ip, then name.

    A name shared by several devices is ambiguous and resolves to nothing
    (issue #14): attaching data to the wrong device is worse than reporting
    it as unmatched to the collector."""
    scope = site_query(site_id) if site_id else {}
    if did:
        d = await db.devices.find_one({"id": did, **scope}, {"_id": 0})
        if d:
            return d
    if ip and not _is_placeholder(ip):
        # devices are stored with the normalized IP; legacy rows may hold the raw text
        candidates = [ip, ip.strip()]
        if _valid_ip(ip):
            candidates.insert(0, _normalize_ip(ip))
        matches = await db.devices.find({"ip": {"$in": list(dict.fromkeys(candidates))}, **scope}, {"_id": 0}).to_list(2)
        if matches:
            return matches[0] if len(matches) == 1 else None
    if name:
        matches = await db.devices.find({"name": name, **scope}, {"_id": 0}).to_list(2)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            logging.warning("ambiguous device name %r matches several devices; sample not attached", name)
    return None


async def _prefetch_devices(samples) -> dict:
    """Load every device a batch may refer to with ONE query (issue #16)."""
    ids, ips, names = set(), set(), set()
    for s in samples:
        if s.device_id:
            ids.add(s.device_id)
        if s.ip:
            ips.update({s.ip, s.ip.strip()})
            if _valid_ip(s.ip):
                ips.add(_normalize_ip(s.ip))
        if s.name:
            names.add(s.name)
    ors = []
    if ids:
        ors.append({"id": {"$in": list(ids)}})
    if ips:
        ors.append({"ip": {"$in": list(ips)}})
    if names:
        ors.append({"name": {"$in": list(names)}})
    docs = await db.devices.find({"$or": ors}, {"_id": 0}).to_list(None) if ors else []
    cache = {"by_id": {}, "by_ip": {}, "by_name": {}}
    for d in docs:
        _cache_add(cache, d)
    return cache


def _cache_add(cache: dict, d: dict):
    if d["id"] in cache["by_id"]:
        return
    cache["by_id"][d["id"]] = d
    if d.get("ip"):
        cache["by_ip"].setdefault(d["ip"], []).append(d)
    cache["by_name"].setdefault(d.get("name"), []).append(d)


def _resolve_cached(cache: dict, did=None, ip=None, name=None, site_id=None) -> Optional[dict]:
    """Same rules as _find_device (id, normalized/raw ip, unique name), in memory."""
    def in_scope(doc):
        return not site_id or doc.get("site_id", "default") == site_id

    if did and did in cache["by_id"] and in_scope(cache["by_id"][did]):
        return cache["by_id"][did]
    if ip and not _is_placeholder(ip):
        candidates = ([_normalize_ip(ip)] if _valid_ip(ip) else []) + [ip, ip.strip()]
        for c in candidates:
            if c in cache["by_ip"]:
                matches = [d for d in cache["by_ip"][c] if in_scope(d)]
                return matches[0] if len(matches) == 1 else None
    if name:
        matches = [d for d in cache["by_name"].get(name, []) if in_scope(d)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            logging.warning("ambiguous device name %r matches several devices; sample not attached", name)
    return None


async def _normalize_stored_ips() -> int:
    """Startup migration (#33): rewrite device IPs stored in a non-canonical
    spelling (' 10.0.0.1', 'FE80::1') to the canonical form, so duplicate checks
    compare like with like. Skips a device when the canonical IP is already used
    by another device (logged) and leaves invalid IPs (e.g. hostnames) untouched."""
    fixed = 0
    async for d in db.devices.find({}, {"_id": 0, "id": 1, "ip": 1, "site_id": 1}):
        raw = d.get("ip") or ""
        if not _valid_ip(raw):
            continue
        canon = _normalize_ip(raw)
        if canon == raw:
            continue
        if not _is_placeholder(canon) and await _ip_taken(canon, exclude_id=d["id"], site_id=d.get("site_id", "default")):
            logging.warning("device %s: IP %r not normalized, %s is used by another device", d["id"], raw, canon)
            continue
        await db.devices.update_one({"id": d["id"]}, {"$set": {"ip": canon}})
        fixed += 1
    if fixed:
        logging.info("normalized %d stored device IP(s)", fixed)
    return fixed
