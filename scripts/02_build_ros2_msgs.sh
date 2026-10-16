#!/usr/bin/env bash
# Build the ROS 2 (Jazzy) kinova_msgs interface package.
# NOTE: the active `python3` on this box is conda's 3.14, which ROS 2 Jazzy cannot
# use. We force the system 3.12 interpreter for both PATH and CMake.
set -eo pipefail

unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_EXE CONDA_PYTHON_EXE PYTHONHOME 2>/dev/null || true
export PATH=/usr/bin:/bin:/usr/sbin:/sbin

source /opt/ros/jazzy/setup.bash

WS=/root/jaco-project/ros2_ws
cd "$WS"
colcon build --symlink-install --packages-select kinova_msgs \
  --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3.12 -DPython_EXECUTABLE=/usr/bin/python3.12

echo
echo "Built. Source it with:"
echo "  source $WS/install/setup.bash"
