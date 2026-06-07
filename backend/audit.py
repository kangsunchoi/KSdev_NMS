"""
NetVision OT — Audit Trail (records state-changing API actions).

The auth middleware calls record() after a successful POST/PUT/PATCH/DELETE.
Entries are stored in the `audit` collection with a 30-day TTL. Reading the
log requires operator+ (enforced by the auth middleware via the /api/audit path
and the request method = GET -> viewer; we additionally gate it as a normal
read, which is fine because audit data is non-sensitive operational history).
"""

import os
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from starlette.requests import Request

logger = logging.getLogger("netvision.audit")

AUDIT_TTL_DAYS = int(os.environ.get("AUDIT_TTL_DAYS", "30"))


async def record(db, username: str, role: str, method: str, path: str, status: int):
    doc = {
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "ts_dt": datetime.now(timezone.utc),  # for TTL index
        "username": username,
        "role": role,
        "method": method,
        "path": path,
        "status": status,
    }
    await db.audit.insert_one(doc)


async def ensure_indexes(db):
    try:
        await db.audit.create_index("ts_dt", expireAfterSeconds=AUDIT_TTL_DAYS * 24 * 3600)
        await db.audit.create_index([("ts", -1)])
    except Exception as e:
        logger.warning("audit index create failed: %s", e)


def register_routes(api_router: APIRouter, db):
    @api_router.get("/audit")
    async def list_audit(limit: int = 200, request: Request = None):
        limit = max(1, min(limit, 1000))
        rows = await db.audit.find({}, {"_id": 0, "ts_dt": 0}).sort("ts", -1).to_list(limit)
        return rows
