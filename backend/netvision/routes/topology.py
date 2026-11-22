"""Topology graph (zones, parent edges, LLDP links, unmanaged segments, assets) and
LLDP/CDP neighbor links."""
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter

from netvision import config
from netvision.database import db
from netvision.devices import _find_device
from netvision.models import LinksPayload

router = APIRouter()


def _compute_unmanaged_segments(device_ids: set, fdb_docs: list, links: list, min_macs: int):
    """Pure function: derive unmanaged-segment nodes/edges from FDB + LLDP links.

    A (switch, port) becomes a segment when it forwards >= min_macs distinct MACs
    AND has no LLDP/CDP neighbor on that port (i.e. nothing manageable is there).
    """
    lldp_ports = set()
    for lk in links:
        if lk.get("source_id") and lk.get("source_port"):
            lldp_ports.add((lk["source_id"], lk["source_port"]))
    seg_nodes, seg_edges = [], []
    for fdb in fdb_docs:
        sw = fdb.get("device_id")
        if sw not in device_ids:
            continue
        for port, macs in (fdb.get("ports") or {}).items():
            uniq = list({m for m in (macs or []) if m})
            if len(uniq) >= min_macs and (sw, port) not in lldp_ports:
                seg_id = f"seg-{sw}-{port}"
                seg_nodes.append({"data": {
                    "id": seg_id, "label": f"{port} · {len(uniq)} hosts",
                    "type": "unmanaged_segment", "is_segment": True,
                    "mac_count": len(uniq), "switch_id": sw, "port": port,
                    "macs": uniq[:50],
                }})
                seg_edges.append({"data": {
                    "id": f"se-{seg_id}", "source": sw, "target": seg_id, "kind": "unmanaged",
                }})
    return seg_nodes, seg_edges


def _compute_asset_elements(device_ids: set, assets: list):
    """Pure function: logical-asset nodes/edges hanging off their parent device."""
    nodes, edges = [], []
    for a in assets:
        parent = a.get("parent_device_id")
        if parent not in device_ids:
            continue
        aid = f"asset-{a['id']}"
        nodes.append({"data": {
            "id": aid, "label": a.get("name", aid), "type": "asset", "is_asset": True,
            "asset_type": a.get("asset_type", "module"), "parent_device_id": parent,
            "detail": a.get("detail"),
        }})
        edges.append({"data": {"id": f"ae-{aid}", "source": parent, "target": aid, "kind": "asset"}})
    return nodes, edges


# Topology
@router.get("/topology")
async def topology():
    devices = await db.devices.find({}, {"_id": 0}).to_list(None)
    # zone compound parents
    zones = sorted({d["zone"] for d in devices if d.get("zone")})
    zone_nodes = [
        {"data": {"id": f"zone-{z}", "label": z, "is_zone": True}}
        for z in zones
    ]
    nodes = []
    for d in devices:
        data = {
            "id": d["id"],
            "label": d["name"],
            "type": d["device_type"],
            "status": d["status"],
            "stale": d.get("stale", False),
            "ip": d["ip"],
            "vendor": d["vendor"],
            "model": d["model"],
            "protocol": d["protocol"],
            "zone": d.get("zone"),
        }
        if d.get("zone"):
            data["parent"] = f"zone-{d['zone']}"
        nodes.append({"data": data})

    device_ids = {d["id"] for d in devices}
    edges = [
        {"data": {"id": f"e-{d['id']}", "source": d["parent_id"], "target": d["id"]}}
        for d in devices
        if d.get("parent_id") and d["parent_id"] in device_ids
    ]
    # LLDP/CDP discovered links (drawn as additional edges; stale ones skipped)
    links = await db.links.find({}, {"_id": 0}).to_list(None)
    for lk in links:
        if lk.get("source_id") in device_ids and lk.get("target_id") in device_ids:
            port_lbl = ""
            if lk.get("source_port") or lk.get("target_port"):
                port_lbl = f"{lk.get('source_port', '')}\u2192{lk.get('target_port', '')}"
            edges.append({"data": {
                "id": f"l-{lk['id']}",
                "source": lk["source_id"],
                "target": lk["target_id"],
                "label": port_lbl,
                "kind": "lldp",
            }})

    # Phase 4: derive unmanaged segments (FDB + LLDP) and logical asset nodes.
    fdb_docs = await db.device_fdb.find({}, {"_id": 0}).to_list(None)
    assets = await db.assets.find({}, {"_id": 0}).to_list(None)
    seg_nodes, seg_edges = _compute_unmanaged_segments(device_ids, fdb_docs, links, config.UNMANAGED_MIN_MACS)
    asset_nodes, asset_edges = _compute_asset_elements(device_ids, assets)

    return {
        "nodes": zone_nodes + nodes + seg_nodes + asset_nodes,
        "edges": edges + seg_edges + asset_edges,
        "zones": zones,
    }


# ---------------- TOPOLOGY LINKS (LLDP/CDP neighbor relations) ---------------- #

@router.post("/links")
async def post_links(payload: LinksPayload):
    """Upsert neighbor links. Both endpoints are resolved to known devices;
    unresolved ones are skipped and reported back."""
    added = 0
    updated = 0
    unresolved = []
    now = datetime.now(timezone.utc).isoformat()
    for lk in payload.links:
        src = await _find_device(lk.source_id, lk.source_ip, lk.source_name)
        dst = await _find_device(lk.neighbor_id, lk.neighbor_ip, lk.neighbor_name)
        if not src or not dst or src["id"] == dst["id"]:
            unresolved.append({
                "source": lk.source_id or lk.source_ip or lk.source_name,
                "neighbor": lk.neighbor_id or lk.neighbor_ip or lk.neighbor_name,
            })
            continue
        key = {"source_id": src["id"], "target_id": dst["id"]}
        res = await db.links.update_one(
            key,
            {"$set": {**key, "source_port": lk.local_port, "target_port": lk.remote_port, "last_seen": now},
             "$setOnInsert": {"id": str(uuid.uuid4())}},
            upsert=True,
        )
        if res.upserted_id is not None:
            added += 1
        else:
            updated += 1
    return {"received": len(payload.links), "added": added, "updated": updated, "unresolved": unresolved}


@router.get("/links")
async def list_links():
    links = await db.links.find({}, {"_id": 0}).to_list(None)
    return links


@router.post("/links/reset")
async def reset_links():
    res = await db.links.delete_many({})
    return {"deleted": res.deleted_count}
