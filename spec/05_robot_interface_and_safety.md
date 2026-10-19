# 05 — Robot Interface, Action-Space Mapping & Safety

This is the highest-risk part of the project: the model must drive a **real arm**.
Everything here is specified to fail safe.

## 1. What the bridge actually exposes (measured)

The `ros1_bridge` carries **topics and services, not actions**. Verified interfaces:

| Interface | Kind | Direction | Status |
|-----------|------|-----------|--------|
| `/j2s6s300_driver/in/joint_velocity` (`kinova_msgs/JointVelocity`) | topic | ROS 2 → ROS 1 | ✅ proven (`jog.py`) |
| `/j2s6s300_driver/in/cartesian_velocity*` (`PoseVelocity[...]`) | topic | ROS 2 → ROS 1 | available |
| `/j2s6s300_driver/in/home_arm` | service | ROS 2 → ROS 1 | ✅ proven |
| `/j2s6s300_driver/in/start` · `/in/stop` | service | ROS 2 → ROS 1 | available |
| `/j2s6s300_driver/in/clear_trajectories` | service | ROS 2 → ROS 1 | available |
| `/j2s6s300_driver/in/add_pose_to_Cartesian_trajectory` | service | ROS 2 → ROS 1 | available |
| `/j2s6s300_driver/trajectory_controller/command` (`trajectory_msgs/JointTrajectory`) | topic | ROS 2 → ROS 1 | **to verify** (driver subscribes; converts to joint velocities) |
| Feedback: `out/joint_state`, `out/joint_angles`, `out/tool_pose`, `out/tool_wrench`, `out/finger_position` | topic | ROS 1 → ROS 2 | ✅ |
| `ArmPose` / `ArmJointAngles` / `SetFingersPosition` | **action** | — | ❌ not bridged |

### 1a. Gripper gap (must solve for pick-and-place)

The gripper's position command is the **`SetFingersPosition` action**, which is *not*
bridged. Current gripper options from ROS 2 are limited (`in/cartesian_velocity_with_fingers`
carries finger *velocity*). **Proposed fix:** write a tiny **ROS 1 relay node** that
subscribes to a simple ROS 2-bridged topic (e.g. `.../in/finger_cmd`, `std_msgs/Float32` or
a `kinova_msgs/FingerPosition` topic) and calls the ROS 1 `SetFingersPosition` action
locally. This is small, self-contained, and avoids forking the bridge. *(Decision item D5.)*

## 2. Action-space design

Most VLAs emit a **7-DoF end-effector delta** per step:
`[Δx, Δy, Δz, Δroll, Δpitch, Δyaw, gripper]` (position in metres, rotation in radians or
normalized, gripper 0–1). We must map that to JACO2.

### 2a. Mapping options

| Option | Model output → command | Pros | Cons |
|--------|------------------------|------|------|
| **A. EEF delta → joint velocity** | ΔEEF → (IK or Jacobian) → joint velocity limits → `in/joint_velocity` | direct, low latency, matches VLA output | needs IK/Jacobian; no built-in collision safety |
| **B. EEF delta → EEF velocity** | ΔEEF → scale → `in/cartesian_velocity` | simplest, exactly what the driver wants | Cartesian velocity moves in straight lines; obstacle risk |
| **C. EEF delta → joint trajectory** | ΔEEF → IK → joint target → `trajectory_controller/command` | **bounded** motion per step | IK + timing; topic bridging to verify |
| **D. joint-position VLAs** | model outputs joints directly → `trajectory_controller/command` | no IK needed | many VLAs output EEF, not joints |

**Recommendation:** start with **A/B** (velocity, low latency, easy watchdog) for the
bring-up loop, and add **C** (bounded joint trajectories) as the preferred *safe* execution
mode once the `trajectory_controller/command` topic is validated. IK: use the driver's own
kinematics (JACO2 IK is available in `kinova_driver`/ikfast) or `KDL`/`trac_ik` in ROS 2 —
decide at M3.

### 2b. Frames

- Cameras → `camera_color_optical_frame`; arm base → `root`/`base_link`.
- We need a **base ← camera** transform (extrinsic calibration) to express model actions in
  the arm frame. Start with a hand-measured/approx transform; proper calibration is an M1
  task.
- Actions are produced relative to the **current EEF pose** (`out/tool_pose`), so small
  calibration errors degrade gracefully.

## 3. Safety supervisor (mandatory)

The stock driver has **no velocity watchdog** and will keep moving on the last velocity
command. A companion `safety_supervisor` node wraps every command:

| Guard | Behaviour |
|-------|-----------|
| **Watchdog** | if no fresh command within `T_wd` (e.g. 200 ms) → publish zero velocity + drop to IDLE |
| **Velocity clamp** | per-joint and Cartesian speed caps (configurable) |
| **Accel/step clamp** | limit Δcommand per tick to avoid jerks |
| **Workspace box** | reject any target EEF pose outside a configured box (table + reachable set) |
| **Joint limits** | hard limits from the JACO2 spec, enforced before sending |
| **Mode gate** | only forwards commands in `ACTIVE`; `DRY_RUN` logs only |
| **E-stop** | physical e-stop always wins; software `stop` service + a big red "STOP" topic |
| **Rate limit** | cap command publish rate to a sane value |
| **Trip log** | every clamp/trip recorded (episode dir + stdout) |

The supervisor sits **between the policy client and the bridge**, and is the *only* thing
allowed to publish arm commands.

## 4. Point-of-failure behaviours

| Failure | Response |
|---------|----------|
| VLA server timeout / crash | zero velocity, IDLE, alert |
| Camera dropout | pause policy, hold position (or re-home), alert |
| Bridge/driver crash (this *has* happened — see doc 08) | supervisor detects missing feedback → zero velocity; requires restart |
| Command out of workspace/limits | clamp + log; if persistent, FAULT |
| Model emits NaN/Inf | discard chunk, IDLE, log |

## 5. Validation hooks (details in doc 07)

- **Shadow test:** replay a dataset through the full mapper+supervisor with the arm in
  `DRY_RUN`; assert no commands are published and clamp stats match expectations.
- **Step-response test:** send a small command, verify motion matches within tolerance,
  verify watchdog stops the arm when the stream is cut.
- **Fault injection:** kill the VLA server mid-chunk → assert zero velocity < 200 ms.
