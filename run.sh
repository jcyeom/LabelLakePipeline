#!/usr/bin/env bash
#
# LLP — 종합 실행 스크립트 (backend + frontend)
# 백엔드(uvicorn :8000)와 프론트엔드(vite :5173)를 함께 띄우고,
# Ctrl-C 한 번으로 두 프로세스를 모두 종료한다.
#
# 사용법:
#   ./run.sh             # 백엔드 + 프론트엔드 동시 실행
#   ./run.sh backend     # 백엔드만 (uvicorn --reload)
#   ./run.sh frontend    # 프론트엔드만 (vite dev)
#   ./run.sh test        # 백엔드 pytest 실행
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-all}"
BACKEND_HOST="${LLP_HOST:-127.0.0.1}"
BACKEND_PORT="${LLP_PORT:-8000}"

log()  { printf '\033[1;34m[run]\033[0m %s\n'   "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

[ -x "$ROOT/backend/.venv/bin/python" ] \
  || die "백엔드 가상환경이 없습니다. 먼저 ./setup.sh 를 실행하세요."

run_test() {
  log "백엔드 테스트 실행 (pytest)"
  cd "$ROOT/backend"
  exec ./.venv/bin/python -m pytest
}

run_backend() {
  cd "$ROOT/backend"
  log "백엔드 기동: http://$BACKEND_HOST:$BACKEND_PORT/docs"
  ./.venv/bin/python -m uvicorn app.main:app --reload \
    --host "$BACKEND_HOST" --port "$BACKEND_PORT"
}

run_frontend() {
  [ -d "$ROOT/frontend/node_modules" ] \
    || die "프론트엔드 의존성이 없습니다. 먼저 ./setup.sh 를 실행하세요."
  cd "$ROOT/frontend"
  log "프론트엔드 기동: http://localhost:5173"
  npm run dev
}

run_all() {
  local pids=()
  cleanup() {
    log "종료 중... 자식 프로세스 정리"
    for pid in "${pids[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
  }
  trap cleanup INT TERM EXIT

  run_backend &  pids+=($!)
  run_frontend & pids+=($!)

  log "백엔드 + 프론트엔드 실행 중. 종료하려면 Ctrl-C."
  wait -n          # 한 프로세스라도 죽으면 cleanup 으로 전체 종료
}

case "$TARGET" in
  backend)  run_backend ;;
  frontend) run_frontend ;;
  test)     run_test ;;
  all)      run_all ;;
  *)        die "알 수 없는 대상: $TARGET (backend|frontend|test|all)" ;;
esac
