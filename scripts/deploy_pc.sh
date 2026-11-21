#!/usr/bin/env bash
# NetVision OT — 테스트 PC 배포 스크립트 (Ubuntu 22.04/24.04, 재실행 안전)
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/kangsunchoi/KSdev_NMS/main/scripts/deploy_pc.sh)
#
# 하는 일
#   1. 저장소를 ~/dev/KSdev_NMS 에 받거나 최신화 (main)
#   2. 백엔드: Python venv + requirements, backend/.env 없으면 데모 모드로 생성 (DB: netvision_pc)
#   3. 프론트: nvm Node 20 + yarn으로 빌드 (백엔드 주소 = 이 PC IP:8001)
#   4. systemd --user 서비스 2개: netvision-backend(:8001), netvision-frontend(:3000)
#   5. 상태 확인 — 둘 다 응답해야 "완료", 아니면 로그 안내 후 exit 1
# 하지 않는 일
#   - MongoDB 설치/설정 변경 (기존 MongoDB에 netvision_pc DB만 사용), 방화벽, 운영 VM, sudo
# 쓰는 위치: ~/dev/KSdev_NMS, ~/.config/systemd/user, ~/.nvm (+ npm/pip/yarn 캐시)
# 환경변수로 덮어쓰기: APP_DIR, HOST_IP, DB_NAME
set -euo pipefail

main() {
  local REPO_URL="https://github.com/kangsunchoi/KSdev_NMS.git"
  local APP_DIR="${APP_DIR:-$HOME/dev/KSdev_NMS}"
  local BACKEND_PORT=8001 FRONTEND_PORT=3000
  local DB_NAME="${DB_NAME:-netvision_pc}"
  local ME="${USER:-$(id -un)}"
  export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

  say "0. 사전 확인"
  [ "$(id -u)" -ne 0 ] || die "root로 실행하지 마세요. sudo 없이 일반 사용자로 실행합니다."
  command -v git >/dev/null || die "git 없음: sudo apt install -y git"
  command -v curl >/dev/null || die "curl 없음: sudo apt install -y curl"
  command -v python3 >/dev/null || die "python3 없음"
  python3 -c 'import venv, ensurepip' 2>/dev/null || die "python3-venv 없음: sudo apt install -y python3-venv"
  systemctl --user show-environment >/dev/null 2>&1 \
    || die "사용자 systemd 세션 없음: 데스크톱 터미널 또는 SSH로 이 사용자에 직접 로그인해서 실행하세요."
  if systemctl is-active --quiet mongod 2>/dev/null \
     || timeout 2 bash -c '</dev/tcp/127.0.0.1/27017' 2>/dev/null; then
    echo "MongoDB: 127.0.0.1:27017 응답"
  else
    die "MongoDB가 실행 중이 아님 (sudo systemctl start mongod 후 재실행)"
  fi
  local HOST_IP="${HOST_IP:-}"
  if [ -z "$HOST_IP" ]; then
    HOST_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="src"){print $(i+1); exit}}' || true)"
  fi
  HOST_IP="${HOST_IP:-127.0.0.1}"
  echo "이 PC 주소: $HOST_IP (다르면 HOST_IP=x.x.x.x 를 앞에 붙여 재실행)"

  say "1. 저장소 ($APP_DIR)"
  if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch -q origin main
    git -C "$APP_DIR" checkout -q main
    git -C "$APP_DIR" pull -q --ff-only origin main
  else
    mkdir -p "$(dirname "$APP_DIR")"
    git clone -q "$REPO_URL" "$APP_DIR"
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
DB_NAME="$DB_NAME"
CORS_ORIGINS="*"
SIMULATION_MODE=true
AUTH_ENABLED=false
ENV
    echo ".env 생성: 데모 모드, DB=$DB_NAME (실데이터는 SIMULATION_MODE=false 후 재실행)"
  else
    echo ".env 유지 (기존 설정 사용)"
  fi

  say "3. 프론트엔드 빌드 (nvm Node 20)"
  export NVM_DIR="$HOME/.nvm"
  if [ ! -s "$NVM_DIR/nvm.sh" ]; then
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | PROFILE=/dev/null bash >/dev/null
  fi
  set +u  # nvm.sh is not nounset-safe
  # shellcheck disable=SC1091
  . "$NVM_DIR/nvm.sh"
  nvm install 20 >/dev/null
  nvm use 20 >/dev/null
  set -u
  local NODE_BIN; NODE_BIN="$(dirname "$(nvm which 20)")"
  export PATH="$NODE_BIN:$PATH"
  corepack enable --install-directory "$NODE_BIN"
  command -v yarn >/dev/null || die "yarn 준비 실패 (corepack)"
  echo "node $(node -v), yarn $(yarn --version)"
  cd "$APP_DIR/frontend"
  yarn install --frozen-lockfile --network-timeout 600000 >/dev/null
  CI=false REACT_APP_BACKEND_URL="http://$HOST_IP:$BACKEND_PORT" yarn build >/dev/null
  echo "빌드 완료: 백엔드 주소 http://$HOST_IP:$BACKEND_PORT"
  # static server installed locally once, so the service starts without network
  npm install -s --prefix "$APP_DIR/.tools" serve@14 >/dev/null
  local SERVE_JS="$APP_DIR/.tools/node_modules/serve/build/main.js"
  [ -f "$SERVE_JS" ] || die "serve 설치 실패"

  say "4. 서비스 등록 (systemd --user)"
  local UNIT_DIR="$HOME/.config/systemd/user"
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/netvision-backend.service" <<UNIT
[Unit]
Description=NetVision OT backend

