#!/usr/bin/env python3
"""Traffic analytics: speed estimation, state classification and trend forecast.

Compatible with Python 3.6 (JetPack 4.x).  No external dependencies beyond
numpy (already installed via python3-opencv in the DeepStream image).

NOTE: The 5/10-minute forecast uses linear regression on recent history.
This is a trend-extrapolation method, NOT a trained machine-learning model.
"""

from __future__ import print_function

import math
import time
from collections import deque

import numpy as np

from analytics.speed_estimator import (
    PerspectiveCalibration,
    StreamTimestamp,
    TrackSpeedEstimator,
)


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
                 congested_speed_kmh=15.0,
                 slow_speed_kmh=30.0,
                 slow_density_veh_per_km_lane=80.0,
                 congested_density_veh_per_km_lane=120.0):
        if not (0.0 <= stopped_speed_kmh <= congested_speed_kmh <= slow_speed_kmh):
            raise ValueError('Require stopped <= congested <= slow speed thresholds')
        if not (0.0 < slow_density_veh_per_km_lane <= congested_density_veh_per_km_lane):
            raise ValueError('Require 0 < slow_density <= congested_density')

        self.stopped_speed_kmh = float(stopped_speed_kmh)
        self.congested_speed_kmh = float(congested_speed_kmh)
        self.slow_speed_kmh = float(slow_speed_kmh)
        self.slow_density = float(slow_density_veh_per_km_lane)
        self.congested_density = float(congested_density_veh_per_km_lane)

        # Smoothing: deque of (timestamp, raw_state)
        self._state_history = deque()
        self._current_smooth = self.UNKNOWN

    def classify(self, avg_speed_kmh, density, stopped_ratio, timestamp):
        """Return smoothed traffic state string and congestion score 0-100.

        avg_speed_kmh: None if speed not yet available
        density: veh/km/lane (float)
        stopped_ratio: fraction of vehicles stopped (0.0 - 1.0)
        timestamp: current time seconds
        """
        raw = self._raw_classify(avg_speed_kmh, density, stopped_ratio)
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

        score = self._congestion_score(avg_speed_kmh, density, stopped_ratio)
        return smooth, score

    def _raw_classify(self, avg_speed_kmh, density, stopped_ratio):
        if avg_speed_kmh is None:
            return self.UNKNOWN

        speed_congested = avg_speed_kmh <= self.congested_speed_kmh
        speed_slow = avg_speed_kmh <= self.slow_speed_kmh
        density_congested = density >= self.congested_density
        density_slow = density >= self.slow_density
        stopped_heavy = stopped_ratio >= 0.3

        if speed_congested and (density_congested or stopped_heavy):
            return self.CONGESTED
        if speed_congested or (speed_slow and density_congested):
            return self.CONGESTED
        if speed_slow or density_slow:
            return self.SLOW
        return self.FREE

    def _congestion_score(self, avg_speed_kmh, density, stopped_ratio):
        """Compute congestion score 0-100."""
        score = 0.0

        # Speed component (0-40 pts): low speed = high score
        if avg_speed_kmh is not None:
            # 0 km/h -> 40 pts, slow_speed_kmh -> 0 pts
            speed_score = max(0.0, 40.0 * (1.0 - avg_speed_kmh / max(self.slow_speed_kmh, 1.0)))
            score += min(40.0, speed_score)

        # Density component (0-40 pts)
        if self.congested_density > 0:
            density_score = min(40.0, 40.0 * density / self.congested_density)
            score += density_score

        # Stopped ratio component (0-20 pts)
        score += min(20.0, stopped_ratio * 20.0 / 0.5)

        return int(round(min(100.0, score)))


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
                 forecast_minimum_history_seconds=300.0):
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

        # Entry rate: deque of (timestamp, track_id) for new confirmations
        self._entry_events = deque()
        self._seen_track_ids = set()  # Track IDs already counted for entry rate

        # Score history for forecast: deque of (timestamp, congestion_score)
        self._score_history = deque()

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

        # Compute speed stats
        speed_values = [v['speed_kmh'] for v in speeds.values()]
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
        # Vehicles confirmed MOVING = in speeds dict AND speed >= threshold.
        # All others (no speed estimate yet, or confirmed slow) are treated as
        # potentially stopped/slow. This avoids undercounting when vehicles are
        # new to the ROI or standing still and haven't accumulated enough samples.
        stopped_threshold = self._state_model.stopped_speed_kmh
        moving_count = sum(
            1 for v in speeds.values()
            if v['speed_kmh'] >= stopped_threshold
        )
        stopped_count = max(0, current_count - moving_count)
        stopped_ratio = (float(stopped_count) / current_count
                         if current_count > 0 else 0.0)

        # Density: veh / km / lane
        if self._road_length_km > 0 and self._lane_count > 0:
            density = float(current_count) / self._road_length_km / self._lane_count
        else:
            density = 0.0
        density = round(density, 2)

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
        if avg_speed is not None and density > 0:
            estimated_flow_per_hour = density * avg_speed * self._lane_count
            estimated_flow_per_min = round(estimated_flow_per_hour / 60.0, 2)
            estimated_flow_per_hour = round(estimated_flow_per_hour, 1)
        else:
            estimated_flow_per_min = 0.0
            estimated_flow_per_hour = 0.0

        # Traffic state classification
        state, congestion_score = self._state_model.classify(
            avg_speed, density, stopped_ratio, timestamp
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
            'density_veh_per_km_lane': density,
            'roi_entry_rate_veh_per_min': roi_entry_rate,
            'estimated_flow_veh_per_min': estimated_flow_per_min,
            'estimated_flow_veh_per_hour': estimated_flow_per_hour,
            'stopped_vehicle_count': stopped_count,
            'stopped_vehicle_ratio': round(stopped_ratio, 3),
            'traffic_status': state,
            'congestion_score': congestion_score,
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
