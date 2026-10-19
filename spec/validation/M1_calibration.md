# M1 — Calibration & TF (validation log)

**Status:** 🔴 **BLOCKED on a host-side Incus USB refresh** (arm + cameras), then re-run.
No motion is being commanded while blocked.

**Goal:** publish a validated `j2s6s300_link_base ↔ cam0_link` extrinsic and store the
per-serial intrinsics, so a table point maps consistently into the arm base frame.

---

## Step 1 — read-only TF / intrinsics audit (done)

The arm and camera drivers were briefly healthy.  Findings:

### Arm TF tree

```
world
└── root
    └── j2s6s300_link_base          (root of the arm kinematics)
        └── j2s6s300_link_1
            └── j2s6s300_link_2
                └── j2s6s300_link_3
                    └── j2s6s300_link_4
                        └── j2s6s300_link_5
                            └── j2s6s300_link_6
                                ├── j2s6s300_link_finger_1 → ..._tip_1
                                ├── j2s6s300_link_finger_2 → ..._tip_2
                                ├── j2s6s300_link_finger_3 → ..._tip_3
                                └── j2s6s300_end_effector   (static)
```

`j2s6s300_link_base` is the calibration parent; `j2s6s300_link_6` is the gripper
frame used for hand-eye (the marker offset is absorbed by the solve).

### Camera TF tree (before the frame-name cleanup)

```
camera_link
├── camera_depth_frame → camera_depth_optical_frame
└── camera_color_frame → camera_color_optical_frame
```

`camera_link` had **no parent** — the base ↔ camera extrinsic is the missing edge.
`scripts/20_cameras.sh` was changed to pass `-p camera_name:=$name`, so the next
start publishes `cam0_link`, `cam0_color_frame`, `cam0_color_optical_frame`, …
Topics stay under `/cam0/camera/...` (the `camera_name` parameter only changes
frame IDs; the namespace is set by `__ns:=/cam0`).

### Colour intrinsics (`/cam0/camera/color/camera_info`)

| parameter | value |
|-----------|-------|
| size | 640 × 480 |
| fx | 604.023 px |
| fy | 602.751 px |
| cx | 309.191 px |
| cy | 237.923 px |
| distortion model | `plumb_bob` |
| D | `[0, 0, 0, 0, 0]` |
| frame_id | `camera_color_optical_frame` |

These are driver-provided and will be stored per serial in the calibration YAML
(the capture samples already embed K and D).

### Joint limits (from `j2s6s300.xacro`)

| joint | type | limits (deg) | velocity limit |
|-------|------|--------------|----------------|
| 1 | continuous | ±360 | 36 °/s |
| 2 | revolute | 47 … 313 | 36 °/s |
| 3 | revolute | 19 … 341 | 36 °/s |
| 4 | continuous | ±360 | 48 °/s |
| 5 | revolute | 30 … 330 | 48 °/s |
| 6 | continuous | ±360 | 48 °/s |

`handeye_move.py` uses a **5° margin** on the revolute joints and caps each move
at `--max-delta` (45° in the orchestrator).

### Tooling available

- system Python 3.12, OpenCV **4.6.0**: `aruco`, `calibrateHandEye`, `solvePnP`,
  `findChessboardCorners` all present.
- `tf2_ros` (`spin_thread=False`, spun manually).
- ROS 1 `ArmJointAngles` action (`kinova_msgs/ArmJointAnglesAction`): smooth,
  driver-managed, 2° tolerance, stall detection, speed limits 20 °/s.
- Driver `/in/stop` service; **no velocity watchdog** (R6).

---

## Step 2 — camera view problem (needs a physical fix)

A frame at the recovered arm pose (`logs/handeye/scene_before.png`) shows:

- the Kinova base and joystick at the bottom of the frame;
- the arm going **up and out of the top edge** — the gripper is not visible;
- the table surface is only a thin strip at the very bottom (the camera is close
  and looking almost horizontally at the wall).

A RANSAC plane fit on that bottom strip gives a plane **0.116 m** from the camera
with its normal almost perpendicular to the optical axis, i.e. the strip is the
near table edge / camera mount, not the workspace.

**Required physical fix:** move `cam0` back (~1.0–1.5 m from the arm base) and
tilt it **down** so the table area in front of the arm fills the lower/central
frame.  Then move the arm to a low “ready” pose so the gripper (and the marker)
is inside the view.  The camera must not move after calibration.

---

## Step 3 — USB re-enumeration incident (2026-10-19 ~21:17–21:20)

While adding the `camera_name:=cam0` parameter, `cam0` was stopped and restarted.
That USB event propagated to the host, the container's USB sysfs lost **all**
device entries, and the arm driver died:

