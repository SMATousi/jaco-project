# Calibration assets

This directory holds the hand-eye calibration target and the generated
camera-to-arm extrinsics.

## ArUco target

`aruco_4x4_50_id0.png` (regenerate with `python3 scripts/make_aruco_marker.py`):

- dictionary: `DICT_4X4_50`
- id: `0`
- image: 800 × 800 px, 300 dpi
- nominal black-square edge: **50.8 mm**

### Print and attach

1. Print at **100% / “actual size”** on plain matte paper (do **not** use
   “fit to page”). Glossy paper causes reflections and unreliable detection.
2. Measure the **black square edge** with a ruler/caliper. Printers commonly
   scale by 1–3 %. Use the measured value (metres) for `--marker-size`.
3. Cut out the marker **with the white quiet zone** (the 100 px border). Keep
   the white border intact — the detector needs it.
4. Tape the marker **flat and rigidly** to the gripper/hand, facing `cam0`.
   It must not flex or shift relative to `j2s6s300_link_6` during the run.
   The back of the hand (the side away from the fingers) is usually the best
   place: it does not block the fingers and stays visible while the wrist
   rotates.
5. Keep the marker roughly 0.3–0.8 m from the camera at the calibration seed
   pose, with the square facing the lens (within ~45°).

## Generated files

| file | meaning |
|------|---------|
| `base_cam0.yaml` | validated `j2s6s300_link_base -> cam0_link` transform + metrics |
| `base_cam0_diagnostics.json` | per-method residuals and the sample list |
| `base_cam0.rejected.yaml` | written instead of `base_cam0.yaml` if the gate fails |

Publish the TF after a successful solve:

```bash
bash scripts/62_calibration_tf.sh start
bash scripts/62_calibration_tf.sh status
```

## Gate

The solver accepts a result only if:

- RMS marker-position consistency in the arm base frame **≤ 20 mm**
  (`--max-position-m`), and
- RMS corner reprojection error **≤ 3 px** (`--max-reproj-px`).

For the M1 gate (a known table point consistent across two views to 1–2 cm),
repeat the same procedure for `cam1` once its USB/video passthrough is healthy,
then compare the two cameras' estimates of the same table point.
