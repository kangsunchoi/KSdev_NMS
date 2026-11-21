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

## 운영 배포

현재 운영은 내부 VM(`192.168.108.129`, 대시보드 `:8080`). 절차는 [`docs/02_구성_배포_운영.md`](docs/02_구성_배포_운영.md).
