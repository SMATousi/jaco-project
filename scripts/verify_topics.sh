#!/usr/bin/env bash
# Read-only check that the JACO topics are visible on both sides of the bridge.
# The ROS 2 checks run in a CLEAN Jazzy environment (no ROS 1 paths), which is
# how your own nodes would run.
set -eo pipefail

echo "=== ROS 1 topics (/j2s6s300_*) ==="
( source /root/jaco-project/scripts/runtime_env.sh ros1 >/dev/null 2>&1
  rostopic list 2>/dev/null | grep -E 'j2s6s300' | grep 'out/' ) \
  || echo "(none - is the driver/roscore running?)"

echo
echo "=== ROS 2 topics (/j2s6s300_*) ==="
( source /root/jaco-project/scripts/runtime_env.sh ros2 >/dev/null 2>&1
  ros2 topic list 2>/dev/null | grep -E 'j2s6s300' | grep -vE 'action|/in/|status' ) \
  || echo "(none - is the bridge running?)"

echo
echo "=== ROS 2 joint_state (one message) ==="
( source /root/jaco-project/scripts/runtime_env.sh ros2 >/dev/null 2>&1
  timeout 10 ros2 topic echo /j2s6s300_driver/out/joint_state --once ) \
  || echo "(no message)"

echo
echo "=== ROS 2 joint_angles (kinova_msgs, one message) ==="
( source /root/jaco-project/scripts/runtime_env.sh ros2 >/dev/null 2>&1
  timeout 10 ros2 topic echo /j2s6s300_driver/out/joint_angles --once ) \
  || echo "(no message)"
