# NetVision OT — 구현 기록 (Pragmatic 경로)

> 이관 메모(2026-11-21): Claude 프로젝트 문서 원문 사본입니다. 가운뎃점만 쉼표나 '/'로 바꿨고 내용은 그대로입니다. 이후 진행 상황은 `01_작업이력.md`, `05_남은작업.md`를 보세요.

> 참조 문서: `NetVision_OT_NMS_Development_Guide.md`(로드맵)의 **섹션 6 "현실적 Emergent 경로"** 를 실제로 구현한 기록.
> 원칙: **"앱은 뇌(관리/시각화), 수집은 Node-RED가 감각기관"** — Core를 Go로 재작성하지 않고, 기존 React+FastAPI+MongoDB 앱에 **수집 입구(API)** 와 **Node-RED 수집기**를 붙여 단계적으로 실데이터화.
> 작성 기준: 2026-06. 저장소: `https://github.com/kangsunchoi/KSdev_NMS`

---

## 0. 이번 작업 요약

기존 NetVision OT 앱은 **시뮬레이션 데이터로만** 도는 관제 화면이었다. 이번 작업으로:

- 외부 수집기가 실데이터를 밀어넣는 **Ingestion API** 추가 + 시뮬레이션 토글
- **Node-RED**를 같은 VM에 설치, 수집기 역할로 연결 (ping / SNMP / 디스커버리 / 식별 / LLDP / Modbus)
- 알람 **자동 해소**, **토폴로지 링크 엔진**, **범용 지표(UnifiedMetric)** 토대 구축
- 모든 백엔드 변경은 **프론트 수정 없이** 동작(기존 화면이 그대로 새 데이터를 소비)

데이터 흐름:
```
[실장비/시뮬]            [Node-RED :1880]                 [NetVision 백엔드 :8001]      [대시보드 :8080]
스위치/PLC  ──ping/SNMP/Modbus──▶  수집 플로우  ──HTTP POST──▶  /api/ingest /api/metrics /api/links  ──WS──▶  화면
```

---

## 1. 배포 구성 (같은 VM, 포트 분리 공존)

ksdev(기존 앱)와 NetVision을 한 VM에 나란히 운영. 코드 경로 `/home/ksadmin/KSdev_NMS`.

| 포트 | 프로그램 | 비고 |
|---|---|---|
| 80 | ksdev nginx | 기존 앱(건드리지 않음) |
| 8000 | ksdev 백엔드 | 기존 |
| **8080** | **NetVision nginx** | 대시보드 접속: `http://192.168.108.129:8080` |
| **8001** | **NetVision 백엔드** | systemd `netvision-backend`, uvicorn |
| **1880** | **Node-RED** | 수집기 편집/실행, systemd `nodered` |
| **1502** | Modbus 시뮬 서버 | Node-RED 내부(테스트용) |
| 27017 | MongoDB | DB명 분리: `netvision` |

### 핵심 설정 포인트
- **Nginx `/api/` 프록시에 WebSocket 업그레이드 헤더 필수** (`Upgrade`/`Connection`). 없으면 대시보드 실시간 갱신이 안 됨.
- `backend/.env`: `MONGO_URL`, `DB_NAME="netvision"`, `CORS_ORIGINS="http://192.168.108.129:8080"`, `SIMULATION_MODE`(true=데모, false=실데이터).
- 백엔드 최소 의존성: `fastapi uvicorn[standard] motor pymongo pydantic python-dotenv` (저장소 requirements.txt의 `emergentintegrations` 등은 설치 실패하므로 미사용).

### 반영(배포) 절차
```bash
# (호스트 PC) GitHub Desktop: 파일 덮어쓰기 → commit → push
# (VM)
cd ~/KSdev_NMS && git pull
sudo systemctl restart netvision-backend   # 백엔드 변경 시
cd frontend && yarn build                   # 프론트 변경 시(이번 작업엔 없음)
```

---

## 2. 백엔드 변경 (`backend/server.py`)

모든 추가는 **동작 보존** 원칙(기존 시뮬 로직 재활용) + 문법 검증 후 반영. 프론트 변경 없음.

### 2.1 Ingestion API + 시뮬레이션 토글
- `POST /api/ingest` — 외부 수집기의 네트워크 지표 수신. 장비는 `device_id → ip → name` 순으로 매칭. 받은 데이터를 **기존 판정→알람→히스토리→WebSocket 파이프라인에 그대로 태움**. `?auto_create=true`면 미등록 IP를 최소 장비로 자동 등록.
  - 필드: `reachable`(ping up/down→offline), `latency_ms`, `packet_loss`, `cpu_pct`, `uptime_pct`, `status`, `ts`