```
[WARN] destruction entered!
terminate called after throwing an instance of 'kinova::KinovaCommException'
  what():  KinovaCommException: Could not get the angular command (return code: 1015)
[j2s6s300_driver-1] process has died [pid 230957, exit code -6, ...]
```

Observed state afterwards:

| check | result |
|-------|--------|
| `/sys/bus/usb/devices/` | only `usb1`, `usb2`, `1-0:1.0`, `2-0:1.0` — **no `1-7` (arm), no `2-2.x` (cameras)** |
| `/sys/class/video4linux/` | **empty** (the `/dev/video*` nodes are stale bind mounts) |
| `/dev/bus/usb/001/026` | present but stale (no sysfs backing) |
| arm driver | **dead** (`KinovaCommException` 1015) |
| motion commanded during the incident | **none** |
| stack | stopped cleanly (`scripts/jaco stop`); no arm process left |

This is the same Incus pinned-passthrough failure as R15/R16, now affecting the
**arm and all cameras at once**.  The host must refresh the USB devices before
anything can be restarted.  Do **not** restart a camera node while the arm is
active until the passthrough is made stable.

---

## Step 4 — calibration tooling (written; ready to run)

| file | purpose |
|------|---------|
| `scripts/make_aruco_marker.py` | regenerate `calibration/aruco_4x4_50_id0.png` |
| `calibration/aruco_4x4_50_id0.png` | printable marker, `DICT_4X4_50`, id 0, 300 dpi, nominal 50.8 mm black edge |
| `calibration/README.md` | print/attach instructions and the acceptance gate |
| `scripts/handeye_move.py` | ROS 1 action-based pose move; limits, stop-on-timeout, JSON output |
| `scripts/handeye_capture.py` | ROS 2 image + ArUco + FK capture; JSON sample + debug image |
| `scripts/handeye_solve.py` | eye-to-hand `calibrateHandEye` (all 5 methods) + residual/reprojection validation |
| `scripts/handeye_run.py` | orchestrator: preview → (move → settle → capture → return) × N → solve |
| `scripts/62_calibration_tf.sh` | publish/stop/status the calibrated static TF |
| `config/handeye_poses.txt` | 12 wrist-only deltas (±35°) around the seed |

USB preflight guards were added after the incident:

- `scripts/jaco start` refuses to start unless the arm (`22cd:0000`) is present in
  `/sys/bus/usb/devices`; it no longer launches a driver into a dead bus.
- `scripts/20_cameras.sh start` refuses if the camera's USB port is absent from the
  container sysfs **or** if any process already holds that serial.  `stop` now also
  kills by serial, so a stale PID file can no longer leave a child holding the
  device while a second node is started (the R17 trigger).

### Solve convention

Fixed camera, marker on the gripper.  With
`A = T_base_gripper⁻¹` (base→gripper), `B = T_target_cam` (target→camera):

```
cv2.calibrateHandEye(A, B) -> X = T_cam_optical_base
C = A X B                  (target→gripper, must be constant)
```

Acceptance (M1 draft): marker-position RMS in the base frame **≤ 20 mm** and
corner reprojection RMS **≤ 3 px**; a rejected result is written as
`base_cam0.rejected.yaml`.

### Planned command sequence (after the host refresh)

```bash
# 1. arm + camera back, then:
bash scripts/jaco restart && bash scripts/jaco verify
bash scripts/20_cameras.sh start cam0
python3 scripts/grab_frame.py /cam0/camera/color/image_raw logs/handeye/scene_after.png 10

# 2. reposition cam0 (back + tilt down) and attach the printed marker to the gripper
#    measure the black square edge, e.g. 0.0508 m

# 3. marker visible at the current pose? no motion:
python3 scripts/handeye_run.py --marker-size 0.0508 --dry-run

# 4. full run (e-stop in hand):
python3 scripts/handeye_run.py --marker-size 0.0508 --yes

# 5. publish the base -> cam0_link TF:
bash scripts/62_calibration_tf.sh start
```

The first motion is only sent after the preview capture finds the marker at the
seed pose; every move is a wrist-only ±35° action and the arm returns to the
seed after each capture.

---

## Blocked on (next actions)

1. **Host:** refresh the Incus USB passthrough for the **arm** (`22cd:0000`) and the
   **cameras** (`8086:0b07`), or physically replug them; then confirm
   `/sys/bus/usb/devices/1-7` and the `2-2.x` video nodes are back.
2. **Container:** restart the arm stack, verify joint feedback, start `cam0`, confirm
   `cam0_*` frames.
3. **Physical:** reposition `cam0` (back + tilt down), print/attach the ArUco marker,
   measure its edge.
4. Run the dry-run, then the full hand-eye run; publish and validate the TF.

Risks: R15 (arm passthrough), R16 (camera passthrough), **R17 (camera restart can
re-enumerate the USB bus and kill the arm driver)**.
