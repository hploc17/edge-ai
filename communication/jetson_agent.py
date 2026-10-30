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
import uuid

# Đường dẫn gốc của project (thư mục chứa main.py)
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import numpy as np
except ImportError:
    np = None

# Thư mục video - hỗ trợ nhiều tên thông dụng
VIDEO_DIR = os.path.join(SCRIPT_DIR, 'Video')
VIDEO_DIRS = [
    os.path.join(SCRIPT_DIR, 'Video'),
    os.path.join(SCRIPT_DIR, 'video'),
    os.path.join(SCRIPT_DIR, 'videos'),
    os.path.join(SCRIPT_DIR, 'data'),
]
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.h264', '.avi', '.264')

# Thư mục configs
CONFIGS_DIR = os.path.join(SCRIPT_DIR, 'configs')
REMOTE_ROI_CONFIG = os.path.join(CONFIGS_DIR, 'roi_config.remote.json')
LOCAL_ROI_CONFIG = os.path.join(CONFIGS_DIR, 'roi_traffic_nano.json')

# Timeout cho graceful shutdown (giây)
GRACEFUL_STOP_TIMEOUT_SEC = 5.0
SIGTERM_TIMEOUT_SEC = 2.0

# IPC: file flag để báo cho pipeline worker cần chụp snapshot / preview (Fix V3)
SNAPSHOT_TRIGGER_FILE = os.path.join(SCRIPT_DIR, '.snapshot_trigger')
PREVIEW_TRIGGER_FILE = os.path.join(SCRIPT_DIR, '.preview_trigger')
LATEST_PREVIEW_FILE = os.path.join(SCRIPT_DIR, '.latest_preview.jpg')


def _request_preview_from_running_pipeline(request_id, timeout_sec=2.0):
    """Yêu cầu pipeline đang chạy trích xuất 1 frame mà KHÔNG mở lại camera CSI (Fix V3)."""
    if os.path.exists(LATEST_PREVIEW_FILE):
        try:
            os.remove(LATEST_PREVIEW_FILE)
        except Exception:
            pass

    try:
        with open(PREVIEW_TRIGGER_FILE, 'w') as f:
            json.dump({'request_id': request_id, 'timestamp': time.time()}, f)
    except Exception as e:
        _log('Warning: could not write PREVIEW_TRIGGER_FILE: %s' % e)

    deadline = time.time() + float(timeout_sec)
    while time.time() < deadline:
        if os.path.exists(LATEST_PREVIEW_FILE) and os.path.getsize(LATEST_PREVIEW_FILE) > 1000:
            try:
                with open(LATEST_PREVIEW_FILE, 'rb') as f:
                    data = f.read()
                _log('Successfully captured preview frame (%d bytes) from active pipeline' % len(data))
                return data
            except Exception as read_err:
                _log('Notice reading preview file: %s' % read_err)
        time.sleep(0.05)

    if os.path.exists(PREVIEW_TRIGGER_FILE):
        try:
            os.remove(PREVIEW_TRIGGER_FILE)
        except Exception:
            pass

    _log('[WARN] Timeout waiting for preview frame from pipeline worker. Falling back to canvas frame.')
    return None


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

def _find_available_videos():
    """Tìm tất cả các file video hợp lệ trong các thư mục video của dự án."""
    found = []
    seen = set()
    for vdir in VIDEO_DIRS:
        if os.path.isdir(vdir):
            for f in os.listdir(vdir):
                if any(f.lower().endswith(ext) for ext in VIDEO_EXTENSIONS) and f not in seen:
                    full_p = os.path.join(vdir, f)
                    if os.path.isfile(full_p):
                        found.append((f, full_p))
                        seen.add(f)
    found.sort(key=lambda x: x[0])
    return found


def _validate_video_filename(filename):
    """Trả về đường dẫn tuyệt đối hợp lệ đến file video hoặc None.

    Hỗ trợ:
      - Tên file trực tiếp: 'traffic.mp4'
      - Đường dẫn tương đối an toàn: 'Video/traffic.mp4'
      - Nếu filename rỗng: tự động chọn file video đầu tiên tìm thấy
    """
    if not filename:
        vids = _find_available_videos()
        if vids:
            _log('No video filename specified, auto-selected: %s' % vids[0][0])
            return vids[0][1]
        return None

    cleaned = str(filename).replace('\\', '/').strip()
    basename = os.path.basename(cleaned)

    # 1. Tìm trong các thư mục video chuẩn
    for vdir in VIDEO_DIRS:
        candidate = os.path.join(vdir, basename)
        if os.path.isfile(candidate):
            return candidate

    # 2. Kiểm tra đường dẫn trực tiếp nếu an toàn (nằm trong SCRIPT_DIR)
    direct_path = os.path.abspath(os.path.join(SCRIPT_DIR, cleaned))
    if direct_path.startswith(os.path.abspath(SCRIPT_DIR)) and os.path.isfile(direct_path):
        return direct_path

    # 3. Fallback: Nếu không tìm thấy file cụ thể nhưng có video khác, dùng video đầu tiên
    vids = _find_available_videos()
    if vids:
        _log('Video %s not found on disk, fallback to: %s' % (basename, vids[0][0]))
        return vids[0][1]

    return None


# ── Các Handler lệnh ──────────────────────────────────────────────────────────

def make_list_videos_handler():
    """Liệt kê video trong các thư mục video của hệ thống."""
    def handler(data):
        vids = _find_available_videos()
        files = [v[0] for v in vids]
        _log('list_videos: found %d files' % len(files))
        return files
    return handler


