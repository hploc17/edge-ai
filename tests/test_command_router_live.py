import os
import sys
import threading
import time
import pytest
from communication.command_router import ALLOWED_ACTIONS, CommandHandler
from core.live_stream import LiveStreamController, set_global_controller, register_live_handlers


class MockPublisher(object):
    def __init__(self):
        self.results = []

    def publish_command_result(self, command_id, action, status, message=""):
        self.results.append({
            "command_id": command_id,
            "action": action,
            "status": status,
            "message": message
        })


def test_command_router_whitelist_contains_live():
    for act in ["start_live", "stop_live", "live_keepalive", "live_status"]:
        assert act in ALLOWED_ACTIONS, "Action %s must be in ALLOWED_ACTIONS" % act


def test_command_router_live_lifecycle():
    pub = MockPublisher()
    handler = CommandHandler(pub)

    # Initialize a mock LiveStreamController
    class MockValve(object):
        def __init__(self):
            self.drop = True
        def set_property(self, k, v):
            if k == "drop":
                self.drop = v

    valve = MockValve()
    ctrl = LiveStreamController(valve=valve, idle_timeout_s=10.0, rtsp_url="rtsp://localhost:8554/live/edge-01")
    set_global_controller(ctrl)
    register_live_handlers(handler)

    # 1. Test start_live
    handler.handle({
        "command_id": "test-start-1",
        "action": "start_live",
        "params": {"injected_malicious_url": "http://evil.com/stream"} # Must be ignored!
    })
    time.sleep(0.1)
    assert ctrl.state == "on"
    assert valve.drop is False

    # 2. Test live_keepalive
    handler.handle({
        "command_id": "test-keep-1",
        "action": "live_keepalive"
    })
    time.sleep(0.1)
    assert ctrl.state == "on"

    # 3. Test live_status
    handler.handle({
        "command_id": "test-stat-1",
        "action": "live_status"
    })
    time.sleep(0.1)
    assert ctrl.state == "on"

    # 4. Test stop_live
    handler.handle({
        "command_id": "test-stop-1",
        "action": "stop_live"
    })
    time.sleep(0.1)
    assert ctrl.state == "off"
    assert valve.drop is True


def test_command_router_rejects_disallowed_actions():
    pub = MockPublisher()
    handler = CommandHandler(pub)

    handler.handle({
        "command_id": "bad-1",
        "action": "system_exec_rm_rf",
        "params": {}
    })
    assert len(pub.results) == 1
    assert pub.results[0]["status"] == "rejected"
    assert "disallowed action" in pub.results[0]["message"]


def test_pipeline_concurrent_start_idempotent(monkeypatch):
    """L3: Kiểm thử gọi start_pipeline đồng thời 2 lần - Đảm bảo chỉ sinh 1 tiến trình và không bị race condition."""
    import threading
    from communication.jetson_agent import make_start_pipeline_handler, make_stop_pipeline_handler

    spawn_count = 0
    class DummyProc:
        def __init__(self, pid):
            self.pid = pid
        def poll(self):
            return None
        def wait(self, timeout=None):
            return 0

    def mock_popen(*args, **kwargs):
        nonlocal spawn_count
        spawn_count += 1
        time.sleep(0.05)
        return DummyProc(1000 + spawn_count)

    monkeypatch.setattr("subprocess.Popen", mock_popen)

    agent_state = {
        'pipeline_process': None,
        'pipeline_started_at': None,
        'pipeline_lock': threading.Lock(),
        'pipeline_current_cmd': None,
    }

    start_handler = make_start_pipeline_handler(agent_state)

    results = []
    def call_start(cmd_id):
        res = start_handler({'command_id': cmd_id, 'params': {'source_type': 'csi'}})
        results.append(res)

    t1 = threading.Thread(target=call_start, args=('cmd-1',))
    t2 = threading.Thread(target=call_start, args=('cmd-2',))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Nghiệm thu L3: dù gọi đồng thời 2 lần, spawn_count chỉ là 1, và cả 2 đều trả về cùng PID
    assert spawn_count == 1
    assert len(results) == 2
    assert results[0]['pid'] == results[1]['pid']


