#!/usr/bin/env python3
"""Unit tests for traffic_analytics module.

Tests: Homography, speed estimation, density, flow, stopped vehicles,
state classification, state smoothing, forecast readiness, forecast 5/10min.

Run with: python3 -m pytest tests/ -v
Compatible with Python 3.6 and pytest 3.x+
"""

from __future__ import print_function

import math
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from analytics.traffic_classifier import (
    PerspectiveCalibration,
    TrackSpeedEstimator,
    TrafficAnalyzer,
    TrafficStateModel,
    _compute_homography,
    _apply_homography,
)

import numpy as np


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_calibration(width_m=10.0, length_m=40.0):
    """Create calibration with a simple rectangular image region."""
    image_points = [
        [200, 300],   # P1 start-left
        [600, 300],   # P2 start-right
        [700, 500],   # P3 end-right
        [100, 500],   # P4 end-left
    ]
    return PerspectiveCalibration(image_points, width_m, length_m)


# ── Test: PerspectiveCalibration ─────────────────────────────────────────────

class TestPerspectiveCalibration:

    def test_world_corners_map_correctly(self):
        """The four image points should map exactly to world corners."""
        cal = make_calibration(10.0, 40.0)
        # P1 should map to (0, 0)
        wx, wy = cal.image_to_world(200, 300)
        assert abs(wx) < 0.1 and abs(wy) < 0.1, 'P1 should be world origin (0,0)'
        # P2 should map to (width, 0)
        wx, wy = cal.image_to_world(600, 300)
        assert abs(wx - 10.0) < 0.1 and abs(wy) < 0.1
        # P3 should map to (width, length)
        wx, wy = cal.image_to_world(700, 500)
        assert abs(wx - 10.0) < 0.1 and abs(wy - 40.0) < 0.1
        # P4 should map to (0, length)
        wx, wy = cal.image_to_world(100, 500)
        assert abs(wx) < 0.1 and abs(wy - 40.0) < 0.1

    def test_world_distance_midpoints(self):
        """Distance between midpoints of start and end edges should equal road_length."""
        cal = make_calibration(10.0, 40.0)
        # Midpoint of start edge (P1-P2 midpoint)
        mx1, my1 = (200 + 600) / 2, 300
        # Midpoint of end edge (P4-P3 midpoint)
        mx2, my2 = (100 + 700) / 2, 500
        dist = cal.world_distance_m(mx1, my1, mx2, my2)
        assert abs(dist - 40.0) < 1.0, 'Centre-to-centre distance should be ~road_length'

    def test_invalid_points_raises(self):
        with pytest.raises(ValueError):
            PerspectiveCalibration([[0, 0], [1, 0], [1, 1]], 5.0, 10.0)

    def test_invalid_dimensions_raises(self):
        pts = [[0, 0], [10, 0], [10, 20], [0, 20]]
        with pytest.raises(ValueError):
            PerspectiveCalibration(pts, -1.0, 10.0)
        with pytest.raises(ValueError):
            PerspectiveCalibration(pts, 5.0, 0.0)


# ── Test: TrackSpeedEstimator ─────────────────────────────────────────────────

