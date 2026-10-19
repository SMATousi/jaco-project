#!/usr/bin/env bash
#
# 40_vla_server.sh — start/stop/status the resident SmolVLA inference server.
#
# The server runs in the dedicated `vla` conda env (torch + lerobot). The ROS 2
# side talks to it over localhost HTTP; see spec/04_vla_model.md §4.
#
#   bash scripts/40_vla_server.sh start
#   bash scripts/40_vla_server.sh status
#   bash scripts/40_vla_server.sh stop
#   bash scripts/40_vla_server.sh logs
#
set -eo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
LOG="$ROOT/logs"
mkdir -p "$LOG"

PY="${VLA_PYTHON:-/root/miniconda3/envs/vla/bin/python}"
HOST="${VLA_HOST:-127.0.0.1}"
PORT="${VLA_PORT:-8090}"
URL="http://${HOST}:${PORT}"

_is_running() {
  local pidfile="$LOG/vla_server.pid" pid
  [ -f "$pidfile" ] || return 1
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

cmd_start() {
  if _is_running; then
    echo "  vla_server already running (pid $(cat "$LOG/vla_server.pid"))"
    return 0
  fi
  if [ ! -x "$PY" ]; then
    echo "ERROR: python not found: $PY (set VLA_PYTHON)" >&2
    return 2
  fi
  echo "Starting SmolVLA server on ${URL} ..."
  setsid bash -c "cd '$ROOT'; exec '$PY' -m vla.vla_server --host '$HOST' --port $PORT" \
    >"$LOG/vla_server.log" 2>&1 &
  echo $! >"$LOG/vla_server.pid"
  echo "  pid $(cat "$LOG/vla_server.pid") -> logs/vla_server.log"

  # model load + warm-up can take ~15-30 s
  for i in $(seq 1 60); do
    if curl -sf --max-time 2 "$URL/health" >/dev/null 2>&1; then
      echo "  healthy after ${i}s"
      curl -s "$URL/health"
      echo
      return 0
    fi
    sleep 1
  done
  echo "ERROR: server did not become healthy in 60s; see logs/vla_server.log" >&2
  return 1
}

cmd_stop() {
  if ! _is_running; then
    rm -f "$LOG/vla_server.pid"
    echo "  vla_server: not running"
    return 0
  fi
  local pid
  pid="$(cat "$LOG/vla_server.pid")"
  kill -INT -- "-$pid" 2>/dev/null || kill -INT "$pid" 2>/dev/null || true
  for _ in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
  kill -KILL -- "-$pid" 2>/dev/null || true
  rm -f "$LOG/vla_server.pid"
  echo "  vla_server: stopped"
}

cmd_status() {
  if _is_running; then
    echo "vla_server: running (pid $(cat "$LOG/vla_server.pid"))"
    curl -s --max-time 2 "$URL/health" || echo "  (health request failed)"
    echo
  else
    echo "vla_server: stopped"
  fi
}

case "${1:-status}" in
  start)  cmd_start ;;
  stop)   cmd_stop ;;
  status) cmd_status ;;
  logs)   tail -n 80 -f "$LOG/vla_server.log" ;;
  *) echo "usage: $0 {start|stop|status|logs}" >&2; exit 2 ;;
esac
