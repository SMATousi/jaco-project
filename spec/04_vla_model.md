# 04 — VLA Model Selection, Inference & Fine-Tuning

> Model landscape moves fast. The table below reflects what is known at spec time
> (2026-10); at implementation we will **pin an exact revision hash** and re-check
> licenses before downloading.

## 1. Requirements driving the choice

| Requirement | Value |
|-------------|-------|
| GPU memory | 24 GB (RTX 3090) — single GPU only |
| Inference latency target | ≤ 250 ms per action chunk |
| Control frequency after chunking | ≥ 2 Hz policy rate |
| Action space flexibility | must map to JACO2 (custom) |
| Fine-tuning | must fit on 24 GB → **LoRA** strongly preferred |
| Ecosystem | HuggingFace / LeRobot friendly, good docs |

## 2. Candidate models

| Model | Params | ~VRAM (infer) | Action head | Fine-tune on 24 GB? | Notes |
|-------|-------:|--------------:|-------------|---------------------|-------|
| **SmolVLA** | ~0.45 B | < 2 GB | continuous, flow-matching, chunked | yes (even LoRA-free) | LeRobot-native; runs on modest GPUs; great for bring-up |
| **OpenVLA-7B** | 7 B | ~15 GB | discretized 7-DoF tokens | **yes, LoRA** (~1 epoch, batch 1 + accum) | most documented; Llama-2-based license |
| **OpenVLA-OFT** | 7 B | ~15 GB | continuous (L1), parallel decode | yes, LoRA | faster + higher success than vanilla OpenVLA |
| **π0 / π0.5** | ~3 B | ~7 GB | flow-matching, high-freq | tight (needs their stack, often multi-GPU) | strong policies; heavier toolchain |
| **GR00T N1/N1.5** | ~2–3 B | ~7 GB | diffusion transformer | yes (their repo) | NVIDIA ecosystem; embodiment-tagged |
| **RDT-1B** | 1 B | ~4 GB | diffusion | yes | bilingual, strong on arms |
| **Octo** | 93 M | < 1 GB | continuous, flexible | yes | old but light and hackable |
| **TinyVLA** | ~1 B | ~4 GB | continuous | yes | lightweight research option |

## 3. Recommendation — phased (needs D1 approval)

**Phase A — pipeline bring-up with SmolVLA (fast, low-risk).**
Get the *entire loop* working (cameras → policy → mapped actions → dry-run → arm) with a
model small enough to ignore the storage/VRAM issues. Proves the plumbing, the action
mapping, the safety layer, and the evaluation harness.

**Phase B — research model with OpenVLA-7B (+ LoRA).**
Once a small demonstration dataset exists, fine-tune with LoRA on the 3090. OpenVLA-OFT is
the preferred target if its toolchain installs cleanly (better success + speed).

**Not chosen initially:** π0/GR00T — powerful but their toolchains and VRAM needs add risk
before we have a working loop. Revisit at M7.

## 4. Inference server design (`vla_server`)

- **Resident process**: load weights once, warm up, keep on GPU. Never reload per request.
- **Transport**: local **ZeroMQ** (REQ/REP or PUB/SUB) or HTTP. Payload = observation
  (images + instruction + optional state) → **action chunk** `[K, D]` + metadata.
- **Images**: send as JPEG/PNG-encoded bytes or raw `uint8` (HxWx3) — decide by measuring.
  Preprocessing (resize/normalize) happens **server-side** to keep the client thin.
- **Action chunking**: return K steps (e.g. 8–16). Client executes them at the execution
  rate, overlapping the next inference.
- **Failure handling**: timeout → client holds last-safe / goes to IDLE; OOM → server
  restarts, client detects and stops.
- **Health**: `/health` endpoint, VRAM + latency metrics exported.

Interface sketch:

```
request  : { instruction: str, images: {view: <encoded>}, state?: [q, qd, eef], meta: {...} }
response : { actions: [[...K...]], dt: float, model: str, latency_ms: float }
```

## 5. Fine-tuning strategy (Phase B)

- **Method:** LoRA (PEFT) on the action-expert / attention projections. Frozen vision tower
  unless accuracy demands otherwise.
- **Data:** see doc 06. Start with **~50 episodes** of the target task; scale to 200+ if the
  success rate plateaus.
- **Compute:** batch 1 + gradient accumulation, bf16, gradient checkpointing; ~hours on one
  3090 for 50–100 episodes. Exact time measured at M6.
- **Evaluation:** held-out initial states; report success rate + a saved `result.json` per run
  (doc 07).
- **Repro:** pin base-model revision, dataset hash, LoRA config, seeds.

## 6. Action-space reality check (ties to doc 05)

VLAs are trained on specific embodiments:
- OpenVLA / RT-style: **7-DoF end-effector delta** (Δxyz, Δrpy) + **gripper**.
- π0/GR00T/SmolVLA: continuous joint or EEF chunks depending on the checkpoint.

JACO2 is **not** a standard VLA embodiment, so:
1. Zero-shot success will likely be **low** — we measure it, we don't depend on it.
2. We need a **mapper** from the model's action space → a JACO2 control interface
   (doc 05). This mapper is a first-class component, not glue.

## 7. Dependencies (draft)

```
# vla env (own conda env; NOT the ROS python)
torch, torchvision, transformers, timm, einops, accelerate, peft,
huggingface_hub, safetensors, numpy, pillow, opencv-python, pyzmq
lerobot            # for SmolVLA (Phase A)
# + model-specific extras (openvla / openpi / Isaac-GR00T) as needed
```

ROS 2 side (system py3.12): `rclpy`, `cv_bridge`, `sensor_msgs`, `numpy`, `pyzmq`.
