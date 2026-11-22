"""Store discoveries separately from the inventory until an operator approves them."""
from uuid import uuid4

from netvision.database import db
from netvision.devices import _ip_taken
from netvision.helpers import _utc_now_iso, _valid_ipv4


async def queue_address(site_id: str, ip: str, device_type: str = "switch") -> bool:
    ip = ip.strip()
    if not _valid_ipv4(ip) or await _ip_taken(ip, site_id=site_id):
        return False
    result = await db.discovery_candidates.update_one(
        {"_id": f"{site_id}/{ip}"},
        {"$setOnInsert": {"id": str(uuid4()), "site_id": site_id, "ip": ip, "device_type": device_type},
         "$set": {"observed_at": _utc_now_iso()}},
        upsert=True,
    )
    return result.upserted_id is not None
