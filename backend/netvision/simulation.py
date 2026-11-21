"""Simulation mode: mock topology generator, demo seed and the per-tick simulator."""
import random
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from netvision import config
from netvision.alerts import _create_alert, _resolve_device_alerts
from netvision.database import _apply_updates, db
from netvision.models import AlertSeverity, Device, DeviceStatus, DeviceType
from netvision.monitoring import _derive_status, _metric_doc, _worsen_message

_SAMPLE_EVERY = 12  # 12 * 5s = 60s sampling


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


async def _seed_phase4_demo(devices: List[dict]):
    """Simulation-only: plant a small FDB (one switch port with several MACs and
    no LLDP neighbor -> an unmanaged segment) and a couple of PLC child assets,
    so the Topology view demonstrates Phase 4 without needing a real collector.
    Never called in live mode."""
    switches = [d for d in devices if d.get("device_type") == "switch"]
    plcs = [d for d in devices if d.get("device_type") == "plc"]
    now = datetime.now(timezone.utc).isoformat()
    if switches:
        sw = switches[0]
        await db.device_fdb.update_one(
            {"device_id": sw["id"]},
            {"$set": {"device_id": sw["id"], "ts": now, "ports": {
                "Gi1/0/24": ["00:1b:1b:00:00:01", "00:1b:1b:00:00:02", "00:1b:1b:00:00:03"],
            }}},
            upsert=True,
        )
    if plcs:
        plc = plcs[0]
        for a in [
            {"name": "IO-Module-1", "asset_type": "io", "detail": "16DI/16DO"},
            {"name": "IO-Module-2", "asset_type": "io", "detail": "8x Analog In"},
            {"name": "Drive-A1", "asset_type": "drive", "detail": "VFD 7.5kW"},
        ]:
            key = {"parent_device_id": plc["id"], "name": a["name"]}
            await db.assets.update_one(
                key,
                {"$set": {**key, "asset_type": a["asset_type"], "detail": a["detail"], "last_seen": now},
                 "$setOnInsert": {"id": str(uuid.uuid4())}},
                upsert=True,
            )


async def _ensure_seed():
    count = await db.devices.count_documents({})
    if count == 0:
        devs = _build_topology()
        await db.devices.insert_many([d.model_dump() for d in devs])
        await _seed_phase4_demo([d.model_dump() for d in devs])
        # initial alerts for non-online devices
        async for d in db.devices.find({"status": {"$ne": "online"}}, {"_id": 0}):
            sev: AlertSeverity = "critical" if d["status"] in ("critical", "offline") else "warning"
            msg = {
                "warning": "Elevated latency detected",
                "critical": "Device unresponsive — packet loss spike",
                "offline": "Device offline — no heartbeat",
            }.get(d["status"], "Anomaly detected")
            await _create_alert(d, sev, msg)


async def _simulate_tick():
    """One simulation step: jiggle metrics, maybe flip status, create alerts, sample history.

    This is the original per-device simulation body, unchanged in behavior. It only
    runs when simulation mode is ON.
    """
    devices = await db.devices.find({}, {"_id": 0}).to_list(None)
    if not devices:
        return
    metric_docs = []
    ops: List[tuple] = []
    followups: List[tuple] = []
    sample_now = (config._TICK % _SAMPLE_EVERY == 0)
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
        ops.append(({"id": d["id"]}, {"$set": update}))

        # create alert if status worsened
        if new_status != d["status"] and new_status in ("warning", "critical", "offline"):
            sev: AlertSeverity = "critical" if new_status in ("critical", "offline") else "warning"
            followups.append(("alert", d, sev, _worsen_message(d["name"], new_status, latency, ploss)))

        # auto-resolve: device recovered to online -> clear its open alerts
        if d["status"] != "online" and new_status == "online":
            followups.append(("resolve", d["id"]))

        if sample_now:
            metric_docs.append(_metric_doc(d["id"], now_iso, latency, ploss, cpu, new_status))

    # one round-trip for all devices instead of one per device (issue #16)
    await _apply_updates(db.devices, ops, ordered=False)
    for f in followups:
        if f[0] == "alert":
            await _create_alert(f[1], f[2], f[3])
        else:
            await _resolve_device_alerts(f[1])
    if metric_docs:
        await db.device_metrics.insert_many(metric_docs)
