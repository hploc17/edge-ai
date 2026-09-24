#!/usr/bin/env python3
"""ROI Manager module: loads, validates and manages Detection & Analysis ROIs.

Compatible with Python 3.6 (JetPack 4.x).
"""

import json
import os
from spatial.geometry_utils import point_in_polygon, bbox_bottom_center


class RoiManager(object):
    """Manages Detection ROI and Analysis ROI configurations."""

    def __init__(self, config_path=None):
        self.config_path = config_path
        self.detection_roi = []
        self.analysis_roi = []
        self.road_width_m = 7.5
        self.road_length_m = 25.0
        self.perspective_points = []
        
        if config_path and os.path.exists(config_path):
            self.load_from_file(config_path)

    def load_from_file(self, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.detection_roi = data.get("detection_roi", [])
        self.analysis_roi = data.get("analysis_roi", [])
        self.road_width_m = float(data.get("road_width_m", 7.5))
        self.road_length_m = float(data.get("road_length_m", 25.0))
        self.perspective_points = data.get("perspective_points", [])
        
        # Neu perspective_points chua co thi dung 4 dinh cua analysis_roi neu co 4 diem
        if not self.perspective_points and len(self.analysis_roi) == 4:
            self.perspective_points = self.analysis_roi

    def is_in_detection_roi(self, bbox):
        pt = bbox_bottom_center(bbox)
        return point_in_polygon(pt, self.detection_roi)

    def is_in_analysis_roi(self, bbox):
        pt = bbox_bottom_center(bbox)
        return point_in_polygon(pt, self.analysis_roi)
