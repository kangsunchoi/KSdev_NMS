from fastapi import FastAPI, APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import random
import asyncio
import json
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Literal
import uuid
from datetime import datetime, timezone, timedelta


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="NetVision OT API")
api_router = APIRouter(prefix="/api")

# Tick counter for metric sampling cadence
_TICK = 0
_SAMPLE_EVERY = 12  # 12 * 5s = 60s sampling
_METRIC_TTL_SEC = 24 * 60 * 60  # 24h

# ---------------- SIMULATION MODE ---------------- #
# Persistent default from .env. "true" preserves the original demo behavior
# (auto-seed 20 mock devices + random jiggle). Set to "false" for live/ingest mode
# so real data pushed via /api/ingest is NOT overwritten by the simulator.
_SIM_ENV = os.environ.get("SIMULATION_MODE", "true").strip().lower() in ("1", "true", "yes", "on")
# Runtime override via POST /api/sim/mode (None = use env value). Resets on restart.
_SIM_OVERRIDE: Optional[bool] = None
# Timestamp of the last successful ingest (for status endpoint)
_LAST_INGEST_TS: Optional[str] = None


def sim_on() -> bool:
    """Effective simulation mode: runtime override wins over env default."""
    return _SIM_ENV if _SIM_OVERRIDE is None else _SIM_OVERRIDE


# ---------------- MODELS ---------------- #

DeviceType = Literal["switch", "plc", "hmi", "sensor"]
DeviceStatus = Literal["online", "warning", "critical", "offline"]
AlertSeverity = Literal["info", "warning", "critical"]


