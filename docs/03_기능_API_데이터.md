# 03. 기능, API, 데이터

기준: 저장소 main `a6936ec` (2026-06-07) 코드 직접 확인.

## 1. 화면

| 화면 | 파일 | 주요 기능 |
|---|---|---|
| 대시보드 | `pages/Dashboard.jsx` | KPI 카드, 알람 피드, 네트워크 건강도 |
| 장비 | `pages/Devices.jsx` | 장비 CRUD, 검색, CSV 내보내기, 지표 모달, 인터페이스 모달 |
| 지표 모달 | `components/MetricChartModal.jsx` | 네트워크 지표(지연, 손실, CPU) + 범용 지표 최신값 카드와 시계열 |
| 인터페이스 모달 | `components/InterfaceModal.jsx` | 포트별 상태, 속도, In/Out bps, 에러 카운터 |
| 토폴로지 | `pages/Topology.jsx` | Cytoscape, zone 그룹, LLDP/CDP 링크, 미관리 세그먼트(점선 버블), 논리 자산 노드, 상세 패널 |
| 알람 | `pages/Alerts.jsx` | 필터, 확인, 일괄 확인, CSV, RCA 연관 배지 |
| 디스커버리 | `pages/Discovery.jsx` | IP 대역, SNMP community/버전, 기본 장비 타입, 지금 스캔 |
| 설정 | `pages/Settings.jsx` | 사용자 관리(RBAC, 인증 ON일 때), 감사 로그 |
| 로그인 | `pages/Login.jsx` | 인증 ON일 때만 표시 |

- 한/영 전환: `lib/i18n.jsx`, 사이드바 하단 KO/EN 토글, 기본 한국어. SNMP, CPU, IP 같은 기술 약어는 영어 유지
- 토폴로지 노드 도형: switch=round-rectangle, plc=hexagon, hmi=diamond, sensor=ellipse
- 확정된 아이콘 매핑(미적용): switch=`network`, plc=`cpu`, hmi=`monitor-smartphone`, sensor=`radio-receiver`, 미관리 세그먼트=`cloud`, 논리 자산=`box`

## 2. 기능별 상태

| 기능 | 상태 | 비고 |
|---|---|---|
| 장비 관리, 알람, 대시보드, WebSocket | 완료 | Emergent 초기 구현 기반 |
| 수집 API (ingest) + 시뮬 토글 | 완료 | |
| 알람 자동 해소 | 완료 | online 회복 시 미확인 알람 자동 확인 |
| 알람 디바운스 | 완료 | 같은 장비, 같은 심각도는 60초 내 중복 생성 안 함 |
| ping 수집 | 완료 | Node-RED |
| 디스커버리 (화면 설정 + fping) | 완료 | 실장비 수집 확인 |
| SNMP 식별 (vendor/type) | 완료 | snmpd 자가 테스트로 검증 |
| SNMP CPU | 부분 | 모델별 OID 미확정 |
| 인터페이스/트래픽/포트 상태 | 부분 | 수동 주입 검증 완료, 자동 플로우 Deploy 미확인 |
| 토폴로지 링크 엔진 | 완료 | 수동 링크로 검증 |
| LLDP / CDP 수집 | 스캐폴드 | 실스위치 출력으로 파싱/매칭 확정 필요 |
| 토폴로지 포트 라벨 표시 | 미착수 | 백엔드는 라벨 제공, 프론트 엣지 스타일에 label 없음 |
| 범용 지표 (UnifiedMetric) | 완료 | 화면 표시 포함 |
| Modbus 수집 | 부분 | 시뮬로만 검증 |
| OPC UA | 미착수 | |
| 미관리 세그먼트 탐지 | 부분 | 백엔드 + 화면 완료, FDB 수집 플로우 없음 |
| 논리 자산 토폴로지 | 부분 | 백엔드 + 화면 완료, 자산 수집 플로우 없음 |
| 인증 / RBAC / 감사 로그 | 완료 | 기본 OFF (감사 로그는 기본 ON) |
| 알람 RCA | 완료 | 주석만 추가, 기존 알람 억제 없음 |
| 통지 (Slack / Telegram) | 완료 | 환경변수 설정 시에만 발송. 메일은 미구현 |
| 산업 프로토콜 디스커버리 (CIP, PROFINET, S7, BACnet) | 미착수 | |
| 링 모니터링 (MRP, PRP, REP) | 미착수 | |
| Config 백업 | 미착수 | |
| 비인가 자산 탐지 (MAC Observation) | 설계만 | `06_설계_MAC_Observation.md` |

## 3. API 전체 목록

모두 `/api` 접두어. 장비 매칭은 `device_id` → `ip` → `name` 순서.