- `SIMULATION_MODE`(.env) — `true`면 기존처럼 목업 20대 자동 시드 + 랜덤 시뮬. `false`면 시뮬 생성 중단(실데이터 안 덮어씀), 자동 시드 안 함. 단 WebSocket 방송, 알람 정리는 양쪽 모드 모두 유지.
- `GET/POST /api/sim/mode` — 재시작 없이 시뮬 토글(런타임 오버라이드, 재시작 시 .env 기본값으로 복귀).
- 판정 로직을 `_derive_status()` 공용 함수로 분리 → 시뮬/실데이터가 **동일 기준**으로 상태 판정.

### 2.2 알람 자동 해소
- 장비가 `online이 아니던 상태 → online`으로 회복되면 그 장비의 미확인 알람을 자동 확인(acknowledged) 처리(`_resolve_device_alerts()`). 시뮬/실데이터 양쪽 적용. 알람 생성 로직은 불변.

### 2.3 토폴로지 링크 엔진
- `links` 컬렉션 + `POST /api/links` — 이웃 관계 수신, 양 끝을 `id/ip/name`으로 장비 매칭해 upsert. 매칭 실패는 `unresolved`로 보고.
- `GET /api/links`, `POST /api/links/reset`
- `GET /api/topology`가 링크를 엣지로 포함 → **프론트 변경 없이** Cytoscape가 연결선을 그림. (기존 `parent_id` 기반 트리 + 링크 엣지 병합)

### 2.4 범용 지표 (UnifiedMetric)
네트워크 지표(latency/packet_loss/cpu_pct) 외에 **임의의 명명 지표**(PLC 레지스터 등)를 저장하기 위한 토대.
- `POST /api/metrics` — `{samples:[{ip|device_id|name, metric_name, value, unit?, ts?}]}`. **최신값**(`device_kv`) + **시계열**(`unified_metrics`, 24h TTL) 저장, `last_seen` 갱신. 네트워크 status는 건드리지 않음(ping/SNMP 담당 유지).
- `GET /api/devices/{id}/kv` — 장비의 최신 범용 지표 목록
- `GET /api/devices/{id}/series?metric=<name>&hours=24` — 명명 지표 시계열(차트용)

### 2.5 MongoDB 컬렉션
| 컬렉션 | 용도 |
|---|---|
| `devices` | 인벤토리 |
| `alerts` | 알람 |
| `device_metrics` | 네트워크 지표 시계열(24h TTL) |
| `links` | LLDP/CDP 이웃 링크 |
| `device_kv` | 범용 지표 최신값 |
| `unified_metrics` | 범용 지표 시계열(24h TTL) |

장비 삭제/`mock/reset` 시 관련 alerts, links, kv, metrics 함께 정리. 인덱스: TTL + 조회용 복합 인덱스 자동 생성.

### 2.6 전체 API 엔드포인트
```
GET    /api/                         헬스
GET    /api/devices                  목록
POST   /api/devices                  생성
GET    /api/devices/{id}             조회
PATCH  /api/devices/{id}             수정(식별 단계가 vendor/type 교정에 사용)
DELETE /api/devices/{id}             삭제(연관 데이터 cascade)
GET    /api/alerts
POST   /api/alerts/{id}/acknowledge
DELETE /api/alerts/{id}
POST   /api/alerts/bulk-acknowledge
GET    /api/topology                 노드+엣지(parent_id + links)
GET    /api/zones
GET    /api/dashboard/summary
POST   /api/mock/generate            목업 생성(데모)
POST   /api/mock/reset               전체 초기화
GET    /api/devices/{id}/metrics     네트워크 지표 히스토리
POST   /api/ingest [?auto_create]    네트워크 지표 수신(ping/SNMP)
GET    /api/sim/mode
POST   /api/sim/mode                 시뮬 토글
POST   /api/links                    이웃 링크 수신(LLDP/CDP)
GET    /api/links
POST   /api/links/reset
POST   /api/metrics                  범용 지표 수신(Modbus/OPC UA 등)
GET    /api/devices/{id}/kv          범용 지표 최신값
GET    /api/devices/{id}/series      범용 지표 시계열
WS     /api/ws                       실시간 스냅샷 푸시
```

