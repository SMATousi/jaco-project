# 03 — Environment: Hardware, Software, Storage, Install Plan

All numbers below were **measured on 2026-10-19**, not assumed.

## 1. Hardware inventory

| Component | Detail |
|-----------|--------|
| Arm | Kinova **JACO2 Gen2**, 6 DOF, 3-finger (`j2s6s300`), USB `22cd:0000` |
| Cameras | **7× Intel RealSense D435** (`8086:0b07`); serial↔port map measured in M0 (see 1b) |
| GPU | **NVIDIA RTX 3090, 24 GB GDDR6X**, driver 595.84, `/dev/nvidia*` present |
| CPU | Intel i9-12900K (24 threads) |
| RAM | 31 GiB (~29 GiB available at idle) |
| Storage | `/` (nvme0n1p3) 893 GB, **22 GB free (98 % full)**; `/dev/sda` **2.7 TB unformatted/unmounted**; `/dev/sdb` 74.5 GB (two small partitions, FS unknown) |
| Runtime | **Incus container** (`Ubuntu24`); USB devices are passed through individually — see 1c |

### 1a. USB topology & camera bandwidth (important)

| Bus | Speed | Cameras | Implication |
|-----|-------|---------|-------------|
| USB 2 | **480 Mbps** | 3 | Cannot stream 640×480 depth+color at 30 FPS alongside others; drop to lower res/FPS or move off this hub |
| USB 3 | **5 Gbps** | 4 | Comfortable for 848×480 @ 30 FPS color+depth |

D435 at 640×480@30 (depth) + 640×480@30 (color) ≈ **~180–300 Mbps per camera** raw. So the
USB2 trio is the constraint. **Plan: use 2–3 cameras for the VLA; prefer USB3-attached ones
until we re-cable the USB2 group.**

### 1b. Measured camera inventory (M0, 2026-10-19)

Select cameras by the **RealSense SDK serial** (`rs-enumerate-devices -s`); the sysfs
`iSerial` is the **ASIC serial** and differs.

| SDK serial | Port | Speed | Video nodes | Status |
|-----------|------|-------|-------------|--------|
| `935322072821` | `2-2.2` | USB 3 (5 Gbps) | `video6-11` | ✅ **`cam0` (primary)** |
| `935422072205` | `2-2.4` | USB 3 | `video30-35` | ✅ `cam1` (second view) |
| `014122071597` | `1-9.1` | USB 2 | `video12-17` | ✅ `cam2` (spare) |
| `934222072312` | `1-9.2` | USB 2 | `video18-23` | ✅ spare |
| `021222072467` | `1-9.3` | USB 2 | `video24-29` | ✅ spare |
| `937622070994` | `2-2.1` | USB 3 | `video42-47` | ⛔ nodes outside container passthrough |
| — | `2-2.3` | USB 3 | `video0-5` | ⛔ fails to create (`set_xu`, XU control 1) |

Installed stack (APT, pinned): `ros-jazzy-librealsense2 2.58.4`, `ros-jazzy-realsense2-camera
4.58.4`, `ros-jazzy-realsense2-camera-msgs 4.58.4`. Tools are in `/opt/ros/jazzy/bin/`
(`rs-enumerate-devices`, `rs-capture`, …).

Camera control: `config/cameras.yaml` + `scripts/20_cameras.sh {start|stop|status}`.

### 1c. Incus USB passthrough constraint (important)

This machine runs inside an **Incus container**. USB passthrough is per-item:

- `/dev/bus/usb/BBB/DDD` and `/dev/videoN` are **bind-mounted by fixed path** from the host.
- When a device **re-enumerates**, its device/video number changes, and the old path vanishes
  from the container. The host must refresh the passthrough.

Observed twice in M0:

| Device | Before | After | Effect |
|--------|--------|-------|--------|
| Kinova arm | devnum 24 | devnum 26 | no `/dev/bus/usb/001/026` → driver sees "0 attached devices" |
| RealSense `2-2.1` | `video36-41` | `video42-47` | new nodes not in container → camera unusable |

Workarounds until the host is reconfigured: use devices whose numbers are still passed
(`cam0`/`cam1` on `2-2.2`/`2-2.4`), and **stop nodes cleanly** (`scripts/20_cameras.sh`) to
avoid triggering resets. The durable fix is host-side: make the Kinova + `0b07` USB/video
devices follow the device (e.g. `unix-hotplug`) instead of fixed paths. See
`spec/validation/M0_environment.md` and risks **R15/R16**.

