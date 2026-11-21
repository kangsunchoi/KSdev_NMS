# 06. 설계: MAC Observation 기반 비인가 자산 탐지

- 작성: 2026-09-15 ~ 09-16 설계 논의 정리
- 상태: 설계만 완료. 코드, 플로우 모두 구현 안 됨
- 목적: 산업망에 새로 붙은 미등록 단말을 찾아 위치(스위치/포트)와 함께 이슈로 올림

## 1. 조사 결론

1. 상용 제품 (Siemens SINEC NMS, Moxa MXview One, Cisco IND/IAD/Cyber Vision) 모두 결국 "스위치가 아는 정보 + 등록 자산 DB 대조" 구조. 정확도는 등록 자산 DB 품질에 수렴
2. Cisco IAD는 SNMP/YANG을 지원하지 않아 SSH CLI(`show iad inventory`) 파싱에 의존해야 함. 출력 형식 변경에 취약
3. 미관리 스위치 탐지를 공식 기능으로 내세운 건 Hirschmann HiVision(FDB 추론) 정도. 일반 문제는 NP-hard라 "미관리 스위치 발견"이라고 단정하지 않고 "Hidden L2 후보"까지만 표시
4. 탐지 수단 구분
   - 스위치가 이미 아는 정보 (부하 거의 없음, 우선 채택): link-up syslog, CAM/MAC 테이블, ARP, 미사용 포트 link-up, MAC flapping syslog
   - 강제형 (설정 변경 필요): Port Security sticky(OT에서는 `restrict`부터), 802.1X/MAB, DHCP snooping
   - 패시브 관측 (정확도 높음, 비용 발생): SPAN/TAP 분석, 브로드캐스트 청취, NetFlow/IPFIX
   - 능동 스캔 (OT에서 신중히): ARP/ICMP 스윕, nmap. 구형 PLC/HMI가 멈출 수 있어 유지보수 시간대 저속 ARP 스윕까지만
5. 식별 보조: OUI 벤더 조회(비용 0, 효용 큼), DHCP fingerprint, 호스트명/NetBIOS, 산업 프로토콜 응답, 포트 과거 이력
6. 미사용 포트 link-up은 해석 여지가 없고 구현이 가장 쉬워서 별도로 우선 검토할 가치가 있음
7. CAM 주기 폴링 부하 논의: 목적을 "실시간 추적"이 아니라 "syslog 누락 보정"으로 잡으면 주기를 길게(예: 1시간) 해도 됨. 상주 단말은 CAM에 계속 남기 때문. 못 잡는 조합은 "허브 뒤 + 순간 접속"뿐이고 화면에 한계로 명시

## 2. 설계 원칙

출발점은 아래 3원칙이고, 검토 후 보완점을 더했습니다.

| 원칙 | 평가 |
|---|---|
| CAM을 스위치별 스냅샷이 아니라 글로벌 MAC 기준으로 관리 | 채택. 없으면 MOVE 판정 불가 |
| Uplink/Trunk에서 보인 MAC과 Edge 포트에서 보인 MAC 구분 | 채택. 단 버리는 필터가 아니라 분류기로 |
| 다중 MAC을 미관리 스위치로 단정하지 않고 Hidden L2 후보까지만 | 채택 |
| syslog + 주기 스윕 이중 트리거 | 채택. 서로의 사각지대 보완 |

보완한 점:

1. UNLOCATED 버킷: 모든 스위치의 uplink에서만 보이고 어느 edge 포트에도 없는 MAC이 관리 밖 구간 단말. 버리지 않고 별도 상태로 보관 (Hidden L2 후보의 입력)
2. AGED 상태: CAM aging(기본 300초)으로 사라진 것과 떠난 것은 다름. 소멸은 이벤트로 만들지 않음
3. FLAP 상태: 같은 사이클에 서로 다른 edge 포트 두 곳 이상에서 보이면 스푸핑 가능성
4. PRP/HSR 쌍 정규화: LAN_A/LAN_B 양쪽에서 같은 MAC이 보이는 건 정상. peer_group으로 묶어 1건 처리. 안 하면 PRP 단말이 매 사이클 FLAP
5. 자산 DB 워크플로: 베이스라인 일괄 등록, 예외 만료일 강제가 없으면 운영 불가

