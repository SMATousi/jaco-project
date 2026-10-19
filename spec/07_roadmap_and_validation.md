# 07 — Roadmap & Validation Plan

Each milestone has **deliverables** and a **validation gate**. A milestone is *done* only
when its gate passes and is recorded (command + output saved under `spec/validation/` or a
run log). No milestone silently proceeds on "it seemed to work".

## Milestone summary

| M | Title | Gate (must pass) |
|---|-------|------------------|
| M0 | Environment + RealSense bring-up | N cameras stream at target FPS ≥ 10 min, no USB underruns; arm stack healthy |
| M1 | Multi-camera calibration & TF | base↔camera transforms published; cross-view sanity check passes |
| M2 | VLA inference server (offline) | server returns action chunks with documented latency + determinism |
| M3 | Action mapper + safety supervisor | watchdog stop < 200 ms; clamps proven by fault injection; DRY_RUN publishes nothing |
| M4 | Closed-loop loop (bounded motion) | policy drives arm within caps; e-stop + watchdog verified on hardware |
| M5 | Demonstration dataset | ≥ 50 episodes pass QC; replay reproduces recorded actions |
| M6 | Fine-tuning | val action error improves vs base; checkpoint serves in the API |
| M7 | Closed-loop evaluation | task success ≥ target; 0 safety trips; reproducible report |

---

## M0 — Environment & RealSense bring-up

**Tasks**
- Install `librealsense2` (+utils) and `ros-jazzy-realsense2-camera`; pin versions.
- Restart the arm stack (`scripts/jaco restart`); confirm `scripts/jaco verify` passes.
- Bring up **one** camera → color + depth + `camera_info` at 30 FPS; check `dmesg` for UVC
  underruns. Then add cameras one at a time up to the chosen N (2–3; prefer USB-3 ones).
- Assign **stable device names** by serial in the launch config.

**Deliverables:** `scripts/10_install_realsense.sh`, `config/cameras.yaml`, bring-up launch,
a short findings note (which serial ↔ which USB bus).

**Gate:** N cameras publish RGB-D at the configured rate continuously for **≥ 10 min** with
no dropped frames/underruns; arm feedback topics present.

**Status (2026-10-19):** 🟡 PARTIAL → nearly done. RealSense stack installed; `cam0`
(`2-2.2`, serial `935322072821`) streams color+depth at ~27 Hz with no frame warnings;
10-min color soak had **0 driver frame-timeouts**; helper `scripts/20_cameras.sh` and
`config/cameras.yaml` added. **Arm recovered** after the host refreshed the Incus USB
node (R15): driver reports `Jaco V2 Service`, **12** bridged topics, valid joint feedback.
Remaining: a clean ≥10 min **RGB-D** soak and a motion-authorized jog/step-response check.
Full evidence: [`validation/M0_environment.md`](validation/M0_environment.md).

---

## M1 — Multi-camera calibration & TF

**Tasks**
- Publish `TF` for each camera (driver provides optical frames); set the base ↔ camera
  extrinsics (start measured, then refine).
- Intrinsics from `camera_info` stored per serial.
- Optional: hand-eye calibration if we add a wrist camera.

**Deliverables:** TF tree snapshot, calibration files, a script that re-checks them.

**Gate:** a known table point maps consistently across 2+ views into the arm base frame
(error within a stated tolerance, e.g. < 1–2 cm for the static views).

---

## M2 — VLA inference server

**Tasks**
- Create the `vla` env; install SmolVLA (+ later OpenVLA).
- Implement `vla_server` with the API from doc 04; warm-up; health + metrics.
- Run **offline**: feed a captured frame + instruction, get an action chunk.

**Deliverables:** server code + client stub, dependency lockfile, a latency benchmark.

**Gate:** server returns well-formed action chunks; **p50 latency documented** (target
≤ 250 ms); same input+seed ⇒ same output (determinism).

