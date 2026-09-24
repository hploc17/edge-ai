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
    if not no_display:
        nvvidconv_osd = _make(Gst, 'nvvideoconvert', 'nvvidconv_osd')
        osd = _make(Gst, 'nvdsosd', 'osd')
        # nvegltransform is REQUIRED on Tegra / Jetson Nano between nvdsosd and nveglglessink
        transform = Gst.ElementFactory.make('nvegltransform', 'nvegl_transform')
        sink = _make(Gst, 'nveglglessink', 'sink')
        sink.set_property('sync', 0)
        pipeline.add(nvvidconv_osd)
        pipeline.add(osd)
        if transform:
            pipeline.add(transform)
    else:
        nvvidconv_osd = None
        osd = None
        transform = None
        sink = _make(Gst, 'fakesink', 'sink')
        sink.set_property('sync', 0)

    pipeline.add(pgie)
    pipeline.add(tracker)
    pipeline.add(sink)

    # Link the rest of the pipeline: streammux -> pgie -> tracker -> osd -> transform -> sink
    streammux.link(pgie)
    pgie.link(tracker)
    if osd:
        tracker.link(nvvidconv_osd)
        nvvidconv_osd.link(osd)
        if transform:
            osd.link(transform)
            transform.link(sink)
        else:
            osd.link(sink)
    else:
        tracker.link(sink)

    return pipeline, tracker, streammux, mux_sink, osd


def _make(Gst, element_type, name):
    elem = Gst.ElementFactory.make(element_type, name)
    if not elem:
        raise RuntimeError('Cannot create GStreamer element: %s' % element_type)
    return elem