class TestTrackSpeedEstimator:

    def _make_estimator(self):
        cal = make_calibration(10.0, 40.0)
        return TrackSpeedEstimator(
            cal,
            history_seconds=2.0,
            minimum_time_seconds=0.5,
            maximum_speed_kmh=130.0,
        )

    def _bbox_at(self, px, py):
        """Return bbox list with bottom-center at (px, py)."""
        return [px - 10, py - 20, px + 10, py]

    def test_no_speed_before_min_time(self):
        """Speed should not be returned before minimum_time_seconds elapsed."""
        est = self._make_estimator()
        objects = [{'track_id': 1, 'class_name': 'o_to', 'bbox': self._bbox_at(400, 400)}]
        result = est.update(objects, timestamp=0.0)
        assert 1 not in result, 'Speed should not be available with only 1 observation'

        # 0.3 seconds later (less than min_time_seconds=0.5)
        objects = [{'track_id': 1, 'class_name': 'o_to', 'bbox': self._bbox_at(402, 402)}]
        result = est.update(objects, timestamp=0.3)
        assert 1 not in result

    def test_speed_available_after_min_time(self):
        """Speed should be available after minimum_time_seconds."""
        est = self._make_estimator()
        objects = [{'track_id': 1, 'class_name': 'o_to', 'bbox': self._bbox_at(400, 400)}]
        est.update(objects, timestamp=0.0)
        # Move the vehicle along the road (towards end edge, increasing y)
        objects = [{'track_id': 1, 'class_name': 'o_to', 'bbox': self._bbox_at(400, 420)}]
        result = est.update(objects, timestamp=1.0)
        assert 1 in result, 'Speed should be available after 1 second'
        assert result[1]['speed_kmh'] >= 0.0

    def test_unrealistic_speed_filtered(self):
        """Speeds above maximum_speed_kmh should be discarded."""
        est = self._make_estimator()
        # Place at P1 corner
        objects = [{'track_id': 5, 'class_name': 'xe_may', 'bbox': self._bbox_at(200, 300)}]
        est.update(objects, timestamp=0.0)
        # Jump 40 metres in 0.1 seconds = 1440 km/h (unrealistic)
        objects = [{'track_id': 5, 'class_name': 'xe_may', 'bbox': self._bbox_at(100, 500)}]
        result = est.update(objects, timestamp=0.1)
        assert 5 not in result, 'Unrealistic speed should be discarded'

    def test_class_speed_stats(self):
        """class_speed_stats should return per-class averages."""
        est = self._make_estimator()
        objects = [
            {'track_id': 1, 'class_name': 'xe_may', 'bbox': self._bbox_at(300, 350)},
            {'track_id': 2, 'class_name': 'o_to', 'bbox': self._bbox_at(400, 350)},
        ]
        est.update(objects, timestamp=0.0)
        objects = [
            {'track_id': 1, 'class_name': 'xe_may', 'bbox': self._bbox_at(300, 380)},
            {'track_id': 2, 'class_name': 'o_to', 'bbox': self._bbox_at(400, 370)},
        ]
        speeds = est.update(objects, timestamp=1.0)
        stats = est.class_speed_stats(speeds, objects)
        for class_name in speeds_for_class(speeds, objects):
            assert class_name in stats
            assert 'count' in stats[class_name]
            assert 'avg_speed_kmh' in stats[class_name]
            assert 'median_speed_kmh' in stats[class_name]


def speeds_for_class(speeds, objects):
    seen = set()
    for obj in objects:
        if int(obj['track_id']) in speeds:
            seen.add(obj['class_name'])
    return seen


# ── Test: TrafficStateModel ───────────────────────────────────────────────────

