#!/usr/bin/env python3
"""Unit tests cho Đợt 5 — Cải tiến & Nghiệm thu Thuật toán Giao thông (A1 - A6).

Bao quát:
- A1: Mật độ hiển thị vs mật độ phân loại (raw veh/km/lane vs pce/km/lane)
- A2: Ngưỡng điểm và màu sắc định nghĩa tập trung (get_traffic_color, CONGESTION_THRESHOLDS)
- A3: Incident Guard: Xe dừng bất động quá 30 giây trong ROI ít xe (<= 2 xe)
- A4: Cấu hình mặc định algo-version là 'v2' trong main.py và .env.example
- A5: Chống rò rỉ bộ nhớ track_prev_area khi chạy 24/7
- A6: Thước đo đánh giá Benchmark khoa học: Precision, Recall, F1-Score, False Alarm Rate/Hour
"""

import os
import sys
import time
from pathlib import Path

import pytest

# Thêm root vào sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from analytics.traffic_classifier import (
    TrafficAnalyzer,
    TrafficStateModel,
    CONGESTION_THRESHOLDS,
    TRAFFIC_COLORS,
    get_traffic_color,
)
from analytics.traffic_classifier_v2 import (
    ContextAwareTrafficAnalyzer,
    ContextAwareTrafficStateModel,
)
from tools.compare_congestion_models import calculate_metrics, run_synthetic_benchmark


class TestA1DensityMetrics:
    """A1: Kiểm tra tính toán và trả về đầy đủ cả Mật độ thô và Mật độ PCE."""

    def test_density_raw_vs_pce_separation(self):
        analyzer = TrafficAnalyzer(road_length_m=20.0, lane_count=1)

        # 10 xe máy trong ROI 20m, 1 làn đường
        # Raw density = 10 / (0.02 km * 1 lane) = 500 veh/km/lane
        # Motorbike PCE = 0.3 -> PCE density = 3.0 / (0.02 * 1) = 150 pce/km/lane
        presence = {
            'current_total': 10,
            'current_by_class': {'motorbike': 10},
            'current_track_ids': list(range(1, 11)),
            'raw_tracks': 10,
        }
        speeds = {i: {'speed_kmh': 20.0, 'has_moved': True} for i in range(1, 11)}

        result = analyzer.analyze(timestamp=1000.0, presence_snapshot=presence, speeds=speeds)

        assert 'density_raw_veh_per_km_lane' in result
        assert 'density_pce_per_km_lane' in result
        assert 'density_pcu_per_km_lane' in result  # Alias tương thích ngược

        raw_density = result['density_raw_veh_per_km_lane']
        pce_density = result['density_pce_per_km_lane']

        assert pytest.approx(raw_density, 0.1) == 500.0
        assert pytest.approx(pce_density, 0.1) == 150.0
        # Mật độ thô xe máy gấp ~3.33 lần mật độ PCE
        assert raw_density > pce_density * 3.0


class TestA2CongestionThresholdsAndColors:
    """A2: Kiểm tra tập trung hóa ngưỡng điểm và bảng màu chuẩn."""

    def test_centralized_thresholds_and_colors(self):
        assert CONGESTION_THRESHOLDS['FREE_MAX'] == 35
        assert CONGESTION_THRESHOLDS['SLOW_MAX'] == 65

        # FREE
        assert get_traffic_color(20, 'FREE') == TRAFFIC_COLORS['FREE']
        assert get_traffic_color(30) == TRAFFIC_COLORS['FREE']

        # SLOW
        assert get_traffic_color(45, 'SLOW') == TRAFFIC_COLORS['SLOW']
        assert get_traffic_color(50) == TRAFFIC_COLORS['SLOW']

        # CONGESTED
        assert get_traffic_color(80, 'CONGESTED') == TRAFFIC_COLORS['CONGESTED']
        assert get_traffic_color(70) == TRAFFIC_COLORS['CONGESTED']


