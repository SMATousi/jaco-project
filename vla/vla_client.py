#!/usr/bin/env python3
"""HTTP client for the resident SmolVLA server.

This side runs on the **system Python** (same interpreter as ROS 2); it never
imports torch or lerobot. Images are OpenCV BGR arrays, JPEG-encoded and sent
as base64 JSON.

Library use (from a future ``policy_client`` ROS node)::

    from vla.vla_client import VlaClient
    client = VlaClient("http://127.0.0.1:8090")
    out = client.act({"camera1": frame_bgr}, "put the block in the tray", state=[...])
    actions = out["actions"]   # [K][D]

CLI::

    /usr/bin/python3 vla/vla_client.py --image /tmp/cam0_b.png --task "..." --repeat 3
"""

from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.request

import cv2
import numpy as np


def encode_image(bgr: np.ndarray, quality: int = 90) -> str:
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG encode failed")
    return base64.b64encode(buf.tobytes()).decode()


class VlaClient:
    def __init__(self, url: str = "http://127.0.0.1:8090", timeout: float = 30.0) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str) -> dict:
        with urllib.request.urlopen(self.url + path, timeout=self.timeout) as r:
            return json.loads(r.read())

    def health(self) -> dict:
        return self._get("/health")

    def metrics(self) -> dict:
        return self._get("/metrics")

    def act(
        self,
        images: dict[str, np.ndarray],
        instruction: str,
        state: list[float] | None = None,
        seed: int = 0,
    ) -> dict:
        payload = {
            "instruction": instruction,
            "images": {k: encode_image(v) for k, v in images.items()},
            "seed": int(seed),
        }
        if state is not None:
            payload["state"] = [float(x) for x in state]
        req = urllib.request.Request(
            self.url + "/act",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--image")
    ap.add_argument("--task", default="pick up the red block")
    ap.add_argument("--state", type=float, nargs=6, default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--repeat", type=int, default=1, help="repeat and check determinism")
    ap.add_argument("--health", action="store_true")
    args = ap.parse_args()

    client = VlaClient(args.url)

    if args.health or not args.image:
        print(json.dumps(client.health(), indent=2))
        return

    img = cv2.imread(args.image)
    if img is None:
        raise SystemExit(f"cannot read image: {args.image}")

    results = []
    for i in range(args.repeat):
        t0 = time.perf_counter()
        out = client.act({"camera1": img}, args.task, args.state, args.seed)
        wall = (time.perf_counter() - t0) * 1000
        results.append(out)
        print(
            f"call {i}: wall {wall:.1f} ms | server {out['latency_ms']} ms | "
            f"chunk {out['chunk_size']}x{out['action_dim']}"
        )

    first = np.asarray(results[0]["actions"], dtype=np.float32)
    if args.repeat > 1:
        same = all(np.array_equal(first, np.asarray(r["actions"], dtype=np.float32)) for r in results[1:])
        print(f"deterministic (same seed): {same}")
    print("first 3 steps:")
    print(first[:3])


if __name__ == "__main__":
    main()