---

## 3. Node-RED 수집기 플로우

VM에 Node-RED 설치(보안 로그인 설정, Projects 비활성). 각 플로우는 가져오기(Import) 후 배포. 모두 `127.0.0.1:8001`로 POST.

| 플로우 파일 | 탭 | 역할 | 실행 | 필요한 노드 |
|---|---|---|---|---|
| `netvision_collector_flow.json` | NetVision Collector | 등록 장비 **ping** → 상태/지연 → `/api/ingest` | 30초 자동 | `node-red-node-ping` |
| `netvision_discovery_flow.json` | NetVision Discovery | 서브넷 **fping 스윕** → 신규 IP `/api/devices` 등록(중복 제외) | 수동 버튼 | exec(`fping`) |
| `netvision_identify_flow.json` | NetVision Identify | `sysObjectID`/`sysDescr`로 **vendor, type 자동 분류** → PATCH | 수동 버튼 | `node-red-node-snmp` |
| `netvision_snmp_flow.json` | NetVision SNMP | switch의 **CPU** SNMP 폴링 → `/api/ingest` | 60초 자동 | `node-red-node-snmp` |
| `netvision_lldp_flow.json` | NetVision LLDP | **LLDP 이웃** walk(`lldpRemSysName`) → `/api/links` (스캐폴드) | 수동 버튼 | `node-red-node-snmp` |
| `netvision_modbus_flow.json` | NetVision Modbus | **Modbus 시뮬 서버 + 수집** → `/api/metrics` | 자동(5초) | `node-red-contrib-modbus` |

### 설치한 패키지
```bash
# Node-RED 본체(공식 스크립트) + 방화벽
sudo ufw allow 1880/tcp
# 팔렛트 노드
cd ~/.node-red
npm install node-red-node-ping node-red-node-snmp node-red-contrib-modbus
sudo systemctl restart nodered
# 디스커버리용
sudo apt-get install -y fping       # 필요 시: sudo setcap cap_net_raw+ep $(which fping)
# SNMP 무하드웨어 테스트용(VM 자체를 SNMP 장비로)
sudo apt-get install -y snmpd snmp
```

### "discover → identify → parse" 루프
디스커버리(인벤토리 채움) → SNMP 식별(vendor/type 자동 분류) → SNMP CPU/지표 파싱이 한 줄로 연결된다. 식별이 `device_type=switch`로 바꾼 장비를 SNMP CPU 플로우가 자동으로 폴링.

---

## 4. 핵심 기술 메모 / 트러블슈팅

| 항목 | 내용 |
|---|---|
| **WebSocket 프록시** | Nginx `/api/`에 `proxy_http_version 1.1` + `Upgrade`/`Connection` 헤더 없으면 실시간 갱신 안 됨. 이 앱은 폴링 폴백이 없어 더 중요. |
| **시뮬↔실데이터** | 실데이터로 전환: `.env`에 `SIMULATION_MODE=false` + restart + `POST /api/mock/reset`. 데모 보기: `POST /api/sim/mode {enabled:true}`(주의: `mock/generate`는 목업 20대를 다시 만듦). |
| **무하드웨어 테스트** | (1) ping: 항상 응답하는 IP(127.0.0.1, 게이트웨이, 8.8.8.8) 등록. (2) SNMP 식별/CPU: VM에 `snmpd` 설치(`rocommunity public`, `agentaddress udp:161`) → VM 자신을 SNMP 장비로. (3) Modbus: 플로우 내 Modbus 서버 노드가 시뮬레이터 역할. |
| **SNMP는 숫자 OID만** | `node-red-node-snmp`(net-snmp)는 MIB 파일을 로드하지 않음. 표준(퍼블릭) OID는 벤더 무관 동일 숫자라 그대로 사용, 벤더 전용 OID는 vendor별 프로파일(함수 내 맵)로 관리. |
| **SNMP 식별 매칭** | sysObjectID의 enterprise 번호 → vendor(Cisco 9 / Siemens 4329 / Moxa 8691 / Hirschmann 248 / Net-SNMP 8072). 폴백은 sysDescr 키워드. 새 벤더는 `ENT` 맵에 한 줄 추가. |
| **Modbus 바이트/워드** | `node-red-contrib-modbus` 서버 노드는 `value`를 **바이트**로 기록(`bufferFactor=8`). 16비트 레지스터를 쓰려면 **빅엔디안 2바이트로 분할**해서 기록해야 함(시뮬 값 생성 함수에 반영). |
| **매칭 키** | ingest/metrics/links 모두 `device_id → ip → name` 순으로 장비 매칭. Modbus는 대상 장비 IP(`DEVICE_IP`)로 매칭. |
| **join 타임아웃** | SNMP는 응답 실패가 잦아 batch join에 타임아웃(20초)을 둬 일부 실패해도 나머지 전송. |

