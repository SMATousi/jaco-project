#!/usr/bin/env bash
#
# 10_install_realsense.sh — install the Intel RealSense ROS 2 stack (APT).
#
# Decision D8: use the distro APT packages, pinned to the versions validated on
# 2026-10-19, with a fallback to "latest" if the repo has rotated the build.
#
#   bash scripts/10_install_realsense.sh [--latest]
#
# After install:
#   source /opt/ros/jazzy/setup.bash
#   rs-enumerate-devices -s
#
set -euo pipefail

ROS_DISTRO="${ROS_DISTRO:-jazzy}"
LATEST=0
[ "${1:-}" = "--latest" ] && LATEST=1

# Versions validated in spec/validation/M0_environment.md (2026-10-19).
PIN_LIBREALSENSE="${REALSENSE_LIB_VERSION:-2.58.4-1noble.20260831.015923}"
PIN_CAMERA="${REALSENSE_CAMERA_VERSION:-4.58.4-1noble.20260920.235447}"
PIN_MSGS="${REALSENSE_MSGS_VERSION:-4.58.4-1noble.20260911.141016}"

if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
else
  SUDO=""
fi

echo "Installing RealSense ROS 2 packages for '${ROS_DISTRO}' ..."
$SUDO apt-get update

if [ "$LATEST" -eq 1 ]; then
  $SUDO apt-get install -y \
    "ros-${ROS_DISTRO}-realsense2-camera"
else
  $SUDO apt-get install -y \
    "ros-${ROS_DISTRO}-librealsense2=${PIN_LIBREALSENSE}" \
    "ros-${ROS_DISTRO}-realsense2-camera-msgs=${PIN_MSGS}" \
    "ros-${ROS_DISTRO}-realsense2-camera=${PIN_CAMERA}" \
    || {
      echo "Pinned versions unavailable; falling back to the latest APT build."
      $SUDO apt-get install -y "ros-${ROS_DISTRO}-realsense2-camera"
    }
fi

echo
echo "Installed:"
dpkg -l 2>/dev/null \
  | awk '/ros-.*-(realsense2-camera|realsense2-camera-msgs|librealsense2) / {printf "  %-40s %s\n", $2, $3}'

echo
echo "Verify with:"
echo "  source /opt/ros/${ROS_DISTRO}/setup.bash"
echo "  rs-enumerate-devices -s"
