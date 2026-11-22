"""Pydantic models: stored documents and request payloads."""
import uuid
from datetime import datetime, timezone
from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from netvision.helpers import _normalize_ip, _valid_ipv4

SiteId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]

DeviceType = Literal["switch", "plc", "hmi", "sensor", "l2-switch", "l3-switch", "router", "server", "storage", "workstation", "access-point", "wireless-controller"]
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
    site_id: SiteId = "default"


class DeviceCreate(DeviceBase):
    @field_validator("ip")
    @classmethod
    def _check_ip(cls, v: str) -> str:
        v = (v or "").strip()
        if not _valid_ipv4(v):
            raise ValueError("ip must identify an IPv4 device")
        return _normalize_ip(v)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name must not be empty")
        return v


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    ip: Optional[str] = None  # validated in update_device only when it actually changes
    vendor: Optional[str] = None
    model: Optional[str] = None
    protocol: Optional[str] = None
    device_type: Optional[DeviceType] = None
    zone: Optional[str] = None


class Device(DeviceBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: DeviceStatus = "online"
    latency_ms: Optional[float] = None
    packet_loss: float = 0.0
    uptime_pct: float = 100.0
    cpu_pct: float = 0.0
    last_seen: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    parent_id: Optional[str] = None  # for topology hierarchy
    stale: bool = False  # offline because the collector stopped sending data (issue #9)


class Alert(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    device_id: str
    device_name: str
    severity: AlertSeverity
    message: str
    acknowledged: bool = False  # kept for older clients: True once acknowledged OR resolved
    # Lifecycle (issue #10): active -> acknowledged (operator) / resolved (device recovered)
    state: Literal["active", "acknowledged", "resolved"] = "active"
    acknowledged_at: Optional[str] = None
    resolved_at: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # RCA: id of the parent/upstream device whose outage likely caused this alert.
    # None = standalone / root-cause alert. Optional so older clients ignore it.
    correlated_to: Optional[str] = None


# ---------------- REQUEST PAYLOADS ---------------- #

class CleanupPayload(BaseModel):
    """Selective cleanup of leftover mock devices, matched by name prefix and/or
    IP prefix. dry_run=True (default) only previews. Both criteria, when given,
    must match (conservative) so real discovered devices are not removed."""
    model_config = ConfigDict(extra="ignore")
    name_prefixes: List[str] = ["SW-", "PLC-", "SNS-"]
    ip_prefix: Optional[str] = "10.20."
    dry_run: bool = True


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

    @field_validator("subnet")
    @classmethod
    def _ipv4_subnet(cls, value):
        if value and ":" in value:
            raise ValueError("Only IPv4 discovery ranges are supported")
        return value


class DiscoveryRegister(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ips: List[str] = []
    site_id: SiteId = "default"


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
    site_id: Optional[SiteId] = None
    device_id: Optional[str] = None
    ip: Optional[str] = None
    name: Optional[str] = None
    interfaces: List[IfRow] = []


class FdbEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    port: str
    mac: str


class FdbPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    site_id: Optional[SiteId] = None
    device_id: Optional[str] = None
    ip: Optional[str] = None
    name: Optional[str] = None
    entries: List[FdbEntry] = []


class AssetPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    site_id: Optional[SiteId] = None
    parent_device_id: Optional[str] = None
    parent_ip: Optional[str] = None
    parent_name: Optional[str] = None
    name: str
    asset_type: str = "module"     # module | drive | io | hmi | sensor ...
    detail: Optional[str] = None


class AssetsPayload(BaseModel):
    assets: List[AssetPayload] = []


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


class GenericSample(BaseModel):
    model_config = ConfigDict(extra="ignore")
    site_id: Optional[SiteId] = None
    device_id: Optional[str] = None
    ip: Optional[str] = None
    name: Optional[str] = None
    metric_name: str            # e.g. "plc.temperature", "plc.run_status"
    value: float
    unit: Optional[str] = ""
    ts: Optional[str] = None


class MetricsPayload(BaseModel):
    samples: List[GenericSample]


# Bulk acknowledge alerts
class BulkAckPayload(BaseModel):
    ids: Optional[List[str]] = None  # if None, ack ALL open


class MetricSample(BaseModel):
    """One measurement from an external collector (Node-RED / Telegraf / etc.).

    Identify the target device by ANY of device_id / ip / name (checked in that order).
    Provide whatever metrics you have — omitted fields keep their previous value.
    """
    model_config = ConfigDict(extra="ignore")
    site_id: Optional[SiteId] = None
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


# Simulation mode control (for switching demo <-> live without editing files)
class SimModePayload(BaseModel):
    enabled: bool
