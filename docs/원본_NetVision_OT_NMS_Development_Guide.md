# NetVision OT - NMS 개발 가이드 & 로드맵

> 이관 메모(2026-11-21): Claude 프로젝트 문서 원문 사본입니다. NMS와 무관한 "9.3 급등주 분석 기준" 절만 빼고, 가운뎃점은 쉼표나 '/'로 바꿨습니다. 실제 구현은 이 문서의 Go/Neo4j 아키텍처 대신 6절 "Emergent 한계 극복 전략"의 Pragmatic 경로(React + FastAPI + MongoDB + Node-RED)로 진행했습니다.

> **작성일**: 2026-06-03  
> **목적**: Cisco IND(Industrial Network Director)를 벤치마킹한 산업용 네트워크 NMS 개발  
> **개발 도구**: Emergent AI (AI-native development platform)  
> **개발자 배경**: 비개발자, AI 에이전트를 통한 개발 진행

---

## 📌 1. 프로젝트 비전

### 1.1 벤치마킹 대상: Cisco IND (Industrial Network Director)
- **특징**: 웹 기반 산업용 NMS, 비-IT 운영 인력용 직관적 UI
- **현황**: 2024년 2월 End-of-Sale, 2026년 2월 지원 종료 예정
- **대체 제품**: Cisco Catalyst Center (DNA Center) — 하지만 IT 중심
- **우리의 기회**: IND의 "산업용 단순성"은 유지하되, "벤더 종속성"과 "모놀리식 아키텍처"를 버린 **멀티벤더 산업용 NMS**

### 1.2 핵심 철학
- **퍼블릭 MIB은 공통, 차이점은 프로파일로**
- **물리는 물리대로, 논리는 논리대로** (네트워크 토폴로지 ≠ 자산 토폴로지)
- **Core는 신성하고, Adapter는 소모품이다**
- **코어는 절대 수정하지 않고, 어댑터/프로파일만 추가하는 것**

---

## 🏗️ 2. 아키텍처 설계

### 2.1 Core-Adapter-Profile 3-Layer

```
┌─────────────────────────────────────────────────────────────┐
│                    NMS Core (수정 불가 영역)                  │
│  • Unified Data Bus (gRPC/HTTP)                             │
│  • TimescaleDB (시계열) + Neo4j (토폴로지) + PostgreSQL      │
│  • Alarm Correlation Engine                                 │
│  • REST API / WebSocket                                     │
│  • Plugin Loader (동적 .so/.dll 로딩)                        │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ 표준 인터페이스 (gRPC/Shared Lib)
┌─────────────────────────────────────────────────────────────┐
│              Adapter Layer (확장 가능 영역)                    │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐   │
│  │ SNMP Adapter│ │ OPC UA      │ │ Native Protocol     │   │
│  │ (Built-in)  │ │ Adapter     │ │ Adapter (Plugin)    │   │
│  │             │ │ (Built-in)  │ │ • S7 Protocol       │   │
│  │ • Public MIB│ │             │ │ • Modbus TCP        │   │
│  │ • Private   │ │ • Client    │ │ • EtherNet/IP       │   │
│  │   Profile   │ │ • Server    │ │ • PROFINET DCP      │   │
│  └─────────────┘ └─────────────┘ └─────────────────────┘   │
│                                                             │
│  [신규 추가 시] adapter_siemens_s7.so 파일만 drop-in       │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ YAML/JSON
┌─────────────────────────────────────────────────────────────┐
│              Profile Layer (설정 기반 확장)                    │
│  profiles/cisco-ie2000.yaml                                │
│  profiles/moxa-eds510e.yaml                                │
│  profiles/s7-1500-opcua.yaml                               │
│  profiles/rockwell-5069.yaml                               │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 UnifiedMetric 스키마 (모든 데이터의 표준)

```protobuf
// api/proto/unified_metric.proto
message UnifiedMetric {
  int64 timestamp = 1;           // Unix timestamp (milliseconds)
  string device_id = 2;          // 고유 장비 ID
  string metric_name = 3;        // "device.temperature", "plc.cpu_load"
  double value = 4;              // 측정값
  string unit = 5;               // "celsius", "percent", "volts"
  map<string, string> tags = 6;  // {vendor: "cisco", model: "ie-2000"}
  string raw_source = 7;         // "oid:1.3.6.1.4.1.9.9.13.1.3.1.3"
}

message DeviceInfo {
  string id = 1;
  string vendor = 2;
  string model = 3;
  string ip = 4;
  string protocol = 5;           // "snmp", "opcua", "modbus_tcp"
}
```

### 2.3 Adapter SDK 인터페이스

```go
// sdk/go/adapter.go
package sdk

type ProtocolAdapter interface {
  Init(config map[string]interface{}) error
  Connect(target string, credentials Credentials) (Connection, error)
  Collect(conn Connection) ([]UnifiedMetric, error)
  Discover(subnet string) ([]DeviceInfo, error)
  Disconnect(conn Connection) error
}
```

### 2.4 Profile YAML 스키마

```yaml
# Profile Schema (JSON Schema로 검증)
vendor: string
model: string
protocol: enum[snmp, opcua, modbus_tcp, ethernet_ip, profinet]
sysObjectID: string  # SNMP 전용, 없으면 null

discovery:
  method: string
  port: int
  register_test: [int]  # Modbus 전용

