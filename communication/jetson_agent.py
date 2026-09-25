#!/usr/bin/env python3
"""Jetson Agent: tiến trình nền thường trực quản lý vòng đời pipeline phân tích.

Kiến trúc 2 tầng:
  - Agent (file này): chạy vĩnh viễn, kết nối MQTT, nhận lệnh WebGIS
  - Pipeline Worker (main.py): tiến trình con, Agent kích hoạt qua subprocess.Popen

Nguyên tắc bảo mật:
  - Zero Inbound: Jetson chỉ chủ động kết nối ra ngoài (MQTT TLS, HTTP POST)
  - Whitelist cứng: chỉ 10 lệnh được phép trong command_router.py
  - Tham số video: chỉ tên file, không nhận đường dẫn tùy ý

Chống rò rỉ VRAM (Jetson Nano 4GB shared):
  - Dừng pipeline bằng SIGINT để GStreamer gửi EOS và cleanup VRAM TensorRT
  - Chỉ dùng SIGKILL làm phương án cuối cùng

Chống xung đột Camera CSI:
  - Nếu pipeline đang chạy: capture_preview dùng snapshot từ pipeline hiện tại
  - Nếu pipeline đang dừng: capture_preview gọi grab_one_frame() + release ngay

Compatible với Python 3.6 (JetPack 4.x).
"""

from __future__ import print_function

import json
import os
import signal
import subprocess
import sys
import threading
import time

# Đường dẫn gốc của project (thư mục chứa main.py)
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Thư mục video cố định - KHÔNG cho phép đường dẫn tùy ý từ bên ngoài
VIDEO_DIR = os.path.join(SCRIPT_DIR, 'Video')
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.h264', '.avi', '.264')

# Thư mục configs
CONFIGS_DIR = os.path.join(SCRIPT_DIR, 'configs')
REMOTE_ROI_CONFIG = os.path.join(CONFIGS_DIR, 'roi_config.remote.json')
LOCAL_ROI_CONFIG = os.path.join(CONFIGS_DIR, 'roi_config.local.json')

# Timeout cho graceful shutdown (giây)
GRACEFUL_STOP_TIMEOUT_SEC = 5.0
SIGTERM_TIMEOUT_SEC = 2.0

# IPC: file flag để báo cho pipeline worker cần chụp snapshot
SNAPSHOT_TRIGGER_FILE = os.path.join(SCRIPT_DIR, '.snapshot_trigger')


def _log(msg):
    print('[AGENT] %s' % msg)
    sys.stdout.flush()


# ── Giải phóng tài nguyên VRAM an toàn ────────────────────────────────────────

def graceful_stop_pipeline(process):
    """Dừng pipeline worker một cách an toàn, giải phóng VRAM TensorRT.

    Quy trình:
      1. Gửi SIGINT (tương đương Ctrl+C) - GStreamer gửi EOS, cleanup pad/VRAM
      2. Chờ tối đa 5 giây
      3. Nếu chưa thoát: gửi SIGTERM, chờ thêm 2 giây
      4. Cuối cùng: SIGKILL (bắt buộc kill, có thể rò rỉ VRAM nhỏ)
    """
    if process is None or process.poll() is not None:
        return  # đã thoát hoặc chưa bao giờ chạy

    pid = process.pid
    _log('Graceful stop pipeline PID=%d ...' % pid)

    # Bước 1: SIGINT -> GStreamer EOS cleanup
    try:
        process.send_signal(signal.SIGINT)
    except (OSError, ProcessLookupError):
        return  # tiến trình đã chết

    try:
        process.wait(timeout=GRACEFUL_STOP_TIMEOUT_SEC)
        _log('Pipeline PID=%d exited cleanly after SIGINT.' % pid)
        return
    except subprocess.TimeoutExpired:
        pass

    # Bước 2: SIGTERM
    _log('Pipeline PID=%d did not exit, sending SIGTERM ...' % pid)
    try:
        process.terminate()
    except (OSError, ProcessLookupError):
        return

    try:
        process.wait(timeout=SIGTERM_TIMEOUT_SEC)
        _log('Pipeline PID=%d exited after SIGTERM.' % pid)
        return
    except subprocess.TimeoutExpired:
        pass

    # Bước 3: SIGKILL (last resort)
    _log('Force-killing pipeline PID=%d with SIGKILL.' % pid)
    try:
        process.kill()
        process.wait()
    except (OSError, ProcessLookupError):
        pass
    _log('Pipeline PID=%d killed.' % pid)


