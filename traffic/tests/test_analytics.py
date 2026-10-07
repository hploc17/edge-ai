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
        from snapshot.trigger_guard import SnapshotTrigger
        trigger = SnapshotTrigger(congestion_confirm_seconds=15.0, cooldown_seconds=60.0)
        assert not trigger.check('FREE', now=0.0)
        assert not trigger.check('SLOW', now=1.0)
        assert not trigger.check('UNKNOWN', now=2.0)

    def test_snapshot_after_15_seconds_congested(self):
        from snapshot.trigger_guard import SnapshotTrigger
        trigger = SnapshotTrigger(congestion_confirm_seconds=15.0, cooldown_seconds=60.0)
        # First 14 seconds — not triggered
        assert not trigger.check('CONGESTED', now=0.0)
        assert not trigger.check('CONGESTED', now=14.0)
        # At 15 seconds — should trigger
        assert trigger.check('CONGESTED', now=15.0)

    def test_cooldown_prevents_second_snapshot(self):
        from snapshot.trigger_guard import SnapshotTrigger
        trigger = SnapshotTrigger(congestion_confirm_seconds=15.0, cooldown_seconds=60.0)
        trigger.check('CONGESTED', now=0.0)
        trigger.check('CONGESTED', now=15.0)  # First snapshot
        # 30 seconds later (within cooldown)
        assert not trigger.check('CONGESTED', now=45.0)
        # After cooldown
        assert trigger.check('CONGESTED', now=76.0)

    def test_reset_on_free_state(self):
        from snapshot.trigger_guard import SnapshotTrigger
        trigger = SnapshotTrigger(congestion_confirm_seconds=15.0, cooldown_seconds=60.0)
        trigger.check('CONGESTED', now=0.0)
        trigger.check('FREE', now=10.0)  # Reset
        trigger.check('CONGESTED', now=11.0)  # Restart timer
        # Only 4 seconds of CONGESTED → should not trigger
        assert not trigger.check('CONGESTED', now=14.0)


if __name__ == '__main__':
    import pytest as _pytest
    _pytest.main([__file__, '-v'])
