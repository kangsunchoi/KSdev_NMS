# NetVision OT 이관 자료 (docs)

NetVision OT(KSdev_NMS)를 만들면서 진행한 작업, 결정, 운영 절차, 트러블슈팅, 남은 작업을 한곳에 모은 문서 묶음입니다.

- 작성일: 2026-11-21
- 저장소: https://github.com/kangsunchoi/KSdev_NMS (public)
- 기준 코드: main 브랜치 마지막 커밋 `a6936ec` (2026-06-07)
- 출처
  1. Claude 프로젝트 문서 2종 (개발 가이드, 구현 기록)
  2. 프로젝트 대화 기록 (2026-06-03 ~ 2026-10-23, 8개 세션)
  3. 저장소 코드 직접 확인 (backend/server.py, auth.py, audit.py, notify.py, frontend/src)

## 파일 구성

| 파일 | 내용 |
|---|---|
| `README.md` | 이 문서. 전체 현황과 읽는 순서 |
| `01_작업이력.md` | 날짜별 작업 내역, 결정 사항, 결과 |
| `02_구성_배포_운영.md` | 서버/포트 구성, 배포 절차, Node-RED 수집기, 토글, 검증 명령 |
| `03_기능_API_데이터.md` | 화면, 기능별 구현 상태, 전체 API, MongoDB 컬렉션, 인증/RCA/통지 동작 |
| `04_트러블슈팅.md` | 실제로 겪은 문제와 원인, 해결 방법 |
| `05_남은작업.md` | 로드맵 대비 진행표, 바로 할 일, 실장비 필요 항목 |
| `06_설계_MAC_Observation.md` | 비인가 자산 탐지 설계 스펙 (설계만 완료, 구현 안 됨) |
| `원본_NetVision_OT_NMS_Development_Guide.md` | 초기 개발 가이드/로드맵 원문 (2026-06-03) |
| `원본_NetVision_OT_구현기록_pragmatic.md` | Pragmatic 경로 구현 기록 원문 (2026-06-05) |

처음 보는 경우 `README` → `01` → `05` 순서로 읽고, 작업할 때 `02`, `03`, `04`를 참조하면 됩니다.

## 현재 상태 요약 (2026-11-21 기준)

1. 앱 구성
   - React 19 + Tailwind + Cytoscape.js / FastAPI + Motor / MongoDB(`netvision`) / Node-RED 수집기
   - 내부 VM `192.168.108.129`에서 운영 (대시보드 `:8080`, 백엔드 `:8001`, Node-RED `:1880`)
2. 코드 (저장소 반영 완료)
   - 장비/알람/토폴로지/대시보드, 수집 API(ingest, metrics, interfaces, links, fdb, assets), 디스커버리 탭, 인터페이스 모니터링
   - 인증/RBAC/감사 로그, 알람 RCA 표시, Slack/Telegram 통지, 미관리 세그먼트, 논리 자산, 설정 화면, 한/영 전환
   - 신규 기능은 `.env` 토글로 기본 OFF
3. 저장소에 없는 것
   - Node-RED 플로우 전부 (VM의 `~/.node-red/flows.json`에만 있음). 백업이 최우선 할 일
4. 설계만 있는 것
   - MAC Observation 기반 비인가 자산 탐지 (`06_설계_MAC_Observation.md`)
5. 실장비가 있어야 끝나는 것
   - LLDP/CDP 실파싱, SNMP CPU OID, 전원/SFP, 링 모니터링, Config 백업, 실 PLC 수집

## 표기 규칙

- 상태: `완료` / `부분` / `스캐폴드`(구조만 있고 실데이터 검증 전) / `미착수` / `보류`
- 검증: `[확인]` 대화 기록이나 코드에서 확인됨 / `[미확인]` 기록 없음, VM에서 직접 확인 필요

## 보안 메모

저장소가 public이라 이 문서에는 비밀번호, 토큰, 웹훅 URL, 공인 IP, 고객사명, 개인 이름을 넣지 않았습니다. 내부 사설 IP(192.168.x.x)는 운영 정보라 남겼습니다. 실제 값은 VM의 `backend/.env`와 Node-RED 자격증명 파일에만 둡니다.