def test_l5_handler_error_mapping():
    """L5: Đảm bảo handler trả dict lỗi được ánh xạ chính xác thành status='error' thay vì 'completed'."""
    pub = MockPublisher()
    handler = CommandHandler(pub)

    # 1. Handler trả {'status': 'error', 'message': 'LiveStreamController not ready'}
    handler.register('start_live', lambda d: {'status': 'error', 'message': 'LiveStreamController not ready'})
    handler.handle({'action': 'start_live', 'command_id': 'cmd-err-1'})
    time.sleep(0.05)

    assert len(pub.results) == 1
    assert pub.results[0]['command_id'] == 'cmd-err-1'
    assert pub.results[0]['status'] == 'error'
    assert pub.results[0]['message'] == 'LiveStreamController not ready'

    # 2. Handler trả {'error': 'Hardware sensor busy'}
    handler.register('capture_preview', lambda d: {'error': 'Hardware sensor busy'})
    handler.handle({'action': 'capture_preview', 'command_id': 'cmd-err-2'})
    time.sleep(0.05)

    assert len(pub.results) == 2
    assert pub.results[1]['command_id'] == 'cmd-err-2'
    assert pub.results[1]['status'] == 'error'

    # 3. Handler trả kết quả thành công bình thường -> status='completed'
    handler.register('stop_live', lambda d: {'status': 'ok', 'state': 'off'})
    handler.handle({'action': 'stop_live', 'command_id': 'cmd-ok-3'})
    time.sleep(0.05)

    assert len(pub.results) == 3
    assert pub.results[2]['command_id'] == 'cmd-ok-3'
    assert pub.results[2]['status'] == 'completed'


def test_l6_restart_analytics_spawns_new_process(monkeypatch):
    """L6: Đảm bảo restart_analytics thực sự dừng tiến trình cũ và khởi động tiến trình mới (không chỉ dừng lại)."""
    import threading
    from communication.jetson_agent import (
        make_start_pipeline_handler,
        make_stop_pipeline_handler,
        make_restart_pipeline_handler,
    )

    spawn_count = 0
    class DummyProc:
        def __init__(self, pid):
            self.pid = pid
            self.stopped = False
        def poll(self):
            return 0 if self.stopped else None
        def wait(self, timeout=None):
            self.stopped = True
            return 0
        def send_signal(self, sig):
            self.stopped = True

    def mock_popen(*args, **kwargs):
        nonlocal spawn_count
        spawn_count += 1
        return DummyProc(3000 + spawn_count)

    monkeypatch.setattr("subprocess.Popen", mock_popen)
    # Rút ngắn thời gian sleep khi test
    monkeypatch.setattr("time.sleep", lambda s: None)

    agent_state = {
        'pipeline_process': None,
        'pipeline_started_at': None,
        'pipeline_lock': threading.RLock(),
        'pipeline_current_cmd': None,
        'last_start_data': None,
        'intentional_stop': False,
        'crash_retry_count': 0,
    }

    start_fn = make_start_pipeline_handler(agent_state)
    start_res = start_fn({'params': {'source_type': 'csi'}})
    assert spawn_count == 1
    assert start_res['pid'] == 3001

    # Gọi restart
    restart_fn = make_restart_pipeline_handler(agent_state)
    restart_res = restart_fn({'params': {'source_type': 'csi'}})

    # Phải sinh ra tiến trình mới (spawn_count == 2, PID mới 3002)
    assert spawn_count == 2
    assert restart_res['pid'] == 3002
    assert agent_state['pipeline_process'] is not None
    assert agent_state['pipeline_process'].pid == 3002