핵심 결정 4가지:

1. 1급 키는 `(MAC, VLAN)`
2. `mac_observations`는 append-only 원본, 나머지는 전부 재계산 가능한 파생
3. 포트 역할은 SNMP가 아니라 running-config에서 판정, 하루 1회 별도 수집
4. 출현만 이벤트, 소멸은 `last_seen` 갱신만

## 3. 파이프라인

```
syslog(link-up) --+
                  +--> CAM 수집 --> mac_observations (불변, append-only)
주기 스윕(30분) --+                        |
                                           v
                                   peer_group 병합 (PRP/HSR 쌍 -> 1건)
                                           |
                                           v
                                   포트 역할 분류 (port_roles 조회)
                    +----------------------+----------------------+
                    v                      v                      v
              edge 관측 있음          uplink/ring만             판정 불가
                    |                      |                      |
                 LOCATED               UNLOCATED          unknown (edge로 취급 + 플래그)
                    +----------+-----------+
                               v
                        mac_current 갱신
                               v
                    전이 계산 -> mac_events
           NEW / MOVE / FLAP / RELOCATED / REAPPEAR / UNLOCATED_APPEAR
                               v
              억제 규칙 (학습기간 / 중복 / 작업창 / 랜덤 MAC)
                               v
                     asset_registry 대조
                               v
                            issues

[별도 배치] last_seen 30일 초과 -> state = AGED (이벤트 아님)
[별도 수집] running-config -> port_roles (1일 1회)
```

## 4. MongoDB 컬렉션

### 4.1 `mac_observations` (원본, 불변)

```jsonc
{
  "_id": ObjectId,
  "run_id": "2026-09-16T10:00:00Z-periodic",
  "mac": "00:11:22:33:44:55",      // 소문자 콜론 표기로 정규화
  "vlan": 100,
  "switch_id": "dev_abc123",
  "switch_ip": "192.168.1.10",
  "if_name": "GigabitEthernet1/0/5",
  "bridge_port": 5,
  "port_role": "edge",              // 수집 시점의 역할 스냅샷 (판정 근거 보존)
  "peer_group": null,               // PRP/HSR 쌍이면 "prp1"
  "source": "periodic",             // periodic | syslog | iad | ipdt
  "ts": ISODate("2026-09-16T10:00:12Z")
}
```

### 4.2 `mac_current` (최신 상태, 파생)

```jsonc
{
  "_id": "00:11:22:33:44:55|100",
  "mac": "00:11:22:33:44:55",
  "vlan": 100,
  "state": "LOCATED",               // LOCATED | UNLOCATED | AGED
  "location": {
    "switch_id": "dev_abc123",
    "switch_ip": "192.168.1.10",
    "if_name": "GigabitEthernet1/0/5",
    "port_role": "edge"
  },
  "seen_on": [                      // 이번 사이클 전체 관측점
    {"switch_id":"dev_abc123","if_name":"Gi1/0/5","role":"edge","ts":ISODate},
    {"switch_id":"dev_core01","if_name":"Te1/1/1","role":"uplink","ts":ISODate}
  ],
  "first_seen": ISODate,
  "last_seen": ISODate,
  "obs_count": 142,
  "ip": "192.168.1.55",             // nullable
  "ip_source": "ipdt",              // ipdt | arp | dhcp | null
  "oui_vendor": "Siemens AG",
  "is_random_mac": false,
  "asset_status": "unregistered",   // registered | unregistered | exception | unauthorized
  "review_state": "NEW",            // NEW | REVIEWING | RESOLVED
  "last_event": "NEW",
  "flap_count_24h": 0
}
```

### 4.3 `mac_events` (전이 기록, 파생)

