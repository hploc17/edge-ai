#!/usr/bin/env python3
"""ROI traffic analytics with calibrated speed, 5/10-minute forecast, MQTT and snapshot.

Entry point for Jetson Nano/DeepStream. Run inside Docker or directly on Jetson.
Compatibility: Python 3.6, JetPack 4.x, DeepStream 6.0.1, paho-mqtt 1.6.1.
"""

from __future__ import print_function

import argparse
import json
import os
import signal
import sys
import time
import threading
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

try:
    import pyds
except ImportError:
    pyds = None

# Snapshot package is stored next to this main file in ./snap.  Load its .env
# before importing mqtt_publisher because that module reads MQTT settings at
# import time.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SNAPSHOT_DIR = SCRIPT_DIR / 'snap'

try:
    from snap.config import load_env_file
    from snap.runtime import create_from_env
    from snap.deepstream_integration import attach_snapshot_probe
except ImportError:
    try:
        import importlib.util
        def _load_snap_submodule(sub_name, file_name):
            p = str(SNAPSHOT_DIR / file_name)
            spec = importlib.util.spec_from_file_location(sub_name, p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m

        _snap_cfg = _load_snap_submodule('snap_cfg', 'config.py')
        load_env_file = _snap_cfg.load_env_file
        _snap_rt = _load_snap_submodule('snap_rt', 'runtime.py')
        create_from_env = _snap_rt.create_from_env
        _snap_ds = _load_snap_submodule('snap_ds', 'deepstream_integration.py')
        attach_snapshot_probe = _snap_ds.attach_snapshot_probe
    except Exception as error:
        raise RuntimeError(
            'Missing snapshot package in %s: %s' % (SNAPSHOT_DIR, error)
        )

# Bảo vệ tuyệt đối: Đảm bảo namespace 'config' trỏ về package config/ gốc của repo
if 'config' in sys.modules and not hasattr(sys.modules['config'], '__path__'):
    del sys.modules['config']

# Nạp duy nhất từ file .env chính tại thư mục gốc của project
root_env_file = str(SCRIPT_DIR / '.env')
if os.path.isfile(root_env_file):
    load_env_file(root_env_file)
elif os.path.isfile(str(SNAPSHOT_DIR / '.env')):
    load_env_file(str(SNAPSHOT_DIR / '.env'))

# IPC Trigger Files (Fix V3: Nhận trigger chụp ảnh từ Agent khi pipeline đang chạy)
SNAPSHOT_TRIGGER_FILE = str(SCRIPT_DIR / '.snapshot_trigger')
PREVIEW_TRIGGER_FILE = str(SCRIPT_DIR / '.preview_trigger')
LATEST_PREVIEW_FILE = str(SCRIPT_DIR / '.latest_preview.jpg')

# Khóa chạy một bản: camera CSI (Argus) chỉ cho một phiên. Agent cũng đọc khóa này để biết
# pipeline đang chạy, kể cả khi main.py được chạy tay ngoài agent.
PIPELINE_LOCK_FILE = str(SCRIPT_DIR / '.pipeline.lock')
EXIT_ALREADY_RUNNING = 3
_pipeline_lock_handle = None


def acquire_single_instance_lock(wait_seconds=3.0):
    """Giữ khóa độc quyền suốt vòng đời tiến trình. Trả về False nếu bản khác đang giữ."""
    global _pipeline_lock_handle
    try:
        import fcntl
    except ImportError:
        return True  # Windows (môi trường phát triển): không có camera CSI, bỏ qua khóa
    handle = open(PIPELINE_LOCK_FILE, 'a+')
    deadline = time.monotonic() + float(wait_seconds)
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except (IOError, OSError):
            # Agent có thể đang thử khóa trong tích tắc để kiểm tra trạng thái: chờ ngắn rồi thử lại
            if time.monotonic() >= deadline:
                handle.close()
                return False
            time.sleep(0.2)
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _pipeline_lock_handle = handle
    return True

# Chỉ đặt mặc định cho các giá trị không bí mật. EDGE_TOKEN / MQTT_PASS bắt buộc khai báo trong .env.
os.environ.setdefault('BACKEND_URL', 'http://localhost:8000')
os.environ.setdefault('MQTT_HOST',
                      '829e7cb26c594257a7470e5a5af58064.s1.eu.hivemq.cloud')
os.environ.setdefault('MQTT_PORT', '8883')
os.environ.setdefault('EDGE_ID', 'edge-01')
os.environ.setdefault('MQTT_PIPELINE_CLIENT_ID', 'edge-01-pipeline')

# Edge modules
from spatial.geometry_utils import bbox_bottom_center, point_in_polygon
from core.gstreamer_builder import (
    DEFAULT_VEHICLE_CLASSES,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    ROOT,
    build_pipeline,
    capture_setup_frame,
    expanded_detection_roi,
    load_class_names,
    normalized_to_pixels,
    pixels_to_normalized,
    resolve_video_source,
    source_type,
)
from analytics.presence_counter import RoiPresenceCounter
from analytics.traffic_classifier import (
    TrafficAnalyzer,
    TrafficStateModel,
)
from analytics.speed_estimator import (
    PerspectiveCalibration,
    StreamTimestamp,
    TrackSpeedEstimator,
)
from communication.mqtt_client import MQTTPublisher
from communication.command_router import CommandHandler


def _collect_edge_metrics(fps):
    """Collect CPU/GPU/RAM/temperature metrics from the Jetson."""
    cpu_val = None
    ram_val = None
    gpu_val = None
    temp_val = None

    try:
        import psutil
        cpu_val = int(psutil.cpu_percent(interval=None))
        vm = psutil.virtual_memory()
        ram_val = int(vm.percent)
    except ImportError:
        pass

    try:
        with open('/sys/devices/virtual/thermal/thermal_zone0/temp', 'r') as f:
            temp_mc = int(f.read().strip())
            temp_val = round(temp_mc / 1000.0, 1)
    except (IOError, ValueError):
        pass

    try:
        gpu_load_path = '/sys/devices/gpu.0/load'
        if os.path.exists(gpu_load_path):
            with open(gpu_load_path, 'r') as f:
                gpu_val = int(f.read().strip())
    except (IOError, ValueError):
        pass

    latency = round(1000.0 / max(fps, 1.0), 1) if fps > 0 else None

    return {
        'fps': round(fps, 1),
        'inference_latency_ms': latency,
        'cpu_percent': cpu_val,
        'cpu_usage_pct': cpu_val,
        'gpu_percent': gpu_val,
        'gpu_usage_pct': gpu_val,
        'ram_percent': ram_val,
        'ram_usage_pct': ram_val,
        'temperature_c': temp_val,
    }


def validate_traffic_config(config):
    if (config.get('frame_width') != FRAME_WIDTH or
            config.get('frame_height') != FRAME_HEIGHT):
        raise ValueError(
            'Traffic ROI config must use %dx%d coordinates' %
            (FRAME_WIDTH, FRAME_HEIGHT)
        )
    analysis = normalized_to_pixels(config.get('analysis_roi', []))
    detection = normalized_to_pixels(config.get('detection_roi', []))
    calibration = normalized_to_pixels(
        config.get('calibration_image_points', [])
    )
    if len(analysis) != 4:
        raise ValueError('Analysis ROI requires exactly 4 ordered points')
    if len(calibration) != 4:
        raise ValueError('Calibration requires exactly 4 image points')
    if len(detection) < 3:
        raise ValueError('Detection ROI requires at least 3 points')
    if float(config.get('road_width_m', 0.0)) <= 0:
        raise ValueError('road_width_m must be positive')
    if float(config.get('road_length_m', 0.0)) <= 0:
        raise ValueError('road_length_m must be positive')
    if int(config.get('lane_count', 0)) <= 0:
        raise ValueError('lane_count must be positive')

    for name, polygon in (
            ('Analysis ROI', analysis),
            ('Detection ROI', detection),
            ('Calibration points', calibration)):
        for x, y in polygon:
            if not 0 <= x < FRAME_WIDTH or not 0 <= y < FRAME_HEIGHT:
                raise ValueError('%s contains a point outside the frame' % name)

    PerspectiveCalibration(
        calibration,
        config['road_width_m'],
        config['road_length_m']
    )


def resolve_config_file(file_path):
    if not file_path:
        return file_path
    p = Path(file_path)
    if p.exists():
        return str(p.resolve())
    candidates = [
        SCRIPT_DIR / p,
        SCRIPT_DIR / 'configs' / p.name,
        Path('/app/configs') / p.name,
        Path('/workspace/configs') / p.name,
    ]
    for cand in candidates:
        if cand.exists():
            return str(cand.resolve())
    return str(p)


def load_traffic_config(config_path):
    resolved = resolve_config_file(config_path)
    path = Path(resolved)
    if not path.exists():
        raise FileNotFoundError('Traffic ROI config file not found: %s' % config_path)
    with path.open('r', encoding='utf-8') as source_file:
        config = json.load(source_file)
    validate_traffic_config(config)
    return config


def _optional_number(value, digits=1):
    if value is None:
        return '--'
    return ('%%.%df' % digits) % float(value)


def _class_speed_text(speed_by_class):
    parts = []
    for class_name, values in sorted(speed_by_class.items()):
        parts.append('%s:%s' % (
            class_name, _optional_number(values.get('avg_speed_kmh'), 1)
        ))
    return ' '.join(parts) or 'waiting'


def _forecast_text(forecast):
    if not forecast.get('ready'):
        return 'Forecast warming: %ss/%ss' % (
            _optional_number(forecast.get('history_seconds'), 0),
            _optional_number(forecast.get('required_history_seconds'), 0)
        )
    horizons = forecast.get('horizons', {})
    return 'Forecast 5m:%s 10m:%s conf:%s' % (
        horizons.get('5m', {}).get('status', '?'),
        horizons.get('10m', {}).get('status', '?'),
        forecast.get('confidence', '?')
    )


def format_diagnostics_table(frame_num, event_time, congestion_score,
                             traffic_status, timing_drift, dt_event,
                             dt_expected, track_rows):
    """Format per-track diagnostic inspection table for debug mode (Python 3.6 compatible)."""
    header = (
        "\n[DIAGNOSTICS] Frame=%d EventTime=%.3fs CongestionScore=%d State=%s | "
        "TimingDrift=%+.4fs (dt_event=%.4fs, dt_expected=%.4fs)" % (
            int(frame_num), float(event_time), int(congestion_score),
            str(traffic_status), float(timing_drift), float(dt_event),
            float(dt_expected)
        )
    )
    cols = (
        "+-------+------------+-----------+--------------------+---------------+---------+---------+------------+"
    )
    title = (
        "| Track | Class      | Speed kmh | World (X, Y)       | Age (s/f)     | DetConf | TrkConf | Area Ratio |"
    )
    lines = [header, cols, title, cols]
    if not track_rows:
        lines.append("| (No tracks currently active inside Analysis ROI)                                            |")
    else:
        for r in track_rows:
            spd_str = "%.1f" % r['speed_kmh'] if r.get('speed_kmh') is not None else "--"
            det_str = "%.3f" % r['det_conf'] if r.get('det_conf') is not None else "N/A"
            trk_str = "%.3f" % r['trk_conf'] if r.get('trk_conf') is not None else "N/A"
            world_str = "(%6.2f, %6.2f)" % (r['world_x'], r['world_y'])
            age_str = "%.1fs (%df)" % (r['age_seconds'], r['age_frames'])
            ratio_str = "%.2f" % r['area_ratio']
            row_str = (
                "| #%-5d | %-10s | %-9s | %-18s | %-13s | %-7s | %-7s | %-10s |" % (
                    int(r['track_id']),
                    str(r['class_name'])[:10],
                    spd_str,
                    world_str,
                    age_str,
                    det_str,
                    trk_str,
                    ratio_str
                )
            )
            lines.append(row_str)
    lines.append(cols)
    return "\n".join(lines)


def add_traffic_display_meta(pyds, batch_meta, frame_meta, geometry,
                             metrics, fps, raw_counts):
    display = pyds.nvds_acquire_display_meta_from_pool(batch_meta)
    display.num_lines = (
        len(geometry['detection']) + len(geometry['analysis'])
    )
    line_index = 0
    for polygon, color, width in (
            (geometry['detection'], (0.1, 0.55, 1.0, 0.85), 2),
            (geometry['analysis'], (0.0, 1.0, 0.0, 0.95), 3)):
        for point_index, point in enumerate(polygon):
            end = polygon[(point_index + 1) % len(polygon)]
            line = display.line_params[line_index]
            line.x1, line.y1 = int(point[0]), int(point[1])
            line.x2, line.y2 = int(end[0]), int(end[1])
            line.line_width = width
            line.line_color.set(*color)
            line_index += 1

    counts_text = ' '.join(
        '%s:%d' % (name, value)
        for name, value in sorted(metrics['counts_by_class'].items())
        if value > 0
    ) or 'empty'
    summary_text = (
        'FPS %.1f | ROI %d | STATUS %s | %s %.1f\n'
        'Counts: %s | raw:%d\n'
        'Speed avg:%s median:%s km/h | stopped:%d (%.0f%%)\n'
        'Speed/class km/h: %s\n'
        'Density raw:%.1f v/km (PCE:%.1f pcu/km) | entries:%d/min | flow:%.1f v/m\n'
        '%s' % (
            fps, metrics['current_vehicle_count'],
            metrics['traffic_status'],
            ('SPEED-REDUCTION' if metrics.get('algorithm_version') == 'v3' else 'SCORE'),
            metrics['congestion_score'],
            counts_text, sum(raw_counts.values()),
            _optional_number(metrics['avg_speed_kmh']),
            _optional_number(metrics['median_speed_kmh']),
            metrics['stopped_vehicle_count'],
            metrics['stopped_vehicle_ratio'] * 100.0,
            _class_speed_text(metrics.get('speed_by_class', {})),
            metrics.get('density_raw_veh_per_km_lane', metrics.get('density_veh_per_km_lane', 0.0)),
            metrics.get('density_pce_per_km_lane', metrics.get('density_veh_per_km_lane', 0.0)),
            metrics['roi_entry_rate_veh_per_min'],
            metrics['estimated_flow_veh_per_min'],
            _forecast_text(metrics['forecast'])
        )
    )
    display.num_labels = 1
    summary = display.text_params[0]
    summary.display_text = summary_text
    summary.x_offset = 15
    summary.y_offset = 18
    summary.font_params.font_name = 'Sans'
    summary.font_params.font_size = 12
    summary.font_params.font_color.set(1.0, 1.0, 1.0, 1.0)
    summary.set_bg_clr = 1
    summary.text_bg_clr.set(0.0, 0.0, 0.0, 0.74)
    pyds.nvds_add_display_meta_to_frame(frame_meta, display)


def resolve_algorithm_version(cli_version, traffic_config):
    """Explicit CLI overrides win; saved config precedes environment fallback."""
    version = str(cli_version or traffic_config.get('algorithm_version')
                  or os.getenv('TRAFFIC_ALGORITHM_VERSION') or 'v2').strip().lower()
    if version not in ('v1', 'v2', 'v3'):
        raise ValueError('algorithm_version must be v1, v2, or v3')
    return version


def resolve_reference_speed(cli_speed, traffic_config):
    """Config null explicitly clears reference speed, including env defaults."""
    value = cli_speed
    if value is None:
        value = (traffic_config['reference_speed_kmh'] if 'reference_speed_kmh' in traffic_config
                 else os.getenv('SPI_REFERENCE_SPEED_KMH'))
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Jetson Nano ROI speed and traffic analytics',
        allow_abbrev=False
    )
    parser.add_argument('source', nargs='?', default=None,
                        help='csi, RTSP URL, video path, or webcam /dev/video0')
    parser.add_argument('--source', '-s', dest='source_opt', default=None)
    parser.add_argument('--sensor-id', type=int, default=0)
    parser.add_argument('--roi-config', default=str(
        SCRIPT_DIR / 'configs' / 'roi_traffic_nano.json'))
    parser.add_argument('--detection-margin', type=int, default=100)
    parser.add_argument('--infer-config', default=str(
        SCRIPT_DIR / 'configs' / 'config_infer_yolo11_nano.txt'))
    parser.add_argument('--interval', type=int, default=1,
                        help='PGIE inference interval (default: 1, 0=infer every frame, 1=every 2nd frame)')
    parser.add_argument('--tracker-config', default=str(
        SCRIPT_DIR / 'configs' / 'config_tracker_optimized.yml'))
    parser.add_argument('--labels', default=str(
        SCRIPT_DIR / 'configs' / 'labels_custom.txt'))
    parser.add_argument('--vehicle-classes', default=','.join(
        DEFAULT_VEHICLE_CLASSES))
    parser.add_argument('--enter-confirm', type=float, default=0.10)
    parser.add_argument('--exit-confirm', type=float, default=0.25)
    parser.add_argument('--lost-timeout', type=float, default=1.00)
    parser.add_argument('--speed-window', type=float, default=2.00)
    parser.add_argument('--speed-min-time', type=float, default=0.80)
    parser.add_argument('--speed-min-displacement', type=float, default=0.35)
    parser.add_argument('--speed-smoothing-alpha', type=float, default=0.25)
    parser.add_argument('--speed-max-gap', type=float, default=0.75)
    parser.add_argument('--speed-max-kmh', type=float, default=130.0)
    parser.add_argument('--source-fps', type=float, default=30.0)
    parser.add_argument('--stopped-speed-kmh', type=float, default=5.0)
    parser.add_argument('--congested-speed-kmh', type=float, default=10.0,
                        help='Threshold speed for CONGESTED state (default: 10.0 km/h)')
    parser.add_argument('--slow-speed-kmh', type=float, default=18.0,
                        help='Threshold speed for SLOW state (default: 18.0 km/h)')
    parser.add_argument('--free-speed-kmh', type=float, default=22.0,
                        help='Threshold speed for guaranteed FREE state override (default: 22.0 km/h)')
    parser.add_argument('--slow-density', type=float, default=140.0,
                        help='Threshold PCE density for SLOW state (default: 140.0 PCU/km/lane)')
    parser.add_argument('--congested-density', type=float, default=220.0,
                        help='Threshold PCE density for CONGESTED state (default: 220.0 PCU/km/lane)')
    parser.add_argument('--forecast-min-history', type=float, default=300.0)
    parser.add_argument('--forecast-history', type=float, default=900.0)
    parser.add_argument('--no-mqtt', action='store_true')
    parser.add_argument('--no-snapshot', action='store_true',
                        help='Disable manual/congestion snapshots')
    parser.add_argument('--no-display', action='store_true')
    parser.add_argument('--setup', action='store_true',
                        help='Open interactive GUI to draw ROI and calibrate road dimensions')
    parser.add_argument(
        '--debug-diagnostics', action='store_true',
        default=os.getenv('EDGE_DEBUG_DIAGNOSTICS', '').strip().lower() in ('1', 'true', 'yes') or
                os.getenv('TRAFFIC_DEBUG_DIAGNOSTICS', '').strip().lower() in ('1', 'true', 'yes'),
        help='Log detailed per-track diagnostics and timing drift when congestion score > 40'
    )
    parser.add_argument(
        '--algo-version', default=None,
        choices=['v1', 'v2', 'v3'],
        help='Traffic analysis algorithm version: v1, v2, or v3 (reference-speed reduction)'
    )
    parser.add_argument(
        '--reference-speed-kmh',
        type=float,
        default=None,
        help='V3 configured reference speed in km/h; configure per camera/ROI'
    )
    parser.add_argument(
        '--free-flow-speed-kmh', type=float, default=None,
        help='Optional independent free-flow speed for HCM LOS proxy'
    )
    parser.add_argument(
        '--minimum-valid-tracks', type=int, default=None,
        help='V3 minimum valid speed tracks required before classification'
    )
    parser.add_argument(
        '--free-speed-ratio-min-percent', type=float, default=None,
        help='Legacy option; V3 uses fixed SPI boundary 50 percent'
    )
    parser.add_argument(
        '--congested-speed-ratio-max-percent', type=float, default=None,
        help='Legacy option; V3 uses fixed SPI boundary 25 percent'
    )
    parser.add_argument(
        '--status-confirm-seconds', type=float, default=None,
        help='V3 minimum persistence time before changing displayed status'
    )
    parser.add_argument(
        '--traffic-context', default=os.getenv('TRAFFIC_CONTEXT', 'signalized'),
        choices=['signalized', 'midblock'],
        help='Traffic context for v2: signalized (has red light) or midblock (no signals)'
    )
    parser.add_argument('--tracker', choices=['nvdcf', 'iou'], default='nvdcf',
                        help='Tracker algorithm: nvdcf or iou (default: nvdcf)')
    parser.add_argument('--min-detector-confidence', type=float, default=0.20,
                        help='Minimum detection confidence for speed estimation (default: 0.20)')
    parser.add_argument('--min-tracker-confidence', type=float, default=0.20,
                        help='Minimum tracker confidence for speed estimation (default: 0.20)')
    parser.add_argument('--max-bbox-area-change', type=float, default=0.60,
                        help='Max allowed bbox area fraction change between frames (default: 0.60)')

    # Benchmark / Profiler (measure_jetson integration)
    auto_measure_default = os.getenv('AUTO_MEASURE', os.getenv('MEASURE_PERF', '1')).strip().lower() in ('1', 'true', 'yes')
    parser.add_argument(
        '--measure', action='store_true',
        default=auto_measure_default,
        help='Tự động đo hiệu năng Jetson (FPS, GPU, CPU, RAM, Temp, Power, Net) song song với pipeline (Mặc định: Bật nếu AUTO_MEASURE=1)'
    )
    parser.add_argument(
        '--no-measure', dest='measure', action='store_false',
        help='Tắt chế độ đo hiệu năng'
    )
    parser.add_argument(
        '--measure-phase', default=None,
        help='Tên kịch bản đo benchmark (vd: baseline, osd_off, live_on, v3_spi). Nếu không truyền sẽ tự động lấy theo tên video/camera'
    )
    parser.add_argument(
        '--measure-duration', type=int, default=None,
        help='Thời gian đo (giây). Mặc định: đo liên tục đến khi video kết thúc hoặc bấm Ctrl+C'
    )
    parser.add_argument(
        '--measure-warmup', type=int, default=os.getenv('MEASURE_WARMUP', '0'),
        help='Số giây warm-up bỏ qua trước khi ghi số liệu (mặc định: 0s)'
    )
    parser.add_argument(
        '--measure-interval', type=float, default=os.getenv('MEASURE_INTERVAL', '1.0'),
        help='Chu kỳ lấy mẫu hiệu năng (giây, mặc định: 1.0s)'
    )
    parser.add_argument(
        '--measure-out', default=os.getenv('MEASURE_OUT', 'bench_results'),
        help='Thư mục lưu kết quả benchmark (mặc định: bench_results)'
    )
    parser.add_argument(
        '--measure-no-tegrastats', action='store_true',
        help='Bỏ qua tegrastats (chạy thử nghiệm trên máy không phải Jetson)'
    )
    parser.add_argument(
        '--measure-auto-stop', action='store_true',
        help='Tự động dừng pipeline khi hết thời gian --measure-duration'
    )
    args = parser.parse_args()

    if not acquire_single_instance_lock():
        print('[PIPELINE] Another pipeline instance is running and holds the camera (%s). '
              'Stop it before starting a new one.' % PIPELINE_LOCK_FILE, file=sys.stderr)
        sys.exit(EXIT_ALREADY_RUNNING)

    # Resolve all config paths to absolute paths
    args.roi_config = resolve_config_file(args.roi_config)
    args.infer_config = resolve_config_file(args.infer_config)
    if args.tracker == 'iou':
        args.tracker_config = resolve_config_file(str(SCRIPT_DIR / 'configs' / 'config_tracker_IOU.yml'))
    else:
        args.tracker_config = resolve_config_file(args.tracker_config)
    args.labels = resolve_config_file(args.labels)

    raw_source = args.source_opt if args.source_opt is not None else (args.source or 'csi')
    resolved_source = resolve_video_source(raw_source)
    kind = source_type(resolved_source)

    if args.setup:
        from spatial.roi_setup import interactive_roi_setup
        should_continue = interactive_roi_setup(
            source=resolved_source,
            config_output_path=args.roi_config,
            sensor_id=args.sensor_id
        )
        if not should_continue:
            print('[INFO] Hoan tat setup. Thoat chuong trinh.')
            return

    traffic_config = load_traffic_config(args.roi_config)

    geometry_lock = threading.Lock()
    geometry = {
        'analysis': normalized_to_pixels(traffic_config['analysis_roi']),
        'detection': normalized_to_pixels(traffic_config['detection_roi'])
    }
    calibration_points = normalized_to_pixels(
        traffic_config['calibration_image_points']
    )
    calibration = PerspectiveCalibration(
        calibration_points,
        traffic_config['road_width_m'],
        traffic_config['road_length_m']
    )
    class_names = load_class_names(args.labels)
    available_classes = set(class_names.values())

    resolved_classes = [c.strip() for c in args.vehicle_classes.split(',') if c.strip()]
    vehicle_classes = tuple(resolved_classes)
    print('[CONFIG] Active vehicle classes: %s' % ', '.join(vehicle_classes))

    presence_counter = RoiPresenceCounter(
        geometry['analysis'], vehicle_classes,
        enter_confirm_seconds=args.enter_confirm,
        exit_confirm_seconds=args.exit_confirm,
        lost_timeout_seconds=args.lost_timeout
    )
    speed_estimator = TrackSpeedEstimator(
        calibration,
        history_seconds=args.speed_window,
        minimum_time_seconds=args.speed_min_time,
        minimum_displacement_m=args.speed_min_displacement,
        smoothing_alpha=args.speed_smoothing_alpha,
        maximum_speed_kmh=args.speed_max_kmh,
        maximum_sample_gap_seconds=args.speed_max_gap
    )
    exclusion_polys = [
        normalized_to_pixels(p) for p in traffic_config.get('exclusion_polygons', [])
    ]

    # Explicit CLI overrides persist across remote config restarts.
    algo_version = resolve_algorithm_version(args.algo_version, traffic_config)
    args.algo_version = algo_version
    traffic_context = str(traffic_config.get('traffic_context') or args.traffic_context or 'signalized').strip().lower()

    if algo_version == 'v2':
        from analytics.traffic_classifier_v2 import (
            ContextAwareTrafficStateModel,
            ContextAwareTrafficAnalyzer,
        )
        state_model = ContextAwareTrafficStateModel(
            context=traffic_context,
            stopped_speed_kmh=args.stopped_speed_kmh,
            congested_speed_kmh=args.congested_speed_kmh,
            slow_speed_kmh=args.slow_speed_kmh,
            slow_density_veh_per_km_lane=args.slow_density,
            congested_density_veh_per_km_lane=args.congested_density,
            free_speed_kmh=args.free_speed_kmh
        )
        analyzer = ContextAwareTrafficAnalyzer(
            road_length_m=traffic_config['road_length_m'],
            lane_count=traffic_config['lane_count'],
            state_model=state_model,
            forecast_history_seconds=args.forecast_history,
            forecast_minimum_history_seconds=args.forecast_min_history,
            exclusion_polygons=exclusion_polys,
            ignore_never_moved=True
        )
        print('[ALGORITHM] >>> Engine Activated: V2 (Context-Aware Dwell-Time | Context: %s) <<<' % traffic_context)
    elif algo_version == 'v3':
        from analytics.traffic_classifier_v3 import SPITrafficAnalyzer
        reference_speed = resolve_reference_speed(args.reference_speed_kmh, traffic_config)
        minimum_valid_tracks = args.minimum_valid_tracks
        if minimum_valid_tracks is None:
            minimum_valid_tracks = traffic_config.get(
                'minimum_valid_tracks', os.getenv('SPI_MIN_VALID_TRACKS', '3')
            )
        confirm_seconds = args.status_confirm_seconds
        if confirm_seconds is None:
            confirm_seconds = traffic_config.get(
                'status_confirm_seconds',
                os.getenv('SPI_STATUS_CONFIRM_SECONDS', '10')
            )
        analyzer = SPITrafficAnalyzer(
            road_length_m=traffic_config['road_length_m'],
            lane_count=traffic_config['lane_count'],
            reference_speed_kmh=reference_speed,
            free_flow_speed_kmh=(args.free_flow_speed_kmh if args.free_flow_speed_kmh is not None
                                 else traffic_config.get('free_flow_speed_kmh')),
            forecast_enabled=os.getenv('ENABLE_EDGE_FORECAST', '0').lower() in ('1', 'true', 'yes'),
            minimum_valid_tracks=int(minimum_valid_tracks),
            free_speed_ratio_min_percent=50.0,
            congested_speed_ratio_max_percent=25.0,
            status_confirm_seconds=float(confirm_seconds),
            forecast_history_seconds=args.forecast_history,
            forecast_minimum_history_seconds=args.forecast_min_history,
            exclusion_polygons=exclusion_polys,
            ignore_never_moved=False,
            traffic_context=traffic_context
        )
        print('[ALGORITHM] >>> Engine Activated: V3 (Reference-speed reduction | Reference: %s km/h) <<<' %
              ('NOT CONFIGURED' if reference_speed is None else ('%.1f' % reference_speed)))
    else:
        state_model = TrafficStateModel(
            stopped_speed_kmh=args.stopped_speed_kmh,
            congested_speed_kmh=args.congested_speed_kmh,
            slow_speed_kmh=args.slow_speed_kmh,
            slow_density_veh_per_km_lane=args.slow_density,
            congested_density_veh_per_km_lane=args.congested_density,
            free_speed_kmh=args.free_speed_kmh
        )
        analyzer = TrafficAnalyzer(
            road_length_m=traffic_config['road_length_m'],
            lane_count=traffic_config['lane_count'],
            state_model=state_model,
            forecast_history_seconds=args.forecast_history,
            forecast_minimum_history_seconds=args.forecast_min_history,
            exclusion_polygons=exclusion_polys,
            ignore_never_moved=True
        )
        print('[ALGORITHM] >>> Engine Activated: V1 (Spatial Multi-Criteria Baseline 50-30-20) <<<')

    mqtt_publisher = None
    heartbeat_thread = None
    snapshot_service = None
    cmd_handler = None
    current_fps = [0.0]

    try:
        import queue
    except ImportError:
        import Queue as queue

    # Fix V7: Hàng đợi RAM và Worker Thread nền nén JPEG / ghi đĩa ảnh preview, không block GStreamer Pad Probe
    preview_frame_queue = queue.Queue(maxsize=1)
    preview_worker_stop = threading.Event()

    def _preview_worker_loop():
        """Worker thread nền chuyên nén JPEG và ghi đĩa ảnh preview, không block GStreamer Pad Probe (Fix V7)."""
        while not preview_worker_stop.is_set():
            try:
                item = preview_frame_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                surf_copy, dest_path = item
                import cv2
                bgr = cv2.cvtColor(surf_copy, cv2.COLOR_RGBA2BGR)
                tmp_dest = dest_path + '.tmp'
                cv2.imwrite(tmp_dest, bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if os.path.exists(tmp_dest):
                    if os.path.exists(dest_path):
                        try:
                            os.remove(dest_path)
                        except Exception:
                            pass
                    os.rename(tmp_dest, dest_path)
                    print('[PIPELINE] Async preview frame encoded & saved to: %s' % dest_path)
            except Exception as enc_err:
                print('[PIPELINE WARNING] Error in async preview worker: %s' % enc_err)
            finally:
                preview_frame_queue.task_done()

    preview_thread = threading.Thread(target=_preview_worker_loop, name='AsyncPreviewWorker', daemon=True)
    preview_thread.start()

    if not args.no_mqtt:
        pipeline_client_id = os.getenv('MQTT_PIPELINE_CLIENT_ID', '%s-pipeline' % os.getenv('EDGE_ID', 'edge-01'))
        # Fix L4: Pipeline worker is NOT agent (is_agent=False: không phát heartbeat/LWT cấp Node)
        mqtt_publisher = MQTTPublisher(command_callback=None, client_id=pipeline_client_id, is_agent=False,
                                       subscribe_commands=True)
        cmd_handler = CommandHandler(mqtt_publisher)
        # Phân vai: tiến trình pipeline CHỈ nhận lệnh live stream (mqtt_client.PIPELINE_OWNED_ACTIONS).
        # Các lệnh khác (get_health, request_status, reload_config, snapshot...) do Jetson Agent xử lý;
        # reload_config được Agent thực hiện bằng cách khởi động lại pipeline với cấu hình mới.

    # Gói Live Streaming: chỉ đăng ký cho Camera CSI. Video file không có
    # live camera và không nhận các lệnh start/keepalive MediaMTX.
    if kind == 'csi':
        try:
            from core.live_stream import register_live_handlers
            register_live_handlers(cmd_handler)
        except Exception as _live_reg_err:
            print('[MAIN] Live stream command handler registration notice: %s' % _live_reg_err)
    else:
        print('[MAIN] Live stream disabled for file source: %s' % resolved_source)

    if not args.no_snapshot:
        if not os.getenv('EDGE_TOKEN', '').strip():
            parser.error('EDGE_TOKEN is required in snap/.env')

        def publish_snapshot_result(result):
            if mqtt_publisher is None:
                return
            mqtt_publisher.publish_command_result(
                result.get('command_id'),
                result.get('action', 'capture_test_snapshot'),
                result.get('status', 'failed'),
                result.get('message', '')
            )

        # RTSP/video analysis uses a fresh CSI photo. CSI analysis copies the
        # annotated frame from this DeepStream pipeline without reopening Argus.
        analysis_source = 'csi' if kind == 'csi' else 'video'
        snapshot_service = create_from_env(
            result_callback=publish_snapshot_result,
            analysis_source=analysis_source
        )
        snapshot_service.start()

    if mqtt_publisher is not None:
        mqtt_publisher._command_callback = cmd_handler.handle
        mqtt_publisher.start()

    global pyds
    try:
        import gi
        gi.require_version('Gst', '1.0')
        gi.require_version('GLib', '2.0')
        from gi.repository import Gst, GLib
        if pyds is None:
            import pyds
    except ImportError as error:
        raise RuntimeError('DeepStream Python dependencies missing: %s' % error)

    Gst.init(None)
    pipeline, tracker, mux, mux_sink, osd = build_pipeline(
        args, resolved_source, kind, Gst
    )
    loop = GLib.MainLoop()
    stopping = [False]
    started_wall = time.monotonic()
    timestamp_clock = StreamTimestamp(
        kind, nominal_fps=args.source_fps,
        maximum_pts_gap_seconds=2.0
    )
    fps_window_start = [started_wall]
    fps_frames = [0]
    current_fps[0] = 0.0
    last_console = [started_wall]
    last_metrics = [None]
    last_telemetry = [started_wall]
    snapshot_context_by_source = {}

    # Diagnostic mode state (Giai doan 1)
    debug_diagnostics = bool(args.debug_diagnostics)
    last_diag_time = [started_wall]
    diag_track_meta = {}
    last_timing = [None]
    track_prev_area = {}
    last_area_prune = [started_wall]
    if debug_diagnostics:
        print('[DIAGNOSTICS] Diagnostic logging ENABLED (will log track table when congestion_score > 40)')

    def request_stop(*_unused):
        if not stopping[0]:
            stopping[0] = True
            loop.quit()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    def tracker_probe(_pad, info):
        buffer = info.get_buffer()
        if not buffer:
            return Gst.PadProbeReturn.OK
        batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(buffer))
        if not batch_meta:
            return Gst.PadProbeReturn.OK

        frame_list = batch_meta.frame_meta_list
        while frame_list:
            frame_meta = pyds.NvDsFrameMeta.cast(frame_list.data)

            with geometry_lock:
                det_roi = geometry['detection']
                ana_roi = geometry['analysis']

            detection_objects = []
            analysis_objects = []
            metadata = []
            raw_counts = Counter()
            obj_diagnostics = {}
            object_list = frame_meta.obj_meta_list

            while object_list:
                obj_meta = pyds.NvDsObjectMeta.cast(object_list.data)
                rect = obj_meta.rect_params
                class_id = int(obj_meta.class_id)
                class_name = class_names.get(class_id, 'class_%d' % class_id)
                bbox = [float(rect.left), float(rect.top),
                        float(rect.left + rect.width),
                        float(rect.top + rect.height)]
                point = bbox_bottom_center(bbox)
                is_vehicle = class_name in vehicle_classes
                in_detection = point_in_polygon(point, det_roi)
                in_analysis = point_in_polygon(point, ana_roi)
                track_id = int(obj_meta.object_id)
                valid_track = track_id < (1 << 63)
                item = {
                    'track_id': track_id,
                    'class_name': class_name,
                    'bbox': bbox
                }
                if is_vehicle and valid_track and in_detection:
                    detection_objects.append(item)
                if is_vehicle and valid_track and in_analysis:
                    analysis_objects.append(item)
                    raw_counts[class_name] += 1
                    # Luôn thu thập (không phụ thuộc --debug-diagnostics) vì bộ lọc tốc độ
                    # --min-detector-confidence / --min-tracker-confidence / --max-bbox-area-change dùng dữ liệu này.
                    # Frame chỉ có tracker (interval>0) có confidence < 0 -> None -> không bị lọc.
                    area = float(rect.width * rect.height)
                    conf = float(obj_meta.confidence) if float(obj_meta.confidence) >= 0.0 else None
                    trk_conf = getattr(obj_meta, 'tracker_confidence', None)
                    if trk_conf is not None:
                        try:
                            trk_conf = float(trk_conf)
                        except (TypeError, ValueError):
                            trk_conf = None
                    obj_diagnostics[track_id] = {
                        'det_conf': conf,
                        'trk_conf': trk_conf,
                        'area': area
                    }
                metadata.append((
                    obj_meta, track_id, class_name,
                    is_vehicle and valid_track and in_analysis
                ))
                try:
                    object_list = object_list.next
                except StopIteration:
                    break

            pts = int(frame_meta.buf_pts)
            pts_seconds = None
            if pts >= 0 and pts != Gst.CLOCK_TIME_NONE:
                pts_seconds = float(pts) / float(Gst.SECOND)
            event_time = timestamp_clock.resolve(
                pts_seconds,
                frame_number=int(frame_meta.frame_num),
                wall_now=time.monotonic()
            )

            curr_frame = int(frame_meta.frame_num)
            timing_drift = 0.0
            dt_event = 0.0
            dt_expected = 0.0
            if debug_diagnostics:
                if last_timing[0] is not None:
                    prev_f, prev_t = last_timing[0]
                    dt_event = event_time - prev_t
                    src_fps = float(args.source_fps) if args.source_fps > 0 else 30.0
                    dt_expected = float(curr_frame - prev_f) / src_fps
                    timing_drift = dt_event - dt_expected
                last_timing[0] = (curr_frame, event_time)

            presence_counter.set_raw_tracks(len(detection_objects))
            presence_events = presence_counter.update(
                detection_objects, event_time
            )
            analyzer.record_presence_events(presence_events)

            # Lọc box tin cậy và kiểm tra sanity diện tích trước khi tính tốc độ
            speed_objects = []
            for obj in analysis_objects:
                tid = obj['track_id']
                odiag = obj_diagnostics.get(tid, {})
                det_conf = odiag.get('det_conf')
                trk_conf = odiag.get('trk_conf')
                if det_conf is not None and det_conf < args.min_detector_confidence:
                    continue
                if trk_conf is not None and trk_conf < args.min_tracker_confidence:
                    continue
                curr_area = odiag.get('area')
                if curr_area is not None:
                    prev_entry = track_prev_area.get(tid)
                    if prev_entry is not None:
                        prev_a = prev_entry[0] if isinstance(prev_entry, tuple) else prev_entry
                        if prev_a > 0:
                            area_change = abs(curr_area - prev_a) / prev_a
                            if area_change > args.max_bbox_area_change:
                                track_prev_area[tid] = (curr_area, event_time)
                                continue
                    track_prev_area[tid] = (curr_area, event_time)
                speed_objects.append(obj)

            # Dọn dẹp rò rỉ bộ nhớ cho track_prev_area định kỳ mỗi 5s (Fix A5)
            if event_time - last_area_prune[0] > 5.0:
                stale_area_keys = [
                    k for k, v in list(track_prev_area.items())
                    if event_time - (v[1] if isinstance(v, tuple) else event_time) > 10.0
                ]
                for k in stale_area_keys:
                    track_prev_area.pop(k, None)
                last_area_prune[0] = event_time

            speeds = speed_estimator.update(speed_objects, event_time)
            presence = presence_counter.snapshot()

            speed_by_class = speed_estimator.class_speed_stats(
                speeds, analysis_objects
            )
            # Dùng tập track đã được xác nhận (hysteresis confirmed) từ RoiPresenceCounter để tính mật độ
            metrics = analyzer.analyze(event_time, presence, speeds)
            metrics['speed_by_class'] = speed_by_class
            # counts_by_class / current_vehicle_count do analyzer trả về (đã trừ xe trong vùng loại trừ)
            last_metrics[0] = metrics
            snapshot_context_by_source[int(frame_meta.source_id)] = dict(metrics)
            if snapshot_service is not None:
                snapshot_service.update_telemetry(metrics)

            # Fix V3: Lắng nghe trigger chụp ảnh từ Agent khi pipeline đang chạy (không mở lại camera CSI)
            if os.path.exists(SNAPSHOT_TRIGGER_FILE):
                try:
                    with open(SNAPSHOT_TRIGGER_FILE, 'r') as _tf:
                        _trig = json.load(_tf)
                    if os.path.exists(SNAPSHOT_TRIGGER_FILE):
                        os.remove(SNAPSHOT_TRIGGER_FILE)
                    _cid = _trig.get('command_id')
                    if snapshot_service is not None and _cid:
                        snapshot_service.request_manual_snapshot(_cid)
                except Exception as _terr:
                    print('[PIPELINE] Snapshot trigger error: %s' % _terr)

            for obj_meta, track_id, class_name, should_display in metadata:
                rect = obj_meta.rect_params
                if not should_display:
                    rect.border_width = 0
                    obj_meta.text_params.display_text = ''
                    continue
                rect.border_width = 2
                rect.border_color.set(0.1, 0.9, 0.2, 1.0)
                speed = speeds.get(track_id)
                speed_text = (
                    '%.1f km/h' % speed['speed_kmh']
                    if speed is not None else '-- km/h'
                )
                confidence = float(obj_meta.confidence)
                if confidence >= 0.0:
                    obj_meta.text_params.display_text = (
                        '%s #%d %.2f %s' %
                        (class_name, track_id, confidence, speed_text)
                    )
                else:
                    obj_meta.text_params.display_text = '%s #%d %s' % (
                        class_name, track_id, speed_text
                    )

            now_wall = time.monotonic()
            fps_frames[0] += 1
            elapsed = now_wall - fps_window_start[0]
            if elapsed >= 1.0:
                current_fps[0] = fps_frames[0] / elapsed
                fps_frames[0] = 0
                fps_window_start[0] = now_wall

            if now_wall - last_console[0] >= 1.0:
                print('[TRAFFIC] fps=%.1f %s' % (
                    current_fps[0], json.dumps(metrics, sort_keys=True)
                ))
                last_console[0] = now_wall

            # Diagnostic inspection table logging when debug is ON and score > 40
            if debug_diagnostics and metrics.get('congestion_score', 0) > 40:
                if now_wall - last_diag_time[0] >= 1.0:
                    last_diag_time[0] = now_wall
                    track_rows = []
                    for obj in analysis_objects:
                        tid = obj['track_id']
                        cname = obj['class_name']
                        spd = speeds.get(tid, {}).get('speed_kmh') if speeds else None
                        wx, wy = speed_estimator.calibration.transform(
                            bbox_bottom_center(obj['bbox'])
                        )
                        odiag = obj_diagnostics.get(tid, {})
                        curr_area = odiag.get('area', 1.0)

                        if tid not in diag_track_meta:
                            diag_track_meta[tid] = {
                                'first_time': event_time,
                                'first_frame': curr_frame,
                                'prev_area': curr_area,
                                'last_seen': event_time
                            }
                            age_s = 0.0
                            age_f = 0
                            area_ratio = 1.0
                        else:
                            tmeta = diag_track_meta[tid]
                            age_s = event_time - tmeta['first_time']
                            age_f = curr_frame - tmeta['first_frame']
                            prev_a = tmeta.get('prev_area', curr_area)
                            area_ratio = (curr_area / prev_a) if prev_a and prev_a > 0 else 1.0
                            tmeta['prev_area'] = curr_area
                            tmeta['last_seen'] = event_time

                        track_rows.append({
                            'track_id': tid,
                            'class_name': cname,
                            'speed_kmh': spd,
                            'world_x': wx,
                            'world_y': wy,
                            'age_seconds': age_s,
                            'age_frames': age_f,
                            'det_conf': odiag.get('det_conf'),
                            'trk_conf': odiag.get('trk_conf'),
                            'area_ratio': area_ratio
                        })

                    stale_diag = [
                        k for k, v in diag_track_meta.items()
                        if event_time - v.get('last_seen', event_time) > 10.0
                    ]
                    for k in stale_diag:
                        del diag_track_meta[k]

                    diag_output = format_diagnostics_table(
                        curr_frame, event_time,
                        metrics.get('congestion_score', 0),
                        metrics.get('traffic_status', 'UNKNOWN'),
                        timing_drift, dt_event, dt_expected,
                        track_rows
                    )
                    print(diag_output)

            # MQTT telemetry (Non-blocking queue; avoids spawning OS threads at 1Hz in GStreamer probe)
            if mqtt_publisher is not None and now_wall - last_telemetry[0] >= 1.0:
                edge_metrics = _collect_edge_metrics(current_fps[0])
                if hasattr(mqtt_publisher, 'queue_telemetry'):
                    mqtt_publisher.queue_telemetry(metrics, edge_metrics)
                else:
                    mqtt_publisher.publish_telemetry(metrics, edge_metrics)
                last_telemetry[0] = now_wall

            if osd is not None:
                add_traffic_display_meta(
                    pyds, batch_meta, frame_meta, geometry,
                    metrics, current_fps[0], raw_counts
                )

            try:
                frame_list = frame_list.next
            except StopIteration:
                break
        return Gst.PadProbeReturn.OK

    tracker.get_static_pad('src').add_probe(
        Gst.PadProbeType.BUFFER, tracker_probe
    )

    preview_format_warned = [False]

    def preview_probe(pad, info):
        """Chụp 1 frame sạch (chưa vẽ OSD) cho WebGIS vẽ ROI khi Agent yêu cầu.

        Đặt ở sink pad của nvdsosd vì tại đây buffer đã là RGBA (pyds.get_nvds_buf_surface
        chỉ đọc được RGBA; đầu ra tracker là NV12 nên không đọc được).
        """
        if not os.path.exists(PREVIEW_TRIGGER_FILE):
            return Gst.PadProbeReturn.OK
        buffer = info.get_buffer()
        if not buffer or preview_frame_queue.full():
            return Gst.PadProbeReturn.OK
        try:
            os.remove(PREVIEW_TRIGGER_FILE)
        except OSError:
            pass
        try:
            caps = pad.get_current_caps()
            fmt = caps.get_structure(0).get_string('format') if caps is not None else None
            if fmt != 'RGBA':
                if not preview_format_warned[0]:
                    print('[PIPELINE] Preview requires RGBA at osd sink pad, got %s' % fmt, file=sys.stderr)
                    preview_format_warned[0] = True
                return Gst.PadProbeReturn.OK
            batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(buffer))
            if not batch_meta or not batch_meta.frame_meta_list:
                return Gst.PadProbeReturn.OK
            frame_meta = pyds.NvDsFrameMeta.cast(batch_meta.frame_meta_list.data)
            batch_id = int(frame_meta.batch_id)
            surface = pyds.get_nvds_buf_surface(hash(buffer), batch_id)
            try:
                # Copy nhanh sang RAM; nén JPEG và ghi file ở worker nền, không chặn luồng GStreamer
                preview_frame_queue.put_nowait((np.array(surface, copy=True, order='C'), LATEST_PREVIEW_FILE))
            finally:
                if hasattr(pyds, 'unmap_nvds_buf_surface'):
                    pyds.unmap_nvds_buf_surface(hash(buffer), batch_id)
        except Exception as _perr:
            print('[PIPELINE] Preview capture error: %s' % _perr)
        return Gst.PadProbeReturn.OK

    osd.get_static_pad('sink').add_probe(Gst.PadProbeType.BUFFER, preview_probe)

    snapshot_pad = None
    snapshot_probe_id = None
    if snapshot_service is not None and kind == 'csi':
        if osd is None:
            raise RuntimeError(
                'CSI snapshot requires the RGBA/OSD branch. Remove '
                '--no-display or update build_pipeline to keep OSD when '
                'snapshot is enabled.'
            )
        snapshot_pad, snapshot_probe_id = attach_snapshot_probe(
            osd,
            snapshot_service,
            get_metrics=lambda frame_meta: snapshot_context_by_source.get(
                int(frame_meta.source_id)
            ),
            source_id=0
        )

    def on_bus_message(_bus, message):
        if message.type == Gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            src_elem = getattr(message, 'src', None)
            src_name = src_elem.get_name() if (src_elem and hasattr(src_elem, 'get_name')) else ''

            # Fix V2: Phân loại lỗi element. Nếu là lỗi nhánh Live Stream (rtspclientsink, encoder, MediaMTX rớt mạng)
            live_elements = {'queue_live', 'live_valve', 'conv_live', 'caps_live', 'enc_live', 'parse_live', 'sink_live'}
            is_live_error = (src_name in live_elements) or ('live' in src_name.lower()) or ('rtsp' in src_name.lower())

            if is_live_error:
                print('[PIPELINE WARNING] Live stream branch error from "%s": %s (AI pipeline kept intact)' % (src_name, error), file=sys.stderr)
                try:
                    from core.live_stream import get_global_controller
                    ctrl = getattr(pipeline, 'live_controller', None) or get_global_controller()
                    if ctrl:
                        ctrl.on_bus_error(error)
                except Exception as ctrl_err:
                    print('[PIPELINE WARNING] Error calling live_controller.on_bus_error: %s' % ctrl_err, file=sys.stderr)
                # Tuyệt đối KHÔNG gọi request_stop()! AI DeepStream và telemetry tiếp tục chạy bình thường!
                return

            print('[PIPELINE CRITICAL ERROR] Element "%s": %s' % (src_name, error), file=sys.stderr)
            request_stop()
        elif message.type == Gst.MessageType.EOS:
            print('[PIPELINE] End of stream')
            request_stop()

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus_handler = bus.connect('message', on_bus_message)

    profiler = None
    if getattr(args, 'measure', False):
        try:
            from measure_jetson import JetsonPerformanceProfiler
            phase_to_use = args.measure_phase
            if not phase_to_use or phase_to_use == 'baseline':
                if kind == 'file' and resolved_source:
                    stem = Path(resolved_source).stem
                    phase_to_use = stem if stem else 'video_file'
                elif kind == 'csi':
                    phase_to_use = 'camera_csi'
                elif kind == 'rtsp':
                    phase_to_use = 'rtsp_stream'
                else:
                    phase_to_use = 'baseline'
                if getattr(args, 'algo_version', None):
                    phase_to_use = '%s_%s' % (phase_to_use, args.algo_version)

            profiler = JetsonPerformanceProfiler(
                phase=phase_to_use,
                duration=args.measure_duration,
                warmup=args.measure_warmup,
                interval=args.measure_interval,
                out_dir=args.measure_out,
                no_tegrastats=args.measure_no_tegrastats,
                get_fps_fn=lambda: current_fps[0],
                on_duration_reached=request_stop if args.measure_auto_stop else None,
                pid=os.getpid()
            )
            profiler.start()
        except Exception as e:
            print('[MEASURE WARNING] Khong the khoi dong profiler: %s' % e, file=sys.stderr)
            profiler = None

    try:
        state_result = pipeline.set_state(Gst.State.PLAYING)
        if state_result == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError('DeepStream pipeline failed to start')
        print('[PIPELINE] Running calibrated ROI traffic analytics: %s' %
              resolved_source)
        loop.run()
    finally:
        pipeline.set_state(Gst.State.NULL)
        bus.disconnect(bus_handler)
        bus.remove_signal_watch()
        mux.release_request_pad(mux_sink)

        if profiler is not None:
            try:
                profiler.stop()
            except Exception as e:
                print('[MEASURE WARNING] Loi khi dung profiler: %s' % e, file=sys.stderr)

        if snapshot_pad is not None and snapshot_probe_id is not None:
            snapshot_pad.remove_probe(snapshot_probe_id)
        if snapshot_service is not None:
            snapshot_service.stop(timeout=20)

        preview_worker_stop.set()
        try:
            preview_frame_queue.put_nowait(None)
        except Exception:
            pass
        if preview_thread is not None and preview_thread.is_alive():
            preview_thread.join(timeout=1.0)

        if mqtt_publisher:
            mqtt_publisher.stop()

    if last_metrics[0] is not None:
        print('[FINAL] %s' % json.dumps(last_metrics[0], sort_keys=True))
    sys.exit(0)


if __name__ == '__main__':
    main()
