# 01 — Overview, Scope & Success Criteria

## 1. Objective

Enable the JACO2 arm to be driven by a **vision-language-action** policy: given one or more
camera streams and a short natural-language instruction ("put the red block in the tray"),
the system produces a stream of robot actions that accomplish the task.

The goal is a **reproducible research rig**, not a product: everything observable, logged,
and replayable, with a hard safety envelope around the physical arm.

## 2. Why this robot / these cameras

- The JACO2 is already integrated and controllable from ROS 2 (via the ROS 1 bridge), so we
  can focus effort on perception + policy rather than driver work.
- Seven D435s give us multi-view RGB-D. Most VLAs take 1–3 views; the extras let us choose
  the best viewpoints and support future multi-view / 3D variants and data collection.

## 3. Scope

**In scope**
- RealSense bring-up on ROS 2 Jazzy (image + depth + intrinsics, TF, calibration).
- A VLA **inference service** running locally on the RTX 3090, exposed to ROS 2.
- An **action interface layer** that maps model output to safe JACO2 commands.
- A **safety supervisor** (watchdog, clamps, workspace limits, dry-run mode).
- **Data collection** (teleoperation) and optional **LoRA fine-tuning** of a VLA.
- Logging + a repeatable **evaluation harness** (episode success, latency, safety trips).

**Out of scope (initial)**
- Full MoveIt/IK motion planning and collision avoidance (may be revisited if needed).
- Whole-body or multi-arm setups; the JACO is a fixed-base single arm.
- Sim-to-real training pipelines (we may add a sim smoke test later, but not required).
- Production hardening / long-duration autonomy.

## 4. Proposed first task (needs your approval — D2)

**Tabletop pick-and-place with the 3-finger gripper.**

- Workspace: a fixed table in front of the arm, with 2–3 movable objects (colored blocks)
  and 1–2 target containers.
- Instruction examples: *"move the red block to the tray"*, *"put the blue cube on the right"*,
  *"pick up the green block"*.
- Why: it exercises the whole loop (perception → language → grasp → place), is measurable,
  and is what most VLA benchmarks (e.g. LIBERO-style, bridge/RT-1-style tasks) assume, so
  pretrained models have a chance zero-shot and fine-tuning is tractable.

Alternatives if you prefer something else: button pressing, drawer opening, wiping,
handover. These have different action-space demands (force/torque, longer horizon).

## 5. Success criteria

We track two tiers: **pipeline success** (can we move bits end-to-end) and **policy success**
(can the model do the task).

| Tier | Metric | Target |
|------|--------|--------|
| Pipeline | All chosen cameras publish RGB-D at 30 FPS with < 100 ms pipeline latency | Pass |
| Pipeline | VLA inference end-to-end latency (image+text → action chunk) | ≤ 250 ms (chunked) |
| Pipeline | Command→motion round trip through the bridge | ≤ 100 ms |
| Safety | Unintended motion with no command (watchdog) | 0 events |
| Safety | All clamps/limits enforced in a fault-injection test | Pass |
| Policy (zero-shot) | Task success with a pretrained VLA, 10 trials | measure baseline (likely low) |
| Policy (fine-tuned) | Task success after LoRA fine-tune, 20 trials | ≥ 60 % on the chosen task |
| Reproducibility | Any episode replayable from logs (images, states, actions) | Pass |

> Numeric targets are proposals; tuning them is part of M7.

## 6. Definitions

- **VLA** — a model that takes image(s) + text + (often) robot state and outputs actions.
- **Action chunk** — VLAs typically predict a *sequence* of future actions (e.g. 8–16 steps)
  at once, executed open-loop until the next inference (a.k.a. action chunking / receding
  horizon).
- **Embodiment gap** — VLAs are trained on specific robots; JACO2 is non-standard, so
  zero-shot transfer is weak and fine-tuning is usually required.
- **Shadow / dry-run** — the policy runs and its actions are logged/compared, but nothing is
  sent to the arm.
- **Watchdog** — a timer that forces a stop if commands stop arriving (the stock driver has
  none; we must add one).

## 7. Assumptions

- We may install system packages (librealsense, realsense-ros) and create a Python env.
- The machine remains the single compute node (perception + policy on the 3090).
- The arm stays in the current mounting / workspace during the project.
- We can freely reboot/restart the ROS 1 stack as needed.
