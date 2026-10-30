#!/usr/bin/env python3
"""DeepStream pipeline builder for Jetson Nano.

Provides the shared constants and GStreamer/DeepStream pipeline setup
used by main_roi_traffic.py.  Compatible with Python 3.6 (JetPack 4.x).

This module must only import DeepStream/GStreamer when actually building
the pipeline so that unit tests can import traffic_analytics.py and
roi_presence_counter.py on a development PC without DeepStream installed.
"""

import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
ROOT = Path(__file__).resolve().parent.parent

# Auto-load master .env
_env_path = ROOT / ".env"
if _env_path.is_file():
    try:
        with open(str(_env_path), "r", encoding="utf-8") as _f:
            for _l in _f:
                _l = _l.strip()
                if _l and not _l.startswith("#") and "=" in _l:
                    _k, _v = _l.split("=", 1)
                    _v = _v.split("#")[0].strip().strip("\"'")
                    os.environ[_k.strip()] = _v
    except Exception:
        pass

DEFAULT_VEHICLE_CLASSES = ('motorbike', 'car', 'truck', 'bus', 'bicycle')
ALL_CLASSES = ('bicycle', 'bus', 'car', 'motorbike', 'people', 'truck', 'vehicle_fire')


# ---------------------------------------------------------------------------
# Source helpers
# ---------------------------------------------------------------------------

def source_type(source):
    """Return 'csi', 'rtsp', 'file', or 'video'."""
    s = str(source).strip().lower()
    if s == 'csi' or s == 'csi://0' or s == 'csi://1':
        return 'csi'
    if s.startswith('rtsp://') or s.startswith('rtsps://'):
        return 'rtsp'
    if s.isdigit() or s.startswith('/dev/video') or s.startswith('v4l2'):
        return 'video'
    return 'file'


def resolve_video_source(source):
    """Resolve shorthand (e.g. '0', '1') or search paths to GStreamer-compatible source."""
    s = str(source).strip()
    if s.isdigit():
        return '/dev/video%s' % s
    if source_type(s) == 'file':
        p = Path(s)
        if p.exists():
            return str(p.resolve())
        # Try candidate paths if user referenced Video/ or relative path
        candidates = [
            ROOT / s,
            ROOT / 'Video' / p.name,
            Path('/workspace') / 'Video' / p.name,
            Path('/app') / 'Video' / p.name,
            Path('/workspace') / s,
            Path('/app') / s,
        ]
        for cand in candidates:
            if cand.exists():
                print('[INFO] Auto-resolved video source: %s -> %s' % (s, cand))
                return str(cand.resolve())
    return s


# ---------------------------------------------------------------------------
# ROI helpers
# ---------------------------------------------------------------------------

def normalized_to_pixels(points):
    """Convert list of [nx, ny] (0-1) to pixel coordinates."""
    result = []
    for point in points:
        x = float(point[0]) * FRAME_WIDTH
        y = float(point[1]) * FRAME_HEIGHT
        result.append([x, y])
    return result


def pixels_to_normalized(points):
    """Convert list of [px, py] pixel coordinates to normalized (0-1)."""
    result = []
    for point in points:
        x = float(point[0]) / FRAME_WIDTH
        y = float(point[1]) / FRAME_HEIGHT
        result.append([x, y])
    return result


def expanded_detection_roi(analysis_roi_pixels, margin_px):
    """Return detection ROI polygon by expanding analysis ROI by margin_px."""
    if not analysis_roi_pixels:
        return []
    margin = float(margin_px)
    # Compute centroid
    cx = sum(p[0] for p in analysis_roi_pixels) / len(analysis_roi_pixels)
    cy = sum(p[1] for p in analysis_roi_pixels) / len(analysis_roi_pixels)
    result = []
    for px, py in analysis_roi_pixels:
        dx = px - cx
        dy = py - cy
        length = (dx * dx + dy * dy) ** 0.5
        if length < 1e-6:
            result.append([px, py])
        else:
            scale = (length + margin) / length
            result.append([
                cx + dx * scale,
                cy + dy * scale,
            ])
    # Clamp to frame
    clamped = []
    for x, y in result:
        clamped.append([
            max(0.0, min(float(FRAME_WIDTH - 1), x)),
            max(0.0, min(float(FRAME_HEIGHT - 1), y)),
        ])
    return clamped


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def load_class_names(labels_path):
    """Return dict {class_id: class_name} from a labels file (one per line)."""
    p = Path(labels_path)
    if not p.exists():
        candidates = [
            ROOT / labels_path,
            ROOT / 'configs' / p.name,
            Path('/app/configs') / p.name,
            Path('/workspace/configs') / p.name,
        ]
        for cand in candidates:
            if cand.exists():
                p = cand
                break
    result = {}
    try:
        with open(str(p), 'r', encoding='utf-8') as f:
            for idx, line in enumerate(f):
                name = line.strip()
                if name:
                    result[idx] = name
    except IOError as err:
        raise IOError('Cannot read labels file %s: %s' % (labels_path, err))
    return result