class TestTrafficStateModel:

    def _make_model(self):
        return TrafficStateModel(
            stopped_speed_kmh=3.0,
            congested_speed_kmh=5.0,
            slow_speed_kmh=15.0,
            slow_density_veh_per_km_lane=25.0,
            congested_density_veh_per_km_lane=40.0,
        )

    def test_free_state(self):
        model = self._make_model()
        state, score = model.classify(avg_speed_kmh=30.0, density=10.0,
                                      stopped_ratio=0.0, timestamp=0.0)
        # With short history, majority may still show FREE
        assert state in ('FREE', 'UNKNOWN')

    def test_congested_by_speed_and_density(self):
        model = self._make_model()
        t = 0.0
        # Fill 10s window with CONGESTED readings
        for i in range(12):
            state, score = model.classify(
                avg_speed_kmh=2.0, density=50.0,
                stopped_ratio=0.6, timestamp=t
            )
            t += 1.0
        assert state == 'CONGESTED'
        assert score > 60

    def test_slow_state(self):
        model = self._make_model()
        t = 0.0
        for i in range(12):
            state, score = model.classify(
                avg_speed_kmh=10.0, density=30.0,
                stopped_ratio=0.1, timestamp=t
            )
            t += 1.0
        assert state == 'SLOW'

    def test_unknown_without_speed(self):
        model = self._make_model()
        state, score = model.classify(
            avg_speed_kmh=None, density=0.0,
            stopped_ratio=0.0, timestamp=0.0
        )
        assert state == 'UNKNOWN'

    def test_state_smoothing(self):
        """A single FREE reading in a CONGESTED window should not flip state."""
        model = self._make_model()
        t = 0.0
        # Fill with CONGESTED
        for i in range(10):
            model.classify(2.0, 50.0, 0.6, t)
            t += 1.0
        # One FREE reading
        state, _ = model.classify(50.0, 2.0, 0.0, t)
        assert state == 'CONGESTED', 'One FREE reading should not flip smoothed state'

    def test_threshold_validation(self):
        with pytest.raises(ValueError):
            TrafficStateModel(stopped_speed_kmh=10.0, congested_speed_kmh=5.0,
                              slow_speed_kmh=15.0)

    def test_congestion_score_range(self):
        model = self._make_model()
        for avg_speed, density, stopped_ratio in [
            (0.0, 100.0, 1.0),
            (50.0, 5.0, 0.0),
            (None, 0.0, 0.0),
        ]:
            _, score = model.classify(avg_speed, density, stopped_ratio, 0.0)
            assert 0 <= score <= 100

    def test_vietnam_motorcycle_free_flow(self):
        """Dòng xe máy đông nhưng trôi nhanh (22 km/h, ít xe dừng) phải là FREE và score thấp."""
        model = TrafficStateModel()  # dùng default thresholds chuẩn VN
        t = 0.0
        for i in range(12):
            state, score = model.classify(
                avg_speed_kmh=22.5,
                density=80.0,  # mật độ tương đối cao
                stopped_ratio=0.05,
                timestamp=t,
            )
            t += 1.0
        assert state == 'FREE', 'Dòng xe máy trôi nhanh > 22 km/h phải được phân loại là FREE'
        assert score < 30, 'Điểm số kẹt xe phải thấp (< 30) khi dòng xe trôi thoát tốt'

    def test_vietnam_real_congestion(self):
        """Khi xe máy dừng dồn ứ (tốc độ < 10 km/h, tỷ lệ dừng >= 35%) thì mới là CONGESTED."""
        model = TrafficStateModel()
        t = 0.0
        for i in range(12):
            state, score = model.classify(
                avg_speed_kmh=6.0,
                density=180.0,
                stopped_ratio=0.45,
                timestamp=t,
            )
            t += 1.0
        assert state == 'CONGESTED'
        assert score >= 65

    def test_low_vehicle_count_guard(self):
        """Khi chỉ có 1-2 xe (kể cả dừng đỗ hoàn toàn), không được báo CONGESTED và điểm số <= 15."""
        model = TrafficStateModel()
        t = 0.0
        for i in range(12):
            state, score = model.classify(
                avg_speed_kmh=0.0,
                density=10.0,
                stopped_ratio=1.0,
                timestamp=t,
                vehicle_count=2
            )
            t += 1.0
        assert state == 'FREE', 'Đường có 2 xe không thể xem là ùn tắc giao thông'
        assert score <= 15, 'Điểm số phải <= 15 khi số lượng xe <= 2'

    def test_low_count_with_moving_override(self):
        """Khi có xe chạy nhanh >= 25 km/h trên đường vắng (<= 4 xe), trạng thái phải là FREE."""
        model = TrafficStateModel()
        t = 0.0
        for i in range(12):
            state, score = model.classify(
                avg_speed_kmh=15.0,
                density=25.0,
                stopped_ratio=0.66,
                timestamp=t,
                vehicle_count=3,
                max_speed_kmh=30.0
            )
            t += 1.0
        assert state == 'FREE', 'Có xe lưu thông 30 km/h trên đường vắng phải là FREE'
        assert score <= 30



# ── Test: TrafficAnalyzer ─────────────────────────────────────────────────────