def test_l8_command_router_ttl_expired():
    """L8: Kiểm tra lệnh quá hạn TTL bị từ chối và phản hồi 'expired'."""
    pub = MockPublisher()
    handler = CommandHandler(pub, command_ttl=30.0)

    executed = []
    handler.register('list_videos', lambda payload: executed.append(payload))

    # 1. Gửi lệnh cũ từ 60 giây trước (quá hạn 30s)
    old_ts = time.strftime('%Y-%m-%dT%H:%M:%S+07:00', time.localtime(time.time() - 60))
    handler.handle({
        'command_id': 'cmd-expired-1',
        'action': 'list_videos',
        'timestamp': old_ts,
    })

    assert len(executed) == 0, "Handler không được thực thi khi lệnh đã hết hạn"
    assert len(pub.results) == 1
    assert pub.results[0]['command_id'] == 'cmd-expired-1'
    assert pub.results[0]['status'] == 'expired'
    assert 'expired' in pub.results[0]['message'].lower()

    # 2. Gửi lệnh hợp lệ vừa phát ra (timestamp hiện tại)
    fresh_ts = time.strftime('%Y-%m-%dT%H:%M:%S+07:00', time.localtime(time.time()))
    handler.handle({
        'command_id': 'cmd-fresh-1',
        'action': 'list_videos',
        'timestamp': fresh_ts,
    })
    time.sleep(0.05)
    assert len(executed) == 1, "Handler phải được thực thi khi lệnh còn hạn TTL"
    assert len(pub.results) == 2
    assert pub.results[1]['command_id'] == 'cmd-fresh-1'
    assert pub.results[1]['status'] == 'completed'

    # 3. Lệnh có custom ttl trong payload (ttl=5s, lệnh gửi từ 10s trước)
    custom_old_ts = time.time() - 10
    handler.handle({
        'command_id': 'cmd-custom-ttl-1',
        'action': 'list_videos',
        'timestamp': custom_old_ts,
        'ttl': 5.0,
    })
    assert len(executed) == 1
    assert len(pub.results) == 3
    assert pub.results[2]['command_id'] == 'cmd-custom-ttl-1'
    assert pub.results[2]['status'] == 'expired'


def test_l8_mqtt_publisher_offline_queue_and_flush():
    """L8: Kiểm tra MQTTPublisher lưu kết quả lệnh (QoS 1) khi offline và xả khi online lại."""
    from communication.mqtt_client import MQTTPublisher

    pub = MQTTPublisher(client_id="test-l8-pub", is_agent=True)
    published_calls = []

    # Mock client publish
    class MockClientPublishResult:
        rc = 0

    def mock_publish(topic, payload, qos=0, retain=False):
        published_calls.append((topic, payload, qos, retain))
        return MockClientPublishResult()

    pub._client.publish = mock_publish
    pub._is_connected = False  # Giả lập rớt mạng

    # 1. Telemetry (QoS 0) khi offline -> Drop, không lưu offline queue
    pub.publish_telemetry({'current_vehicle_count': 5}, {})
    assert pub.offline_queue_size == 0

    # 2. Command result (QoS 1) khi offline -> Lưu vào offline queue
    pub.publish_command_result('cmd-off-1', 'start_pipeline', 'completed', 'OK')
    assert pub.offline_queue_size == 1

    # 3. Thêm một kết quả lệnh thứ hai
    pub.publish_command_result('cmd-off-2', 'stop_pipeline', 'completed', 'Stopped')
    assert pub.offline_queue_size == 2
    assert len(published_calls) == 0

    # 4. Giả lập kết nối lại thành công (_on_connect)
    pub._on_connect(pub._client, None, None, rc=0)

    # Đảm bảo hàng đợi offline đã được xả toàn bộ
    assert pub.offline_queue_size == 0
    assert len(published_calls) >= 2
    # Hai bản tin đầu tiên sau khi xả phải là 2 command result đã queue
    topics = [call[0] for call in published_calls]
    assert any('command-result' in t for t in topics)

    pub.stop()


