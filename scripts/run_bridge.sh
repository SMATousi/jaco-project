#!/usr/bin/env bash
# Run the ros1_bridge dynamic bridge. --bridge-all-1to2-topics makes every ROS 1
# topic visible from ROS 2 even without a subscriber, which is what we want for
# the read-only bring-up check (so `ros2 topic list` shows the JACO topics).
#
# The bridge repeatedly logs a harmless "failed to create 2to1 bridge for topic
# '/rosout'" warning (ROS 2 rcl_interfaces/Log has no ROS 1 equivalent); stderr is
# redirected to a log so the terminal stays readable.
set -eo pipefail
source /root/jaco-project/scripts/runtime_env.sh bridge

mkdir -p /root/jaco-project/logs
exec ros2 run ros1_bridge dynamic_bridge --bridge-all-1to2-topics \
  2>> /root/jaco-project/logs/bridge.log
