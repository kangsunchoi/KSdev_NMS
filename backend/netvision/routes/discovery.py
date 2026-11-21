"""Discovery settings (read by the Node-RED collector) and alive-IP registration."""
from datetime import datetime, timezone

from fastapi import APIRouter, Request

import auth
from netvision.database import db
from netvision.helpers import _valid_ip
from netvision.models import Device, DiscoveryRegister, DiscoveryUpdate

router = APIRouter()

# ---------------- DISCOVERY (subnet sweep config + register) ---------------- #
# The app stores discovery settings here; the Node-RED collector reads them,
# sweeps the subnet (fping), and posts the alive IPs back to /discovery/register.

_DISCOVERY_DEFAULT = {
    "id": "default", "subnet": "", "community": "public", "snmp_version": "2c",
    "default_type": "switch", "enabled": False, "run_requested": False,
    "last_run": None, "last_found": 0, "last_created": 0, "last_message": "",
}


async def _get_discovery_doc():
    doc = await db.discovery.find_one({"id": "default"}, {"_id": 0})
    if not doc:
        await db.discovery.insert_one(dict(_DISCOVERY_DEFAULT))
        doc = await db.discovery.find_one({"id": "default"}, {"_id": 0})
    return doc


COMMUNITY_MASK = "********"


def _discovery_view(doc: dict, request: Request) -> dict:
    """Hide the SNMP community from UI users (issue #7). The collector (valid
    X-Ingest-Token) gets the real value. Without INGEST_TOKEN the collector
    cannot be told apart, so the value stays visible for backward compatibility."""
    if doc and doc.get("community") and auth.INGEST_TOKEN and not getattr(request.state, "collector", False):
        doc = {**doc, "community": COMMUNITY_MASK}
    return doc


@router.get("/discovery")
async def get_discovery(request: Request):
    return _discovery_view(await _get_discovery_doc(), request)


@router.put("/discovery")
async def update_discovery(patch: DiscoveryUpdate, request: Request):
    await _get_discovery_doc()
    fields = {k: v for k, v in patch.model_dump().items() if v is not None}
    if fields.get("community") == COMMUNITY_MASK:
        fields.pop("community")  # UI sent back the mask unchanged -> keep stored value
    if fields:
        await db.discovery.update_one({"id": "default"}, {"$set": fields})
    return _discovery_view(await db.discovery.find_one({"id": "default"}, {"_id": 0}), request)


@router.post("/discovery/register")
async def discovery_register(payload: DiscoveryRegister):
    """Register newly-found IPs as minimal devices (skip existing). Called by the
    Node-RED discovery collector after an fping sweep. Also clears run_requested
    and records the run summary."""
    cfg = await _get_discovery_doc()
    dtype = cfg.get("default_type") or "switch"
    existing = set()
    async for d in db.devices.find({}, {"_id": 0, "ip": 1}):
        if d.get("ip"):
            existing.add(d["ip"])
    created = 0
    new_ips = []
    for raw in payload.ips:
        ip = (raw or "").strip()
        if not ip or ip in existing or not _valid_ip(ip):
            continue
        dev = Device(name=ip, ip=ip, vendor="unknown", model="unknown",
                     protocol="snmp", device_type=dtype, status="online")
        await db.devices.insert_one(dev.model_dump())
        existing.add(ip)
        new_ips.append(ip)
        created += 1
    now = datetime.now(timezone.utc).isoformat()
    await db.discovery.update_one({"id": "default"}, {"$set": {
        "run_requested": False, "last_run": now,
        "last_found": len(payload.ips), "last_created": created,
        "last_message": f"{len(payload.ips)} alive, {created} new",
    }})
    return {"found": len(payload.ips), "created": created, "new_ips": new_ips}