def test_v3_capture_preview_does_not_open_csi_when_pipeline_running(monkeypatch):
    """V3: Khi pipeline đang chạy, capture_preview không mở lại camera CSI để tránh Resource Busy."""
    from communication.jetson_agent import make_capture_preview_handler
    import communication.jetson_agent as ja

    direct_csi_calls = []
    def mock_capture_direct_csi_jpeg(**kwargs):
        direct_csi_calls.append(kwargs)
        return b"fake_direct_csi_jpeg_bytes"

    monkeypatch.setattr(ja, "capture_direct_csi_jpeg", mock_capture_direct_csi_jpeg)

    uploaded_frames = []
    def mock_upload_preview(frame_payload, request_id):
        uploaded_frames.append((frame_payload, request_id))
        return True, "OK"

    class DummyRunningProc:
        def poll(self):
            return None  # Pipeline is running!

    # 1. Pipeline ĐANG CHẠY:
    agent_state_running = {
        'pipeline_process': DummyRunningProc(),
        'pipeline_lock': None,
    }

    # Giả lập pipeline worker đang chạy: khi thấy PREVIEW_TRIGGER_FILE thì ghi LATEST_PREVIEW_FILE
    fake_frame_bytes = b"\xff\xd8\xff\xe0" + b"A" * 2000 + b"\xff\xd9"

    for f_clean in (ja.PREVIEW_TRIGGER_FILE, ja.LATEST_PREVIEW_FILE):
        if os.path.exists(f_clean):
            try:
                os.remove(f_clean)
            except Exception:
                pass

    stop_writer = threading.Event()
    def mock_pipeline_writer():
        for _ in range(200):
            if stop_writer.is_set():
                break
            if os.path.exists(ja.PREVIEW_TRIGGER_FILE):
                try:
                    with open(ja.LATEST_PREVIEW_FILE, 'wb') as f:
                        f.write(fake_frame_bytes)
                except Exception:
                    pass
                time.sleep(0.05)
                if not os.path.exists(ja.PREVIEW_TRIGGER_FILE):
                    break
            time.sleep(0.02)

    writer_thread = threading.Thread(target=mock_pipeline_writer, daemon=True)
    writer_thread.start()

    preview_handler = make_capture_preview_handler(agent_state_running, mock_upload_preview)
    res = preview_handler({
        'command_id': 'cmd-prev-1',
        'params': {'source_type': 'csi', 'request_id': 'req-v3-1'}
    })
    stop_writer.set()

    assert res == 'Preview frame uploaded successfully'
    assert len(uploaded_frames) == 1
    assert len(direct_csi_calls) == 0, "TUYỆT ĐỐI không được gọi capture_direct_csi_jpeg khi pipeline đang chạy"
    assert uploaded_frames[0][0] == fake_frame_bytes

    # 2. Pipeline ĐANG DỪNG:
    agent_state_idle = {
        'pipeline_process': None,  # Pipeline is stopped!
        'pipeline_lock': None,
    }

    preview_handler_idle = make_capture_preview_handler(agent_state_idle, mock_upload_preview)
    res_idle = preview_handler_idle({
        'command_id': 'cmd-prev-2',
        'params': {'source_type': 'csi', 'request_id': 'req-v3-2'}
    })

    assert res_idle == 'Preview frame uploaded successfully'
    assert len(direct_csi_calls) == 1, "Khi pipeline dừng, được phép mở camera CSI trực tiếp"
    assert uploaded_frames[1][0] == b"fake_direct_csi_jpeg_bytes"

    # Dọn dẹp
    if os.path.exists(ja.LATEST_PREVIEW_FILE):
        try:
            os.remove(ja.LATEST_PREVIEW_FILE)
        except Exception:
            pass