## 2. Software already present

| Layer | Status |
|-------|--------|
| ROS 2 Jazzy (host, system Python 3.12) | ✅ installed (287 packages) |
| ROS 1 Noetic + `kinova-ros` + `ros1_bridge`, `kinova_msgs` port | ✅ working (see repo README) |
| Arm control helpers | ✅ `scripts/jaco`, `scripts/jog.py` |
| RealSense | ✅ `ros-jazzy-librealsense2 2.58.4` + `ros-jazzy-realsense2-camera 4.58.4` (installed 2026-10-19) |
| CUDA-capable PyTorch | ✅ in conda envs `qem-deep-learning` (py3.14, torch 2.13+cu126) and `blackwater` (py3.10, torch 2.13+cu130), `cuda True` |
| conda | ✅ `/root/miniconda3` (base py3.14) |
| colcon / rosdep | ✅ |
| Internet | ✅ (huggingface.co reachable) |

## 3. Missing pieces to install

| # | Item | Plan |
|---|------|------|
| 1 | ~~RealSense SDK~~ | ✅ installed 2026-10-19 (`ros-jazzy-librealsense2 2.58.4`) |
| 2 | ~~realsense-ros~~ | ✅ installed 2026-10-19 (`ros-jazzy-realsense2-camera 4.58.4`) |
| 3 | **VLA Python env** | New dedicated conda env `vla` (Py 3.10 or 3.11), torch matching CUDA, `transformers`, etc. |
| 4 | **Camera tooling** | `v4l-utils` (optional diagnostics); `cv-bridge`/`image-transport` already present |
| 5 | **Calibration tools** | camera intrinsics come from RealSense; extrinsics via `ros2 run tf2_ros` / hand-eye later |
| 6 | **ZeroMQ or HTTP stack** | for policy_client ↔ vla_server |

### 3a. Python environment strategy (avoid the classic clash)

- **ROS 2 nodes (`policy_client`, `safety_supervisor`, `recorder`) run on the system Python
  3.12** with `rclpy` — this is the only interpreter with working `rclpy` here.
- **The VLA server runs in its own conda env** (Py 3.10/3.11, PyTorch).
- They talk over **HTTP or ZeroMQ**, never by importing each other's Python. This keeps a
  model crash or a CUDA OOM from taking down robot I/O, and avoids `rclpy`/`torch` ABI
  conflicts.

## 4. Storage plan (blocking issue)

21 GB free on `/` will not hold a 7 B VLA (≈15 GB) + tokenizer/cache + datasets + episode
logs. Options, in order of preference:

| Option | Pros | Cons |
|--------|------|------|
| **A. Format & mount `/dev/sda` (2.7 TB)** as `/data` | plenty of room; clean separation | destructive if the disk holds data — **needs D4 approval**; `blkid` shows *no filesystem* |
| B. Free space on `/` | no new mount | 813 GB used by other projects (conda envs, other datasets) — risky to touch |
| C. Use `/dev/sdb` partitions (25.6 GB / 9.5 GB) | smaller blast radius | still tight for 7 B models; FS unknown |

**Recommendation:** Option A, after you confirm `/dev/sda` is expendable. Model cache
(`HF_HOME`) and episodes would live under `/data`. Until then, we can prototype with the
**450 M SmolVLA** (< 2 GB) to avoid the blocker.

## 5. Camera bring-up plan (details in M0/M1)

1. Install librealsense + `realsense2_camera`.
2. Enumerate devices by **serial**; assign stable names (`cam0..camN`) via launch config.
3. Bring up **one** camera, verify color+depth+camera_info at 30 FPS and `TF` frames.
4. Add cameras one at a time, watching for USB bandwidth errors (`dmesg` UVC underruns).
5. Decide final N (2–3) and pin resolution/FPS.
6. udev/permissions: RealSense uses UVC; add the recommended udev rules for non-root access
   (the ROS 1 arm already has `10-kinova-arm.rules`).

## 6. Network / remote

- Everything is local; no cloud inference (privacy + latency).
- HF downloads only for initial model weights (over the existing internet path).

## 7. Reproducibility notes

- Pin every version: `librealsense2`, `realsense2_camera`, torch/CUDA, model revision hash.
- Record the git commit + config hash in each episode's `meta.json`.
- Keep the model in a **separate env** from ROS so upgrades don't couple.
