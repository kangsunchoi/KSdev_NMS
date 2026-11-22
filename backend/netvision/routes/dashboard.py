"""Zone counts and the dashboard summary."""
from fastapi import APIRouter

from netvision.database import db
from netvision.summary import summarize_devices

router = APIRouter()


# Zones list
@router.get("/zones")
async def list_zones():
    devices = await db.devices.find({}, {"_id": 0, "zone": 1, "status": 1}).to_list(None)
    counts: dict[str, dict] = {}
    for d in devices:
        z = d.get("zone")
        if not z:
            continue
        c = counts.setdefault(z, {"name": z, "total": 0, "online": 0, "warning": 0, "critical": 0})
        c["total"] += 1
        if d["status"] == "online":
            c["online"] += 1
        elif d["status"] == "warning":
            c["warning"] += 1
        else:
            c["critical"] += 1
    return sorted(counts.values(), key=lambda x: x["name"])


# Dashboard summary
@router.get("/dashboard/summary")
async def dashboard_summary():
    devices = await db.devices.find({}, {"_id": 0}).to_list(None)
    return await summarize_devices(devices)