```jsonc
{
  "_id": ObjectId,
  "run_id": "...",
  "mac": "00:11:22:33:44:55",
  "vlan": 100,
  "event": "MOVE",                  // NEW | MOVE | FLAP | RELOCATED | REAPPEAR | UNLOCATED_APPEAR
  "from": {"switch_id":"dev_abc","if_name":"Gi1/0/5"},
  "to":   {"switch_id":"dev_xyz","if_name":"Gi1/0/9"},
  "evidence": [ObjectId, ObjectId], // mac_observations 참조
  "severity": "warning",            // info | warning | critical
  "suppressed": false,
  "suppress_reason": null,          // learning_window | duplicate | maintenance | random_mac
  "ts": ISODate
}
```

### 4.4 `port_roles` (기준 데이터)

```jsonc
{
  "_id": "dev_abc123|GigabitEthernet1/0/5",
  "switch_id": "dev_abc123",
  "if_name": "GigabitEthernet1/0/5",
  "bridge_port": 5,
  "role": "edge",                   // edge | uplink | ring | unused | unknown
  "reason": "access",               // 5절 판정표 참조
  "peer_group": null,
  "admin_status": "up",
  "updated_at": ISODate
}
```

### 4.5 `collector_runs` (수집 커버리지)

```jsonc
{
  "_id": "2026-09-16T10:00:00Z-periodic",
  "source": "periodic",
  "started_at": ISODate, "finished_at": ISODate,
  "targets": 32, "ok": 28, "failed": 4,
  "failures": [
    {"switch_ip":"192.168.1.22","reason":"snmp_timeout"},
    {"switch_ip":"192.168.1.31","reason":"pdu_too_big"}
  ]
}
```

- 이 컬렉션이 없으면 "신규 0건"이 수집 실패인지 정말 0건인지 구분이 안 됨. 화면 상단에 상시 노출

### 4.6 `asset_registry` (화이트리스트)

```jsonc
{
  "_id": "00:11:22:33:44:55",
  "mac": "00:11:22:33:44:55",
  "label": "MCC-1 라인 PLC",
  "owner": "생산1팀",
  "status": "registered",           // registered | exception | unauthorized
  "expires_at": null,               // exception이면 필수 (null 금지)
  "note": "",
  "registered_by": "<사용자>",
  "registered_at": ISODate
}
```

### 4.7 인덱스

```bash
# (VM)
mongosh netvision --eval '
db.mac_observations.createIndex({mac:1, ts:-1});
db.mac_observations.createIndex({run_id:1});
db.mac_observations.createIndex({switch_id:1, if_name:1, ts:-1});
db.mac_observations.createIndex({ts:1}, {expireAfterSeconds: 7776000});
db.mac_current.createIndex({state:1, asset_status:1});
db.mac_current.createIndex({last_seen:-1});
db.mac_current.createIndex({"location.switch_id":1, "location.if_name":1});
db.mac_current.createIndex({mac:1});
db.mac_events.createIndex({ts:-1});
db.mac_events.createIndex({mac:1, ts:-1});
db.mac_events.createIndex({event:1, suppressed:1, ts:-1});
db.port_roles.createIndex({switch_id:1, if_name:1}, {unique:true});
db.collector_runs.createIndex({finished_at:-1});
'
```

- `mac_observations`만 90일 TTL. `mac_current`, `asset_registry`는 영구

## 5. 포트 역할 판정표

위에서부터 평가하고 처음 맞는 규칙에서 멈춥니다.

| # | 조건 | role | reason | 수집원 |
|---|---|---|---|---|
| 1 | shutdown 상태 | unused | `shutdown` | SNMP `ifAdminStatus` |
| 2 | `switchport mode trunk` | uplink | `trunk` | config |
| 3 | LLDP/CDP 이웃이 관리 대상 스위치 | uplink | `lldp_neighbor` | SNMP LLDP-MIB |
| 4 | `channel-group` 멤버 | uplink | `portchannel` | config |
| 5 | `prp-channel-group` 멤버 | ring | `prp` | config |
| 6 | HSR-ring 멤버 포트 | ring | `hsr` | config |
| 7 | `rep segment` 설정 | ring | `rep` | config |
| 8 | `mrp ring` 설정 | ring | `mrp` | config |
| 9 | `switchport mode access` | edge | `access` | config |
| 10 | 위 어디에도 미해당 | unknown | `undetermined` | - |

