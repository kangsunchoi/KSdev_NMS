"""Pure helpers: IP validation/normalization and timestamps."""
import ipaddress
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


def _valid_ipv4(value: str) -> bool:
    try:
        return not ipaddress.IPv4Address((value or "").strip()).is_unspecified
    except ValueError:
        return False


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
