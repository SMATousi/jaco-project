#!/usr/bin/env python3
"""Safe joint-pose move for the JACO2, used by the hand-eye calibration.

The ROS 1 kinova driver exposes an ``ArmJointAngles`` action that runs a smooth,
driver-managed joint trajectory with a 2 deg tolerance and stall detection.  This
helper wraps it so the calibration orchestrator can call it as a subprocess:

    handeye_move.py --check                    # read current angles, no motion
    handeye_move.py --target "a,b,c,d,e,f"     # absolute target, degrees
    handeye_move.py --delta  "0,0,0,20,0,0"    # relative to the current pose
    handeye_move.py --stop                     # call /in/stop, no motion

It refuses targets outside conservative joint limits, caps the per-joint move,
and on timeout/interrupt cancels the goal and (after a short grace period) calls
the driver's ``/in/stop`` service.  It never calls ``/in/start`` automatically:
after a stop the operator decides when control is resumed.

stdout is a single JSON object; human-readable progress goes to stderr.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_ENV = os.path.join(_HERE, "runtime_env.sh")
_REEXEC_FLAG = "_JACO_HANDEYE_MOVE_IN_ENV"


def _bootstrap() -> None:
    """Re-exec under the project's ROS 1 env + system Python if needed."""
    if os.environ.get(_REEXEC_FLAG) == "1" or not os.path.exists(_RUNTIME_ENV):
        return
    os.environ[_REEXEC_FLAG] = "1"
    inner = 'source "$1" ros1 >/dev/null 2>&1; shift; exec python3 "$0" "$@"'
    os.execvp("bash", ["bash", "-c", inner, os.path.abspath(__file__),
                       _RUNTIME_ENV, *sys.argv[1:]])


try:
    import actionlib
    import rospy
    from actionlib_msgs.msg import GoalStatus
    from kinova_msgs.msg import (ArmJointAnglesAction, ArmJointAnglesGoal,
                                 JointAngles)
    from kinova_msgs.srv import Stop
except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
    _bootstrap()
    sys.stderr.write(
        f"error: {exc}\n\n"
        "Could not import ROS 1 / kinova_msgs. Run through the project helper:\n\n"
        "    python3 scripts/handeye_move.py --check\n"
    )
    raise SystemExit(2)


# Conservative limits from kinova_description/urdf/j2s6s300.xacro (degrees).
LIMITS = {2: (47.0, 313.0), 3: (19.0, 341.0), 5: (30.0, 330.0)}
MARGIN_DEG = 5.0
CONTINUOUS = {1, 4, 6}

STATUS = {
    0: "PENDING", 1: "ACTIVE", 2: "PREEMPTED", 3: "SUCCEEDED",
    4: "ABORTED", 5: "REJECTED", 6: "PREEMPTING", 7: "RECALLING",
    8: "RECALLED", 9: "LOST",
}


def parse_six(text: str) -> list[float]:
    vals = [float(x) for x in text.replace(",", " ").split()]
    if len(vals) != 6:
        raise argparse.ArgumentTypeError(
            f"expected 6 comma/space separated values, got {len(vals)}")
    return vals


def emit(obj: dict) -> None:
    print(json.dumps(obj, sort_keys=True))


def get_angles(topic: str, timeout: float = 5.0) -> list[float]:
    msg = rospy.wait_for_message(topic, JointAngles, timeout=timeout)
    return [float(getattr(msg, f"joint{i}")) for i in range(1, 7)]


def wrap_into_limits(cur: list[float], raw: list[float]) -> list[float]:
    """Resolve continuous joints to the nearest equivalent; wrap revolute joints."""
    out: list[float] = []
    for i, (c, v) in enumerate(zip(cur, raw), start=1):
        if i in CONTINUOUS:
            while v - c > 180.0:
                v -= 360.0
            while v - c < -180.0:
                v += 360.0
        else:
            v = v % 360.0
        out.append(v)
    return out


def validate_target(target: list[float]) -> str | None:
    for j, (lo, hi) in LIMITS.items():
        v = target[j - 1]
        if not (lo + MARGIN_DEG <= v <= hi - MARGIN_DEG):
            return (f"joint{j}={v:.2f} deg outside safe range "
                    f"[{lo + MARGIN_DEG:.1f}, {hi - MARGIN_DEG:.1f}]")
    return None


