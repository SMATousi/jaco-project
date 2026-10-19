# M0 — Environment & RealSense Bring-up — Validation Log

**Started:** 2026-10-19
**Operator:** agent (documented step by step)
**Status:** IN PROGRESS — RealSense streaming on `cam0`; **arm blocked on host-side Incus action**

---

## Step 1 — Restart the arm stack

**Why:** the `kinova_arm_driver` had crashed (SIGSEGV) during the 3-day idle gap
(see `spec/README.md` §3 and `spec/08_risks_and_decisions.md` R1).

**Command**

```bash
cd /root/jaco-project
bash scripts/jaco restart
```

**Result (2026-10-19 ~18:45 UTC)**

```
Stopping JACO bring-up ...
  bridge: stopped
  driver: stopped
  roscore: stopped
Starting JACO bring-up (robot type: j2s6s300) ...
  started roscore (pid 222646)
  started driver (pid 222709)
  started bridge (pid 222849)
  timeout waiting for ROS 2 topics (j2s6s300)
```

**Driver log**

```
[ERROR] Could not find the specified arm (serial: not_set) among the 0 attached devices
[ERROR] KinovaCommException: Could not find the specified arm (return code: 0)
[j2s6s300_driver-1] process has died [pid 222797, exit code -11, ...]
```

The process **starts but cannot open the arm**, then crashes in the same way as
before (`exit code -11`, SIGSEGV).

### Root cause — Incus USB passthrough is pinned to the old device number

The arm *is* enumerated on USB, but at a **new device number**:

| Check | Finding |
|-------|---------|
| `lsusb` equivalent (sysfs) | `22cd:0000 Kinova Robotic Platform` present at `1-7` |
| `cat /sys/bus/usb/devices/1-7/devnum` | **26** |
| `cat /sys/bus/usb/devices/1-7/dev` | `189:25` |
| `/dev/bus/usb/001/` | only `005`, `008`, `010`, `024` — **no `026`** |
| `/proc/self/mountinfo` | `/dev/bus/usb/001/024` is a bind mount from `/var/lib/incus/devices/Ubuntu24/unix.kinova.dev-bus-usb-001-024` |
| Incus agent `/1.0/devices` | `"kinova": {"type":"usb","vendorid":"22cd","productid":"0000"}` |

So: the arm re-enumerated from devnum 24 → 26 after the driver crash, but the
container only has a node for **24**. The host-side Incus device handler did not
refresh the bind mount (the re-enumeration happened while the container was idle
over the weekend).

**Why it cannot be fixed from inside the container**

| Attempt | Result |
|---------|--------|
| `mknod /dev/bus/usb/001/026 c 189 25` | `Operation not permitted` (no effective CAP_MKNOD for the host-owned `/dev` tmpfs; user-namespace restriction) |
| bind-mount a node created elsewhere | `mknod` fails everywhere (`/tmp` too) |
| `echo change > /sys/bus/usb/devices/1-7/uevent` | `Permission denied` |
| Incus management socket `/var/lib/incus/unix.socket` | not present inside the container |
| `/dev/incus/sock` | Incus **agent** API — read-only device listing, no config mutation |

The container's `/dev` tmpfs is host-mounted (`uid=1000000`), and the device
cgroup allow-list is managed by the host, so a new device node must be created
by the host/Incus.

### Required resolution (host side)

On the **host** (where Incus runs), any one of:

1. **Re-apply the Incus USB device** so the node is re-created at the current
   address (preferred, no container restart):
   ```bash
   incus config device list Ubuntu24
   incus config device remove Ubuntu24 kinova
   incus config device add Ubuntu24 kinova usb vendorid=22cd productid=0000
   ```
   (If the installed Incus prefers `unix-hotplug` for containers, use
   `incus config device add Ubuntu24 kinova unix-hotplug vendorid=22cd productid=0000`.)

2. **Physically unplug/replug the arm's USB cable** (or power-cycle the arm) so a
   fresh udev hotplug event lets the host handler mount the new node.

3. Restart the container (last resort — this also terminates the current session).

**After the host action**, verify inside the container:

