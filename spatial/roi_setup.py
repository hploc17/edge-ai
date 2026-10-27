#!/usr/bin/env python3
"""Interactive GUI tool to draw ROI and calibrate road homography on a video frame.

Compatible with Python 3.6+ / JetPack 4.x.
Allows drawing Detection ROI & Analysis ROI using mouse clicks,
entering real-world road width & road length, and auto-saving to JSON config.
"""

import json
import os
import sys
from pathlib import Path
import cv2
import numpy as np

from core.gstreamer_builder import (
    FRAME_WIDTH,
    FRAME_HEIGHT,
    capture_setup_frame,
    pixels_to_normalized,
    expanded_detection_roi,
)

_points_by_target = {"analysis": [], "detection": []}
_current_target = "analysis"


def _on_mouse(event, x, y, _flags, _userdata):
    global _points_by_target, _current_target
    if event == cv2.EVENT_LBUTTONDOWN:
        if _current_target == "analysis" and len(_points_by_target["analysis"]) >= 4:
            print("[WARN] Analysis ROI can dung 4 diem. Nhan [r] de ve lai hoac [n] sang Detection ROI.")
            return
        _points_by_target[_current_target].append([int(x), int(y)])
    elif event == cv2.EVENT_RBUTTONDOWN:
        if _points_by_target[_current_target]:
            _points_by_target[_current_target].pop()


def _render_frame(base_frame):
    frame = base_frame.copy()

    # Colors: Analysis = Green (0, 255, 0), Detection = Cyan/Orange (0, 200, 255)
    target_colors = {
        "analysis": (0, 255, 0),
        "detection": (0, 200, 255),
    }

    # 1. Draw Detection ROI
    det_pts = _points_by_target["detection"]
    for idx, pt in enumerate(det_pts):
        cv2.circle(frame, (pt[0], pt[1]), 5, (0, 200, 255), -1)
    if len(det_pts) >= 2:
        for i in range(len(det_pts) - 1):
            cv2.line(frame, tuple(det_pts[i]), tuple(det_pts[i + 1]), (0, 200, 255), 2)
        if len(det_pts) >= 3:
            cv2.line(frame, tuple(det_pts[-1]), tuple(det_pts[0]), (0, 200, 255), 1)

    # 2. Draw Analysis ROI
    ana_pts = _points_by_target["analysis"]
    point_labels = ["P1 (Near-L)", "P2 (Near-R)", "P3 (Far-R)", "P4 (Far-L)"]
    for idx, pt in enumerate(ana_pts):
        cv2.circle(frame, (pt[0], pt[1]), 6, (0, 255, 0), -1)
        lbl = point_labels[idx] if idx < len(point_labels) else ("P%d" % (idx + 1))
        cv2.putText(
            frame, lbl, (pt[0] + 8, pt[1] - 8),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA
        )
    if len(ana_pts) >= 2:
        for i in range(len(ana_pts) - 1):
            cv2.line(frame, tuple(ana_pts[i]), tuple(ana_pts[i + 1]), (0, 255, 0), 2)
        if len(ana_pts) == 4:
            cv2.line(frame, tuple(ana_pts[-1]), tuple(ana_pts[0]), (0, 255, 0), 2)

    # 3. HUD Overlay
    status_text = "Dang ve: %s ROI (%d diem)" % (
        _current_target.upper(), len(_points_by_target[_current_target])
    )
    hud_lines = [
        status_text,
        "Chuot trai: Them diem | Chuot phai: Xoa diem cuoi",
        "[n]: Chuyen doi giua ANALYSIS va DETECTION | [r]: Xoa ve lai",
        "[s]: Xong & Luu cau hinh | [q]: Thoat khong luu",
    ]
    for i, line in enumerate(hud_lines):
        y = 26 + i * 22
        cv2.putText(frame, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)

    return frame