metrics:
  - name: string           # "device.temperature"
    description: string
    unit: string           # "celsius"
    thresholds:
      warning: float
      critical: float
    # Protocol-specific
    snmp:
      oid: string
      index: int
    modbus:
      register_type: enum[holding, input, coil]
      address: int
      data_type: enum[uint16, int16, float32]
    opcua:
      node_id: string
      namespace: int
```

---

## 🗓️ 3. 개발 로드맵 (총 20~24주)

### Phase 0: 확장성 설계 (Week 1-2) ⭐ 가장 중요
**목표**: "앞으로 10년간 코어를 건드리지 않고 새로운 벤더/프로토콜을 추가할 기반"

| 작업 | 산출물 |
|------|--------|
| Adapter SDK 정의 | `nms_adapter.h` / `adapter.go` — Init, Connect, Collect, Disconnect 4개 함수 |
| Unified Schema 확정 | `Metric`, `Device`, `Interface`, `Alarm` protobuf 정의 |
| Plugin Loader 구현 | `plugin/` 디렉토리 감시 → `.so` 파일 동적 로딩 + hot-reload |
| Profile Schema 확정 | 벤더 YAML 스펙 v1.0 (OID 매핑, 인덱스 규칙, 임계값) |
| Message Bus 설계 | Adapter → Core로 데이터를 넘기는 gRPC 스트리밍 또는 Redis Pub/Sub |

**기술 결정**:
- Adapter 언어: Go (빌드 속도, cross-compile, .so 플러그인 지원)
- Plugin 인터페이스: Go plugin 패키지 또는 HashiCorp go-plugin (RPC 기반, crash isolation)
- Profile 포맷: YAML (버전 관리 친화적)

### Phase 1: NMS Core Platform (Week 3-5)
**목표**: 데이터를 받아 저장하고 API로 노출하는 "뼈대"

| 작업 | 산출물 |
|------|--------|
| Database Layer | TimescaleDB (메트릭), Neo4j (토폴로지 그래프), PostgreSQL (CMDB/인벤토리) |
| Data Ingestion API | gRPC 서버 — Adapter가 붙어서 스트리밍 업로드 |
| REST API | OpenAPI 3.0 스펙 — 장비 CRUD, 메트릭 조회, 토폴로지 쿼리 |
| WebSocket | 실시간 알람 푸시 |
| Plugin Registry | 어떤 Adapter가 로드됐는지, 어떤 Profile이 있는지 관리 |

### Phase 2: SNMP Adapter + Profile Engine (Week 6-8)
**목표**: 네트워크 스위치를 수집하고, 프로파일로 벤더를 자동 인식

| 작업 | 산출물 |
|------|--------|
| SNMP Poller Engine | GoSNMP 기반 v1/v2c/v3 폴러, 10,000대 동시 폴링 |
| Trap/Syslog Receiver | UDP 162/514 수신기, 파서 |
| Profile Engine | sysObjectID 매칭 → YAML 프로파일 로드 → OID 목록 동적 생성 |
| Public MIB Mapper | IF-MIB, ENTITY-MIB, LLDP-MIB, IP-MIB → Unified Schema 변환 |
| Private MIB Mapper | 프로파일의 enterprise OID → `vendor.temperature` 등으로 정규화 |
| 벤더 프로파일 3종 | Cisco IE, Moxa EDS, Hirschmann Octopus |

**확장성 검증**:
- 새로운 벤더 추가 테스트: `profiles/new-vendor.yaml` 파일 하나만 넣으면 자동 인식
- OID 변경 대응: 프로파일 버전 관리 (v1 → v2)

### Phase 3: Topology Engine (Week 9-11)
**목표**: 물리 네트워크 토폴로지 자동 구성

| 작업 | 산출물 |
|------|--------|
| FDB Parser | Bridge-MIB/dot1qTpFdbPort → MAC-to-Port 매핑 |
| LLDP/CDP Parser | 이웃 장비, 포트, VLAN 정보 추출 |
| ARP Correlator | IP-MIB + 외부 ARP 테이블 → MAC-to-IP |
| Unmanaged Segment Detector | "한 포트에 다수 MAC" → 버블 노드 생성 |
| Graph Builder | Neo4j에 `(Device)-[CONNECTED_TO {port}]->(Device)` 저장 |
| Topology API | 최단 경로, 업스트림/다운스트림 쿼리 |

### Phase 4: OPC UA Adapter (Week 12-14)
**목표**: 현대 PLC를 Primary 프로토콜로 수집

| 작업 | 산출물 |
|------|--------|
| OPC UA Client | gopcua 기반, Discovery, Browsing, Subscription |
| Security Manager | X.509 인증서 자동 생성/교환/갱신 파이프라인 |
| PLCopen Profile | IEC 62541 Companion Specification → `plc.cpu_load`, `plc.temperature` |
| Address Space Mapper | 사용자가 OPC UA 노드를 NMS 메트릭으로 매핑하는 UI |
| Adapter Plugin | `adapter_opcua.so` — Core와 독립 프로세스로 통신 |

### Phase 5: Native Protocol Adapters (Week 15-17)
**목표**: 레거시 PLC를 위한 세컨더리 프로토콜 (Plugin 형태)

| 작업 | 산출물 |
|------|--------|
| Modbus TCP Adapter | `adapter_modbus.so` — Holding Register 프로파일 매핑 |
| Siemens S7 Adapter | `adapter_s7.so` — DB 직접 읽기, 프로파일로 DB/Offset 매핑 |
| EtherNet/IP Adapter | `adapter_cip.so` — ListIdentity, Explicit Message |
| PROFINET DCP Adapter | `adapter_profinet.so` — IO Controller/Device 발견, AR 관계 |
| Protocol Profile YAML | `protocols/modbus-tcp.yaml`, `protocols/s7-1500.yaml` |

**확장성 검증**:
- 3rd Party 개발자 가이드: "Adapter 개발 101" 문서 — 4개 함수만 구현
- 샘플 Adapter: `adapter_template.so` (Hello World 수준) 제공

### Phase 6: OT Asset Topology (Week 18-19)
**목표**: PLC 하위 논리 자산 트리

| 작업 | 산출물 |
|------|--------|
| CIP Asset Parser | EtherNet/IP로 IO Adapter, Drive, HMI 발견 |
| PROFINET Asset Parser | DCP + AR로 IO Device 관계 파악 |
| Logical Tree Builder | Neo4j에 `(PLC)-[HAS_CHILD]->(IO_Module)` 저장 |
| UI Overlay | 네트워크 노드 클릭 시 논리 트리 펼침 (Compound Node) |

### Phase 7: UI/UX + Dashboard (Week 20-22)
**목표**: 사용자가 데이터를 보고 조작

| 작업 | 산출물 |
|------|--------|
| React SPA | 토폴로지 그래프 (Cytoscape.js), 메트릭 차트 (Apache ECharts) |
| Topology Viewer | 물리/논리 토글, 줌/패닝, 포트 레벨 드릴다운 |
| Alarm Console | 실시간 알람, ACK, 상관관계(RCA) 표시 |
| Profile Editor | 웹에서 YAML 프로파일 작성/검증/업로드 |
| Adapter Management | Plugin 목록, 상태, 로그, 버전 관리 UI |

### Phase 8: 고급 기능 + 안정화 (Week 23-24)
**목표**: 상용화를 위한 마무리

| 작업 | 산출물 |
|------|--------|
| Event Correlation | "포트 Down → PLC Offline" 자동 RCA |
| Baseline/Anomaly | 메트릭 기준선 학습, 이상 탐지 |
| Config Backup | SSH로 스위치/PLC 설정 백업, 버전 관리 |
| Performance Test | 10,000 네트워크 노드 + 5,000 PLC 시뮬레이션 |
| Documentation | API 문서, Adapter SDK, Profile 작성 가이드 |

---

## 🔌 4. 확장성 보장 메커니즘

### 4.1 Adapter SDK (C/Go/Rust)

```go
// adapter_sdk.go — 어댑터 개발자가 구현해야 할 인터페이스
package sdk

