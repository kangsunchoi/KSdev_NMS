"""MongoDB client, index definitions and bulk-write helper."""
import logging
import os
from typing import List

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne

from netvision import config  # noqa: F401  (load_dotenv before reading MONGO_URL)

# same logger name as before the split (server.py used logging.getLogger(__name__))
logger = logging.getLogger("server")

mongo_url = os.environ['MONGO_URL']
if mongo_url.startswith("mongomock://"):
    # Test-only in-memory MongoDB (pip install mongomock-motor). Never used in production.
    from mongomock_motor import AsyncMongoMockClient
    client = AsyncMongoMockClient()
else:
    client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

_METRIC_TTL_SEC = 24 * 60 * 60  # 24h


async def _apply_updates(coll, pairs: List[tuple], ordered: bool = True):
    """Apply (filter, update) pairs in ONE bulk round-trip (issue #16).
    The in-memory test DB (mongomock) does not support current pymongo bulk ops,
    so it falls back to sequential updates there."""
    if not pairs:
        return
    if mongo_url.startswith("mongomock://"):
        for f, u in pairs:
            await coll.update_one(f, u)
        return
    await coll.bulk_write([UpdateOne(f, u) for f, u in pairs], ordered=ordered)


_INDEXES = [
    # (collection, keys, options). Each one is created on its own, so one failure
    # (e.g. legacy duplicate ids blocking a unique index) never skips the rest.
    ("device_metrics", "ts_dt", {"expireAfterSeconds": _METRIC_TTL_SEC}),
    ("device_metrics", [("device_id", 1), ("ts", 1)], {}),
    ("devices", "ip", {}),  # speed up ingest lookups by IP
    ("devices", "name", {}),
    ("links", [("source_id", 1), ("target_id", 1)], {"unique": True}),
    ("unified_metrics", "ts_dt", {"expireAfterSeconds": _METRIC_TTL_SEC}),
    ("unified_metrics", [("device_id", 1), ("metric_name", 1), ("ts", 1)], {}),
    ("device_kv", [("device_id", 1), ("metric_name", 1)], {"unique": True}),
    # alerts: counted every 5s and on every ingest; history is kept for days now
    ("alerts", [("acknowledged", 1), ("severity", 1)], {}),
    ("alerts", [("device_id", 1), ("severity", 1), ("timestamp", -1)], {}),
    ("alerts", [("timestamp", -1)], {}),
    ("alerts", "id", {"unique": True}),
    ("devices", "id", {"unique": True}),
]


async def _ensure_indexes() -> list:
    """Create every index independently; return the ones that failed."""
    failed = []
    for coll, keys, opts in _INDEXES:
        try:
            await db[coll].create_index(keys, **opts)
        except Exception as e:
            failed.append((coll, keys))
            logger.warning("index create failed on %s %s: %s", coll, keys, e)
            if coll == "devices" and keys == "id":
                try:
                    dups = await db.devices.aggregate([
                    {"$group": {"_id": "$id", "n": {"$sum": 1}}}, {"$match": {"n": {"$gt": 1}}},
                        {"$limit": 20}]).to_list(20)
                    logger.warning("duplicate device ids blocking the unique index: %s",
                                   [d["_id"] for d in dups])
                except Exception:
                    pass
    return failed
