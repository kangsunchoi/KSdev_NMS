"""Device CRUD, selective cleanup and per-device metric history."""
from datetime import datetime, timezone, timedelta
from typing import List

from fastapi import APIRouter, HTTPException

from netvision.database import db
from netvision.devices import _cascade_delete_devices, _ip_taken
from netvision.helpers import _is_placeholder, _normalize_ip, _valid_ip
from netvision.models import CleanupPayload, Device, DeviceCreate, DeviceUpdate

router = APIRouter()


@router.get("/")
async def root():
    return {"service": "NetVision OT", "status": "ok"}


# Devices CRUD
@router.get("/devices", response_model=List[Device])
async def list_devices():
    docs = await db.devices.find({}, {"_id": 0}).to_list(None)
    return docs


@router.post("/devices", response_model=Device)
async def create_device(payload: DeviceCreate):
    if await _ip_taken(payload.ip):
        raise HTTPException(409, f"A device with IP {payload.ip} already exists")
    dev = Device(**payload.model_dump())
    await db.devices.insert_one(dev.model_dump())
    return dev


@router.get("/devices/{device_id}", response_model=Device)
async def get_device(device_id: str):
    doc = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Device not found")
    return doc


@router.patch("/devices/{device_id}", response_model=Device)
async def update_device(device_id: str, payload: DeviceUpdate):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(400, "Empty update")
    if "name" in update:
        update["name"] = update["name"].strip()
        if not update["name"]:
            raise HTTPException(422, "name must not be empty")
    current = await db.devices.find_one({"id": device_id}, {"_id": 0, "ip": 1})
    if not current:
        raise HTTPException(404, "Device not found")
    if "ip" in update:
        new_ip = update["ip"].strip()
        if new_ip == (current.get("ip") or ""):
            # unchanged: never block editing other fields of a legacy device whose
            # stored IP is invalid or duplicated (data from before validation existed)
            update.pop("ip")
        else:
            if not _valid_ip(new_ip):
                raise HTTPException(422, "ip must be a valid IPv4/IPv6 address")
            if _is_placeholder(new_ip):
                raise HTTPException(422, "0.0.0.0 / :: is reserved for auto-created devices")
            new_ip = _normalize_ip(new_ip)
            if await _ip_taken(new_ip, exclude_id=device_id):
                raise HTTPException(409, f"A device with IP {new_ip} already exists")
            update["ip"] = new_ip
    if not update:  # only the unchanged ip was sent
        return await db.devices.find_one({"id": device_id}, {"_id": 0})
    result = await db.devices.update_one({"id": device_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(404, "Device not found")
    doc = await db.devices.find_one({"id": device_id}, {"_id": 0})
    return doc


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str):
    if await _cascade_delete_devices([device_id]) == 0:
        raise HTTPException(404, "Device not found")
    return {"deleted": device_id}


@router.post("/devices/cleanup")
async def cleanup_devices(payload: CleanupPayload):
    prefixes = [p for p in (payload.name_prefixes or []) if p]
    ipp = (payload.ip_prefix or "").strip()

    def _matches(d: dict) -> bool:
        name = d.get("name") or ""
        ip = d.get("ip") or ""
        name_ok = any(name.startswith(p) for p in prefixes) if prefixes else None
        ip_ok = ip.startswith(ipp) if ipp else None
        checks = [c for c in (name_ok, ip_ok) if c is not None]
        if not checks:
            return False
        return all(checks)

    all_devs = await db.devices.find({}, {"_id": 0}).to_list(None)
    matched = [d for d in all_devs if _matches(d)]
    preview = [{"id": d["id"], "name": d.get("name"), "ip": d.get("ip"),
                "device_type": d.get("device_type")} for d in matched]

    if payload.dry_run:
        return {"dry_run": True, "matched": len(matched), "devices": preview}

    ids = [d["id"] for d in matched]
    await _cascade_delete_devices(ids)
    return {"dry_run": False, "deleted": len(ids), "devices": preview}


# Device metric history (last N hours, default 24h)
@router.get("/devices/{device_id}/metrics")
async def device_metrics(device_id: str, hours: int = 24):
    exists = await db.devices.find_one({"id": device_id}, {"_id": 0, "id": 1})
    if not exists:
        raise HTTPException(404, "Device not found")
    hours = max(1, min(hours, 168))
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    cursor = db.device_metrics.find(
        {"device_id": device_id, "ts": {"$gte": since}},
        {"_id": 0},
    ).sort("ts", 1)
    points = await cursor.to_list(20000)
    return {"device_id": device_id, "hours": hours, "points": points}
