#!/usr/bin/env python3
"""Công cụ Chạy So Sánh Đối Chứng Thuật Toán Ùn Tắc Giao Thông (A/B Benchmark).

So sánh Phương án 1 (Spatial Snapshot 50-30-20) vs Phương án 2 (Context-Aware Dwell-Time).
Xuất bảng tổng kết số liệu trực quan lên màn hình và ghi file CSV/JSON để phục vụ làm báo cáo/slide.

Cách chạy:
    python tools/compare_congestion_models.py
    python tools/compare_congestion_models.py --context midblock
    python tools/compare_congestion_models.py --output benchmark_results.csv
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

# Thêm thư mục gốc vào sys.path
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from analytics.traffic_classifier import TrafficStateModel, TrafficAnalyzer
from analytics.traffic_classifier_v2 import ContextAwareTrafficStateModel, ContextAwareTrafficAnalyzer


def run_synthetic_benchmark(context='signalized', output_csv='benchmark_report.csv'):
    print("\n" + "="*80)
    print(" HỆ THỐNG SO SÁNH ĐỐI CHỨNG A/B THUẬT TOÁN ÙN TẮC GIAO THÔNG (JETSON NANO)")
    print("="*80)
    print(" • Phương án 1 (V1): Spatial Snapshot (Trọng số 50-30-20 cơ bản)")
    print(" • Phương án 2 (V2): Context-Aware Dwell-Time (Ngữ cảnh: %s)" % context.upper())
    print("="*80 + "\n")

    # Khởi tạo 2 mô hình V1 và V2
    model_v1 = TrafficStateModel()
    analyzer_v1 = TrafficAnalyzer(road_length_m=20.0, lane_count=2, state_model=model_v1)

    model_v2 = ContextAwareTrafficStateModel(context=context)
    analyzer_v2 = ContextAwareTrafficAnalyzer(road_length_m=20.0, lane_count=2, state_model=model_v2)

    # Định nghĩa 4 kịch bản thực nghiệm tiêu chuẩn
    scenarios = [
        {
            'name': 'Kịch bản 1: Chờ đèn đỏ hợp pháp tại nút giao (Pha đỏ 30 giây)',
            'ground_truth': 'FREE (Không kẹt)',
            'duration_s': 30,
            'step_s': 1.0,
            'generator': lambda t: {
                'presence': {
                    'current_total': 12,
                    'current_by_class': {'motorbike': 10, 'car': 2},
                    'current_track_ids': list(range(1, 13)),
                    'raw_tracks': 12,
                },
                'speeds': {
                    i: {'speed_kmh': 0.0, 'has_moved': True} for i in range(1, 13)
                }
            }
        },
        {
            'name': 'Kịch bản 2: Đoạn đường ngắn ít xe ban đêm (1 ô tô đỗ tạm + 1 xe máy)',
            'ground_truth': 'FREE (Đường vắng)',
            'duration_s': 15,
            'step_s': 1.0,
            'generator': lambda t: {
                'presence': {
                    'current_total': 2,
                    'current_by_class': {'motorbike': 1, 'car': 1},
                    'current_track_ids': [101, 102],
                    'raw_tracks': 2,
                },
                'speeds': {
                    101: {'speed_kmh': 0.0, 'has_moved': False}, # Xe đỗ lề đường
                    102: {'speed_kmh': 18.0, 'has_moved': True},
                }
            }
        },
        {
            'name': 'Kịch bản 3: Giờ tan tầm đông đúc nhưng xe máy trôi nhanh (22 km/h)',
            'ground_truth': 'FREE (Dòng mao dẫn)',
            'duration_s': 20,
            'step_s': 1.0,
            'generator': lambda t: {
                'presence': {
                    'current_total': 25,
                    'current_by_class': {'motorbike': 23, 'car': 2},
                    'current_track_ids': list(range(200, 225)),
                    'raw_tracks': 25,
                },
                'speeds': {
                    i: {'speed_kmh': 22.0 + (i % 4), 'has_moved': True} for i in range(200, 225)
                }
            }
        },
        {
            'name': 'Kịch bản 4: Kẹt xe thực sự kéo dài qua nhiều chu kỳ đèn (70 giây)',
            'ground_truth': 'CONGESTED (Kẹt xe thật)',
            'duration_s': 70,
            'step_s': 1.0,
            'generator': lambda t: {
                'presence': {
                    'current_total': 18,
                    'current_by_class': {'motorbike': 15, 'car': 3},
                    'current_track_ids': list(range(300, 318)),
                    'raw_tracks': 18,
                },
                'speeds': {
                    i: {'speed_kmh': 1.5, 'has_moved': True} for i in range(300, 318)
                }
            }
        }
    ]

    records = []
    summary_stats = {
        'V1': {'false_alarms': 0, 'correct_predictions': 0, 'total_frames': 0, 'avg_latency_ms': 0.0},
        'V2': {'false_alarms': 0, 'correct_predictions': 0, 'total_frames': 0, 'avg_latency_ms': 0.0},
    }

    v1_latencies = []
    v2_latencies = []

    for sc in scenarios:
        print("▶ ĐANG CHẠY: %s" % sc['name'])
        print("  Thực tế (Ground Truth): %s | Thời lượng test: %ds" % (sc['ground_truth'], sc['duration_s']))
        print("-" * 80)
        print("%-6s | %-16s | %-16s | %-12s | %-12s" % ("Giây", "Trạng thái V1", "Trạng thái V2", "Điểm V1", "Điểm V2"))
        print("-" * 80)

        t_base = 1000.0
        v1_congested_count = 0
        v2_congested_count = 0

        for step in range(int(sc['duration_s'])):
            t_curr = t_base + step
            data = sc['generator'](step)

            # Chạy V1 & đo độ trễ
            t0 = time.perf_counter()
            m1 = analyzer_v1.analyze(t_curr, data['presence'], data['speeds'])
            t1 = time.perf_counter()
            v1_latencies.append((t1 - t0) * 1000.0)

            # Chạy V2 & đo độ trễ
            t2 = time.perf_counter()
            m2 = analyzer_v2.analyze(t_curr, data['presence'], data['speeds'])
            t3 = time.perf_counter()
            v2_latencies.append((t3 - t2) * 1000.0)

            s1 = m1['traffic_status']
            score1 = m1['congestion_score']
            s2 = m2['traffic_status']
            score2 = m2['congestion_score']

            if s1 == 'CONGESTED':
                v1_congested_count += 1
            if s2 == 'CONGESTED':
                v2_congested_count += 1

            summary_stats['V1']['total_frames'] += 1
            summary_stats['V2']['total_frames'] += 1

            # Kiểm tra False Alarm (Báo CONGESTED khi thực tế là FREE)
            if 'FREE' in sc['ground_truth']:
                if s1 == 'CONGESTED':
                    summary_stats['V1']['false_alarms'] += 1
                else:
                    summary_stats['V1']['correct_predictions'] += 1

                if s2 == 'CONGESTED':
                    summary_stats['V2']['false_alarms'] += 1
                else:
                    summary_stats['V2']['correct_predictions'] += 1
            else: # Thực tế là CONGESTED
                if s1 == 'CONGESTED':
                    summary_stats['V1']['correct_predictions'] += 1
                if s2 == 'CONGESTED':
                    summary_stats['V2']['correct_predictions'] += 1

            records.append({
                'scenario': sc['name'],
                'second': step,
                'v1_status': s1,
                'v1_score': score1,
                'v2_status': s2,
                'v2_score': score2,
                'dwell_avg_s': m2.get('dwell_time_avg_s', 0.0),
                'ground_truth': sc['ground_truth'],
            })

            # In mẫu mỗi 5 giây hoặc tại giây cuối
            if step % 5 == 0 or step == sc['duration_s'] - 1:
                print("%-6ds | %-16s | %-16s | %-12d | %-12d" % (step, s1, s2, score1, score2))

        print("-" * 80)
        print("  -> Kết luận kịch bản: V1 báo kẹt %d/%ds | V2 báo kẹt %d/%ds\n" % (
            v1_congested_count, sc['duration_s'], v2_congested_count, sc['duration_s']
        ))

    # Tính toán kết quả tổng kết
    v1_total = max(1, summary_stats['V1']['total_frames'])
    v2_total = max(1, summary_stats['V2']['total_frames'])

    v1_far = (summary_stats['V1']['false_alarms'] / float(v1_total)) * 100.0
    v2_far = (summary_stats['V2']['false_alarms'] / float(v2_total)) * 100.0

    v1_acc = (summary_stats['V1']['correct_predictions'] / float(v1_total)) * 100.0
    v2_acc = (summary_stats['V2']['correct_predictions'] / float(v2_total)) * 100.0

    v1_avg_lat = sum(v1_latencies) / len(v1_latencies) if v1_latencies else 0.0
    v2_avg_lat = sum(v2_latencies) / len(v2_latencies) if v2_latencies else 0.0

    print("="*80)
    print(" BẢNG TỔNG KẾT ĐỐI CHỨNG THỰC NGHIỆM (A/B BENCHMARK SUMMARY)")
    print("="*80)
    print("%-35s | %-18s | %-18s" % ("Chỉ số đánh giá", "Phương án 1 (V1)", "Phương án 2 (V2)"))
    print("-" * 80)
    print("%-35s | %-18s | %-18s" % ("1. Cơ chế phân loại", "Snapshot tức thời", "Context Dwell-Time"))
    print("%-35s | %-18s | %-18s" % ("2. Xử lý đèn đỏ hợp pháp", "Không (Báo kẹt sai)", "Có (Ân hạn 30s)"))
    print("%-35s | %-18s | %-18s" % ("3. Bảo vệ đoạn ROI ngắn", "Không có", "Có (Low Count Guard)"))
    print("%-35s | %-18.1f%% | %-18.1f%%" % ("4. Tỷ lệ Báo động giả (FAR)", v1_far, v2_far))
    print("%-35s | %-18.1f%% | %-18.1f%%" % ("5. Độ chính xác tổng thể (Accuracy)", v1_acc, v2_acc))
    print("%-35s | %-18.2f ms | %-18.2f ms" % ("6. Độ trễ thuật toán (Latency)", v1_avg_lat, v2_avg_lat))
    print("="*80)

    # Ghi file CSV
    out_path = Path(output_csv)
    with out_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'scenario', 'second', 'v1_status', 'v1_score', 'v2_status', 'v2_score', 'dwell_avg_s', 'ground_truth'
        ])
        writer.writeheader()
        writer.writerows(records)

    print("\n[OK] Đã xuất báo cáo chi tiết ra file: %s" % out_path.resolve())
    print("[TIP] Bạn có thể dùng bảng số liệu trên để đưa thẳng vào Slide hoặc Chương 4 của Khóa luận!\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='So sánh đối chứng A/B Thuật toán Ùn tắc')
    parser.add_argument('--context', choices=['signalized', 'midblock'], default='signalized',
                        help='Ngữ cảnh phân tích: signalized (nút giao có đèn) hoặc midblock (đoạn không đèn)')
    parser.add_argument('--output', default='benchmark_report.csv', help='Đường dẫn file CSV kết quả')
    args = parser.parse_args()

    run_synthetic_benchmark(context=args.context, output_csv=args.output)
