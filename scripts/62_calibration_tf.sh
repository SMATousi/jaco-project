#!/usr/bin/env bash
#
# 62_calibration_tf.sh — publish the calibrated base <-> camera static TF.
#
#   bash scripts/62_calibration_tf.sh start [calibration/base_cam0.yaml]
#   bash scripts/62_calibration_tf.sh stop
#   bash scripts/62_calibration_tf.sh status
#
# The YAML is written by scripts/handeye_solve.py.  The transform is published
# as parent -> child (cam0_link pose in the arm base frame).
#
set -eo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
LOG="$ROOT/logs"
PIDFILE="$LOG/calibration_tf.pid"
LOGFILE="$LOG/calibration_tf.log"
YAMLFILE="$LOG/calibration_tf.yaml"
YAML="${2:-$ROOT/calibration/base_cam0.yaml}"

_is_running() {
  [ -f "$PIDFILE" ] || return 1
  local pid; pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

_fields() {
  /usr/bin/python3 - "$1" <<'PY'
import sys, yaml
p = sys.argv[1]
with open(p) as fh:
    d = yaml.safe_load(fh)
if not d.get("valid", False):
    print("WARNING: calibration YAML is marked invalid", file=sys.stderr)
t = d["translation"]; q = d["rotation"]
print(d["frame_parent"])
print(d["frame_child"])
for v in list(t) + list(q):
    print(f"{float(v):.9f}")
PY
}

cmd_start() {
  if _is_running; then
    echo "  calibration TF already running (pid $(cat "$PIDFILE"))"
    return 0
  fi
  if [ ! -f "$YAML" ]; then
    echo "  missing $YAML — run scripts/handeye_solve.py first" >&2
    return 2
  fi

  mapfile -t v < <(_fields "$YAML")
  local parent="${v[0]}" child="${v[1]}"
  local x="${v[2]}" y="${v[3]}" z="${v[4]}"
  local qx="${v[5]}" qy="${v[6]}" qz="${v[7]}" qw="${v[8]}"

  echo "  $parent -> $child"
  echo "  xyz=[$x, $y, $z] q=[$qx, $qy, $qz, $qw]"

  setsid bash -c "source /opt/ros/jazzy/setup.bash
    exec ros2 run tf2_ros static_transform_publisher \
      --x '$x' --y '$y' --z '$z' \
      --qx '$qx' --qy '$qy' --qz '$qz' --qw '$qw' \
      --frame-id '$parent' --child-frame-id '$child'" \
    >"$LOGFILE" 2>&1 &
  echo $! >"$PIDFILE"
  sleep 1
  if _is_running; then
    echo "$YAML" >"$YAMLFILE"
    echo "  started (pid $(cat "$PIDFILE")) -> logs/calibration_tf.log"
  else
    echo "  FAILED to start; see logs/calibration_tf.log" >&2
    tail -20 "$LOGFILE" >&2 || true
    return 3
  fi
}

cmd_stop() {
  if ! _is_running; then
    rm -f "$PIDFILE"
    echo "  calibration TF: not running"
    return 0
  fi
  local pid; pid="$(cat "$PIDFILE")"
  kill -INT -- "-$pid" 2>/dev/null || kill -INT "$pid" 2>/dev/null || true
  for _ in $(seq 1 5); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
  kill -KILL -- "-$pid" 2>/dev/null || true
  rm -f "$PIDFILE" "$YAMLFILE"
  echo "  calibration TF: stopped"
}

cmd_status() {
  if _is_running; then
    local y="$YAML"
    [ -f "$YAMLFILE" ] && y="$(cat "$YAMLFILE")"
    echo "  calibration TF: running (pid $(cat "$PIDFILE"))"
    echo "  YAML: $y"
    _fields "$y" 2>/dev/null | sed 's/^/    /' || true
  else
    echo "  calibration TF: stopped"
  fi
}

case "${1:-status}" in
  start)  cmd_start ;;
  stop)   cmd_stop ;;
  status) cmd_status ;;
  *) echo "usage: $0 {start|stop|status} [calibration/base_cam0.yaml]" >&2; exit 2 ;;
esac