def call_stop(stop_srv: str) -> bool:
    try:
        rospy.wait_for_service(stop_srv, timeout=2.0)
        rospy.ServiceProxy(stop_srv, Stop)()
        print(f"called {stop_srv}", file=sys.stderr)
        return True
    except Exception as exc:  # noqa: BLE001 - report and keep going
        print(f"ERROR calling {stop_srv}: {exc}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--robot", default="j2s6s300")
    ap.add_argument("--target", type=parse_six, help="absolute angles j1..j6 (deg)")
    ap.add_argument("--delta", type=parse_six, help="relative angles j1..j6 (deg)")
    ap.add_argument("--check", action="store_true", help="read/validate only, do not move")
    ap.add_argument("--stop", action="store_true", help="call the driver stop service")
    ap.add_argument("--max-delta", type=float, default=60.0,
                    help="refuse any per-joint move larger than this (deg)")
    ap.add_argument("--timeout", type=float, default=60.0,
                    help="action timeout in seconds")
    args = ap.parse_args()

    if args.target is not None and args.delta is not None:
        emit({"ok": False, "reason": "use either --target or --delta, not both"})
        return 2

    rospy.init_node("jaco_handeye_move", anonymous=True, disable_signals=True)
    ang_topic = f"/{args.robot}_driver/out/joint_angles"
    stop_srv = f"/{args.robot}_driver/in/stop"

    if args.stop:
        ok = call_stop(stop_srv)
        emit({"ok": ok, "stopped": ok})
        return 0 if ok else 1

    try:
        cur = get_angles(ang_topic)
    except Exception as exc:  # noqa: BLE001
        emit({"ok": False, "reason": f"no joint_angles feedback: {exc}"})
        return 3

    if args.target is None and args.delta is None:
        emit({"ok": True, "no_motion": True, "before": cur})
        return 0

    raw = args.target if args.target is not None else [c + d for c, d in zip(cur, args.delta)]
    target = wrap_into_limits(cur, raw)
    err = validate_target(target)
    if err:
        emit({"ok": False, "reason": err, "before": cur, "target": target})
        return 2

    deltas = [t - c for t, c in zip(target, cur)]
    biggest = max(abs(d) for d in deltas)
    if biggest > args.max_delta:
        emit({"ok": False, "before": cur, "target": target, "delta": deltas,
              "reason": f"largest per-joint move {biggest:.1f} deg > "
                        f"--max-delta {args.max_delta:.1f} deg"})
        return 2

    if args.check:
        emit({"ok": True, "no_motion": True, "before": cur,
              "target": target, "delta": deltas})
        return 0

    client = actionlib.SimpleActionClient(
        f"/{args.robot}_driver/joints_action/joint_angles", ArmJointAnglesAction)
    if not client.wait_for_server(rospy.Duration(5.0)):
        emit({"ok": False, "reason": "joint_angles action server unavailable",
              "before": cur})
        return 4

    goal = ArmJointAnglesGoal()
    for i, v in enumerate(target, start=1):
        setattr(goal.angles, f"joint{i}", float(v))

    print("current: " + " ".join(f"{v:8.2f}" for v in cur), file=sys.stderr)
    print("target : " + " ".join(f"{v:8.2f}" for v in target), file=sys.stderr)
    print("delta  : " + " ".join(f"{v:+8.2f}" for v in deltas), file=sys.stderr)

    client.send_goal(goal)
    try:
        finished = client.wait_for_result(rospy.Duration(args.timeout))
    except KeyboardInterrupt:
        print("interrupted; cancelling goal", file=sys.stderr)
        client.cancel_goal()
        rospy.sleep(0.5)
        call_stop(stop_srv)
        emit({"ok": False, "reason": "interrupted", "before": cur, "target": target})
        return 130

    if not finished:
        print(f"timeout after {args.timeout:.0f}s; cancelling goal", file=sys.stderr)
        client.cancel_goal()
        rospy.sleep(1.0)
        if client.get_state() == GoalStatus.ACTIVE:
            call_stop(stop_srv)
        emit({"ok": False, "reason": "timeout", "before": cur, "target": target})
        return 5

    state = client.get_state()
    result = client.get_result()
    after = target
    if result is not None:
        try:
            after = [float(getattr(result.angles, f"joint{i}")) for i in range(1, 7)]
        except Exception:  # noqa: BLE001 - keep the target as a fallback
            pass

    ok = state == GoalStatus.SUCCEEDED
    if not ok:
        print(f"action ended with {STATUS.get(state, state)}", file=sys.stderr)
    emit({
        "ok": ok,
        "before": cur,
        "target": target,
        "after": after,
        "state": int(state),
        "state_text": STATUS.get(state, str(state)),
    })
    return 0 if ok else 6


if __name__ == "__main__":
    raise SystemExit(main())
