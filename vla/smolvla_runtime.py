"""SmolVLA runtime — config loading, preprocessing and action-chunk inference.

Runs only inside the dedicated ``vla`` conda env (torch + lerobot). The ROS 2
side must never import this module; it talks to the HTTP server instead
(see ``spec/03_environment.md`` and ``spec/04_vla_model.md``).

Note on checkpoints
-------------------
``lerobot`` 0.4.4's ``PreTrainedConfig.from_pretrained`` re-parses ``config.json``
with draccus and rejects the ``type`` key that ``lerobot/smolvla_base`` contains.
We therefore load the JSON ourselves and rebuild the ``PolicyFeature`` objects.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import cv2
import numpy as np
import torch
from huggingface_hub import snapshot_download
from lerobot.configs.types import FeatureType, PolicyFeature
from lerobot.policies.factory import make_pre_post_processors
from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

CAMERA_KEYS = (
    "observation.images.camera1",
    "observation.images.camera2",
    "observation.images.camera3",
)
DEFAULT_REPO = "lerobot/smolvla_base"


def load_smolvla_config(repo_or_dir: str) -> tuple[SmolVLAConfig, str]:
    """Load a SmolVLA config from a HF repo id or a local directory."""
    local = repo_or_dir if os.path.isdir(repo_or_dir) else snapshot_download(repo_or_dir)
    with open(os.path.join(local, "config.json")) as f:
        raw = json.load(f)
    raw.pop("type", None)
    for key in ("input_features", "output_features"):
        raw[key] = {
            k: PolicyFeature(type=FeatureType(v["type"]), shape=tuple(v["shape"]))
            for k, v in raw[key].items()
        }
    return SmolVLAConfig(**raw), local


def decode_b64_image(data: str) -> np.ndarray:
    """Decode a base64 JPEG/PNG string to a BGR uint8 array."""
    buf = np.frombuffer(__import__("base64").b64decode(data), dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image")
    return img


def image_to_tensor(bgr: np.ndarray, size: int = 256) -> torch.Tensor:
    """BGR uint8 -> RGB float tensor [1,3,size,size] in [0,1]."""
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    rgb = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA)
    arr = rgb.astype(np.float32) / 255.0
    return torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)


class SmolVLARuntime:
    """Loads SmolVLA once, warms up, and serves action chunks.

    The base checkpoint expects three camera views. If fewer are supplied, the
    first available view is duplicated (documented limitation of the base
    checkpoint; the fine-tuned model will be trained with the rig's real views).
    """

    def __init__(
        self,
        repo: str = DEFAULT_REPO,
        device: str = "cuda",
        image_size: int = 256,
        warmup: bool = True,
    ) -> None:
        self.repo = repo
        self.image_size = image_size
        self.lock = threading.Lock()
        self._latencies: list[float] = []

        t0 = time.time()
        self.config, self.local_dir = load_smolvla_config(repo)
        self.config.device = device
        self.preprocessor, self.postprocessor = make_pre_post_processors(
            self.config, pretrained_path=self.local_dir
        )
        self.policy = SmolVLAPolicy.from_pretrained(self.local_dir, config=self.config)
        self.policy.eval()
        self.load_s = time.time() - t0

        if warmup:
            self.warmup()

    # ------------------------------------------------------------------ api
    def warmup(self, n: int = 2) -> None:
        blank = np.zeros((self.image_size, self.image_size, 3), dtype=np.uint8)
        for _ in range(n):
            self.act({"camera1": blank}, "warm up", state=[0.0] * 6, seed=0, record=False)

    def act(
        self,
        images: dict[str, np.ndarray],
        instruction: str,
        state: list[float] | None = None,
        seed: int = 0,
        record: bool = True,
    ) -> dict[str, Any]:
        """Run one inference. ``images`` maps view name -> BGR uint8 array."""
        views: list[np.ndarray] = []
        for key in ("camera1", "camera2", "camera3"):
            if key in images and images[key] is not None:
                views.append(images[key])
        if not views:
            raise ValueError("at least one image view is required")
        while len(views) < 3:
            views.append(views[0])

        obs: dict[str, Any] = {
            CAMERA_KEYS[i]: image_to_tensor(views[i], self.image_size) for i in range(3)
        }
        obs["observation.state"] = torch.tensor(
            [state if state is not None else [0.0] * 6], dtype=torch.float32
        )
        obs["task"] = [instruction]

        with self.lock:
            # Flow-matching samples noise; seed it so identical requests match.
            torch.manual_seed(int(seed))
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(int(seed))
            batch = self.preprocessor(obs)
            t0 = time.perf_counter()
            with torch.inference_mode():
                chunk = self.policy.predict_action_chunk(batch)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            chunk = self.postprocessor(chunk)

        actions = chunk[0].detach().cpu().numpy().tolist()
        if record:
            self._latencies.append(latency_ms)
        return {
            "actions": actions,
            "latency_ms": round(latency_ms, 2),
            "chunk_size": len(actions),
            "action_dim": len(actions[0]) if actions else 0,
            "model": self.repo,
            "seed": int(seed),
        }

    def stats(self) -> dict[str, Any]:
        lat = sorted(self._latencies)
        if not lat:
            return {"requests": 0}
        p = lambda q: lat[min(len(lat) - 1, int(q * len(lat)))]
        return {
            "requests": len(lat),
            "p50_ms": round(p(0.50), 2),
            "p95_ms": round(p(0.95), 2),
            "min_ms": round(lat[0], 2),
            "max_ms": round(lat[-1], 2),
        }

    def health(self) -> dict[str, Any]:
        vram = None
        if torch.cuda.is_available():
            vram = round(torch.cuda.memory_allocated() / 2**20, 1)
        return {
            "status": "ok",
            "model": self.repo,
            "device": str(next(self.policy.parameters()).device),
            "load_s": round(self.load_s, 1),
            "vram_alloc_mb": vram,
            "chunk_size": self.config.chunk_size,
            "action_dim": self.config.action_feature.shape[0],
            "latency": self.stats(),
        }