type ProtocolAdapter interface {
  // 1. 초기화 (설정 파일 로드)
  Init(config map[string]interface{}) error

  // 2. 장비 연결/인증
  Connect(target string, credentials Credentials) (Connection, error)

  // 3. 데이터 수집 (Core가 주기적으로 호출)
  Collect(conn Connection) ([]UnifiedMetric, error)

  // 4. 장비 발견 (디스커버리 모드)
  Discover(subnet string) ([]DeviceInfo, error)

  // 5. 연결 해제
  Disconnect(conn Connection) error
}

// Core로 전송하는 표준 메시지
type UnifiedMetric struct {
  Timestamp   int64
  DeviceID    string
  MetricName  string  // "device.temperature", "plc.cpu_load"
  Value       float64
  Unit        string
  Tags        map[string]string
  RawSource   string  // "oid:1.3.6.1.4.1.9.9.13.1.3.1.3"
}
```

### 4.2 동적 플러그인 로딩

```go
// Core의 Plugin Loader
func LoadAdapter(path string) (ProtocolAdapter, error) {
  p, err := plugin.Open(path)  // .so 파일 동적 로드
  // ...
  return adapter, nil
}

// 실행 중 새 Adapter 추가
// $ cp adapter_mitsubishi_melsec.so /opt/nms/adapters/
// → File Watcher가 감지 → hot-reload → 즉시 사용 가능
```

### 4.3 프로파일 기반 벤더 확장 (코드 수정 ZERO)

```yaml
# profiles/mitsubishi-fx5u.yaml — 신규 벤더 추가 예시
vendor: mitsubishi
model: fx5u
protocol: modbus_tcp
sysObjectID: ~  # PLC는 sysObjectID 없음, discovery로 식별

discovery:
  method: modbus_tcp_scan
  port: 502
  register_test: [0, 1]  # Holding Register 0 읽기 테스트

metrics:
  - name: plc.run_status
    description: "PLC RUN/STOP 상태"
    modbus:
      register_type: holding
      address: 0
      data_type: uint16
    mapping:
      0: "STOP"
      1: "RUN"
      2: "PAUSE"
