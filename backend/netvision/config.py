"""Settings (from the environment) and mutable runtime state.

`load_dotenv()` runs here, so import this module before anything that reads the
environment at import time (auth, audit, notify, database).

Everything here is read as ``config.NAME`` at call time (never ``from config import
NAME``), so runtime changes (``POST /api/sim/mode``, ingest timestamps) and test
monkeypatches are seen by every module.
"""
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent.parent  # backend/ (same .env file as before the split)
load_dotenv(ROOT_DIR / '.env')

# Alert correlation (RCA) toggle — default ON. Purely additive: it only annotates
# alerts with the parent device id when the parent is already down; it never
# suppresses or changes existing alert creation.
RCA_ENABLED = str(os.environ.get("RCA_ENABLED", "true")).strip().lower() in ("1", "true", "yes", "on")

# Topology: a switch port carrying this many MACs with NO LLDP/CDP neighbor is
# treated as an "unmanaged segment" (a dumb hub or daisy-chain). Default 2.
UNMANAGED_MIN_MACS = int(os.environ.get("UNMANAGED_MIN_MACS", "2"))

# L2/L3 link inference (issue #48). OFF by default: while off, GET
# /api/topology/inferred answers 404 and nothing else changes. /api/arp ingest is
# always available (it only stores data).
L2_INFERENCE_ENABLED = str(os.environ.get("L2_INFERENCE_ENABLED", "false")).strip().lower() in (
    "1", "true", "yes", "on")
# A MAC that answers for MORE than this many IPs in ARP is flagged as a
# virtualization host / proxy-ARP device (still placed, but marked). Default 4.
L2_VIRT_HOST_MAX_IPS = int(os.environ.get("L2_VIRT_HOST_MAX_IPS", "4"))

# Stale detection (issue #9): in live mode, a device whose last_seen is older than
# this many seconds is marked offline ("no data from collector"). 0 disables.
# Default 180s = 6 missed cycles of the 30s Node-RED ping flow.
STALE_AFTER_SEC = int(os.environ.get("STALE_AFTER_SEC", "180"))
# Alert history retention (issue #10). Resolved/acknowledged alerts are kept this
# many days (previously deleted after 2 hours).
ALERT_RETENTION_DAYS = int(os.environ.get("ALERT_RETENTION_DAYS", "30"))

# Alerts: upper bound of open alerts sent in the live list / every 5s WS snapshot. The
# open-alert COUNT stays exact (count_documents); beyond the cap the UI points
# to the history view.
OPEN_ALERTS_CAP = int(os.environ.get("OPEN_ALERTS_CAP", "2000"))

# Coalesced broadcasting (issue #16): collectors may post many times per second;
# build and send at most one snapshot per BROADCAST_DEBOUNCE_SEC.
BROADCAST_DEBOUNCE_SEC = float(os.environ.get("BROADCAST_DEBOUNCE_SEC", "1.0"))

# Tick counter for metric sampling cadence
_TICK = 0

# ---------------- SIMULATION MODE ---------------- #
# Persistent default from .env. "true" preserves the original demo behavior
# (auto-seed 20 mock devices + random jiggle). Set to "false" for live/ingest mode
# so real data pushed via /api/ingest is NOT overwritten by the simulator.
_SIM_ENV = os.environ.get("SIMULATION_MODE", "true").strip().lower() in ("1", "true", "yes", "on")
# Runtime override via POST /api/sim/mode (None = use env value). Resets on restart.
_SIM_OVERRIDE: Optional[bool] = None
# Timestamp of the last successful ingest (for status endpoint)
_LAST_INGEST_TS: Optional[str] = None
# Process start time: reference for "collector stale" before the first ingest.
_STARTED_AT = datetime.now(timezone.utc)


def sim_on() -> bool:
    """Effective simulation mode: runtime override wins over env default."""
    return _SIM_ENV if _SIM_OVERRIDE is None else _SIM_OVERRIDE
