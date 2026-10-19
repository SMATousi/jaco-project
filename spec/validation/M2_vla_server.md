# M2 — VLA Inference Server (offline) — Validation Log

**Started:** 2026-10-19
**Status:** ✅ **OFFLINE GATE PASSED** — server returns well-formed action chunks at
**p50 ≈ 114 ms**; deterministic for a fixed seed.

> ⚠️ **Safety:** the base checkpoint's 6-D actions are **not JACO2 commands**. They are
> in the base model's training convention and are only used here to validate the
> pipeline. Nothing from this server is sent to the arm until the action mapping and
> fine-tuning (M6) are validated. The arm is still blocked anyway (R15).

---

## 1. Environment

Dedicated conda env `vla` (decision D1: SmolVLA first; strict split from system Python).

| Package | Version |
|---------|---------|
| Python | 3.11 |
| torch | **2.10.0+cu128** (`cuda.is_available() == True`, RTX 3090) |
| torchvision | matching cu128 build |
| transformers | **4.57.6** (pinned `<5.0`) |
| huggingface_hub | 0.35.3 |
| lerobot | **0.4.4** |
| others | numpy 2.2.6, opencv-python, pyzmq, num2words, datasets, diffusers |

**Model artifacts** (HF cache `/root/.cache/huggingface`):

| Artifact | Size |
|----------|------|
| `lerobot/smolvla_base` (config + `model.safetensors` + processors) | 873 MB |
| `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` (VLM backbone used by SmolVLA) | 1.9 GB |

**Disk:** `/` went **22 GB → 8.5 GB free** after the env + weights. **D4 (storage) is now
urgent** — there is no room for OpenVLA-7B or a dataset on `/`.

### Issues hit and fixes

1. **`lerobot` downgraded metadata but left `transformers` too new.**
   `lerobot 0.4.4` requires `huggingface-hub <0.36` and (for SmolVLA)
   `transformers>=4.57.1,<5.0`, but pip had installed `transformers 5.20.2`.
   → pin `transformers==4.57.6`.
2. **Checkpoint `config.json` contains `"type": "smolvla"`.**
   `lerobot`'s `PreTrainedConfig.from_pretrained` re-parses the raw JSON with draccus and
   raises `DecodingError: The fields 'type' are not valid`.
   → load the JSON, drop `type`, rebuild `PolicyFeature`/`FeatureType` objects, and pass
   `config=` to `PreTrainedPolicy.from_pretrained` (implemented in
   `vla/smolvla_runtime.py`).
3. **`num2words` missing** (SmolVLM processor) → installed.
4. **Base checkpoint expects 3 camera views** (`camera1/2/3`) but the rig currently
   publishes one. → the runtime duplicates the first available view into the other two
   slots. This is a pipeline workaround only; the fine-tuned model will use the real rig
   views.

---

## 2. Implementation

| File | Role |
|------|------|
| `vla/smolvla_runtime.py` | config loading, image decode/resize, seeded inference, latency stats |
| `vla/vla_server.py` | resident **HTTP** server (`/health`, `/metrics`, `/act`) |
| `vla/vla_client.py` | system-Python client (JPEG+base64 JSON); usable from `policy_client` |
| `scripts/30_test_smolvla.py` | one-shot offline smoke test |
| `scripts/40_vla_server.sh` | `start/stop/status/logs` (conda env, PID file, health wait) |

**Protocol** (follows `spec/04_vla_model.md` §4):

```
POST /act
  { instruction: str,
    images: { "camera1": <b64 jpeg>, ... },   # BGR uint8 from OpenCV
    state?: [6 floats],
    seed?: int }                              # seeds flow-matching noise
->
  { actions: [[K x D]], latency_ms, chunk_size, action_dim, model, seed }

GET /health   -> model, device, VRAM, chunk size, load time, latency percentiles
GET /metrics  -> request count + p50/p95/min/max
```

The server serializes GPU inference with a lock (single 3090). Preprocessing
(resize 256×256, `[0,1]` RGB, normalization, tokenizer) happens **server-side**.

---

## 3. Results

**Startup**

```
load_s: 5.2
vram_alloc_mb: 892.5
device: cuda:0
chunk_size: 50, action_dim: 6
```

**Three consecutive calls (same image/instruction/seed 0)**

| Call | Client wall | Server | Chunk |
|------|-------------|--------|-------|
| 0 | 137.9 ms | 115.21 ms | 50×6 |
| 1 | 119.3 ms | 110.87 ms | 50×6 |
| 2 | 120.2 ms | 113.84 ms | 50×6 |

**Latency (warm-up excluded): p50 = 113.84 ms, p95 = 115.21 ms, min = 110.87 ms,
max = 115.21 ms.** Target was ≤250 ms per chunk → **met**.

**Determinism**

- same seed (0) → **identical** action chunks (bitwise) across calls;
- different seed (1) → max abs difference **1.149** (flow-matching sampling is stochastic
  by design; the `seed` field makes runs reproducible).

**Example chunk (seed 0, first 3 of 50 steps):**

```
[[-0.2014 -0.1717 -0.2263  0.0329  0.0147 -0.0855]
 [-0.3125 -0.2323 -0.2371 -0.0534  0.0074 -0.1117]
 [-0.3359 -0.2883 -0.1524 -0.1884 -0.0398 -0.1226]]
```

---

## 4. Gate

| M2 gate item | Status |
|--------------|--------|
| Server returns well-formed `[K, D]` chunks | ✅ 50×6 |
| Resident model, loaded once, warmed up | ✅ 5.2 s load, 2 warm-up passes |
| p50 latency documented | ✅ **113.8 ms** (p95 115.2 ms) |
| Determinism documented | ✅ same seed → identical; seed controls sampling |
| Health endpoint + metrics | ✅ `/health`, `/metrics` |
| Client on system Python (no torch) | ✅ `vla/vla_client.py` uses numpy/cv2/urllib only |

**Remaining for M2 → M3:** feed real RGB-D from `policy_client`, define the action
mapping (base outputs → JACO2 velocity commands) and clamp/watchdog policy, and benchmark
end-to-end latency with camera capture + ROS transport.

---

## Shutdown (2026-10-19)

The resident server (pid 229411, 901.6 MB VRAM) was stopped cleanly after the offline
measurements:

```bash
bash scripts/40_vla_server.sh stop     # -> vla_server: stopped
```

No GPU memory is held while the arm/camera USB recovery is pending.  Restart with
`bash scripts/40_vla_server.sh start` (model load ≈5.2 s, two warm-up passes); the offline
gate results above remain valid.