```

**이 파일 하나만 추가하면, Core와 Adapter는 자동으로 FX5U를 인식하고 수집합니다.**

---

## 📁 5. 프로젝트 디렉토리 구조

```
nms-platform/
├── core/                      # 수정 불가 (Core 팀만)
│   ├── api/                   # REST/gRPC 서버
│   ├── db/                    # TimescaleDB, Neo4j, PostgreSQL
│   ├── alarm/                 # 상관관계 엔진
│   ├── plugin/                # Plugin Loader, Registry
│   └── bus/                   # 메시지 버스 (NATS/Kafka)
│
├── adapters/                  # 확장 가능 (3rd Party 개발 가능)
│   ├── snmp/                  # Built-in
│   ├── opcua/                 # Built-in
│   ├── modbus/                # Plugin
│   ├── s7/                    # Plugin
│   ├── cip/                   # Plugin
│   └── template/              # SDK 예시
│
├── profiles/                  # YAML 기반 (엔지니어가 관리)
│   ├── network/
│   │   ├── cisco-ie2000.yaml
│   │   ├── moxa-eds510e.yaml
│   │   └── hirschmann-octopus.yaml
│   └── plc/
│       ├── siemens-s7-1500-opcua.yaml
│       ├── rockwell-5069-cip.yaml
│       └── mitsubishi-fx5u-modbus.yaml
│
├── sdk/                       # Adapter 개발 키트
│   ├── go/                    # Go SDK
│   ├── c/                     # C SDK (임베디드 개발자용)
│   └── docs/                  # "Adapter 개발 가이드"
│
└── ui/                        # React 프론트엔드
    ├── topology/
    ├── dashboard/
    └── admin/                 # Profile/Adapter 관리
```

---

## 🎨 6. Emergent AI 전용 개발 가이드

### 6.1 Emergent AI 플랫폼 개요
- **특징**: 자연어 프롬프트로 풀스택 앱을 생성하는 AI-native 도구
- **5개 전문 에이전트**: Architect, Designer, Developer, Integration, Product Manager
- **기술 스택**: MongoDB 기반 웹 앱 (SaaS, 대시보드, CRUD에 최적화)
- **한계**: SNMP 폴링, 실시간 프로토콜 파싱, 그래프 DB 등 복잡한 백엔드에는 한계

### 6.2 AI 개발 전략 3원칙

| 원칙 | 설명 |
|------|------|
| **Context-First** | 매 프롬프트 시작에 "우리가 뭘 만들고 있는지" 3줄 요약을 붙인다 |
| **Interface-First** | 구현 전에 반드시 인터페이스/스키마를 먼저 짜게 한다 |
| **Test-Driven** | 코드 생성 후 바로 유닛 테스트를 짜게 한다 (AI가 스스로 검증) |

### 6.3 Emergent.sh 사용 워크플로우

**Step 1: 첫 생성 (15분)**
- 상세 프롬프트 입력 → **Architect Agent**가 질문 → 답변
- "Should the topology update in real time or on page refresh?" → **"Real-time via WebSocket"**
- "Do you need user roles?" → **"No, single admin user for now"**

**Step 2: 검토 및 수정 (30분)**
- 생성된 앱의 **Live Preview**를 클릭해서 확인
- 문제점을 찾아 **Follow-up Prompt**로 수정 요청

**Step 3: GitHub Export (즉시)**
- 코드가 괜찮으면 **바로 GitHub로보내기**
- 이유: Emergent은 컨텍스트 윈도우(200K 토큰 Standard)가 꽉 차면 이전 코드를 잊어버림

**Step 4: Forking으로 단계 확장 (컨텍스트 관리)**
- 프로젝트가 커지면 **Fork** 기능으로 새 브랜치 생성
- Phase 1 (UI/대시보드) → Fork → Phase 2 (SNMP 연동) → Fork → Phase 3 (토폴로지 엔진)

### 6.4 초기 프롬프트 (Emergent AI용)

```
Build an Industrial Network Management System (NMS) dashboard called "NetVision OT".

This is a web application for factory engineers to monitor industrial network devices (Ethernet switches, PLCs, sensors, HMIs).

## Tech Stack Requirements
- Frontend: React + TypeScript, Cytoscape.js for network topology graph, Tailwind CSS
- Backend: FastAPI (Python) or Node.js with Express
- Database: MongoDB for device inventory and configuration
- Real-time: WebSocket for live alerts and status updates
- Theme: Dark industrial theme. Background #1a1a2e, accent color #16c79a (teal). Must look like a professional SCADA/NMS tool, not a generic SaaS dashboard.

## Core Features (Phase 1 - MVP)

### 1. Device Management
- Add/edit/delete network devices
- Device types: Switch, PLC, HMI, End Device, Unmanaged Hub
- Fields per device: Name, IP Address, Vendor (Cisco, Moxa, Siemens, Rockwell, Hirschmann), Model, Protocol (SNMP, OPC UA, Modbus TCP, EtherNet/IP, PROFINET), Status (Online/Offline/Warning)
- Auto-discovery simulation: Generate mock discovered devices for demo purposes

### 2. Network Topology Viewer
- Interactive graph using Cytoscape.js
- Node shapes by type: Switch (rectangle, blue), PLC (hexagon, green), HMI (diamond, orange), End Device (circle, gray), Unmanaged Segment (cloud/blob, translucent gray)
- Edges: Solid lines for known connections, dashed lines for inferred/unmanaged segments
- Click node to open side panel with device details
- Zoom, pan, fit-to-screen controls
- Legend overlay

### 3. Dashboard / Home Screen
- Summary cards: Total Devices, Online, Offline, Critical Alerts
- Real-time alert feed (WebSocket simulation)
- Recent events timeline
- Network health score (calculated from device statuses)

