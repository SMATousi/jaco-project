#!/usr/bin/env python3
"""Resident SmolVLA inference server (HTTP + JSON).

Run inside the dedicated ``vla`` conda env:

    /root/miniconda3/envs/vla/bin/python -m vla.vla_server --port 8090

Endpoints
---------
``GET  /health``  -> model/device/latency stats
``GET  /metrics`` -> latency percentiles
``POST /act``     -> {instruction, images: {view: b64-jpeg}, state?: [6], seed?}
                     -> {actions: [[K x D]], latency_ms, model, ...}

Images are BGR uint8 arrays encoded as JPEG by the client; preprocessing is
server-side. See ``spec/04_vla_model.md`` §4.
"""

from __future__ import annotations

import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from vla.smolvla_runtime import SmolVLARuntime, decode_b64_image

log = logging.getLogger("vla_server")


class Handler(BaseHTTPRequestHandler):
    server_version = "vla-server/1.0"
    runtime: SmolVLARuntime

    def log_message(self, fmt: str, *args) -> None:  # quieter default
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/health", "/healthz"):
            self._send(200, self.runtime.health())
        elif self.path == "/metrics":
            self._send(200, self.runtime.stats())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/act":
            self._send(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            images = {k: decode_b64_image(v) for k, v in (req.get("images") or {}).items()}
            out = self.runtime.act(
                images=images,
                instruction=req.get("instruction", ""),
                state=req.get("state"),
                seed=int(req.get("seed", 0)),
            )
            self._send(200, out)
        except Exception as exc:  # keep the server alive on bad requests
            log.exception("request failed")
            self._send(500, {"error": f"{type(exc).__name__}: {exc}"})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--repo", default="lerobot/smolvla_base")
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("loading %s on %s ...", args.repo, args.device)
    runtime = SmolVLARuntime(repo=args.repo, device=args.device)
    log.info("ready: %s", json.dumps(runtime.health()))

    Handler.runtime = runtime
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    log.info("listening on http://%s:%d", args.host, args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