def interactive_roi_setup(source, config_output_path, sensor_id=0):
    """Grab frame from source, run interactive OpenCV window, and save config."""
    global _points_by_target, _current_target
    _points_by_target = {"analysis": [], "detection": []}
    _current_target = "analysis"

    print("[INFO] Dang chup 1 frame tu nguon: %s ..." % source)
    frame = capture_setup_frame(source, sensor_id=sensor_id)
    if frame is None or frame.shape[0] == 0:
        print("[FATAL] Khong the lay frame tu nguon video.")
        return False

    if frame.shape[1] != FRAME_WIDTH or frame.shape[0] != FRAME_HEIGHT:
        frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT), interpolation=cv2.INTER_AREA)

    window_title = "ROI Setup Tool (1280x720) - [s] de luu, [q] de thoat"
    cv2.namedWindow(window_title)
    cv2.setMouseCallback(window_title, _on_mouse)

    print("--------------------------------------------------------")
    print("[*] Huong dan ve:")
    print("  1. ANALYSIS ROI: Ve 4 diem theo thu tu (Near-Left -> Near-Right -> Far-Right -> Far-Left).")
    print("  2. DETECTION ROI: Nhan 'n' de ve them vung phat hien (hoac de trong se tu dong tao).")
    print("  3. Nhan 's' de luu cau hinh va nhap chieu dai/rong mat duong.")
    print("--------------------------------------------------------")

    saved = False
    while True:
        rendered = _render_frame(frame)
        cv2.imshow(window_title, rendered)
        key = cv2.waitKey(20) & 0xFF

        if key == ord("q"):
            print("[INFO] Huy bo cai dat ROI.")
            cv2.destroyAllWindows()
            return False

        elif key == ord("r"):
            _points_by_target[_current_target] = []
            print("[INFO] Da xoa diem cua vung %s." % _current_target)

        elif key == ord("n"):
            if _current_target == "analysis":
                if len(_points_by_target["analysis"]) != 4:
                    print("[WARN] Analysis ROI can dung 4 diem truoc khi chuyen.")
                _current_target = "detection"
                print("[INFO] Chuyen sang ve: DETECTION ROI.")
            else:
                _current_target = "analysis"
                print("[INFO] Chuyen sang ve: ANALYSIS ROI.")

        elif key == ord("s"):
            if len(_points_by_target["analysis"]) != 4:
                print("[CANH BAO] Analysis ROI bat buoc phai co DUNG 4 diem de hieu chinh van toc!")
                continue
            saved = True
            break

    cv2.destroyAllWindows()

    if not saved:
        return False

    # Neu detection ROI chua duoc ve, tu dong mo rong tu analysis ROI
    analysis_pts = _points_by_target["analysis"]
    detection_pts = _points_by_target["detection"]
    if len(detection_pts) < 3:
        print("[INFO] Tu dong tao Detection ROI tu Analysis ROI voi margin 100px.")
        detection_pts = expanded_detection_roi(analysis_pts, margin_px=100)

    # Hoi nguoi dung nhap thong so thuc te mat duong
    print("\n========================================================")
    print("  HIEU CHINH KHONG GIAN & MAT DUONG (HOMOGRAPHY)")
    print("========================================================")
    print("Analysis ROI gom 4 diem da duoc ghi nhan thanh cong.")
    print("Vui long nhap thong so doan duong that de tinh van toc (km/h):")

    def _prompt_float(prompt_text, default_val):
        try:
            val_str = input("%s [Mac dinh: %.1f]: " % (prompt_text, default_val)).strip()
            return float(val_str) if val_str else default_val
        except (ValueError, EOFError):
            return default_val

    def _prompt_int(prompt_text, default_val):
        try:
            val_str = input("%s [Mac dinh: %d]: " % (prompt_text, default_val)).strip()
            return int(val_str) if val_str else default_val
        except (ValueError, EOFError):
            return default_val

    road_width_m = _prompt_float("Nhap chieu rong mat duong (road_width_m)", 7.5)
    road_length_m = _prompt_float("Nhap chieu dai doan duong (road_length_m)", 25.0)
    lane_count = _prompt_int("Nhap so lan duong (lane_count)", 2)

    config_data = {
        "analysis_roi": pixels_to_normalized(analysis_pts),
        "calibration_image_points": pixels_to_normalized(analysis_pts),
        "calibration_point_order": [
            "P1_near_left",
            "P2_near_right",
            "P3_far_right",
            "P4_far_left"
        ],
        "detection_margin_px": 100,
        "detection_roi": pixels_to_normalized(detection_pts),
        "frame_height": FRAME_HEIGHT,
        "frame_width": FRAME_WIDTH,
        "lane_count": lane_count,
        "mode": "roi_speed_traffic_forecast",
        "road_length_m": road_length_m,
        "road_width_m": road_width_m,
        "schema_version": 1,
        "world_points_m": [
            [0.0, 0.0],
            [road_width_m, 0.0],
            [road_width_m, road_length_m],
            [0.0, road_length_m]
        ]
    }

    out_path = Path(config_output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(out_path), "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

    print("\n[SUCCESS] Da luu cau hinh moi vao: %s" % out_path)
    print("  - Kich thuoc duong: %.1fm (rong) x %.1fm (dai)" % (road_width_m, road_length_m))
    print("  - So lan duong:     %d" % lane_count)
    print("--------------------------------------------------------")

    try:
        cont_str = input("Ban co muon tiep tuc chay pipeline phan tich luon khong? (Y/n): ").strip().lower()
        if cont_str in ('n', 'no', '0'):
            return False
    except (EOFError, KeyboardInterrupt):
        return False

    return True
