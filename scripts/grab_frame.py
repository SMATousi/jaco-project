#!/usr/bin/env python3
"""Grab a single frame from a ROS 2 Image topic and save it as PNG."""
import sys
import time

import cv2
import rclpy
from cv_bridge import CvBridge
from sensor_msgs.msg import Image

topic = sys.argv[1] if len(sys.argv) > 1 else "/cam0/camera/color/image_raw"
out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/frame.png"
timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0

rclpy.init()
node = rclpy.create_node("grab_frame")
bridge = CvBridge()
holder = {}


def cb(msg):
    holder["msg"] = msg


node.create_subscription(Image, topic, cb, 1)
t0 = time.time()
while "msg" not in holder and time.time() - t0 < timeout:
    rclpy.spin_once(node, timeout_sec=0.1)

if "msg" in holder:
    msg = holder["msg"]
    encoding = "passthrough" if msg.encoding in ("16UC1", "32FC1", "mono8", "mono16") else "bgr8"
    img = bridge.imgmsg_to_cv2(msg, desired_encoding=encoding)
    cv2.imwrite(out, img)
    print(f"saved {out}: {img.shape} dtype={img.dtype} mean={img.mean():.1f}")
else:
    print(f"NO FRAME on {topic} within {timeout}s")
    sys.exit(1)

node.destroy_node()
rclpy.shutdown()
