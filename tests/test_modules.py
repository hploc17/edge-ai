#!/usr/bin/env python3
"""Tests for newly modularized packages: spatial, analytics, snapshot, config."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from spatial.geometry_utils import point_in_polygon, bbox_bottom_center
from spatial.roi_manager import RoiManager
from analytics.presence_counter import RoiPresenceCounter
from analytics.speed_estimator import PerspectiveCalibration, StreamTimestamp, TrackSpeedEstimator
from analytics.traffic_classifier import TrafficStateModel
from snap.trigger_guard import SnapshotTrigger
from config.settings import FRAME_WIDTH, FRAME_HEIGHT, CONGESTION_CONFIRM_SECONDS


def test_spatial_modules():
    poly = [[0, 0], [10, 0], [10, 10], [0, 10]]
    assert point_in_polygon([5, 5], poly) is True
    assert point_in_polygon([15, 15], poly) is False
    assert bbox_bottom_center([0, 0, 10, 20]) == (5.0, 20.0)


def test_analytics_presence():
    counter = RoiPresenceCounter(
        analysis_roi=[[0, 0], [100, 0], [100, 100], [0, 100]],
        vehicle_classes=["car"],
        enter_confirm_seconds=0.1,
    )
    assert counter.snapshot()["current_total"] == 0


def test_traffic_classifier_model():
    model = TrafficStateModel()
    # High speed, low density -> FREE
    state, score = model.classify(avg_speed_kmh=50.0, density=5.0, stopped_ratio=0.0, timestamp=1.0)
    assert state == "FREE"
    assert score < 30.0


def test_snapshot_trigger_guard():
    guard = SnapshotTrigger(congestion_confirm_seconds=2.0, cooldown_seconds=5.0)
    # Free state -> No snapshot
    assert guard.check("FREE", now=1.0) is False
    # Congested starts -> Not confirmed yet
    assert guard.check("CONGESTED", now=1.5) is False
    # Congested >= 2.0s -> Trigger snapshot
    assert guard.check("CONGESTED", now=4.0) is True
    # In cooldown -> No snapshot
    assert guard.check("CONGESTED", now=5.0) is False


def test_config_settings():
    assert FRAME_WIDTH == 1280
    assert FRAME_HEIGHT == 720
    assert CONGESTION_CONFIRM_SECONDS > 0


def test_diagnostics_table():
    from main import format_diagnostics_table
    table = format_diagnostics_table(
        frame_num=100, event_time=3.333, congestion_score=45,
        traffic_status='SLOW', timing_drift=0.0012, dt_event=0.0333,
        dt_expected=0.0333,
        track_rows=[{
            'track_id': 1, 'class_name': 'car', 'speed_kmh': 15.2,
            'world_x': 3.5, 'world_y': 20.1, 'age_seconds': 2.5,
            'age_frames': 75, 'det_conf': 0.88, 'trk_conf': 0.92,
            'area_ratio': 1.05
        }]
    )
    assert '[DIAGNOSTICS]' in table
    assert 'CongestionScore=45' in table
    assert '#1' in table
    assert 'car' in table
    assert '15.2' in table
    assert 'TimingDrift=+0.0012s' in table

    # Empty rows test
    table_empty = format_diagnostics_table(
        frame_num=101, event_time=3.366, congestion_score=42,
        traffic_status='SLOW', timing_drift=0.0, dt_event=0.0333,
        dt_expected=0.0333, track_rows=[]
    )
    assert 'No tracks currently active' in table_empty

