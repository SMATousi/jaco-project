# JACO2 Vision-Language-Action (VLA) — Specification

**Status:** Draft for review — **no implementation started.**
**Owner:** Ali Tousi
**Started:** 2026-10-19

---

## 1. What this is

A plan to run a **Vision-Language-Action** policy on the **Kinova JACO2 Gen2** arm using
the **7× Intel RealSense D435** cameras already attached to this machine, integrated with
the existing **ROS 2 Jazzy** stack (the arm is driven by the ROS 1 `kinova-ros` driver via
`ros1_bridge` — see the repo's top-level `README.md`).

In one line:

> **camera images + a natural-language instruction + robot state → VLA model → a safe,
> bounded action stream → JACO2 arm.**

This folder specifies *what* we will build, *how* each piece is validated, and *what
decisions you need to approve* before coding starts.

## 2. Documents

| # | Document | What it covers |
|---|----------|----------------|
| 00 | `README.md` (this file) | Index, ground truths, approval checklist |
| 01 | [`01_overview.md`](01_overview.md) | Goals, scope, first task, success criteria |
| 02 | [`02_architecture.md`](02_architecture.md) | Components, data flow, control loop, latency budget |
| 03 | [`03_environment.md`](03_environment.md) | Measured hardware/software inventory, install plan, storage |
| 04 | [`04_vla_model.md`](04_vla_model.md) | Model selection, inference server, fine-tuning strategy |
| 05 | [`05_robot_interface_and_safety.md`](05_robot_interface_and_safety.md) | Action interfaces, action-space mapping, safety layer |
| 06 | [`06_data_and_teleoperation.md`](06_data_and_teleoperation.md) | Teleoperation, demonstration capture, dataset format |
| 07 | [`07_roadmap_and_validation.md`](07_roadmap_and_validation.md) | Milestones M0–M7 with validation gates |
| 08 | [`08_risks_and_decisions.md`](08_risks_and_decisions.md) | Risk register + decisions needed from you |

## 3. Ground truths measured on this machine (2026-10-19)

These were verified directly, not assumed:

| Item | Finding |
|------|---------|
| Cameras | **7× Intel RealSense D435** (`8086:0b07`). 4 enumerate at **USB 3 (5 Gbps)**, **3 at USB 2 (480 Mbps)** — a bandwidth constraint (see 03). |
| Arm | Kinova JACO2 Gen2 present on USB (`22cd:0000`). |
| GPU | **NVIDIA RTX 3090, 24 GB**, driver 595.84. `torch ... cuda True` works in the existing conda envs. |
| CPU/RAM | i9-12900K (24 threads), 31 GB RAM. |
| Root disk | `/` = 893 GB, **only ~21 GB free (98% full)**. |
| Extra storage | `/dev/sda` **2.7 TB, unformatted/unmounted** (candidate for model/dataset storage — needs your confirmation before touching). |
| ROS 2 | Jazzy installed (287 pkgs) + **Realsense ROS 2 stack** (`ros-jazzy-realsense2-camera` 4.58.4, `librealsense2` 2.58.4). |
| ROS 1 + bridge | Working pipeline exists (`scripts/jaco`, `kinova_msgs` port, `jog.py`). |
| RealSense SDK | ✅ installed 2026-10-19 (APT, pinned); 6/7 cameras enumerate, `cam0` streams RGB-D. |
| Internet | huggingface.co reachable (HTTP 200). |

> ⚠️ **Current robot state:** the arm driver crashed during the 3-day gap, and on restart
> the Kinova **re-enumerated to USB devnum 26**. This is an **Incus container**, which passes
> USB nodes through by fixed device number, so the container has no `/dev/bus/usb/001/026` —
> the driver reports *"0 attached devices"*. **A host-side Incus device refresh (or a physical
> replug) is required**; it cannot be fixed from inside the container (`mknod` is blocked,
> sysfs `uevent` is read-only). Details and exact host commands:
> [`validation/M0_environment.md`](validation/M0_environment.md), risk **R15**.

## 4. Headline recommendation (for approval)

1. **Bring-up model first, fine-tuning second.** Stand up the *whole loop* with a small,
   fast VLA (**SmolVLA, ~450 M**) and a **dry-run (shadow) mode**, then move to **OpenVLA-7B
   with LoRA fine-tuning** once the pipeline and a small demonstration dataset exist.
2. **Start with 2–3 cameras**, not all 7 (bandwidth + VLA input is typically 1–3 views).
3. **Add a safety supervisor** around the arm (the stock driver has **no velocity watchdog**).
4. **Solve storage first** — 21 GB free will not hold a 7 B model + datasets.

## 5. Approval checklist

Please review and answer in `08_risks_and_decisions.md` (D1–D8). The blocking ones:

- **D1** Model choice / order (SmolVLA-first vs OpenVLA-first vs π0/GR00T).
- **D2** First task + environment (tabletop pick-and-place? something else?).
- **D3** Camera count & mounting (2–3 views? which?).
- **D4** Storage: may I format/mount `/dev/sda` (2.7 TB) for models/datasets?
- **D5** Action interface preference (joint position vs joint velocity vs EEF delta).
- **D6** Teleop hardware available (gamepad / SpaceMouse / keyboard?) for demos.
- **D7** Zero-shot only vs fine-tuning in scope.
- **D8** RealSense install path (APT `realsense2-camera` vs source build).

Once D1–D8 are settled, implementation starts at **M0** in `07_roadmap_and_validation.md`.

## 6. Implementation progress (live)

| Milestone | Status | Evidence |
|-----------|--------|----------|
| M0 — Environment + RealSense | 🟡 **partial** | RealSense installed; `cam0` (`2-2.2`, `935322072821`) streams color+depth ~27 Hz; `config/cameras.yaml` + `scripts/20_cameras.sh`. Arm **blocked** on Incus passthrough (R15). |
| M1 — Calibration & TF | ⬜ not started | needs arm feedback for base↔camera extrinsics |
| M2 — VLA inference server | ⬜ not started | pending D4 (storage) / M0 close |
| M3 — Mapper + safety | ⬜ not started | |
| M4 — Closed loop | ⬜ not started | |
| M5 — Dataset | ⬜ not started | |
| M6 — Fine-tune | ⬜ not started | |
| M7 — Evaluation | ⬜ not started | |

Step-by-step evidence lives in [`validation/`](validation/).
