#!/usr/bin/env bash
#
# LLP — 종합 설치 스크립트 (backend + frontend)
# 백엔드 Python venv 생성·의존성 설치, 프론트엔드 npm 의존성 설치 및 .env 준비.
#
# 사용법:
#   ./setup.sh              # 백엔드 + 프론트엔드 모두 설치
#   ./setup.sh backend      # 백엔드만
#   ./setup.sh frontend     # 프론트엔드만
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
TARGET="${1:-all}"

log()  { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n'  "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

setup_backend() {
  log "백엔드 설치 시작 ($ROOT/backend)"
  command -v "$PYTHON_BIN" >/dev/null 2>&1 \
    || die "$PYTHON_BIN 을 찾을 수 없습니다. Python 3.11 설치 후 PYTHON_BIN 으로 지정하세요."

  cd "$ROOT/backend"
  if [ ! -d .venv ]; then
    log "가상환경 생성: .venv"
    "$PYTHON_BIN" -m venv .venv
  else
    log "기존 .venv 재사용"
  fi

  log "pip 업그레이드 및 의존성 설치"
  ./.venv/bin/python -m pip install --upgrade pip >/dev/null
  ./.venv/bin/python -m pip install -r requirements.txt

  # SQLite DB(llp.db)는 첫 서버 기동 시 startup 훅의 init_db()가 생성하므로 별도 작업 불필요.
  log "백엔드 설치 완료. 테스트는 ./run.sh test 또는 backend/.venv/bin/python -m pytest"
}

setup_frontend() {
  log "프론트엔드 설치 시작 ($ROOT/frontend)"
  command -v npm >/dev/null 2>&1 \
    || die "npm 을 찾을 수 없습니다. Node.js 18+ 를 설치하세요."

  cd "$ROOT/frontend"
  if [ ! -f .env ]; then
    log ".env 생성 (.env.example 복사)"
    cp .env.example .env
  else
    log "기존 .env 유지"
  fi

  log "npm 의존성 설치"
  npm install

  log "프론트엔드 설치 완료."
}

case "$TARGET" in
  backend)  setup_backend ;;
  frontend) setup_frontend ;;
  all)      setup_backend; setup_frontend ;;
  *)        die "알 수 없는 대상: $TARGET (backend|frontend|all)" ;;
esac

log "전체 설치 완료. 실행: ./run.sh"
