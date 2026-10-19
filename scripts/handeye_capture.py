#!/usr/bin/env python3
"""Capture one hand-eye calibration sample.

Subscribes to the colour image + camera_info of one RealSense, detects a single
ArUco marker (default DICT_4X4_50, id 0), solves its pose in the camera optical
frame, and records it together with the arm forward-kinematics pose from TF:

    T_base_gripper        (j2s6s300_link_base -> j2s6s300_link_6)
    T_target_cam          (marker -> camera optical; solvePnP convention)
    T_camera_link_optical (static, used later to publish base -> cam0_link)

The marker must be rigidly attached to the gripper.  The marker size is the
*measured* edge length of the printed black square, in metres.

stdout is a single JSON object; human-readable progress goes to stderr.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_ENV = os.path.join(_HERE, "runtime_env.sh")
_REEXEC_FLAG = "_JACO_HANDEYE_CAPTURE_IN_ENV"


def _bootstrap() -> None:
    if os.environ.get(_REEXEC_FLAG) == "1" or not os.path.exists(_RUNTIME_ENV):
        return
    os.environ[_REEXEC_FLAG] = "1"
    inner = 'source "$1" ros2 >/dev/null 2>&1; shift; exec python3 "$0" "$@"'
    os.execvp("bash", ["bash", "-c", inner, os.path.abspath(__file__),
                       _RUNTIME_ENV, *sys.argv[1:]])


try:
    import cv2
    import numpy as np
    import rclpy
    import tf2_ros
    from cv_bridge import CvBridge
    from rclpy.duration import Duration
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import CameraInfo, Image
    from tf2_ros import TransformException
except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
    _bootstrap()
    sys.stderr.write(
        f"error: {exc}\n\n"
        "Could not import ROS 2 / cv2. Run through the project helper:\n\n"
        "    python3 scripts/handeye_capture.py --marker-size 0.0508 ...\n"
    )
    raise SystemExit(2)


def emit(obj: dict) -> None:
    print(json.dumps(obj, sort_keys=True))


def quat_to_R(x: float, y: float, z: float, w: float) -> np.ndarray:
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n < 1e-12:
        return np.eye(3)
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)


def tf_to_mat(tf) -> np.ndarray:
    t = tf.transform.translation
    q = tf.transform.rotation
    T = np.eye(4)
    T[:3, :3] = quat_to_R(q.x, q.y, q.z, q.w)
    T[:3, 3] = [t.x, t.y, t.z]
    return T


def marker_object_points(size_m: float) -> np.ndarray:
    h = size_m / 2.0
    return np.array([
        [-h, +h, 0.0],
        [+h, +h, 0.0],
        [+h, -h, 0.0],
        [-h, -h, 0.0],
    ], dtype=np.float32)


def lookup(buffer, parent: str, child: str, node: Node, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline and rclpy.ok():
        try:
            return buffer.lookup_transform(parent, child, rclpy.time.Time())
        except TransformException as exc:  # noqa: PERF203 - retry loop
            last = exc
            rclpy.spin_once(node, timeout_sec=0.05)
    raise RuntimeError(f"TF {parent} -> {child} unavailable: {last}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="output sample JSON path")
    ap.add_argument("--marker-size", type=float, required=True,
                    help="measured black-square edge length (metres)")
    ap.add_argument("--marker-id", type=int, default=0)
    ap.add_argument("--dict", default="DICT_4X4_50",
                    help="OpenCV ArUco dictionary name")
    ap.add_argument("--color-topic", default="/cam0/camera/color/image_raw")
    ap.add_argument("--info-topic", default="/cam0/camera/color/camera_info")
    ap.add_argument("--base-frame", default="j2s6s300_link_base")
    ap.add_argument("--gripper-frame", default="j2s6s300_link_6")
    ap.add_argument("--camera-frame", default="cam0_link",
                    help="parent frame of the optical frame (for TF publishing)")
    ap.add_argument("--timeout", type=float, default=12.0)
    ap.add_argument("--debug-dir", default="logs/handeye")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    os.makedirs(args.debug_dir, exist_ok=True)

    rclpy.init()
    node = Node("jaco_handeye_capture")
    img_holder: dict = {}
    info_holder: dict = {}

    node.create_subscription(
        Image, args.color_topic,
        lambda m: img_holder.__setitem__("m", m), qos_profile_sensor_data)
    node.create_subscription(
        CameraInfo, args.info_topic,
        lambda m: info_holder.__setitem__("m", m), qos_profile_sensor_data)

    buffer = tf2_ros.Buffer(cache_time=Duration(seconds=10))
    tf2_ros.TransformListener(buffer, node)
    bridge = CvBridge()

    try:
        deadline = time.monotonic() + args.timeout
        while (time.monotonic() < deadline and rclpy.ok()
               and ("m" not in img_holder or "m" not in info_holder)):
            rclpy.spin_once(node, timeout_sec=0.1)

        if "m" not in img_holder or "m" not in info_holder:
            emit({"ok": False, "reason": "no image/camera_info",
                  "image": "m" in img_holder, "info": "m" in info_holder})
            return 3

        img_msg = img_holder["m"]
        info = info_holder["m"]
        img = bridge.imgmsg_to_cv2(img_msg, desired_encoding="bgr8")
        optical = img_msg.header.frame_id or "camera_color_optical_frame"

        # Give TF a moment to catch up with the latest joint state.
        T_base_gripper = tf_to_mat(lookup(buffer, args.base_frame, args.gripper_frame, node))
        T_camlink_optical = tf_to_mat(lookup(buffer, args.camera_frame, optical, node))

        K = np.array(info.k, dtype=np.float64).reshape(3, 3)
        D = np.array(info.d, dtype=np.float64)
        if K[0, 0] <= 0 or K[1, 1] <= 0:
            emit({"ok": False, "reason": "camera_info has no valid intrinsics"})
            return 3

        stamp = f"{img_msg.header.stamp.sec}_{img_msg.header.stamp.nanosec}"
        dbg_path = os.path.join(args.debug_dir, f"capture_{stamp}.png")

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        try:
            aruco_dict = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, args.dict))
            params = cv2.aruco.DetectorParameters_create()
            params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
            corners, ids, _rejected = cv2.aruco.detectMarkers(
                gray, aruco_dict, parameters=params)
        except Exception as exc:  # noqa: BLE001
            emit({"ok": False, "reason": f"ArUco detection failed: {exc}"})
            return 5

        target_idx = None
        if ids is not None:
            for k, mid in enumerate(ids.ravel().tolist()):
                if int(mid) == args.marker_id:
                    target_idx = k
                    break

        if target_idx is None:
            dbg = img.copy()
            cv2.putText(dbg, f"marker {args.marker_id} NOT found", (12, 32),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            cv2.imwrite(dbg_path, dbg)
            emit({"ok": False, "reason": "marker_not_found",
                  "marker_id": args.marker_id, "debug_image": dbg_path,
                  "image_frame": optical})
            return 2

        rvecs, tvecs, _ = cv2.aruco.estimatePoseSingleMarkers(
            [corners[target_idx]], args.marker_size, K, D)
        rvec = np.asarray(rvecs[0]).reshape(3)
        tvec = np.asarray(tvecs[0]).reshape(3)
        R = cv2.Rodrigues(rvec)[0]
        T_target_cam = np.eye(4)
        T_target_cam[:3, :3] = R
        T_target_cam[:3, 3] = tvec

        obj = marker_object_points(args.marker_size)
        proj, _ = cv2.projectPoints(obj, rvec, tvec, K, D)
        detected = corners[target_idx].reshape(4, 2).astype(np.float64)
        reproj_px = float(np.mean(np.linalg.norm(
            proj.reshape(4, 2) - detected, axis=1)))

        dbg = img.copy()
        cv2.aruco.drawDetectedMarkers(dbg, [corners[target_idx]],
                                      np.array([[args.marker_id]], dtype=np.int32))
        cv2.drawFrameAxes(dbg, K, D, rvec, tvec, args.marker_size * 0.5)
        cv2.putText(dbg,
                    f"id {args.marker_id}  reproj {reproj_px:.2f}px",
                    (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.imwrite(dbg_path, dbg)

        sample = {
            "ok": True,
            "stamp": {"sec": int(img_msg.header.stamp.sec),
                      "nanosec": int(img_msg.header.stamp.nanosec)},
            "marker_id": int(args.marker_id),
            "marker_size_m": float(args.marker_size),
            "dictionary": args.dict,
            "image_frame": optical,
            "camera_matrix": K.tolist(),
            "dist_coeffs": D.tolist(),
            "corners": detected.tolist(),
            "rvec": rvec.tolist(),
            "tvec": tvec.tolist(),
            "T_target_cam": T_target_cam.tolist(),
            "T_base_gripper": T_base_gripper.tolist(),
            "T_camera_link_cam_optical": T_camlink_optical.tolist(),
            "reproj_px": reproj_px,
            "base_frame": args.base_frame,
            "gripper_frame": args.gripper_frame,
            "camera_frame": args.camera_frame,
            "camera_optical_frame": optical,
            "debug_image": dbg_path,
        }

        with open(args.out, "w") as fh:
            json.dump(sample, fh, indent=2, sort_keys=True)
            fh.write("\n")

        print(f"saved {args.out}: reproj {reproj_px:.2f}px, "
              f"tvec {np.round(tvec, 3).tolist()}", file=sys.stderr)
        emit(sample)
        return 0
    except Exception as exc:  # noqa: BLE001 - always return JSON
        emit({"ok": False, "reason": f"capture failed: {exc}"})
        return 5
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