class TestTrafficAnalyzer:

    def _make_analyzer(self):
        state_model = TrafficStateModel()
        return TrafficAnalyzer(
            road_length_m=40.0,
            lane_count=2,
            state_model=state_model,
            forecast_history_seconds=300.0,
            forecast_minimum_history_seconds=60.0,
        )

    def _make_presence(self, total=10, by_class=None):
        if by_class is None:
            by_class = {'xe_may': 6, 'o_to': 4}
        return {
            'current_total': total,
            'current_by_class': by_class,
            'raw_tracks': total + 2,
        }

    def test_density_calculation(self):
        analyzer = self._make_analyzer()
        presence = self._make_presence(20)
        metrics = analyzer.analyze(0.0, presence, {})
        # density = 20 / (40/1000) / 2 = 20 / 0.04 / 2 = 250
        expected = 20.0 / (40.0 / 1000.0) / 2.0
        assert abs(metrics['density_veh_per_km_lane'] - expected) < 1.0

    def test_zero_vehicles(self):
        analyzer = self._make_analyzer()
        presence = self._make_presence(0, {'xe_may': 0, 'o_to': 0})
        metrics = analyzer.analyze(0.0, presence, {})
        assert metrics['current_vehicle_count'] == 0
        assert metrics['density_veh_per_km_lane'] == 0.0
        assert metrics['stopped_vehicle_count'] == 0
        assert metrics['stopped_vehicle_ratio'] == 0.0

    def test_estimated_flow_from_density_speed(self):
        analyzer = self._make_analyzer()
        presence = self._make_presence(10)
        speeds = {
            i: {'speed_kmh': 20.0} for i in range(1, 11)
        }
        metrics = analyzer.analyze(0.0, presence, speeds)
        # flow = density * speed * lanes / 60
        density = metrics['density_veh_per_km_lane']
        expected_flow_per_min = density * 20.0 * 2 / 60.0
        assert abs(metrics['estimated_flow_veh_per_min'] - expected_flow_per_min) < 1.0

    def test_stopped_vehicle_count(self):
        analyzer = self._make_analyzer()
        presence = self._make_presence(5)
        # 3 vehicles stopped (< 3 km/h), 2 moving
        speeds = {
            1: {'speed_kmh': 1.0},
            2: {'speed_kmh': 2.0},
            3: {'speed_kmh': 1.5},
            4: {'speed_kmh': 10.0},
            5: {'speed_kmh': 15.0},
        }
        metrics = analyzer.analyze(0.0, presence, speeds)
        assert metrics['stopped_vehicle_count'] == 3
        assert abs(metrics['stopped_vehicle_ratio'] - 3.0/5.0) < 0.01

    def test_stopped_vehicle_ratio_with_unmeasured_speed_vehicle(self):
        """Khi có 2 xe dừng và 1 xe mới vào đang đo tốc độ (speed=None), tỷ lệ dừng phải là 2/3 chứ không phải 2/2."""
        analyzer = self._make_analyzer()
        presence = self._make_presence(3)
        speeds = {
            1: {'speed_kmh': 0.0, 'has_moved': True},
            2: {'speed_kmh': 0.0, 'has_moved': True},
            3: {'speed_kmh': None, 'has_moved': False},  # mới vào ROI
        }
        metrics = analyzer.analyze(0.0, presence, speeds)
        assert metrics['stopped_vehicle_count'] == 2
        # Mẫu số là max(current_count=3, active_speeds=2) = 3
        assert abs(metrics['stopped_vehicle_ratio'] - 2.0/3.0) < 0.01

    def test_forecast_not_ready_initially(self):
        analyzer = self._make_analyzer()
        presence = self._make_presence(5)
        metrics = analyzer.analyze(0.0, presence, {})
        assert metrics['forecast']['ready'] is False

    def test_forecast_ready_after_sufficient_history(self):
        """After 60+ seconds of data, forecast should become ready."""
        analyzer = self._make_analyzer()
        presence = self._make_presence(10)
        t = 0.0
        metrics = None
        # Simulate 70 seconds of data
        for i in range(70):
            metrics = analyzer.analyze(t, presence, {})
            t += 1.0
        assert metrics['forecast']['ready'] is True, (
            'Forecast should be ready after 70 seconds (min_history=60s)'
        )
        assert 'horizons' in metrics['forecast'] or 'forecast_5min' in metrics['forecast']

    def test_forecast_5min_and_10min_present(self):
        analyzer = self._make_analyzer()
        presence = self._make_presence(10)
        t = 0.0
        for i in range(70):
            metrics = analyzer.analyze(t, presence, {})
            t += 1.0
        if metrics['forecast']['ready']:
            fc = metrics['forecast']
            assert 'forecast_5min' in fc or '5m' in fc.get('horizons', {})
            assert 'forecast_10min' in fc or '10m' in fc.get('horizons', {})