### 3.1 장비

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | 헬스 체크 |
| GET | `/devices` | 목록 |
| POST | `/devices` | 생성 |
| GET | `/devices/{id}` | 조회 |
| PATCH | `/devices/{id}` | 수정 (식별 플로우가 vendor/type 교정에 사용) |
| DELETE | `/devices/{id}` | 삭제 (알람, 링크, 지표 등 연관 데이터 같이 정리) |
| POST | `/devices/cleanup` | 이름/IP 접두어로 목업 정리. `dry_run` 기본 true |
| GET | `/devices/{id}/metrics?hours=24` | 네트워크 지표 히스토리 |
| GET | `/devices/{id}/kv` | 범용 지표 최신값 |
| GET | `/devices/{id}/series?metric=<이름>&hours=24` | 범용 지표 시계열 |
| GET | `/devices/{id}/interfaces` | 인터페이스 목록 (bps 포함) |
| GET | `/zones` | zone별 집계 |
| GET | `/dashboard/summary` | 대시보드 요약 |

### 3.2 알람

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/alerts?limit=200` | 목록 |
| POST | `/alerts/{id}/acknowledge` | 확인 |
| DELETE | `/alerts/{id}` | 삭제 |
| POST | `/alerts/bulk-acknowledge` | `{"ids":[...]}`, ids 없으면 전체 미확인 알람 확인 |

### 3.3 수집 입구 (Node-RED → 백엔드)

| 메서드 | 경로 | 본문 예시 | 수집 토큰 대상 |
|---|---|---|---|
| POST | `/ingest?auto_create=false` | `{"samples":[{"ip":"..","reachable":true,"latency_ms":3.2}]}` | 예 |
| POST | `/metrics` | `{"samples":[{"ip":"..","metric_name":"plc.temperature","value":41.5,"unit":"celsius"}]}` | 예 |
| POST | `/interfaces` | `{"ip":"..","interfaces":[{"ifindex":1,"name":"Gi1/1","oper":1,"speed_mbps":1000,"in_octets":0,"out_octets":0}]}` | 예 |
| POST | `/links` | `{"links":[{"source_ip":"..","neighbor_ip":"..","local_port":"Gi0/1","remote_port":"eth0"}]}` | 예 |
| POST | `/discovery/register` | `{"ips":["192.168.0.10", ".."]}` | 예 |
| POST | `/fdb` | `{"ip":"..","entries":[{"port":"Gi1/0/5","mac":"00:11:22:33:44:01"}]}` | 아니오 |
| POST | `/assets` | `{"assets":[{"parent_ip":"..","name":"IO-Module-1","asset_type":"io","detail":"16DI/16DO"}]}` | 아니오 |

- `ingest` 필드: `reachable`(false면 offline), `latency_ms`, `packet_loss`, `cpu_pct`, `uptime_pct`, `status`, `ts`. 빠진 필드는 이전 값 유지
- `ingest?auto_create=true`: 미등록 IP를 최소 장비로 자동 등록
- `metrics`: 최신값(`device_kv`) + 시계열(`unified_metrics`, 24h TTL). 네트워크 상태는 건드리지 않음
- `interfaces`: 연속 두 샘플의 카운터 차이로 bps 계산. 음수 델타(32비트 카운터 wrap)는 무시

### 3.4 디스커버리, 링크, 자산

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/discovery` | 설정 조회 (subnet, community, snmp_version, default_type, run_requested, last_run 등) |
| PUT | `/discovery` | 설정 저장, `run_requested:true`로 스캔 요청 |
| GET | `/links` | 링크 목록 |
| POST | `/links/reset` | 링크 전체 삭제 |
| GET | `/assets` | 논리 자산 목록 |
| POST | `/assets/reset` | 논리 자산 전체 삭제 |
| GET | `/topology` | 노드 + 엣지 (parent_id 트리 + 링크 + 미관리 세그먼트 + 자산) |

