"""The 5-second background loop (simulation tick, stale sweep, retention purge,
periodic WebSocket snapshot)."""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from netvision import config, ws  # first: loads .env before notify reads env
import notify  # noqa: E402
from netvision.database import db
from netvision.monitoring import _stale_sweep
from netvision.simulation import _simulate_tick


async def metrics_loop():
    """Runs every 5s. Generates data only in simulation mode; always purges old
    acknowledged alerts and broadcasts a fresh snapshot so dashboards stay live
    whether data comes from the simulator or from /api/ingest."""
    while True:
        try:
            await asyncio.sleep(5)
            config._TICK += 1

            if config.sim_on():
                await _simulate_tick()

            await _stale_sweep()
            await notify.flush_suppressed()

            # purge closed (acknowledged/resolved) alerts older than the retention period
            # (counted from when the alert was CLOSED, not created)
            cutoff = (datetime.now(timezone.utc) - timedelta(days=config.ALERT_RETENTION_DAYS)).isoformat()
            await db.alerts.delete_many({"acknowledged": True, "$or": [
                {"resolved_at": {"$lt": cutoff}},
                {"resolved_at": None, "acknowledged_at": {"$lt": cutoff}},
                {"resolved_at": None, "acknowledged_at": None, "timestamp": {"$lt": cutoff}},
            ]})

            # Broadcast snapshot to WS clients
            if ws.ws_manager.clients:
                snap = await ws._build_snapshot()
                await ws.ws_manager.broadcast(snap)
        except Exception as e:
            logging.exception("metrics loop error: %s", e)
