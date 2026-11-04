#!/usr/bin/env python3
"""ROI Manager module: loads, validates and manages Detection & Analysis ROIs.

Compatible with Python 3.6 (JetPack 4.x).
"""

import json
import os
import threading
from spatial.geometry_utils import point_in_polygon, bbox_bottom_center


class RoiManager(object):
    """Manages Detection ROI and Analysis ROI configurations with thread-safe Hot Reload."""

    def __init__(self, config_path=None):
        self.config_path = config_path
        self.detection_roi = []
        self.analysis_roi = []
        self.road_width_m = 7.5
        self.road_length_m = 25.0
        self.lane_count = 2
        self.perspective_points = []
        self.lock = threading.Lock()
        
        if config_path and os.path.exists(config_path):
            self.load_from_file(config_path)

    def load_from_file(self, path):
        with self.lock:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.config_path = path
            self.detection_roi = data.get("detection_roi", [])
            self.analysis_roi = data.get("analysis_roi", [])
            self.road_width_m = float(data.get("road_width_m", 7.5))
            self.road_length_m = float(data.get("road_length_m", 25.0))
            self.lane_count = int(data.get("lane_count", 2))
            self.perspective_points = data.get("perspective_points", []) or data.get("calibration_image_points", [])
            
            # Nếu perspective_points chưa có thì dùng 4 đỉnh của analysis_roi nếu có 4 điểm
            if not self.perspective_points and len(self.analysis_roi) == 4:
                self.perspective_points = self.analysis_roi

    def update_roi(self, new_roi_data, save_path=None):
        """Cập nhật an toàn đa luồng vùng ROI và ghi ra đĩa (Mục 6 Hot-Reload)."""
        with self.lock:
            if "detection_roi" in new_roi_data:
                self.detection_roi = new_roi_data["detection_roi"]
            if "analysis_roi" in new_roi_data:
                self.analysis_roi = new_roi_data["analysis_roi"]
            if "road_width_m" in new_roi_data:
                self.road_width_m = float(new_roi_data["road_width_m"])
            if "road_length_m" in new_roi_data:
                self.road_length_m = float(new_roi_data["road_length_m"])
            if "lane_count" in new_roi_data:
                self.lane_count = int(new_roi_data["lane_count"])

            pts = new_roi_data.get("perspective_points") or new_roi_data.get("calibration_image_points")
            if pts:
                self.perspective_points = pts
            elif len(self.analysis_roi) == 4:
                self.perspective_points = self.analysis_roi

            target_path = save_path or self.config_path or "configs/roi_traffic_nano.json"
            try:
                os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
                config_export = {
                    "frame_width": 1280,
                    "frame_height": 720,
                    "detection_roi": self.detection_roi,
                    "analysis_roi": self.analysis_roi,
                    "calibration_image_points": self.perspective_points,
                    "road_width_m": self.road_width_m,
                    "road_length_m": self.road_length_m,
                    "lane_count": self.lane_count
                }
                tmp_path = target_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(config_export, f, indent=2)
                if os.path.exists(target_path):
                    os.remove(target_path)
                os.rename(tmp_path, target_path)
                self.config_path = target_path
                print(f"[ROI] Thread-safe Hot Reload: Saved new coordinates to {target_path}")
            except Exception as e:
                print(f"[ROI ERROR] Cannot persist updated ROI: {e}")

            return {
                "detection_roi_points": len(self.detection_roi),
                "analysis_roi_points": len(self.analysis_roi),
                "road_width_m": self.road_width_m,
                "road_length_m": self.road_length_m,
            }

    def is_in_detection_roi(self, bbox):
        with self.lock:
            pt = bbox_bottom_center(bbox)
            return point_in_polygon(pt, self.detection_roi)

    def is_in_analysis_roi(self, bbox):
        with self.lock:
            pt = bbox_bottom_center(bbox)
            return point_in_polygon(pt, self.analysis_roi)