def test_v4_capture_preview_fails_when_camera_disconnected_and_synthetic_flag(monkeypatch):
    """V4: Kiểm tra khi rút camera CSI hoặc lỗi phần cứng:
    - Mặc định: fail-fast bắn lỗi thay vì upload canvas trống rồi báo 'uploaded successfully'
    - Chỉ upload synthetic khi có cờ tường minh allow_synthetic=True, gắn kèm cờ is_synthetic=True.
    """
    import communication.jetson_agent as ja
    from communication.jetson_agent import make_capture_preview_handler
    from communication.command_router import CommandHandler

    # Giả lập camera CSI bị ngắt kết nối (trả về None)
    monkeypatch.setattr(ja, 'capture_direct_csi_jpeg', lambda **kwargs: None)
    sys.path.insert(0, os.path.join(ja.SCRIPT_DIR, 'tools'))
    try:
        import roi_picker
        monkeypatch.setattr(roi_picker, 'grab_one_frame', lambda *args, **kwargs: None)
    except Exception:
        pass

    uploaded_frames = []

    def mock_upload(payload, req_id, is_synthetic=False):
        uploaded_frames.append((payload, req_id, is_synthetic))
        return True, "OK"

    agent_state_idle = {
        'pipeline_process': None,
        'pipeline_lock': None,
    }

    # 1. Mặc định (allow_synthetic=False): Rút camera CSI -> Bắn RuntimeError, không được upload canvas trống
    preview_handler = make_capture_preview_handler(agent_state_idle, mock_upload)
    
    with pytest.raises(RuntimeError) as exc_info:
        preview_handler({
            'command_id': 'cmd-v4-fail',
            'params': {'source_type': 'csi', 'request_id': 'req-v4-1'}
        })
    assert 'Camera CSI không phản hồi' in str(exc_info.value)
    assert len(uploaded_frames) == 0, "Không được upload frame giả khi rút camera mà không bật allow_synthetic"

    # Kiểm tra qua CommandHandler để đảm bảo MQTT trả về status="failed"
    pub = MockPublisher()
    cmd_handler = CommandHandler(pub)
    cmd_handler.register('capture_preview', preview_handler)

    cmd_handler.handle({
        'command_id': 'cmd-v4-mqtt-fail',
        'action': 'capture_preview',
        'params': {'source_type': 'csi'}
    })
    time.sleep(0.05)

    assert len(pub.results) == 1
    assert pub.results[0]['command_id'] == 'cmd-v4-mqtt-fail'
    assert pub.results[0]['status'] in ('error', 'failed')
    assert 'Camera CSI không phản hồi' in pub.results[0]['message']

    # 2. Bật tường minh allow_synthetic=True:
    res_synth = preview_handler({
        'command_id': 'cmd-v4-synth',
        'params': {'source_type': 'csi', 'allow_synthetic': True, 'request_id': 'req-v4-synth'}
    })
    assert 'Synthetic' in res_synth
    assert len(uploaded_frames) == 1
    assert uploaded_frames[0][1] == 'req-v4-synth'
    assert uploaded_frames[0][2] is True, "Upload phải được gắn cờ is_synthetic=True"


