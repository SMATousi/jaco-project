#!/usr/bin/env python3
"""Safe, self-stopping joint-velocity jog for the Kinova JACO2 through ros1_bridge.

Why this exists
---------------
The ROS 1 kinova driver has NO watchdog on velocity commands. A single non-zero
JointVelocity message starts the arm moving, and it keeps moving at that velocity
until it receives zeros (or you call Stop / hit the e-stop). A jog therefore must
*always* end with a zero command, which is exactly what this script guarantees -
including on Ctrl+C or any error (the stop runs in a `finally` block).

It also refuses to move unless it can confirm the bridge is actually forwarding
(a ROS 2 subscriber appears on the command topic), so we never fire a velocity
into the void and then lose the ability to stop it.

Two ways to specify the move:
  * time  - "5 deg/s for 2 s" (open loop; actual motion is a bit less than nominal
            because of ramp-up and bridge latency).
  * delta - "--delta 10" runs the velocity until the joint has ACTUALLY moved
            ~10 deg (closed loop on the bridged joint_angles feedback), then stops.
            More accurate and bounded by angle.

Usage
-----
    jog.py <joint 1-6> <deg_per_sec> <secs>          [--robot j2s6s300] [--rate HZ]
    jog.py <joint 1-6> <deg_per_sec> --delta DEG     [--robot j2s6s300] [--rate HZ]
    jog.py <joint 1-6> 0 --check                     # zeros only, verify the path
"""
from __future__ import annotations

import argparse
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_ENV = os.path.join(_HERE, "runtime_env.sh")
_REEXEC_FLAG = "_JACO_JOG_IN_ENV"


def _bootstrap():
    """If rclpy isn't importable, re-exec under the project's ROS 2 env + system Python.

    Lets you run `./scripts/jog.py ...` directly even with conda active / ROS unsourced.
    """
    if os.environ.get(_REEXEC_FLAG) == "1" or not os.path.exists(_RUNTIME_ENV):
        return
    os.environ[_REEXEC_FLAG] = "1"
    inner = 'source "$1" ros2 >/dev/null 2>&1; shift; exec python3 "$0" "$@"'
    os.execvp("bash", ["bash", "-c", inner,
                       os.path.abspath(__file__), _RUNTIME_ENV, *sys.argv[1:]])


try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

    from kinova_msgs.msg import JointVelocity, JointAngles
except ModuleNotFoundError as exc:
    _bootstrap()
    sys.stderr.write(
        f"error: {exc}\n\n"
        "Could not import rclpy. Run through the wrapper, which sets up the ROS 2\n"
        "environment and the system Python 3.12 (not conda):\n\n"
        "    scripts/jaco jog <joint 1-6> <deg/s> <secs|--delta DEG> [--check]\n"
    )
    raise SystemExit(2)


MAX_VEL = 20.0          # deg/s hard cap enforced by this helper
MAX_SECS = 10.0         # seconds hard cap
WARMUP_S = 1.5          # zeros published before any motion
STOP_S = 2.0            # zeros published after motion (flushes the API FIFO)
SUBSCRIBE_TIMEOUT_S = 15.0
READ_TIMEOUT_S = 3.0


