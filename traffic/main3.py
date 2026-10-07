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
SCRIPT_DIR = Path(__file__).resolve().parent

# Đảm bảo thư mục gốc project ở vị trí đầu tiên của sys.path để package config/ được ưu tiên
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Nạp cấu hình từ tệp .env DUY NHẤT thông qua config.settings
from config.settings import (
    LOADED_ENV_PATH,
    OUTBOX_DIR,
    DEVICE_NAME,
    ROAD_NAME,
    GEO_LAT,
    GEO_LNG,
    GEO_ALTITUDE_M,
    CAMERA_HEADING,
    CAMERA_FOV,
)

try:
    from snap.runtime import create_from_env
    from snap.deepstream_integration import attach_snapshot_probe
except ImportError as error:
    create_from_env = None
    attach_snapshot_probe = None
    print('[WARNING] Snapshot package not available: %s' % error)

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
    default_source = os.getenv('VIDEO_SOURCE', 'csi')
    parser = argparse.ArgumentParser(
        description='Jetson Nano ROI speed and traffic analytics',
        allow_abbrev=False
    )
    parser.add_argument('source', nargs='?', default=None,
                        help='csi, RTSP URL, video path, or webcam /dev/video0')
    parser.add_argument('--source', '-s', dest='source_opt', default=None)
    parser.add_argument('--sensor-id', type=int, default=int(os.getenv('SENSOR_ID', '0')))
    parser.add_argument('--roi-config', default=os.getenv('ROI_CONFIG', str(
        SCRIPT_DIR / 'configs' / 'roi_traffic_nano.json')))
    parser.add_argument('--detection-margin', type=int, default=100)
    parser.add_argument('--infer-config', default=os.getenv('INFER_CONFIG', str(
        SCRIPT_DIR / 'configs' / 'config_infer_yolo11_nano.txt')))
    parser.add_argument('--tracker-config', default=os.getenv('TRACKER_CONFIG', str(
        SCRIPT_DIR / 'configs' / 'config_tracker_optimized.yml')))
    parser.add_argument('--labels', default=os.getenv('LABELS_FILE', str(
        SCRIPT_DIR / 'configs' / 'labels_custom.txt')))
    parser.add_argument('--vehicle-classes', default=os.getenv('ACTIVE_VEHICLE_CLASSES', ','.join(
        DEFAULT_VEHICLE_CLASSES)))
    parser.add_argument('--enter-confirm', type=float, default=0.10)
    parser.add_argument('--exit-confirm', type=float, default=0.25)
    parser.add_argument('--lost-timeout', type=float, default=1.00)
    parser.add_argument('--speed-window', type=float, default=2.00)
    parser.add_argument('--speed-min-time', type=float, default=0.80)
    parser.add_argument('--speed-min-displacement', type=float, default=0.35)
    parser.add_argument('--speed-smoothing-alpha', type=float, default=0.25)
    parser.add_argument('--speed-max-gap', type=float, default=0.75)
    parser.add_argument('--speed-max-kmh', type=float, default=130.0)
    parser.add_argument('--source-fps', type=float, default=float(os.getenv('SOURCE_FPS', '30.0')))
    parser.add_argument('--stopped-speed-kmh', type=float, default=float(os.getenv('STOPPED_SPEED_KMH', '5.0')))
    parser.add_argument('--congested-speed-kmh', type=float, default=float(os.getenv('CONGESTED_SPEED_KMH', '15.0')))
    parser.add_argument('--slow-speed-kmh', type=float, default=float(os.getenv('SLOW_SPEED_KMH', '30.0')))
    parser.add_argument('--slow-density', type=float, default=float(os.getenv('SLOW_DENSITY', '80.0')))
    parser.add_argument('--congested-density', type=float, default=float(os.getenv('CONGESTED_DENSITY', '120.0')))
    parser.add_argument('--forecast-min-history', type=float, default=300.0)
    parser.add_argument('--forecast-history', type=float, default=900.0)
    parser.add_argument('--no-mqtt', action='store_true')
    parser.add_argument('--no-snapshot', action='store_true',
                        default=not (os.getenv('ENABLE_SNAPSHOT', 'true').lower() in ('true', '1', 'yes')),
                        help='Disable manual/congestion snapshots')
    parser.add_argument('--no-display', action='store_true')
    parser.add_argument('--display', action='store_true',
                        help='Enable X11 display window')
    parser.add_argument('--source-type', default=None,
                        help='Source type compatibility option (file, csi, rtsp)')
    parser.add_argument('--setup', action='store_true',
                        help='Open interactive GUI to draw ROI and calibrate road dimensions')
    parser.add_argument('--backend-url', default=None,
                        help='URL to WebGIS backend API (default from .env)')
    args = parser.parse_args()

    if args.backend_url:
        os.environ['BACKEND_URL'] = args.backend_url

    # Resolve all config paths to absolute paths
    args.roi_config = resolve_config_file(args.roi_config)
    args.infer_config = resolve_config_file(args.infer_config)
    args.tracker_config = resolve_config_file(args.tracker_config)
    args.labels = resolve_config_file(args.labels)

    raw_source = args.source_opt if args.source_opt is not None else (args.source or default_source)
    resolved_source = resolve_video_source(raw_source)
    kind = source_type(resolved_source)

    resolved_classes = [c.strip() for c in args.vehicle_classes.split(',') if c.strip()]
    vehicle_classes = tuple(resolved_classes)

    print("=" * 66)
    print("   EDGE TRAFFIC AI - NVIDIA JETSON NANO PIPELINE STARTUP")
    print("=" * 66)
    print(" [ENV] Config file loaded   : %s" % (LOADED_ENV_PATH or "System Environment"))
    print(" [DEVICE] Edge ID / Camera  : %s / %s" % (os.getenv('EDGE_ID', 'edge-01'), os.getenv('CAMERA_ID', 'camera-01')))
    print(" [DEVICE] Segment / Sensor  : %s / %s" % (os.getenv('SEGMENT_ID', 'segment-001'), os.getenv('SENSOR_ID', '0')))
    print(" [GIS] Tọa độ & Tên trạm    : Quản lý từ WebGIS (Thiết lập / chỉnh sửa trên Web)")
    print(" [BACKEND] WebGIS URL       : %s" % os.getenv('BACKEND_URL', ''))
    print(" [MQTT] Broker              : %s:%s" % (os.getenv('MQTT_HOST', ''), os.getenv('MQTT_PORT', '')))
    print(" [VIDEO] Source / Kind      : %s (%s)" % (resolved_source, kind))
    print(" [CLASSES] Active Vehicles  : %s" % ', '.join(vehicle_classes))
    print(" [SNAPSHOT] Service Active  : %s" % (not args.no_snapshot))
    print("=" * 66)

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
    state_model = TrafficStateModel(
        stopped_speed_kmh=args.stopped_speed_kmh,
        congested_speed_kmh=args.congested_speed_kmh,
        slow_speed_kmh=args.slow_speed_kmh,
        slow_density_veh_per_km_lane=args.slow_density,
        congested_density_veh_per_km_lane=args.congested_density
    )
    analyzer = TrafficAnalyzer(
        road_length_m=traffic_config['road_length_m'],
        lane_count=traffic_config['lane_count'],
        state_model=state_model,
        forecast_history_seconds=args.forecast_history,
        forecast_minimum_history_seconds=args.forecast_min_history
    )

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
        # Tọa độ GPS: Chỉ gửi khi thực tế có phần cứng GPS. Mặc định None để WebGIS yêu cầu thiết lập
        geo_data = None
        if GEO_LAT is not None and GEO_LNG is not None:
            geo_data = {
                'lat': GEO_LAT,
                'lng': GEO_LNG,
                'altitude_m': GEO_ALTITUDE_M or 0.0,
            }

        profile_data = {
            'event': 'device_registered',
            'edge_id': os.getenv('EDGE_ID', 'edge-01'),
            'camera_id': os.getenv('CAMERA_ID', 'camera-01'),
            'segment_id': os.getenv('SEGMENT_ID', 'segment-001'),
            'sensor_id': int(os.getenv('SENSOR_ID', '0')),
            'mac_address': _get_mac_address(),
            'has_gps': geo_data is not None,
            'geo': geo_data,
            'spatial_config': {
                'road_length_m': float(traffic_config.get('road_length_m', 50.0)),
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
                'stop_pipeline',
                'start_pipeline',
                'reload_config',
                'restart_analytics',
                'capture_test_snapshot',
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

        stop_ctx = {'request_stop': None}

        def _handle_stop_pipeline(payload):
            print('[CMD] Received stop_pipeline command from WebGIS, stopping pipeline...')
            fn = stop_ctx.get('request_stop')
            if fn:
                fn()
            return {'status': 'stopped', 'message': 'Pipeline stopped successfully'}

        cmd_handler.register('stop_pipeline', _handle_stop_pipeline)
        cmd_handler.register('restart_analytics', _handle_stop_pipeline)
        cmd_handler.register('start_pipeline', lambda p: {'pid': os.getpid(), 'state': 'running', 'message': 'Pipeline already running'})

    if not args.no_snapshot:
        if not os.getenv('EDGE_TOKEN', '').strip():
            parser.error('EDGE_TOKEN is required in .env')

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
            action = payload.get('action') if isinstance(payload, dict) else None
            if action in ('capture_test_snapshot', 'capture_snapshot'):
                if snapshot_service is None:
                    mqtt_publisher.publish_command_result(
                        payload.get('command_id'),
                        action, 'failed',
                        'Snapshot service is disabled'
                    )
                    return False
                payload_to_handle = dict(payload)
                payload_to_handle['action'] = 'capture_test_snapshot'
                handled = snapshot_service.handle_mqtt_command(payload_to_handle)
                print('[SNAPSHOT] Manual snapshot command dispatched: %s (handled=%s)' % (
                    payload.get('command_id'), handled
                ))
                return handled
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

    # Đảm bảo DISPLAY=:0 để Tegra EGL context khởi tạo thành công
    if not os.environ.get('DISPLAY'):
        os.environ['DISPLAY'] = ':0'

    Gst.init(None)

    # Tự động phát hiện và phục hồi nếu nvstreammux bị blacklist trong cache GStreamer
    if Gst.ElementFactory.find('nvstreammux') is None:
        print('[WARN] Element nvstreammux is missing or blacklisted. Clearing corrupted cache and re-scanning...')
        import glob
        for cf in glob.glob(os.path.expanduser('~/.cache/gstreamer-1.0/registry*.bin')):
            try:
                os.remove(cf)
                print('[INFO] Removed corrupted GStreamer cache: %s' % cf)
            except Exception:
                pass
        ds_plugin_path = '/usr/lib/aarch64-linux-gnu/gstreamer-1.0/deepstream'
        if os.path.isdir(ds_plugin_path):
            Gst.Registry.get().scan_path(ds_plugin_path)
        Gst.update_registry()

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
    total_frames = [0]
    last_frame_wall = [started_wall]
    current_fps[0] = 0.0
    last_console = [started_wall]
    last_metrics = [None]
    last_telemetry = [started_wall]
    snapshot_context_by_source = {}

    def request_stop(*_unused):
        if not stopping[0]:
            stopping[0] = True
            print('[PIPELINE] Requesting graceful stop and closing display window...')
            GLib.idle_add(loop.quit)

    if 'stop_ctx' in locals():
        stop_ctx['request_stop'] = request_stop

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    # Tự động đóng cửa sổ khi chạy xong video file (không cần bấm dừng thủ công)
    if kind == 'file':
        def _file_stream_watchdog():
            if stopping[0]:
                return False
            now = time.monotonic()
            # Khi đã nhận frame (>= 10 frame) và sau 2.0s không còn frame mới -> Video đã chạy hết
            if total_frames[0] >= 10 and (now - last_frame_wall[0]) >= 2.0:
                print('[PIPELINE] Video playback completed (EOS). Closing window automatically...')
                request_stop()
                return False
            return True

        GLib.timeout_add(500, _file_stream_watchdog)

    def tracker_probe(_pad, info):
        buffer = info.get_buffer()
        if not buffer:
            return Gst.PadProbeReturn.OK
        batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(buffer))
        if not batch_meta:
            return Gst.PadProbeReturn.OK

        total_frames[0] += 1
        last_frame_wall[0] = time.monotonic()

        frame_list = batch_meta.frame_meta_list
        while frame_list:
            frame_meta = pyds.NvDsFrameMeta.cast(frame_list.data)

            detection_objects = []
            analysis_objects = []
            metadata = []
            raw_counts = Counter()
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

            presence_counter.set_raw_tracks(len(detection_objects))
            presence_events = presence_counter.update(
                detection_objects, event_time
            )
            analyzer.record_presence_events(presence_events)
            speeds = speed_estimator.update(analysis_objects, event_time)
            presence = presence_counter.snapshot()

            # Override current_total with analysis zone count so that density
            # and stopped_ratio are computed against the same vehicle population
            # that the speed estimator observes. Detection zone is larger and
            # inflates the denominator when computing stopped_ratio.
            analysis_presence = dict(presence)
            analysis_presence['current_total'] = len(analysis_objects)
            analysis_presence['current_by_class'] = dict(raw_counts)
            analysis_presence['current_track_ids'] = [int(obj['track_id']) for obj in analysis_objects]

            speed_by_class = speed_estimator.class_speed_stats(
                speeds, analysis_objects
            )
            metrics = analyzer.analyze(event_time, analysis_presence, speeds)
            metrics['speed_by_class'] = speed_by_class
            if 'counts_by_class' not in metrics:
                metrics['counts_by_class'] = metrics.get(
                    'current_by_class', presence.get('current_by_class', {})
                )
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

            # MQTT telemetry
            if mqtt_publisher is not None and now_wall - last_telemetry[0] >= 1.0:
                edge_metrics = _collect_edge_metrics(current_fps[0])
                threading.Thread(
                    target=mqtt_publisher.publish_telemetry,
                    args=(metrics, edge_metrics),
                    daemon=True
                ).start()
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
            print(
                '[WARNING] CSI snapshot requires the RGBA/OSD branch. Snapshot probe disabled.',
                file=sys.stderr
            )
        else:
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
            print('[PIPELINE ERROR] %s' % error, file=sys.stderr)
            request_stop()
        elif message.type == Gst.MessageType.EOS:
            print('[PIPELINE] End of stream received on bus.')
            request_stop()
        return True

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus_handler = bus.connect('message', on_bus_message)

    # Thêm pad probe bắt EOS trực tiếp từ sink pad (nveglglessink)
    sink_elem = pipeline.get_by_name('sink')
    if sink_elem:
        sink_pad = sink_elem.get_static_pad('sink')
        if sink_pad:
            def _sink_event_probe(_pad, info):
                evt = info.get_event()
                if evt and evt.type == Gst.EventType.EOS:
                    print('[PIPELINE] EOS event reached display sink pad, closing window...')
                    request_stop()
                return Gst.PadProbeReturn.OK
            sink_pad.add_probe(Gst.PadProbeType.EVENT_DOWNSTREAM, _sink_event_probe)
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

        if heartbeat_thread:
            heartbeat_thread.stop()
        if mqtt_publisher:
            mqtt_publisher.stop()

    if last_metrics[0] is not None:
        print('[FINAL] %s' % json.dumps(last_metrics[0], sort_keys=True))


if __name__ == '__main__':
    main()
