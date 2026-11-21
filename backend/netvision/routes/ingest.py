"""Collector ingestion: ping/SNMP samples, generic metrics, interfaces, FDB, ARP, assets."""
from datetime import datetime, timezone, timedelta
from typing import List, Optional
import uuid

from fastapi import APIRouter

from netvision import config, ws
from netvision.alerts import _create_alert, _resolve_device_alerts
from netvision.database import _apply_updates, db
from netvision.devices import _cache_add, _find_device, _prefetch_devices, _resolve_cached
from netvision.helpers import _is_placeholder, _normalize_ip, _normalize_mac, _normalize_ts, _utc_now_iso, _valid_ip
from netvision.models import (AlertSeverity, ArpPayload, AssetsPayload, Device, FdbPayload, IngestPayload,
                              InterfacesPayload, MetricSample, MetricsPayload)
from netvision.monitoring import COLLECTOR_ALERT_ID, _derive_status, _metric_doc, _recover_if_stale, _worsen_message

router = APIRouter()

# ---------------- INTERFACES (IF-MIB / ifXTable snapshot + bps) ---------------- #
# The collector posts per-interface counters (ifHCInOctets / ifHCOutOctets etc.);
# the backend diffs against the previous snapshot to compute in_bps / out_bps.

@router.post("/interfaces")
async def ingest_interfaces(payload: InterfacesPayload):
    dev = await _find_device(payload.device_id, payload.ip, payload.name)
    if not dev:
        return {"matched": False, "ip": payload.ip}
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    now_epoch = now.timestamp()

    prev = await db.device_interfaces.find_one({"device_id": dev["id"]}, {"_id": 0})
    prev_map = {}
    dt = None
    if prev:
        for r in prev.get("interfaces", []):
            prev_map[r.get("ifindex")] = r
        pe = prev.get("ts_epoch")
        if pe:
            dt = now_epoch - pe
            if dt <= 0:
                dt = None

    rows = []
    for r in payload.interfaces:
        in_bps = None
        out_bps = None
        p = prev_map.get(r.ifindex)
        if dt and p:
            if r.in_octets is not None and p.get("in_octets") is not None:
                d = r.in_octets - p["in_octets"]
                if d >= 0:
                    in_bps = round((d / dt) * 8, 1)
            if r.out_octets is not None and p.get("out_octets") is not None:
                d = r.out_octets - p["out_octets"]
                if d >= 0:
                    out_bps = round((d / dt) * 8, 1)
        rows.append({
            "ifindex": r.ifindex, "name": r.name or "", "oper": r.oper, "admin": r.admin,
            "speed_mbps": r.speed_mbps, "in_octets": r.in_octets, "out_octets": r.out_octets,
            "in_errors": r.in_errors, "out_errors": r.out_errors,
            "in_bps": in_bps, "out_bps": out_bps,
        })

    await db.device_interfaces.update_one(
        {"device_id": dev["id"]},
        {"$set": {"device_id": dev["id"], "ts": now_iso, "ts_epoch": now_epoch, "interfaces": rows}},
        upsert=True,
    )
    await db.devices.update_one({"id": dev["id"]}, {"$set": {"last_seen": now_iso}})
    await _recover_if_stale(dev)
    return {"matched": True, "device_id": dev["id"], "count": len(rows), "bps_ready": dt is not None}


@router.get("/devices/{device_id}/interfaces")
async def device_interfaces(device_id: str):
    doc = await db.device_interfaces.find_one({"device_id": device_id}, {"_id": 0})
    if not doc:
        return {"device_id": device_id, "ts": None, "interfaces": []}
    return doc


# ---------------- FDB & LOGICAL ASSETS (Phase 4: unmanaged segments + asset tree) ---------------- #
# A collector (Node-RED via SNMP dot1q FDB) posts per-port MAC lists here. The
# topology endpoint then combines FDB with LLDP neighbor links to surface
# "unmanaged segments" (a switch port with several MACs and no LLDP neighbor =
# a dumb hub / daisy chain). Logical assets (PLC child IO modules discovered via
# CIP/PROFINET) are posted to /api/assets and shown as child nodes.

