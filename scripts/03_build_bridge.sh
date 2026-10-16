#!/usr/bin/env bash
# Build ros1_bridge in its OWN workspace (ros2_bridge_ws), against BOTH ROS 1
# Noetic (with the kinova-ros messages) and ROS 2 Jazzy (with our ported
# kinova_msgs from the clean ros2_ws).
#
# Why a separate workspace? colcon writes the set of sourced underlays into the
# generated install/setup.bash. If the bridge were built in the same workspace as
# kinova_msgs, that workspace's setup.bash would pull in /opt/ros/noetic and the
# ROS 1 overlay, contaminating every ROS 2 consumer that sources it.
set -eo pipefail

unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_EXE CONDA_PYTHON_EXE PYTHONHOME 2>/dev/null || true
export PATH=/usr/bin:/bin:/usr/sbin:/sbin

ROS1_WS=/root/jaco-project/ros1_ws
ROS2_WS=/root/jaco-project/ros2_ws
BRIDGE_WS=/root/jaco-project/ros2_bridge_ws

# --- consumer overlay must already be built (clean, Jazzy-only) ---
[ -f "$ROS2_WS/install/setup.bash" ] || {
  echo "ros2_ws is not built yet; run scripts/02_build_ros2_msgs.sh first" >&2; exit 1; }

# --- source everything, ordered so the ROS 2 kinova_msgs wins find_package() ---
# The ROS 1 catkin package also exports a kinova_msgs CMake config (in
# ros1_ws/devel/share/kinova_msgs/cmake). setup.bash prepends each prefix, so the
# LAST sourced ends up FIRST on CMAKE_PREFIX_PATH. We therefore source ROS 1 first
# and the ROS 2 overlay last, and additionally pin the ROS 2 overlay explicitly.
source /opt/ros/noetic/setup.bash
source "$ROS1_WS/devel/setup.bash"
source /opt/ros/jazzy/setup.bash
source "$ROS2_WS/install/setup.bash"
export CMAKE_PREFIX_PATH="$ROS2_WS/install:$CMAKE_PREFIX_PATH"

cd "$BRIDGE_WS"
colcon build \
  --packages-select ros1_bridge \
  --cmake-force-configure \
  --cmake-args \
    -DBUILD_TESTING=OFF \
    -DTRACETOOLS_DISABLED=ON \
    -DPython3_EXECUTABLE=/usr/bin/python3.12 \
    -DPython_EXECUTABLE=/usr/bin/python3.12 \
    -DCMAKE_BUILD_TYPE=Release

echo
echo "ros1_bridge built. Check bridged types with:"
echo "  source /root/jaco-project/scripts/runtime_env.sh bridge"
echo "  ros2 run ros1_bridge dynamic_bridge --print-pairs | grep -i kinova"