def make_capture_preview_handler(agent_state, upload_preview_fn):
    """Chụp 1 frame để người dùng WebGIS vẽ ROI.

    Đảm bảo chụp frame thật từ Camera CSI hoặc File video.
    Fix V4: Fail-fast nếu camera bị rút hoặc lỗi phần cứng, không trả canvas giả mạo thành công.
    Chỉ cho phép synthetic canvas khi người dùng bật tường minh allow_synthetic=True (cho dev/test).
    """
    def handler(data):
        params = data.get('params', {})
        source_type = str(params.get('source_type', 'file')).strip().lower()
        source = params.get('source', '')
        allow_synthetic = bool(params.get('allow_synthetic', False))
        request_id = params.get('request_id') or data.get('request_id') or data.get('command_id', '')
        if not request_id:
            request_id = 'prev-%s' % uuid.uuid4().hex[:8]

        _log('capture_preview requested: source_type=%s, source=%s, req_id=%s, allow_synthetic=%s' % (source_type, source, request_id, allow_synthetic))

        target_payload = None
        is_synthetic = False

        proc = agent_state.get('pipeline_process')
        is_pipeline_running = proc is not None and proc.poll() is None

        # 1. Nguồn CSI Camera:
        if source_type == 'csi':
            if is_pipeline_running:
                # Fix V3: Pipeline đang giữ camera CSI -> Lấy frame từ pipeline worker, KHÔNG mở CSI trực tiếp!
                _log('capture_preview: pipeline is actively running, requesting frame from active pipeline...')
                target_payload = _request_preview_from_running_pipeline(request_id)
            else:
                # Pipeline đang dừng -> An toàn mở camera CSI trực tiếp
                sensor_id = int(os.getenv('SENSOR_ID', os.getenv('CSI_SENSOR_ID', '0')))
                _log('capture_preview: pipeline idle, capturing direct hardware CSI (sensor %d)...' % sensor_id)
                raw_jpeg = capture_direct_csi_jpeg(sensor_id=sensor_id, width=1280, height=720, quality=85)
                if not raw_jpeg and sensor_id == 0:
                    raw_jpeg = capture_direct_csi_jpeg(sensor_id=1, width=1280, height=720, quality=85)
                if raw_jpeg:
                    _log('capture_preview: captured %d bytes directly from CSI' % len(raw_jpeg))
                    target_payload = raw_jpeg

        # 2. Nguồn File Video: Tìm đường dẫn video thực tế
        elif source_type == 'file':
            validated_path = _validate_video_filename(source)
            if validated_path:
                source = validated_path
            else:
                _log('[WARN] No video file available for source=%s' % source)

        # 3. Nếu chưa có frame từ CSI trực tiếp, trích xuất qua grab_one_frame
        # Lưu ý: nếu pipeline đang chạy trên CSI, KHÔNG gọi grab_one_frame('csi') để tránh Argus resource busy (Fix V3)
        if target_payload is None:
            if source_type == 'csi' and is_pipeline_running:
                _log('[WARN] Pipeline is holding CSI sensor; skipping grab_one_frame(csi) to avoid Argus resource busy.')
            else:
                try:
                    sys.path.insert(0, os.path.join(SCRIPT_DIR, 'tools'))
                    from roi_picker import grab_one_frame
                    frame = grab_one_frame(source_type, source)
                    if frame is not None:
                        target_payload = frame
                except Exception as err:
                    _log('[WARN] grab_one_frame failed (%s)' % err)

        # 4. Xử lý trường hợp không lấy được frame thật (Fix V4)
        if target_payload is None:
            if allow_synthetic:
                try:
                    sys.path.insert(0, os.path.join(SCRIPT_DIR, 'tools'))
                    from roi_picker import _create_fallback_frame
                    target_payload = _create_fallback_frame(1280, 720)
                    is_synthetic = True
                    _log('capture_preview: explicitly permitted synthetic canvas fallback 1280x720')
                except Exception as err2:
                    _log('[ERROR] Failed to create synthetic fallback frame: %s' % err2)
            else:
                if source_type == 'csi':
                    raise RuntimeError('Camera CSI không phản hồi hoặc đã bị ngắt kết nối. Vui lòng kiểm tra cáp phần cứng.')
                else:
                    raise RuntimeError('Không thể trích xuất khung hình từ nguồn video "%s". File không hợp lệ hoặc không tồn tại.' % source)

        if target_payload is None:
            raise RuntimeError('Could not acquire preview frame')

        # 5. Tải ảnh preview lên Backend WebGIS qua HTTP POST
        try:
            ok, msg = upload_preview_fn(target_payload, request_id, is_synthetic=is_synthetic)
        except TypeError:
            ok, msg = upload_preview_fn(target_payload, request_id)

        if not ok:
            raise RuntimeError('Upload failed: %s' % msg)

        _log('capture_preview: upload success (request_id=%s, synthetic=%s)' % (request_id, is_synthetic))
        if is_synthetic:
            return 'Warning: Synthetic preview frame generated (no hardware camera)'
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
        traffic_context = str(params.get('traffic_context', 'signalized')).lower().strip()
        if traffic_context not in ('signalized', 'midblock'):
            traffic_context = 'signalized'

        # Kiểm tra dữ liệu đầu vào: detection_roi >= 3, analysis_roi == 4 (cho Homography Perspective)
        if len(detection_roi) < 3:
            raise ValueError('detection_roi needs at least 3 points')
        if len(analysis_roi) != 4:
            raise ValueError('analysis_roi requires exactly 4 ordered points')

        # Kiểm tra tọa độ Normalized [0.0, 1.0]
        for roi_name, roi_points in [('detection_roi', detection_roi), ('analysis_roi', analysis_roi)]:
            for pt in roi_points:
                if len(pt) != 2:
                    raise ValueError('%s: each point must be [x, y]' % roi_name)
                x, y = float(pt[0]), float(pt[1])
                if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                    raise ValueError('%s: coordinates must be normalized [0.0, 1.0], got [%s, %s]' % (roi_name, x, y))

        # R2: Kiểm tra thứ tự 4 điểm P1-P4 và tỉ lệ phối cảnh mặt đường
        try:
            from analytics.speed_estimator import PerspectiveCalibration
            PerspectiveCalibration.validate_aspect_ratio_and_order(analysis_roi, road_width_m, road_length_m)
        except (ImportError, AttributeError):
            pass

        config = {
            'frame_width': 1280,
            'frame_height': 720,
            'detection_roi': [[float(p[0]), float(p[1])] for p in detection_roi],
            'analysis_roi': [[float(p[0]), float(p[1])] for p in analysis_roi],
            'calibration_image_points': [[float(p[0]), float(p[1])] for p in analysis_roi],
            'road_width_m': road_width_m,
            'road_length_m': road_length_m,
            'lane_count': lane_count,
            'traffic_context': traffic_context,
        }

        os.makedirs(CONFIGS_DIR, exist_ok=True)
        with open(REMOTE_ROI_CONFIG, 'w') as f:
            json.dump(config, f, indent=2)

        _log('set_roi_remote: saved to %s' % REMOTE_ROI_CONFIG)
        return 'Remote ROI saved successfully'

    return handler


