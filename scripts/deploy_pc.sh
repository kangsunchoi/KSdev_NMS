#!/usr/bin/env bash
# NetVision OT — 테스트 PC 배포 스크립트 (Ubuntu 22.04/24.04, 재실행 안전)
#
#   bash scripts/deploy_pc.sh            # 설치 또는 최신 main으로 업데이트
#
# 하는 일
#   1. 저장소를 ~/dev/KSdev_NMS 에 받거나 최신화 (main)
#   2. 백엔드: Python venv + requirements 설치, backend/.env 없으면 데모 모드로 생성
#   3. 프론트: Node 20 + yarn으로 빌드 (백엔드 주소 = 이 PC IP:8001)
#   4. systemd --user 서비스 2개 등록/재시작: netvision-backend(:8001), netvision-frontend(:3000)
#   5. 상태 확인 출력
# 하지 않는 일
#   - MongoDB 설치/설정 변경/데이터 삭제 (이미 설치된 MongoDB를 그대로 사용)
#   - 방화벽 변경, 운영 VM 접속
set -euo pipefail

REPO_URL="https://github.com/kangsunchoi/KSdev_NMS.git"
APP_DIR="${APP_DIR:-$HOME/dev/KSdev_NMS}"
BACKEND_PORT=8001
FRONTEND_PORT=3000
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"; HOST_IP="${HOST_IP:-127.0.0.1}"

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m[중단] %s\033[0m\n' "$*" >&2; exit 1; }

say "0. 사전 확인"
command -v git >/dev/null || die "git 없음: sudo apt install -y git"
command -v python3 >/dev/null || die "python3 없음"
python3 -c 'import venv' 2>/dev/null || die "python3-venv 없음: sudo apt install -y python3-venv"
if systemctl is-active --quiet mongod 2>/dev/null || (command -v mongosh >/dev/null && mongosh --quiet --eval 'db.runCommand({ping:1}).ok' >/dev/null 2>&1); then
  echo "MongoDB: 실행 중"
else
  die "MongoDB가 실행 중이 아님 (sudo systemctl start mongod 후 재실행)"
fi

say "1. 저장소 ($APP_DIR)"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch -q origin main && git -C "$APP_DIR" checkout -q main && git -C "$APP_DIR" pull -q --ff-only origin main
else
  mkdir -p "$(dirname "$APP_DIR")" && git clone -q "$REPO_URL" "$APP_DIR"
fi
git -C "$APP_DIR" log --oneline -1

say "2. 백엔드"
cd "$APP_DIR/backend"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
if [ ! -f .env ]; then
  cat > .env <<ENV
MONGO_URL="mongodb://localhost:27017"
DB_NAME="netvision"
CORS_ORIGINS="*"
SIMULATION_MODE=true
AUTH_ENABLED=false
ENV
  echo ".env 생성 (데모 모드). 실데이터는 SIMULATION_MODE=false로 바꾼 뒤 재실행"
else
  echo ".env 유지 (기존 설정 사용)"
fi

say "3. 프론트엔드 빌드"
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 18 ]; then
  export NVM_DIR="$HOME/.nvm"
  [ -s "$NVM_DIR/nvm.sh" ] || curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  # shellcheck disable=SC1091
  . "$NVM_DIR/nvm.sh" && nvm install 20 >/dev/null && nvm use 20 >/dev/null
fi
NODE_BIN="$(dirname "$(command -v node)")"
cd "$APP_DIR/frontend"
corepack enable --install-directory "$NODE_BIN" 2>/dev/null || corepack enable || true
yarn install --frozen-lockfile --network-timeout 600000 >/dev/null
CI=false REACT_APP_BACKEND_URL="http://$HOST_IP:$BACKEND_PORT" yarn build >/dev/null
echo "빌드 완료: 백엔드 주소 http://$HOST_IP:$BACKEND_PORT"

say "4. 서비스 등록 (systemd --user)"
UNIT_DIR="$HOME/.config/systemd/user"; mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/netvision-backend.service" <<UNIT
[Unit]
Description=NetVision OT backend
After=network-online.target

[Service]
WorkingDirectory=$APP_DIR/backend
ExecStart=$APP_DIR/backend/.venv/bin/uvicorn server:app --host 0.0.0.0 --port $BACKEND_PORT
Restart=on-failure

[Install]
WantedBy=default.target
UNIT
cat > "$UNIT_DIR/netvision-frontend.service" <<UNIT
[Unit]
Description=NetVision OT dashboard (static build)

[Service]
WorkingDirectory=$APP_DIR/frontend
Environment=PATH=$NODE_BIN:/usr/bin:/bin
ExecStart=$NODE_BIN/npx --yes serve@14 -s build -l $FRONTEND_PORT
Restart=on-failure

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now netvision-backend netvision-frontend >/dev/null 2>&1 || true
systemctl --user restart netvision-backend netvision-frontend
if ! loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q yes; then
  echo "참고: 로그아웃/재부팅 후에도 자동 실행하려면 1회 실행 → sudo loginctl enable-linger $USER"
fi

say "5. 상태 확인"
for i in $(seq 1 30); do curl -fs "http://127.0.0.1:$BACKEND_PORT/api/" >/dev/null && break; sleep 1; done
curl -fs "http://127.0.0.1:$BACKEND_PORT/api/" && echo
curl -fs "http://127.0.0.1:$BACKEND_PORT/api/dashboard/summary" | head -c 300 && echo
for i in $(seq 1 30); do curl -fs -o /dev/null "http://127.0.0.1:$FRONTEND_PORT/" && break; sleep 1; done
curl -fs -o /dev/null -w "대시보드 HTTP %{http_code}\n" "http://127.0.0.1:$FRONTEND_PORT/" || echo "대시보드 응답 없음"
systemctl --user --no-pager --lines=0 status netvision-backend netvision-frontend | grep -E "●|Active:"

say "완료: 대시보드 http://$HOST_IP:$FRONTEND_PORT  (백엔드 http://$HOST_IP:$BACKEND_PORT)"