**Status (2026-10-19):** ✅ **offline gate passed.** `vla` env (Python 3.11, torch
2.10+cu128), SmolVLA base loaded in 5.2 s, **50×6** chunks, **p50 113.8 ms / p95
115.2 ms** (RTX 3090), deterministic for a fixed seed. Deliverables: `vla/smolvla_runtime.py`,
`vla/vla_server.py`, `vla/vla_client.py`, `scripts/40_vla_server.sh`,
`scripts/30_test_smolvla.py`. **Caveat:** base-model actions are not JACO2 commands — the
mapping + safety gate is M3, and fine-tuning is M6. Disk is now 8.5 GB free (D4 urgent).
Evidence: [`validation/M2_vla_server.md`](validation/M2_vla_server.md).

---

## M3 — Action mapper + safety supervisor (dry-run only)

**Tasks**
- Implement the action mapper (doc 05 §2) and the supervisor + mode state machine (doc 02 §5).
- Verify `trajectory_controller/command` bridging; decide velocity vs bounded-trajectory mode.
- Implement the **gripper relay** (ROS 1 node) if needed.
- **Shadow replay**: run recorded/scripted observations through mapper+supervisor in
  `DRY_RUN`; nothing reaches the arm.

**Deliverables:** `policy_client`, `safety_supervisor`, gripper relay, config for clamps.

**Gate:**
- `DRY_RUN` publishes **zero** arm commands (verified by a topic sniffer).
- **Watchdog test:** cut the command stream → zero velocity published **< 200 ms**.
- **Fault injection:** NaN action, out-of-workspace target, over-limit joint → all rejected
  and logged.

---

## M4 — Closed-loop with bounded motion

**Tasks**
- Add teleop (gamepad) and wire policy output → `ACTIVE` with **small** caps.
- Step-response tests; first motion driven by a real VLA output (SmolVLA).

**Deliverables:** teleop node, mode-control service, a recorded first-policy-motion video.

**Gate (on hardware, e-stop in hand):**
- Small commanded step moves the arm within tolerance and stops.
- **E-stop** and **watchdog** each verified to halt motion.
- No safety trip during a 5-minute supervised run.

---

## M5 — Demonstration dataset

**Tasks**
- Collect ≥ 50 episodes per the protocol (doc 06); include failures.
- QC + export to LeRobot format; produce train/val split by seed.

**Deliverables:** dataset + `stats`, QC report, replay harness.

**Gate:** all QC checks pass; **replay** of a subset reproduces the recorded executed actions
and re-drives the arm in `DRY_RUN` identically.

---

## M6 — Fine-tuning

**Tasks**
- Train (LoRA) the chosen model on the dataset; log configs + seeds.
- Offline evaluation on the val split vs the base model.

**Deliverables:** training config, checkpoint, learning curves, val metrics.

**Gate:** val action error decreases vs base; checkpoint loads and serves in the M2 API;
inference latency still within budget.

---

## M7 — Closed-loop evaluation & report

**Tasks**
- Run the eval harness: 20 trials of the target task from held-out initial states.
- Record success/failure, duration, safety trips, and a failure taxonomy.
- Optional ablations: camera count, views, velocity vs bounded-trajectory mode.

**Deliverables:** eval results, videos, written report, updated spec.

**Gate:** task success ≥ target (proposal **≥ 60 %**), **0 safety trips**, every trial
reproducible from its episode dir.

---

## Cross-cutting validation methodology

- **Deterministic replay** is the backbone: any run is re-executable in shadow mode from its
  logged observations.
- **Gate evidence** is stored (command + output), not asserted in prose.
- **Simulation shim (optional):** a simple kinematic sim node that accepts the same commands
  lets us test the policy loop without the physical arm (nice-to-have, not required).
- **Metric set:** task success, time-to-complete, safety trips, inference latency (p50/p95),
  command→motion latency, clamp/reject counts.
