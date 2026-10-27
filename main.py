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

os.environ.setdefault('BACKEND_URL', 'http://192.168.1.26:8000')
os.environ.setdefault('EDGE_TOKEN', 'dev-edge-token')
os.environ.setdefault('MQTT_HOST',
                      '829e7cb26c594257a7470e5a5af58064.s1.eu.hivemq.cloud')
os.environ.setdefault('MQTT_PORT', '8883')
os.environ.setdefault('MQTT_USER', 'admin')
os.environ.setdefault('MQTT_PASS', '12345678')
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
from communication.mqtt_client import MQTTPublisher, HeartbeatThread
from communication.command_router import CommandHandler
from communication.system_metrics import collect_comprehensive_health, _get_mac_address
from config.settings import (
    OUTBOX_DIR,
    DEVICE_NAME,
    ROAD_NAME,
    GEO_LAT,
    GEO_LNG,
    GEO_ALTITUDE_M,
    CAMERA_HEADING,
    CAMERA_FOV,
)


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
        'FPS %.1f | ROI %d | STATUS %s | SCORE %d\n'
        'Counts: %s | raw:%d\n'
        'Speed avg:%s median:%s km/h | stopped:%d (%.0f%%)\n'
        'Speed/class km/h: %s\n'
        'Density:%.1f veh/km/lane | ROI entries:%d/min | flow est:%.1f veh/min\n'
        '%s' % (
            fps, metrics['current_vehicle_count'],
            metrics['traffic_status'], metrics['congestion_score'],
            counts_text, sum(raw_counts.values()),
            _optional_number(metrics['avg_speed_kmh']),
            _optional_number(metrics['median_speed_kmh']),
            metrics['stopped_vehicle_count'],
            metrics['stopped_vehicle_ratio'] * 100.0,
            _class_speed_text(metrics.get('speed_by_class', {})),
            metrics['density_veh_per_km_lane'],
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
        '--algo-version', default=os.getenv('TRAFFIC_ALGORITHM_VERSION', 'v1'),
        choices=['v1', 'v2'],
        help='Traffic classification algorithm version: v1 (Snapshot) or v2 (Context Dwell-Time)'
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
    args = parser.parse_args()

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

    algo_version = str(args.algo_version).strip().lower()
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

    if not args.no_mqtt:
        pipeline_client_id = os.getenv('MQTT_PIPELINE_CLIENT_ID', '%s-pipeline' % os.getenv('EDGE_ID', 'edge-01'))
        mqtt_publisher = MQTTPublisher(command_callback=None, client_id=pipeline_client_id)
        cmd_handler = CommandHandler(mqtt_publisher)

        # Gói 1: Profile & GIS Registration cho WebGIS
        profile_data = {
            'event': 'device_registered',
            'edge_id': os.getenv('EDGE_ID', 'edge-01'),
            'device_name': DEVICE_NAME,
            'mac_address': _get_mac_address(),
            'geo': {
                'lat': GEO_LAT,
                'lng': GEO_LNG,
                'altitude_m': GEO_ALTITUDE_M,
                'segment_id': os.getenv('SEGMENT_ID', 'segment-001'),
                'road_name': ROAD_NAME,
                'heading': CAMERA_HEADING,
                'fov': CAMERA_FOV,
            },
            'spatial_config': {
                'road_length_m': float(traffic_config.get('road_length_m', 20.0)),
                'road_width_m': float(traffic_config.get('road_width_m', 7.0)),
                'lane_count': int(traffic_config.get('lane_count', 2)),
                'homography_calibrated': True,
            },
            'system_profile': {
                'hardware': 'NVIDIA Jetson Nano',
                'app_version': '1.0.0',
                'model_version': os.getenv('MODEL_VERSION', 'exp.engine'),
                'supported_classes': list(vehicle_classes),
            },
            'supported_commands': [
                'get_health',
                'request_status',
                'reload_config',
                'restart_analytics',
                'capture_test_snapshot',
                'start_live',
                'stop_live',
                'live_keepalive',
                'live_status',
            ],
        }
        mqtt_publisher.set_registration_profile(profile_data)

        # Gói 2: Chuẩn đoán sức khỏe theo yêu cầu WebGIS
        def _handle_get_health(payload):
            return collect_comprehensive_health(
                fps=current_fps[0],
                camera_status='streaming',
                outbox_dir=str(OUTBOX_DIR),
            )

        cmd_handler.register('get_health', _handle_get_health)
        cmd_handler.register('request_status', lambda p: {
            'status': 'running',
            'edge_id': os.getenv('EDGE_ID', 'edge-01'),
            'fps': round(float(current_fps[0]), 1),
            'model_version': os.getenv('MODEL_VERSION', 'exp.engine'),
        })

        # Gói điều khiển: Hot-Reload ROI và Homography Calibration trực tiếp trong bộ nhớ (Mục 6)
        def _handle_reload_config(payload):
            print('[HOT-RELOAD] Received reload_config command via MQTT...')
            params = payload.get('params', {}) if isinstance(payload, dict) else {}
            cfg_path = params.get('config_path') or args.roi_config
            new_cfg = load_traffic_config(cfg_path)
            
            # Cập nhật đa giác ROI
            geometry['analysis'] = normalized_to_pixels(new_cfg['analysis_roi'])
            geometry['detection'] = normalized_to_pixels(new_cfg['detection_roi'])
            presence_counter.update_geometry(geometry['analysis'])
            
            # Cập nhật ma trận phối cảnh
            calib_pts = normalized_to_pixels(new_cfg['calibration_image_points'])
            new_calib = PerspectiveCalibration(
                calib_pts,
                new_cfg['road_width_m'],
                new_cfg['road_length_m']
            )
            speed_estimator.update_calibration(new_calib)
            
            # Cập nhật thông số mặt đường chuẩn xác qua update_geometry
            analyzer.update_geometry(new_cfg['road_length_m'], new_cfg['lane_count'])
            if hasattr(state_model, 'context') and 'traffic_context' in new_cfg:
                ctx_val = str(new_cfg['traffic_context']).lower().strip()
                if ctx_val in ('signalized', 'midblock'):
                    state_model.context = ctx_val
                    print('[HOT-RELOAD] Updated traffic context to: %s' % ctx_val)

            print('[HOT-RELOAD] Successfully reloaded ROI and Calibration in memory without restarting!')
            return {
                'command_id': payload.get('command_id', 'unknown'),
                'status': 'SUCCESS',
                'message': 'ROI and Calibration hot-reloaded successfully',
                'road_length_m': new_cfg['road_length_m'],
                'road_width_m': new_cfg['road_width_m']
            }

        cmd_handler.register('reload_config', _handle_reload_config)

        # Gói Live Streaming: MediaMTX On-Demand
        try:
            from core.live_stream import register_live_handlers
            register_live_handlers(cmd_handler)
        except Exception as _live_reg_err:
            print('[MAIN] Live stream command handler registration notice: %s' % _live_reg_err)

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
        def route_command(payload):
            if (isinstance(payload, dict) and
                    payload.get('action') == 'capture_test_snapshot'):
                if snapshot_service is None:
                    mqtt_publisher.publish_command_result(
                        payload.get('command_id'),
                        'capture_test_snapshot', 'failed',
                        'Snapshot service is disabled'
                    )
                    return False
                # SnapshotCoordinator sends queued/completed/failed only after
                # the real capture state changes. Do not let CommandHandler send
                # a false "completed" result immediately.
                return snapshot_service.handle_mqtt_command(payload)
            return cmd_handler.handle(payload)

        mqtt_publisher._command_callback = route_command
        mqtt_publisher.start()
        heartbeat_thread = HeartbeatThread(mqtt_publisher)
        heartbeat_thread.start()

    try:
        import gi
        gi.require_version('Gst', '1.0')
        gi.require_version('GLib', '2.0')
        from gi.repository import Gst, GLib
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
                in_detection = point_in_polygon(point, geometry['detection'])
                in_analysis = point_in_polygon(point, geometry['analysis'])
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
                    if debug_diagnostics:
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
                    prev_a = track_prev_area.get(tid)
                    if prev_a is not None and prev_a > 0:
                        area_change = abs(curr_area - prev_a) / prev_a
                        if area_change > args.max_bbox_area_change:
                            track_prev_area[tid] = curr_area
                            continue
                    track_prev_area[tid] = curr_area
                speed_objects.append(obj)

            speeds = speed_estimator.update(speed_objects, event_time)
            presence = presence_counter.snapshot()

            speed_by_class = speed_estimator.class_speed_stats(
                speeds, analysis_objects
            )
            # Dùng tập track đã được xác nhận (hysteresis confirmed) từ RoiPresenceCounter để tính mật độ
            metrics = analyzer.analyze(event_time, presence, speeds)
            metrics['speed_by_class'] = speed_by_class
            metrics['counts_by_class'] = dict(presence['current_by_class'])
            metrics['current_by_class'] = dict(presence['current_by_class'])
            metrics['current_vehicle_count'] = presence['current_total']
            last_metrics[0] = metrics
            snapshot_context_by_source[int(frame_meta.source_id)] = dict(metrics)
            if snapshot_service is not None:
                snapshot_service.update_telemetry(metrics)

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

    # On-Demand Live Streaming (kích hoạt khi LIVE_STREAM_ENABLED=1)
    live_stream_sender = None
    live_appsink = pipeline.get_by_name('live_appsink')
    if live_appsink is not None:
        try:
            from communication.live_stream_sender import LiveStreamSender
            from config.settings import BACKEND_URL, EDGE_ID, EDGE_TOKEN, LIVE_WIDTH, LIVE_HEIGHT, LIVE_FPS
            live_stream_sender = LiveStreamSender(
                backend_url=BACKEND_URL,
                edge_id=EDGE_ID,
                edge_token=EDGE_TOKEN,
                width=LIVE_WIDTH,
                height=LIVE_HEIGHT,
                fps=LIVE_FPS
            )
            live_stream_sender.start()

            def on_live_sample(sink):
                sample = sink.emit('pull-sample')
                if not sample:
                    return Gst.FlowReturn.OK
                if not live_stream_sender.is_streaming:
                    return Gst.FlowReturn.OK
                buf = sample.get_buffer()
                if not buf:
                    return Gst.FlowReturn.OK
                success, map_info = buf.map(Gst.MapFlags.READ)
                if success:
                    try:
                        live_stream_sender.send_frame(bytes(map_info.data))
                    finally:
                        buf.unmap(map_info)
                return Gst.FlowReturn.OK

            live_appsink.connect('new-sample', on_live_sample)
            print('[PIPELINE] Live Stream appsink successfully hooked to LiveStreamSender')
        except Exception as err:
            print('[PIPELINE] Failed to initialize LiveStreamSender: %s' % err)

    def on_bus_message(_bus, message):
        if message.type == Gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            print('[PIPELINE ERROR] %s' % error, file=sys.stderr)
            request_stop()
        elif message.type == Gst.MessageType.EOS:
            print('[PIPELINE] End of stream')
            request_stop()

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus_handler = bus.connect('message', on_bus_message)
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

        if snapshot_pad is not None and snapshot_probe_id is not None:
            snapshot_pad.remove_probe(snapshot_probe_id)
        if snapshot_service is not None:
            snapshot_service.stop(timeout=20)
        if live_stream_sender is not None:
            live_stream_sender.stop()

        if heartbeat_thread:
            heartbeat_thread.stop()
        if mqtt_publisher:
            mqtt_publisher.stop()

    if last_metrics[0] is not None:
        print('[FINAL] %s' % json.dumps(last_metrics[0], sort_keys=True))


if __name__ == '__main__':
    main()
