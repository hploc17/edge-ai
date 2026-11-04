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


def calculate_metrics(stats, duration_s):
    """Tính các chỉ số Precision, Recall, F1-Score và False Alarms per Hour."""
    tp = stats['tp']
    fp = stats['fp']
    fn = stats['fn']
    tn = stats['tn']
    total = stats['total_frames']

    precision = (tp / float(tp + fp)) * 100.0 if (tp + fp) > 0 else 0.0
    recall = (tp / float(tp + fn)) * 100.0 if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    accuracy = ((tp + tn) / float(total)) * 100.0 if total > 0 else 0.0

    duration_hours = max(1e-6, duration_s / 3600.0)
    far_per_hour = fp / duration_hours

    return {
        'tp': tp,
        'fp': fp,
        'fn': fn,
        'tn': tn,
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'accuracy': accuracy,
        'far_per_hour': far_per_hour,
    }


def run_benchmark(records_source, context='signalized', output_csv='benchmark_report.csv', is_real_data=False):
    print("\n" + "="*85)
    print(" HỆ THỐNG SO SÁNH ĐỐI CHỨNG A/B THUẬT TOÁN ÙN TẮC GIAO THÔNG (JETSON NANO)")
    print("="*85)
    print(" • Phương án 1 (V1): Spatial Snapshot (Trọng số 50-30-20 cơ bản)")
    print(" • Phương án 2 (V2): Context-Aware Dwell-Time (Ngữ cảnh: %s)" % context.upper())
    print(" • Chế độ dữ liệu:  %s" % ("DỮ LIỆU THỰC TẾ (REAL LOG)" if is_real_data else "KỊCH BẢN TỔNG HỢP (SYNTHETIC)"))
    print("="*85 + "\n")

    model_v1 = TrafficStateModel()
    analyzer_v1 = TrafficAnalyzer(road_length_m=20.0, lane_count=2, state_model=model_v1)

    model_v2 = ContextAwareTrafficStateModel(context=context)
    analyzer_v2 = ContextAwareTrafficAnalyzer(road_length_m=20.0, lane_count=2, state_model=model_v2)

    records = []
    stats = {
        'V1': {'tp': 0, 'fp': 0, 'fn': 0, 'tn': 0, 'total_frames': 0},
        'V2': {'tp': 0, 'fp': 0, 'fn': 0, 'tn': 0, 'total_frames': 0},
    }
    v1_latencies = []
    v2_latencies = []
    total_duration_s = 0.0

    for item in records_source:
        name = item.get('name', 'Scenario')
        gt = item.get('ground_truth', 'FREE')
        steps = item.get('steps', [])
        is_gt_congested = ('CONGESTED' in gt.upper())

        print("▶ PHÂN TÍCH: %s" % name)
        print("  Ground Truth: %s | Số bước/frames: %d" % (gt, len(steps)))
        print("-" * 85)
        print("%-6s | %-16s | %-16s | %-12s | %-12s" % ("Bước", "Trạng thái V1", "Trạng thái V2", "Điểm V1", "Điểm V2"))
        print("-" * 85)

        for idx, step_data in enumerate(steps):
            t_curr = step_data.get('timestamp', 1000.0 + idx)
            presence = step_data['presence']
            speeds = step_data['speeds']
            step_gt = step_data.get('ground_truth', gt)
            step_is_congested = ('CONGESTED' in step_gt.upper())

            # V1
            t0 = time.perf_counter()
            m1 = analyzer_v1.analyze(t_curr, presence, speeds)
            t1 = time.perf_counter()
            v1_latencies.append((t1 - t0) * 1000.0)

            # V2
            t2 = time.perf_counter()
            m2 = analyzer_v2.analyze(t_curr, presence, speeds)
            t3 = time.perf_counter()
            v2_latencies.append((t3 - t2) * 1000.0)

            s1 = m1['traffic_status']
            score1 = m1['congestion_score']
            s2 = m2['traffic_status']
            score2 = m2['congestion_score']

            v1_congested = (s1 == 'CONGESTED')
            v2_congested = (s2 == 'CONGESTED')

            # Update stats V1
            stats['V1']['total_frames'] += 1
            if step_is_congested:
                if v1_congested:
                    stats['V1']['tp'] += 1
                else:
                    stats['V1']['fn'] += 1
            else:
                if v1_congested:
                    stats['V1']['fp'] += 1
                else:
                    stats['V1']['tn'] += 1

            # Update stats V2
            stats['V2']['total_frames'] += 1
            if step_is_congested:
                if v2_congested:
                    stats['V2']['tp'] += 1
                else:
                    stats['V2']['fn'] += 1
            else:
                if v2_congested:
                    stats['V2']['fp'] += 1
                else:
                    stats['V2']['tn'] += 1

            total_duration_s += 1.0

            records.append({
                'scenario': name,
                'second': idx,
                'v1_status': s1,
                'v1_score': score1,
                'v2_status': s2,
                'v2_score': score2,
                'dwell_avg_s': m2.get('dwell_time_avg_s', 0.0),
                'ground_truth': step_gt,
            })

            if idx % 5 == 0 or idx == len(steps) - 1:
                print("%-6d | %-16s | %-16s | %-12d | %-12d" % (idx, s1, s2, score1, score2))

        print("-" * 85 + "\n")

    m1_res = calculate_metrics(stats['V1'], total_duration_s)
    m2_res = calculate_metrics(stats['V2'], total_duration_s)

    v1_avg_lat = sum(v1_latencies) / len(v1_latencies) if v1_latencies else 0.0
    v2_avg_lat = sum(v2_latencies) / len(v2_latencies) if v2_latencies else 0.0

    print("="*85)
    print(" BẢNG TỔNG KẾT ĐỐI CHỨNG TOÀN DIỆN (A/B BENCHMARK METRICS SUMMARY)")
    print("="*85)
    print("%-35s | %-20s | %-20s" % ("Chỉ số Đánh Giá Khoa Học", "Phương án 1 (V1)", "Phương án 2 (V2)"))
    print("-" * 85)
    print("%-35s | %-20s | %-20s" % ("1. Cơ chế phân loại", "Snapshot tức thời", "Context Dwell-Time"))
    print("%-35s | %-20.2f%% | %-20.2f%%" % ("2. Độ chính xác (Accuracy)", m1_res['accuracy'], m2_res['accuracy']))
    print("%-35s | %-20.2f%% | %-20.2f%%" % ("3. Độ chính xác phát hiện (Precision)", m1_res['precision'], m2_res['precision']))
    print("%-35s | %-20.2f%% | %-20.2f%%" % ("4. Độ nhạy / Thu hồi (Recall)", m1_res['recall'], m2_res['recall']))
    print("%-35s | %-20.2f%% | %-20.2f%%" % ("5. F1-Score (Cân bằng P-R)", m1_res['f1'], m2_res['f1']))
    print("%-35s | %-20.2f cảnh báo/h | %-20.2f cảnh báo/h" % ("6. Tần suất báo động giả (FAR/Hour)", m1_res['far_per_hour'], m2_res['far_per_hour']))
    print("%-35s | %-20d | %-20d" % ("7. Số ca báo động sai (False Alarms)", m1_res['fp'], m2_res['fp']))
    print("%-35s | %-20.2f ms | %-20.2f ms" % ("8. Độ trễ thuật toán (Latency)", v1_avg_lat, v2_avg_lat))
    print("="*85)

    out_path = Path(output_csv)
    with out_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'scenario', 'second', 'v1_status', 'v1_score', 'v2_status', 'v2_score', 'dwell_avg_s', 'ground_truth'
        ])
        writer.writeheader()
        writer.writerows(records)

    print("\n[OK] Đã xuất báo cáo chi tiết ra file: %s" % out_path.resolve())
    return {
        'v1': m1_res,
        'v2': m2_res,
        'latency_v1': v1_avg_lat,
        'latency_v2': v2_avg_lat,
    }


