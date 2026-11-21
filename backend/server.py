"""NetVision OT API — application assembly.

Entry point stays ``uvicorn server:app``. The code lives in the ``netvision``
package (issue #17):

  netvision/config.py      settings + mutable runtime state (read as config.NAME)
  netvision/database.py    Mongo client, indexes, bulk-write helper
  netvision/helpers.py     IP / timestamp helpers
  netvision/models.py      pydantic models
  netvision/alerts.py      alert lifecycle
  netvision/monitoring.py  status judgment, stale sweep, collector health
  netvision/devices.py     device lookup / cascades / IP migration
  netvision/simulation.py  mock generator + simulator tick
  netvision/ws.py          WebSocket manager, coalesced broadcast, snapshot
  netvision/background.py  5s metrics loop
  netvision/routes/*.py    one APIRouter per feature
"""
import asyncio
import logging
import os

from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware

# config runs load_dotenv(); it MUST be imported before auth/audit/notify, which
# read environment variables at import time.
from netvision import config
import auth      # noqa: E402  (authentication / RBAC / audit middleware)
import audit     # noqa: E402  (audit trail)
from netvision.background import metrics_loop  # noqa: E402
from netvision import database  # noqa: E402
from netvision.devices import _normalize_stored_ips  # noqa: E402
from netvision.routes import (alerts, dashboard, devices, discovery, ingest, realtime,  # noqa: E402
                              sim, topology)
from netvision.simulation import _ensure_seed  # noqa: E402

app = FastAPI(title="NetVision OT API")
api_router = APIRouter(prefix="/api")

# Feature routers, in the order their first route appeared in the old server.py.
for _feature in (devices, discovery, ingest, alerts, topology, dashboard, sim, realtime):
    api_router.include_router(_feature.router)
del _feature

# Mutable state lives in netvision.config / netvision.ws / netvision.database and is
# NOT re-exported here: monkeypatching a copy on this module would silently do
# nothing, so such a patch fails loudly (AttributeError) instead. Patch the owner
# module (e.g. netvision.config._SIM_OVERRIDE, netvision.ws._build_snapshot).


# ---------------- APP WIRING ---------------- #

# Auth & audit endpoints must be attached to api_router BEFORE include_router.
auth.register_routes(api_router, database.db)
audit.register_routes(api_router, database.db)

app.include_router(api_router)

# Auth + RBAC + audit middleware. Registered BEFORE CORS so that CORS stays the
# OUTERMOST layer (every response, including 401/403, keeps its CORS headers).
auth.register_middleware(app, database.db, audit_module=audit)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def startup():
    await database._ensure_indexes()
    await _normalize_stored_ips()
    # One-time migration: alerts created before the lifecycle fields existed (issue #10)
    await database.db.alerts.update_many({"state": {"$exists": False}, "acknowledged": True},
                                         {"$set": {"state": "acknowledged"}})
    await database.db.alerts.update_many({"state": {"$exists": False}}, {"$set": {"state": "active"}})
    # Audit indexes (always) + default admin (only when AUTH_ENABLED and no users yet).
    await audit.ensure_indexes(database.db)
    await auth.ensure_default_admin(database.db)
    auth.startup_warnings()
    # Only auto-seed mock devices in simulation mode
    if config.sim_on():
        await _ensure_seed()
    asyncio.create_task(metrics_loop())
    logger.info("NetVision OT started — mode=%s", "simulation" if config.sim_on() else "live(ingest)")


@app.on_event("shutdown")
async def shutdown_db_client():
    database.client.close()
