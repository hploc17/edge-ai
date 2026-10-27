#!/usr/bin/env python3
"""Unit tests for traffic_classifier_v2 (Phương án 2: Dwell-Time & Context-Aware)."""

import pytest
import time
from analytics.traffic_classifier_v2 import (
    ContextAwareTrafficStateModel,
    ContextAwareTrafficAnalyzer,
)


class TestContextAwareTrafficStateModel:

    def test_low_vehicle_count_guard(self):
        """<= 2 vehicles should ALWAYS be FREE with score <= 15."""
        model = ContextAwareTrafficStateModel(context='signalized')
        # Dù xe dừng hẳn (v=0 km/h) và tỷ lệ dừng 100%
        state, score = model.classify(
            avg_speed_kmh=0.0,
            density=150.0,
            stopped_ratio=1.0,
            vehicle_count=2,
        )
        assert state == model.FREE
        assert score <= 15

    def test_signalized_grace_period_red_light(self):
        """At signalized intersection, waiting red light (0-30s) must NOT trigger CONGESTED."""
        model = ContextAwareTrafficStateModel(context='signalized', signalized_grace_period_s=30.0)

        # Giả lập 10 xe dừng đèn đỏ ở giây thứ 15
        t_now = 1000.0
        # Cập nhật dwell time: xe mới vào lúc t=985.0 -> dwell = 15.0s
        active_ids = list(range(1, 11))
        model._track_entry_times = {tid: 985.0 for tid in active_ids}
        dwell_stats = model.update_dwell_times(active_ids, t_now, stopped_track_ids=active_ids)

        assert dwell_stats['stopped_dwell_max_s'] == 15.0

        state, score = model.classify(
            avg_speed_kmh=0.0,
            density=180.0,
            stopped_ratio=1.0,
            timestamp=t_now,
            vehicle_count=10,
        )
        # Trong thời gian ân hạn 30s đèn đỏ, không được báo CONGESTED
        assert state == model.FREE
        assert score <= 30

    def test_signalized_severe_congestion_after_60s(self):
        """At signalized intersection, waiting > 60s (vượt quá 1 chu kỳ đèn) triggers CONGESTED."""
        model = ContextAwareTrafficStateModel(context='signalized', signalized_grace_period_s=30.0)

        t_now = 1000.0
        # Xe đã dừng kẹt từ 70s trước (t=930.0)
        active_ids = list(range(1, 15))
        model._track_entry_times = {tid: 930.0 for tid in active_ids}
        dwell_stats = model.update_dwell_times(active_ids, t_now, stopped_track_ids=active_ids)

        assert dwell_stats['stopped_dwell_max_s'] == 70.0

        # Làm đầy lịch sử 10s để vượt qua smooth filter
        for t in range(990, 1001):
            state, score = model.classify(
                avg_speed_kmh=2.0,
                density=200.0,
                stopped_ratio=0.85,
                timestamp=float(t),
                vehicle_count=14,
            )

        assert state == model.CONGESTED
        assert score >= 65

    def test_midblock_normal_traffic(self):
        """On midblock road, dwell <= 5s is FREE."""
        model = ContextAwareTrafficStateModel(context='midblock')
        t_now = 1000.0
        active_ids = [101, 102, 103, 104, 105]
        model._track_entry_times = {tid: 997.0 for tid in active_ids}  # dwell = 3s
        model.update_dwell_times(active_ids, t_now)

        state, score = model.classify(
            avg_speed_kmh=20.0,
            density=80.0,
            stopped_ratio=0.0,
            timestamp=t_now,
            vehicle_count=5,
        )
        assert state == model.FREE
        assert score <= 30

    def test_midblock_stopped_congestion(self):
        """On midblock road, stopping > 15s triggers CONGESTED."""
        model = ContextAwareTrafficStateModel(context='midblock', midblock_slow_threshold_s=15.0)
        t_now = 1000.0
        active_ids = list(range(1, 10))
        # Dừng 25s trên đoạn không đèn
        model._track_entry_times = {tid: 975.0 for tid in active_ids}
        model.update_dwell_times(active_ids, t_now, stopped_track_ids=active_ids)

        for t in range(990, 1001):
            state, score = model.classify(
                avg_speed_kmh=1.0,
                density=160.0,
                stopped_ratio=0.7,
                timestamp=float(t),
                vehicle_count=9,
            )
        assert state == model.CONGESTED
        assert score >= 65


class TestContextAwareTrafficAnalyzer:

    def test_analyzer_integration(self):
        """Test full analyzer pipeline with Dwell Time telemetry output."""
        analyzer = ContextAwareTrafficAnalyzer(road_length_m=20.0, lane_count=2)
        presence = {
            'current_total': 5,
            'current_by_class': {'motorbike': 4, 'car': 1},
            'current_track_ids': [1, 2, 3, 4, 5],
            'raw_tracks': 5,
        }
        speeds = {
            1: {'speed_kmh': 22.0, 'has_moved': True},
            2: {'speed_kmh': 21.0, 'has_moved': True},
            3: {'speed_kmh': 24.0, 'has_moved': True},
            4: {'speed_kmh': 23.0, 'has_moved': True},
            5: {'speed_kmh': 25.0, 'has_moved': True},
        }
        metrics = analyzer.analyze(timestamp=100.0, presence_snapshot=presence, speeds=speeds)
        assert metrics['traffic_status'] == 'FREE'
        assert 'dwell_time_avg_s' in metrics
        assert metrics['algorithm_version'] == 'v2_dwell_time'
