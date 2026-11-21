"""Zone counts and the dashboard summary."""
from fastapi import APIRouter

from netvision import config
from netvision.database import db
from netvision.monitoring import _collector_status

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
    total = len(devices)
    online = sum(1 for d in devices if d["status"] == "online")
    warning = sum(1 for d in devices if d["status"] == "warning")
    critical = sum(1 for d in devices if d["status"] in ("critical", "offline"))

    open_alerts = await db.alerts.count_documents({"acknowledged": False})
    critical_alerts = await db.alerts.count_documents({"acknowledged": False, "severity": "critical"})

    # Health score: online weighted +, warning slight -, critical heavy -
    if total == 0:
        health = 100
    else:
        score = (online * 100 + warning * 60 + critical * 0) / total
        score -= min(critical_alerts * 3, 25)
        health = max(0, min(100, round(score)))

    avg_latency = round(sum(d.get("latency_ms", 0) for d in devices) / total, 2) if total else 0.0
    avg_packet_loss = round(sum(d.get("packet_loss", 0) for d in devices) / total, 2) if total else 0.0

    return {
        "total": total,
        "online": online,
        "warning": warning,
        "critical": critical,
        "open_alerts": open_alerts,
        "critical_alerts": critical_alerts,
        "health_score": health,
        "avg_latency_ms": avg_latency,
        "avg_packet_loss": avg_packet_loss,
        **_collector_status(),
        "alerts_truncated": open_alerts > config.OPEN_ALERTS_CAP,
    }
