#!/usr/bin/env bash
# Shared environment helper.
# Usage:  source scripts/runtime_env.sh ros2|ros1|bridge
#
#   ros2    - clean ROS 2 Jazzy + kinova_msgs only. Use this for your own nodes
#             and for ros2 CLI checks. Never pulls in ROS 1.
#   ros1    - ROS 1 Noetic + kinova-ros driver.
#   bridge  - everything, for running the ros1_bridge node itself.
set -eo pipefail

_clean() {
  unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_EXE CONDA_PYTHON_EXE PYTHONHOME 2>/dev/null || true
  unset ROS_DISTRO ROS_VERSION ROS_PYTHON_VERSION ROS_MASTER_URI ROS_PACKAGE_PATH 2>/dev/null || true
  export PATH=/usr/bin:/bin:/usr/sbin:/sbin
}

case "${1:-}" in
  ros2)
    _clean
    source /opt/ros/jazzy/setup.bash
    source /root/jaco-project/ros2_ws/install/setup.bash
    ;;
  ros1)
    _clean
    source /opt/ros/noetic/setup.bash
    source /root/jaco-project/ros1_ws/devel/setup.bash
    export ROS_MASTER_URI=http://localhost:11311
    ;;
  bridge)
    _clean
    source /opt/ros/jazzy/setup.bash
    source /root/jaco-project/ros2_ws/install/setup.bash
    source /root/jaco-project/ros2_bridge_ws/install/setup.bash
    source /opt/ros/noetic/setup.bash
    source /root/jaco-project/ros1_ws/devel/setup.bash
    export ROS_MASTER_URI=http://localhost:11311
    ;;
  *)
    echo "usage: source runtime_env.sh ros2|ros1|bridge" >&2
    ;;
esac
