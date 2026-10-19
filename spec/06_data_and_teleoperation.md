# 06 — Data Collection & Teleoperation

Fine-tuning a VLA needs **demonstrations**. This document defines how we collect them so
the data is directly usable by LeRobot / OpenVLA / GR00T training pipelines.

## 1. Teleoperation options for the JACO2

| Option | How | Pros | Cons |
|--------|-----|------|------|
| **A. Gamepad / joystick** (recommended) | ROS 2 node maps axes → joint/Cartesian velocity → `in/joint_velocity` | intuitive, hands-on, cheap | needs a pad |
| **B. SpaceMouse** | 6-DoF twist → EEF velocity | natural for EEF tasks; matches VLA action space | needs a SpaceMouse + driver |
| **C. Keyboard** | key-to-velocity, coarse | zero hardware | jerky, slow to demonstrate |
| **D. Scripted/kinesthetic** | hand-guide or pre-recorded trajectories | no hardware | not general |
| **E. Leader-follower** | second arm mirrors | high quality | we don't have a second arm |

**Recommendation:** A (gamepad) as the primary teleop, with B if a SpaceMouse is available.
Teleop uses the **same action interface + safety supervisor** as the policy, so recorded
actions are directly comparable to policy actions. *(Decision item D6.)*

> The JACO2's on-arm joystick (if fitted) can also drive it, but it bypasses our supervisor
> and gives no ROS-side action stream — not suitable for dataset capture.

## 2. Episode protocol

1. **Reset** the scene to a randomized-but-bounded initial state (object poses sampled from a
   small set); record the initial frame.
2. **State the instruction** for the episode (one of the task's fixed templates, plus
   paraphrases) — this becomes the language label.
3. **Teleoperate** to complete the task at a natural pace (< ~30 s/episode).
4. **Mark the outcome** (success/fail, notes).
5. Save the episode; return to step 1.

Target: **50 episodes** to start (Phase B), scaling to **200+** if needed. Include failures
and recovery attempts for robustness.

## 3. What each step records

Synchronized at a fixed control rate (e.g. 20–30 Hz):

| Stream | Source | Notes |
|--------|--------|-------|
| RGB (per chosen camera) | `/camN/color/image_raw` | resize to model input (e.g. 224/256) |
| Depth (optional) | `/camN/aligned_depth_to_color/...` | for 3D variants / analysis |
| Joint positions/velocities | `sensor_msgs/JointState` | from bridge |
| EEF pose + wrench | `out/tool_pose`, `out/tool_wrench` | |
| Finger positions | `out/finger_position` | gripper state |
| **Action** | the mapped command actually sent | e.g. EEF delta + gripper |
| Language | fixed string | the instruction |

Timestamps are unified to a single monotonic clock; interpolation fills gaps.

## 4. Dataset format

**Primary: LeRobot dataset (v2/v3 layout)** — parquet + videos, directly consumable by
SmolVLA/OpenVLA tooling:

```
dataset/
  meta/            info.json, tasks.jsonl, episodes.jsonl, stats
  data/            chunk-*/episode_*.parquet   (state, action, timestamps)
  videos/          observation.images.<cam>/chunk-*/episode_*.mp4
```

- `action` = the **mapped, executed** action (same space the policy will output).
- `observation.images.*` = one key per camera.
- `task` = instruction string.

**Secondary export:** RLDS/TFRecord if we target a model that expects it (GR00T/OpenVLA
converters exist). Keep the raw episode dirs (doc 02) as the source of truth so any format
can be regenerated.

## 5. Camera selection & synchronization

- Start with **2–3 views**: e.g. a **wrist view** (if we can mount one; none is on the arm
  today) and **1–2 static workspace views**. Re-evaluate in M4.
- D435 color+depth are hardware-synced per camera; **across** cameras we rely on host
  timestamps (good enough at 20–30 Hz for this task).
- Record at the **model's native input resolution** where possible to avoid re-scaling
  artifacts; store the resize in `meta.json`.

## 6. Quality checks (before training)

- No dropped/over-length episodes; monotonic timestamps.
- Actions within clamps (sanity: no teleop command saturated the whole episode).
- View coverage: objects visible in the chosen cameras for the relevant phase.
- Language labels balanced across paraphrases.
- Split: ~90 % train / 10 % validation, **by initial-state seed** (no leakage).

## 7. Storage estimate

| Item | Size |
|------|------|
| RGB 256×256 @ 20 Hz, 30 s, 3 cams, h264 | ~10–30 MB/episode |
| 50–200 episodes | ~1–6 GB |
| Depth (if recorded) | 3–5× RGB |
| Model weights + cache | up to ~20 GB (7 B) |

Comfortable on the 2.7 TB disk (D4); tight on `/` (21 GB).