- 2번과 4~9번은 running-config에서만 나옴. SNMP로는 트렁크 여부도 벤더 MIB가 필요하고 PRP/HSR은 표준 MIB가 없음
- 포트 역할은 거의 안 바뀌므로 하루 1회 수집. CAM 수집(30분)과 주기 분리

PRP/HSR 쌍 정규화 예:

```
prp-channel 1
 +- GigabitEthernet1/3 (LAN_A) -> peer_group: "dev_abc123|prp1"
 +- GigabitEthernet1/4 (LAN_B) -> peer_group: "dev_abc123|prp1"
```

규칙: 같은 `peer_group`에서 나온 같은 MAC 관측은 1건으로 취급

## 6. 전이 계산 로직

```python
def derive_events(mac, vlan, obs_this_run, prev):
    # 1) PRP/HSR 쌍 병합
    obs = merge_peer_groups(obs_this_run)

    edges   = [o for o in obs if o.port_role in ("edge", "unknown")]
    uplinks = [o for o in obs if o.port_role in ("uplink", "ring")]

    # 2) 같은 사이클에 서로 다른 edge 포트 -> FLAP
    distinct_edges = unique_by(edges, key=lambda o: (o.switch_id, o.if_name))
    if len(distinct_edges) >= 2:
        return Event("FLAP", to=distinct_edges, severity="critical"), State.LOCATED

    # 3) edge 1곳 -> 위치 확정
    if len(distinct_edges) == 1:
        loc = distinct_edges[0]
        if prev is None:
            return Event("NEW", to=loc, severity="warning"), State.LOCATED
        if prev.state == "AGED":
            return Event("REAPPEAR", to=loc, severity="info"), State.LOCATED
        if prev.location != loc:
            return Event("MOVE", frm=prev.location, to=loc, severity="info"), State.LOCATED
        return None, State.LOCATED          # 변화 없음, last_seen만 갱신

    # 4) uplink/ring에서만 관측 -> 위치 미상
    if len(uplinks) >= 1:
        if prev is None:
            return Event("UNLOCATED_APPEAR", severity="warning"), State.UNLOCATED
        if prev.state == "LOCATED":
            return Event("RELOCATED", frm=prev.location, severity="warning"), State.UNLOCATED
        return None, State.UNLOCATED

    # 5) 이번 사이클 미관측 -> 아무것도 안 함 (소멸은 이벤트가 아님)
    return None, prev.state
```

AGED 배치 (1일 1회, 이벤트 없음. 재출현 시 NEW가 아니라 REAPPEAR):

```python
db.mac_current.update_many(
    {"last_seen": {"$lt": now - 30days}, "state": {"$ne": "AGED"}},
    {"$set": {"state": "AGED"}}
)
```

이벤트 심각도:

| 이벤트 | 심각도 | 근거 |
|---|---|---|
| FLAP | critical | 스푸핑 가능성. 등록 MAC도 예외 아님 |
| NEW + 미등록 | warning | 신규 미등록 단말 |
| RELOCATED | warning | 관리 구간 밖으로 이동 |
| UNLOCATED_APPEAR | warning | 위치 미상 단말 출현 |
| MOVE | info | 정상 이설 가능성 높음 |
| REAPPEAR | info | 복귀 |

## 7. 억제 규칙

`mac_events`는 항상 기록하고 `issues` 발행만 억제합니다.

```python
SUPPRESS_RULES = [
    ("learning_window", lambda e: now < baseline_end),           # 도입 후 14일
    ("duplicate",       lambda e: has_open_issue(e.mac)),
    ("maintenance",     lambda e: in_maintenance_window(now)),
    ("random_mac",      lambda e: is_locally_administered(e.mac)
                                  and e.event in ("NEW", "REAPPEAR")),
]

def is_locally_administered(mac):
    first_octet = int(mac.split(":")[0], 16)
    return bool(first_octet & 0b10)   # 두 번째 비트 1 -> x2/x6/xA/xE
```

- 랜덤 MAC(Windows 11, iOS, Android 기본 동작)은 억제하되 목록에는 남김

## 8. API (기존 `/api` 규칙 따름)

### 8.1 수집 입구