def main() -> int:
    ap = argparse.ArgumentParser(description="Safe self-stopping joint jog (JACO2 via ros1_bridge).")
    ap.add_argument("joint", type=int, help="joint index 1..6")
    ap.add_argument("vel", type=float, help="velocity in degrees/second")
    ap.add_argument("secs", type=float, nargs="?", help="duration in seconds (omit with --delta)")
    ap.add_argument("--delta", type=float, help="stop after the joint has moved ~this many degrees")
    ap.add_argument("--robot", default="j2s6s300", help="robot prefix (default j2s6s300)")
    ap.add_argument("--rate", type=float, default=50.0, help="publish rate in Hz (default 50)")
    ap.add_argument("--check", action="store_true", help="publish zeros only (no motion)")
    args = ap.parse_args()

    use_delta = args.delta is not None
    if not 1 <= args.joint <= 6:
        print(f"error: joint must be 1..6 (got {args.joint})", file=sys.stderr)
        return 2
    if abs(args.vel) > MAX_VEL:
        print(f"error: refusing |vel| > {MAX_VEL} deg/s (got {args.vel})", file=sys.stderr)
        return 2
    if args.check:
        if args.vel != 0.0:
            print("error: --check only allows vel 0", file=sys.stderr)
            return 2
    elif use_delta:
        if args.vel == 0.0 or args.delta == 0.0:
            print("error: --delta needs a non-zero vel and delta", file=sys.stderr)
            return 2
        if abs(args.delta) > 180.0:
            print("error: refusing |delta| > 180 deg", file=sys.stderr)
            return 2
    else:
        if args.secs is None:
            print("error: provide <secs> or --delta", file=sys.stderr)
            return 2
        if not 0 < args.secs <= MAX_SECS:
            print(f"error: seconds must be in (0, {MAX_SECS}] (got {args.secs})", file=sys.stderr)
            return 2

    vel = 0.0 if args.check else args.vel
    cmd_topic = f"/{args.robot}_driver/in/joint_velocity"
    ang_topic = f"/{args.robot}_driver/out/joint_angles"

    rclpy.init()
    node = Node("jaco_jog")
    qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                     history=HistoryPolicy.KEEP_LAST)
    pub = node.create_publisher(JointVelocity, cmd_topic, qos)

    latest: dict = {}
    node.create_subscription(JointAngles, ang_topic,
                             lambda m: latest.__setitem__("v", m), 10)

    def make(v: float) -> JointVelocity:
        m = JointVelocity()
        setattr(m, f"joint{args.joint}", float(v))
        return m

    zero, target = make(0.0), make(vel)
    period = 1.0 / args.rate

    def current_angle():
        m = latest.get("v")
        return None if m is None else getattr(m, f"joint{args.joint}")

    def spin_until_angle(timeout: float):
        deadline = time.monotonic() + timeout
        while "v" not in latest and time.monotonic() < deadline and rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.1)
        return current_angle()

    def stream(msg: JointVelocity, secs: float) -> None:
        end = time.monotonic() + secs
        while time.monotonic() < end and rclpy.ok():
            pub.publish(msg)
            rclpy.spin_once(node, timeout_sec=0.0)
            time.sleep(max(0.0, period - 0.0005))

    def stream_until_delta(msg: JointVelocity, start, delta: float, max_secs: float) -> None:
        sign = 1.0 if delta >= 0 else -1.0
        end = time.monotonic() + max_secs
        while time.monotonic() < end and rclpy.ok():
            pub.publish(msg)
            rclpy.spin_once(node, timeout_sec=0.0)
            cur = current_angle()
            if start is not None and cur is not None:
                if sign * (cur - start) >= abs(delta) - 0.2:   # tolerance vs. comm delay
                    break
            time.sleep(max(0.0, period - 0.0005))

    before = spin_until_angle(READ_TIMEOUT_S)
    rc = 0
    try:
        if args.check:
            desc = "check (zeros only)"
        elif use_delta:
            desc = f"move ~{args.delta:+.1f} deg (closed loop)"
        else:
            desc = f"{vel:+.1f} deg/s for {args.secs:.1f}s (~{abs(vel) * args.secs:.1f} deg)"
        print(f"jog: joint{args.joint}  {desc}  ->  {cmd_topic}")
        print(f"joint{args.joint} before: " + ("?" if before is None else f"{before:.2f} deg"))

        # wait for the bridge to subscribe -> command *and stop* path is live
        deadline = time.monotonic() + SUBSCRIBE_TIMEOUT_S
        while pub.get_subscription_count() == 0 and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
        n = pub.get_subscription_count()
        if n == 0:
            print("ERROR: bridge never subscribed to the command topic; refusing to "
                  "send a velocity we could not guarantee stopping.", file=sys.stderr)
            return 3
        print(f"bridge subscribed ({n} subscriber(s)); warming up with zeros ...")

        stream(zero, WARMUP_S)   # confirms the stop path before we move

        if args.check:
            print("check mode: zeros only, no motion sent.")
        elif use_delta:
            if before is None:
                approx = min(MAX_SECS, abs(args.delta) / max(abs(vel), 0.1))
                print(f"no angle feedback; falling back to ~{approx:.1f}s timed move")
                stream(target, approx)
            else:
                print("moving ...")
                cap = min(MAX_SECS, abs(args.delta) / max(abs(vel), 0.1) * 3.0 + 3.0)
                stream_until_delta(target, before, args.delta, cap)
        else:
            print("moving ...")
            stream(target, args.secs)
    except KeyboardInterrupt:
        print("\ninterrupted -> stopping", file=sys.stderr)
        rc = 130
    finally:
        # ALWAYS stop, no matter how we got here.
        try:
            if pub.get_subscription_count() > 0:
                print("stopping (zeros) ...")
                stream(zero, STOP_S)
        finally:
            after = spin_until_angle(READ_TIMEOUT_S)
            if after is not None:
                delta = "" if before is None else f"  (moved {after - before:+.2f} deg)"
                print(f"joint{args.joint} after:  {after:.2f} deg{delta}")
            pub.destroy()
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()

    print("done.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