# ── Kiểm tra tên video hợp lệ (phòng path traversal) ─────────────────────────

def _validate_video_filename(filename):
    """Trả về đường dẫn tuyệt đối hợp lệ hoặc None nếu không an toàn.

    Chỉ cho phép tên file, không nhận:
      - Đường dẫn tương đối (../ hay ../../)
      - Đường dẫn tuyệt đối bắt đầu bằng /
      - Tên file có ký tự đặc biệt nguy hiểm
    """
    if not filename:
        return None
    # Chỉ lấy phần tên file (loại bỏ mọi thành phần path)
    basename = os.path.basename(filename)
    if basename != filename:
        return None  # filename có chứa separator -> path traversal
    # Phải có extension hợp lệ
    if not any(basename.lower().endswith(ext) for ext in VIDEO_EXTENSIONS):
        return None
    full_path = os.path.join(VIDEO_DIR, basename)
    if not os.path.isfile(full_path):
        return None
    return full_path


# ── Các Handler lệnh ──────────────────────────────────────────────────────────

def make_list_videos_handler():
    """Liệt kê video trong thư mục cố định VIDEO_DIR."""
    def handler(data):
        if not os.path.isdir(VIDEO_DIR):
            return []
        files = [
            f for f in os.listdir(VIDEO_DIR)
            if any(f.lower().endswith(ext) for ext in VIDEO_EXTENSIONS)
        ]
        files.sort()
        _log('list_videos: found %d files' % len(files))
        return files
    return handler


def make_capture_preview_handler(agent_state, upload_preview_fn):
    """Chụp 1 frame để người dùng WebGIS vẽ ROI.

    Xử lý xung đột CSI:
      - Pipeline đang chạy: đánh dấu trigger, chờ pipeline worker chụp
      - Pipeline đang dừng: gọi grab_one_frame() trực tiếp
    """
    def handler(data):
        params = data.get('params', {})
        source_type = params.get('source_type', 'file')
        source = params.get('source', '')
        request_id = params.get('request_id') or data.get('request_id') or data.get('command_id', '')

        # Nếu source là tên file video, kiểm tra whitelist
        if source_type == 'file':
            validated = _validate_video_filename(source)
            if validated is None:
                raise ValueError('Invalid or non-existent video file: %s' % source)
            source = validated

        # Trường hợp pipeline đang chạy: không được mở camera thêm lần nữa
        if agent_state.get('pipeline_process') is not None and \
                agent_state['pipeline_process'].poll() is None:
            _log('capture_preview: pipeline running, triggering internal snapshot')
            # Ghi file trigger để pipeline worker tự chụp
            try:
                with open(SNAPSHOT_TRIGGER_FILE, 'w') as f:
                    json.dump({'request_id': request_id, 'purpose': 'roi_setup'}, f)
                # Chờ tối đa 8 giây để pipeline chụp và upload
                for _ in range(80):
                    time.sleep(0.1)
                    if not os.path.exists(SNAPSHOT_TRIGGER_FILE):
                        break
                return 'Preview frame captured from running pipeline'
            except Exception as err:
                raise RuntimeError('Failed to trigger pipeline snapshot: %s' % err)
        else:
            # Pipeline không chạy: dùng grab_one_frame() trực tiếp
            _log('capture_preview: pipeline idle, using grab_one_frame()')
            try:
                # Import ở đây để tránh import circular và giữ Python 3.6 compat
                sys.path.insert(0, os.path.join(SCRIPT_DIR, 'tools'))
                from roi_picker import grab_one_frame
                frame = grab_one_frame(source_type, source)
                # Camera đã được release bên trong grab_one_frame()
            except Exception as err:
                raise RuntimeError('grab_one_frame failed: %s' % err)

            # Upload preview frame
            ok, msg = upload_preview_fn(frame, request_id)
            if not ok:
                raise RuntimeError('Upload failed: %s' % msg)
            return 'Preview frame uploaded successfully'

    return handler