```
POST /api/cam                수집기 -> CAM 관측 적재
POST /api/port-roles         config 수집기 -> 포트 역할 갱신
POST /api/collector-runs     수집 사이클 결과 보고
```

`POST /api/cam` 요청과 응답:

```json
{
  "run_id": "2026-09-16T10:00:00Z-periodic",
  "source": "periodic",
  "switch_ip": "192.168.1.10",
  "entries": [
    {"mac": "0011.2233.4455", "vlan": 100, "bridge_port": 5},
    {"mac": "0011.2233.4456", "vlan": 100, "if_name": "GigabitEthernet1/0/6"}
  ]
}
```

```json
{
  "accepted": 48,
  "unresolved_ports": 2,
  "events": {"NEW": 1, "MOVE": 0, "FLAP": 0, "UNLOCATED_APPEAR": 3},
  "suppressed": 1
}
```

- `bridge_port`와 `if_name` 중 하나만 있으면 됨. 백엔드가 `port_roles`로 변환

`POST /api/port-roles`:

```json
{
  "switch_ip": "192.168.1.10",
  "ports": [
    {"if_name":"GigabitEthernet1/1","bridge_port":1,"role":"uplink","reason":"trunk"},
    {"if_name":"GigabitEthernet1/3","bridge_port":3,"role":"ring","reason":"prp","peer_group":"prp1"},
    {"if_name":"GigabitEthernet1/4","bridge_port":4,"role":"ring","reason":"prp","peer_group":"prp1"},
    {"if_name":"GigabitEthernet1/5","bridge_port":5,"role":"edge","reason":"access"},
    {"if_name":"GigabitEthernet1/6","bridge_port":6,"role":"unused","reason":"shutdown"}
  ]
}
```

### 8.2 조회

```
GET /api/macs?state=LOCATED&asset_status=unregistered&limit=100
GET /api/macs/{mac}                          상세 + 최근 관측 이력
GET /api/mac-events?event=FLAP&hours=24
GET /api/unlocated                           Hidden L2 후보 분석용
GET /api/coverage                            수집 커버리지 (화면 상단 배너)
GET /api/ports/{switch_id}/{if_name}/macs    포트별 MAC 목록
```

`GET /api/unlocated`의 후보 포트 항목에는 "이 포트 하단에 다중 단말 존재 가능. Unmanaged Switch 확정 아님" 문구를 코드에 고정. 화면에서 "Unmanaged Switch 발견"으로 표현하지 않음.

### 8.3 워크플로

```
POST  /api/assets/bulk          베이스라인 일괄 승격 (dry_run 먼저)
PATCH /api/macs/{mac}/review    상태 전이
POST  /api/baseline/close       학습 기간 종료 -> 이슈 발행 시작
```

```json
{
  "filter": {"state": "LOCATED", "first_seen_before": "2026-09-30T00:00:00Z"},
  "status": "registered",
  "owner": "생산1팀",
  "note": "2026-09 베이스라인 일괄 등록",
  "dry_run": true
}
```

```json
{"asset_status": "exception", "expires_at": "2026-12-31T00:00:00Z", "note": "협력사 계측기"}
```

- `exception`인데 `expires_at`이 없으면 400 반환으로 강제

## 9. 수집기 (Node-RED)

### 9.1 SNMP OID

```
dot1qTpFdbPort        1.3.6.1.2.1.17.7.1.2.2.1.2   주 수집 대상
dot1dBasePortIfIndex  1.3.6.1.2.1.17.1.4.1.2       bridge_port -> ifIndex
ifName                1.3.6.1.2.1.31.1.1.1.1       ifIndex -> 인터페이스명
ifAdminStatus         1.3.6.1.2.1.2.2.1.7          shutdown 판정
```

`dot1qTpFdbPort`는 OID 인덱스가 VLAN + MAC(6옥텟 10진), 값이 bridge port 번호:

```
1.3.6.1.2.1.17.7.1.2.2.1.2 . 100 . 0.17.34.51.68.85 = 5
```

