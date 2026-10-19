#!/usr/bin/env bash
#
# 20_cameras.sh — start/stop/status the RealSense camera nodes.
#
#   bash scripts/20_cameras.sh start [cam0|cam1|cam2|all]
#   bash scripts/20_cameras.sh stop  [cam0|cam1|cam2|all]
#   bash scripts/20_cameras.sh status
#   bash scripts/20_cameras.sh logs  [cam0]
#
# Camera serials/roles are documented in config/cameras.yaml. The serials here
# are the RealSense *SDK* serials (rs-enumerate-devices), not the sysfs iSerial.
#
# Nodes publish under /<name>/camera/... (e.g. /cam0/camera/color/image_raw).
#
set -eo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
LOG="$ROOT/logs"
mkdir -p "$LOG"

declare -A SERIAL=(
  [cam0]="935322072821"   # port 2-2.2 (USB 3), video6-11
  [cam1]="935422072205"   # port 2-2.4 (USB 3), video30-35
  [cam2]="014122071597"   # port 1-9.1 (USB 2), video12-17
)

# USB port used as a preflight check.  The video node numbers are NOT stable;
# the port is (until the device is replugged).  If the port is absent from the
# container sysfs, the host passthrough must be refreshed first (R15/R16/R17).
declare -A PORT=(
  [cam0]="2-2.2"
  [cam1]="2-2.4"
  [cam2]="1-9.1"
)

_serial_pids() {
  pgrep -f "realsense2_camera_node.*serial_no:.*$1" 2>/dev/null || true
}

PROFILE_COLOR="640x480x30"
PROFILE_DEPTH="640x480x30"

_is_running() {
  local pidfile="$LOG/$1.pid" pid
  [ -f "$pidfile" ] || return 1
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

_start() {
  local name="$1" serial="${SERIAL[$1]:-}"
  if [ -z "$serial" ]; then
    echo "unknown camera: $name (known: cam0 cam1 cam2)" >&2
    return 2
  fi
  if _is_running "$name"; then
    echo "  $name already running (pid $(cat "$LOG/$name.pid"))"
    return 0
  fi

  local port="${PORT[$name]:-}"
  if [ -n "$port" ] && [ ! -d "/sys/bus/usb/devices/$port" ]; then
    echo "  $name: USB port $port is absent from this container." >&2
    echo "  Refresh the host Incus USB passthrough (or replug the camera) first." >&2
    return 1
  fi

  # A stale pid file can hide a live node; never start a second node on the
  # same serial (two nodes fighting for the device triggered a USB reset, R17).
  local existing
  existing="$(_serial_pids "$serial")"
  if [ -n "$existing" ]; then
    echo "  $name: refusing to start; serial $serial already in use by:" >&2
    echo "$existing" | sed 's/^/    /' >&2
    echo "  stop it with: bash scripts/20_cameras.sh stop $name" >&2
    return 1
  fi

  setsid bash -c 'source /opt/ros/jazzy/setup.bash
    exec ros2 run realsense2_camera realsense2_camera_node \
      --ros-args -r "__ns:=/$0" -r __node:=camera \
      -p "serial_no:='\''$1'\''" \
      -p camera_name:=$0 \
      -p enable_color:=true -p enable_depth:=true \
      -p enable_infra1:=false -p enable_infra2:=false \
      -p align_depth.enable:=true -p pointcloud.enable:=false \
      -p "rgb_camera.color_profile:=$2" \
      -p "depth_module.depth_profile:=$3"' \
    "$name" "$serial" "$PROFILE_COLOR" "$PROFILE_DEPTH" \
    >"$LOG/$name.log" 2>&1 &
  echo $! >"$LOG/$name.pid"
  echo "  started $name (serial $serial, pid $(cat "$LOG/$name.pid")) -> logs/$name.log"
}

_stop() {
  local name="$1" pidfile="$LOG/$name.pid" pid serial="${SERIAL[$1]:-}"
  local stopped=0
  if _is_running "$name"; then
    pid="$(cat "$pidfile")"
    kill -INT -- "-$pid" 2>/dev/null || kill -INT "$pid" 2>/dev/null || true
    for _ in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    kill -KILL -- "-$pid" 2>/dev/null || true
    stopped=1
  fi
  # Fallback for a stale pid file or a reparented child: kill by serial.
  if [ -n "$serial" ]; then
    local p
    for p in $(_serial_pids "$serial"); do
      kill -KILL "$p" 2>/dev/null || true
      stopped=1
    done
  fi
  rm -f "$pidfile"
  if [ "$stopped" = 1 ]; then
    echo "  $name: stopped"
    sleep 1   # give the kernel a moment to release the video nodes
  else
    echo "  $name: not running"
  fi
}

_all() { echo cam0 cam1 cam2; }

cmd_start() {
  local who="${1:-all}"
  echo "Starting RealSense nodes ..."
  if [ "$who" = "all" ]; then for c in $(_all); do _start "$c"; done; else _start "$who"; fi
}

cmd_stop() {
  local who="${1:-all}"
  echo "Stopping RealSense nodes ..."
  if [ "$who" = "all" ]; then for c in $(_all); do _stop "$c"; done; else _stop "$who"; fi
}

cmd_status() {
  echo "Cameras:"
  for c in $(_all); do
    if _is_running "$c"; then
      echo "  $c: running (serial ${SERIAL[$c]}, pid $(cat "$LOG/$c.pid"))"
    else
      echo "  $c: stopped"
    fi
  done
  echo "ROS 2 camera topics:"
  bash -c 'source /opt/ros/jazzy/setup.bash; ros2 topic list 2>/dev/null' \
    | grep -E '^/(cam[0-9])/camera/(color|depth|aligned_depth_to_color)/image_raw$' \
    | sed 's/^/  /' || true
}

case "${1:-status}" in
  start)  shift; cmd_start "${1:-all}" ;;
  stop)   shift; cmd_stop "${1:-all}" ;;
  status) cmd_status ;;
  logs)   tail -n 50 -f "$LOG/${2:-cam0}.log" ;;
  *) echo "usage: $0 {start|stop|status|logs} [cam0|cam1|cam2|all]" >&2; exit 2 ;;
esac