@pytest.mark.asyncio
async def test_r1_roi_validation_unified(monkeypatch, tmp_path):
    """Test R1: Đảm bảo luật kiểm tra ROI thống nhất tại cả Jetson Agent và Backend:
    - detection_roi: >= 3 điểm.
    - analysis_roi: bắt buộc đúng 4 điểm (Homography Perspective Calibration).
    - Từ chối ngay khi lưu, không chờ pipeline khởi động rồi crash."""
    from communication.jetson_agent import make_set_roi_remote_handler
    import communication.jetson_agent as ja_module

    # Chuyển hướng lưu config tạm sang tmp_path để tránh ghi đè file thật
    tmp_config_dir = tmp_path / "configs"
    tmp_roi_file = tmp_config_dir / "roi_config.remote.json"
    monkeypatch.setattr(ja_module, "CONFIGS_DIR", str(tmp_config_dir))
    monkeypatch.setattr(ja_module, "REMOTE_ROI_CONFIG", str(tmp_roi_file))

    agent_handler = make_set_roi_remote_handler()

    # 1. Jetson Agent: analysis_roi có 3 điểm -> phải bị từ chối
    with pytest.raises(ValueError) as exc:
        agent_handler({
            "command_id": "r1-cmd-3pts",
            "params": {
                "detection_roi": [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]],
                "analysis_roi": [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]],
            }
        })
    assert "analysis_roi requires exactly 4 ordered points" in str(exc.value)

    # 2. Jetson Agent: analysis_roi có 5 điểm -> phải bị từ chối
    with pytest.raises(ValueError) as exc:
        agent_handler({
            "command_id": "r1-cmd-5pts",
            "params": {
                "detection_roi": [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]],
                "analysis_roi": [[0.1, 0.1], [0.5, 0.1], [0.9, 0.5], [0.7, 0.9], [0.2, 0.9]],
            }
        })
    assert "analysis_roi requires exactly 4 ordered points" in str(exc.value)

    # 3. Jetson Agent: detection_roi < 3 điểm -> phải bị từ chối
    with pytest.raises(ValueError) as exc:
        agent_handler({
            "command_id": "r1-cmd-det-2pts",
            "params": {
                "detection_roi": [[0.1, 0.1], [0.9, 0.1]],
                "analysis_roi": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
            }
        })
    assert "detection_roi needs at least 3 points" in str(exc.value)

    # 4. Jetson Agent: Đúng 4 điểm analysis_roi và >= 3 điểm detection_roi -> Thành công
    res = agent_handler({
        "command_id": "r1-cmd-valid",
        "params": {
            "detection_roi": [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]],
            "analysis_roi": [[0.1, 0.9], [0.9, 0.9], [0.7, 0.2], [0.3, 0.2]],
            "road_width_m": 8.0,
            "road_length_m": 40.0,
            "lane_count": 3
        }
    })
    assert "saved successfully" in res.lower()
    assert tmp_roi_file.exists()

    # 5. Kiểm tra CommandHandler bọc ngoài Jetson Agent: Trả status="failed"/"error" qua MQTT khi vi phạm
    pub = MockPublisher()
    cmd_handler = CommandHandler(pub)
    cmd_handler.register("set_roi_remote", agent_handler)

    cmd_handler.handle({
        "command_id": "cmd-roi-fail",
        "action": "set_roi_remote",
        "params": {
            "detection_roi": [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]],
            "analysis_roi": [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]]  # 3 điểm
        }
    })
    time.sleep(0.05)
    assert len(pub.results) == 1
    assert pub.results[0]["command_id"] == "cmd-roi-fail"
    assert pub.results[0]["status"] in ("failed", "error")
    assert "analysis_roi requires exactly 4 ordered points" in pub.results[0]["message"]

    # 6. Backend API (remote_control.py): Chặn từ HTTP 400
    try:
        from fastapi import HTTPException
        import webgis.backend.routers.remote_control as rc_module
        from webgis.backend.routers.remote_control import set_remote_roi, SetRoiRequest

        monkeypatch.setattr(rc_module, "_check_node_exists", lambda edge_id: {"id": edge_id})
        monkeypatch.setattr(rc_module.mqtt_service, "publish_command", lambda *args, **kwargs: None)

        # 6a. detection_roi < 3 điểm -> HTTP 400
        req_det_fail = SetRoiRequest(
            detection_roi=[[0.1, 0.1], [0.9, 0.1]],
            analysis_roi=[[0.1, 0.9], [0.9, 0.9], [0.7, 0.2], [0.3, 0.2]]
        )
        with pytest.raises(HTTPException) as http_exc:
            await set_remote_roi("edge-test", req_det_fail)
        assert http_exc.value.status_code == 400
        assert "detection_roi" in http_exc.value.detail

        # 6b. analysis_roi có 3 điểm -> HTTP 400
        req_3pts = SetRoiRequest(
            detection_roi=[[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]],
            analysis_roi=[[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]]
        )
        with pytest.raises(HTTPException) as http_exc:
            await set_remote_roi("edge-test", req_3pts)
        assert http_exc.value.status_code == 400
        assert "analysis_roi" in http_exc.value.detail

        # 6c. analysis_roi có 5 điểm -> HTTP 400
        req_5pts = SetRoiRequest(
            detection_roi=[[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]],
            analysis_roi=[[0.1, 0.1], [0.5, 0.1], [0.9, 0.5], [0.7, 0.9], [0.2, 0.9]]
        )
        with pytest.raises(HTTPException) as http_exc:
            await set_remote_roi("edge-test", req_5pts)
        assert http_exc.value.status_code == 400
        assert "analysis_roi" in http_exc.value.detail

        # 6d. analysis_roi đúng 4 điểm -> HTTP 200 (Thành công)
        req_valid = SetRoiRequest(
            detection_roi=[[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]],
            analysis_roi=[[0.1, 0.9], [0.9, 0.9], [0.7, 0.2], [0.3, 0.2]]
        )
        res_backend = await set_remote_roi("edge-test", req_valid)
        assert res_backend["status"] == "sent"
    except ImportError:
        pass