```javascript
// Node-RED function 노드
function parseFdbOid(oid, value) {
  const base = "1.3.6.1.2.1.17.7.1.2.2.1.2.";
  const idx  = oid.substring(base.length).split(".").map(Number);
  const vlan = idx[0];
  const mac  = idx.slice(1, 7)
                  .map(b => b.toString(16).padStart(2, "0"))
                  .join(":");
  return { mac, vlan, bridge_port: Number(value) };
}
```

### 9.2 플로우 구성

| 플로우 | 주기 | 역할 | POST 대상 |
|---|---|---|---|
| `netvision_cam_flow.json` | 30분 | dot1qTpFdbPort walk | `/api/cam` |
| `netvision_cam_targeted.json` | syslog 트리거 | 해당 스위치만 즉시 walk | `/api/cam` |
| `netvision_portrole_flow.json` | 1일 1회 | SSH → running-config 파싱 | `/api/port-roles` |
| `netvision_ipdt_flow.json` | 1시간 | `show device-tracking database` | `/api/cam` (source=ipdt) |

- IPDT를 ARP보다 우선. IP/MAC/포트/VLAN을 한 번에 주고 게이트웨이 접근도 필요 없음
- FDB는 크기가 커서 `tooBig` PDU 에러가 날 수 있음. `max-repetitions` 10~25, 실패 시 VLAN 단위로 쪼개 재시도, 실패는 `collector_runs.failures`에 기록

## 10. 단계별 적용

| Phase | 기간 | 범위 | 판단 기준 |
|---|---|---|---|
| 1 | 2주 | CAM 수집 + mac_observations/current만, 화면 없음 | UNLOCATED 비율 |
| 2 | 1주 | port_roles 수집 + 분류 적용 | FLAP 건수가 0에 수렴하는가 (PRP 정규화 검증) |
| 3 | 2주 | 베이스라인 관측 → `/api/assets/bulk` 승격 | 등록 후 신규 발생률 안정 |
| 4 | - | issues 발행 시작 | - |

- Phase 2의 FLAP 건수가 핵심 지표. 0에 수렴하기 전에는 Phase 3으로 넘어가지 않음

## 11. 실장비 검증 항목

| 항목 | 이유 |
|---|---|
| PRP-channel 멤버 포트의 CAM 표기 | 채널 단위로 나오면 peer_group 병합 불필요, 물리 포트 단위면 필수 |
| HSR-ring 포트의 FDB 동작 | 링 전체 MAC이 보이는지, 링 포트를 ring으로만 빼면 되는지 |
| IE3100/3300의 `dot1qTpFdbTable` 응답 | 미지원이거나 PDU 크기 제한이 있는 모델 존재 가능 |
| link-up syslog 메시지 형식 | targeted 트리거 파싱 규칙 확정 |
| `show device-tracking database` 가용성 | 되면 ARP 조인이 필요 없어 설계가 단순해짐 |
| VLAN 조회 방식 | 구형 IOS는 community indexing(`public@10`), IOS-XE는 직접 조회 |
| CAM aging과 syslog 발생 조건 | 상주 단말의 CAM 갱신 동작은 표준 기준 추론이라 현장 확인 필요 |

대상 스위치에서:

```
terminal length 0
show mac address-table
show device-tracking database
show interfaces status
show etherchannel summary
show prp channel detail
show running-config | include ^interface|switchport mode|channel-group|prp-channel|rep segment|mrp ring|shutdown
```

관리 PC에서:

```bash
snmpbulkwalk -v2c -c <community> -Cr10 <스위치IP> 1.3.6.1.2.1.17.7.1.2.2.1.2 | head -20
snmpwalk -v2c -c <community> <스위치IP> 1.3.6.1.2.1.17.1.4.1.2 | head -20
```

- 첫 명령이 `tooBig`이나 타임아웃이면 `-Cr` 값을 5까지 낮춤

## 12. 기존 코드와의 관계

- 현재 `/api/fdb` + 미관리 세그먼트(포트당 MAC 2개 이상 + LLDP 이웃 없음)는 이 설계의 단순판
- 구현 시 `device_fdb`를 `mac_observations`/`mac_current`로 대체하고, 토폴로지의 세그먼트 계산은 `UNLOCATED` + 후보 포트 데이터로 바꾸는 방향이 자연스러움 (결정 필요)