---

## 5. 진행 상태 (로드맵 대비)

| 항목 | 상태 | 비고 |
|---|---|---|
| Ingestion API + 시뮬 토글 | ✅ | |
| ping 수집 | ✅ | 동작 확인 |
| 알람 자동 해소 | ✅ | 통지는 보류(실서비스 연동 때) |
| 디스커버리(fping) | ✅ | 로컬 서브넷 검증 완료 |
| SNMP 식별(sysObjectID) | ✅ | snmpd 자가 테스트로 검증 |
| SNMP CPU 수집 | ⚠️ 구조 완성 | 실스위치 OID 확정 필요 |
| 토폴로지 링크 엔진 | ✅ | 수동 링크로 검증 |
| LLDP 수집 | ⚠️ 스캐폴드 | 실스위치 LLDP 출력으로 파싱/매칭 확정 필요 |
| 범용 지표(UnifiedMetric) | ✅ | |
| Modbus 수집(+시뮬) | ✅ | 시뮬로 전 구간 검증 |
| 통지(Slack/메일/Telegram) | ⏸ 보류 | 순수 Node-RED 폴링 방식으로 설계만 합의 |
| OPC UA 어댑터 | ⏳ 미착수 | 로드맵 Phase 4 |
| 토폴로지/PLC 지표 **화면 표시** | ⏳ 미착수 | 프론트 작업(데이터는 준비됨) |

**하드웨어 필요(추후 실장비로 확정):** SNMP CPU OID(모델별), LLDP 이웃 파싱/매칭, OPC UA/Modbus 실 PLC, 실스위치 다수 연결 시 토폴로지.

---

## 6. 검증용 명령 모음 (VM)

```bash
# 백엔드 상태/엔드포인트 반영 확인
systemctl is-active netvision-backend
curl -s http://127.0.0.1:8001/api/sim/mode; echo
curl -s -X POST http://127.0.0.1:8001/api/metrics -H 'Content-Type: application/json' -d '{"samples":[]}'; echo

# 장비 목록(이름/IP/타입)
curl -s http://127.0.0.1:8001/api/devices | python3 -c "import sys,json;d=json.load(sys.stdin);[print(x['name'],x['ip'],x['device_type']) for x in d]"

# 특정 장비(IP로) 범용 지표 최신값
DID=$(curl -s http://127.0.0.1:8001/api/devices | python3 -c "import sys,json;d=json.load(sys.stdin);print(next(x['id'] for x in d if x['ip']=='192.168.108.129'))")
curl -s http://127.0.0.1:8001/api/devices/$DID/kv; echo

# 토폴로지 링크 수동 테스트
curl -s -X POST http://127.0.0.1:8001/api/links -H 'Content-Type: application/json' \
  -d '{"links":[{"source_ip":"192.168.108.2","neighbor_ip":"192.168.108.129","local_port":"Gi0/1","remote_port":"eth0"}]}'; echo
```

---

## 7. 백로그 / 다음 단계 후보

- **PLC/네트워크 지표 화면 표시**(프론트): `/api/devices/{id}/kv`, `/series`를 장비 상세에 그래프로. (데이터는 준비됨)
- **OPC UA 어댑터**(Phase 4): `node-red-contrib-opcua` → `/api/metrics`.
- **SNMP CPU/트래픽 OID 확정**(실스위치 `snmpwalk`) 및 인터페이스 트래픽 추가.
- **LLDP 파싱/매칭 확정**(실스위치) + CDP(`cdpCacheTable`) 추가.
- **알람 통지**: Node-RED가 `/api/alerts` 폴링 → 신규 미확인 알람만 채널 발송.
- **인벤토리 정돈**: 잔여 목업(SW-/PLC-/SNS- 10.20.x.x) 정리. (`mock/reset`은 disc 장비까지 지우니 주의 → 정리 후 디스커버리 재실행)
- **보안**: `/api/ingest`, `/api/metrics`, `/api/links` 무인증 → 외부 노출 시 토큰 헤더 검증 추가.
