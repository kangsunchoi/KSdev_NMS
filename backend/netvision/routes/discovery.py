"""Discovery settings (read by the Node-RED collector) and alive-IP registration."""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pymongo.errors import DuplicateKeyError

import auth
from netvision.database import db
from netvision.devices import site_query
from netvision.discovery_queue import queue_address
from netvision.helpers import _valid_ipv4
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
        await db.discovery.update_one({"id": "default"}, {"$setOnInsert": _DISCOVERY_DEFAULT}, upsert=True)
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
    """Record unique IPv4 observations for operator review."""
    cfg = await _get_discovery_doc()
    dtype = cfg.get("default_type") or "switch"
    ips = dict.fromkeys(raw.strip() for raw in payload.ips if _valid_ipv4(raw))
    new_ips = []
    for ip in ips:
        if await queue_address(payload.site_id, ip, dtype):
            new_ips.append(ip)
    now = datetime.now(timezone.utc).isoformat()
    await db.discovery.update_one({"id": "default"}, {"$set": {
        "run_requested": False, "last_run": now,
        "last_found": len(ips), "last_created": 0, "last_queued": len(new_ips),
        "last_message": f"{len(ips)} IPv4, {len(new_ips)} pending approval",
    }})
    return {"found": len(ips), "created": 0, "queued": len(new_ips), "new_ips": new_ips}


@router.get("/discovery/candidates")
async def list_candidates():
    return await db.discovery_candidates.find({}, {"_id": 0}).sort([("site_id", 1), ("ip", 1)]).to_list(None)


@router.post("/discovery/candidates/{candidate_id}/approve", response_model=Device)
async def approve_candidate(candidate_id: str):
    candidate = await db.discovery_candidates.find_one({"id": candidate_id})
    if not candidate:
        device = await db.devices.find_one({"id": candidate_id})
        if device:
            return device
        raise HTTPException(404, "Discovery candidate not found")
    site_id, ip = candidate["site_id"], candidate["ip"]
    address = {"ip": ip, **site_query(site_id)}
    device = await db.devices.find_one(address)
    if not device:
        dev = Device(id=candidate_id, name=ip, ip=ip, site_id=site_id, vendor="unknown", model="unknown",
                     protocol="snmp", device_type=candidate["device_type"], status="offline",
                     last_seen=candidate["observed_at"])
        try:
            await db.devices.insert_one({**dev.model_dump(), "managed_address": candidate["_id"]})
            device = dev
        except DuplicateKeyError:
            device = await db.devices.find_one(address)
            if not device:
                raise HTTPException(409, "Device changed during approval; refresh inventory") from None
    await db.discovery_candidates.delete_one({"id": candidate_id})
    return device
