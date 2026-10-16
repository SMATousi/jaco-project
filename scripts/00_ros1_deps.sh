#!/usr/bin/env bash
# Install the remaining ROS 1 Noetic + system dependencies needed to build/run
# the kinova-ros Gen2 (JACO2) driver and the ROS 1 side of the bridge.
set -eo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get -o Acquire::Retries=15 --fix-missing install -y \
  ros-noetic-xacro \
  ros-noetic-urdf \
  ros-noetic-tf \
  ros-noetic-angles \
  ros-noetic-actionlib \
  ros-noetic-actionlib-msgs \
  ros-noetic-control-msgs \
  ros-noetic-trajectory-msgs \
  ros-noetic-dynamic-reconfigure \
  ros-noetic-interactive-markers \
  ros-noetic-visualization-msgs \
  ros-noetic-message-generation \
  ros-noetic-message-runtime \
  ros-noetic-robot-state-publisher \
  ros-noetic-joint-state-publisher \
  libboost-dev \
  python3-empy \
  python3-lark \
  python3-yaml \
  python3-catkin-pkg

echo "ROS 1 dependencies installed."