@router.post("/fdb")
async def ingest_fdb(payload: FdbPayload):
    """Store the forwarding database (port -> MAC list) for a switch."""
    dev = await _find_device(payload.device_id, payload.ip, payload.name)
    if not dev:
        return {"matched": False, "ip": payload.ip}
    ports: dict = {}
    for e in payload.entries:
        if not e.port or not e.mac:
            continue
        ports.setdefault(e.port, [])
        if e.mac not in ports[e.port]:
            ports[e.port].append(e.mac)
    now = datetime.now(timezone.utc).isoformat()
    await db.device_fdb.update_one(
        {"device_id": dev["id"]},
        {"$set": {"device_id": dev["id"], "ts": now, "ports": ports}},
        upsert=True,
    )
    return {"matched": True, "device_id": dev["id"], "ports": len(ports)}


# ---------------- ARP (IP <-> MAC) for L2 link inference (issue #48) ---------------- #
# Source = an L3 gateway's ARP table (ipNetToMediaPhysAddress) or the collector
# host's own neighbor table (`ip neigh` after a ping sweep). Rows are upserted per
# (source_id, ip, mac) with last_seen; nothing here changes devices or topology.

ARP_SOURCE_COLLECTOR = "collector"
_ARP_INVALID_REPORT_CAP = 100


def _arp_entry_error(e) -> Optional[str]:
    if not isinstance(e, dict):
        return "entry must be an object"
    ip = e.get("ip")
    if not isinstance(ip, str) or not _valid_ip(ip) or _is_placeholder(ip):
        return "invalid ip"
    if _normalize_mac(e.get("mac")) is None:
        return "invalid mac"
    return None


@router.post("/arp")
async def ingest_arp(payload: ArpPayload):
    """Upsert ARP rows. Invalid rows are skipped and reported back (index + reason)."""
    if payload.source == ARP_SOURCE_COLLECTOR:
        source_id, source_type = ARP_SOURCE_COLLECTOR, "collector"
    else:
        dev = await _find_device(payload.device_id, payload.ip, payload.name)
        if not dev:
            return {"matched": False, "ip": payload.ip, "received": len(payload.entries), "accepted": 0}
        source_id, source_type = dev["id"], "gateway"
    now = _utc_now_iso()
    invalid = []
    rows = {}
    for i, e in enumerate(payload.entries):
        err = _arp_entry_error(e)
        if err:
            raw = e if isinstance(e, dict) else {}
            invalid.append({"index": i, "reason": err, "ip": raw.get("ip"), "mac": raw.get("mac")})
            continue
        vlan, ifname = e.get("vlan"), e.get("ifname")
        rows[(_normalize_ip(e["ip"]), _normalize_mac(e["mac"]))] = {
            "ifname": str(ifname) if ifname is not None else None,
            "vlan": str(vlan) if vlan is not None else None,
        }
    pairs = []
    for (ip, mac), extra in rows.items():
        key = {"source_id": source_id, "ip": ip, "mac": mac}
        pairs.append((key, {"$set": {**key, "source_type": source_type, **extra, "last_seen": now},
                            "$setOnInsert": {"first_seen": now}}))
    await _apply_updates(db.arp_entries, pairs, ordered=False, upsert=True)
    return {"matched": True, "source_id": source_id, "source_type": source_type,
            "received": len(payload.entries), "accepted": len(rows),
            "invalid_count": len(invalid), "invalid": invalid[:_ARP_INVALID_REPORT_CAP]}


@router.post("/assets")
async def ingest_assets(payload: AssetsPayload):
    """Upsert logical assets that hang off a parent device (e.g. PLC IO modules)."""
    upserts = 0
    unresolved = []
    for a in payload.assets:
        parent = await _find_device(a.parent_device_id, a.parent_ip, a.parent_name)
        if not parent:
            unresolved.append(a.name)
            continue
        key = {"parent_device_id": parent["id"], "name": a.name}
        await db.assets.update_one(
            key,
            {"$set": {**key, "asset_type": a.asset_type, "detail": a.detail,
                      "last_seen": datetime.now(timezone.utc).isoformat()},
             "$setOnInsert": {"id": str(uuid.uuid4())}},
            upsert=True,
        )
        upserts += 1
    return {"received": len(payload.assets), "upserted": upserts, "unresolved": unresolved}


