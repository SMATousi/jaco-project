# 08 — Risks, Decisions & Open Questions

## 1. Risk register

| # | Risk | L | Impact | Mitigation |
|---|------|---|--------|-----------|
| R1 | **Arm driver crash / instability** — *observed*: `kinova_arm_driver` SIGSEGV'd while idle after a USB hiccup (`KinovaCommException 1015`) | M | High | health-monitor node; auto `scripts/jaco restart` on fault; safety supervisor stops the arm on lost feedback; keep the arm stack separate from policy code; report upstream |
| R2 | **Storage exhaustion** — **8.5 GB free** on `/` after the M2 env + SmolVLA weights (was 22 GB) | H | High | **resolve D4 now** (`/dev/sda` 2.7 TB): no room for OpenVLA-7B, datasets, or rollouts on `/`; SmolVLA inference still fits; monitor every download |
| R3 | **USB bandwidth** — 3 of 7 cameras on a USB 2 hub | M | Med | use 2–3 cameras, prefer USB-3; lower res/FPS; re-cable if needed |
| R4 | **RealSense ↔ ROS 2 Jazzy install friction** | M | Med | use APT `ros-jazzy-realsense2-camera`; pin version; fall back to source build |
| R5 | **Embodiment gap** — JACO2 not a VLA training robot → poor zero-shot | H | High | treat zero-shot as a baseline only; plan LoRA fine-tuning (M6) |
| R6 | **Action mapping / IK error** | M | High | start with velocity control; validate step response; add bounded-trajectory mode with clamps; calibrate extrinsics |
| R7 | **No stock watchdog** | H | High | the safety supervisor is mandatory (M3) and gates all motion |
| R8 | **Gripper not bridged** (action only) | M | Med | small ROS 1 relay node (doc 05 §1a) |
| R9 | **Fine-tune won't fit 24 GB** | M | Med | LoRA + grad checkpointing + batch 1; drop to SmolVLA/GR00T if needed |
| R10 | **Env conflicts (conda vs system py)** | M | Med | strict split: ROS nodes on system py3.12, model in its own conda env, talk over IPC |
| R11 | **Model downloads / network** | L | Low | HF reachable; cache models on the data disk |
| R12 | **Latency too high for smooth control** | M | Med | action chunking; measure p50/p95; reduce model/size if needed |
| R13 | **Safety incident during hardware tests** | L | Critical | e-stop in hand, small caps, DRY_RUN first, one operator |
| R14 | **Calibration drift / mounting changes** | M | Med | rigidly mount cameras; re-run M1 gate after any move |
| R15 | **Incus USB passthrough is pinned to device numbers** — *observed*: the arm re-enumerated devnum 24→26 and the container had no node, so the driver saw "0 attached devices" | H | High | host must refresh the Incus `kinova` device (or replug the arm); durable fix is a device that follows the device (`usb`/`unix-hotplug`); documented in `spec/validation/M0_environment.md` |
| R16 | **Incus video-node passthrough is pinned (`video0-41`)** — *observed*: camera `2-2.1` re-enumerated to `video42-47`, outside the passthrough | M | High | use `cam0`/`cam1` on `2-2.2`/`2-2.4`; stop nodes cleanly via `scripts/20_cameras.sh`; host should pass the UVC devices dynamically |

## 2. Decisions needed from you

| # | Decision | Options | Recommendation | Decision |
|---|----------|---------|----------------| -------- |
| **D1** | Model + order | SmolVLA-first → OpenVLA; OpenVLA-first; π0/GR00T | **SmolVLA-first**, then **OpenVLA-7B (+LoRA)** | Recommendation approved | 
| **D2** | First task | tabletop pick-place; button press; drawer; handover | **tabletop pick-and-place** (2–3 blocks + tray) | Recommendation approved | 
| **D3** | Cameras | 2 / 3 / all 7; which views | **2–3**: 1–2 static workspace + (if available) wrist; prefer USB-3 | 1-2 static (without wrist for the first draft) |
| **D4** | Storage | format/mount `/dev/sda` (2.7 TB) as `/data`; free `/`; use `/dev/sdb` | **format & mount `/dev/sda`** (needs your OK — currently no filesystem) | Not decided yet |
| **D5** | Action interface | joint velocity; EEF velocity; bounded joint trajectory; + gripper relay | **velocity first**, add **bounded trajectory** after verifying the topic; add gripper relay | Recommendation approved | 
| **D6** | Teleop hardware | gamepad; SpaceMouse; keyboard | **gamepad** (tell me what you have) |  Recommendation approved (I have the Kinova joystick) | 
| **D7** | Scope | zero-shot only; + fine-tuning | **include fine-tuning** (needed for real success) | Recommendation approved | 
| **D8** | RealSense install | APT `realsense2-camera`; source build | **APT**, pinned | Recommendation approved | 

**Implementation status (2026-10-19):** D1 (SmolVLA-first), D2 (pick-and-place), D3 (1–2 static
views), D5 (velocity first), D6 (Kinova joystick), D7 (fine-tuning) and D8 (APT, pinned) are
approved and in progress. **D4 (storage) is still open** — `/dev/sda` has not been touched;
work continues within the ~22 GB free on `/`, and the 7 B model/downloads are deferred until
D4 is resolved.

## 3. Open questions

1. **Wrist camera?** None is mounted on the arm today. Is there a mount/bracket, or do we
   run fully from static views?
2. **Task objects & table** — do you have a defined workspace/table and object set, or should
   I propose one?
3. **Multi-view / 3D VLA?** Do you want to eventually evaluate spatial/multi-view models
   (which would use more cameras + depth), or keep to RGB 2-view?
4. **Do you have a data-collection target** (e.g. a paper, a demo, a class) that sets the
   task and the success bar?
5. **Is `/dev/sda` truly free?** `blkid` shows no filesystem, but I will not touch it without
   your explicit go-ahead.
6. **GPU sharing** — may the VLA server use the 3090 exclusively during training/eval, or do
   other jobs (e.g. the conda ML envs) share it?
7. **Arm stability** — given R1, do you want a **health-monitor + auto-restart** for the
   driver as part of M0, or keep restarts manual?

## 4. Immediate next actions (after you answer D1–D8)

1. Restart the arm stack and confirm it is healthy (currently the driver has crashed).
2. Resolve storage (D4).
3. Install RealSense; bring up the first camera (M0).
4. Create the `vla` env and stand up the SmolVLA inference server (M2 seed).

> Nothing in this spec changes the working arm stack or installs software until you approve
> and we begin M0.