### 4. Alert Management
- Alert list table with filters (severity, device, time range)
- Severity levels: Critical (red), Warning (yellow), Info (blue)
- Acknowledge and dismiss actions
- Alert detail view with recommended actions

### 5. Metric Display (Simulation Phase)
- Device detail page with metric tabs
- Metrics: CPU Usage, Memory Usage, Temperature, Port Status, Uptime
- Mock data generator that simulates realistic industrial metric patterns
- Simple line charts (Recharts or Chart.js)

### 6. Profile System (Extensibility Foundation)
- "Device Profile" collection in MongoDB
- Profile fields: Vendor, Model, Protocol, Default Metrics, OID Templates (for SNMP), Thresholds
- Pre-load profiles for: Cisco IE-2000, Moxa EDS-510E, Siemens S7-1500
- When adding a device, auto-match profile by vendor+model

### 7. Adapter Framework (Plugin Architecture)
- "Protocol Adapter" collection in MongoDB
- Each adapter has: Name, Protocol Type, Status (Active/Inactive), Configuration JSON
- Start with 2 adapters:
  a) SNMP Simulator: Generates mock SNMP walk data
  b) OPC UA Simulator: Generates mock OPC UA node values
- Design the code structure so new adapters can be added as separate modules without touching core code

## API Requirements
- REST API with OpenAPI (Swagger) documentation
- Endpoints needed:
  - GET/POST/PUT/DELETE /api/devices
  - GET /api/topology/nodes-and-edges
  - GET /api/alerts
  - POST /api/alerts/{id}/acknowledge
  - GET /api/metrics?device_id={id}
  - GET /api/profiles
  - GET /api/adapters
- WebSocket endpoint: /ws/alerts for real-time push

## Data Model (MongoDB Collections)
1. devices: _id, name, ip, type, vendor, model, protocol, status, profile_id, location, created_at
2. topology_nodes: _id, device_id, type, position {x, y}, parent_id (for unmanaged segments)
3. topology_edges: _id, source, target, port_source, port_target, type (lldp/cdp/inferred)
4. alerts: _id, device_id, severity, message, metric_name, threshold, acknowledged, created_at
5. metrics: _id, device_id, metric_name, value, unit, timestamp
6. profiles: _id, vendor, model, protocol, metrics_template, thresholds
7. adapters: _id, name, protocol, status, config, last_run

## Non-Functional Requirements
- Responsive: Desktop primary, tablet support minimum
- Dark mode only (industrial environment friendly)
- Export: Device list to CSV, Alerts to CSV
- GitHub integration enabled for code export
- Must be production-deployable on Emergent hosting

## Do NOT Include
- No user authentication/login (single-user system for now)
- No payment/billing integration
- No email notifications
- No drag-and-drop UI builders - code must be real React components
```

### 6.5 Architect Agent 질문 답변 가이드

| 질문 | 답변 | 이유 |
|------|------|------|
| Mock data generation? | **c. Both** | Auto-seed(데모용) + Manual button(테스트용) |
| Live metrics simulation? | **a. Yes, auto-refresh every few seconds** | 실시간 파이프라인을 지금 구축 |
| Topology connections? | **a. Auto-generate realistic hierarchy** | 수동 정의는 Visio와 다름없음 |
| Alert generation? | **a. Auto-generated based on simulated device states** | 임계값 엔진을 지금 구축 |
| Design preference? | JetBrains Mono + Inter, SCADA/HMI 느낌, functional over beautiful | 산업용 전문성 |

### 6.6 추가 기능 제안 수락 전략

**수락할 기능**:
- Per-device historical metric chart
- Bulk acknowledge + text search on Devices table
- WebSocket push instead of polling
- CSV export of devices/alerts
- Group devices by plant zone/cell with collapsible topology sub-views
- Per-alert rate-limiting to avoid burst-flood during status flips
- Stricter API contract: 404 on metrics for unknown device id

**거절할 기능**:
- Multi-tenant with RBAC
- Microservices architecture
- Kubernetes-native
- OAuth2 / JWT authentication (Phase 1에서)

### 6.7 Follow-up Prompt 템플릿

**디스커버리 기능 강화**:
```
Add a "Network Discovery" feature to the Devices page:

1. "Discover Devices" button in the top toolbar
2. Opens a modal with:
   - Subnet input field (default: 192.168.1.0/24)
   - Protocol checkboxes: SNMP, OPC UA, Modbus TCP
   - "Start Scan" button
3. Simulation: After 3 seconds, show progress bar and "Found X devices"
4. Discovered devices are auto-added to the device list with:
   - Auto-detected type (Switch if port 161 responds, PLC if port 4840 responds)
   - Auto-matched profile by vendor guess from MAC OUI or device name pattern
   - Status: "Discovered - Pending Configuration"
5. Show discovery log: "10:05:12 - Scanning 192.168.1.1...10:05:13 - Found device at 192.168.1.10 (Cisco IE-2000)..."

Use mock/simulated responses for now. The UI and flow must be production-ready.
```

**토폴로지 엣지 개선**:
```
The topology graph shows nodes but no connection lines between them. Fix this:

