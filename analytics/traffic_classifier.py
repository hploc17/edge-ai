#!/usr/bin/env python3
"""Traffic analytics: speed estimation, state classification and trend forecast.

Compatible with Python 3.6 (JetPack 4.x).  No external dependencies beyond
numpy (already installed via python3-opencv in the DeepStream image).

NOTE: The 5/10-minute forecast uses linear regression on recent history.
This is a trend-extrapolation method, NOT a trained machine-learning model.
"""

from __future__ import print_function

import math
import os
import time
from collections import deque

import numpy as np

from analytics.speed_estimator import (
    PerspectiveCalibration,
    StreamTimestamp,
    TrackSpeedEstimator,
)
from spatial.geometry_utils import point_in_polygon


def _compute_homography(src, dst):
    """Compute 3x3 homography matrix mapping src -> dst using DLT."""
    n = len(src)
    A = []
    for i in range(n):
        xs, ys = src[i]
        xd, yd = dst[i]
        A.append([-xs, -ys, -1, 0, 0, 0, xd * xs, xd * ys, xd])
        A.append([0, 0, 0, -xs, -ys, -1, yd * xs, yd * ys, yd])
    A = np.array(A, dtype=np.float64)
    _, _, Vt = np.linalg.svd(A)
    H = Vt[-1].reshape(3, 3)
    H = H / H[2, 2]
    return H


def _apply_homography(H, points):
    """Apply homography H to Nx2 array of points, return Nx2 array."""
    pts = points.reshape(-1, 2)
    ones = np.ones((len(pts), 1), dtype=np.float64)
    homogeneous = np.hstack([pts, ones])
    transformed = homogeneous.dot(H.T)
    w = transformed[:, 2:3]
    w = np.where(np.abs(w) < 1e-10, 1e-10, w)
    result = transformed[:, :2] / w
    return result


# ---------------------------------------------------------------------------
# Congestion Thresholds & Colors Definition (Fix A2: Single Source of Truth)
# ---------------------------------------------------------------------------

CONGESTION_THRESHOLDS = {
    'FREE_MAX': 35,
    'SLOW_MAX': 65,
}

TRAFFIC_COLORS = {
    'FREE': '#10B981',      # Emerald Green
    'SLOW': '#F59E0B',      # Amber Orange
    'CONGESTED': '#EF4444', # Rose Red
    'UNKNOWN': '#6B7280',   # Gray
}

def get_traffic_color(congestion_score: int, traffic_status: str = None) -> str:
    """Hàm chuẩn hóa màu duy nhất cho toàn hệ thống (Fix A2)."""
    if traffic_status == 'CONGESTED' or congestion_score >= CONGESTION_THRESHOLDS['SLOW_MAX']:
        return TRAFFIC_COLORS['CONGESTED']
    elif traffic_status == 'SLOW' or congestion_score >= CONGESTION_THRESHOLDS['FREE_MAX']:
        return TRAFFIC_COLORS['SLOW']
    elif traffic_status == 'FREE' or congestion_score < CONGESTION_THRESHOLDS['FREE_MAX']:
        return TRAFFIC_COLORS['FREE']
    return TRAFFIC_COLORS['UNKNOWN']


# ---------------------------------------------------------------------------
# Traffic State Model
# ---------------------------------------------------------------------------

