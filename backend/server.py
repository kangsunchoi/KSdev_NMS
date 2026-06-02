from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import random
import asyncio
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


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    ip: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    protocol: Optional[str] = None
    device_type: Optional[DeviceType] = None


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


def _new_device(device_type: DeviceType, idx: int, parent_id: Optional[str] = None) -> Device:
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
    )


def _build_topology() -> List[Device]:
    """Build a realistic hierarchy: 3 core switches -> PLCs/HMIs -> sensors."""
    devices: List[Device] = []
    # Core switches
    switches = [_new_device("switch", i + 1) for i in range(3)]
    devices.extend(switches)

    # PLCs (5) and HMIs (3) attached to switches
    plc_count = 5
    hmi_count = 3
    plcs: List[Device] = []
    for i in range(plc_count):
        parent = switches[i % len(switches)]
        plc = _new_device("plc", i + 1, parent_id=parent.id)
        plcs.append(plc)
        devices.append(plc)

    for i in range(hmi_count):
        parent = switches[i % len(switches)]
        hmi = _new_device("hmi", i + 1, parent_id=parent.id)
        devices.append(hmi)

    # Sensors (9) attached to PLCs
    for i in range(9):
        parent = plcs[i % len(plcs)]
        sensor = _new_device("sensor", i + 1, parent_id=parent.id)
        devices.append(sensor)

    return devices  # total 20


# ---------------- HELPERS ---------------- #

def _serialize(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


async def _create_alert(device: dict, severity: AlertSeverity, message: str):
    alert = Alert(
        device_id=device["id"],
        device_name=device["name"],
        severity=severity,
        message=message,
    )
    await db.alerts.insert_one(alert.model_dump())
    return alert


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
    # cascade: clear parent_id refs and alerts
    await db.devices.update_many({"parent_id": device_id}, {"$set": {"parent_id": None}})
    await db.alerts.delete_many({"device_id": device_id})
    return {"deleted": device_id}


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
    nodes = [
        {
            "data": {
                "id": d["id"],
                "label": d["name"],
                "type": d["device_type"],
                "status": d["status"],
                "ip": d["ip"],
                "vendor": d["vendor"],
                "model": d["model"],
                "protocol": d["protocol"],
            }
        }
        for d in devices
    ]
    edges = [
        {"data": {"id": f"e-{d['id']}", "source": d["parent_id"], "target": d["id"]}}
        for d in devices
        if d.get("parent_id")
    ]
    return {"nodes": nodes, "edges": edges}


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
    return {"status": "cleared"}


# ---------------- SIMULATION TASK ---------------- #

async def simulate_metrics_loop():
    """Periodically jiggle device metrics & sometimes flip status / create alerts."""
    while True:
        try:
            await asyncio.sleep(5)
            devices = await db.devices.find({}, {"_id": 0}).to_list(1000)
            if not devices:
                continue
            for d in devices:
                # jiggle metrics
                latency = max(0.1, d.get("latency_ms", 1.0) + random.uniform(-1.5, 1.8))
                ploss = max(0.0, min(100.0, d.get("packet_loss", 0.0) + random.uniform(-0.4, 0.6)))
                cpu = max(0.0, min(100.0, d.get("cpu_pct", 30.0) + random.uniform(-3.0, 4.0)))

                # rare status change
                new_status = d["status"]
                roll = random.random()
                if roll < 0.02:
                    new_status = random.choices(
                        ["online", "warning", "critical", "offline"],
                        weights=[70, 15, 10, 5],
                    )[0]

                # derive status from metrics
                if d["status"] != "offline":
                    if ploss > 8 or latency > 80:
                        new_status = "critical"
                    elif ploss > 4 or latency > 45:
                        new_status = "warning"
                    elif ploss < 1.5 and latency < 25:
                        new_status = "online"

                update = {
                    "latency_ms": round(latency, 2),
                    "packet_loss": round(ploss, 2),
                    "cpu_pct": round(cpu, 1),
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "status": new_status,
                }
                await db.devices.update_one({"id": d["id"]}, {"$set": update})

                # create alert if status worsened
                if new_status != d["status"] and new_status in ("warning", "critical", "offline"):
                    sev: AlertSeverity = "critical" if new_status in ("critical", "offline") else "warning"
                    msg_map = {
                        "warning": f"{d['name']}: degraded performance (latency {round(latency,1)}ms)",
                        "critical": f"{d['name']}: critical state (packet loss {round(ploss,1)}%)",
                        "offline": f"{d['name']}: lost contact",
                    }
                    await _create_alert(d, sev, msg_map.get(new_status, "Anomaly"))

            # purge very old acknowledged alerts (>2h)
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            await db.alerts.delete_many({"acknowledged": True, "timestamp": {"$lt": cutoff}})
        except Exception as e:
            logging.exception("simulation error: %s", e)


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
    await _ensure_seed()
    asyncio.create_task(simulate_metrics_loop())
    logger.info("NetVision OT started — simulation loop running")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
