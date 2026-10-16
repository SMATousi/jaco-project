#!/usr/bin/env bash
# Bring up the kinova-ros driver for the JACO2 6-DOF 3-finger arm in READ-ONLY
# mode: it connects to the arm and publishes joint state / status. It does NOT
# command any motion. Run scripts/run_bridge.sh in a second terminal to expose
# these topics to ROS 2 Jazzy.
set -eo pipefail
source /root/jaco-project/scripts/runtime_env.sh ros1

exec roslaunch kinova_bringup kinova_robot.launch \
  kinova_robotType:=j2s6s300