### 3.5 시뮬, 목업

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/sim/mode` | 현재 시뮬 상태 |
| POST | `/sim/mode` | `{"enabled":true}` 런타임 토글 (재시작 시 `.env` 값 복귀) |
| POST | `/mock/generate` | 목업 20대 생성. 기존 장비를 지우고 생성하므로 실장비 환경에서 사용 금지 |
| POST | `/mock/reset` | 전체 초기화 (디스커버리 장비 포함) |

### 3.6 인증, 감사

| 메서드 | 경로 | 권한 |
|---|---|---|
| GET | `/auth/config` | 공개 (인증 ON/OFF 여부) |
| POST | `/auth/login` | 공개 |
| GET | `/auth/me` | 로그인 사용자 |
| GET/POST | `/auth/users` | admin |
| PATCH/DELETE | `/auth/users/{username}` | admin |
| GET | `/audit?limit=200` | viewer 이상 |

### 3.7 실시간

| 경로 | 설명 |
|---|---|
| WS `/ws` | 요약, 장비, 알람 스냅샷 주기 푸시 |

## 4. MongoDB 컬렉션 (DB: `netvision`)

| 컬렉션 | 용도 | 보관 |
|---|---|---|
| `devices` | 장비 인벤토리 | 영구 |
| `alerts` | 알람 (`correlated_to`, `state`=active/acknowledged/resolved, `acknowledged_at`, `resolved_at`) | 확인·해소된 알람은 닫힌 시점부터 `ALERT_RETENTION_DAYS`(기본 30일) 뒤 삭제. 2026-11-21 스프린트 2에서 변경(이전: 확인 후 2시간) |
| `device_metrics` | 네트워크 지표 시계열 | 24h TTL |
| `device_kv` | 범용 지표 최신값 | 영구 |
| `unified_metrics` | 범용 지표 시계열 | 24h TTL |
| `device_interfaces` | 인터페이스 최신 상태와 bps | 영구 |
| `links` | LLDP/CDP 이웃 링크 | 영구 |
| `device_fdb` | 스위치 포트별 MAC 목록 | 영구 |
| `assets` | 논리 자산 (PLC 하위 IO 등) | 영구 |
| `discovery` | 디스커버리 설정 (문서 1개, id=`default`) | 영구 |
| `users` | 사용자 (인증 ON일 때) | 영구 |
| `audit` | 감사 로그 | 30일 TTL |

- 보관 기간 중 "영구"는 TTL 인덱스가 없다는 뜻입니다
- `device_interfaces`는 장비당 문서 1개를 최신 상태로 덮어씁니다 (이력 없음)

## 5. 동작 규칙

### 5.1 인증 / RBAC (`backend/auth.py`)

- 표준 라이브러리(hashlib, hmac, secrets)로 구현. 추가 패키지 없음
- 역할: viewer < operator < admin
  - GET, HEAD, OPTIONS: viewer 이상
  - POST, PUT, PATCH, DELETE: operator 이상
  - `/api/auth/users*`: admin
- 미들웨어 처리 순서
  1. 수집 경로(`/api/ingest`, `/api/metrics`, `/api/interfaces`, `/api/links`, `/api/discovery/register`)는 `INGEST_TOKEN`만 검사. 토큰 미설정이면 통과
  2. `AUTH_ENABLED=false`면 전부 통과
  3. 공개 경로(`/api/`, `/api/auth/login`, `/api/auth/config`, `/docs`, `/openapi.json`, `/redoc`) 통과
  4. 나머지는 `Authorization: Bearer <토큰>` 필요
- 감사 로그: 성공한 POST/PUT/PATCH/DELETE만 기록 (사용자, 역할, 메서드, 경로, 상태)

### 5.2 알람 RCA

- 알람 생성 시 장비의 상위(`parent_id`) 장비가 offline 또는 critical이면 `correlated_to=<상위 장비 id>` 추가
- 주석만 추가하고 기존 알람은 억제하지 않음. 알람 화면에 연관 배지로 표시

### 5.3 통지 (`backend/notify.py`)

- 알람이 새로 생성될 때 발송. 표준 라이브러리 urllib 사용, 별도 스레드로 실행
- 채널: Slack incoming webhook, Telegram bot (메일은 미구현)
- `NOTIFY_MIN_SEVERITY` 미만은 발송 안 함. 실패해도 알람 생성에는 영향 없음
- 메시지 형식: `[NetVision OT] CRITICAL — <장비명>: <메시지>`

### 5.4 미관리 세그먼트

- 조건: (스위치, 포트)에서 서로 다른 MAC이 `UNMANAGED_MIN_MACS`(기본 2)개 이상이고, 그 포트에 LLDP/CDP 이웃이 없음
- 결과: 토폴로지에 포트명과 호스트 수가 적힌 점선 버블 노드 추가 (예: Gi1/0/5, 3 hosts). MAC은 최대 50개 보관
- FDB 데이터가 없으면 세그먼트 0개라 기존 토폴로지와 동일
- 시뮬 모드 시드: 첫 스위치 `Gi1/0/24`에 MAC 3개, 첫 PLC에 자산 3개(IO 모듈 2, 드라이브 1)

### 5.5 SNMP 식별 매핑

sysObjectID enterprise 번호로 vendor 판정, 실패 시 sysDescr 키워드. 새 벤더는 Node-RED 함수 노드의 `ENT` 맵에 한 줄 추가.

| enterprise | vendor |
|---|---|
| 9 | Cisco |
| 4329 | Siemens |
| 8691 | Moxa |
| 248 | Hirschmann |
| 8072 | Net-SNMP |

### 5.6 인터페이스 수집 OID (ifTable, `1.3.6.1.2.1.2.2.1`)

| 하위 | 항목 |
|---|---|
| .2 | ifDescr (이름) |
| .5 | ifSpeed (32비트, 약 4Gbps까지) |
| .8 | ifOperStatus (up/down) |
| .10 | ifInOctets (32비트 카운터) |
| .14 | ifInErrors |
| .16 | ifOutOctets (32비트 카운터) |
| .20 | ifOutErrors |
