#!/usr/bin/env python3
"""Validation tool for Perspective Calibration and Homography Speed Estimation.

Usage:
    # 1. Compare distance between 2 image points (in pixels or normalized) vs ground truth:
    python tools/validate_calibration.py --p1 537 231 --p2 144 703 --real-dist 50.0

    # 2. Validate simulated speed against ground-truth reference speed:
    python tools/validate_calibration.py --test-track --ref-speed 20.0 --fps 15.0
"""

from __future__ import print_function
import argparse
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analytics.speed_estimator import PerspectiveCalibration, TrackSpeedEstimator
from core.gstreamer_builder import normalized_to_pixels
import numpy as np


def load_calibration_from_json(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    pts = normalized_to_pixels(cfg["calibration_image_points"])
    road_w = float(cfg.get("road_width_m", 7.0))
    road_l = float(cfg.get("road_length_m", 50.0))
    calib = PerspectiveCalibration(pts, road_w, road_l)
    return calib, road_w, road_l


def validate_distance(calib, p1, p2, real_distance_m=None):
    w1 = calib.image_to_world(p1[0], p1[1])
    w2 = calib.image_to_world(p2[0], p2[1])
    computed_dist = calib.world_distance_m(p1[0], p1[1], p2[0], p2[1])

    print("------------------------------------------------------------------")
    print("CALIBRATION DISTANCE VALIDATION")
    print("------------------------------------------------------------------")
    print("Point 1 Image: (%.1f, %.1f) -> World: (%.2f, %.2f) m" % (p1[0], p1[1], w1[0], w1[1]))
    print("Point 2 Image: (%.1f, %.1f) -> World: (%.2f, %.2f) m" % (p2[0], p2[1], w2[0], w2[1]))
    print("Computed Distance by Homography: %.3f m" % computed_dist)
    if real_distance_m is not None and real_distance_m > 0:
        error_m = abs(computed_dist - real_distance_m)
        error_pct = (error_m / real_distance_m) * 100.0
        print("Ground Truth Real Distance:     %.3f m" % real_distance_m)
        print("Absolute Error:                  %.3f m" % error_m)
        print("Relative Error:                  %.2f%%" % error_pct)
    print("------------------------------------------------------------------")
    return computed_dist


def validate_track_speed(calib, ref_speed_kmh, fps=15.0, duration_s=3.0, noise_px=0.0):
    """Simulate a vehicle moving along the center line from y=10m to y=40m at ref_speed_kmh."""
    estimator = TrackSpeedEstimator(calib, history_seconds=2.0, minimum_time_seconds=0.8)
    
    # Invert world (x=3.5, y) to image (px, py)
    # Using inverse homography H_inv
    H_inv = np.linalg.inv(calib.matrix)
    v_ms = ref_speed_kmh * 1000.0 / 3600.0
    dt = 1.0 / fps
    total_frames = int(duration_s * fps)
    
    start_y = 10.0
    measured_speeds = []
    
    for i in range(total_frames):
        t = i * dt
        curr_y = start_y + v_ms * t
        if curr_y > 48.0:
            break
        # Project world (3.5, curr_y) to image coordinates
        world_pt = np.array([3.5, curr_y, 1.0], dtype=np.float64)
        img_h = H_inv.dot(world_pt)
        px = (img_h[0] / img_h[2]) + (np.random.uniform(-noise_px, noise_px) if noise_px > 0 else 0.0)
        py = (img_h[1] / img_h[2]) + (np.random.uniform(-noise_px, noise_px) if noise_px > 0 else 0.0)
        
        # Bounding box bottom-center at (px, py)
        bbox = [px - 20, py - 40, px + 20, py]
        objects = [{'track_id': 101, 'class_name': 'car', 'bbox': bbox}]
        res = estimator.update(objects, timestamp=t)
        if 101 in res and res[101].get('speed_kmh') is not None:
            measured_speeds.append(res[101]['speed_kmh'])

    print("------------------------------------------------------------------")
    print("TRACK SPEED VALIDATION")
    print("------------------------------------------------------------------")
    print("Reference Ground Truth Speed: %.2f km/h (FPS=%.1f, Noise=%.1f px)" % (ref_speed_kmh, fps, noise_px))
    if measured_speeds:
        final_speed = measured_speeds[-1]
        avg_est_speed = sum(measured_speeds) / len(measured_speeds)
        err_kmh = abs(avg_est_speed - ref_speed_kmh)
        err_pct = (err_kmh / ref_speed_kmh) * 100.0 if ref_speed_kmh > 0 else 0.0
        print("Final Estimated Speed:        %.2f km/h" % final_speed)
        print("Average Estimated Speed:      %.2f km/h" % avg_est_speed)
        print("Speed Estimation Error:       %.2f km/h (%.2f%%)" % (err_kmh, err_pct))
    else:
        print("[WARNING] Not enough samples to compute speed (duration too short).")
    print("------------------------------------------------------------------")


def main():
    import numpy  # ensure numpy available
    parser = argparse.ArgumentParser(description="Validate perspective calibration and speed estimation.")
    parser.add_argument("--config", default=str(ROOT / "configs" / "roi_traffic_nano.json"),
                        help="Path to roi_traffic_nano.json")
    parser.add_argument("--p1", nargs=2, type=float, metavar=("X1", "Y1"),
                        help="Image coordinates of point 1 (in pixels)")
    parser.add_argument("--p2", nargs=2, type=float, metavar=("X2", "Y2"),
                        help="Image coordinates of point 2 (in pixels)")
    parser.add_argument("--real-dist", type=float, default=None,
                        help="Known ground-truth distance in meters between p1 and p2")
    parser.add_argument("--test-track", action="store_true",
                        help="Run simulated vehicle track speed validation")
    parser.add_argument("--ref-speed", type=float, default=20.0,
                        help="Reference speed in km/h for track test (default: 20.0)")
    parser.add_argument("--fps", type=float, default=15.0,
                        help="Simulation FPS (default: 15.0)")
    parser.add_argument("--noise-px", type=float, default=0.0,
                        help="Random bbox jitter in pixels (default: 0.0)")

    args = parser.parse_args()
    calib, road_w, road_l = load_calibration_from_json(args.config)
    print("[INFO] Loaded calibration: width=%.1fm, length=%.1fm from %s" % (road_w, road_l, args.config))

    if args.p1 and args.p2:
        validate_distance(calib, args.p1, args.p2, args.real_dist)
    elif not args.test_track:
        # Default: validate left edge (P1 to P4) and right edge (P2 to P3)
        pts = normalized_to_pixels([
            [0.41953125, 0.32083333333333336],
            [0.828125, 0.31805555555555554],
            [0.99140625, 0.9791666666666666],
            [0.1125, 0.9763888888888889]
        ])
        print("\n--- Validating Left Boundary (P1_far_left -> P4_near_left) ---")
        validate_distance(calib, pts[0], pts[3], road_l)
        print("\n--- Validating Right Boundary (P2_far_right -> P3_near_right) ---")
        validate_distance(calib, pts[1], pts[2], road_l)
        print("\n--- Validating Far Width (P1_far_left -> P2_far_right) ---")
        validate_distance(calib, pts[0], pts[1], road_w)
        print("\n--- Validating Near Width (P4_near_left -> P3_near_right) ---")
        validate_distance(calib, pts[3], pts[2], road_w)

    if args.test_track or not (args.p1 and args.p2):
        print("\n--- Running Reference Speed Simulation (%.1f km/h) ---" % args.ref_speed)
        validate_track_speed(calib, args.ref_speed, fps=args.fps, noise_px=args.noise_px)


if __name__ == "__main__":
    main()
