"""Pure helpers: IP / MAC validation and normalization, timestamps."""
import ipaddress
import re
from datetime import datetime, timezone, timedelta
from typing import Optional


def _valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address((value or "").strip())
        return True
    except ValueError:
        return False


def _normalize_ip(value: str) -> str:
    """Canonical text form (e.g. lower-case IPv6) so duplicate checks compare like with like."""
    return str(ipaddress.ip_address(value.strip()))


_HEX12 = re.compile(r"[0-9a-f]{12}")
_CISCO_DOTTED = re.compile(r"[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}")
_HEX_GROUP = re.compile(r"[0-9a-f]{1,2}")
_INVALID_MACS = {"000000000000", "ffffffffffff"}


def _normalize_mac(value) -> Optional[str]:
    """Canonical 'aa:bb:cc:dd:ee:ff', or None when the value is not a usable MAC.

    Accepts any case and these forms: aa:bb:cc:dd:ee:ff, aa-bb-cc-dd-ee-ff,
    'aa bb cc dd ee ff' (SNMP hex string), aabb.ccdd.eeff (Cisco), aabbccddeeff.
    Colon/dash/space groups may drop a leading zero (net-snmp prints 0:1b:...).
    Mixed separators, all-zero (incomplete ARP) and broadcast are rejected."""
    if not isinstance(value, str):
        return None
    s = value.strip().lower()
    hexstr = None
    if _HEX12.fullmatch(s):
        hexstr = s
    elif _CISCO_DOTTED.fullmatch(s):
        hexstr = s.replace(".", "")
    else:
        for sep in (":", "-", " "):
            parts = s.split(sep)
            if len(parts) == 6 and all(_HEX_GROUP.fullmatch(p) for p in parts):
                hexstr = "".join(p.zfill(2) for p in parts)
                break
    if hexstr is None or hexstr in _INVALID_MACS:
        return None
    return ":".join(hexstr[i:i + 2] for i in range(0, 12, 2))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into an aware UTC datetime. None if invalid."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # naive collector time is treated as UTC
    return dt.astimezone(timezone.utc)


def _normalize_ts(value: Optional[str]) -> str:
    """Collector timestamps are stored as UTC ISO strings with the SAME format as
    server timestamps, so string range queries/sorts stay correct (issue #12).
    Invalid or future (>60s ahead) values fall back to server time."""
    now = datetime.now(timezone.utc)
    dt = _parse_ts(value)
    if dt is None or dt > now + timedelta(seconds=60):
        return now.isoformat()
    return dt.isoformat()


def _serialize(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


# IPs that do not identify a real device (auto-created name-only devices use 0.0.0.0)
_PLACEHOLDER_IPS = {"0.0.0.0", "::"}


def _is_placeholder(ip: Optional[str]) -> bool:
    """0.0.0.0 / :: in any spelling (e.g. '::0', ' 0.0.0.0 ') (#36)."""
    v = (ip or "").strip()
    if v in _PLACEHOLDER_IPS:
        return True
    return _valid_ip(v) and _normalize_ip(v) in _PLACEHOLDER_IPS