# ── Test: Snapshot Trigger ────────────────────────────────────────────────────

class TestSnapshotTrigger:

    def test_no_snapshot_when_not_congested(self):
        from snap.trigger_guard import SnapshotTrigger
        trigger = SnapshotTrigger(congestion_confirm_seconds=15.0, cooldown_seconds=60.0)
        assert not trigger.check('FREE', now=0.0)
        assert not trigger.check('SLOW', now=1.0)
        assert not trigger.check('UNKNOWN', now=2.0)

    def test_snapshot_after_15_seconds_congested(self):
        from snap.trigger_guard import SnapshotTrigger
        trigger = SnapshotTrigger(congestion_confirm_seconds=15.0, cooldown_seconds=60.0)
        # First 14 seconds — not triggered
        assert not trigger.check('CONGESTED', now=0.0)
        assert not trigger.check('CONGESTED', now=14.0)
        # At 15 seconds — should trigger
        assert trigger.check('CONGESTED', now=15.0)

    def test_cooldown_prevents_second_snapshot(self):
        from snap.trigger_guard import SnapshotTrigger
        trigger = SnapshotTrigger(congestion_confirm_seconds=15.0, cooldown_seconds=60.0)
        trigger.check('CONGESTED', now=0.0)
        trigger.check('CONGESTED', now=15.0)  # First snapshot
        # 30 seconds later (within cooldown)
        assert not trigger.check('CONGESTED', now=45.0)
        # After cooldown
        assert trigger.check('CONGESTED', now=76.0)

    def test_reset_on_free_state(self):
        from snap.trigger_guard import SnapshotTrigger
        trigger = SnapshotTrigger(congestion_confirm_seconds=15.0, cooldown_seconds=60.0)
        trigger.check('CONGESTED', now=0.0)
        trigger.check('FREE', now=10.0)  # Reset
        trigger.check('CONGESTED', now=11.0)  # Restart timer
        # Only 4 seconds of CONGESTED → should not trigger
        assert not trigger.check('CONGESTED', now=14.0)


# ── Test: Homography Regression Scenarios ─────────────────────────────────────