class TrafficStateModel(object):
    """Classify traffic state using speed, density and stopped ratio.

    States: UNKNOWN, FREE, SLOW, CONGESTED

    NOTE: Classification is NOT based on vehicle count alone.
    It combines:
      - average speed
      - density (veh/km/lane)
      - stopped vehicle ratio
      - state smoothing over ~10 seconds
    """

    UNKNOWN = 'UNKNOWN'
    FREE = 'FREE'
    SLOW = 'SLOW'
    CONGESTED = 'CONGESTED'

    SMOOTH_WINDOW_S = 10.0  # State smoothing window

    def __init__(self,
                 stopped_speed_kmh=5.0,
                 congested_speed_kmh=10.0,
                 slow_speed_kmh=18.0,
                 slow_density_veh_per_km_lane=140.0,
                 congested_density_veh_per_km_lane=220.0,
                 free_speed_kmh=22.0,
                 free_max_score=30.0,
                 slow_min_score=35.0,
                 slow_max_score=65.0,
                 congested_min_score=65.0):
        if not (0.0 <= stopped_speed_kmh <= congested_speed_kmh <= slow_speed_kmh):
            raise ValueError('Require stopped <= congested <= slow speed thresholds')
        if not (0.0 < slow_density_veh_per_km_lane <= congested_density_veh_per_km_lane):
            raise ValueError('Require 0 < slow_density <= congested_density')

        self.stopped_speed_kmh = float(stopped_speed_kmh)
        self.congested_speed_kmh = float(congested_speed_kmh)
        self.slow_speed_kmh = float(slow_speed_kmh)
        self.slow_density = float(slow_density_veh_per_km_lane)
        self.congested_density = float(congested_density_veh_per_km_lane)
        self.free_speed_kmh = float(free_speed_kmh)
        self.free_max_score = float(free_max_score)
        self.slow_min_score = float(slow_min_score)
        self.slow_max_score = float(slow_max_score)
        self.congested_min_score = float(congested_min_score)

        # Ngưỡng thời gian phát hiện xe đứng yên / tai nạn / chết máy (Fix A3)
        self.stationary_incident_threshold_s = float(os.getenv('STATIONARY_INCIDENT_SECONDS', '30.0'))
        self._stationary_start_time = None
        self._incident_detected = False

        # Smoothing: deque of (timestamp, raw_state)
        self._state_history = deque()
        self._current_smooth = self.UNKNOWN

    def classify(self, avg_speed_kmh, density, stopped_ratio, timestamp=None,
                 median_speed_kmh=None, vehicle_count=None, max_speed_kmh=None):
        """Return smoothed traffic state string and congestion score 0-100.

        avg_speed_kmh: None if speed not yet available
        density: PCE density in PCU/km/lane (float)
        stopped_ratio: fraction of vehicles stopped (0.0 - 1.0)
        timestamp: current time seconds (default time.time())
        median_speed_kmh: median speed for robust outlier rejection
        vehicle_count: current total vehicle count in ROI (int or None)
        max_speed_kmh: highest measured vehicle speed in ROI (float or None)
        """
        if timestamp is None:
            timestamp = time.time()
        raw = self._raw_classify(
            avg_speed_kmh, density, stopped_ratio,
            median_speed_kmh=median_speed_kmh,
            vehicle_count=vehicle_count,
            max_speed_kmh=max_speed_kmh,
            timestamp=timestamp
        )
        self._state_history.append((float(timestamp), raw))

        # Prune entries outside smoothing window
        cutoff = timestamp - self.SMOOTH_WINDOW_S
        while self._state_history and self._state_history[0][0] < cutoff:
            self._state_history.popleft()

        # Majority vote within window
        counts = {self.FREE: 0, self.SLOW: 0, self.CONGESTED: 0, self.UNKNOWN: 0}
        for _, s in self._state_history:
            counts[s] = counts.get(s, 0) + 1
        smooth = max(counts, key=counts.get)
        self._current_smooth = smooth

        score = self._congestion_score(
            avg_speed_kmh, density, stopped_ratio,
            state=smooth, median_speed_kmh=median_speed_kmh,
            vehicle_count=vehicle_count
        )
        return smooth, score

    def _raw_classify(self, avg_speed_kmh, density, stopped_ratio,
                      median_speed_kmh=None, vehicle_count=None, max_speed_kmh=None,
                      timestamp=None):
        effective_speed = median_speed_kmh if median_speed_kmh is not None else avg_speed_kmh
        if effective_speed is None:
            return self.UNKNOWN

        # Guard Level 0: Low vehicle count guard & Stationary Incident Detection (Fix A3)
        # Trên một đoạn đường, <= 2 xe không thể tạo thành kẹt xe diện rộng,
        # NHƯNG nếu xe đứng yên bất động kéo dài quá ngưỡng (vd > 30s) -> Kích hoạt cảnh báo sự cố SLOW
        if vehicle_count is not None:
            if vehicle_count <= 2:
                if vehicle_count > 0 and stopped_ratio >= 0.50:
                    now_ts = float(timestamp) if timestamp is not None else time.time()
                    if self._stationary_start_time is None:
                        self._stationary_start_time = now_ts
                    stationary_dur = now_ts - self._stationary_start_time
                    if stationary_dur >= self.stationary_incident_threshold_s:
                        self._incident_detected = True
                        return self.SLOW
                else:
                    self._stationary_start_time = None
                    self._incident_detected = False
                return self.FREE
            if vehicle_count <= 4 and density < self.slow_density:
                # Nếu có xe đang lưu thông tốt (>= 20 km/h), đảm bảo là FREE
                if max_speed_kmh is not None and max_speed_kmh >= 20.0:
                    return self.FREE
                if stopped_ratio >= 0.50:
                    return self.SLOW
                return self.FREE

        # Gating Level 1: Free Flow Override (Dòng mao dẫn xe máy: trôi thoát tự do)
        # Nếu tốc độ >= free_speed (22 km/h) và tỷ lệ dừng thấp (< 15%), bắt buộc là FREE
        if effective_speed >= self.free_speed_kmh and stopped_ratio < 0.15:
            return self.FREE

        # Gating Level 1.5: Moving vehicle override khi mật độ thấp
        # Nếu mật độ chưa đạt ngưỡng chậm (density < slow_density) và có phương tiện chạy nhanh >= 25 km/h,
        # hoặc tốc độ trung vị >= free_speed, không thể phân loại CONGESTED
        if density < self.slow_density and (
            (max_speed_kmh is not None and max_speed_kmh >= 25.0) or
            (effective_speed >= self.free_speed_kmh)
        ):
            if stopped_ratio >= 0.50:
                return self.SLOW
            return self.FREE

        # Gating Level 2: Congested Gate (Chỉ tắc khi dừng bánh nặng hoặc tốc độ cực thấp kèm mật độ cao)
        speed_congested = effective_speed <= self.congested_speed_kmh
        speed_slow = effective_speed <= self.slow_speed_kmh
        density_congested = density >= self.congested_density
        density_slow = density >= self.slow_density
        stopped_heavy = stopped_ratio >= 0.30

        if (speed_congested or stopped_heavy) and (density_congested or stopped_ratio >= 0.40):
            return self.CONGESTED
        if speed_congested and (density_slow or stopped_ratio >= 0.25):
            return self.CONGESTED

        # Gating Level 3: Slow Flow
        if speed_slow or density_congested or stopped_ratio >= 0.15 or density_slow:
            return self.SLOW

        return self.FREE

    def _congestion_score(self, avg_speed_kmh, density, stopped_ratio, state=None,
                          median_speed_kmh=None, vehicle_count=None):
        """Compute congestion score 0-100 with balanced physical weights:
        - 50% Speed factor (vận tốc trôi thoát)
        - 30% Stopped ratio factor (tỷ lệ xe dừng dồn ứ)
        - 20% Density factor (mật độ chiếm dụng PCE)
        Gated by classified state to ensure zero score/status contradiction.
        """
        effective_speed = median_speed_kmh if median_speed_kmh is not None else avg_speed_kmh
        if density <= 0.0 and (effective_speed is None or effective_speed >= self.free_speed_kmh):
            return 0

        # Guard for low vehicle count (Fix A3: <= 2 xe bình thường <= 15, nếu tai nạn/chết máy lâu dài đạt mức cảnh báo)
        if vehicle_count is not None and vehicle_count <= 2:
            if getattr(self, '_incident_detected', False):
                return 45  # Mức điểm cảnh báo SLOW (35-65) khi phát hiện sự cố đứng yên kéo dài
            return min(15, int(round(stopped_ratio * 15.0)))

        score = 0.0

        # 1. Speed component (0-50 pts):
        # Vận tốc >= 25 km/h -> 0 pts. Vận tốc = 0 km/h -> 50 pts.
        if effective_speed is not None:
            speed_ref = max(self.free_speed_kmh, 25.0)
            speed_score = max(0.0, 50.0 * (1.0 - effective_speed / speed_ref))
            score += min(50.0, speed_score)
        else:
            score += 15.0  # Mức trung hòa khi chưa đo được vận tốc

        # 2. Stopped ratio component (0-30 pts):
        # Dấu hiệu rõ ràng nhất của kẹt xe cục bộ (tỷ lệ dừng >= 35% ăn trọn 30 pts)
        stopped_score = min(30.0, 30.0 * (stopped_ratio / 0.35))
        score += stopped_score

        # 3. Density component (0-20 pts):
        # Mật độ quy đổi xe con PCE so với năng lực thông hành
        if self.congested_density > 0:
            density_score = min(20.0, 20.0 * (density / self.congested_density))
            score += density_score

        # Gating congestion_score theo traffic state để nhãn và điểm không mâu thuẫn
        if state == self.FREE:
            score = min(float(self.free_max_score), score)
        elif state == self.SLOW:
            score = max(float(self.slow_min_score), min(float(self.slow_max_score), score))
        elif state == self.CONGESTED:
            score = max(float(self.congested_min_score), score)

        return int(round(min(100.0, max(0.0, score))))


