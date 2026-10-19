#!/usr/bin/env python3
"""Generate a printable ArUco marker for the hand-eye calibration.

Default: DICT_4X4_50, id 0, 600 px marker + 100 px white quiet zone at 300 dpi.
At 300 dpi the black square is nominally 50.8 mm; printers often scale slightly,
so measure the printed square and pass the measured value to the calibration
scripts (``--marker-size``).  The solver only needs the true size, not the
nominal one.

    python3 scripts/make_aruco_marker.py
    # -> calibration/aruco_4x4_50_id0.png
"""
from __future__ import annotations

import argparse
import os

import cv2
import numpy as np


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="calibration/aruco_4x4_50_id0.png")
    ap.add_argument("--dict", default="DICT_4X4_50")
    ap.add_argument("--id", type=int, default=0)
    ap.add_argument("--size-px", type=int, default=600)
    ap.add_argument("--quiet-px", type=int, default=100)
    ap.add_argument("--dpi", type=int, default=300)
    args = ap.parse_args()

    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, args.dict))
    marker = cv2.aruco.drawMarker(dictionary, args.id, args.size_px)
    q = args.quiet_px
    img = np.full((args.size_px + 2 * q, args.size_px + 2 * q), 255, np.uint8)
    img[q:q + args.size_px, q:q + args.size_px] = marker

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    try:
        from PIL import Image
        Image.fromarray(img).save(args.out, dpi=(args.dpi, args.dpi))
    except ImportError:
        cv2.imwrite(args.out, img)

    mm = args.size_px / args.dpi * 25.4
    corners, ids, _ = cv2.aruco.detectMarkers(img, dictionary)
    ok = ids is not None and args.id in ids.ravel().tolist()
    print(f"wrote {args.out} ({img.shape[1]}x{img.shape[0]} px, {args.dpi} dpi)")
    print(f"nominal black-square edge: {mm:.1f} mm  (measure the print!)")
    print(f"self-detect: {'OK' if ok else 'FAILED'}")
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
