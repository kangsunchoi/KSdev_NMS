"""Alert lifecycle: create (debounced, RCA-annotated), auto-resolve, live list."""
from datetime import datetime, timezone, timedelta
from typing import List

from netvision import config  # first: loads .env before notify reads env
import notify  # noqa: E402
from netvision.database import db
from netvision.helpers import _utc_now_iso
from netvision.models import Alert, AlertSeverity


ALERT_DEBOUNCE_SEC = 60


async def _create_alert(device: dict, severity: AlertSeverity, message: str, force: bool = False):
    """Insert alert unless a same-device-same-severity alert exists in the last ALERT_DEBOUNCE_SEC."""
    if device["id"] == "collector":  # COLLECTOR_ALERT_ID: keep a single open alert
        if await db.alerts.find_one({"device_id": "collector", "acknowledged": False}, {"_id": 0, "id": 1}):
            return None
    if not force:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=ALERT_DEBOUNCE_SEC)).isoformat()
        recent = await db.alerts.find_one(
            # only an OPEN alert suppresses a new one: after offline->online->offline the
            # first alert is already resolved and the new outage must be visible (#36)
            {"device_id": device["id"], "severity": severity, "acknowledged": False,
             "timestamp": {"$gte": cutoff}},
            {"_id": 0, "id": 1},
        )
        if recent:
            return None
    alert = Alert(
        device_id=device["id"],
        device_name=device["name"],
        severity=severity,
        message=message,
    )
    doc = alert.model_dump()
    # RCA: if this device has a parent that is already down, annotate the alert
    # as correlated to that upstream outage. Annotation only — nothing existing
    # is suppressed or altered.
    if config.RCA_ENABLED and device.get("parent_id"):
        parent = await db.devices.find_one(
            {"id": device["parent_id"]}, {"_id": 0, "status": 1}
        )
        if parent and parent.get("status") in ("offline", "critical"):
            doc["correlated_to"] = device["parent_id"]
    await db.alerts.insert_one(doc)
    # Fire-and-forget notification (silent no-op unless a channel is configured).
    await notify.notify_alert(doc)
    return alert


async def _resolve_device_alerts(device_id: str) -> int:
    """Auto-resolve: when a device recovers to 'online', mark its still-open
    alerts as acknowledged so they drop out of the active list (the periodic
    2h purge then removes them). Returns how many alerts were resolved.

    Shared by both the simulator and the live ingestion path so recovery
    behaves identically regardless of where the data came from.
    """
    now = _utc_now_iso()
    result = await db.alerts.update_many(
        {"device_id": device_id, "state": {"$in": ["active", "acknowledged"]}, "resolved_at": None},
        {"$set": {"acknowledged": True, "state": "resolved", "resolved_at": now}},
    )
    # legacy rows created before the lifecycle fields existed
    legacy = await db.alerts.update_many(
        {"device_id": device_id, "acknowledged": False, "state": {"$exists": False}},
        {"$set": {"acknowledged": True, "state": "resolved", "resolved_at": now}},
    )
    return result.modified_count + legacy.modified_count


async def _recent_alerts(limit: int = 200) -> List[dict]:
    """Live view: open alerts (up to OPEN_ALERTS_CAP, newest first) plus the most
    recent closed ones up to `limit` rows in total (issue #24)."""
    open_docs = await (db.alerts.find({"acknowledged": False}, {"_id": 0}).sort("timestamp", -1)
                       .limit(config.OPEN_ALERTS_CAP).to_list(config.OPEN_ALERTS_CAP))
    room = max(0, limit - len(open_docs))
    closed = []
    if room:
        closed = await (db.alerts.find({"acknowledged": True}, {"_id": 0}).sort("timestamp", -1)
                        .limit(room).to_list(room))
    return sorted(open_docs + closed, key=lambda a: a.get("timestamp", ""), reverse=True)