@router.get("/assets")
async def list_assets():
    return await db.assets.find({}, {"_id": 0}).to_list(None)


@router.post("/assets/reset")
async def reset_assets():
    res = await db.assets.delete_many({})
    return {"deleted": res.deleted_count}


# ---------------- GENERIC METRICS (UnifiedMetric: arbitrary named values) ---------------- #
# For non-network data (PLC registers via Modbus, OPC UA nodes, etc.) that don't fit the
# fixed device fields. Collectors POST named metrics here; latest value + time-series stored.

@router.post("/metrics")
async def ingest_metrics(payload: MetricsPayload):
    """Ingest arbitrary named metrics. Resolves device by id/ip/name, stores the
    latest value (device_kv) plus a time-series point (unified_metrics), and
    bumps last_seen. Does not judge network status (that stays with ping/SNMP),
    except that a device offline only because data stopped (stale) recovers."""
    updated = 0
    unmatched = []
    docs = []
    touched = set()
    now = datetime.now(timezone.utc).isoformat()
    for s in payload.samples:
        dev = await _find_device(s.device_id, s.ip, s.name)
        if not dev:
            unmatched.append(s.device_id or s.ip or s.name or s.metric_name)
            continue
        ts = _normalize_ts(s.ts) if s.ts else now
        docs.append({
            "device_id": dev["id"], "metric_name": s.metric_name,
            "value": float(s.value), "unit": s.unit or "",
            "ts": ts, "ts_dt": datetime.now(timezone.utc),
        })
        await db.device_kv.update_one(
            {"device_id": dev["id"], "metric_name": s.metric_name},
            {"$set": {"device_id": dev["id"], "metric_name": s.metric_name,
                      "value": float(s.value), "unit": s.unit or "", "ts": ts}},
            upsert=True,
        )
        if dev["id"] not in touched:
            await _recover_if_stale(dev)
        touched.add(dev["id"])
        updated += 1
    if docs:
        await db.unified_metrics.insert_many(docs)
    for did in touched:
        await db.devices.update_one({"id": did}, {"$set": {"last_seen": now}})
    return {"received": len(payload.samples), "updated": updated, "unmatched": unmatched}


@router.get("/devices/{device_id}/kv")
async def device_kv(device_id: str):
    """Latest value of each generic metric for a device."""
    rows = await db.device_kv.find({"device_id": device_id}, {"_id": 0}).to_list(500)
    return rows


@router.get("/devices/{device_id}/series")
async def device_series(device_id: str, metric: str, hours: int = 24):
    """Time-series of one named metric for a device."""
    hours = max(1, min(hours, 168))
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = await db.unified_metrics.find(
        {"device_id": device_id, "metric_name": metric, "ts": {"$gte": since}},
        {"_id": 0},
    ).sort("ts", 1).to_list(20000)
    return {"device_id": device_id, "metric": metric, "points": rows}


# ---------------- INGESTION (live data from external collectors) ---------------- #

async def _resolve_device(s: MetricSample) -> Optional[dict]:
    return await _find_device(s.device_id, s.ip, s.name)


