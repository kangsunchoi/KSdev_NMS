# NetVision OT (NMS)

산업용(OT) 네트워크 관제 대시보드. 스위치·PLC·HMI·센서의 상태, 알람, 토폴로지, 인터페이스 트래픽을 보여 준다.

```
[장비] --ping/SNMP/Modbus--> [Node-RED :1880 수집기] --HTTP POST--> [백엔드 :8001] --WebSocket--> [대시보드]
```

| 구성 | 기술 |
|---|---|
| 백엔드 | Python FastAPI + Motor (MongoDB) — `backend/` |
| 프론트엔드 | React 19 + Tailwind + shadcn/ui + Cytoscape.js — `frontend/` |
| DB | MongoDB, DB 이름 `netvision` |
| 수집기 | Node-RED (플로우: `nodered/`, 준비 중) |

자세한 이력·운영·API 문서는 [`docs/`](docs/README.md)에 있다.

## 로컬 실행

사전 준비: Python 3.10+, Node.js 20 LTS, MongoDB 6+ (localhost:27017)

```bash
# 백엔드
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 아래 "필수 설정"을 채운다
uvicorn server:app --host 0.0.0.0 --port 8001
```

`backend/.env` 필수 설정:

```
MONGO_URL="mongodb://localhost:27017"
DB_NAME="netvision"
CORS_ORIGINS="*"
SIMULATION_MODE=true     # true: 목업 20대 데모, false: 실데이터(Node-RED 수집)
```

```bash
# 프론트엔드 (새 터미널)
cd frontend
corepack enable
yarn install
REACT_APP_BACKEND_URL=http://localhost:8001 yarn start   # http://localhost:3000
```

확인: `curl http://localhost:8001/api/` → `{"service":"NetVision OT","status":"ok"}`

## 테스트

DB 없이도 돈다(인메모리 MongoDB로 서버를 자동 기동).

```bash
cd backend
pip install -r requirements-dev.txt
ruff check .
pytest -q
```

실제 MongoDB로 돌리려면 `TEST_MONGO_URL=mongodb://localhost:27017 pytest -q`.
PR마다 GitHub Actions가 린트, 백엔드 테스트(실 MongoDB), 프론트 빌드를 자동 실행한다.

## 테스트 PC 배포 (한 줄)

MongoDB가 실행 중인 Ubuntu PC에서:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/kangsunchoi/KSdev_NMS/main/scripts/deploy_pc.sh)
```

- sudo 없이 일반 사용자로, 데스크톱 터미널 또는 SSH 직접 로그인 상태에서 실행한다.
- `~/dev/KSdev_NMS`에 설치하고 nvm Node 20으로 빌드한 뒤 `systemd --user` 서비스로 백엔드(:8001)·대시보드(:3000)를 띄운다. 재실행하면 최신 main으로 업데이트된다.
- MongoDB 설정은 건드리지 않고, 기본 DB 이름은 `netvision_pc`(기존 DB와 분리). `DB_NAME=…`, `HOST_IP=…`, `APP_DIR=…`를 앞에 붙여 바꿀 수 있다.
- 두 서비스가 응답할 때만 "완료"를 출력하고, 아니면 로그 확인 명령을 안내하며 실패로 끝난다.

## 운영 배포

현재 운영은 내부 VM(`192.168.108.129`, 대시보드 `:8080`). 절차는 [`docs/02_구성_배포_운영.md`](docs/02_구성_배포_운영.md).