def make_set_roi_remote_handler():
    """Lưu cấu hình ROI từ xa vào configs/roi_config.remote.json.

    Kiểm tra tọa độ Normalized [0.0, 1.0] trước khi lưu.
    """
    def handler(data):
        params = data.get('params', {})
        detection_roi = params.get('detection_roi', [])
        analysis_roi = params.get('analysis_roi', [])
        road_width_m = float(params.get('road_width_m', 7.0))
        road_length_m = float(params.get('road_length_m', 20.0))
        lane_count = int(params.get('lane_count', 2))

        # Kiểm tra dữ liệu đầu vào
        if len(detection_roi) < 3:
            raise ValueError('detection_roi needs at least 3 points')
        if len(analysis_roi) < 3:
            raise ValueError('analysis_roi needs at least 3 points')

        # Kiểm tra tọa độ Normalized [0.0, 1.0]
        for roi_name, roi_points in [('detection_roi', detection_roi), ('analysis_roi', analysis_roi)]:
            for pt in roi_points:
                if len(pt) != 2:
                    raise ValueError('%s: each point must be [x, y]' % roi_name)
                x, y = float(pt[0]), float(pt[1])
                if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                    raise ValueError('%s: coordinates must be normalized [0.0, 1.0], got [%s, %s]' % (roi_name, x, y))

        config = {
            'frame_width': 1280,
            'frame_height': 720,
            'detection_roi': [[float(p[0]), float(p[1])] for p in detection_roi],
            'analysis_roi': [[float(p[0]), float(p[1])] for p in analysis_roi],
            'calibration_image_points': [[float(p[0]), float(p[1])] for p in analysis_roi],
            'road_width_m': road_width_m,
            'road_length_m': road_length_m,
            'lane_count': lane_count,
        }

        os.makedirs(CONFIGS_DIR, exist_ok=True)
        with open(REMOTE_ROI_CONFIG, 'w') as f:
            json.dump(config, f, indent=2)

        _log('set_roi_remote: saved to %s' % REMOTE_ROI_CONFIG)
        return 'Remote ROI saved successfully'

    return handler


def make_start_pipeline_handler(agent_state):
    """Khởi động pipeline worker subprocess.

    Luôn dừng pipeline cũ trước (graceful) nếu đang chạy.
    Chỉ chạy 1 pipeline tại 1 thời điểm.
    """
    def handler(data):
        params = data.get('params', {})
        source_type = params.get('source_type', 'file')
        source = params.get('source', '')
        roi_config_type = params.get('roi_config', 'local')  # "local" | "remote"
        display = bool(params.get('display', False))

        # Validate source
        if source_type == 'file':
            validated = _validate_video_filename(source)
            if validated is None:
                raise ValueError('Invalid or non-existent video file: %s' % source)
            source = validated

        # Chọn file config ROI
        if roi_config_type == 'remote':
            if not os.path.isfile(REMOTE_ROI_CONFIG):
                raise RuntimeError('Remote ROI config not found. Run set_roi_remote first.')
            roi_config_path = REMOTE_ROI_CONFIG
        else:
            if not os.path.isfile(LOCAL_ROI_CONFIG):
                raise RuntimeError('Local ROI config not found at %s' % LOCAL_ROI_CONFIG)
            roi_config_path = LOCAL_ROI_CONFIG

        # Dừng pipeline cũ trước
        old_proc = agent_state.get('pipeline_process')
        if old_proc is not None and old_proc.poll() is None:
            _log('start_pipeline: stopping previous pipeline PID=%d' % old_proc.pid)
            graceful_stop_pipeline(old_proc)
            time.sleep(1.0)  # Chờ tài nguyên GPU được giải phóng hoàn toàn

        # Dựng command line
        cmd = [
            sys.executable,
            os.path.join(SCRIPT_DIR, 'main.py'),
            '--source-type', source_type,
            '--source', source,
            '--roi-config', roi_config_path,
        ]
        if not display:
            cmd.append('--no-display')

        _log('start_pipeline: %s' % ' '.join(cmd))

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=SCRIPT_DIR,
        )

        agent_state['pipeline_process'] = proc
        agent_state['pipeline_started_at'] = time.time()
        _log('start_pipeline: started PID=%d' % proc.pid)

        return {'pid': proc.pid, 'state': 'running', 'roi_config': roi_config_type, 'display': display}

    return handler


def make_stop_pipeline_handler(agent_state):
    """Dừng pipeline worker một cách an toàn."""
    def handler(data):
        proc = agent_state.get('pipeline_process')
        if proc is None or proc.poll() is not None:
            return 'No pipeline is currently running'
        graceful_stop_pipeline(proc)
        agent_state['pipeline_process'] = None
        return 'Pipeline stopped successfully'
    return handler


