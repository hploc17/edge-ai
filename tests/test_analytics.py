#!/usr/bin/env python3
"""Unit test cho các module thuật toán (chạy trên PC, không cần DeepStream/Jetson).

Chạy:  python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analytics.presence_counter import RoiPresenceCounter  # noqa: E402
from analytics.speed_estimator import (  # noqa: E402
    PerspectiveCalibration, StreamTimestamp, TrackSpeedEstimator,
)
from analytics.traffic_classifier import (  # noqa: E402
    CONGESTION_THRESHOLDS, TrafficAnalyzer, TrafficStateModel, status_from_score,
)
from analytics.traffic_classifier_v2 import (  # noqa: E402
    ContextAwareTrafficAnalyzer, ContextAwareTrafficStateModel,
)

ROI = [[100, 700], [1180, 700], [900, 200], [380, 200]]   # P1 gần-trái, P2 gần-phải, P3 xa-phải, P4 xa-trái
VEHICLES = ('motorbike', 'car', 'truck', 'bus', 'bicycle')


def bbox_at(x, y, w=40, h=40):
    """bbox có đáy-giữa tại (x, y)."""
    return [x - w / 2.0, y - h, x + w / 2.0, y]


def obj(tid, cls, x, y):
    return {'track_id': tid, 'class_name': cls, 'bbox': bbox_at(x, y)}


# ─────────────────────────────────────────────────────────────────────────────
class TestPresenceCounter(unittest.TestCase):

    def setUp(self):
        self.counter = RoiPresenceCounter(ROI, VEHICLES, enter_confirm_seconds=0.1,
                                          exit_confirm_seconds=0.25, lost_timeout_seconds=1.0)

    def _run(self, frames):
        for t, objects in frames:
            self.counter.update(objects, t)

    def test_confirm_after_enter_hysteresis(self):
        self.counter.update([obj(1, 'car', 640, 500)], 0.0)
        self.assertEqual(self.counter.snapshot()['current_total'], 0)   # chưa đủ 0.1 s
        self.counter.update([obj(1, 'car', 640, 500)], 0.2)
        snap = self.counter.snapshot()
        self.assertEqual(snap['current_total'], 1)
        self.assertEqual(snap['current_by_class']['car'], 1)
        self.assertIn(1, snap['track_positions'])

    def test_release_after_leaving_roi(self):
        self._run([(0.0, [obj(1, 'car', 640, 500)]), (0.2, [obj(1, 'car', 640, 500)])])
        self._run([(0.3, [obj(1, 'car', 640, 100)]), (0.6, [obj(1, 'car', 640, 100)])])
        self.assertEqual(self.counter.snapshot()['current_total'], 0)

    def test_lost_track_is_released(self):
        self._run([(0.0, [obj(1, 'car', 640, 500)]), (0.2, [obj(1, 'car', 640, 500)])])
        self.counter.update([], 1.5)
        self.assertEqual(self.counter.snapshot()['current_total'], 0)

    def test_class_flicker_does_not_create_ghost_vehicles(self):
        """H2: YOLO đổi nhãn motorbike <-> bicycle không được làm số đếm trôi."""
        t = 0.0
        for cycle in range(50):
            tid = 100 + cycle
            for i in range(6):
                cls = 'motorbike' if i % 2 == 0 else 'bicycle'
                self.counter.update([obj(tid, cls, 640, 500)], t)
                t += 0.1
            # xe rời ROI với nhãn khác nhãn lúc vào
            self.counter.update([obj(tid, 'bicycle', 640, 100)], t)
            self.counter.update([obj(tid, 'bicycle', 640, 100)], t + 0.3)
            t += 0.5
        snap = self.counter.snapshot()
        self.assertEqual(snap['current_total'], 0)
        self.assertTrue(all(v == 0 for v in snap['current_by_class'].values()), snap['current_by_class'])

    def test_majority_vote_class(self):
        for i, cls in enumerate(['car', 'car', 'truck', 'car']):
            self.counter.update([obj(7, cls, 640, 500)], i * 0.1)
        self.assertEqual(self.counter.snapshot()['track_classes'][7], 'car')

    def test_reset(self):
        self._run([(0.0, [obj(1, 'car', 640, 500)]), (0.2, [obj(1, 'car', 640, 500)])])
        self.counter.reset()
        self.assertEqual(self.counter.snapshot()['current_total'], 0)


# ─────────────────────────────────────────────────────────────────────────────
class TestSpeedEstimator(unittest.TestCase):

    def setUp(self):
        # Hình chữ nhật trên ảnh <-> mặt đường 10 m x 50 m (1 px dọc = 0.1 m)
        self.calib = PerspectiveCalibration([[100, 700], [300, 700], [300, 200], [100, 200]], 10.0, 50.0)

    def test_homography_maps_corners(self):
        wx, wy = self.calib.transform((300, 200))
        self.assertAlmostEqual(wx, 10.0, places=6)
        self.assertAlmostEqual(wy, 50.0, places=6)

    def test_rejects_crossed_points(self):
        with self.assertRaises(ValueError):
            PerspectiveCalibration([[100, 700], [300, 200], [300, 700], [100, 200]], 10.0, 50.0)

    def test_constant_speed_is_measured(self):
        est = TrackSpeedEstimator(self.calib, history_seconds=2.0, minimum_time_seconds=0.8)
        fps, speed_mps = 25.0, 10.0          # 10 m/s = 36 km/h -> 100 px/s theo trục dọc
        result = {}
        for i in range(60):
            t = i / fps
            y = 650 - speed_mps * t / 0.1
            result = est.update([obj(1, 'car', 200, y)], t)
        self.assertIn(1, result)
        self.assertAlmostEqual(result[1]['speed_kmh'], 36.0, delta=0.5)
        self.assertTrue(result[1]['has_moved'])

    def test_stationary_vehicle_reports_zero_and_never_moved(self):
        est = TrackSpeedEstimator(self.calib)
        result = {}
        for i in range(60):
            result = est.update([obj(2, 'car', 200, 500 + (i % 2))], i / 25.0)  # rung 1 px
        self.assertEqual(result[2]['speed_kmh'], 0.0)
        self.assertFalse(result[2]['has_moved'])

    def test_stream_timestamp_is_monotonic(self):
        clock = StreamTimestamp('video', nominal_fps=25.0)
        values = [clock.resolve(pts, frame_number=i, wall_now=None)
                  for i, pts in enumerate([0.0, 0.04, None, -1.0, 0.16, 0.12])]
        self.assertEqual(values, sorted(values))


# ─────────────────────────────────────────────────────────────────────────────
class TestThresholds(unittest.TestCase):

    def test_status_from_score_boundaries(self):
        self.assertEqual(status_from_score(0), 'FREE')
        self.assertEqual(status_from_score(34), 'FREE')
        self.assertEqual(status_from_score(35), 'SLOW')
        self.assertEqual(status_from_score(64), 'SLOW')
        self.assertEqual(status_from_score(65), 'CONGESTED')
        self.assertEqual(status_from_score(100), 'CONGESTED')

    def test_score_bands_match_thresholds_for_both_models(self):
        """M1: dải điểm của từng nhãn khớp thang chung (không chồng lấn 65)."""
        for model in (TrafficStateModel(), ContextAwareTrafficStateModel()):
            self.assertLess(model.free_max_score, CONGESTION_THRESHOLDS['FREE_MAX'])
            self.assertGreaterEqual(model.slow_min_score, CONGESTION_THRESHOLDS['FREE_MAX'])
            self.assertLess(model.slow_max_score, CONGESTION_THRESHOLDS['SLOW_MAX'])
            self.assertGreaterEqual(model.congested_min_score, CONGESTION_THRESHOLDS['SLOW_MAX'])

    def test_classified_score_never_contradicts_label(self):
        model = TrafficStateModel()
        cases = [(40.0, 10.0, 0.0), (15.0, 160.0, 0.2), (3.0, 260.0, 0.6), (8.0, 230.0, 0.5)]
        for i, (speed, density, stopped) in enumerate(cases):
            label, score = model.classify(speed, density, stopped, timestamp=1000.0 * (i + 1),
                                          median_speed_kmh=speed, vehicle_count=10)
            self.assertEqual(status_from_score(score), label, (speed, density, stopped, label, score))


# ─────────────────────────────────────────────────────────────────────────────
def presence(ids, positions=None, classes=None, by_class=None):
    ids = list(ids)
    classes = classes or dict((t, 'car') for t in ids)
    if by_class is None:
        by_class = {}
        for t in ids:
            by_class[classes[t]] = by_class.get(classes[t], 0) + 1
    return {
        'current_total': len(ids),
        'current_by_class': by_class,
        'current_track_ids': ids,
        'track_positions': positions or dict((t, (640.0, 500.0)) for t in ids),
        'track_classes': classes,
        'raw_tracks': len(ids),
    }


def speeds_of(values, never_moved=()):
    return dict((tid, {'speed_kmh': v, 'has_moved': tid not in never_moved}) for tid, v in values.items())


class TestTrafficAnalyzer(unittest.TestCase):

    def test_exclusion_polygon_removes_parked_vehicle(self):
        """M2: xe trong vùng loại trừ không được tính vào số đếm/mật độ/tỷ lệ dừng."""
        parking = [[0, 0], [200, 0], [200, 720], [0, 720]]
        analyzer = TrafficAnalyzer(20.0, 2, exclusion_polygons=[parking])
        pres = presence([1, 2], positions={1: (100.0, 500.0), 2: (640.0, 500.0)})
        metrics = analyzer.analyze(10.0, pres, speeds_of({1: 0.0, 2: 30.0}))
        self.assertEqual(metrics['current_vehicle_count'], 1)
        self.assertEqual(metrics['excluded_vehicle_count'], 1)
        self.assertEqual(metrics['stopped_vehicle_count'], 0)
        self.assertEqual(metrics['counts_by_class']['car'], 1)

    def test_entry_rate_uses_event_time(self):
        """L3: cửa sổ 60 s tính theo thời gian luồng, không theo đồng hồ máy."""
        analyzer = TrafficAnalyzer(20.0, 2)
        for i in range(5):
            analyzer.record_presence_events([{'event': 'confirmed', 'track_id': i, 'timestamp': float(i)}])
        self.assertEqual(analyzer.analyze(10.0, presence([]), {})['roi_entry_rate_veh_per_min'], 5)
        self.assertEqual(analyzer.analyze(100.0, presence([]), {})['roi_entry_rate_veh_per_min'], 0)

    def test_forecast_history_sampled_at_1hz(self):
        """M10: lịch sử dự báo lấy mẫu 1 Hz thay vì mỗi frame."""
        analyzer = TrafficAnalyzer(20.0, 2, forecast_history_seconds=900.0,
                                   forecast_minimum_history_seconds=60.0)
        for i in range(25 * 120):                     # 120 s ở 25 fps
            analyzer.analyze(i / 25.0, presence([1, 2, 3]), speeds_of({1: 30.0, 2: 30.0, 3: 30.0}))
        self.assertLessEqual(len(analyzer._score_history), 121)
        forecast = analyzer.analyze(120.0, presence([1, 2, 3]), speeds_of({1: 30.0, 2: 30.0, 3: 30.0}))['forecast']
        self.assertTrue(forecast['ready'])
        self.assertEqual(forecast['horizons']['5m']['status'],
                         status_from_score(forecast['horizons']['5m']['congestion_score']))


# ─────────────────────────────────────────────────────────────────────────────
class TestContextAwareV2(unittest.TestCase):

    def make(self, context):
        model = ContextAwareTrafficStateModel(context=context)
        return ContextAwareTrafficAnalyzer(20.0, 2, state_model=model)

    def run_seconds(self, analyzer, seconds, pres, spd, start=0.0, fps=5.0):
        metrics = None
        for i in range(int(seconds * fps)):
            metrics = analyzer.analyze(start + i / fps, pres, spd)
        return metrics

    def test_parked_vehicle_does_not_cause_congestion_midblock(self):
        """H6: 1 xe đỗ (chưa từng di chuyển) + 5 xe chạy bình thường -> không được báo ùn tắc."""
        analyzer = self.make('midblock')
        ids = [1, 2, 3, 4, 5, 6]
        values = {1: 0.0, 2: 35.0, 3: 32.0, 4: 30.0, 5: 34.0, 6: 31.0}
        # xe 2-6 thay track liên tục (đi qua ROI), xe 1 đứng yên suốt 60 s
        metrics = None
        for second in range(60):
            moving = [100 + second * 10 + k for k in range(5)]
            pres = presence([1] + moving)
            spd = speeds_of(dict([(1, 0.0)] + [(t, 32.0) for t in moving]), never_moved={1})
            metrics = analyzer.analyze(float(second), pres, spd)
        self.assertEqual(metrics['traffic_status'], 'FREE', metrics)
        self.assertGreaterEqual(metrics['max_dwell_s'], 50.0)   # max vẫn được báo cáo để giám sát
        self.assertLess(metrics['median_dwell_s'], 5.0)
        del ids, values

    def test_stop_duration_counts_from_stop_not_entry(self):
        """M9: xe đi chậm 25 s rồi mới dừng 1 s -> thời gian dừng ~1 s, không phải 26 s."""
        model = ContextAwareTrafficStateModel(context='signalized')
        for t in range(26):
            model.update_dwell_times([1], float(t), stopped_track_ids=[])
        stats = model.update_dwell_times([1], 26.0, stopped_track_ids=[1])
        stats = model.update_dwell_times([1], 27.0, stopped_track_ids=[1])
        self.assertAlmostEqual(stats['stopped_dwell_max_s'], 1.0, places=1)
        self.assertAlmostEqual(stats['max_dwell_s'], 27.0, places=1)

    def test_long_queue_becomes_congested_midblock(self):
        """Đoạn không đèn: đa số xe dừng > 15 s, mật độ cao -> CONGESTED."""
        analyzer = self.make('midblock')
        ids = list(range(1, 13))
        pres = presence(ids)
        spd = speeds_of(dict((t, 1.0) for t in ids))
        metrics = self.run_seconds(analyzer, 40, pres, spd)
        self.assertEqual(metrics['traffic_status'], 'CONGESTED', metrics)
        self.assertGreaterEqual(metrics['congestion_score'], CONGESTION_THRESHOLDS['SLOW_MAX'])

    def test_red_light_wait_within_grace_is_free(self):
        """Nút giao có đèn: dừng chờ đèn đỏ < 30 s -> vẫn FREE."""
        analyzer = self.make('signalized')
        ids = list(range(1, 9))
        pres = presence(ids)
        spd = speeds_of(dict((t, 0.5) for t in ids))
        metrics = self.run_seconds(analyzer, 20, pres, spd)
        self.assertEqual(metrics['traffic_status'], 'FREE', metrics)


if __name__ == '__main__':
    unittest.main()