class DeviceBase(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    ip: str
    vendor: str
    model: str
    protocol: str
    device_type: DeviceType
    zone: Optional[str] = None


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    ip: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    protocol: Optional[str] = None
    device_type: Optional[DeviceType] = None
    zone: Optional[str] = None


class Device(DeviceBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: DeviceStatus = "online"
    latency_ms: float = 0.0
    packet_loss: float = 0.0
    uptime_pct: float = 100.0
    cpu_pct: float = 0.0
    last_seen: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    parent_id: Optional[str] = None  # for topology hierarchy


class Alert(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    device_id: str
    device_name: str
    severity: AlertSeverity
    message: str
    acknowledged: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------- MOCK GENERATORS ---------------- #

VENDORS = {
    "switch": [("Cisco", "Catalyst 9300"), ("Hirschmann", "RSP35"), ("Moxa", "EDS-510E")],
    "plc": [("Siemens", "S7-1500"), ("Allen-Bradley", "ControlLogix 5580"), ("Schneider", "Modicon M580")],
    "hmi": [("Siemens", "TP1200 Comfort"), ("Rockwell", "PanelView Plus 7"), ("Pro-face", "GP4000")],
    "sensor": [("SICK", "DFS60"), ("IFM", "O5D100"), ("Pepperl+Fuchs", "VDM100"), ("Endress+Hauser", "Promag 400")],
}

PROTOCOLS = {
    "switch": ["SNMP", "LLDP"],
    "plc": ["Profinet", "EtherNet/IP", "Modbus TCP"],
    "hmi": ["OPC UA", "Profinet"],
    "sensor": ["IO-Link", "Modbus RTU", "HART"],
}

NAME_PREFIXES = {
    "switch": "SW",
    "plc": "PLC",
    "hmi": "HMI",
    "sensor": "SNS",
}


def _gen_ip(base="10.20"):
    return f"{base}.{random.randint(1, 50)}.{random.randint(2, 254)}"


def _new_device(device_type: DeviceType, idx: int, parent_id: Optional[str] = None, zone: Optional[str] = None) -> Device:
    vendor, model = random.choice(VENDORS[device_type])
    protocol = random.choice(PROTOCOLS[device_type])
    name = f"{NAME_PREFIXES[device_type]}-{idx:02d}"
    status: DeviceStatus = random.choices(
        ["online", "warning", "critical", "offline"], weights=[75, 12, 8, 5]
    )[0]
    return Device(
        name=name,
        ip=_gen_ip(),
        vendor=vendor,
        model=model,
        protocol=protocol,
        device_type=device_type,
        status=status,
        latency_ms=round(random.uniform(0.5, 25.0), 2),
        packet_loss=round(random.uniform(0.0, 3.5), 2),
        uptime_pct=round(random.uniform(90.0, 100.0), 2),
        cpu_pct=round(random.uniform(5.0, 85.0), 1),
        parent_id=parent_id,
        zone=zone,
    )


ZONES = ["Cell-A", "Cell-B", "Utilities"]


def _build_topology() -> List[Device]:
    """Build a realistic hierarchy: 3 core switches (each = 1 zone) -> PLCs/HMIs -> sensors."""
    devices: List[Device] = []
    switches = [_new_device("switch", i + 1, zone=ZONES[i]) for i in range(3)]
    devices.extend(switches)

    plcs: List[Device] = []
    for i in range(5):
        parent = switches[i % len(switches)]
        plc = _new_device("plc", i + 1, parent_id=parent.id, zone=parent.zone)
        plcs.append(plc)
        devices.append(plc)

    for i in range(3):
        parent = switches[i % len(switches)]
        hmi = _new_device("hmi", i + 1, parent_id=parent.id, zone=parent.zone)
        devices.append(hmi)

    for i in range(9):
        parent = plcs[i % len(plcs)]
        sensor = _new_device("sensor", i + 1, parent_id=parent.id, zone=parent.zone)
        devices.append(sensor)

    return devices  # total 20


# ---------------- HELPERS ---------------- #

def _serialize(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


ALERT_DEBOUNCE_SEC = 60


async def _create_alert(device: dict, severity: AlertSeverity, message: str, force: bool = False):
    """Insert alert unless a same-device-same-severity alert exists in the last ALERT_DEBOUNCE_SEC."""
    if not force:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=ALERT_DEBOUNCE_SEC)).isoformat()
        recent = await db.alerts.find_one(
            {"device_id": device["id"], "severity": severity, "timestamp": {"$gte": cutoff}},
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
    await db.alerts.insert_one(alert.model_dump())
    return alert


def _derive_status(prev_status: str, candidate: str, latency: float, ploss: float) -> str:
    """Deterministic status derivation from metrics.

    Extracted verbatim from the original simulation loop so that BOTH the
    simulator and the live ingestion path judge status identically.
    `candidate` is the starting status (for the simulator this may already
    reflect its rare random flip; for ingestion it equals prev_status).
    """
    new_status = candidate
    if prev_status != "offline":
        if ploss > 8 or latency > 80:
            new_status = "critical"
        elif ploss > 4 or latency > 45:
            new_status = "warning"
        elif ploss < 1.5 and latency < 25:
            new_status = "online"
    return new_status


def _worsen_message(name: str, new_status: str, latency: float, ploss: float) -> str:
    """Alert text for a worsening transition (same wording as the simulator)."""
    return {
        "warning": f"{name}: degraded performance (latency {round(latency, 1)}ms)",
        "critical": f"{name}: critical state (packet loss {round(ploss, 1)}%)",
        "offline": f"{name}: lost contact",
    }.get(new_status, "Anomaly")


def _metric_doc(device_id: str, ts_iso: str, latency: float, ploss: float, cpu: float, status: str) -> dict:
    """Build one time-series history point (same shape used by the simulator)."""
    return {
        "device_id": device_id,
        "ts": ts_iso,
        "ts_dt": datetime.now(timezone.utc),  # for TTL index
        "latency_ms": round(latency, 2),
        "packet_loss": round(ploss, 2),
        "cpu_pct": round(cpu, 1),
        "status": status,
    }


async def _resolve_device_alerts(device_id: str) -> int:
    """Auto-resolve: when a device recovers to 'online', mark its still-open
    alerts as acknowledged so they drop out of the active list (the periodic
    2h purge then removes them). Returns how many alerts were resolved.

    Shared by both the simulator and the live ingestion path so recovery
    behaves identically regardless of where the data came from.
    """
    result = await db.alerts.update_many(
        {"device_id": device_id, "acknowledged": False},
        {"$set": {"acknowledged": True}},
    )
    return result.modified_count


async def _ensure_seed():
    count = await db.devices.count_documents({})
    if count == 0:
        devs = _build_topology()
        await db.devices.insert_many([d.model_dump() for d in devs])
        # initial alerts for non-online devices
        async for d in db.devices.find({"status": {"$ne": "online"}}, {"_id": 0}):
            sev: AlertSeverity = "critical" if d["status"] in ("critical", "offline") else "warning"
            msg = {
                "warning": "Elevated latency detected",
                "critical": "Device unresponsive — packet loss spike",
                "offline": "Device offline — no heartbeat",
            }.get(d["status"], "Anomaly detected")
            await _create_alert(d, sev, msg)


# ---------------- ROUTES ---------------- #

@api_router.get("/")
async def root():
    return {"service": "NetVision OT", "status": "ok"}


# Devices CRUD
@api_router.get("/devices", response_model=List[Device])
async def list_devices():
    docs = await db.devices.find({}, {"_id": 0}).to_list(1000)
    return docs


@api_router.post("/devices", response_model=Device)
async def create_device(payload: DeviceCreate):
    dev = Device(**payload.model_dump())
    await db.devices.insert_one(dev.model_dump())
    return dev


@api_router.get("/devices/{device_id}", response_model=Device)
async def get_device(device_id: str):
    doc = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Device not found")
    return doc


@api_router.patch("/devices/{device_id}", response_model=Device)
async def update_device(device_id: str, payload: DeviceUpdate):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(400, "Empty update")
    result = await db.devices.update_one({"id": device_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(404, "Device not found")
    doc = await db.devices.find_one({"id": device_id}, {"_id": 0})
    return doc


@api_router.delete("/devices/{device_id}")
async def delete_device(device_id: str):
    result = await db.devices.delete_one({"id": device_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Device not found")
    # cascade: clear parent_id refs, alerts, and topology links
    await db.devices.update_many({"parent_id": device_id}, {"$set": {"parent_id": None}})
    await db.alerts.delete_many({"device_id": device_id})
    await db.links.delete_many({"$or": [{"source_id": device_id}, {"target_id": device_id}]})
    await db.device_kv.delete_many({"device_id": device_id})
    await db.unified_metrics.delete_many({"device_id": device_id})
    await db.device_interfaces.delete_many({"device_id": device_id})
    return {"deleted": device_id}


class CleanupPayload(BaseModel):
    """Selective cleanup of leftover mock devices, matched by name prefix and/or
    IP prefix. dry_run=True (default) only previews. Both criteria, when given,
    must match (conservative) so real discovered devices are not removed."""
    model_config = ConfigDict(extra="ignore")
    name_prefixes: List[str] = ["SW-", "PLC-", "SNS-"]
    ip_prefix: Optional[str] = "10.20."
    dry_run: bool = True


@api_router.post("/devices/cleanup")
async def cleanup_devices(payload: CleanupPayload):
    prefixes = [p for p in (payload.name_prefixes or []) if p]
    ipp = (payload.ip_prefix or "").strip()

    def _matches(d: dict) -> bool:
        name = d.get("name") or ""
        ip = d.get("ip") or ""
        name_ok = any(name.startswith(p) for p in prefixes) if prefixes else None
        ip_ok = ip.startswith(ipp) if ipp else None
        checks = [c for c in (name_ok, ip_ok) if c is not None]
        if not checks:
            return False
        return all(checks)

    all_devs = await db.devices.find({}, {"_id": 0}).to_list(100000)
    matched = [d for d in all_devs if _matches(d)]
    preview = [{"id": d["id"], "name": d.get("name"), "ip": d.get("ip"),
                "device_type": d.get("device_type")} for d in matched]

    if payload.dry_run:
        return {"dry_run": True, "matched": len(matched), "devices": preview}

    ids = [d["id"] for d in matched]
    if ids:
        await db.devices.delete_many({"id": {"$in": ids}})
        await db.devices.update_many({"parent_id": {"$in": ids}}, {"$set": {"parent_id": None}})
        await db.alerts.delete_many({"device_id": {"$in": ids}})
        await db.links.delete_many({"$or": [{"source_id": {"$in": ids}}, {"target_id": {"$in": ids}}]})
        await db.device_kv.delete_many({"device_id": {"$in": ids}})
        await db.unified_metrics.delete_many({"device_id": {"$in": ids}})
        await db.device_interfaces.delete_many({"device_id": {"$in": ids}})
    return {"dry_run": False, "deleted": len(ids), "devices": preview}


# ---------------- DISCOVERY (subnet sweep config + register) ---------------- #
# The app stores discovery settings here; the Node-RED collector reads them,
# sweeps the subnet (fping), and posts the alive IPs back to /discovery/register.

_DISCOVERY_DEFAULT = {
    "id": "default", "subnet": "", "community": "public", "snmp_version": "2c",
    "default_type": "switch", "enabled": False, "run_requested": False,
    "last_run": None, "last_found": 0, "last_created": 0, "last_message": "",
}


async def _get_discovery_doc():
    doc = await db.discovery.find_one({"id": "default"}, {"_id": 0})
    if not doc:
        await db.discovery.insert_one(dict(_DISCOVERY_DEFAULT))
        doc = await db.discovery.find_one({"id": "default"}, {"_id": 0})
    return doc


class DiscoveryUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    subnet: Optional[str] = None
    community: Optional[str] = None
    snmp_version: Optional[str] = None
    default_type: Optional[DeviceType] = None
    enabled: Optional[bool] = None
    run_requested: Optional[bool] = None
    last_run: Optional[str] = None
    last_found: Optional[int] = None
    last_created: Optional[int] = None
    last_message: Optional[str] = None


class DiscoveryRegister(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ips: List[str] = []


@api_router.get("/discovery")
async def get_discovery():
    return await _get_discovery_doc()


@api_router.put("/discovery")
async def update_discovery(patch: DiscoveryUpdate):
    await _get_discovery_doc()
    fields = {k: v for k, v in patch.model_dump().items() if v is not None}
    if fields:
        await db.discovery.update_one({"id": "default"}, {"$set": fields})
    return await db.discovery.find_one({"id": "default"}, {"_id": 0})


@api_router.post("/discovery/register")
async def discovery_register(payload: DiscoveryRegister):
    """Register newly-found IPs as minimal devices (skip existing). Called by the
    Node-RED discovery collector after an fping sweep. Also clears run_requested
    and records the run summary."""
    cfg = await _get_discovery_doc()
    dtype = cfg.get("default_type") or "switch"
    existing = set()
    async for d in db.devices.find({}, {"_id": 0, "ip": 1}):
        if d.get("ip"):
            existing.add(d["ip"])
    created = 0
    new_ips = []
    for raw in payload.ips:
        ip = (raw or "").strip()
        if not ip or ip in existing:
            continue
        dev = Device(name=ip, ip=ip, vendor="unknown", model="unknown",
                     protocol="snmp", device_type=dtype, status="online")
        await db.devices.insert_one(dev.model_dump())
        existing.add(ip)
        new_ips.append(ip)
        created += 1
    now = datetime.now(timezone.utc).isoformat()
    await db.discovery.update_one({"id": "default"}, {"$set": {
        "run_requested": False, "last_run": now,
        "last_found": len(payload.ips), "last_created": created,
        "last_message": f"{len(payload.ips)} alive, {created} new",
    }})
    return {"found": len(payload.ips), "created": created, "new_ips": new_ips}


# ---------------- INTERFACES (IF-MIB / ifXTable snapshot + bps) ---------------- #
# The collector posts per-interface counters (ifHCInOctets / ifHCOutOctets etc.);
# the backend diffs against the previous snapshot to compute in_bps / out_bps.

class IfRow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ifindex: int
    name: Optional[str] = ""
    oper: Optional[int] = None     # 1=up, 2=down (ifOperStatus)
    admin: Optional[int] = None
    speed_mbps: Optional[int] = None
    in_octets: Optional[float] = None
    out_octets: Optional[float] = None
    in_errors: Optional[float] = None
    out_errors: Optional[float] = None


class InterfacesPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    device_id: Optional[str] = None
    ip: Optional[str] = None
    name: Optional[str] = None
    interfaces: List[IfRow] = []


@api_router.post("/interfaces")
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
    return {"matched": True, "device_id": dev["id"], "count": len(rows), "bps_ready": dt is not None}


@api_router.get("/devices/{device_id}/interfaces")
async def device_interfaces(device_id: str):
    doc = await db.device_interfaces.find_one({"device_id": device_id}, {"_id": 0})
    if not doc:
        return {"device_id": device_id, "ts": None, "interfaces": []}
    return doc


# Alerts
@api_router.get("/alerts", response_model=List[Alert])
async def list_alerts(limit: int = 200):
    docs = await db.alerts.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return docs


@api_router.post("/alerts/{alert_id}/acknowledge", response_model=Alert)
async def acknowledge_alert(alert_id: str):
    result = await db.alerts.update_one({"id": alert_id}, {"$set": {"acknowledged": True}})
    if result.matched_count == 0:
        raise HTTPException(404, "Alert not found")
    doc = await db.alerts.find_one({"id": alert_id}, {"_id": 0})
    return doc


@api_router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str):
    result = await db.alerts.delete_one({"id": alert_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Alert not found")
    return {"deleted": alert_id}


# Topology
@api_router.get("/topology")
async def topology():
    devices = await db.devices.find({}, {"_id": 0}).to_list(1000)
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
    links = await db.links.find({}, {"_id": 0}).to_list(5000)
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
    return {"nodes": zone_nodes + nodes, "edges": edges, "zones": zones}


# ---------------- TOPOLOGY LINKS (LLDP/CDP neighbor relations) ---------------- #

async def _find_device(did=None, ip=None, name=None):
    """Resolve a device by id, then ip, then name (first match)."""
    if did:
        d = await db.devices.find_one({"id": did}, {"_id": 0})
        if d:
            return d
    if ip:
        d = await db.devices.find_one({"ip": ip}, {"_id": 0})
        if d:
            return d
    if name:
        d = await db.devices.find_one({"name": name}, {"_id": 0})
        if d:
            return d
    return None


class NeighborLink(BaseModel):
    """One neighbor relation reported by a collector (from LLDP/CDP).

    Identify each endpoint by id / ip / name (checked in that order). 'source'
    is the polled switch; 'neighbor' is what it sees on a port.
    """
    model_config = ConfigDict(extra="ignore")
    source_id: Optional[str] = None
    source_ip: Optional[str] = None
    source_name: Optional[str] = None
    neighbor_id: Optional[str] = None
    neighbor_ip: Optional[str] = None
    neighbor_name: Optional[str] = None
    local_port: Optional[str] = None
    remote_port: Optional[str] = None


class LinksPayload(BaseModel):
    links: List[NeighborLink]


@api_router.post("/links")
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


@api_router.get("/links")
async def list_links():
    links = await db.links.find({}, {"_id": 0}).to_list(5000)
    return links


@api_router.post("/links/reset")
async def reset_links():
    res = await db.links.delete_many({})
    return {"deleted": res.deleted_count}


# ---------------- GENERIC METRICS (UnifiedMetric: arbitrary named values) ---------------- #
# For non-network data (PLC registers via Modbus, OPC UA nodes, etc.) that don't fit the
# fixed device fields. Collectors POST named metrics here; latest value + time-series stored.

class GenericSample(BaseModel):
    model_config = ConfigDict(extra="ignore")
    device_id: Optional[str] = None
    ip: Optional[str] = None
    name: Optional[str] = None
    metric_name: str            # e.g. "plc.temperature", "plc.run_status"
    value: float
    unit: Optional[str] = ""
    ts: Optional[str] = None


class MetricsPayload(BaseModel):
    samples: List[GenericSample]


@api_router.post("/metrics")
async def ingest_metrics(payload: MetricsPayload):
    """Ingest arbitrary named metrics. Resolves device by id/ip/name, stores the
    latest value (device_kv) plus a time-series point (unified_metrics), and
    bumps last_seen. Does NOT touch network status (that stays with ping/SNMP)."""
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
        ts = s.ts or now
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
        touched.add(dev["id"])
        updated += 1
    if docs:
        await db.unified_metrics.insert_many(docs)
    for did in touched:
        await db.devices.update_one({"id": did}, {"$set": {"last_seen": now}})
    return {"received": len(payload.samples), "updated": updated, "unmatched": unmatched}


@api_router.get("/devices/{device_id}/kv")
async def device_kv(device_id: str):
    """Latest value of each generic metric for a device."""
    rows = await db.device_kv.find({"device_id": device_id}, {"_id": 0}).to_list(500)
    return rows


@api_router.get("/devices/{device_id}/series")
async def device_series(device_id: str, metric: str, hours: int = 24):
    """Time-series of one named metric for a device."""
    hours = max(1, min(hours, 168))
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = await db.unified_metrics.find(
        {"device_id": device_id, "metric_name": metric, "ts": {"$gte": since}},
        {"_id": 0},
    ).sort("ts", 1).to_list(20000)
    return {"device_id": device_id, "metric": metric, "points": rows}


# Zones list
@api_router.get("/zones")
async def list_zones():
    devices = await db.devices.find({}, {"_id": 0, "zone": 1, "status": 1}).to_list(1000)
    counts: dict[str, dict] = {}
    for d in devices:
        z = d.get("zone")
        if not z:
            continue
        c = counts.setdefault(z, {"name": z, "total": 0, "online": 0, "warning": 0, "critical": 0})
        c["total"] += 1
        if d["status"] == "online":
            c["online"] += 1
        elif d["status"] == "warning":
            c["warning"] += 1
        else:
            c["critical"] += 1
    return sorted(counts.values(), key=lambda x: x["name"])


# Dashboard summary
@api_router.get("/dashboard/summary")
async def dashboard_summary():
    devices = await db.devices.find({}, {"_id": 0}).to_list(1000)
    total = len(devices)
    online = sum(1 for d in devices if d["status"] == "online")
    warning = sum(1 for d in devices if d["status"] == "warning")
    critical = sum(1 for d in devices if d["status"] in ("critical", "offline"))

    open_alerts = await db.alerts.count_documents({"acknowledged": False})
    critical_alerts = await db.alerts.count_documents({"acknowledged": False, "severity": "critical"})

    # Health score: online weighted +, warning slight -, critical heavy -
    if total == 0:
        health = 100
    else:
        score = (online * 100 + warning * 60 + critical * 0) / total
        score -= min(critical_alerts * 3, 25)
        health = max(0, min(100, round(score)))

    avg_latency = round(sum(d.get("latency_ms", 0) for d in devices) / total, 2) if total else 0.0
    avg_packet_loss = round(sum(d.get("packet_loss", 0) for d in devices) / total, 2) if total else 0.0

    return {
        "total": total,
        "online": online,
        "warning": warning,
        "critical": critical,
        "open_alerts": open_alerts,
        "critical_alerts": critical_alerts,
        "health_score": health,
        "avg_latency_ms": avg_latency,
        "avg_packet_loss": avg_packet_loss,
    }


# Mock data generator (manual)
@api_router.post("/mock/generate")
async def generate_mock(replace: bool = True):
    if replace:
        await db.devices.delete_many({})
        await db.alerts.delete_many({})
    devs = _build_topology()
    await db.devices.insert_many([d.model_dump() for d in devs])
    # seed alerts
    new_alerts = 0
    async for d in db.devices.find({"status": {"$ne": "online"}}, {"_id": 0}):
        sev: AlertSeverity = "critical" if d["status"] in ("critical", "offline") else "warning"
        msg = {
            "warning": "Elevated latency detected",
            "critical": "Device unresponsive — packet loss spike",
            "offline": "Device offline — no heartbeat",
        }.get(d["status"], "Anomaly detected")
        await _create_alert(d, sev, msg)
        new_alerts += 1
    return {"devices_created": len(devs), "alerts_created": new_alerts}


# Reset all
@api_router.post("/mock/reset")
async def reset_all():
    await db.devices.delete_many({})
    await db.alerts.delete_many({})
    await db.device_metrics.delete_many({})
    await db.links.delete_many({})
    await db.device_kv.delete_many({})
    await db.unified_metrics.delete_many({})
    await db.device_interfaces.delete_many({})
    return {"status": "cleared"}


# Device metric history (last N hours, default 24h)
@api_router.get("/devices/{device_id}/metrics")
async def device_metrics(device_id: str, hours: int = 24):
    exists = await db.devices.find_one({"id": device_id}, {"_id": 0, "id": 1})
    if not exists:
        raise HTTPException(404, "Device not found")
    hours = max(1, min(hours, 168))
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    cursor = db.device_metrics.find(
        {"device_id": device_id, "ts": {"$gte": since}},
        {"_id": 0},
    ).sort("ts", 1)
    points = await cursor.to_list(20000)
    return {"device_id": device_id, "hours": hours, "points": points}


# Bulk acknowledge alerts
class BulkAckPayload(BaseModel):
    ids: Optional[List[str]] = None  # if None, ack ALL open


@api_router.post("/alerts/bulk-acknowledge")
async def bulk_ack(payload: BulkAckPayload):
    q: dict = {"acknowledged": False}
    if payload.ids:
        q["id"] = {"$in": payload.ids}
    result = await db.alerts.update_many(q, {"$set": {"acknowledged": True}})
    return {"acknowledged": result.modified_count}


# ---------------- INGESTION (live data from external collectors) ---------------- #

class MetricSample(BaseModel):
    """One measurement from an external collector (Node-RED / Telegraf / etc.).

    Identify the target device by ANY of device_id / ip / name (checked in that order).
    Provide whatever metrics you have — omitted fields keep their previous value.
    """
    model_config = ConfigDict(extra="ignore")
    device_id: Optional[str] = None
    ip: Optional[str] = None
    name: Optional[str] = None
    reachable: Optional[bool] = None        # ICMP ping up/down (False -> offline)
    latency_ms: Optional[float] = None
    packet_loss: Optional[float] = None
    cpu_pct: Optional[float] = None
    uptime_pct: Optional[float] = None
    status: Optional[DeviceStatus] = None   # explicit status overrides derivation
    ts: Optional[str] = None                # collector timestamp (ISO); default = now


class IngestPayload(BaseModel):
    samples: List[MetricSample]


async def _resolve_device(s: MetricSample) -> Optional[dict]:
    if s.device_id:
        d = await db.devices.find_one({"id": s.device_id}, {"_id": 0})
        if d:
            return d
    if s.ip:
        d = await db.devices.find_one({"ip": s.ip}, {"_id": 0})
        if d:
            return d
    if s.name:
        d = await db.devices.find_one({"name": s.name}, {"_id": 0})
        if d:
            return d
    return None


@api_router.post("/ingest")
async def ingest(payload: IngestPayload, auto_create: bool = False):
    """Accept real metrics from external collectors and run them through the
    SAME judgment -> alert -> history -> WebSocket pipeline the simulator uses.

    - auto_create=true  : if a sample's device is not found, create a minimal
                          device (type=switch, vendor/model=Unknown) so it shows up.
    - auto_create=false : unmatched samples are skipped and reported back.
    """
    global _LAST_INGEST_TS
    updated = 0
    created = 0
    unmatched: List[str] = []
    metric_docs: List[dict] = []

    for s in payload.samples:
        device = await _resolve_device(s)

        # auto-create a minimal device if requested and not found
        if device is None and auto_create and (s.ip or s.name):
            dev = Device(
                name=s.name or s.ip or "device",
                ip=s.ip or "0.0.0.0",
                vendor="Unknown",
                model="Unknown",
                protocol="ICMP",
                device_type="switch",
            )
            await db.devices.insert_one(dev.model_dump())
            device = dev.model_dump()
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
        if s.status is not None:
            new_status = s.status
        elif s.reachable is False:
            new_status = "offline"
        else:
            # allow recovery: if device was offline and is now reachable, re-evaluate from metrics
            base = "online" if (s.reachable is True and prev_status == "offline") else prev_status
            new_status = _derive_status(base, base, latency, ploss)

        now_iso = s.ts or datetime.now(timezone.utc).isoformat()
        await db.devices.update_one(
            {"id": device["id"]},
            {"$set": {
                "latency_ms": round(latency, 2),
                "packet_loss": round(ploss, 2),
                "cpu_pct": round(cpu, 1),
                "uptime_pct": round(uptime, 2),
                "last_seen": now_iso,
                "status": new_status,
            }},
        )

        # create alert on worsening transition (same rule as the simulator)
        if new_status != prev_status and new_status in ("warning", "critical", "offline"):
            sev: AlertSeverity = "critical" if new_status in ("critical", "offline") else "warning"
            await _create_alert(device, sev, _worsen_message(device["name"], new_status, latency, ploss))

        # auto-resolve: device recovered to online -> clear its open alerts
        if prev_status != "online" and new_status == "online":
            await _resolve_device_alerts(device["id"])

        metric_docs.append(_metric_doc(device["id"], now_iso, latency, ploss, cpu, new_status))
        updated += 1

    if metric_docs:
        await db.device_metrics.insert_many(metric_docs)

    _LAST_INGEST_TS = datetime.now(timezone.utc).isoformat()

    # push fresh snapshot to dashboards
    if ws_manager.clients:
        snap = await _build_snapshot()
        await ws_manager.broadcast(snap)

    return {
        "received": len(payload.samples),
        "updated": updated,
        "created": created,
        "unmatched": unmatched,
        "simulation_mode": sim_on(),
    }


# Simulation mode control (for switching demo <-> live without editing files)
class SimModePayload(BaseModel):
    enabled: bool


@api_router.get("/sim/mode")
async def get_sim_mode():
    return {"simulation_mode": sim_on(), "env_default": _SIM_ENV, "override": _SIM_OVERRIDE,
            "last_ingest_ts": _LAST_INGEST_TS}


@api_router.post("/sim/mode")
async def set_sim_mode(payload: SimModePayload):
    """Toggle the simulator at runtime. NOTE: this override resets on restart;
    set SIMULATION_MODE in backend/.env for the persistent default."""
    global _SIM_OVERRIDE
    _SIM_OVERRIDE = payload.enabled
    return {"simulation_mode": sim_on(), "note": "runtime override; resets on restart"}


# ---------------- WEBSOCKET ---------------- #

class WSManager:
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def broadcast(self, payload: dict):
        if not self.clients:
            return
        msg = json.dumps(payload, default=str)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


ws_manager = WSManager()


@api_router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        # send an initial snapshot
        snap = await _build_snapshot()
        await websocket.send_text(json.dumps(snap, default=str))
        while True:
            # keep connection alive; ignore incoming messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


async def _build_snapshot() -> dict:
    devices = await db.devices.find({}, {"_id": 0}).to_list(1000)
    alerts = await db.alerts.find({}, {"_id": 0}).sort("timestamp", -1).to_list(200)
    total = len(devices)
    online = sum(1 for d in devices if d["status"] == "online")
    warning = sum(1 for d in devices if d["status"] == "warning")
    critical = sum(1 for d in devices if d["status"] in ("critical", "offline"))
    open_alerts = sum(1 for a in alerts if not a["acknowledged"])
    critical_alerts = sum(1 for a in alerts if not a["acknowledged"] and a["severity"] == "critical")
    if total == 0:
        health = 100
    else:
        score = (online * 100 + warning * 60 + critical * 0) / total
        score -= min(critical_alerts * 3, 25)
        health = max(0, min(100, round(score)))
    avg_lat = round(sum(d.get("latency_ms", 0) for d in devices) / total, 2) if total else 0.0
    avg_pl = round(sum(d.get("packet_loss", 0) for d in devices) / total, 2) if total else 0.0
    return {
        "type": "tick",
        "summary": {
            "total": total, "online": online, "warning": warning, "critical": critical,
            "open_alerts": open_alerts, "critical_alerts": critical_alerts,
            "health_score": health, "avg_latency_ms": avg_lat, "avg_packet_loss": avg_pl,
        },
        "devices": devices,
        "alerts": alerts,
    }


# ---------------- METRICS LOOP (simulation + periodic broadcast) ---------------- #

async def _simulate_tick():
    """One simulation step: jiggle metrics, maybe flip status, create alerts, sample history.

    This is the original per-device simulation body, unchanged in behavior. It only
    runs when simulation mode is ON.
    """
    devices = await db.devices.find({}, {"_id": 0}).to_list(1000)
    if not devices:
        return
    metric_docs = []
    sample_now = (_TICK % _SAMPLE_EVERY == 0)
    now_iso = datetime.now(timezone.utc).isoformat()
    for d in devices:
        # jiggle metrics
        latency = max(0.1, d.get("latency_ms", 1.0) + random.uniform(-1.5, 1.8))
        ploss = max(0.0, min(100.0, d.get("packet_loss", 0.0) + random.uniform(-0.4, 0.6)))
        cpu = max(0.0, min(100.0, d.get("cpu_pct", 30.0) + random.uniform(-3.0, 4.0)))

        # rare random status change (simulation only)
        candidate = d["status"]
        if random.random() < 0.02:
            candidate = random.choices(
                ["online", "warning", "critical", "offline"],
                weights=[70, 15, 10, 5],
            )[0]

        # derive status from metrics (shared with ingestion)
        new_status = _derive_status(d["status"], candidate, latency, ploss)

        update = {
            "latency_ms": round(latency, 2),
            "packet_loss": round(ploss, 2),
            "cpu_pct": round(cpu, 1),
            "last_seen": now_iso,
            "status": new_status,
        }
        await db.devices.update_one({"id": d["id"]}, {"$set": update})

        # create alert if status worsened
        if new_status != d["status"] and new_status in ("warning", "critical", "offline"):
            sev: AlertSeverity = "critical" if new_status in ("critical", "offline") else "warning"
            await _create_alert(d, sev, _worsen_message(d["name"], new_status, latency, ploss))

        # auto-resolve: device recovered to online -> clear its open alerts
        if d["status"] != "online" and new_status == "online":
            await _resolve_device_alerts(d["id"])

        if sample_now:
            metric_docs.append(_metric_doc(d["id"], now_iso, latency, ploss, cpu, new_status))

    if metric_docs:
        await db.device_metrics.insert_many(metric_docs)


async def metrics_loop():
    """Runs every 5s. Generates data only in simulation mode; always purges old
    acknowledged alerts and broadcasts a fresh snapshot so dashboards stay live
    whether data comes from the simulator or from /api/ingest."""
    global _TICK
    while True:
        try:
            await asyncio.sleep(5)
            _TICK += 1

            if sim_on():
                await _simulate_tick()

            # purge very old acknowledged alerts (>2h) — applies to both modes
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            await db.alerts.delete_many({"acknowledged": True, "timestamp": {"$lt": cutoff}})

            # Broadcast snapshot to WS clients
            if ws_manager.clients:
                snap = await _build_snapshot()
                await ws_manager.broadcast(snap)
        except Exception as e:
            logging.exception("metrics loop error: %s", e)


# ---------------- APP WIRING ---------------- #

app.include_router(api_router)

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
    # TTL index for metric history (24h)
    try:
        await db.device_metrics.create_index("ts_dt", expireAfterSeconds=_METRIC_TTL_SEC)
        await db.device_metrics.create_index([("device_id", 1), ("ts", 1)])
        await db.devices.create_index("ip")  # speed up ingest lookups by IP
        await db.links.create_index([("source_id", 1), ("target_id", 1)], unique=True)
        await db.unified_metrics.create_index("ts_dt", expireAfterSeconds=_METRIC_TTL_SEC)
        await db.unified_metrics.create_index([("device_id", 1), ("metric_name", 1), ("ts", 1)])
        await db.device_kv.create_index([("device_id", 1), ("metric_name", 1)], unique=True)
    except Exception as e:
        logger.warning("index create failed: %s", e)
    # Only auto-seed mock devices in simulation mode
    if sim_on():
        await _ensure_seed()
    asyncio.create_task(metrics_loop())
    logger.info("NetVision OT started — mode=%s", "simulation" if sim_on() else "live(ingest)")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