def make_capture_snapshot_handler(agent_state):
    """Kích hoạt chụp ảnh thủ công từ pipeline đang chạy."""
    def handler(data):
        params = data.get('params', {})
        reason = params.get('reason', 'manual')

        proc = agent_state.get('pipeline_process')
        if proc is None or proc.poll() is not None:
            raise RuntimeError('No pipeline is running to capture snapshot')

        # Ghi trigger file cho pipeline worker
        try:
            with open(SNAPSHOT_TRIGGER_FILE, 'w') as f:
                json.dump({'purpose': 'manual', 'reason': reason}, f)
            return 'Snapshot enqueued'
        except Exception as err:
            raise RuntimeError('Failed to trigger snapshot: %s' % err)

    return handler


def make_request_status_handler(agent_state):
    """Báo cáo trạng thái pipeline hiện tại."""
    def handler(data):
        proc = agent_state.get('pipeline_process')
        if proc is None:
            return {'pipeline_running': False, 'pid': None}
        retcode = proc.poll()
        if retcode is None:
            uptime = time.time() - agent_state.get('pipeline_started_at', time.time())
            return {'pipeline_running': True, 'pid': proc.pid, 'uptime_sec': int(uptime)}
        else:
            return {'pipeline_running': False, 'pid': None, 'last_exit_code': retcode}
    return handler


# ── Upload helper cho capture_preview ────────────────────────────────────────

