#!/usr/bin/env python3
"""Run the marker-on-gripper hand-eye calibration end to end.

For each pose in ``config/handeye_poses.txt``:
    move seed -> seed+delta  (ROS 1 joint action, driver-managed)
    settle
    capture image + ArUco + FK (ROS 2)
    move back to seed
Then solve and write ``calibration/base_cam0.yaml``.

Safety:
  * a preview capture at the seed must find the marker before any motion;
  * every move goes through ``handeye_move.py`` (limits + stop on timeout);
  * a failed move aborts immediately (the driver may be stopped);
  * a failed capture returns to the seed and aborts.

Examples:
    # no motion, just check the marker is visible at the current pose
    python3 scripts/handeye_run.py --marker-size 0.0508 --dry-run

    # full run (operator holds the e-stop)
    python3 scripts/handeye_run.py --marker-size 0.0508 --yes
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shlex
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(ROOT, "scripts", "runtime_env.sh")
MOVE = os.path.join(ROOT, "scripts", "handeye_move.py")
CAPTURE = os.path.join(ROOT, "scripts", "handeye_capture.py")
SOLVE = os.path.join(ROOT, "scripts", "handeye_solve.py")
POSES = os.path.join(ROOT, "config", "handeye_poses.txt")
PY = "/usr/bin/python3"          # system Python: ROS 2 + cv2 4.6


def log(msg: str) -> None:
    print(f"[{_dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd: list[str], env_name: str, timeout: float = 180.0) -> subprocess.CompletedProcess:
    inner = (f'source {shlex.quote(ENV)} {env_name} >/dev/null 2>&1; '
             f'exec ' + " ".join(shlex.quote(str(c)) for c in cmd))
    return subprocess.run(["bash", "-c", inner], capture_output=True,
                          text=True, timeout=timeout)


def json_out(proc: subprocess.CompletedProcess) -> dict | None:
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def load_poses(path: str) -> list[list[float]]:
    poses = []
    with open(path) as fh:
        for ln, line in enumerate(fh, 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            vals = [float(v) for v in line.replace(",", " ").split()]
            if len(vals) != 6:
                raise ValueError(f"{path}:{ln}: expected 6 values, got {len(vals)}")
            if max(abs(v) for v in vals) > 35.0:
                raise ValueError(f"{path}:{ln}: |delta| > 35 deg")
            if all(abs(v) < 1e-9 for v in vals):
                continue
            poses.append(vals)
    if not poses:
        raise ValueError(f"{path}: no poses")
    return poses


def move_to(target: list[float], timeout: float = 60.0) -> dict:
    proc = run([PY, MOVE, "--target", ",".join(f"{v:.6f}" for v in target),
                "--max-delta", "45", "--timeout", str(timeout)], "ros1", timeout + 30)
    data = json_out(proc)
    if data is None:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError("move helper produced no JSON")
    return data


def capture(out: str, args: argparse.Namespace, timeout: float = 60.0) -> dict:
    proc = run([PY, CAPTURE,
                "--out", out,
                "--marker-size", f"{args.marker_size:.6f}",
                "--marker-id", str(args.marker_id),
                "--camera-frame", args.camera_frame,
                "--base-frame", args.base_frame,
                "--gripper-frame", args.gripper_frame], "ros2", timeout)
    data = json_out(proc)
    if data is None:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError("capture helper produced no JSON")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--marker-size", type=float, required=True,
                    help="measured black-square edge length, metres")
    ap.add_argument("--marker-id", type=int, default=0)
    ap.add_argument("--poses-file", default=POSES)
    ap.add_argument("--seed", default=None,
                    help="absolute seed pose j1..j6 (default: current pose)")
    ap.add_argument("--camera-frame", default="cam0_link")
    ap.add_argument("--base-frame", default="j2s6s300_link_base")
    ap.add_argument("--gripper-frame", default="j2s6s300_link_6")
    ap.add_argument("--samples-root", default=os.path.join(ROOT, "logs", "handeye", "samples"))
    ap.add_argument("--out", default=os.path.join(ROOT, "calibration", "base_cam0.yaml"))
    ap.add_argument("--min-samples", type=int, default=8)
    ap.add_argument("--settle", type=float, default=1.0,
                    help="seconds to wait after each move")
    ap.add_argument("--dry-run", action="store_true",
                    help="capture a preview only; no motion")
    ap.add_argument("--yes", action="store_true",
                    help="do not ask for confirmation")
    args = ap.parse_args()

    poses = load_poses(args.poses_file)

    # --- prerequisites -------------------------------------------------
    st = run(["bash", os.path.join(ROOT, "scripts", "jaco"), "status"], "ros1", 30)
    if "driver: running" not in st.stdout:
        log("arm driver is not running; abort")
        print(st.stdout)
        return 2
    topics = run(["ros2", "topic", "list"], "ros2", 30).stdout
    if "/cam0/camera/color/image_raw" not in topics:
        log("camera topic /cam0/camera/color/image_raw is missing; abort")
        return 2

    chk = run([PY, MOVE, "--check"], "ros1", 30)
    cur = json_out(chk)
    if not cur or not cur.get("ok"):
        log("cannot read joint feedback; abort")
        print(chk.stdout)
        return 2
    seed = ([float(v) for v in args.seed.replace(",", " ").split()]
            if args.seed else [float(v) for v in cur["before"]])
    if len(seed) != 6:
        log("--seed must have 6 values; abort")
        return 2

    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(args.samples_root, f"run_{stamp}")
    os.makedirs(run_dir, exist_ok=True)
    log(f"samples: {run_dir}")
    log("seed (deg): " + " ".join(f"{v:.2f}" for v in seed))
    log(f"poses: {len(poses)} from {args.poses_file}")

    # --- preview: the marker must be visible at the seed --------------
    preview_path = os.path.join(run_dir, "preview.json")
    log("preview capture at the seed (no motion) ...")
    preview = capture(preview_path, args)
    if not preview.get("ok"):
        log(f"preview failed: {preview.get('reason')}")
        log(f"debug image: {preview.get('debug_image')}")
        log("the marker must be visible at the seed pose before any motion.")
        return 2
    log(f"preview OK: reproj {preview['reproj_px']:.2f} px")

    if args.dry_run:
        log("dry-run: no motion. Poses that would be visited:")
        for i, d in enumerate(poses, 1):
            log(f"  {i:2d}: " + " ".join(f"{v:+.0f}" for v in d))
        return 0

    if not args.yes:
        if not sys.stdin.isatty():
            log("refusing to move without --yes (stdin is not a TTY)")
            return 2
        input(f"About to move the arm through {len(poses)} small wrist poses. "
              "E-stop in hand. Press Enter to continue, Ctrl+C to abort... ")

    # --- move / capture loop ------------------------------------------
    for idx, delta in enumerate(poses, 1):
        target = [seed[j] + delta[j] for j in range(6)]
        log(f"[{idx}/{len(poses)}] move delta "
            + " ".join(f"{v:+.0f}" for v in delta))
        try:
            m = move_to(target)
        except Exception as exc:  # noqa: BLE001
            log(f"move failed hard: {exc}; aborting")
            return 3
        if not m.get("ok"):
            log(f"move refused/failed: {m.get('reason', m.get('state_text'))}")
            log("not continuing (the driver may be stopped). Check the arm, then "
                "call /j2s6s300_driver/in/start if needed.")
            return 3

        time.sleep(args.settle)
        out = os.path.join(run_dir, f"sample_{idx:02d}.json")
        log(f"  capture -> {os.path.basename(out)}")
        try:
            c = capture(out, args)
        except Exception as exc:  # noqa: BLE001
            log(f"capture failed hard: {exc}; returning to seed")
            try:
                move_to(seed)
            except Exception as exc2:  # noqa: BLE001
                log(f"return-to-seed also failed: {exc2}")
            return 4

        if not c.get("ok"):
            log(f"  capture failed: {c.get('reason')} (debug {c.get('debug_image')})")
            log("  returning to seed and aborting")
            try:
                move_to(seed)
            except Exception as exc:  # noqa: BLE001
                log(f"return-to-seed failed: {exc}")
            return 4
        log(f"  OK: reproj {c['reproj_px']:.2f} px, "
            f"tvec {[round(v, 3) for v in c['tvec']]}")

        log("  return to seed")
        try:
            back = move_to(seed)
        except Exception as exc:  # noqa: BLE001
            log(f"return-to-seed failed hard: {exc}; aborting")
            return 3
        if not back.get("ok"):
            log(f"return-to-seed failed: {back.get('reason')}; aborting")
            return 3
        time.sleep(0.5)

    # --- solve ---------------------------------------------------------
    log("solving hand-eye ...")
    pattern = os.path.join(run_dir, "sample_*.json")
    proc = subprocess.run(
        [PY, SOLVE, "--samples", pattern, "--out", args.out,
         "--min-samples", str(args.min_samples)],
        capture_output=True, text=True)
    print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        raise SystemExit(130)