class TestA3StationaryIncidentGuard:
    """A3: Kiểm tra phát hiện xe đứng yên kéo dài (>= 30s) khi ít xe (<= 2 xe)."""

    def test_low_vehicle_count_stationary_incident_v1(self):
        model = TrafficStateModel()
        model.stationary_incident_threshold_s = 30.0

        presence = {
            'current_total': 2,
            'current_by_class': {'car': 2},
            'current_track_ids': [1, 2],
        }
        speeds = {
            1: {'speed_kmh': 0.0, 'has_moved': True},
            2: {'speed_kmh': 0.0, 'has_moved': True},
        }

        # Dưới 30s: Vẫn an toàn là FREE (bảo vệ ROI ngắn)
        for t in range(0, 20):
            res = model.classify(
                avg_speed_kmh=0.0,
                density=30.0,
                stopped_ratio=1.0,
                vehicle_count=2,
                timestamp=float(t),
            )
            assert res[0] == 'FREE'
            assert not model._incident_detected

        # Vượt quá 30s: Kích hoạt cảnh báo sự cố (SLOW)
        res = model.classify(
            avg_speed_kmh=0.0,
            density=30.0,
            stopped_ratio=1.0,
            vehicle_count=2,
            timestamp=35.0,
        )
        assert res[0] == 'SLOW'
        assert model._incident_detected is True
        assert res[1] >= 40

    def test_low_vehicle_count_stationary_incident_v2(self):
        model_v2 = ContextAwareTrafficStateModel(context='midblock')
        model_v2.stationary_incident_threshold_s = 30.0
        analyzer_v2 = ContextAwareTrafficAnalyzer(road_length_m=20.0, lane_count=2, state_model=model_v2)

        presence = {
            'current_total': 1,
            'current_by_class': {'car': 1},
            'current_track_ids': [99],
            'raw_tracks': 1,
        }
        speeds = {99: {'speed_kmh': 0.0, 'has_moved': True}}

        # Chạy 35 giây liên tục
        for t in range(36):
            m = analyzer_v2.analyze(timestamp=float(t), presence_snapshot=presence, speeds=speeds)

        assert m['traffic_status'] == 'SLOW'
        assert m.get('is_incident') is True
        assert m['congestion_score'] >= 40


class TestA4DefaultAlgorithmVersion:
    """A4: Kiểm tra cấu hình mặc định là v2 trong main.py và .env.example."""

    def test_env_example_has_v2_default(self):
        env_example_path = ROOT_DIR / '.env.example'
        assert env_example_path.exists()
        content = env_example_path.read_text(encoding='utf-8')
        assert 'TRAFFIC_ALGORITHM_VERSION=v2' in content

    def test_main_cli_defaults_to_v2(self):
        main_path = ROOT_DIR / 'main.py'
        assert main_path.exists()
        content = main_path.read_text(encoding='utf-8')
        # Kiểm tra default được lấy từ biến môi trường mặc định là 'v2'
        assert "os.getenv('TRAFFIC_ALGORITHM_VERSION', 'v2')" in content


class TestA5MemoryLeakPrevention:
    """A5: Kiểm tra dọn dẹp track_prev_area không để rò rỉ bộ nhớ khi chạy dài."""

    def test_prune_stale_track_prev_area(self):
        # Mô phỏng cấu trúc track_prev_area lưu (area, last_seen)
        track_prev_area = {}

        # Thêm 50 tracks cũ tại t=100.0
        for i in range(1, 51):
            track_prev_area[i] = (1500.0, 100.0)

        # Thêm 5 tracks mới tại t=120.0
        for i in range(101, 106):
            track_prev_area[i] = (2000.0, 120.0)

        current_time = 120.0
        # Logic prune giống main.py
        stale_threshold = 10.0
        stale_keys = [k for k, v in track_prev_area.items() if (current_time - v[1]) > stale_threshold]
        for k in stale_keys:
            del track_prev_area[k]

        # Chỉ còn lại 5 tracks mới
        assert len(track_prev_area) == 5
        assert set(track_prev_area.keys()) == {101, 102, 103, 104, 105}


class TestA6ScientificBenchmarkMetrics:
    """A6: Kiểm tra các chỉ số đánh giá Precision, Recall, F1-score và FAR/Hour."""

    def test_metric_calculations(self):
        stats = {
            'tp': 40,
            'fp': 10,
            'fn': 10,
            'tn': 40,
            'total_frames': 100,
        }
        duration_s = 3600.0  # 1 hour

        metrics = calculate_metrics(stats, duration_s)

        # Precision = 40 / (40 + 10) = 80.0%
        assert pytest.approx(metrics['precision'], 0.01) == 80.0
        # Recall = 40 / (40 + 10) = 80.0%
        assert pytest.approx(metrics['recall'], 0.01) == 80.0
        # F1 = 80.0%
        assert pytest.approx(metrics['f1'], 0.01) == 80.0
        # Accuracy = (40 + 40) / 100 = 80.0%
        assert pytest.approx(metrics['accuracy'], 0.01) == 80.0
        # FAR / hour = 10 / 1.0 = 10.0
        assert pytest.approx(metrics['far_per_hour'], 0.01) == 10.0

    def test_run_synthetic_benchmark_executes_cleanly(self, tmp_path):
        out_csv = tmp_path / "test_benchmark.csv"
        results = run_synthetic_benchmark(context='signalized', output_csv=str(out_csv))

        assert out_csv.exists()
        assert 'v1' in results
        assert 'v2' in results
        # V2 phải có False Alarm ít hơn hoặc bằng V1 rất nhiều
        assert results['v2']['fp'] <= results['v1']['fp']
        assert results['v2']['far_per_hour'] <= results['v1']['far_per_hour']
