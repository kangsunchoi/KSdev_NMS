"""Status judgment shared by simulator and ingest, stale detection (#9) and
collector health."""
from datetime import datetime, timezone

from netvision import config
from netvision.alerts import _create_alert, _resolve_device_alerts
from netvision.database import db
from netvision.helpers import _parse_ts, _utc_now_iso


def _derive_status(prev_status: str, candidate: str, latency: float | None, ploss: float) -> str:
    """Deterministic status derivation from metrics.

    Extracted verbatim from the original simulation loop so that BOTH the
    simulator and the live ingestion path judge status identically.
    `candidate` is the starting status (for the simulator this may already
    reflect its rare random flip; for ingestion it equals prev_status).
    """
    new_status = candidate
    if prev_status != "offline":
        if ploss > 8 or (latency is not None and latency > 80):
            new_status = "critical"
        elif ploss > 4 or (latency is not None and latency > 45):
            new_status = "warning"
        elif ploss < 1.5 and latency is not None and latency < 25:
            new_status = "online"
    return new_status


def _worsen_message(name: str, new_status: str, latency: float | None, ploss: float) -> str:
    """Alert text for a worsening transition (same wording as the simulator)."""
    detail = f"latency {latency:.1f}ms" if latency is not None else f"packet loss {ploss:.1f}%"
    return {
        "warning": f"{name}: degraded performance ({detail})",
        "critical": f"{name}: critical state (packet loss {round(ploss, 1)}%)",
        "offline": f"{name}: lost contact",
    }.get(new_status, "Anomaly")


def _metric_doc(device_id: str, ts_iso: str, latency: float | None, ploss: float, cpu: float, status: str) -> dict:
    """Build one time-series history point (same shape used by the simulator)."""
    return {
        "device_id": device_id,
        "ts": ts_iso,
        "ts_dt": datetime.now(timezone.utc),  # for TTL index
        "latency_ms": round(latency, 2) if latency is not None else None,
        "packet_loss": round(ploss, 2),
        "cpu_pct": round(cpu, 1),
        "status": status,
    }


async def _recover_if_stale(dev: dict) -> bool:
    """A device marked offline only because data stopped (stale) comes back
    when ANY collector data arrives: ingest, generic metrics or interfaces (#25)."""
    if not (dev.get("stale") and dev.get("status") == "offline"):
        return False
    # set last_seen in the SAME update: otherwise the stale sweep can run between
    # recovery and the caller's last_seen write and mark the device stale again
    res = await db.devices.update_one({"id": dev["id"], "stale": True},
                                      {"$set": {"status": "online", "stale": False, "last_seen": _utc_now_iso()}})
    if res.modified_count:
        await _resolve_device_alerts(dev["id"])
        return True
    return False


def _collector_status() -> dict:
    """Is the collector (Node-RED) still sending? Only meaningful in live mode."""
    stale = False
    if not config.sim_on() and config.STALE_AFTER_SEC > 0:
        last = _parse_ts(config._LAST_INGEST_TS)
        ref = last or config._STARTED_AT
        stale = (datetime.now(timezone.utc) - ref).total_seconds() > config.STALE_AFTER_SEC
    return {"collector_stale": stale, "last_ingest_ts": config._LAST_INGEST_TS}


COLLECTOR_ALERT_ID = "collector"  # pseudo device id for the single "collector stopped" alert


async def _stale_sweep() -> int:
    """Live mode: mark devices with no data for STALE_AFTER_SEC as offline (issue #9).

    - Ages are measured from max(last_seen, process start): after a restart/outage
      of the backend itself, devices get a full STALE_AFTER_SEC grace period.
    - If the WHOLE collector is silent, raise one "collector stopped" alert instead
      of one alert per device (one root cause).
    """
    if config.sim_on() or config.STALE_AFTER_SEC <= 0:
        return 0
    now = datetime.now(timezone.utc)
    collector_down = _collector_status()["collector_stale"]
    marked = 0
    async for d in db.devices.find({"status": {"$ne": "offline"}}, {"_id": 0}):
        seen = _parse_ts(d.get("last_seen"))
        ref = max(seen, config._STARTED_AT) if seen else config._STARTED_AT
        if (now - ref).total_seconds() <= config.STALE_AFTER_SEC:
            continue
        # filter on the last_seen we read: if an ingest landed meanwhile, do nothing
        res = await db.devices.update_one(
            {"id": d["id"], "status": {"$ne": "offline"}, "last_seen": d.get("last_seen")},
            {"$set": {"status": "offline", "stale": True}},
        )
        if res.modified_count:
            marked += 1
            if not collector_down:
                age = int((now - (seen or config._STARTED_AT)).total_seconds())
                await _create_alert(d, "critical", f"{d['name']}: no data from collector for {age}s")
    if collector_down:
        last = config._LAST_INGEST_TS or "never"
        await _create_alert(
            {"id": COLLECTOR_ALERT_ID, "name": "Collector (Node-RED)"}, "critical",
            f"Collector (Node-RED): no data received since {last}", force=False,
        )
    return marked