```bash
ls -l /dev/bus/usb/001/        # node matching /sys/bus/usb/devices/1-7/devnum
cd /root/jaco-project && bash scripts/jaco restart
bash scripts/jaco verify
```

> Robustness note: because Incus device numbers change on every re-enumeration,
> the host device should be configured so it follows the device
> (`usb`/`unix-hotplug`), not pinned to a single `/dev/bus/usb/BBB/DDD` path.
> This is now **R15** in `spec/08_risks_and_decisions.md`.

---

## Step 2 — RealSense packages (D8 = APT, pinned)

**Command**

```bash
apt-get install -y ros-jazzy-realsense2-camera
```

**Installed**

| Package | Version |
|---------|---------|
| `ros-jazzy-librealsense2` | `2.58.4-1noble.20260831.015923` |
| `ros-jazzy-realsense2-camera` | `4.58.4-1noble.20260920.235447` |
| `ros-jazzy-realsense2-camera-msgs` | `4.58.4-1noble.20260911.141016` |
| `ros-jazzy-diagnostic-updater` | `4.2.7-1noble.20260912.163704` |

Notes:
- CLI tools (`rs-enumerate-devices`, `rs-capture`, `rs-fw-update`, …) install to
  `/opt/ros/jazzy/bin/`; the library lives in `/opt/ros/jazzy/lib/x86_64-linux-gnu/`
  (already on `LD_LIBRARY_PATH` after `source /opt/ros/jazzy/setup.bash`).
- Disk after install: **22 GB free** on `/` (unchanged).

## Step 3 — Camera enumeration

**Result: 6 of 7 cameras create successfully; one (`2-2.3`) fails.**

```
ERROR set_xu(...). xioctl(UVCIOC_CTRL_QUERY) failed on control 1 Last Error: No such file or directory
ERROR [rs2_create_device(index:5)] Backend ...
Could not create device - set_xu(...) ...
```

**Serial ↔ USB port map** (SDK serial — use this for `serial_no`):

| SDK serial | USB port | Speed | Status |
|-----------|----------|-------|--------|
| `014122071597` | `1-9.1` | 480 Mbps (USB 2) | OK |
| `934222072312` | `1-9.2` | 480 Mbps (USB 2) | OK |
| `021222072467` | `1-9.3` | 480 Mbps (USB 2) | OK |
| `937622070994` | `2-2.1` | 5 Gbps (USB 3) | **OK — `cam0`** |
| `935322072821` | `2-2.2` | 5 Gbps (USB 3) | OK |
| `935422072205` | `2-2.4` | 5 Gbps (USB 3) | OK |
| *(unresolved)* | `2-2.3` | 5 Gbps (USB 3) | **FAILS to create** |

Notes:
- The USB **iSerial** in sysfs (e.g. `939323025552`) is the **ASIC serial**, and differs
  from the SDK serial. Always select cameras by the SDK serial printed above.
- The `2-2.3` failure is an XU-control error at device creation. Candidate causes: device in
  a bad state after the long idle (USB reset / replug may fix it), or a firmware/control
  mismatch. It is **not** needed for the first draft (D3 = 1–2 cameras), so it is recorded
  and deferred; re-test after the next USB replug.
- This also confirms R3: the three `1-9.x` cameras are USB 2 (480 Mbps) and should not be
  used for simultaneous high-rate color+depth.

## Step 4 — First camera (`cam0`) streaming

**Command** (background, system ROS 2, infra streams disabled):

```bash
ros2 run realsense2_camera realsense2_camera_node \
  --ros-args -r __ns:=/cam0 -r __node:=camera \
  -p "serial_no:='937622070994'" \
  -p enable_color:=true -p enable_depth:=true \
  -p enable_infra1:=false -p enable_infra2:=false \
  -p align_depth.enable:=true -p pointcloud.enable:=false \
  -p rgb_camera.color_profile:=640x480x30 \
  -p depth_module.depth_profile:=640x480x30
```

**Result**