def make_start_pipeline_handler(agent_state):
    """Khởi động pipeline worker subprocess an toàn (Chống race condition L3).

    - Sử dụng pipeline_lock để tuần tự hóa toàn bộ thao tác bật/tắt.
    - Idempotent: Nếu pipeline đang chạy và cùng tham số (source, roi_config_path, display),
      bỏ qua việc restart trùng lặp và trả về tiến trình hiện tại.
    """
    def handler(data):
        lock = agent_state.setdefault('pipeline_lock', threading.RLock())
        with lock:
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
            elif source_type == 'csi':
                source = 'csi'

            # Tìm file config ROI khả dụng (ưu tiên traffic_nano)
            default_local = None
            candidates = [
                LOCAL_ROI_CONFIG,
                os.path.join(CONFIGS_DIR, 'roi_traffic_nano.json'),
                os.path.join(CONFIGS_DIR, 'roi_nano.json'),
            ]
            for c in candidates:
                if os.path.isfile(c):
                    default_local = c
                    break

            if roi_config_type == 'remote':
                if os.path.isfile(REMOTE_ROI_CONFIG):
                    roi_config_path = REMOTE_ROI_CONFIG
                elif default_local:
                    roi_config_path = default_local
                else:
                    raise RuntimeError('Remote ROI config not found. Run set_roi_remote first.')
            else:
                if default_local:
                    roi_config_path = default_local
                else:
                    raise RuntimeError('Local ROI config not found in %s' % CONFIGS_DIR)

            # Idempotency check: Nếu pipeline hiện tại vẫn đang chạy và cùng cấu hình, không start đè
            curr_proc = agent_state.get('pipeline_process')
            roi_mtime = os.path.getmtime(roi_config_path) if os.path.isfile(roi_config_path) else 0.0
            if curr_proc is not None and curr_proc.poll() is None:
                last_cmd = agent_state.get('pipeline_current_cmd')
                requested_key = (source, roi_config_path, roi_mtime, display)
                if last_cmd == requested_key:
                    _log('start_pipeline: already running with identical config PID=%d (idempotent no-op)' % curr_proc.pid)
                    return {
                        'pid': curr_proc.pid,
                        'state': 'running',
                        'roi_config': roi_config_type,
                        'display': display,
                        'message': 'Pipeline is already running with identical config'
                    }

                # Nếu khác cấu hình hoặc người dùng muốn đổi nguồn: Dừng pipeline cũ trước
                _log('start_pipeline: stopping previous pipeline PID=%d to reconfigure' % curr_proc.pid)
                graceful_stop_pipeline(curr_proc)
                agent_state['pipeline_process'] = None
                log_f = agent_state.pop('pipeline_log_file', None)
                if log_f:
                    try:
                        log_f.close()
                    except Exception:
                        pass
                time.sleep(1.0)  # Chờ tài nguyên CSI sensor và GPU VRAM được giải phóng hoàn toàn

            # Dựng command line: tự động nhận diện main3.py nếu có, ngược lại dùng main.py
            worker_script = 'main3.py' if os.path.exists(os.path.join(SCRIPT_DIR, 'main3.py')) else 'main.py'
            cmd = [
                sys.executable,
                os.path.join(SCRIPT_DIR, worker_script),
                '--source', source or 'csi',
                '--roi-config', roi_config_path,
            ]
            if not display:
                cmd.append('--no-display')

            _log('start_pipeline: %s' % ' '.join(cmd))

            env = os.environ.copy()
            if not env.get('DISPLAY'):
                env['DISPLAY'] = ':0'

            log_file_path = os.path.join(SCRIPT_DIR, 'pipeline.log')
            log_f = open(log_file_path, 'a', encoding='utf-8')
            proc = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                cwd=SCRIPT_DIR,
                env=env,
            )

            agent_state['pipeline_process'] = proc
            agent_state['pipeline_log_file'] = log_f
            agent_state['pipeline_started_at'] = time.time()
            agent_state['pipeline_current_cmd'] = (source, roi_config_path, roi_mtime, display)
            agent_state['intentional_stop'] = False
            agent_state['last_start_data'] = data
            _log('start_pipeline: started PID=%d (logging to %s)' % (proc.pid, log_file_path))

            return {'pid': proc.pid, 'state': 'running', 'roi_config': roi_config_type, 'display': display}

    return handler


