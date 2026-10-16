#!/usr/bin/env bash
# Stop the read-only bring-up processes (roscore, driver, bridge).
set -eo pipefail
pkill -f 'ros2 run ros1_bridge dynamic_bridge' 2>/dev/null || true
pkill -f 'kinova_arm_driver' 2>/dev/null || true
pkill -f 'kinova_robot.launch' 2>/dev/null || true
pkill -f 'robot_state_publisher' 2>/dev/null || true
pkill -f rosmaster 2>/dev/null || true
pkill -f roscore 2>/dev/null || true
sleep 1
echo "Stopped. Remaining ROS processes:"
pgrep -af 'roscore|rosmaster|kinova|dynamic_bridge' || echo "(none)"
