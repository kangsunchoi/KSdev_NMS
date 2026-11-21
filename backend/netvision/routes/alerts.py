"""Alert list/history, acknowledge (single and bulk) and delete."""
from datetime import datetime, timezone, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException

from netvision.alerts import _recent_alerts
from netvision.database import db
from netvision.helpers import _utc_now_iso
from netvision.models import Alert, AlertSeverity, BulkAckPayload

router = APIRouter()


@router.get("/alerts", response_model=List[Alert])
async def list_alerts(limit: int = 200):
    return await _recent_alerts(max(1, min(limit, 1000)))


@router.get("/alerts/history")
async def alerts_history(
    state: Optional[Literal["active", "acknowledged", "resolved"]] = None,
    severity: Optional[AlertSeverity] = None,
    device_id: Optional[str] = None,
    hours: int = 24 * 7,
    page: int = 1,
    page_size: int = 100,
):
    """Paged alert history over the retention period (issue #24)."""
    hours = max(1, min(hours, 24 * 366))
    page = max(1, page)
    page_size = max(1, min(page_size, 500))
    q: dict = {"timestamp": {"$gte": (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()}}
    if state:
        q["state"] = state
    if severity:
        q["severity"] = severity
    if device_id:
        q["device_id"] = device_id
    total = await db.alerts.count_documents(q)
    items = await (db.alerts.find(q, {"_id": 0}).sort([("timestamp", -1), ("id", -1)])
                   .skip((page - 1) * page_size).limit(page_size).to_list(page_size))
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": (total + page_size - 1) // page_size}


@router.post("/alerts/{alert_id}/acknowledge", response_model=Alert)
async def acknowledge_alert(alert_id: str):
    if not await db.alerts.find_one({"id": alert_id}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Alert not found")
    # only an ACTIVE alert becomes "acknowledged"; acknowledged/resolved ones are unchanged
    await db.alerts.update_one(
        {"id": alert_id, "state": "active"},
        {"$set": {"acknowledged": True, "state": "acknowledged", "acknowledged_at": _utc_now_iso()}},
    )
    doc = await db.alerts.find_one({"id": alert_id}, {"_id": 0})
    return doc


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str):
    result = await db.alerts.delete_one({"id": alert_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Alert not found")
    return {"deleted": alert_id}


@router.post("/alerts/bulk-acknowledge")
async def bulk_ack(payload: BulkAckPayload):
    q: dict = {"acknowledged": False}
    if payload.ids:
        q["id"] = {"$in": payload.ids}
    result = await db.alerts.update_many(
        q, {"$set": {"acknowledged": True, "state": "acknowledged", "acknowledged_at": _utc_now_iso()}})
    return {"acknowledged": result.modified_count}