def test_r2_calibration_order_and_perspective():
    """Test R2: Kiểm tra luật phối cảnh và thứ tự 4 điểm P1-P4 (Near-Left -> Near-Right -> Far-Right -> Far-Left)."""
    from analytics.speed_estimator import PerspectiveCalibration

    # 1. Hợp lệ: P1, P2 gần đáy ảnh (y=0.85), P3, P4 xa (y=0.25), đáy gần rộng hơn đáy xa
    valid_quad = [
        [0.15, 0.85],  # P1: Near-Left
        [0.85, 0.85],  # P2: Near-Right
        [0.65, 0.25],  # P3: Far-Right
        [0.35, 0.25],  # P4: Far-Left
    ]
    assert PerspectiveCalibration.validate_aspect_ratio_and_order(valid_quad, road_width_m=7.5, road_length_m=40.0) is True

    # 2. Sai thứ tự: Điểm Xa click trước (P1, P2 có y nhỏ hơn P3, P4)
    inverted_near_far = [
        [0.35, 0.25],  # P1: Far-Left (sai)
        [0.65, 0.25],  # P2: Far-Right (sai)
        [0.85, 0.85],  # P3: Near-Right
        [0.15, 0.85],  # P4: Near-Left
    ]
    with pytest.raises(ValueError) as exc1:
        PerspectiveCalibration.validate_aspect_ratio_and_order(inverted_near_far, 7.5, 40.0)
    assert "Calibration order error" in str(exc1.value)

    # 3. Click dọc theo lề đường (longitudinal curb) thay vì ngang mặt cắt (transversal)
    curb_first = [
        [0.15, 0.85],  # P1: Near-Left
        [0.35, 0.25],  # P2: Far-Left (click dọc theo mép trái đường)
        [0.65, 0.25],  # P3: Far-Right
        [0.85, 0.85],  # P4: Near-Right
    ]
    with pytest.raises(ValueError) as exc2:
        PerspectiveCalibration.validate_aspect_ratio_and_order(curb_first, 7.5, 40.0)
    assert ("Calibration side error" in str(exc2.value) or "Calibration order error" in str(exc2.value))

    # 4. Vi phạm hiệu ứng phối cảnh (Foreshortening): Cạnh xa rộng hơn đáng kể cạnh gần
    invalid_foreshortening = [
        [0.45, 0.85],  # P1: Near-Left (hẹp)
        [0.55, 0.85],  # P2: Near-Right (hẹp: width=0.10)
        [0.90, 0.25],  # P3: Far-Right (rộng: width=0.80)
        [0.10, 0.25],  # P4: Far-Left
    ]
    with pytest.raises(ValueError) as exc3:
        PerspectiveCalibration.validate_aspect_ratio_and_order(invalid_foreshortening, 7.5, 40.0)
    assert "Calibration perspective error" in str(exc3.value)


def test_r3_reload_config_and_pipeline_restart(monkeypatch, tmp_path):
    """Test R3: Kiểm tra reload_config đáng tin cậy và kiểm tra mtime trong idempotency."""
    import communication.jetson_agent as ja_module
    from communication.jetson_agent import make_reload_config_handler, make_start_pipeline_handler

    # Mock subprocess and state
    class MockProcess(object):
        def __init__(self, pid=9999):
            self.pid = pid
        def poll(self):
            return None

    mock_proc = MockProcess(pid=9999)
    agent_state = {
        'pipeline_process': mock_proc,
        'pipeline_current_cmd': ('csi', 'configs/roi_config.remote.json', 1000.0, False),
        'pipeline_lock': threading.RLock(),
    }

    # Giả lập restart_pipeline được gọi
    stopped_processes = []
    started_commands = []

    def mock_stop(proc):
        stopped_processes.append(proc.pid)

    monkeypatch.setattr(ja_module, 'graceful_stop_pipeline', mock_stop)

    def mock_popen(cmd, **kwargs):
        started_commands.append(cmd)
        return MockProcess(pid=10001)

    monkeypatch.setattr(ja_module.subprocess, 'Popen', mock_popen)

    # 1. Gọi reload_config handler khi pipeline đang chạy
    reload_handler = make_reload_config_handler(agent_state)
    res = reload_handler({'command_id': 'reload-test'})
    assert 'restarted' in res.lower()
    assert len(stopped_processes) == 1
    assert stopped_processes[0] == 9999
    assert len(started_commands) == 1
    assert agent_state['pipeline_process'].pid == 10001

    # 2. Khi pipeline KHÔNG chạy, reload_config trả thông báo chờ lần start tới
    agent_state['pipeline_process'] = None
    res_idle = reload_handler({'command_id': 'reload-idle'})
    assert 'not currently running' in res_idle.lower()








