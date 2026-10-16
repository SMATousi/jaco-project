# jaco-project — Kinova JACO2 (Gen2) on ROS 2 Jazzy via ros1_bridge

Bridge the **Kinova JACO2 Gen2** arm (6 DOF, 3-finger → `j2s6s300`) into a **ROS 2
Jazzy** stack on Ubuntu 24.04.

## Why this shape

* Gen2 JACO arms are supported by Kinova **only in ROS 1** (`kinova-ros`). There is
  no official ROS 2 driver for Gen2 (`ros2_kortex` is Gen3-only).
* Ubuntu 24.04 has no official ROS 1, and `ros1_bridge` is not packaged for Jazzy,
  so this uses the community `ppa:ros-for-jammy/noble` Noetic builds and compiles
  `ros1_bridge` from source **against both distros on the host**.

```
  ┌─────────────────────────── host (Ubuntu 24.04) ───────────────────────────┐
  │  ROS 1 Noetic                          ROS 2 Jazzy                         │
  │  kinova-ros driver  ──topics──►  ros1_bridge  ──DDS──►  your Jazzy nodes   │
  │  (libusb → JACO USB)             (topics + services)                        │
  └────────────────────────────────────────────────────────────────────────────┘
```

## Layout

```
ros1_ws/               Kinova Gen2 ROS 1 driver (upstream Kinovarobotics/kinova-ros)
  └ src/kinova-ros
ros2_ws/               ROS 2 port of the Kinova interfaces — CLEAN (Jazzy-only)
  └ src/kinova_msgs      source THIS in your own nodes to get kinova_msgs
ros2_bridge_ws/        ros1_bridge, built separately (its env chains ROS 1 + ROS 2)
  └ src/ros1_bridge
scripts/               control + build helpers
  └ jaco                 one-command bring-up + control (start/stop/status/verify/echo/jog/logs)
```

> **Why two ROS 2 workspaces?** colcon writes the sourced underlays into the
> generated `install/setup.bash`. Building the bridge in the same workspace as
> `kinova_msgs` would make that workspace's setup pull in `/opt/ros/noetic` and the
> ROS 1 overlay, breaking any ROS 2 consumer that sources it. The bridge therefore
> lives in its own workspace.


## Build (one time)

```bash
bash      scripts/00_clone_upstream.sh   # clone kinova-ros + ros1_bridge at pinned commits
sudo bash scripts/00_ros1_deps.sh        # remaining Noetic deps (xacro, tf, actionlib, ...)
bash      scripts/01_build_ros1.sh       # catkin_make the kinova-ros packages
bash      scripts/02_build_ros2_msgs.sh  # colcon build the ROS 2 kinova_msgs
bash      scripts/03_build_bridge.sh     # colcon build ros1_bridge (its own workspace)
```

> The `kinova-ros` and `ros1_bridge` sources are third-party and are **not** committed
> (see `.gitignore`); `00_clone_upstream.sh` fetches them at the verified commits.
> The scripts assume the project lives at `/root/jaco-project` (paths are absolute in
> a few places); adjust them if you clone elsewhere.

## Run — one command

```bash
scripts/jaco start      # roscore + driver + bridge, in the background
scripts/jaco status     # processes + topics
scripts/jaco verify     # read live JointState from ROS 2
scripts/jaco jog 1 5 --delta 10   # safe, self-stopping joint jog (see "Motion control")
scripts/jaco stop       # stop everything
scripts/jaco logs       # follow logs/driver.log (or: logs bridge|roscore)
```

`start` brings up the processes detached (they keep running after the shell exits)
with PID files and logs under `logs/`. It waits for roscore, the driver node, and the
bridged ROS 2 topics to appear before returning. `scripts/jaco help` lists commands.

### Run — manual (three terminals)

```bash
bash scripts/run_driver_readonly.sh   # terminal 1: driver (connects to arm)
bash scripts/run_bridge.sh            # terminal 2: bridge
bash scripts/verify_topics.sh         # terminal 3: check from ROS 2
```

### Consuming from your own nodes

```bash
source scripts/runtime_env.sh ros2    # clean Jazzy + kinova_msgs, no ROS 1
ros2 topic list | grep j2s6s300
ros2 topic echo /j2s6s300_driver/out/joint_state --once
```

> Do **not** source the ROS 1 environment in a shell you use for `ros2` CLI checks:
> ROS 1's Python packages shadow ROS 2's and the CLI reports
> "The message type 'sensor_msgs/msg/JointState' is invalid".

Typical ROS 1 topics (namespaced by `j2s6s300`):

| Topic | Type |
|---|---|
| `/j2s6s300_driver/out/joint_state` | `sensor_msgs/JointState` |
| `/j2s6s300_driver/out/joint_angles` | `kinova_msgs/JointAngles` |
| `/j2s6s300_driver/out/tool_pose` | `geometry_msgs/PoseStamped` |
| `/j2s6s300_driver/out/tool_wrench` | `geometry_msgs/WrenchStamped` |
| `/j2s6s300_driver/out/finger_position` | `kinova_msgs/FingerPosition` |

## Motion control

The bridge carries **topics and services**, not actions, so from ROS 2 you can:

