#!/usr/bin/env bash
# Clone the upstream third-party sources this project builds against, pinned to the
# commits that were verified working. Run once, before the other build scripts.
#
#   ros1_ws/src/kinova-ros        Kinovarobotics/kinova-ros   (ROS 1 Gen2 driver)
#   ros2_bridge_ws/src/ros1_bridge ros2/ros1_bridge           (topic/service bridge)
set -eo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"

clone_at() {  # <url> <dest> <commit>
  local url="$1" dest="$2" commit="$3"
  if [ -d "$dest/.git" ]; then
    echo "  already cloned: $dest"
  else
    echo "  cloning $url"
    mkdir -p "$(dirname "$dest")"
    git clone "$url" "$dest"
  fi
  git -C "$dest" fetch --all --tags --quiet
  git -C "$dest" checkout --quiet "$commit"
  echo "  $dest @ $(git -C "$dest" rev-parse --short HEAD)"
}

echo "Fetching upstream sources ..."
clone_at https://github.com/Kinovarobotics/kinova-ros.git \
         "$ROOT/ros1_ws/src/kinova-ros" \
         924781d3dfe241b2b94b3c72a804b80d3658cf02

clone_at https://github.com/ros2/ros1_bridge.git \
         "$ROOT/ros2_bridge_ws/src/ros1_bridge" \
         611755fd917285316051cbea80507e8b2f6b7ec1

echo "Done. Next: sudo bash scripts/00_ros1_deps.sh"
