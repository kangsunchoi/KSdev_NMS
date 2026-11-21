"""WebSocket client registry, coalesced broadcast (#16) and the snapshot payload."""
import asyncio
import json
import logging
from typing import Optional

from fastapi import WebSocket

from netvision import config
from netvision.alerts import _recent_alerts
from netvision.database import db
from netvision.monitoring import _collector_status


class WSManager:
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def broadcast(self, payload: dict):
        if not self.clients:
            return
        msg = json.dumps(payload, default=str)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


ws_manager = WSManager()

# Coalesced broadcasting (issue #16): collectors may post many times per second;
# build and send at most one snapshot per config.BROADCAST_DEBOUNCE_SEC.
_broadcast_task: Optional[asyncio.Task] = None


_broadcast_dirty = False


async def _delayed_broadcast():
    global _broadcast_dirty
    try:
        while True:
            # wait before every snapshot, so constant ingest caps the rate at ~1/(debounce+build)
            await asyncio.sleep(config.BROADCAST_DEBOUNCE_SEC)
            _broadcast_dirty = False
            if ws_manager.clients:
                await ws_manager.broadcast(await _build_snapshot())
            if not _broadcast_dirty:  # nothing changed while the snapshot was being built
                break
    except Exception:
        logging.exception("coalesced broadcast failed")


def _schedule_broadcast():
    global _broadcast_task
    if not ws_manager.clients:
        return
    global _broadcast_dirty
    if _broadcast_task is not None and not _broadcast_task.done():
        _broadcast_dirty = True  # picked up by the pending task (even mid-snapshot)
        return
    _broadcast_task = asyncio.create_task(_delayed_broadcast())


async def _build_snapshot() -> dict:
    devices = await db.devices.find({}, {"_id": 0}).to_list(None)
    alerts = await _recent_alerts(200)
    total = len(devices)
    online = sum(1 for d in devices if d["status"] == "online")
    warning = sum(1 for d in devices if d["status"] == "warning")
    critical = sum(1 for d in devices if d["status"] in ("critical", "offline"))
    open_alerts = await db.alerts.count_documents({"acknowledged": False})
    critical_alerts = await db.alerts.count_documents({"acknowledged": False, "severity": "critical"})
    if total == 0:
        health = 100
    else:
        score = (online * 100 + warning * 60 + critical * 0) / total
        score -= min(critical_alerts * 3, 25)
        health = max(0, min(100, round(score)))
    avg_lat = round(sum(d.get("latency_ms", 0) for d in devices) / total, 2) if total else 0.0
    avg_pl = round(sum(d.get("packet_loss", 0) for d in devices) / total, 2) if total else 0.0
    return {
        "type": "tick",
        "summary": {
            "total": total, "online": online, "warning": warning, "critical": critical,
            "open_alerts": open_alerts, "critical_alerts": critical_alerts,
            "health_score": health, "avg_latency_ms": avg_lat, "avg_packet_loss": avg_pl,
            **_collector_status(),
            "alerts_truncated": open_alerts > config.OPEN_ALERTS_CAP,
        },
        "devices": devices,
        "alerts": alerts,
    }
