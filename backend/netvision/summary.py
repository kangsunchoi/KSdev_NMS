"""Fleet summary shared by HTTP and live dashboard snapshots."""
from netvision import config
from netvision.database import db
from netvision.monitoring import _collector_status


async def summarize_devices(devices: list[dict]) -> dict:
    total = len(devices)
    online = sum(1 for d in devices if d["status"] == "online")
    warning = sum(1 for d in devices if d["status"] == "warning")
    critical = sum(1 for d in devices if d["status"] in ("critical", "offline"))

    open_alerts = await db.alerts.count_documents({"acknowledged": False})
    active_alerts = await db.alerts.count_documents({"state": {"$ne": "resolved"}})
    critical_alerts = await db.alerts.count_documents({"state": {"$ne": "resolved"}, "severity": "critical"})

    # Health score: online weighted +, warning slight -, critical heavy -
    if total == 0:
        health = 100
    else:
        score = (online * 100 + warning * 60 + critical * 0) / total
        score -= min(critical_alerts * 3, 25)
        health = max(0, min(100, round(score)))

    latencies = [d["latency_ms"] for d in devices if d.get("latency_ms") is not None]
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else None
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
        "latency_sample_count": len(latencies),
        "avg_packet_loss": avg_packet_loss,
        **_collector_status(),
        "alerts_truncated": active_alerts > config.OPEN_ALERTS_CAP,
    }