def parse_real_log(log_path):
    """Nạp dữ liệu thực tế từ file CSV hoặc JSONL."""
    path = Path(log_path)
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file log thực tế: {log_path}")

    steps = []
    if path.suffix.lower() == '.jsonl':
        with path.open('r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    steps.append(json.loads(line))
    else: # Mặc định đọc JSON hoặc CSV
        try:
            with path.open('r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    steps = data
                else:
                    steps = data.get('frames', [])
        except json.JSONDecodeError:
            # Đọc CSV cơ bản
            with path.open('r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for r in reader:
                    total = int(r.get('total', r.get('current_total', 0)))
                    speed = float(r.get('speed', 0.0))
                    gt = r.get('ground_truth', 'FREE')
                    steps.append({
                        'timestamp': float(r.get('timestamp', time.time())),
                        'presence': {
                            'current_total': total,
                            'current_by_class': {'car': total},
                            'current_track_ids': list(range(1, total + 1)),
                            'raw_tracks': total,
                        },
                        'speeds': {i: {'speed_kmh': speed, 'has_moved': speed > 2.0} for i in range(1, total + 1)},
                        'ground_truth': gt,
                    })

    return [{
        'name': f"Thực nghiệm dữ liệu thực tế ({path.name})",
        'ground_truth': 'MIXED',
        'steps': steps,
    }]


def run_synthetic_benchmark(context='signalized', output_csv='benchmark_report.csv'):
    scenarios_def = [
        {
            'name': 'Kịch bản 1: Chờ đèn đỏ hợp pháp tại nút giao (Pha đỏ 30 giây)',
            'ground_truth': 'FREE (Không kẹt)',
            'duration_s': 30,
            'generator': lambda t: {
                'presence': {
                    'current_total': 12,
                    'current_by_class': {'motorbike': 10, 'car': 2},
                    'current_track_ids': list(range(1, 13)),
                    'raw_tracks': 12,
                },
                'speeds': {i: {'speed_kmh': 0.0, 'has_moved': True} for i in range(1, 13)}
            }
        },
        {
            'name': 'Kịch bản 2: Đoạn đường ngắn ít xe ban đêm (1 ô tô đỗ tạm + 1 xe máy)',
            'ground_truth': 'FREE (Đường vắng)',
            'duration_s': 15,
            'generator': lambda t: {
                'presence': {
                    'current_total': 2,
                    'current_by_class': {'motorbike': 1, 'car': 1},
                    'current_track_ids': [101, 102],
                    'raw_tracks': 2,
                },
                'speeds': {
                    101: {'speed_kmh': 0.0, 'has_moved': False},
                    102: {'speed_kmh': 18.0, 'has_moved': True},
                }
            }
        },
        {
            'name': 'Kịch bản 3: Giờ tan tầm đông đúc nhưng xe máy trôi nhanh (22 km/h)',
            'ground_truth': 'FREE (Dòng mao dẫn)',
            'duration_s': 20,
            'generator': lambda t: {
                'presence': {
                    'current_total': 25,
                    'current_by_class': {'motorbike': 23, 'car': 2},
                    'current_track_ids': list(range(200, 225)),
                    'raw_tracks': 25,
                },
                'speeds': {i: {'speed_kmh': 22.0 + (i % 4), 'has_moved': True} for i in range(200, 225)}
            }
        },
        {
            'name': 'Kịch bản 4: Kẹt xe thực sự kéo dài qua nhiều chu kỳ đèn (70 giây)',
            'ground_truth': 'CONGESTED (Kẹt xe thật)',
            'duration_s': 70,
            'generator': lambda t: {
                'presence': {
                    'current_total': 18,
                    'current_by_class': {'motorbike': 15, 'car': 3},
                    'current_track_ids': list(range(300, 318)),
                    'raw_tracks': 18,
                },
                'speeds': {i: {'speed_kmh': 1.5, 'has_moved': True} for i in range(300, 318)}
            }
        }
    ]

    records_source = []
    for sc in scenarios_def:
        steps = []
        t_base = 1000.0
        for step in range(int(sc['duration_s'])):
            data = sc['generator'](step)
            steps.append({
                'timestamp': t_base + step,
                'presence': data['presence'],
                'speeds': data['speeds'],
                'ground_truth': sc['ground_truth'],
            })
        records_source.append({
            'name': sc['name'],
            'ground_truth': sc['ground_truth'],
            'steps': steps,
        })

    return run_benchmark(records_source, context=context, output_csv=output_csv, is_real_data=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='So sánh đối chứng A/B Thuật toán Ùn tắc')
    parser.add_argument('--context', choices=['signalized', 'midblock'], default='signalized',
                        help='Ngữ cảnh phân tích: signalized (nút giao có đèn) hoặc midblock (đoạn không đèn)')
    parser.add_argument('--output', default='benchmark_report.csv', help='Đường dẫn file CSV kết quả')
    parser.add_argument('--input-log', default=None, help='Đường dẫn file JSON/JSONL/CSV dữ liệu thực tế gán nhãn')
    args = parser.parse_args()

    if args.input_log:
        records_source = parse_real_log(args.input_log)
        run_benchmark(records_source, context=args.context, output_csv=args.output, is_real_data=True)
    else:
        run_synthetic_benchmark(context=args.context, output_csv=args.output)



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='So sánh đối chứng A/B Thuật toán Ùn tắc')
    parser.add_argument('--context', choices=['signalized', 'midblock'], default='signalized',
                        help='Ngữ cảnh phân tích: signalized (nút giao có đèn) hoặc midblock (đoạn không đèn)')
    parser.add_argument('--output', default='benchmark_report.csv', help='Đường dẫn file CSV kết quả')
    args = parser.parse_args()

    run_synthetic_benchmark(context=args.context, output_csv=args.output)