1. Every Switch node must have edges (lines) connecting to its downstream PLCs and End Devices
2. Edge style: Solid line (#2a3b55, 2px) for known connections, Dashed line (#4a5568, 1px) for inferred/unmanaged
3. Click edge to show tooltip: "Switch-01:Port-3 → PLC-01:Eth0"
4. Unmanaged Segment nodes must show dashed edges to all child devices inside them
5. Add a "Refresh Topology" button that re-calculates connections based on current device list
```

**프로파일 자동 매칭**:
```
When a device is discovered or manually added, auto-match it to a Profile:

1. On device creation, check Profiles collection for matching vendor + model
2. If match found, auto-populate:
   - Default metrics (CPU, Temperature, Port Status)
   - Thresholds (Warning 55°C, Critical 70°C)
   - Protocol-specific config (SNMP community string template, OPC UA endpoint template)
3. Show "Profile Matched: Cisco IE-2000" badge on device detail page
4. If no match, show "No Profile - Add Custom" button linking to Profile Editor

Pre-load these profiles in MongoDB:
- Cisco IE-2000 (SNMP)
- Moxa EDS-510E (SNMP)
- Siemens S7-1500 (OPC UA)
- Rockwell 5069 (EtherNet/IP)
```

### 6.8 Emergent.sh 한계 극복 전략

| Emergent.sh가 잘하는 것 | Emergent.sh가 어려운 것 | 해결책 |
|----------------------|---------------------|--------|
| 웹 UI, 대시보드, CRUD | SNMP/OPC UA 실시간 폴링 | **Node-RED** 또는 **Telegraf**를 별도로 두고, Emergent 백엔드가 그 데이터를 받아 표시만 함 |
| MongoDB 스키마/API | 시계열 DB (TimescaleDB) | MongoDB에 시계열 데이터를 그대로 저장하거나, **InfluxDB Cloud**를 외부 연동 |
| 반응형 UI, 알람 콘솔 | 그래프 DB (Neo4j) | MongoDB의 `$graphLookup`으로 토폴로지 조회를 대체, 또는 Neo4j를 Docker로 띄우고 REST API로 연동 |
| 인증, 배포 | 산업 프로토콜 파싱 | **Kepware/OPC Router** 같은 상용 게이트웨이를 중간에 두고, Emergent는 게이트웨이의 REST API만 호출 |

**공식**: **"Emergent는 뇌(관리/시각화)가 되고, 데이터 수집은 기존 산업용 도구가 감각기관이 되는 구조"**

---

## 🎯 7. 핵심 기능 상세 설계

### 7.1 수집 데이터의 두 개 층 (Two-Layer Model)

#### Layer 1: Universal / Public MIB (벤더 무관 공통)
모든 네트워크 장비가 의무적으로 지원하는 표준 MIB입니다.

| MIB | OID Base | 수집 항목 | 표시 방식 |
|-----|----------|----------|----------|
| **SNMPv2-MIB** | 1.3.6.1.2.1.1 | sysDescr, sysObjectID, sysUpTime, sysContact | 장비 기본 정보 패널 |
| **IF-MIB** | 1.3.6.1.2.1.2 | ifTable, ifXTable | 포트 목록, 대역폭 그래프 |
| **IP-MIB** | 1.3.6.1.2.1.4 | ipAddrTable, ipRouteTable | IP 주소, 라우팅 테이블 |
| **ENTITY-MIB** | 1.3.6.1.2.1.47 | entPhysicalTable | 모듈/슬롯/파워 서플라이 |
| **LLDP-MIB** | 1.3.6.1.2.1.16 | lldpRemTable | 토폴로지 자동 구성 |
| **Bridge-MIB** | 1.3.6.1.2.1.17 | dot1dBase/dot1qVlan | VLAN, MAC 테이블 |

#### Layer 2: Vendor Enterprise MIB (벤더별 차이점)

| 벤더 | Enterprise OID | 프라이빗 MIB 예시 | 특화 데이터 |
|------|---------------|-------------------|-------------|
| **Cisco** | 1.3.6.1.4.1.9 | CISCO-ENV-MON-MIB, CISCO-PROCESS-MIB | CPU/메모리 상세, 온도, PoE, STP 상세 |
| **Siemens Scalance** | 1.3.6.1.4.1.4329 | SCALANCE-MIB | PROFINET 우선순위, 산업 프로토콜 통계 |
| **Moxa** | 1.3.6.1.4.1.8691 | MOXA-IKS-MIB | 릴레이 출력 상태, 파워 입력 전압, 트래픽 우선순위 |
| **Hirschmann** | 1.3.6.1.4.1.248 | Hirschmann-MIB | HIPER-Ring 상태, MRP 관리자 상태, 산업 이더넷 진단 |

### 7.2 PLC 데이터 수집 전략

#### OPC UA vs 네이티브 프로토콜 비교

| 구분 | OPC UA Client 방식 | 네이티브 프로토콜 방식 |
|------|-------------------|---------------------|
| **대상** | 현대 PLC (S7-1500, Beckhoff, B&R, CODESYS) | 레거시 PLC (S7-300/400, Modbus-only) |
| **데이터 의미** | `Device.Temperature` 이름과 단위, 품질 플래그, 타임스탬프 함께 제공 | Modbus의 Holding Register 40001이 "온도"인지 외부 문서로 매핑 필요 |
| **보안** | X.509 인증서, TLS/AES 암호화, 세션 기반 접근 제어 | Modbus TCP는 인증/암호화 없음 |
| **주소 공간** | 동적 브라우징 가능 | 미리 주소 매핑 필요 |
| **Companion Spec** | PLCopen, ISA-95 등 표준 정보 모델 | 벤더별 독자 규격 |
| **오버헤드** | 헤더 무거움, 1만 대 이상 스케일링 시 부하 | 가벼움 |
| **복잡도** | 클라이언트/서버 모델, 세션 관리, 인증서 교환 복잡 | 단순 폴링 |

**전략**: **OPC UA를 Primary로, Modbus TCP를 Secondary로, 벤더 특화는 고객 요구 기반**

#### 하이브리드 PLC 어댑터 아키텍처

```
┌─────────────────────────────────────────┐
│           NMS Core (Go/Rust)            │
│  - Unified Device Model (정규화된 스키마)  │
│  - 메트릭 저장 (TimescaleDB)             │
│  - 알람/토폴로지 엔진                     │
└─────────────────────────────────────────┘
                    ▲
                    │ gRPC / HTTP / MQTT
┌─────────────────────────────────────────┐
│      PLC Adapter Layer (Edge/Gateway)    │
│  ┌─────────────┐  ┌─────────────┐       │
│  │ OPC UA      │  │ Native       │       │
│  │ Client      │  │ Protocol     │       │
│  │ (Primary)   │  │ Bridge       │       │
│  │             │  │ (Secondary)  │       │
│  │ • Siemens   │  │ • Modbus TCP │       │
│  │   S7-1500   │  │ • S7 Protocol│       │
│  │ • Beckhoff  │  │ • EtherNet/IP│       │
│  │ • B&R       │  │ • PROFINET   │       │
│  │ • CODESYS   │  │ • MELSEC     │       │
│  └─────────────┘  └─────────────┘       │
└─────────────────────────────────────────┘
```

### 7.3 토폴로지 엔진

#### 두 개의 토폴로지 분리

| 토폴로지 유형 | 수집 방법 | 표시 대상 | 예시 |
|-------------|----------|----------|------|
| **물리 네트워크 토폴로지** | SNMP FDB + LLDP/CDP + ARP | 스위치, 포트, PLC, PC, 서버 | 스위치 포트 3 → PLC-01 |
| **논리 자산 토폴로지** | 산업 프로토콜(CIP/PROFINET/OPC UA) | PLC 하위 IO 모듈, 드라이브, 센서 | PLC-01 → IO 모듈 #2 → 채널 4 |

#### Unmanaged Segment Detector 알고리즘

```python
function detectUnmanagedSegments(switch):
    fdb = snmp_get_fdb(switch)  # {mac: port}
    port_macs = groupByPort(fdb)

    for port, macs in port_macs:
        neighbor = get_lldp_neighbor(switch, port)
        if len(macs) > 1 and not neighbor:
            # Unmanaged Hub 또는 다수 단말이 연결된 포트
            create_unmanaged_segment(switch, port, macs)

            # ARP 테이블로 IP 매핑 시도
            for mac in macs:
                ip = arp_table.get(mac)
                device = lookup_inventory(mac, ip)
                add_to_segment(segment_id, device)
```

#### UI Compound Node 시각화

```
[Switch-01]──►[Port Gi1/0/3]──►[ ? ]  ← "Unmanaged Segment" (회색 구름 모양)
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              [PC-01]      [HMI-02]     [Unknown MAC]
             192.168.1.21  192.168.1.22   (Silent)
```

### 7.4 알람 및 이벤트 관리

| 기능 | 설명 |
|------|------|
| **이벤트 상관관계** | 동일 장애로 인한 다중 알람 중복 제거 (예: 업링크 다운 → 다수 노드 Unreachable 알람 1건으로 집계) |
| **AI 기반 이상 탐지** | 정적 임계값 대신 LSTM/Isolation Forest로 트래픽 패턴 이상 감지 |
| **심각도 자동 조정** | CPU 90%가 1분 지속 vs 1시간 지속 시 다른 심각도 |
| **알람 플로우** | PagerDuty/Slack/Teams 연동 (Webhook) |

---

## ⚠️ 8. 주의사항 및 리스크 관리

### 8.1 AI 개발 시 주의사항

1. **"생성된 코드를 그대로 믿지 마세요"** — AI는 OID를 잘못 쓰거나, Go의 nil pointer dereference를 자주 만듭니다. 반드시 `go test`와 `go vet`을 통과시키세요.

2. **"YAML Schema는 AI가 자꾸 바꿉니다"** — `profiles/`의 YAML 구조가 AI 세션마다 달라지면 Adapter가 파싱 에러를 냅니다. JSON Schema를 `sdk/profile-schema.json`으로 고정하고 AI에게 "이 스키마를 따르라"고 강제하세요.

3. **"Neo4j Cypher 쿼리는 AI가 잘 못 씁니다"** — 복잡한 그래프 쿼리는 AI가 relationship 방향을 거꾸로 쓰는 경우가 많습니다. Cypher 쿼리는 항상 `EXPLAIN`으로 실행 계획을 확인하세요.

4. **"Context Window 관리"** — 6개월치 대화를 한 세션에 넣으면 AI가 과거 내용을 잊습니다. 주차별로 세션을 나누고, **"이전에 정의한 XXX를 따름"**이라고 명시적으로 언급하세요.

### 8.2 Emergent.sh 특유의 함정

- **MongoDB만 기본 지원**: TimescaleDB나 Neo4j는 직접 연동해야 함
- **복잡한 네트워크 프로토콜 스택 한계**: SNMP 폴링 엔진, OPC UA 클라이언트는 한계 있음
- **과도한 추상화**: 복잡한 아키텍처를 받으면 코드가 수정하기 어려워짐

### 8.3 IND 벤치마킹 시 피할 것

- ❌ **Cisco 전용 MIB에만 의존** → 멀티벤더 지원 필수
- ❌ **모놀리식 아키텍처** → 마이크로서비스/플러그인 기반
- ❌ **OT-IT 경계 무시** → 산업용 단순성 + IT 보안 동시 충족

---

## 📚 9. 참고 자료

### 9.1 Cisco IND 특징
- 웹 기반 산업용 NMS
- CIP/PROFINET 디스커버리
- 통합 토폴로지 (네트워크 + 자동화 자산)
- 웹 기반 GUI (비-IT 운영 인력용)
- 알람/대시보드 (CPU/메모리/온도/대역폭 + 포트 상태)
- REST API (북바운드/사우스바운드 연동)
- 디바이스 팩 (Cisco IE 스위치 중심 템플릿)

### 9.2 ISO/TMN 계층 모델

```
[SML] Service Management Layer
    ├── 고객 포털 / SLA 대시보드 / 티켓 연동
    └── Northbound API (REST/gRPC)

[NML] Network Management Layer  
    ├── 이벤트 상관관계(RCA) 엔진
    ├── 근본원인 분석 / 알람 집계
    └── 토폴로지 계산 / 경로 분석

[EML] Element Management Layer
    ├── SNMP(v1/v2c/v3) 수집기
    ├── Syslog/Trap 수집기
    ├── NETCONF/RESTCONF 에이전트
    ├── ICMP/LLDP/CDP 디스커버리
    └── 산업 프로토콜 어댑터 (CIP/PROFINET/OPC-UA)
```

---

## ✅ 10. 오늘부터 시작하는 실행 순서

### Step 0: 오늘 할 일 (개발 환경 세팅) — 30분

```bash
# 1. Go 설치 확인 (1.22 이상)
go version

# 2. 프로젝트 폴더 생성
mkdir -p ~/projects/nms-platform && cd ~/projects/nms-platform
go mod init github.com/yourname/nms-platform

# 3. 필요한 도구 설치
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/protobuf/cmd/protoc-gen-go-grpc@latest

# 4. Docker로 데이터베이스 띄우기
docker compose up -d

# 5. 폴더 구조 생성
mkdir -p api/proto core/{plugin,db,topology,alarm} adapters/snmp profiles/network profiles/plc sdk/go ui docs
```

### Step 1: AI에게 첫 작업 시키기 (계약서 작성) — 1시간

**Cursor를 열고, `.cursorrules` 파일을 프로젝트 루트에 만들고 저장:**

```markdown
당신은 산업용 NMS "NetVision OT"의 개발자입니다.

## 아키텍처
- Core-Adapter-Profile 3-Layer
- Core: Go, gRPC, TimescaleDB, Neo4j, NATS
- Adapter: HashiCorp go-plugin (독립 프로세스)
- Profile: YAML (vendor/model/metrics/oids)
- 모든 Adapter는 UnifiedMetric protobuf로 Core에 데이터 전송

## 절대 규칙
1. Core는 Adapter를 import하지 않는다.
2. 모든 메트릭은 UnifiedMetric으로 정규화한다.
3. 에러는 fmt.Errorf("%w", err)로 wrapping한다.
4. 테스트는 table-driven 방식으로 작성한다.
5. OID나 레지스터 주소는 반드시 3번 검증한다.
```

**AI에게 첫 프롬프트를 던지고, 생성된 파일을 Git 커밋:**

```bash
git init
git add .
git commit -m "feat: core contract - proto, adapter sdk, profile schema"
```

### Step 2~8: 주차별 반복

| 주차 | 작업 | 산출물 |
|------|------|--------|
| Week 1-2 | 확장성 설계 | proto, SDK, Profile Schema |
| Week 3-5 | Core Platform | DB, API, WebSocket, Plugin Registry |
| Week 6-8 | SNMP Adapter | Poller, Profile Engine, Cisco/Moxa Profile |
| Week 9-11 | Topology Engine | FDB, LLDP, ARP, Unmanaged Segment |
| Week 12-14 | OPC UA Adapter | Client, Security, PLCopen Profile |
| Week 15-17 | Native Adapters | Modbus, S7, CIP, PROFINET |
| Week 18-19 | OT Asset Topology | CIP/PROFINET Parser, Logical Tree |
| Week 20-22 | UI/UX | React, Cytoscape, Dashboard |
| Week 23-24 | 고급 기능 | RCA, Anomaly, Config Backup, 문서화 |

---

> **"코어는 신성하고, Adapter는 소모품이다"**
> 
> Core의 `UnifiedMetric` 스키마는 최소한의 필드로 유지하세요. 벤더 특화 필드를 넣으면 확장성이 죽습니다.
> Adapter는 프로세스 격리로 실행하세요. S7 Adapter가 Siemens PLC의 변칙적인 응답으로 panic이 나도 Core는 죽지 않아야 합니다.
> Profile은 Git으로 버전 관리하세요. 고객사별로 포크해서 커스텀 프로파일을 만들 수 있게 하세요.
