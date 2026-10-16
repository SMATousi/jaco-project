#!/usr/bin/env bash
# Build the kinova-ros (ROS 1) workspace for the JACO2 6-DOF 3-finger arm.
# Only the packages needed for the read-only bring-up are whitelisted, because
# the full repo also contains MoveIt/Gazebo packages that are not installed.
set -eo pipefail

unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_EXE CONDA_PYTHON_EXE PYTHONHOME 2>/dev/null || true
export PATH=/usr/bin:/bin:/usr/sbin:/sbin

source /opt/ros/noetic/setup.bash

WS=/root/jaco-project/ros1_ws
cd "$WS"

PKGS="kinova_msgs;kinova_description;kinova_driver;kinova_bringup;kinova_demo"

catkin_make \
  -DCATKIN_WHITELIST_PACKAGES="$PKGS" \
  -DCMAKE_BUILD_TYPE=Release

echo
echo "Built. Source it with:"
echo "  source $WS/devel/setup.bash"