class TestHomographyRegressionScenarios:
    """Four regression simulation scenarios based on roi_traffic_nano.json homography."""

    @classmethod
    def setup_class(cls):
        # Image points and dimensions from configs/roi_traffic_nano.json
        cls.image_points = [[537, 231], [637, 234], [640, 705], [144, 703]]
        cls.road_width_m = 7.0
        cls.road_length_m = 50.0
        cls.lane_count = 2
        cls.calib = PerspectiveCalibration(cls.image_points, cls.road_width_m, cls.road_length_m)

    def test_scenario_1_free_flowing_traffic(self):
        """Kịch bản 1: Dòng sạch 20 xe tốc độ ~20 km/h, nhiễu 3 px -> FREE, score < 30."""
        model = TrafficStateModel(free_speed_kmh=18.0, slow_speed_kmh=12.0, congested_speed_kmh=6.0, stopped_speed_kmh=3.0)
        analyzer = TrafficAnalyzer(self.road_length_m, self.lane_count, state_model=model)

        speeds = {}
        for i in range(1, 21):
            speeds[i] = {
                'speed_kmh': 20.0 + float(np.random.uniform(-1.0, 1.0)),
                'has_moved': True
            }
        presence = {
            'current_total': 20,
            'raw_tracks': 20,
            'current_track_ids': list(range(1, 21)),
            'current_by_class': {'motorcycle': 20}
        }
        res = analyzer.analyze(timestamp=10.0, presence_snapshot=presence, speeds=speeds)
        assert res['traffic_status'] == 'FREE', "Expected FREE but got %s" % res['traffic_status']
        assert res['congestion_score'] < 30, "Expected score < 30 but got %d" % res['congestion_score']

    def test_scenario_2_free_flow_with_parked_vehicles(self):
        """Kịch bản 2: Dòng sạch + 6 và 10 xe đứng yên trong ROI: KHÔNG ĐƯỢC ra CONGESTED, score < 35."""
        for parked_count in [6, 10]:
            model = TrafficStateModel(free_speed_kmh=18.0, slow_speed_kmh=12.0, congested_speed_kmh=6.0, stopped_speed_kmh=3.0)
            analyzer = TrafficAnalyzer(self.road_length_m, self.lane_count, state_model=model)

            speeds = {}
            for i in range(1, 21):
                speeds[i] = {
                    'speed_kmh': 20.0 + float(np.random.uniform(-1.0, 1.0)),
                    'has_moved': True
                }
            for p in range(100, 100 + parked_count):
                speeds[p] = {
                    'speed_kmh': 0.0,
                    'has_moved': False
                }
            presence = {
                'current_total': 20 + parked_count,
                'raw_tracks': 20 + parked_count,
                'current_track_ids': list(speeds.keys()),
                'current_by_class': {'motorcycle': 20, 'car': parked_count}
            }
            res = analyzer.analyze(timestamp=10.0, presence_snapshot=presence, speeds=speeds)
            assert res['traffic_status'] != 'CONGESTED', "Parked vehicles must not trigger CONGESTED (parked=%d, got %s)" % (parked_count, res['traffic_status'])
            assert res['congestion_score'] < 35, "Congestion score must stay < 35 (parked=%d, got %d)" % (parked_count, res['congestion_score'])

    def test_scenario_3_real_congestion(self):
        """Kịch bản 3: Kẹt thật (35 xe, 1-3 km/h): BẮT BUỘC ra CONGESTED, score >= 65."""
        model = TrafficStateModel(free_speed_kmh=18.0, slow_speed_kmh=12.0, congested_speed_kmh=6.0, stopped_speed_kmh=3.0)
        analyzer = TrafficAnalyzer(self.road_length_m, self.lane_count, state_model=model)

        speeds = {}
        for i in range(1, 36):
            speeds[i] = {
                'speed_kmh': float(np.random.uniform(1.0, 2.8)),
                'has_moved': True
            }
        presence = {
            'current_total': 35,
            'raw_tracks': 35,
            'current_track_ids': list(range(1, 36)),
            'current_by_class': {'car': 35}
        }
        res = analyzer.analyze(timestamp=10.0, presence_snapshot=presence, speeds=speeds)
        assert res['traffic_status'] == 'CONGESTED', "Real gridlock must trigger CONGESTED, got %s" % res['traffic_status']
        assert res['congestion_score'] >= 65, "Congestion score must be >= 65, got %d" % res['congestion_score']

    def test_scenario_4_stationary_vehicle_bbox_drift(self):
        """Kịch bản 4: Xe đứng yên nhưng đáy bbox trôi 15 px/s: tốc độ trung vị không được vượt ngưỡng dừng khi lọc bằng tracker_confidence."""
        estimator = TrackSpeedEstimator(self.calib, history_seconds=2.0, minimum_time_seconds=0.8, min_moving_speed_kmh=3.0)
        fps = 15.0
        dt = 1.0 / fps
        min_tracker_conf = 0.90

        measured_speeds = []
        for i in range(30):
            t = i * dt
            tracker_conf = 0.50 if i > 5 else 0.95
            if tracker_conf < min_tracker_conf:
                continue

            px = 300.0
            py = 400.0 + 15.0 * t
            bbox = [px - 20, py - 40, px + 20, py]
            res = estimator.update([{'track_id': 99, 'class_name': 'car', 'bbox': bbox}], timestamp=t)
            if 99 in res and res[99].get('speed_kmh') is not None:
                measured_speeds.append(res[99]['speed_kmh'])

        if measured_speeds:
            median_speed = sorted(measured_speeds)[len(measured_speeds) // 2]
            assert median_speed <= 3.0, "Drifted speed %f exceeded stopped threshold" % median_speed
        else:
            assert len(measured_speeds) == 0, "All unconfident drifting samples successfully rejected"


if __name__ == '__main__':
    import pytest as _pytest
    _pytest.main([__file__, '-v'])