# ---------------------------------------------------------------------------
# Frame capture for setup
# ---------------------------------------------------------------------------

def capture_setup_frame(source, sensor_id=0):
    """Capture a single frame for ROI setup (without DeepStream)."""
    import cv2
    import numpy as np

    kind = source_type(source)
    cap = None

    if kind == 'csi':
        pipeline = (
            'nvarguscamerasrc sensor-id=%d ! '
            'video/x-raw(memory:NVMM),format=NV12,width=%d,height=%d,framerate=30/1 ! '
            'nvvidconv flip-method=0 ! '
            'video/x-raw,format=BGRx ! videoconvert ! appsink'
        ) % (sensor_id, FRAME_WIDTH, FRAME_HEIGHT)
        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    elif kind == 'rtsp':
        cap = cv2.VideoCapture(source)
    elif kind == 'video':
        resolved = resolve_video_source(source)
        if resolved.startswith('/dev/video'):
            try:
                dev_idx = int(resolved.replace('/dev/video', ''))
                cap = cv2.VideoCapture(dev_idx)
            except ValueError:
                cap = cv2.VideoCapture(resolved)
        else:
            cap = cv2.VideoCapture(resolved)
    else:
        cap = cv2.VideoCapture(source)

    if not cap or not cap.isOpened():
        print('[SETUP] Cannot open camera, using blank frame', file=sys.stderr)
        return np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype='uint8')

    for _ in range(5):
        ret, frame = cap.read()
        if ret and frame is not None:
            cap.release()
            return frame
    cap.release()
    return np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype='uint8')


# ---------------------------------------------------------------------------
# DeepStream infer config auto-resolver
# ---------------------------------------------------------------------------

