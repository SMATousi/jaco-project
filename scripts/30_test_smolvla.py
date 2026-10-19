#!/usr/bin/env python3
"""SmolVLA smoke test — load the base checkpoint and run one inference.

Run with the dedicated env (NOT system python):

    /root/miniconda3/envs/vla/bin/python scripts/30_test_smolvla.py \
        --image /tmp/cam0_b.png --task "put the red block in the tray"

The base checkpoint expects 3 cameras (camera1/2/3), a 6-D state, and outputs a
6-D action chunk. With a single physical camera we duplicate the view into all
three slots; this is a pipeline test, not a claim of zero-shot competence.

Note: `lerobot` 0.4.4's `from_pretrained` re-parses config.json with draccus and
rejects the checkpoint's `type` field. We build the config directly from JSON and
pass it to the policy loader instead.
"""
import argparse
import json
import os
import time

import cv2
import numpy as np
import torch
from huggingface_hub import snapshot_download
from lerobot.configs.types import FeatureType, PolicyFeature
from lerobot.policies.factory import make_pre_post_processors
from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

REPO = "lerobot/smolvla_base"


def load_config(repo_or_dir: str) -> tuple[SmolVLAConfig, str]:
    local = snapshot_download(repo_or_dir) if "/" in repo_or_dir else repo_or_dir
    with open(os.path.join(local, "config.json")) as f:
        cfg = json.load(f)
    cfg.pop("type", None)
    for key in ("input_features", "output_features"):
        cfg[key] = {
            k: PolicyFeature(type=FeatureType(v["type"]), shape=tuple(v["shape"]))
            for k, v in cfg[key].items()
        }
    return SmolVLAConfig(**cfg), local


def load_image(path: str, size: int = 256) -> torch.Tensor:
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(path)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    img = img.astype(np.float32) / 255.0
    return torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0)  # [1,3,H,W]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--task", default="pick up the red block")
    ap.add_argument("--state", type=float, nargs=6, default=[0.0] * 6)
    ap.add_argument("--repo", default=REPO)
    args = ap.parse_args()

    print(f"loading config from {args.repo} ...")
    cfg, local = load_config(args.repo)
    print(f"  image_features: {list(cfg.image_features)}  device: {cfg.device}")
    preprocessor, postprocessor = make_pre_post_processors(cfg, pretrained_path=local)

    print("loading policy (first run downloads the SmolVLM2 backbone) ...")
    t0 = time.time()
    policy = SmolVLAPolicy.from_pretrained(local, config=cfg)
    policy.eval()
    print(f"  loaded in {time.time() - t0:.1f}s on {next(policy.parameters()).device}")

    img = load_image(args.image)
    obs = {
        "observation.images.camera1": img,
        "observation.images.camera2": img.clone(),
        "observation.images.camera3": img.clone(),
        "observation.state": torch.tensor([args.state], dtype=torch.float32),
        "task": [args.task],
    }

    print("preprocessing ...")
    obs = preprocessor(obs)

    for i in range(2):
        t = time.time()
        with torch.inference_mode():
            chunk = policy.predict_action_chunk(obs)
        dt = (time.time() - t) * 1000
        print(f"  run {i}: chunk {tuple(chunk.shape)} in {dt:.1f} ms")

    chunk = postprocessor(chunk)
    print("action chunk (first 3 steps, first 6 dims):")
    print(chunk[0, :3, :6].cpu().numpy())
    print(f"chunk stats: min={chunk.min().item():.3f} max={chunk.max().item():.3f}")


if __name__ == "__main__":
    main()