| Topic | Measured rate (Python subscriber) | Notes |
|-------|-----------------------------------|-------|
| `/cam0/camera/color/image_raw` | ~22 Hz | configured 30 Hz |
| `/cam0/camera/depth/image_rect_raw` | ~20 Hz | configured 30 Hz |
| `/cam0/camera/aligned_depth_to_color/image_raw` | ~12.7 Hz | alignment cost |

- **No `Frames didn't arrive` warnings** after disabling `infra1`/`infra2`
  (they appeared with the default IR streams enabled).
- Measured rates are limited by the Python `ros2 topic hz` subscriber, not the driver;
  a C++/`image_transport` consumer (and the VLA client) will be benchmarked in M2.
- A color frame was saved via `scripts/grab_frame.py` and **visually verified**: the JACO2
  arm, the table, and the room are clearly visible. Depth frame saved as `16UC1`
  (mean ~984 mm-raw units).

**Python caveat:** `serial_no` must be passed as a **string** in `--ros-args`
(`-p "serial_no:='937622070994'"`); a bare number is parsed as an integer and rejected.

## Step 5 — Video-node shift (Incus) and final `cam0`

While stopping the first test node, the camera on **2-2.1** re-enumerated (librealsense
performs a hardware reset on shutdown). Its UVC video nodes moved **`video36-41` →
`video42-47`**.

Because Incus passes video nodes into the container by **fixed path**
(`/dev/video0 .. /dev/video41`), the new nodes were not present in the container and the
node failed with:

```
map_device_descriptor Cannot open '/dev/video36' ... No such file or directory
Error starting device: map_device_descriptor Cannot open '/dev/video36'
```

A leftover child process from the manual test also still held the device; it was cleaned up
with `pkill -f realsense2_camera_node`.

**Full camera map after the incident** (sysfs):

| Port | Video nodes | Passed to container? | SDK serial | Use |
|------|-------------|----------------------|-----------|-----|
| `2-2.1` | `video42-47` | **NO** | `937622070994` | blocked (host fix needed) |
| `2-2.2` | `video6-11` | yes | `935322072821` | **`cam0` (primary)** |
| `2-2.3` | `video0-5` | yes | — | fails to create (XU control) |
| `2-2.4` | `video30-35` | yes | `935422072205` | `cam1` (second view) |
| `1-9.1` | `video12-17` | yes | `014122071597` | `cam2` (USB 2 spare) |
| `1-9.2` | `video18-23` | yes | `934222072312` | spare (USB 2) |
| `1-9.3` | `video24-29` | yes | `021222072467` | spare (USB 2) |

**Final `cam0` = port `2-2.2`, serial `935322072821`.** Restarted via the new helper:

```bash
bash scripts/20_cameras.sh start cam0     # -> logs/cam0.log, logs/cam0.pid
bash scripts/20_cameras.sh status
```

**Verification**

| Check | Result |
|-------|--------|
| `/cam0/camera/color/image_raw` | **~27.4 Hz**, no `Frames didn't arrive` warnings |
| Color frame | saved, mean 110.0, **visually verified** (arm + Kinova joystick + table) |
| Aligned depth frame | saved, `16UC1`, mean 962.2 |
| `logs/cam0.log` | no errors, "RealSense Node Is Up!" |

**Lesson:** always use `scripts/20_cameras.sh` (clean start/stop). Abruptly killing a node can
trigger a hardware reset → re-enumeration → video-node shift. This is recorded as **R16**
and needs a host-side passthrough fix to be robust (same class as the arm's R15).

## M0 gate status

| Gate item | Status |
|-----------|--------|
| RealSense stack installed (APT, pinned) | ✅ |
| Camera streams RGB-D at target rate, no underruns | ✅ `cam0` (`2-2.2`, ~27 Hz observed via Python subscriber) |
| Stable camera names by serial | ✅ `config/cameras.yaml` + `scripts/20_cameras.sh` |
| ≥ 10 min continuous run | ⏳ to run |
| Arm stack healthy | ❌ **blocked — host must refresh the Incus Kinova USB device (R15)** |
| 6/7 cameras usable | ✅ (7th = 2-2.1 needs host fix; 2-2.3 fails to instantiate) |