def make_reload_config_handler(agent_state):
    """Thực hiện reload cấu hình ROI và calibration đáng tin cậy (Fix R3).

    Nếu pipeline đang chạy: khởi động lại pipeline (Graceful Restart) với file cấu hình mới nhất
    để giải phóng CUDA context cũ và nạp ma trận Homography mới hoàn toàn sạch sẽ, tránh race condition.
    """
    def handler(data):
        lock = agent_state.setdefault('pipeline_lock', threading.RLock())
        with lock:
            proc = agent_state.get('pipeline_process')
            is_running = proc is not None and proc.poll() is None
            if not is_running:
                return 'Config updated. Pipeline is not currently running; changes will apply on next start.'

            _log('reload_config: pipeline is running (PID=%d), restarting with latest config...' % proc.pid)
            last_cmd = agent_state.get('pipeline_current_cmd')
            source = last_cmd[0] if last_cmd else 'csi'
            display = last_cmd[3] if last_cmd and len(last_cmd) > 3 else False

            # Buộc restart bằng cách xóa key cache
            agent_state['pipeline_current_cmd'] = None

            start_fn = make_start_pipeline_handler(agent_state)
            res = start_fn({
                'command_id': data.get('command_id', 'reload-%s' % uuid.uuid4().hex[:6]),
                'params': {
                    'source_type': 'csi' if source == 'csi' else 'file',
                    'source': source,
                    'roi_config': 'remote' if os.path.isfile(REMOTE_ROI_CONFIG) else 'local',
                    'display': display
                }
            })
            new_pid = res.get('pid') if isinstance(res, dict) else '?'
            return 'Pipeline successfully restarted with new configuration (new PID: %s)' % new_pid
    return handler