[Service]
WorkingDirectory=$APP_DIR/backend
ExecStart=$APP_DIR/backend/.venv/bin/uvicorn server:app --host 0.0.0.0 --port $BACKEND_PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT
  cat > "$UNIT_DIR/netvision-frontend.service" <<UNIT
[Unit]
Description=NetVision OT dashboard (static build)

[Service]
WorkingDirectory=$APP_DIR/frontend
ExecStart=$NODE_BIN/node $SERVE_JS -s build -l $FRONTEND_PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT
  systemctl --user daemon-reload
  systemctl --user enable netvision-backend netvision-frontend >/dev/null 2>&1
  systemctl --user restart netvision-backend netvision-frontend
  if ! loginctl show-user "$ME" -p Linger 2>/dev/null | grep -q yes; then
    echo "참고: 로그아웃/재부팅 후에도 자동 실행하려면 1회 → sudo loginctl enable-linger $ME"
  fi

  say "5. 상태 확인"
  local ok=1 _
  for _ in $(seq 1 30); do curl -fs "http://127.0.0.1:$BACKEND_PORT/api/" >/dev/null && break; sleep 1; done
  if curl -fs "http://127.0.0.1:$BACKEND_PORT/api/"; then
    echo
    curl -fs "http://127.0.0.1:$BACKEND_PORT/api/dashboard/summary" | head -c 300 || true
    echo
  else
    echo "백엔드 응답 없음"; ok=0
  fi
  for _ in $(seq 1 30); do curl -fs -o /dev/null "http://127.0.0.1:$FRONTEND_PORT/" && break; sleep 1; done
  if curl -fs -o /dev/null "http://127.0.0.1:$FRONTEND_PORT/"; then
    echo "대시보드 응답 OK"
  else
    echo "대시보드 응답 없음"; ok=0
  fi
  systemctl --user --no-pager --lines=0 status netvision-backend netvision-frontend 2>/dev/null \
    | grep -E "●|Active:" || true

  if [ "$ok" -ne 1 ]; then
    echo
    echo "로그 확인: journalctl --user -u netvision-backend -n 30 --no-pager"
    echo "          journalctl --user -u netvision-frontend -n 30 --no-pager"
    die "배포는 됐지만 서비스가 응답하지 않습니다 (위 로그를 Claude에게 보내주세요)"
  fi
  say "완료: 대시보드 http://$HOST_IP:$FRONTEND_PORT  (백엔드 http://$HOST_IP:$BACKEND_PORT)"
}

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m[중단] %s\033[0m\n' "$*" >&2; exit 1; }

main "$@"