def make_upload_preview_fn(backend_url, edge_id, edge_token):
    """Trả về hàm upload frame preview lên backend qua HTTP POST.

    Tuân thủ thiết kế:
      - purpose = "roi_setup"
      - Không đưa vào offline_outbox nếu thất bại
      - Trả về (ok: bool, msg: str)
    """
    import uuid
    try:
        import urllib.request as _req
        import urllib.error as _err
        _HAS_URLLIB = True
    except ImportError:
        _HAS_URLLIB = False

    try:
        import cv2
        _HAS_CV2 = True
    except ImportError:
        _HAS_CV2 = False

    def upload(frame, request_id):
        if not _HAS_CV2:
            return False, 'cv2 not available'
        if not _HAS_URLLIB:
            return False, 'urllib not available'

        # Encode JPEG
        ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            return False, 'JPEG encode failed'
        jpeg_bytes = buf.tobytes()

        url = '%s/api/edge/%s/capture' % (backend_url.rstrip('/'), edge_id)
        boundary = 'PreviewBoundary' + uuid.uuid4().hex
        parts = []

        def _add_field(name, value):
            parts.append(('--' + boundary + '\r\n').encode('utf-8'))
            parts.append(('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode('utf-8'))
            parts.append(str(value).encode('utf-8'))
            parts.append(b'\r\n')

        _add_field('purpose', 'roi_setup')
        _add_field('request_id', request_id)
        _add_field('timestamp', time.strftime('%Y-%m-%dT%H:%M:%S+07:00'))

        # File part
        parts.append(('--' + boundary + '\r\n').encode('utf-8'))
        parts.append(('Content-Disposition: form-data; name="file"; filename="preview_%s.jpg"\r\n'
                      'Content-Type: image/jpeg\r\n\r\n' % request_id).encode('utf-8'))
        parts.append(jpeg_bytes)
        parts.append(b'\r\n')
        parts.append(('--' + boundary + '--\r\n').encode('utf-8'))

        body = b''.join(parts)
        headers = {
            'Content-Type': 'multipart/form-data; boundary=' + boundary,
            'Content-Length': str(len(body)),
            'X-Edge-Token': edge_token,
        }

        try:
            req = _req.Request(url, data=body, headers=headers, method='POST')
            with _req.urlopen(req, timeout=15) as resp:
                success = resp.status in (200, 201)
                return success, 'HTTP %d' % resp.status
        except Exception as e:
            return False, str(e)

    return upload


def _load_env_file(path, override=True):
    """Đọc file .env đơn giản, tương thích Python 3.6 không cần thư viện ngoài."""
    if not os.path.isfile(path):
        return False
    try:
        # Python 2/3 compatibility for open
        try:
            f = open(path, 'r', encoding='utf-8')
        except TypeError:
            f = open(path, 'r')
        with f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip('"\'')
                    if override or key not in os.environ:
                        os.environ[key] = val
        return True
    except Exception as e:
        _log('Warning: could not read .env at %s: %s' % (path, e))
        return False


# ── Entry point: khởi động Jetson Agent ──────────────────────────────────────

def run_agent():
    """Vòng lặp chính của Jetson Agent.

    Tải cấu hình từ environment variables, kết nối MQTT,
    đăng ký tất cả handler lệnh và chạy vòng lặp vô hạn.
    """
    # Nạp môi trường: Ưu tiên số 1 là file .env ở thư mục gốc project
    root_env_path = os.path.join(SCRIPT_DIR, '.env')
    if _load_env_file(root_env_path, override=True):
        _log('Loaded environment from: %s' % root_env_path)

    # Nạp bổ sung từ snap/.env nếu có biến chưa được đặt
    snap_env_path = os.path.join(SCRIPT_DIR, 'snap', '.env')
    if os.path.isfile(snap_env_path):
        _load_env_file(snap_env_path, override=False)

    edge_id = os.getenv('EDGE_ID', 'edge-01')
    backend_url = os.getenv('BACKEND_URL', 'http://192.168.1.10:8000')
    edge_token = os.getenv('EDGE_TOKEN', 'dev-edge-token')

    _log('Starting Jetson Agent for edge_id=%s' % edge_id)
    _log('Configured Backend URL: %s' % backend_url)
    _log('Configured MQTT Host: %s:%s' % (os.getenv('MQTT_HOST', 'hivemq'), os.getenv('MQTT_PORT', '8883')))


    # Import MQTT publisher
    sys.path.insert(0, SCRIPT_DIR)
    from communication.mqtt_client import MQTTPublisher, HeartbeatThread
    from communication.command_router import CommandHandler
    try:
        from communication.system_metrics import collect_comprehensive_health
    except (ImportError, AttributeError):
        try:
            from system_metrics import collect_comprehensive_health
        except (ImportError, AttributeError):
            def collect_comprehensive_health():
                return {'general': {'service_status': 'running', 'fallback': True}}


    # Trạng thái dùng chung giữa các handler (thay dict thay cho global)
    agent_state = {
        'pipeline_process': None,
        'pipeline_started_at': None,
    }

    # Upload helper
    upload_preview_fn = make_upload_preview_fn(backend_url, edge_id, edge_token)

    # Khởi tạo CommandHandler trước, sau đó pass vào publisher
    cmd_handler = None

    publisher = MQTTPublisher(command_callback=lambda data: cmd_handler.handle(data) if cmd_handler else None)
    cmd_handler = CommandHandler(publisher)

    # Đăng ký tất cả handler
    cmd_handler.register('list_videos', make_list_videos_handler())
    cmd_handler.register('capture_preview', make_capture_preview_handler(agent_state, upload_preview_fn))
    cmd_handler.register('set_roi_remote', make_set_roi_remote_handler())
    cmd_handler.register('start_pipeline', make_start_pipeline_handler(agent_state))
    cmd_handler.register('stop_pipeline', make_stop_pipeline_handler(agent_state))
    cmd_handler.register('capture_snapshot', make_capture_snapshot_handler(agent_state))
    cmd_handler.register('request_status', make_request_status_handler(agent_state))
    cmd_handler.register('get_health', lambda data: collect_comprehensive_health())
    # Legacy aliases
    cmd_handler.register('restart_analytics', make_stop_pipeline_handler(agent_state))
    cmd_handler.register('reload_config', lambda data: 'Config reload queued (restart pipeline to apply)')
    cmd_handler.register('start_video_test', make_start_pipeline_handler(agent_state))

    # Kết nối MQTT
    publisher.start()
    heartbeat = HeartbeatThread(publisher)
    heartbeat.start()

    _log('Agent is running. Waiting for commands via MQTT...')
    _log('Listening on topic: traffic/%s/command' % edge_id)

    # Vòng lặp chính: giám sát pipeline process và dọn dẹp zombie
    try:
        while True:
            time.sleep(5.0)
            proc = agent_state.get('pipeline_process')
            if proc is not None:
                retcode = proc.poll()
                if retcode is not None:
                    _log('Pipeline PID=%d exited with code=%d' % (proc.pid, retcode))
                    agent_state['pipeline_process'] = None
                    agent_state['pipeline_started_at'] = None
    except KeyboardInterrupt:
        _log('Agent shutting down...')
    finally:
        # Dừng pipeline nếu đang chạy
        proc = agent_state.get('pipeline_process')
        if proc is not None and proc.poll() is None:
            _log('Stopping pipeline on agent shutdown...')
            graceful_stop_pipeline(proc)
        heartbeat.stop()
        publisher.stop()
        _log('Agent stopped.')


if __name__ == '__main__':
    run_agent()
