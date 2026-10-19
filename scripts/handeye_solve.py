#!/usr/bin/env python3
"""Solve the fixed-camera / marker-on-gripper hand-eye calibration.

Input: samples written by ``handeye_capture.py`` (``sample_*.json``).
Unknown: T_cam_optical_base (camera -> arm base).
Known per sample:
    T_base_gripper        (FK, gripper -> base)
    T_target_cam          (marker -> camera optical)
    T_camera_link_optical (static, optical -> camera_link)

Because the camera is fixed and the marker rides on the gripper, we use the
inverted eye-to-hand formulation:

    A = T_base_gripper^-1   (base -> gripper)
    B = T_target_cam        (target -> camera)
    cv2.calibrateHandEye(A, B) -> X = T_cam_optical_base

For every method OpenCV provides we compute:
  * C_i = A_i X B_i  (target -> gripper; must be constant)
  * RMS position / rotation consistency of C_i
  * RMS reprojection of the marker corners predicted through X and C
Only a method that explains the pixels and the arm motion is accepted.

Writes ``base_cam0.yaml`` (or ``*.rejected.yaml`` if the gate fails).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import math
import os
import sys

import cv2
import numpy as np
import yaml


def rot_angle_deg(R: np.ndarray) -> float:
    c = (np.trace(R) - 1.0) / 2.0
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def quat_to_R(q) -> np.ndarray:
    x, y, z, w = [float(v) for v in q]
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n < 1e-12:
        return np.eye(3)
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)


def R_to_quat(R: np.ndarray) -> np.ndarray:
    tr = float(np.trace(R))
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2.0
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2.0
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2.0
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2.0
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    q = np.array([x, y, z, w], dtype=np.float64)
    q /= np.linalg.norm(q)
    if q[3] < 0:
        q = -q
    return q


def inv_T(T: np.ndarray) -> np.ndarray:
    R = T[:3, :3]
    t = T[:3, 3]
    out = np.eye(4)
    out[:3, :3] = R.T
    out[:3, 3] = -R.T @ t
    return out


def rt_to_T(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = np.asarray(t).reshape(3)
    return T


def mean_rotation(Rs: list[np.ndarray]) -> np.ndarray:
    """Markley quaternion average (sign-independent)."""
    Q = np.array([R_to_quat(R) for R in Rs])
    M = Q.T @ Q
    _vals, vecs = np.linalg.eigh(M)
    q = vecs[:, -1]
    if q[3] < 0:
        q = -q
    return quat_to_R(q)


def mean_T(Ts: list[np.ndarray]) -> np.ndarray:
    R = mean_rotation([T[:3, :3] for T in Ts])
    t = np.mean([T[:3, 3] for T in Ts], axis=0)
    return rt_to_T(R, t)


def rms(vals: list[float]) -> float:
    return math.sqrt(float(np.mean(np.square(vals)))) if vals else float("nan")


def marker_object_points(size_m: float) -> np.ndarray:
    h = size_m / 2.0
    return np.array([
        [-h, +h, 0.0],
        [+h, +h, 0.0],
        [+h, -h, 0.0],
        [-h, -h, 0.0],
    ], dtype=np.float32)


def load_samples(pattern: str) -> list[dict]:
    out = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path) as fh:
                s = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            print(f"skip {path}: {exc}", file=sys.stderr)
            continue
        if s.get("ok") and "T_base_gripper" in s and "T_target_cam" in s:
            s["_path"] = path
            out.append(s)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--samples", default="logs/handeye/samples/sample_*.json",
                    help="glob for capture JSON files")
    ap.add_argument("--out", default="calibration/base_cam0.yaml")
    ap.add_argument("--frame-parent", default=None,
                    help="override parent frame (default: from samples)")
    ap.add_argument("--frame-child", default=None,
                    help="override child frame (default: from samples)")
    ap.add_argument("--min-samples", type=int, default=8)
    ap.add_argument("--max-position-m", type=float, default=0.02)
    ap.add_argument("--max-reproj-px", type=float, default=3.0)
    args = ap.parse_args()

    samples = load_samples(args.samples)
    if len(samples) < args.min_samples:
        print(f"ERROR: only {len(samples)} valid sample(s); need >= {args.min_samples}",
              file=sys.stderr)
        return 2

    sizes = {round(float(s["marker_size_m"]), 6) for s in samples}
    if len(sizes) != 1:
        print(f"ERROR: inconsistent marker sizes across samples: {sorted(sizes)}",
              file=sys.stderr)
        return 2
    marker_size = sizes.pop()

    A = [inv_T(np.array(s["T_base_gripper"], dtype=np.float64)) for s in samples]
    B = [np.array(s["T_target_cam"], dtype=np.float64) for s in samples]
    statics = [np.array(s["T_camera_link_cam_optical"], dtype=np.float64)
               for s in samples]

    # Rotation diversity of the gripper motion (needed for a well-posed solve).
    rel_angles = []
    for i in range(len(A)):
        for j in range(i + 1, len(A)):
            rel_angles.append(rot_angle_deg(A[i][:3, :3].T @ A[j][:3, :3]))
    max_rel = max(rel_angles) if rel_angles else 0.0

    methods = {
        "TSAI": cv2.CALIB_HAND_EYE_TSAI,
        "PARK": cv2.CALIB_HAND_EYE_PARK,
        "HORAUD": cv2.CALIB_HAND_EYE_HORAUD,
        "ANDREFF": cv2.CALIB_HAND_EYE_ANDREFF,
        "DANIILIDIS": cv2.CALIB_HAND_EYE_DANIILIDIS,
    }

    results: dict[str, dict] = {}
    for name, method in methods.items():
        try:
            R_c2b, t_c2b = cv2.calibrateHandEye(
                [a[:3, :3] for a in A], [a[:3, 3] for a in A],
                [b[:3, :3] for b in B], [b[:3, 3] for b in B],
                method=method)
        except cv2.error as exc:
            print(f"{name}: solve failed: {exc}", file=sys.stderr)
            continue

        X = rt_to_T(R_c2b, np.asarray(t_c2b).reshape(3))
        Cs = [a @ X @ b for a, b in zip(A, B)]
        C = mean_T(Cs)

        rot_errs = [rot_angle_deg(c[:3, :3].T @ C[:3, :3]) for c in Cs]
        trans_errs = [float(np.linalg.norm(c[:3, 3] - C[:3, 3])) for c in Cs]

        reproj_sq = []
        pos_errs = []
        for s, a, b in zip(samples, A, B):
            T_bg = inv_T(a)
            T_target_base = T_bg @ C
            T_target_cam_pred = inv_T(X) @ T_target_base

            K = np.array(s["camera_matrix"], dtype=np.float64)
            D = np.array(s["dist_coeffs"], dtype=np.float64)
            corners = np.array(s["corners"], dtype=np.float64).reshape(4, 2)
            obj = marker_object_points(float(s["marker_size_m"]))
            rvec, _ = cv2.Rodrigues(T_target_cam_pred[:3, :3])
            proj, _ = cv2.projectPoints(
                obj, rvec, T_target_cam_pred[:3, 3].reshape(3, 1), K, D)
            errs = np.linalg.norm(proj.reshape(4, 2) - corners, axis=1)
            reproj_sq.append(float(np.mean(errs ** 2)))

            p_fk = (T_bg @ C)[:3, 3]
            p_cam = (X @ b)[:3, 3]
            pos_errs.append(float(np.linalg.norm(p_fk - p_cam)))

        results[name] = {
            "X": X,
            "C": C,
            "rms_rotation_deg": rms(rot_errs),
            "rms_translation_m": rms(trans_errs),
            "rms_position_m": rms(pos_errs),
            "rms_reprojection_px": math.sqrt(float(np.mean(reproj_sq))),
        }

    if not results:
        print("ERROR: every hand-eye method failed", file=sys.stderr)
        return 2

    best_name = min(
        results,
        key=lambda n: (round(results[n]["rms_reprojection_px"], 6),
                        round(results[n]["rms_position_m"], 6)))
    best = results[best_name]

    print(f"samples: {len(samples)}  max relative gripper rotation: {max_rel:.1f} deg")
    print(f"{'method':<12}{'pos rms(m)':>12}{'rot rms(deg)':>14}"
          f"{'C t rms(m)':>12}{'reproj(px)':>12}")
    for name, r in results.items():
        mark = " *" if name == best_name else ""
        print(f"{name:<12}{r['rms_position_m']:12.5f}{r['rms_rotation_deg']:14.4f}"
              f"{r['rms_translation_m']:12.5f}{r['rms_reprojection_px']:12.3f}{mark}")

    if max_rel < 15.0:
        print("WARNING: less than 15 deg of relative gripper rotation; the solve "
              "is likely ill-conditioned. Add more wrist poses.", file=sys.stderr)

    # Compose base -> camera_link from the optical-frame result.
    T_camlink_opt = statics[0]
    static_spread = max(float(np.max(np.abs(s - T_camlink_opt))) for s in statics)
    if static_spread > 1e-6:
        print(f"WARNING: static camera TF spread {static_spread:.2e}", file=sys.stderr)
    T_base_camlink = best["X"] @ inv_T(T_camlink_opt)

    parent = args.frame_parent or samples[0].get("base_frame", "j2s6s300_link_base")
    child = args.frame_child or samples[0].get("camera_frame", "cam0_link")
    t = T_base_camlink[:3, 3]
    q = R_to_quat(T_base_camlink[:3, :3])

    valid = (best["rms_position_m"] <= args.max_position_m
             and best["rms_reprojection_px"] <= args.max_reproj_px)

    out = args.out
    if not valid:
        root, ext = os.path.splitext(args.out)
        out = root + ".rejected" + (ext or ".yaml")

    doc = {
        "frame_parent": parent,
        "frame_child": child,
        "translation": [float(v) for v in t],
        "rotation": [float(v) for v in q],
        "T_base_camera_link": T_base_camlink.tolist(),
        "T_cam_optical_base": best["X"].tolist(),
        "T_target_gripper": best["C"].tolist(),
        "marker": {
            "dictionary": samples[0].get("dictionary", "DICT_4X4_50"),
            "id": int(samples[0].get("marker_id", 0)),
            "size_m": float(marker_size),
        },
        "method": best_name,
        "metrics": {
            "samples": len(samples),
            "max_relative_rotation_deg": max_rel,
            "rms_position_m": best["rms_position_m"],
            "rms_rotation_deg": best["rms_rotation_deg"],
            "rms_translation_m": best["rms_translation_m"],
            "rms_reprojection_px": best["rms_reprojection_px"],
            "max_position_m": args.max_position_m,
            "max_reprojection_px": args.max_reproj_px,
        },
        "valid": bool(valid),
        "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as fh:
        yaml.safe_dump(doc, fh, sort_keys=False, default_flow_style=None)

    diag_path = os.path.splitext(out)[0] + "_diagnostics.json"
    with open(diag_path, "w") as fh:
        json.dump({
            "best": best_name,
            "valid": bool(valid),
            "max_relative_rotation_deg": max_rel,
            "methods": {
                name: {
                    "rms_position_m": r["rms_position_m"],
                    "rms_rotation_deg": r["rms_rotation_deg"],
                    "rms_translation_m": r["rms_translation_m"],
                    "rms_reprojection_px": r["rms_reprojection_px"],
                } for name, r in results.items()
            },
            "samples": [s.get("_path") for s in samples],
        }, fh, indent=2)

    print(f"\nbest: {best_name}  valid: {valid}")
    print(f"wrote {out}")
    print(f"wrote {diag_path}")
    print("TF command:")
    print("  ros2 run tf2_ros static_transform_publisher "
          f"--x {t[0]:.6f} --y {t[1]:.6f} --z {t[2]:.6f} "
          f"--qx {q[0]:.6f} --qy {q[1]:.6f} --qz {q[2]:.6f} --qw {q[3]:.6f} "
          f"--frame-id {parent} --child-frame-id {child}")

    if not valid:
        print(f"REJECTED: position rms {best['rms_position_m']:.4f} m "
              f"(limit {args.max_position_m}) / reprojection "
              f"{best['rms_reprojection_px']:.2f} px "
              f"(limit {args.max_reproj_px})", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