| Interface | What it does |
|---|---|
| `/<robot>_driver/in/home_arm` (service) | bounded move to the arm's home pose |
| `/<robot>_driver/in/start` / `in/stop` (services) | software start / stop |
| `/<robot>_driver/in/clear_trajectories` (service) | clear the trajectory FIFO |
| `/<robot>_driver/in/joint_velocity` (`kinova_msgs/JointVelocity`, topic) | jog joints, deg/s |
| `/<robot>_driver/in/cartesian_velocity*` (`PoseVelocity`, topic) | jog in Cartesian space |
| `ArmPose` / `ArmJointAngles` / `SetFingersPosition` (**actions**) | **not bridged** — no bounded go-to-angle/pose from ROS 2 |

### Home

```bash
source scripts/runtime_env.sh ros2
ros2 service call /j2s6s300_driver/in/home_arm kinova_msgs/srv/HomeArm "{}"
```

### Jog — `scripts/jaco jog`

The driver has **no velocity watchdog**: a non-zero velocity keeps the arm moving
until it receives zeros (or Stop / e-stop). `jaco jog` therefore always finishes
with a zero command, and refuses to move unless it confirms the bridge is live.

```bash
scripts/jaco jog 1 5 2            # joint 1 at +5 deg/s for 2 s (open loop)
scripts/jaco jog 1 5 --delta 10   # ... until the joint has moved ~10 deg (closed loop)
scripts/jaco jog 1 0 0 --check    # zeros only: verify the path, no motion
```

Hard limits in the helper: `|vel| ≤ 20 deg/s`, `≤ 10 s`, `|delta| ≤ 180 deg`; it
always publishes a final zero stream to flush the API FIFO.

`scripts/jog.py` can also be run directly (`./scripts/jog.py 1 5 --delta 10`): if it
can't import `rclpy` it re-execs itself under `runtime_env.sh ros2` and the system
Python 3.12, so an active conda env doesn't matter.

> **If you publish a velocity yourself** (e.g. `ros2 topic pub`), *you* must publish
> zeros to stop it — nothing else will.
>
> The driver's own `JointTrajectoryController` advertises `in/joint_velocity`, so with
> `--bridge-all-1to2-topics` the bridge also opens a 1→2 bridge on that topic. A jog
> from a separate ROS 2 process stays loop-safe because `ros1_bridge` sets
> `ignore_local_publications = true` on the 2→1 subscription (`factory.hpp`).

## USB permissions

The Kinova arm is `22cd:0000`. `kinova_driver/udev/10-kinova-arm.rules` sets the
device to `MODE=666`. Install it if the driver cannot open the device:

```bash
sudo cp ros1_ws/src/kinova-ros/kinova_driver/udev/10-kinova-arm.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## Build gotchas already handled

* **Python**: the login `python3` is conda's 3.14, which ROS 2 Jazzy cannot use. All
  scripts force `/usr/bin/python3.12` (PATH + `-DPython3_EXECUTABLE`).
* **ROS 2 interface rules**: `kinova_msgs` needed two edits in the ROS 2 port:
  `KinovaPose` fields lowercased (`X`→`x`, `ThetaX`→`thetax`, …) and the action
  `Arm_KinovaPose` renamed `ArmKinovaPose` (ROS 2 forbids `_` in type names).
  The bridge auto-maps ROS 1 field names case-insensitively, so `X`↔`x` still works.
* **Extra deps** beyond `ros-base`: `control_msgs`, `trajectory_msgs`,
  `dynamic_reconfigure`, `xacro`, `tf`, `actionlib`, `interactive_markers`,
  `visualization_msgs`, `robot_state_publisher` (all in `scripts/00_ros1_deps.sh`).
* **Find-package clash**: the ROS 1 catkin `kinova_msgs` also exports a
  `kinova_msgsConfig.cmake` (in `ros1_ws/devel/share/kinova_msgs/cmake`). If it comes
  first on `CMAKE_PREFIX_PATH`, the bridge links the ROS 1 headers and fails with
  `kinova_msgs/msg/*.hpp: No such file or directory`. `scripts/03_build_bridge.sh`
  sources the ROS 2 overlay last (and pins it) so the ROS 2 config wins.

## Verified working

Read-only bring-up confirmed (Ubuntu 24.04, system Python 3.12):

* Driver connects to the arm and reports `model: Jaco V2 Service` → JACO2.
* All `/j2s6s300_driver/out/*` topics visible in ROS 2 Jazzy, including the custom
  `kinova_msgs/msg/JointAngles`. `sensor_msgs/JointState` carries live positions,
  velocities and efforts for all 6 joints + 3 fingers.
* **Motion via the bridge is confirmed.** `in/home_arm` (2→1 service) moved the arm
  from `(281, 257, 59, 218, 116, 161)` to home `(275, 175, 79, 243, 84, 75)`.
  `scripts/jaco jog 1 5 --delta 6` (2→1 topic) moved joint 1 by **+6.4 deg** and
  stopped cleanly (independently read back at `286.49 deg`).

> **Note:** the driver *does* actuate the gripper once at startup — its log says
> "Initializing fingers... the fingers should open completely". So a fresh launch is
> not 100% motionless; the arm itself is not commanded otherwise.


## Notes / limitations

* `ros1_bridge` (upstream) bridges **topics and services**. Action interfaces
  (`kinova_msgs/*.action`) are **not** bridged, so bounded go-to-angle/pose moves are
  unavailable from ROS 2 today; velocity jogging and services work. An action-capable
  bridge fork (e.g. `smith-doug/ros1_bridge`) would add them.