def ensure_infer_config(infer_config_path):
    """Validate and auto-heal infer config paths (custom-lib, engine, onnx, labels)."""
    p = Path(infer_config_path)
    if not p.is_file():
        return infer_config_path

    try:
        with open(str(p), 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return str(p)

    # 1. Resolve custom-lib-path
    lib_candidates = [
        '/opt/nvidia/deepstream/deepstream/sources/DeepStream-Yolo/nvdsinfer_custom_impl_Yolo/libnvdsinfer_custom_impl_Yolo.so',
        '/opt/nvidia/deepstream/deepstream-6.0/sources/DeepStream-Yolo/nvdsinfer_custom_impl_Yolo/libnvdsinfer_custom_impl_Yolo.so',
        '/opt/nvidia/deepstream/deepstream/lib/libnvdsinfer_custom_impl_Yolo.so',
        '/opt/nvidia/deepstream/deepstream-6.0/lib/libnvdsinfer_custom_impl_Yolo.so',
    ]
    found_lib = None
    for cand in lib_candidates:
        if os.path.isfile(cand):
            found_lib = cand
            break

    if not found_lib:
        for search_root in ['/opt/nvidia/deepstream', '/workspace']:
            if os.path.isdir(search_root):
                for root_dir, _, files in os.walk(search_root):
                    if 'libnvdsinfer_custom_impl_Yolo.so' in files:
                        found_lib = os.path.join(root_dir, 'libnvdsinfer_custom_impl_Yolo.so')
                        break
            if found_lib:
                break

    if found_lib:
        print('[INFO] Using YOLO custom parser lib: %s' % found_lib)

    # 2. Resolve model-engine-file
    engine_candidates = [
        '/workspace/1908/exp.engine',
        '/workspace/exp.engine',
        '/app/exp.engine',
        str(ROOT / 'exp.engine'),
        str(ROOT / 'configs' / 'exp.engine'),
    ]
    found_engine = None
    for cand in engine_candidates:
        if os.path.isfile(cand):
            found_engine = cand
            break

    # 3. Resolve onnx-file
    onnx_candidates = [
        '/workspace/1908/exp.onnx',
        '/workspace/exp.onnx',
        '/app/exp.onnx',
        str(ROOT / 'exp.onnx'),
        str(ROOT / 'configs' / 'exp.onnx'),
    ]
    found_onnx = None
    for cand in onnx_candidates:
        if os.path.isfile(cand):
            found_onnx = cand
            break

    # 4. Resolve labelfile-path
    label_candidates = [
        str(ROOT / 'configs' / 'labels_custom.txt'),
        '/app/configs/labels_custom.txt',
        '/workspace/configs/labels_custom.txt',
        'labels_custom.txt',
    ]
    found_label = None
    for cand in label_candidates:
        if os.path.isfile(cand):
            found_label = cand
            break

    lines = content.splitlines()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('custom-lib-path=') and found_lib:
            new_lines.append('custom-lib-path=%s' % found_lib)
        elif stripped.startswith('model-engine-file='):
            cur_val = stripped.split('=', 1)[1].strip()
            if not os.path.isfile(cur_val) and found_engine:
                new_lines.append('model-engine-file=%s' % found_engine)
            else:
                new_lines.append(line)
        elif stripped.startswith('onnx-file='):
            cur_val = stripped.split('=', 1)[1].strip()
            if not os.path.isfile(cur_val) and found_onnx:
                new_lines.append('onnx-file=%s' % found_onnx)
            else:
                new_lines.append(line)
        elif stripped.startswith('labelfile-path='):
            cur_val = stripped.split('=', 1)[1].strip()
            if not os.path.isfile(cur_val) and found_label:
                new_lines.append('labelfile-path=%s' % found_label)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    new_content = '\n'.join(new_lines) + '\n'
    if new_content != content:
        try:
            with open(str(p), 'w', encoding='utf-8') as f:
                f.write(new_content)
            print('[INFO] Auto-healed infer config: %s' % p)
        except Exception as e:
            print('[WARN] Could not update config %s: %s' % (p, e))

    return str(p)


# ---------------------------------------------------------------------------
# DeepStream pipeline builder
# ---------------------------------------------------------------------------

def build_pipeline(args, source, kind, Gst):
    """Build and return the DeepStream GStreamer pipeline elements.

    Returns (pipeline, tracker, mux, mux_sink, osd)
    """
    pipeline = Gst.Pipeline()

    streammux = _make(Gst, 'nvstreammux', 'mux')
    streammux.set_property('batch-size', 1)
    streammux.set_property('width', FRAME_WIDTH)
    streammux.set_property('height', FRAME_HEIGHT)
    streammux.set_property('batched-push-timeout', 40000)
    if kind in ('csi', 'video', 'rtsp'):
        streammux.set_property('live-source', 1)

    pipeline.add(streammux)
    mux_sink = streammux.get_request_pad('sink_0')

    # Source elements based on source kind
    if kind == 'csi':
        src = _make(Gst, 'nvarguscamerasrc', 'src')
        src.set_property('sensor-id', args.sensor_id)
        if src.find_property('bufapi-version'):
            src.set_property('bufapi-version', True)
        caps_filter = _make(Gst, 'capsfilter', 'csi_caps')
        caps_filter.set_property(
            'caps',
            Gst.Caps.from_string(
                'video/x-raw(memory:NVMM),format=NV12,width=%d,height=%d,framerate=30/1'
                % (FRAME_WIDTH, FRAME_HEIGHT)
            )
        )
        nvvidconv_csi = _make(Gst, 'nvvideoconvert', 'nvvidconv_csi')
        caps_nvvidconv = _make(Gst, 'capsfilter', 'caps_nvvidconv_csi')
        caps_nvvidconv.set_property(
            'caps',
            Gst.Caps.from_string('video/x-raw(memory:NVMM),format=NV12')
        )
        pipeline.add(src)
        pipeline.add(caps_filter)
        pipeline.add(nvvidconv_csi)
        pipeline.add(caps_nvvidconv)
        src.link(caps_filter)
        caps_filter.link(nvvidconv_csi)
        nvvidconv_csi.link(caps_nvvidconv)
        caps_nvvidconv.get_static_pad('src').link(mux_sink)

    elif kind in ('rtsp', 'file'):
        src = _make(Gst, 'uridecodebin', 'uri_decode_bin')
        if str(source).startswith(('rtsp://', 'http://', 'https://', 'file://')):
            uri = str(source)
        else:
            uri = 'file://' + os.path.abspath(str(source))
        src.set_property('uri', uri)

        # Converter & capsfilter to guarantee memory:NVMM into streammux
        conv = _make(Gst, 'nvvideoconvert', 'source_conv')
        conv_caps = _make(Gst, 'capsfilter', 'source_caps')
        conv_caps.set_property(
            'caps',
            Gst.Caps.from_string('video/x-raw(memory:NVMM),format=NV12')
        )
        pipeline.add(src)
        pipeline.add(conv)
        pipeline.add(conv_caps)

        conv.link(conv_caps)
        conv_caps.get_static_pad('src').link(mux_sink)

        def _pad_added(_element, pad):
            caps = pad.get_current_caps()
            if not caps:
                caps = pad.query_caps()
            if caps and caps.get_size() > 0:
                struct_name = caps.get_structure(0).get_name()
                if 'video' in struct_name:
                    conv_sink = conv.get_static_pad('sink')
                    if not conv_sink.is_linked():
                        ret = pad.link(conv_sink)
                        print('[PIPELINE] Linked decoder video pad -> nvvidconv -> streammux: %s' % ret)

        src.connect('pad-added', _pad_added)

    else:
        # USB camera (v4l2src)
        resolved_dev = resolve_video_source(source)
        src = _make(Gst, 'v4l2src', 'src')
        src.set_property('device', resolved_dev)
        vidconv = _make(Gst, 'videoconvert', 'vidconv')
        conv_caps = _make(Gst, 'capsfilter', 'conv_caps')
        conv_caps.set_property(
            'caps',
            Gst.Caps.from_string('video/x-raw,format=I420')
        )
        nvvidconv = _make(Gst, 'nvvideoconvert', 'nvvidconv')
        caps_filter = _make(Gst, 'capsfilter', 'usb_caps')
        caps_filter.set_property(
            'caps',
            Gst.Caps.from_string(
                'video/x-raw(memory:NVMM),format=NV12,width=%d,height=%d'
                % (FRAME_WIDTH, FRAME_HEIGHT)
            )
        )
        pipeline.add(src)
        pipeline.add(vidconv)
        pipeline.add(conv_caps)
        pipeline.add(nvvidconv)
        pipeline.add(caps_filter)
        src.link(vidconv)
        vidconv.link(conv_caps)
        conv_caps.link(nvvidconv)
        nvvidconv.link(caps_filter)
        caps_filter.get_static_pad('src').link(mux_sink)

    # Inference (YOLO)
    pgie = _make(Gst, 'nvinfer', 'pgie')
    infer_cfg = ensure_infer_config(args.infer_config)
    pgie.set_property('config-file-path', infer_cfg)
    infer_interval = getattr(args, 'interval', None)
    if infer_interval is not None and infer_interval >= 0:
        pgie.set_property('interval', int(infer_interval))

    # Tracker (NvDCF)
    tracker = _make(Gst, 'nvtracker', 'tracker')
    tracker.set_property('ll-lib-file',
                         '/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so')
    tracker.set_property('ll-config-file', args.tracker_config)
    tracker.set_property('tracker-width', 640)
    tracker.set_property('tracker-height', 384)
    tracker.set_property('gpu-id', 0)
    tracker.set_property('enable-batch-process', 1)

    no_display = getattr(args, 'no_display', False)
    nvvidconv_osd = _make(Gst, 'nvvideoconvert', 'nvvidconv_osd')
    osd = _make(Gst, 'nvdsosd', 'osd')
    pipeline.add(nvvidconv_osd)
    pipeline.add(osd)

    if not no_display:
        # nvegltransform is REQUIRED on Tegra / Jetson Nano between nvdsosd and nveglglessink
        transform = Gst.ElementFactory.make('nvegltransform', 'nvegl_transform')
        sink = _make(Gst, 'nveglglessink', 'sink')
        sink.set_property('sync', 0)
        if transform:
            pipeline.add(transform)
    else:
        transform = None
        sink = _make(Gst, 'fakesink', 'sink')
        sink.set_property('sync', 0)

    pipeline.add(pgie)
    pipeline.add(tracker)
    pipeline.add(sink)

    # Link the rest of the pipeline: streammux -> pgie -> tracker -> nvvidconv_osd -> osd
    streammux.link(pgie)
    pgie.link(tracker)
    tracker.link(nvvidconv_osd)
    nvvidconv_osd.link(osd)

    live_stream_enabled = os.getenv("LIVE_STREAM_ENABLED", "1").lower() in ("1", "true", "yes")
    print("[GSTREAMER BUILDER] Live stream config: enabled=%s, backend=%s" % (
        live_stream_enabled, os.getenv("BACKEND_URL", "http://localhost:8000")
    ))

    if live_stream_enabled:
        def _safe_int_env(key, default):
            try:
                raw = str(os.getenv(key, str(default))).split("#")[0].strip().strip("\"'")
                return int(raw)
            except Exception:
                return default

        mediamtx_host = str(os.getenv("MEDIAMTX_HOST", "localhost")).split("#")[0].strip().strip("\"'")
        mediamtx_rtsp_port = _safe_int_env("MEDIAMTX_RTSP_PORT", 8554)
        edge_id = str(os.getenv("EDGE_ID", "edge-01")).split("#")[0].strip().strip("\"'")

        # Tự động trỏ sang host của BACKEND_URL nếu MEDIAMTX_HOST đang để localhost mà BACKEND_URL là IP LAN (Fix Jetson -> PC)
        backend_url = str(os.getenv("BACKEND_URL", "")).split("#")[0].strip().strip("\"'")
        if mediamtx_host in ("localhost", "127.0.0.1", "") and backend_url:
            try:
                try:
                    from urllib.parse import urlparse
                except ImportError:
                    from urlparse import urlparse
                b_parsed = urlparse(backend_url)
                if b_parsed.hostname and b_parsed.hostname not in ("localhost", "127.0.0.1"):
                    print("[GSTREAMER BUILDER] Auto-detected MediaMTX host from BACKEND_URL: %s" % b_parsed.hostname)
                    mediamtx_host = b_parsed.hostname
            except Exception:
                pass

        if "LIVE_RTSP_URL" in os.environ:
            live_rtsp_url = str(os.getenv("LIVE_RTSP_URL")).split("#")[0].strip().strip("\"'")
        else:
            live_rtsp_url = "rtsp://%s:%d/live/%s" % (mediamtx_host, mediamtx_rtsp_port, edge_id)

        # An toàn tuyệt đối: Kiểm tra cổng máy chủ MediaMTX trước khi gắn rtspclientsink
        # Tránh lỗi sập pipeline: gst-resource-error-quark: Could not open resource for reading and writing. (7)
        def _check_rtsp_reachable(host, port, timeout=0.8):
            import socket
            try:
                s = socket.create_connection((host, int(port)), timeout=timeout)
                s.close()
                return True
            except Exception:
                return False

        if not _check_rtsp_reachable(mediamtx_host, mediamtx_rtsp_port):
            print(
                "[GSTREAMER BUILDER] [CẢNH BÁO] Không kết nối được máy chủ MediaMTX tại %s:%d. "
                "Tự động bỏ qua nhánh Live Stream để tránh lỗi 'gst-resource-error-quark (7)'. "
                "Pipeline AI chính (YOLO + Analytics + Telemetry) sẽ chạy độc lập an toàn!"
                % (mediamtx_host, mediamtx_rtsp_port)
            )
            live_stream_enabled = False

    if live_stream_enabled:
        live_width = _safe_int_env("LIVE_WIDTH", 640)
        live_height = _safe_int_env("LIVE_HEIGHT", 360)
        live_fps = _safe_int_env("LIVE_FPS", 15)
        live_bitrate = _safe_int_env("LIVE_BITRATE", 1500000)
        live_idle_timeout = _safe_int_env("LIVE_IDLE_TIMEOUT_S", 60)  # Default: 60s On-Demand (Fix V1)
        live_continuous = os.getenv("LIVE_CONTINUOUS_MODE", "0").lower() in ("1", "true", "yes")

        tee = _make(Gst, 'tee', 'live_tee')
        pipeline.add(tee)

        # Branch 1: Main display / fakesink (analytics/preview branch)
        queue_disp = _make(Gst, 'queue', 'queue_disp')
        pipeline.add(queue_disp)

        # Branch 2: MediaMTX H.264 Hardware Streaming
        # queue_live: leaky=2 (downstream - drop newest buffer if congested)
        queue_live = _make(Gst, 'queue', 'queue_live')
        queue_live.set_property('leaky', 2)
        queue_live.set_property('max-size-buffers', 2)
        queue_live.set_property('max-size-time', 0)
        queue_live.set_property('max-size-bytes', 0)

        # valve: On-Demand mặc định đóng (drop=True), chỉ mở khi có client yêu cầu xem (Fix V1)
        initial_live_drop = False if (live_continuous and live_idle_timeout <= 0) else True
        live_valve = _make(Gst, 'valve', 'live_valve')
        live_valve.set_property('drop', initial_live_drop)

        conv_live = _make(Gst, 'nvvideoconvert', 'conv_live')
        caps_live = _make(Gst, 'capsfilter', 'caps_live')
        caps_live.set_property('caps', Gst.Caps.from_string(
            'video/x-raw(memory:NVMM), format=I420, width=%d, height=%d' % (live_width, live_height)
        ))

        # Hardware H.264 encoding via NVENC (0% CPU overhead)
        enc_live = _make(Gst, 'nvv4l2h264enc', 'enc_live')
        try:
            enc_live.set_property('bitrate', live_bitrate)
            enc_live.set_property('profile', 0)  # 0: Baseline profile (no B-frames)
            enc_live.set_property('insert-sps-pps', 1)
            enc_live.set_property('idrinterval', live_fps)
            enc_live.set_property('iframeinterval', live_fps)
        except Exception as _enc_err:
            print('[GSTREAMER BUILDER] Warning configuring nvv4l2h264enc properties: %s' % _enc_err)

        parse_live = _make(Gst, 'h264parse', 'parse_live')
        sink_live = _make(Gst, 'rtspclientsink', 'sink_live')
        sink_live.set_property('location', live_rtsp_url)
        try:
            sink_live.set_property('protocols', 4)  # TCP transport
        except Exception:
            pass

        pipeline.add(queue_live)
        pipeline.add(live_valve)
        pipeline.add(conv_live)
        pipeline.add(caps_live)
        pipeline.add(enc_live)
        pipeline.add(parse_live)
        pipeline.add(sink_live)

        # Link Branch 1
        osd.link(tee)
        tee.link(queue_disp)
        if transform:
            queue_disp.link(transform)
            transform.link(sink)
        else:
            queue_disp.link(sink)

        # Link Branch 2
        tee.link(queue_live)
        queue_live.link(live_valve)
        live_valve.link(conv_live)
        conv_live.link(caps_live)
        caps_live.link(enc_live)
        enc_live.link(parse_live)
        parse_live.link(sink_live)

        # Initialize LiveStreamController
        try:
            from core.live_stream import LiveStreamController, set_global_controller
            live_controller = LiveStreamController(
                valve=live_valve,
                encoder=enc_live,
                sink=sink_live,
                idle_timeout_s=live_idle_timeout,
                rtsp_url=live_rtsp_url,
                continuous_mode=live_continuous
            )
            set_global_controller(live_controller)
            pipeline.live_controller = live_controller
            print('[GSTREAMER BUILDER] LiveStreamController integrated: on_demand=%s, initial_valve_drop=%s, target=%s' %
                  (not live_continuous, initial_live_drop, live_rtsp_url))
        except Exception as _ctrl_err:
            print('[GSTREAMER BUILDER] LiveStreamController initialization warning: %s' % _ctrl_err)

    else:
        if transform:
            osd.link(transform)
            transform.link(sink)
        else:
            osd.link(sink)

    return pipeline, tracker, streammux, mux_sink, osd


def _make(Gst, element_type, name):
    elem = Gst.ElementFactory.make(element_type, name)
    if not elem:
        factory = Gst.ElementFactory.find(element_type)
        if factory is None:
            raise RuntimeError(
                'Cannot create GStreamer element: %s (plugin not found or blacklisted in ~/.cache/gstreamer-1.0). '
                'Please run "xhost +" on Jetson host.' % element_type
            )
        raise RuntimeError('Cannot create GStreamer element: %s (factory found but instantiation failed)' % element_type)
    return elem
