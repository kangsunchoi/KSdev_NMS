"""WebSocket client registry, coalesced broadcast (#16) and the snapshot payload."""
import asyncio
import json
import logging
from typing import Optional

from fastapi import WebSocket

from netvision import config
from netvision.alerts import _recent_alerts
from netvision.database import db
from netvision.summary import summarize_devices


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
    return {
        "type": "tick",
        "summary": await summarize_devices(devices),
        "devices": devices,
        "alerts": alerts,
    }
