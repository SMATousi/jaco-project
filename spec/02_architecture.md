# 02 — System Architecture

## 1. Component overview

```
         ┌──────────────────────────── perception ────────────────────────────┐
         │  7× RealSense D435  ──►  realsense2_camera (ROS 2)                  │
         │                          /camN/color/image_raw  /camN/depth/...     │
         └───────────────────────────────┬─────────────────────────────────────┘
                                         │ RGB-D + camera_info + TF
                                         ▼
   ┌──────────────┐   language    ┌───────────────────────────┐
   │ instruction  │──────────────►│   POLICY CLIENT (ROS 2)    │
   │  (text)      │               │  - selects views           │
   └──────────────┘               │  - builds model input      │
                                  │  - chunks actions          │
   ┌──────────────┐   joint/eef   │  - enforces rate & horizon │
   │ robot state  │──────────────►└───────────┬───────────────┘
   │ (joint_states)│                          │ observation
   └──────────────┘                           ▼
                                  ┌───────────────────────────┐
                                  │   VLA INFERENCE SERVICE    │  (local, RTX 3090)
                                  │  HTTP/gRPC or ZeroMQ       │
                                  │  SmolVLA / OpenVLA / ...   │
                                  └───────────┬───────────────┘
                                              │ action chunk
                                              ▼
                                  ┌───────────────────────────┐
                                  │  ACTION MAPPER + SAFETY    │
                                  │  - action_space → JACO cmd │
                                  │  - clamps, workspace box   │
                                  │  - WATCHDOG (force stop)   │
                                  │  - Dry-run / Active mode   │
                                  └───────────┬───────────────┘
                                              │ ROS 2 command
                                              ▼
                                  ┌───────────────────────────┐
                                  │  ros1_bridge  (2→1)        │
                                  └───────────┬───────────────┘
                                              ▼
                                  ┌───────────────────────────┐
                                  │ ROS 1 kinova-ros driver    │──► JACO2 USB
                                  └───────────────────────────┘
```

Also present: a **recorder/evaluator** node that taps cameras, state, commands, and logs
episodes (for data collection and for replay-based validation).

## 2. Process / deployment topology (single machine)

| Process | Language | Role |
|---------|----------|------|
| `realsense2_camera` ×N | C++ (ROS 2) | one node per camera (or one node, multi-camera) |
| `policy_client` | Python (rclpy) | orchestrates observations → VLA → actions |
| `vla_server` | Python (PyTorch) | model load + inference (own env) |
| `safety_supervisor` | Python (rclpy) | watchdog, clamps, mode state machine, e-stop |
| `kinova_arm_driver` (ROS 1) | C++ | existing |
| `dynamic_bridge` (ros1_bridge) | C++ | existing |
| `recorder` | Python | episode capture (optional, can be merged) |

The ROS 2 side and the VLA server share the GPU box. Keep the model in its own process and
env so a model crash can't take down robot I/O.

## 3. Control loop, rates, and latency budget

Typical VLA control is **not** a tight 1 kHz loop; it is a slow policy loop with a fast
safety/actuation layer underneath.

| Stage | Rate | Budget |
|-------|------|--------|
| Camera capture (per camera) | 30 Hz | — |
| Observation assembly | 10–30 Hz | ≤ 20 ms |
| VLA inference | 2–10 Hz (chunked) | ≤ 250 ms per chunk |
| Action chunk execution | 20–50 Hz | — |
| Safety supervisor | ≥ 50 Hz | ≤ 5 ms |
| Command → bridge → driver | — | ≤ 100 ms |

**Action chunking:** predict N steps (e.g. 8–16), execute them at the execution rate, then
re-infer. This hides inference latency and keeps motion smooth. The safety supervisor runs
*under* the chunk loop and can stop the arm mid-chunk.

**Target end-to-end:** ≥ 2 Hz effective policy rate, ≤ 100 ms actuation latency.

## 4. Interfaces (to be finalized in M2/M3)

- **Camera (ROS 2):** `sensor_msgs/Image` (`/camN/color/image_raw`), `sensor_msgs/Image`
  (`/camN/aligned_depth_to_color/image_raw`), `sensor_msgs/CameraInfo`, `tf`.
- **State (ROS 2):** `sensor_msgs/JointState` from the bridge.
- **VLA server:** local transport — HTTP+JSON or ZeroMQ with msgpack/numpy payloads
  (images as encoded JPEG/PNG or raw). Contract:
  `infer(images[], instruction, state?) -> actions[K, action_dim] + metadata`.
- **Arm command (ROS 2 → bridge):** one of (see doc 05):
  `/j2s6s300_driver/in/joint_velocity`, `/j2s6s300_driver/trajectory_controller/command`,
  or the Cartesian-services path.
- **Mode control:** `/<node>/set_mode` (idle / dry_run / active), plus a physical **e-stop**
  that is always authoritative.

## 5. Mode state machine (safety-critical)

```
        ┌────────┐   arm_ok      ┌──────────┐   enable     ┌────────┐
        │  INIT  │──────────────►│  IDLE    │─────────────►│DRY_RUN │
        └───┬────┘               └────┬─────┘              └───┬────┘
            │ fault                   │ estop                   │ arm
            ▼                         ▼                         ▼
        ┌────────┐  reset          ┌────────┐               ┌────────┐
        │ FAULT  │◄────────────────│ ESTOP  │◄──────────────│ ACTIVE │
        └────────┘                 └────────┘  estop/watch  └────────┘
```

- **IDLE** — cameras/policy may run; nothing is published to the arm.
- **DRY_RUN** — actions computed and logged, compared to ground truth, **not sent**.
- **ACTIVE** — actions sent, subject to clamps + watchdog.
- **ESTOP / FAULT** — immediately publish zero velocity; require explicit reset.

Every transition is logged with a timestamp and reason.

## 6. Logging & replay

One episode = a directory with per-step records:

```
episodes/<task>/<uuid>/
  meta.json          # instruction, camera set, rates, model, git hash, config
  images/            # (or a single .mp4/rosbag) color+depth per step
  states.parquet     # joint positions/velocities, eef pose, timestamps
  actions.parquet    # model actions, mapped commands, mode, safety events
  result.json        # success/failure, duration, operator notes
```

This backs both **data collection** (doc 06) and **validation** (doc 07): any run can be
replayed in shadow mode to reproduce the policy output.