@router.post("/ingest")
async def ingest(payload: IngestPayload, auto_create: bool = False):
    """Accept real metrics from external collectors and run them through the
    SAME judgment -> alert -> history -> WebSocket pipeline the simulator uses.

    - auto_create=true  : if a sample's device is not found, create a minimal
                          device (type=switch, vendor/model=Unknown) so it shows up.
    - auto_create=false : unmatched samples are skipped and reported back.
    """
    updated = 0
    created = 0
    unmatched: List[str] = []
    metric_docs: List[dict] = []
    device_ops: List[tuple] = []
    followups: List[tuple] = []  # ("alert", device, sev, msg) | ("resolve", device_id), run after the bulk write
    cache = await _prefetch_devices(payload.samples)  # one query for the whole batch (issue #16)

    for s in payload.samples:
        device = _resolve_cached(cache, s.device_id, s.ip, s.name)

        # auto-create a minimal device if requested and not found
        # never auto-create when the name already exists: a None here then means the
        # name is AMBIGUOUS, and creating yet another twin would grow forever
        if (device is None and auto_create and (s.ip or s.name) and (not s.ip or _valid_ip(s.ip))
                and not (s.name and s.name in cache["by_name"])):
            dev = Device(
                name=s.name or s.ip or "device",
                ip=_normalize_ip(s.ip) if s.ip else "0.0.0.0",
                vendor="Unknown",
                model="Unknown",
                protocol="ICMP",
                device_type="switch",
            )
            await db.devices.insert_one(dev.model_dump())
            device = dev.model_dump()
            _cache_add(cache, device)
            created += 1

        if device is None:
            unmatched.append(s.device_id or s.ip or s.name or "unknown")
            continue

        prev_status = device["status"]
        # merge metrics: provided values win, omitted keep previous
        latency = float(s.latency_ms) if s.latency_ms is not None else float(device.get("latency_ms", 0.0))
        ploss = float(s.packet_loss) if s.packet_loss is not None else float(device.get("packet_loss", 0.0))
        cpu = float(s.cpu_pct) if s.cpu_pct is not None else float(device.get("cpu_pct", 0.0))
        uptime = float(s.uptime_pct) if s.uptime_pct is not None else float(device.get("uptime_pct", 100.0))

        # determine new status
        was_stale = bool(device.get("stale"))
        if s.status is not None:
            new_status = s.status
        elif s.reachable is False:
            new_status = "offline"
        else:
            # allow recovery: if device was offline and is now reachable, re-evaluate from metrics.
            # A device that went offline only because data STOPPED (stale) recovers on any data.
            recovering = prev_status == "offline" and (s.reachable is True or was_stale)
            base = "online" if recovering else prev_status
            new_status = _derive_status(base, base, latency, ploss)

        # last_seen / stale judgement always use SERVER receive time: a collector with a
        # wrong clock or delayed batches must not make devices flap. The collector's own
        # timestamp is kept only for the metric history point.
        now_iso = _utc_now_iso()
        sample_ts = _normalize_ts(s.ts)
        fields = {
            "latency_ms": round(latency, 2),
            "packet_loss": round(ploss, 2),
            "cpu_pct": round(cpu, 1),
            "uptime_pct": round(uptime, 2),
            "last_seen": now_iso,
            "status": new_status,
            "stale": False,
        }
        device_ops.append(({"id": device["id"]}, {"$set": fields}))
        snapshot_for_alert = dict(device)
        device.update(fields)  # later samples in the same batch see the new state

        # create alert on worsening transition (same rule as the simulator)
        if new_status != prev_status and new_status in ("warning", "critical", "offline"):
            sev: AlertSeverity = "critical" if new_status in ("critical", "offline") else "warning"
            followups.append(("alert", snapshot_for_alert, sev,
                              _worsen_message(device["name"], new_status, latency, ploss)))

        # auto-resolve: device recovered to online -> clear its open alerts
        if prev_status != "online" and new_status == "online":
            followups.append(("resolve", device["id"]))

        metric_docs.append(_metric_doc(device["id"], sample_ts, latency, ploss, cpu, new_status))
        updated += 1

    await _apply_updates(db.devices, device_ops, ordered=True)
    # alerts after the device states are written, so RCA sees parents' new status
    for f in followups:
        if f[0] == "alert":
            await _create_alert(f[1], f[2], f[3])
        else:
            await _resolve_device_alerts(f[1])
    if metric_docs:
        await db.device_metrics.insert_many(metric_docs)

    config._LAST_INGEST_TS = datetime.now(timezone.utc).isoformat()
    await _resolve_device_alerts(COLLECTOR_ALERT_ID)  # collector is alive again

    # push to dashboards, coalesced: many collector posts -> one snapshot per second
    ws._schedule_broadcast()

    return {
        "received": len(payload.samples),
        "updated": updated,
        "created": created,
        "unmatched": unmatched,
        "simulation_mode": config.sim_on(),
    }