# ---------------------------------------------------------------------------
# Traffic Analyzer (density, flow, forecast)
# ---------------------------------------------------------------------------

class TrafficAnalyzer(object):
    """Compute density, flow and 5/10-minute trend forecast.

    NOTE: roi_entry_rate_veh_per_min counts NEW track IDs confirmed in the
    Analysis ROI within the last 60 seconds.  This is NOT equivalent to
    line-crossing flow because vehicles that were already in the ROI when
    the system started, or that re-enter, may be double-counted or missed.
    Use estimated_flow_veh_per_min (= density * avg_speed * lane_count) for
    a more physically meaningful flow estimate.

    The 5/10-minute forecast uses linear regression on congestion_score
    history. It is a trend extrapolation method, NOT a trained ML model.
    """

    ENTRY_RATE_WINDOW_S = 60.0

    def __init__(self, road_length_m, lane_count,
                 state_model=None,
                 forecast_history_seconds=900.0,
                 forecast_minimum_history_seconds=300.0,
                 exclusion_polygons=None,
                 ignore_never_moved=True):
        if road_length_m <= 0:
            raise ValueError('road_length_m must be positive')
        if lane_count <= 0:
            raise ValueError('lane_count must be positive')
        if forecast_history_seconds < forecast_minimum_history_seconds:
            raise ValueError('forecast_history_seconds must be >= forecast_minimum_history_seconds')

        self._road_length_km = float(road_length_m) / 1000.0
        self._lane_count = int(lane_count)
        self._state_model = state_model or TrafficStateModel()
        self._forecast_history_s = float(forecast_history_seconds)
        self._forecast_min_history_s = float(forecast_minimum_history_seconds)
        self._exclusion_polygons = list(exclusion_polygons) if exclusion_polygons else []
        self._ignore_never_moved = bool(ignore_never_moved)

        # Entry rate: deque of (timestamp, track_id) for new confirmations
        self._entry_events = deque()
        self._seen_track_ids = set()  # Track IDs already counted for entry rate

        # Score history for forecast: deque of (timestamp, congestion_score)
        self._score_history = deque()

    def update_geometry(self, road_length_m, lane_count):
        """Update road geometry dynamically during hot-reload."""
        if road_length_m <= 0:
            raise ValueError('road_length_m must be positive')
        if lane_count <= 0:
            raise ValueError('lane_count must be positive')
        self._road_length_km = float(road_length_m) / 1000.0
        self._lane_count = int(lane_count)

    def record_presence_events(self, events):
        """Record entry events from RoiPresenceCounter for entry-rate calculation."""
        now = time.monotonic()
        for event in events:
            if event.get('event') == 'confirmed':
                track_id = event.get('track_id')
                if track_id is not None and track_id not in self._seen_track_ids:
                    self._seen_track_ids.add(track_id)
                    self._entry_events.append((now, track_id))

    def analyze(self, timestamp, presence_snapshot, speeds):
        """Compute full metrics dict.

        timestamp: current event time (seconds)
        presence_snapshot: dict from RoiPresenceCounter.snapshot()
        speeds: dict {track_id: {'speed_kmh': float}} from TrackSpeedEstimator
        Returns: metrics dict matching MQTT telemetry schema.
        """
        current_count = int(presence_snapshot.get('current_total', 0))
        counts_by_class = dict(presence_snapshot.get('current_by_class', {}))
        raw_tracks = int(presence_snapshot.get('raw_tracks', current_count))

        # QUAN TRONG: 'speeds' chua toc do CUA MOI TRACK dang duoc
        # TrackSpeedEstimator theo doi trong TOAN BO khung hinh camera,
        # khong tu dong gioi han trong Analysis ROI. Neu dung thang
        # speeds.values() de tinh avg_speed/stopped_ratio, cac xe NGOAI
        # ROI (lan nguoc chieu, xe dau ngoai vung, track moi chua on dinh
        # toc do...) se lam sai lech ket qua - day la nguyen nhan diem
        # ket xe luon cao bat ke ROI co dang un tac hay khong.
        #
        # 'current_track_ids' PHAI duoc RoiPresenceCounter.snapshot() tra
        # ve (tap track_id dang duoc xac nhan nam trong Analysis ROI).
        # Neu presence_snapshot chua co truong nay, can bo sung o
        # analytics/presence_counter.py truoc (xem ghi chu cuoi file).
        roi_track_ids = presence_snapshot.get('current_track_ids')
        if roi_track_ids is not None:
            roi_track_ids = set(int(t) for t in roi_track_ids)
            speeds = {tid: v for tid, v in speeds.items() if int(tid) in roi_track_ids}
        # Neu presence_snapshot KHONG cung cap duoc tap track_id (module
        # cu chua cap nhat), tam thoi giu nguyen speeds nhu cu NHUNG in
        # canh bao 1 lan ro rang de khong gay spam I/O lam cham he thong.
        else:
            if not getattr(self, '_warned_missing_track_ids', False):
                import sys as _sys
                _sys.stderr.write(
                    "[CANH BAO] presence_snapshot thieu 'current_track_ids' - "
                    "dang tinh toc do/stopped_ratio tren TOAN BO camera thay vi "
                    "chi trong Analysis ROI. Can bo sung truong nay o "
                    "RoiPresenceCounter.snapshot().\n"
                )
                self._warned_missing_track_ids = True

        # Compute speed stats
        speed_values = [v['speed_kmh'] for v in speeds.values() if v.get('speed_kmh') is not None]
        if speed_values:
            avg_speed = sum(speed_values) / len(speed_values)
            sorted_speeds = sorted(speed_values)
            n = len(sorted_speeds)
            if n % 2 == 1:
                median_speed = sorted_speeds[n // 2]
            else:
                median_speed = (sorted_speeds[n // 2 - 1] + sorted_speeds[n // 2]) / 2.0
            avg_speed = round(avg_speed, 2)
            median_speed = round(median_speed, 2)
        else:
            avg_speed = None
            median_speed = None

        # Stopped vehicle count:
        # Chỉ đếm xe dừng khi ĐÃ đo được vận tốc và vận tốc < stopped_threshold.
        # Bỏ qua xe chưa từng di chuyển (parked vehicles) và xe trong exclusion_polygons.
        stopped_threshold = self._state_model.stopped_speed_kmh
        active_speeds = []
        stopped_count = 0
        track_positions = presence_snapshot.get('track_positions') or {}
        for tid, v in speeds.items():
            s = v.get('speed_kmh')
            if s is None:
                continue

            # Bỏ qua xe trong danh sách polygon loại trừ (ví dụ vùng đỗ xe lề đường)
            if self._exclusion_polygons and track_positions and tid in track_positions:
                pt = track_positions[tid]
                from spatial.geometry_utils import point_in_polygon
                if any(point_in_polygon(pt, poly) for poly in self._exclusion_polygons):
                    continue

            # Bỏ qua xe chưa từng di chuyển kể từ khi quan sát (xe đỗ cố định từ đầu)
            has_moved = v.get('has_moved', True)
            if self._ignore_never_moved and not has_moved:
                continue

            active_speeds.append(s)
            if s < stopped_threshold:
                stopped_count += 1

        total_eval = max(current_count, len(active_speeds))
        stopped_ratio = (float(stopped_count) / total_eval
                         if total_eval > 0 else 0.0)

        # Density: veh / km / lane (mật độ thô số lượng xe)
        if self._road_length_km > 0 and self._lane_count > 0:
            density_raw = float(current_count) / self._road_length_km / self._lane_count
        else:
            density_raw = 0.0
        density_raw = round(density_raw, 2)

        # Hệ số quy đổi tương đương xe con (PCE - Passenger Car Equivalent theo TCVN 4054:2005 / HCM)
        # Xe máy quy đổi 0.30 PCU, xe đạp 0.20, xe tải 1.8, xe khách 2.0
        pce_weights = {
            'motorbike': 0.30,
            'motorcycle': 0.30,
            'xe_may': 0.30,
            'bicycle': 0.20,
            'xe_dap': 0.20,
            'car': 1.0,
            'o_to': 1.0,
            'truck': 1.8,
            'xe_tai': 1.8,
            'bus': 2.0,
            'xe_khach': 2.0,
            'vehicle_fire': 2.0,
        }
        if current_count == 0:
            pce_density = 0.0
        elif counts_by_class and any(c in pce_weights for c in counts_by_class):
            pce_count = sum(
                counts_by_class.get(cls, 0) * pce_weights.get(cls, 1.0)
                for cls in counts_by_class
            )
            pce_density = (float(pce_count) / self._road_length_km / self._lane_count
                           if self._road_length_km > 0 and self._lane_count > 0 else 0.0)
        else:
            pce_density = density_raw
        pce_density = round(pce_density, 2)

        # ROI entry rate (last 60 seconds)
        cutoff = float(timestamp) - self.ENTRY_RATE_WINDOW_S
        # Prune old entries using entry_events timestamps (wall clock)
        now_wall = time.monotonic()
        wall_cutoff = now_wall - self.ENTRY_RATE_WINDOW_S
        while self._entry_events and self._entry_events[0][0] < wall_cutoff:
            self._entry_events.popleft()
        roi_entry_rate = len(self._entry_events)  # count in last 60s

        # Estimated flow: q = k * v (fundamental diagram)
        # density (veh/km/lane) * avg_speed (km/h) * lane_count = veh/h per road
        if avg_speed is not None and density_raw > 0:
            estimated_flow_per_hour = density_raw * avg_speed * self._lane_count
            estimated_flow_per_min = round(estimated_flow_per_hour / 60.0, 2)
            estimated_flow_per_hour = round(estimated_flow_per_hour, 1)
        else:
            estimated_flow_per_min = 0.0
            estimated_flow_per_hour = 0.0

        # Traffic state classification (dùng pce_density và median_speed để phân loại chuẩn xác)
        max_speed = max(active_speeds) if active_speeds else None
        state, congestion_score = self._state_model.classify(
            avg_speed, pce_density, stopped_ratio, timestamp,
            median_speed_kmh=median_speed,
            vehicle_count=current_count,
            max_speed_kmh=max_speed
        )

        # Record score for forecast (use event_time for correctness in tests and real pipeline)
        self._score_history.append((float(timestamp), congestion_score))
        hist_cutoff = float(timestamp) - self._forecast_history_s
        while self._score_history and self._score_history[0][0] < hist_cutoff:
            self._score_history.popleft()

        forecast = self._compute_forecast(float(timestamp))

        return {
            'current_vehicle_count': current_count,
            'raw_tracks': raw_tracks,
            'counts_by_class': counts_by_class,
            'avg_speed_kmh': avg_speed,
            'median_speed_kmh': median_speed,
            'density_raw_veh_per_km_lane': density_raw,
            'density_pce_per_km_lane': pce_density,
            'density_veh_per_km_lane': density_raw,  # alias for backward compatibility with frontend and existing tests
            'density_pcu_per_km_lane': pce_density,  # explicit PCU alias (Fix A1)
            'roi_entry_rate_veh_per_min': roi_entry_rate,
            'estimated_flow_veh_per_min': estimated_flow_per_min,
            'estimated_flow_veh_per_hour': estimated_flow_per_hour,
            'stopped_vehicle_count': stopped_count,
            'stopped_vehicle_ratio': round(stopped_ratio, 3),
            'traffic_status': state,
            'congestion_score': congestion_score,
            'is_incident': getattr(self._state_model, '_incident_detected', False),
            'forecast': forecast,
            'current_by_class': counts_by_class,  # internal alias
        }

    def _compute_forecast(self, now_wall):
        """Linear-regression trend extrapolation for 5 and 10 minutes.

        Returns dict with ready flag and horizon predictions.
        NOTE: This is a simple statistical trend, NOT a trained ML model.
        """
        hist = list(self._score_history)
        history_seconds = hist[-1][0] - hist[0][0] if len(hist) >= 2 else 0.0

        if history_seconds < self._forecast_min_history_s or len(hist) < 10:
            return {
                'ready': False,
                'history_seconds': round(history_seconds, 1),
                'required_history_seconds': self._forecast_min_history_s,
            }

        # Linear regression on (t, score)
        times = np.array([h[0] - hist[0][0] for h in hist], dtype=np.float64)
        scores = np.array([h[1] for h in hist], dtype=np.float64)
        t_mean = times.mean()
        s_mean = scores.mean()
        num = ((times - t_mean) * (scores - s_mean)).sum()
        den = ((times - t_mean) ** 2).sum()
        slope = num / den if abs(den) > 1e-10 else 0.0
        intercept = s_mean - slope * t_mean

        # Confidence based on R²
        predicted = slope * times + intercept
        ss_res = ((scores - predicted) ** 2).sum()
        ss_tot = ((scores - s_mean) ** 2).sum()
        r2 = 1.0 - ss_res / ss_tot if abs(ss_tot) > 1e-10 else 0.0

        if r2 > 0.7:
            confidence = 'HIGH'
        elif r2 > 0.4:
            confidence = 'MEDIUM'
        else:
            confidence = 'LOW'

        t_elapsed = times[-1]
        horizons = {}
        for label, minutes in [('5m', 5), ('10m', 10)]:
            t_future = t_elapsed + minutes * 60.0
            predicted_score = int(round(max(0.0, min(100.0, slope * t_future + intercept))))
            # Derive state from predicted score
            if predicted_score >= 60:
                predicted_state = TrafficStateModel.CONGESTED
            elif predicted_score >= 30:
                predicted_state = TrafficStateModel.SLOW
            else:
                predicted_state = TrafficStateModel.FREE
            horizons[label] = {
                'status': predicted_state,
                'congestion_score': predicted_score,
                'confidence': confidence if label == '5m' else (
                    'MEDIUM' if confidence == 'HIGH' else 'LOW'
                ),
            }

        return {
            'ready': True,
            'history_seconds': round(history_seconds, 1),
            'required_history_seconds': self._forecast_min_history_s,
            'confidence': confidence,
            'horizons': horizons,
            # Alias for frontend compatibility
            'forecast_5min': horizons['5m'],
            'forecast_10min': horizons['10m'],
        }