def make_stop_pipeline_handler(agent_state):
    """Dừng pipeline worker một cách an toàn (Sử dụng pipeline_lock)."""
    def handler(data):
        lock = agent_state.setdefault('pipeline_lock', threading.RLock())
        with lock:
            agent_state['intentional_stop'] = True
            agent_state['crash_retry_count'] = 0
            agent_state['last_start_data'] = None
            proc = agent_state.get('pipeline_process')
            stopped_any = False
            if proc is not None and proc.poll() is None:
                graceful_stop_pipeline(proc)
                stopped_any = True

            # Quét và dọn sạch bất kỳ tiến trình main.py nào còn sót lại trên OS Linux (kể cả bật ngoài)
            if sys.platform.startswith('linux'):
                try:
                    out = subprocess.check_output(['pgrep', '-f', 'python3.*main.py'], stderr=subprocess.DEVNULL)
                    for line in out.decode('utf-8', errors='ignore').splitlines():
                        p_str = line.strip()
                        if p_str and int(p_str) != os.getpid():
                            try:
                                os.kill(int(p_str), signal.SIGTERM)
                                stopped_any = True
                            except Exception:
                                pass
                except Exception:
                    pass

                # Giải phóng cảm biến camera CSI ngay lập tức để camera tắt đèn và sẵn sàng chụp preview
                try:
                    subprocess.run(['sudo', 'systemctl', 'restart', 'nvargus-daemon'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
                except Exception:
                    pass

            agent_state['pipeline_process'] = None
            agent_state['pipeline_started_at'] = None
            agent_state['pipeline_current_cmd'] = None
            log_f = agent_state.pop('pipeline_log_file', None)
            if log_f:
                try:
                    log_f.close()
                except Exception:
                    pass

            if not stopped_any:
                return 'No pipeline was running (camera sensor released)'
            return 'Pipeline stopped successfully'
    return handler


def make_restart_pipeline_handler(agent_state):
    """Khởi động lại pipeline: Dừng an toàn pipeline cũ và khởi động lại với cấu hình gần nhất (Fix L6)."""
    def handler(data):
        lock = agent_state.setdefault('pipeline_lock', threading.RLock())
        with lock:
            last_data = agent_state.get('last_start_data') or data
            _log('restart_analytics requested. Gracefully stopping previous pipeline...')
            stop_fn = make_stop_pipeline_handler(agent_state)
            stop_fn(data)
            time.sleep(1.5)  # Chờ giải phóng VRAM TensorRT và cảm biến CSI
            agent_state['intentional_stop'] = False
            _log('restart_analytics: starting new pipeline instance...')
            start_fn = make_start_pipeline_handler(agent_state)
            return start_fn(last_data)
    return handler


def capture_direct_csi_jpeg(sensor_id=0, width=1280, height=720, quality=80):
    """Trích xuất 1 frame JPEG thực tế trực tiếp từ Camera CSI (nvarguscamerasrc) trên Jetson Nano.
    
    Phương pháp:
      1. Thử dùng GStreamer CLI (gst-launch-1.0) chụp trực tiếp frame JPEG từ phần cứng nvarguscamerasrc
      2. Nếu không thành công, dùng OpenCV VideoCapture với GStreamer pipeline
    """
    import tempfile
    # Cách 1: GStreamer nvarguscamerasrc + jpegenc (tiêu chuẩn JetPack trên Jetson Nano)
    try:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
            tmp_path = tmp_file.name

        argv = [
            "gst-launch-1.0", "-e", "-q",
            "nvarguscamerasrc", "sensor-id=%d" % sensor_id, "num-buffers=4", "!",
            "video/x-raw(memory:NVMM),width=%d,height=%d,framerate=30/1,format=NV12" % (width, height), "!",
            "nvvidconv", "!",
            "video/x-raw,format=I420", "!",
            "jpegenc", "quality=%d" % quality, "!",
            "filesink", "location=" + tmp_path
        ]
        res = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
        if res.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 1000:
            with open(tmp_path, 'rb') as f:
                data = f.read()
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            _log('capture_direct_csi_jpeg: Captured %d bytes via gst-launch-1.0' % len(data))
            return data
    except Exception as e:
        _log('Direct gst-launch CSI capture failed: %s' % e)

    # Tự động giải phóng nvargus-daemon nếu phiên camera trước đó chưa nhả cảm biến
    try:
        subprocess.run(['sudo', 'systemctl', 'restart', 'nvargus-daemon'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
        time.sleep(1.0)
        res = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
        if res.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 1000:
            with open(tmp_path, 'rb') as f:
                data = f.read()
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            _log('capture_direct_csi_jpeg: Captured %d bytes via gst-launch after daemon restart' % len(data))
            return data
    except Exception:
        pass

    # Cách 2: OpenCV GStreamer pipeline
    try:
        gst_str = (
            "nvarguscamerasrc sensor-id=%d ! "
            "video/x-raw(memory:NVMM),width=%d,height=%d,framerate=30/1,format=NV12 ! "
            "nvvidconv ! video/x-raw,format=BGRx ! videoconvert ! "
            "video/x-raw,format=BGR ! appsink drop=true max-buffers=1"
        ) % (sensor_id, width, height)
        import cv2
        cap = cv2.VideoCapture(gst_str, cv2.CAP_GSTREAMER)
        if cap and cap.isOpened():
            frame = None
            import time
            for _ in range(12):
                ret, tmp = cap.read()
                if ret and tmp is not None and tmp.size > 0:
                    frame = tmp
                    if tmp.mean() > 1.0:
                        break
                time.sleep(0.08)
            cap.release()
            if frame is not None:
                ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
                if ok:
                    _log('capture_direct_csi_jpeg: Captured %d bytes via OpenCV GStreamer' % len(buf))
                    return buf.tobytes()
    except Exception as e2:
        _log('OpenCV CSI capture failed: %s' % e2)

    return None


def make_capture_snapshot_handler(agent_state, backend_url, edge_id, edge_token):
    """Kích hoạt chụp ảnh theo yêu cầu (WebGIS -> Jetson qua action capture_test_snapshot).
    
    Hỗ trợ 2 chế độ:
      - Pipeline đang chạy: ghi file flag SNAPSHOT_TRIGGER_FILE để pipeline worker chụp frame
      - Pipeline đang dừng: tự động gọi capture_direct_csi_jpeg() từ Camera CSI và upload multipart lên Backend
    """
    def handler(data):
        params = data.get('params', {})
        reason = params.get('reason', 'manual_on_demand')
        command_id = data.get('command_id', str(uuid.uuid4()))

        proc = agent_state.get('pipeline_process')
        if proc is not None and proc.poll() is None:
            # Ghi trigger file cho pipeline worker
            _log('capture_snapshot: pipeline running, queueing trigger to worker')
            try:
                with open(SNAPSHOT_TRIGGER_FILE, 'w') as f:
                    json.dump({'purpose': 'manual', 'reason': reason, 'command_id': command_id}, f)
                return 'Snapshot request queued to active pipeline'
            except Exception as err:
                raise RuntimeError('Failed to trigger snapshot: %s' % err)
        else:
            # Pipeline đang dừng: Trực tiếp dùng Camera CSI để chụp ảnh
            _log('capture_snapshot: pipeline idle, capturing live frame from CSI camera')
            try:
                sensor_id = int(os.getenv('SENSOR_ID', os.getenv('CSI_SENSOR_ID', '0')))
                
                # Ưu tiên số 1: Luôn chụp trực tiếp từ Camera CSI của Jetson Nano
                jpeg_bytes = capture_direct_csi_jpeg(sensor_id=sensor_id, width=1280, height=720, quality=80)
                
                # Fallback nếu CSI hoàn toàn không có (ví dụ môi trường test không gắn camera CSI)
                if not jpeg_bytes:
                    _log('CSI camera not available, falling back to video/sample frame')
                    sys.path.insert(0, os.path.join(SCRIPT_DIR, 'tools'))
                    from roi_picker import grab_one_frame
                    video_files = [f for f in os.listdir(VIDEO_DIR) if f.endswith(VIDEO_EXTENSIONS)] if os.path.exists(VIDEO_DIR) else []
                    source = os.path.join(VIDEO_DIR, video_files[0]) if video_files else ''
                    frame = grab_one_frame('file', source)
                    import cv2
                    ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                    if not ok:
                        raise RuntimeError('JPEG encode failed')
                    jpeg_bytes = buf.tobytes()

                # Upload multipart lên Backend
                url = '%s/api/v1/congestion-events/snapshot' % backend_url.rstrip('/')
                boundary = 'SnapshotBoundary' + uuid.uuid4().hex
                parts = []
                def _add_field(name, value):
                    parts.append(('--' + boundary + '\r\n').encode('utf-8'))
                    parts.append(('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode('utf-8'))
                    parts.append(str(value).encode('utf-8'))
                    parts.append(b'\r\n')

                _add_field('edge_id', edge_id)
                _add_field('camera_id', os.getenv('CAMERA_ID', 'camera-01'))
                _add_field('segment_id', os.getenv('SEGMENT_ID', 'segment-001'))
                _add_field('traffic_status', 'FREE')
                _add_field('trigger_reason', reason)
                _add_field('command_id', command_id)
                _add_field('timestamp', time.strftime('%Y-%m-%dT%H:%M:%S+07:00'))

                # File part (chấp nhận image/file)
                parts.append(('--' + boundary + '\r\n').encode('utf-8'))
                parts.append(('Content-Disposition: form-data; name="image"; filename="snapshot_%s.jpg"\r\n'
                              'Content-Type: image/jpeg\r\n\r\n' % command_id[:8]).encode('utf-8'))
                parts.append(jpeg_bytes)
                parts.append(b'\r\n')
                parts.append(('--' + boundary + '--\r\n').encode('utf-8'))

                body = b''.join(parts)
                headers = {
                    'Content-Type': 'multipart/form-data; boundary=' + boundary,
                    'Content-Length': str(len(body)),
                    'Authorization': 'Bearer ' + edge_token,
                }
                import urllib.request as _req
                req = _req.Request(url, data=body, headers=headers, method='POST')
                with _req.urlopen(req, timeout=12) as resp:
                    if resp.status in (200, 201):
                        return 'Snapshot captured and uploaded successfully (HTTP %d)' % resp.status
                    else:
                        raise RuntimeError('Upload returned HTTP %d' % resp.status)
            except Exception as err:
                raise RuntimeError('Direct snapshot capture failed: %s' % err)

    return handler


def make_request_status_handler(agent_state):
    """Báo cáo trạng thái pipeline hiện tại (hỗ trợ cả tiến trình con và tiến trình chạy ngoài trên OS)."""
    def handler(data=None):
        # 1. Kiểm tra tiến trình con được quản lý bởi agent
        proc = agent_state.get('pipeline_process')
        if proc is not None and proc.poll() is None:
            uptime = time.time() - agent_state.get('pipeline_started_at', time.time())
            return {'pipeline_running': True, 'pid': proc.pid, 'uptime_sec': int(uptime)}

        # 2. Quét tiến trình main.py trên OS (trong trường hợp người dùng chạy từ terminal hoặc systemd)
        try:
            import psutil
            for p in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
                try:
                    cmdline = p.info.get('cmdline') or []
                    cmd_str = ' '.join(cmdline)
                    if ('main.py' in cmd_str or 'main3.py' in cmd_str) and 'jetson_agent.py' not in cmd_str:
                        uptime = time.time() - p.info.get('create_time', time.time())
                        return {'pipeline_running': True, 'pid': p.info['pid'], 'uptime_sec': int(max(0, uptime))}
                except Exception:
                    pass
        except Exception:
            pass

        # 3. Fallback pgrep nếu psutil không có quyền đọc cmdline
        try:
            out = subprocess.check_output(['pgrep', '-f', 'python3.*main.py'], stderr=subprocess.DEVNULL)
            pids = [int(x) for x in out.decode().strip().split() if x.isdigit()]
            if pids:
                return {'pipeline_running': True, 'pid': pids[0], 'uptime_sec': 30}
        except Exception:
            pass

        return {'pipeline_running': False, 'pid': None}
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

    def upload(frame_or_jpeg, request_id, is_synthetic=False):
        if not _HAS_URLLIB:
            return False, 'urllib not available'

        # Nếu đã là JPEG bytes trực tiếp (từ CSI hoặc pipeline)
        if isinstance(frame_or_jpeg, (bytes, bytearray)):
            jpeg_bytes = bytes(frame_or_jpeg)
        else:
            if not _HAS_CV2:
                return False, 'cv2 not available'
            if frame_or_jpeg is None:
                return False, 'frame is None'
            # Encode JPEG
            ok, buf = cv2.imencode('.jpg', frame_or_jpeg, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
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
        _add_field('is_synthetic', 'true' if is_synthetic else 'false')
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
                status_code = getattr(resp, 'status', None)
                if status_code is None and hasattr(resp, 'getcode'):
                    status_code = resp.getcode()
                success = status_code in (200, 201)
                return success, 'HTTP %s' % status_code
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
                line = line.strip().rstrip('\r\n')
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip('"\'').rstrip('\r')
                    if key in ('MQTT_PORT', 'PORT', 'SENSOR_ID'):
                        import re
                        m = re.search(r'\d+', val)
                        if m:
                            val = m.group(0)
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
    # Nạp duy nhất từ file .env tại thư mục gốc của project
    root_env_path = os.path.join(SCRIPT_DIR, '.env')
    if _load_env_file(root_env_path, override=True):
        _log('Loaded single master environment from: %s' % root_env_path)

    edge_id = os.getenv('EDGE_ID', 'edge-01')
    backend_url = os.getenv('BACKEND_URL', 'http://localhost:8000')
    edge_token = os.getenv('EDGE_TOKEN', 'dev-edge-token')
    agent_client_id = os.getenv('MQTT_AGENT_CLIENT_ID', '%s-agent' % edge_id)

    _log('Starting Jetson Agent for edge_id=%s (client_id=%s)' % (edge_id, agent_client_id))
    _log('Configured Backend URL: %s' % backend_url)
    _log('Configured MQTT Host: %s:%s' % (os.getenv('MQTT_HOST', 'hivemq'), os.getenv('MQTT_PORT', '8883')))

    # Import MQTT publisher
    sys.path.insert(0, SCRIPT_DIR)
    from communication.mqtt_client import MQTTPublisher, HeartbeatThread
    from communication.command_router import CommandHandler
    try:
        from communication.system_metrics import collect_comprehensive_health, collect_spatial_info, _get_mac_address
    except (ImportError, AttributeError):
        try:
            from system_metrics import collect_comprehensive_health, collect_spatial_info, _get_mac_address
        except (ImportError, AttributeError):
            def collect_comprehensive_health():
                return {'general': {'service_status': 'running', 'fallback': True}}
            def collect_spatial_info():
                return {'edge_id': edge_id, 'mac_address': '00:00:00:00:00:00'}
            def _get_mac_address():
                return '00:00:00:00:00:00'

    # Trạng thái dùng chung giữa các handler (thay dict thay cho global)
    agent_state = {
        'pipeline_process': None,
        'pipeline_started_at': None,
        'pipeline_lock': threading.RLock(),
        'pipeline_current_cmd': None,
        'last_start_data': None,
        'intentional_stop': False,
        'crash_retry_count': 0,
    }

    # Upload helper
    upload_preview_fn = make_upload_preview_fn(backend_url, edge_id, edge_token)

    # Khởi tạo CommandHandler trước, sau đó pass vào publisher với client_id riêng biệt (chống lỗi rc=7)
    cmd_handler = None

    publisher = MQTTPublisher(
        command_callback=lambda data: cmd_handler.handle(data) if cmd_handler else None,
        client_id=agent_client_id
    )
    cmd_handler = CommandHandler(publisher)

    # Đăng ký tất cả handler
    cmd_handler.register('list_videos', make_list_videos_handler())
    cmd_handler.register('capture_preview', make_capture_preview_handler(agent_state, upload_preview_fn))
    cmd_handler.register('set_roi_remote', make_set_roi_remote_handler())
    cmd_handler.register('start_pipeline', make_start_pipeline_handler(agent_state))
    cmd_handler.register('stop_pipeline', make_stop_pipeline_handler(agent_state))
    cmd_handler.register('start_csi', make_start_pipeline_handler(agent_state))
    cmd_handler.register('capture_snapshot', lambda data: 'Manual snapshot disabled: Snapshots are automatically captured as evidence on CONGESTED traffic events')
    cmd_handler.register('capture_test_snapshot', lambda data: 'Manual snapshot disabled: Snapshots are automatically captured as evidence on CONGESTED traffic events')
    cmd_handler.register('request_status', make_request_status_handler(agent_state))
    cmd_handler.register('get_health', lambda data: collect_comprehensive_health())
    cmd_handler.register('get_spatial_info', lambda data: collect_spatial_info())
    # Legacy aliases
    cmd_handler.register('restart_analytics', make_restart_pipeline_handler(agent_state))
    cmd_handler.register('restart_pipeline', make_restart_pipeline_handler(agent_state))
    cmd_handler.register('reload_config', make_reload_config_handler(agent_state))
    cmd_handler.register('start_video_test', make_start_pipeline_handler(agent_state))

    # Gói Live Streaming: MediaMTX On-Demand
    try:
        from core.live_stream import register_live_handlers
        register_live_handlers(cmd_handler)
    except Exception as _live_reg_err:
        _log('Live stream handler registration notice: %s' % _live_reg_err)

    # Tùy chọn độc lập: Bật kênh Chẩn đoán & Kéo Log từ xa (Remote Maintenance)
    try:
        from communication.remote_maintenance import register_maintenance_handler
        register_maintenance_handler(cmd_handler, agent_state)
    except Exception as _m_err:
        _log('Remote maintenance plugin skipped: %s' % _m_err)


    # Thiết lập hồ sơ thiết bị để WebGIS tự động nhận diện (Auto-discovery) và vẽ Node trên bản đồ
    lat = float(os.getenv('NODE_LAT', os.getenv('GEO_LAT', 10.852708)))
    lng = float(os.getenv('NODE_LON', os.getenv('GEO_LNG', 106.660508)))
    road_name = os.getenv('ROAD_NAME', 'Đường Lê Đức Thọ')
    segment_id = os.getenv('SEGMENT_ID', 'segment-001')
    heading = float(os.getenv('CAMERA_HEADING', 45.0))
    fov = float(os.getenv('CAMERA_FOV', 65.0))

    registration_profile = {
        'event': 'device_registered',
        'edge_id': edge_id,
        'mac_address': _get_mac_address(),
        'name': os.getenv('NODE_NAME', 'Camera AI Jetson (%s)' % edge_id),
        'device_name': os.getenv('NODE_NAME', 'Camera AI Jetson (%s)' % edge_id),
        'camera_id': os.getenv('CAMERA_ID', 'camera-01'),
        'segment_id': segment_id,
        'road_name': road_name,
        'latitude': lat,
        'longitude': lng,
        'geo': {
            'lat': lat,
            'lng': lng,
            'altitude_m': float(os.getenv('NODE_ALTITUDE_M', os.getenv('GEO_ALTITUDE_M', 12.0))),
            'segment_id': segment_id,
            'road_name': road_name,
            'heading': heading,
            'fov': fov,
        },
        'camera_heading': heading,
        'camera_fov': fov,
        'status': 'online',
        'pipeline_running': False,
        'pipeline_pid': None,
        'model_version': os.getenv('MODEL_VERSION', 'exp.engine'),
        'timestamp': time.strftime("%Y-%m-%dT%H:%M:%S+07:00")
    }
    publisher.set_registration_profile(registration_profile)

    def query_live_pipeline_status():
        proc = agent_state.get('pipeline_process')
        if proc is None:
            return {'pipeline_running': False, 'pid': None}
        retcode = proc.poll()
        if retcode is None:
            return {'pipeline_running': True, 'pid': proc.pid}
        return {'pipeline_running': False, 'pid': None}

    publisher.set_pipeline_status_callback(query_live_pipeline_status)

    # Kết nối MQTT
    publisher.start()
    publisher.publish_registration()
    heartbeat = HeartbeatThread(publisher)
    heartbeat.start()

    # Tự động kích hoạt pipeline worker nếu được cấu hình (Mặc định: false để điều khiển từ WebGIS)
    auto_start = os.getenv('AUTO_START_PIPELINE', 'false').lower() in ('true', '1', 'yes')
    if auto_start:
        _log('AUTO_START_PIPELINE is enabled. Launching pipeline worker...')
        try:
            start_fn = make_start_pipeline_handler(agent_state)
            default_source = os.getenv('ANALYTICS_SOURCE', 'file')
            start_fn({'params': {'source_type': default_source}})
        except Exception as _start_err:
            _log('[WARN] Failed to auto-start pipeline: %s' % _start_err)

    _log('Agent is running. Waiting for commands via MQTT...')
    _log('Listening on topic: traffic/%s/command' % edge_id)

    MAX_CRASH_RETRIES = int(os.getenv('WATCHDOG_MAX_RETRIES', '3'))
    BACKOFF_DELAYS = [2.0, 5.0, 10.0]

    # Vòng lặp chính: giám sát pipeline process và watchdog tự phục hồi (Fix L6)
    try:
        while True:
            time.sleep(1.0)
            proc = agent_state.get('pipeline_process')

            # Nếu pipeline đang chạy ổn định > 60s, reset bộ đếm crash về 0
            if proc is not None and proc.poll() is None:
                started_at = agent_state.get('pipeline_started_at')
                if started_at and (time.time() - started_at > 60.0) and agent_state.get('crash_retry_count', 0) > 0:
                    agent_state['crash_retry_count'] = 0
                    _log('[WATCHDOG] Pipeline running stably for >60s. Reset crash counter.')

            if proc is not None:
                retcode = proc.poll()
                if retcode is not None:
                    _log('Pipeline PID=%d finished/exited with code=%d' % (proc.pid, retcode))
                    lock = agent_state.get('pipeline_lock')
                    with lock:
                        agent_state['pipeline_process'] = None
                        agent_state['pipeline_started_at'] = None
                        agent_state['pipeline_current_cmd'] = None
                        log_f = agent_state.pop('pipeline_log_file', None)
                        if log_f:
                            try:
                                log_f.close()
                            except Exception:
                                pass

                    intentional = agent_state.get('intentional_stop', False)
                    last_data = agent_state.get('last_start_data')
                    source_type = (last_data or {}).get('params', {}).get('source_type', 'file')

                    # 1. Người dùng chủ động dừng trên WebGIS hoặc không có dữ liệu khởi động -> Không restart
                    if intentional or not last_data:
                        _log('Pipeline stopped intentionally by user or idle. Watchdog idle.')
                        continue

                    # 2. File video chạy hết tự nhiên (EOS: retcode == 0) -> Không restart, báo Web
                    if retcode == 0 and source_type == 'file':
                        _log('Video playback finished normally (EOS).')
                        try:
                            publisher.publish_command_result(
                                command_id='auto-stop',
                                action='stop_pipeline',
                                status='completed',
                                message='Video playback finished (code 0). Display window closed.'
                            )
                        except Exception as e:
                            _log('Failed to notify auto-stop via MQTT: %s' % e)
                        continue

                    # 3. Crash bất thường (retcode != 0 hoặc CSI camera bị ngắt) -> Watchdog kích hoạt
                    retry_count = agent_state.get('crash_retry_count', 0)
                    if retry_count < MAX_CRASH_RETRIES:
                        agent_state['crash_retry_count'] = retry_count + 1
                        delay = BACKOFF_DELAYS[min(retry_count, len(BACKOFF_DELAYS) - 1)]
                        _log('[WATCHDOG] ⚠️ Pipeline crashed with code %d! Auto-recovering attempt %d/%d in %.1fs...' %
                             (retcode, retry_count + 1, MAX_CRASH_RETRIES, delay))

                        try:
                            publisher.publish_command_result(
                                command_id='watchdog-%d' % int(time.time()),
                                action='pipeline_watchdog',
                                status='restarting',
                                message='Pipeline crashed (code %d). Auto-recovering attempt %d/%d in %.1fs' %
                                        (retcode, retry_count + 1, MAX_CRASH_RETRIES, delay)
                            )
                        except Exception:
                            pass

                        time.sleep(delay)
                        try:
                            start_fn = make_start_pipeline_handler(agent_state)
                            restart_res = start_fn(last_data or {'params': {'source_type': source_type}})
                            _log('[WATCHDOG] ✅ Pipeline recovered successfully PID=%s' % restart_res.get('pid'))
                        except Exception as rec_err:
                            _log('[WATCHDOG] ❌ Recovery attempt failed: %s' % rec_err)
                    else:
                        _log('[WATCHDOG] 🛑 Max crash retries (%d) reached. Pipeline marked failed.' % MAX_CRASH_RETRIES)
                        try:
                            publisher.publish_command_result(
                                command_id='watchdog-fatal',
                                action='stop_pipeline',
                                status='error',
                                message='Pipeline crashed repeatedly (code %d). Max recovery attempts reached.' % retcode
                            )
                        except Exception:
                            pass

    except KeyboardInterrupt:
        _log('Agent shutting down...')
    finally:
        # Dừng pipeline nếu đang chạy
        proc = agent_state.get('pipeline_process')
        if proc is not None and proc.poll() is None:
            _log('Stopping pipeline on agent shutdown...')
            graceful_stop_pipeline(proc)
        heartbeat.stop()
        publisher.stop(publish_offline=True)
        _log('Agent stopped.')


if __name__ == '__main__':
    run_agent()
