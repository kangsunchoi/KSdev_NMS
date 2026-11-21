"""Simulation-only mock data endpoints and the runtime simulation-mode toggle."""
from fastapi import APIRouter, HTTPException

from netvision import config
from netvision.alerts import _create_alert
from netvision.database import db
from netvision.devices import _wipe_device_data
from netvision.models import AlertSeverity, SimModePayload
from netvision.simulation import _build_topology, _seed_phase4_demo

router = APIRouter()


# Mock data generator (manual)
def _require_sim_mode():
    """Mock data endpoints wipe collections; never allow them in live mode (issue #5)."""
    # Both the persistent .env setting AND the runtime mode must be simulation:
    # POST /api/sim/mode alone must not unlock wiping a live database.
    if not (config._SIM_ENV and config.sim_on()):
        raise HTTPException(409, "Disabled in live mode (SIMULATION_MODE=false)")


@router.post("/mock/generate")
async def generate_mock(replace: bool = True):
    _require_sim_mode()
    if replace:
        await _wipe_device_data()
    devs = _build_topology()
    await db.devices.insert_many([d.model_dump() for d in devs])
    await _seed_phase4_demo([d.model_dump() for d in devs])
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
@router.post("/mock/reset")
async def reset_all():
    _require_sim_mode()
    await _wipe_device_data()
    return {"status": "cleared"}


@router.get("/sim/mode")
async def get_sim_mode():
    return {"simulation_mode": config.sim_on(), "env_default": config._SIM_ENV, "override": config._SIM_OVERRIDE,
            "last_ingest_ts": config._LAST_INGEST_TS}


@router.post("/sim/mode")
async def set_sim_mode(payload: SimModePayload):
    """Toggle the simulator at runtime. NOTE: this override resets on restart;
    set SIMULATION_MODE in backend/.env for the persistent default."""
    config._SIM_OVERRIDE = payload.enabled
    return {"simulation_mode": config.sim_on(), "note": "runtime override; resets on restart"}
