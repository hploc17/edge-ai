#!/usr/bin/env python3
"""Tests for gate_counter and roi_presence_counter modules."""

from __future__ import print_function

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from spatial.geometry_utils import bbox_bottom_center, point_in_polygon
from analytics.presence_counter import RoiPresenceCounter


# ── Geometry utility tests ───────────────────────────────────────────────────

class TestBboxBottomCenter:
    def test_simple(self):
        x, y = bbox_bottom_center([100, 50, 200, 150])
        assert x == 150.0 and y == 150.0

    def test_float(self):
        x, y = bbox_bottom_center([10.5, 20.0, 30.5, 40.0])
        assert abs(x - 20.5) < 0.01 and abs(y - 40.0) < 0.01


class TestPointInPolygon:
    def _rect(self):
        return [[100, 100], [300, 100], [300, 300], [100, 300]]

    def test_inside(self):
        assert point_in_polygon([200, 200], self._rect())

    def test_outside(self):
        assert not point_in_polygon([50, 50], self._rect())
        assert not point_in_polygon([350, 200], self._rect())

    def test_on_edge(self):
        assert point_in_polygon([100, 200], self._rect())

    def test_empty_polygon_returns_true(self):
        assert point_in_polygon([100, 100], [])

    def test_triangle(self):
        triangle = [[0, 0], [100, 0], [50, 100]]
        assert point_in_polygon([50, 50], triangle)
        assert not point_in_polygon([0, 100], triangle)


# ── RoiPresenceCounter tests ──────────────────────────────────────────────────

class TestRoiPresenceCounter:
    def _make_roi(self):
        return [[100, 100], [500, 100], [500, 400], [100, 400]]

    def _make_counter(self):
        return RoiPresenceCounter(
            self._make_roi(),
            vehicle_classes=('xe_may', 'o_to'),
            enter_confirm_seconds=0.1,
            exit_confirm_seconds=0.2,
            lost_timeout_seconds=1.0,
        )

    def _obj(self, track_id, class_name, px, py):
        return {
            'track_id': track_id,
            'class_name': class_name,
            'bbox': [px - 10, py - 20, px + 10, py],
        }

    def test_vehicle_confirmed_after_enter_time(self):
        counter = self._make_counter()
        obj = self._obj(1, 'xe_may', 300, 250)
        counter.update([obj], timestamp=0.0)
        events = counter.update([obj], timestamp=0.15)  # > 0.1s
        confirmed = [e for e in events if e['event'] == 'confirmed']
        assert len(confirmed) == 1
        assert counter.snapshot()['current_total'] == 1

    def test_vehicle_not_confirmed_before_enter_time(self):
        counter = self._make_counter()
        obj = self._obj(1, 'o_to', 300, 250)
        counter.update([obj], timestamp=0.0)
        counter.update([obj], timestamp=0.05)  # < 0.1s
        assert counter.snapshot()['current_total'] == 0

    def test_vehicle_released_after_exit_time(self):
        counter = self._make_counter()
        obj = self._obj(1, 'xe_may', 300, 250)
        counter.update([obj], timestamp=0.0)
        counter.update([obj], timestamp=0.15)  # Confirm
        # Move outside ROI
        outside = self._obj(1, 'xe_may', 50, 50)
        counter.update([outside], timestamp=0.20)
        counter.update([outside], timestamp=0.45)  # > 0.2s outside
        assert counter.snapshot()['current_total'] == 0

    def test_non_vehicle_class_ignored(self):
        counter = self._make_counter()
        obj = self._obj(1, 'nguoi', 300, 250)  # not in vehicle_classes
        counter.update([obj], timestamp=0.0)
        counter.update([obj], timestamp=0.5)
        assert counter.snapshot()['current_total'] == 0

    def test_lost_track_released(self):
        counter = self._make_counter()
        obj = self._obj(1, 'o_to', 300, 250)
        counter.update([obj], timestamp=0.0)
        counter.update([obj], timestamp=0.15)  # Confirm
        assert counter.snapshot()['current_total'] == 1
        # No update for 2 seconds (> lost_timeout=1s)
        counter.update([], timestamp=2.15)
        assert counter.snapshot()['current_total'] == 0

    def test_multiple_vehicles(self):
        counter = self._make_counter()
        objs = [
            self._obj(1, 'xe_may', 200, 200),
            self._obj(2, 'o_to', 300, 300),
            self._obj(3, 'xe_may', 400, 200),
        ]
        counter.update(objs, timestamp=0.0)
        counter.update(objs, timestamp=0.15)
        snap = counter.snapshot()
        assert snap['current_total'] == 3
        assert snap['current_by_class']['xe_may'] == 2
        assert snap['current_by_class']['o_to'] == 1

    def test_snapshot_by_class_structure(self):
        counter = self._make_counter()
        snap = counter.snapshot()
        assert 'current_total' in snap
        assert 'current_by_class' in snap
        assert 'raw_tracks' in snap
        assert 'xe_may' in snap['current_by_class']
        assert 'o_to' in snap['current_by_class']


if __name__ == '__main__':
    import pytest as _pytest
    _pytest.main([__file__, '-v'])
