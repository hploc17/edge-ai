import asyncio
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
import pytest
import jwt

BACKEND_DIR = str(Path(__file__).resolve().parent.parent / "webgis" / "backend")
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from webgis.backend.services.data_store import DataStore, _save_json_file
from webgis.backend.services.websocket_manager import WebSocketManager, JWT_SECRET
from webgis.backend.services.mqtt_service import mqtt_service, store as backend_store


def test_d4_dirty_check_no_disk_write_on_heartbeat(tmp_path, monkeypatch):
    """Test D4: Heartbeat và Telemetry định kỳ KHÔNG được ghi đĩa approved_nodes.json."""
    db_file = tmp_path / "test_history.db"
    store = DataStore(db_path=db_file)
    edge_id = "edge-perf-01"

    write_count = [0]
    original_save = store._persist_nodes

    def spy_persist():
        write_count[0] += 1
        return original_save()

    monkeypatch.setattr(store, "_persist_nodes", spy_persist)

    # 1. Thêm node ban đầu -> Phải ghi đĩa 1 lần để lưu cấu hình
    store.upsert_node({
        "edge_id": edge_id,
        "name": "Node Test Performance",
        "latitude": 10.85,
        "longitude": 106.66
    })
    assert write_count[0] == 1, "upsert_node phải ghi đĩa lưu metadata"

    # 2. Nhận 50 bản tin heartbeat và telemetry qua MQTT
    class DummyMsg:
        def __init__(self, t, p):
            self.topic = t
            self.payload = p.encode("utf-8")

    monkeypatch.setattr("webgis.backend.services.mqtt_service.store", store)

    for i in range(20):
        # Heartbeat
        hb_msg = DummyMsg(
            f"traffic/{edge_id}/heartbeat",
            json.dumps({"edge_id": edge_id, "status": "online", "timestamp": datetime.now().isoformat()})
        )
        mqtt_service._on_message(None, None, hb_msg)

        # Telemetry
        tel_msg = DummyMsg(
            f"traffic/{edge_id}/telemetry",
            json.dumps({"edge_id": edge_id, "congestion_score": 30, "avg_speed_kmh": 40.0})
        )
        mqtt_service._on_message(None, None, tel_msg)

    # NGHIỆM THU D4: write_count vẫn phải là 1 (không ghi đĩa thêm 40 lần vô ích)
    assert write_count[0] == 1, f"Heartbeat và Telemetry không được ghi đĩa approved_nodes (thực tế: {write_count[0]})"


@pytest.mark.asyncio
async def test_d4_slow_client_isolation_in_websocket_broadcast():
    """Test D4: Một client WebSocket bị lag/treo không được làm nghẽn các client khác."""
    manager = WebSocketManager()

    class MockFastWebSocket:
        def __init__(self):
            self.received = []

        async def accept(self):
            pass

        async def send_text(self, text):
            self.received.append(text)

    class MockSlowWebSocket:
        def __init__(self):
            self.received = []

        async def accept(self):
            pass

        async def send_text(self, text):
            # Giả lập mạng 3G lag 5 giây (vượt timeout 1.5s)
            await asyncio.sleep(3.0)
            self.received.append(text)

    fast_client = MockFastWebSocket()
    slow_client = MockSlowWebSocket()

    await manager.connect(fast_client)
    await manager.connect(slow_client)

    start_time = time.time()
    # Broadcast phát sóng
    await manager.broadcast({"type": "telemetry", "data": {"speed": 45}})
    elapsed = time.time() - start_time

    # NGHIỆM THU D4:
    # 1. Fast client nhận được tin nhắn ngay lập tức
    assert len(fast_client.received) == 1
    # 2. Tổng thời gian broadcast phải < 2.0s (do timeout 1.5s bảo vệ, không bị treo 3s)
    assert elapsed < 2.0, f"Broadcast bị block quá lâu bởi slow client: {elapsed:.2f}s"
    # 3. Slow client bị loại khỏi danh sách active do timeout
    assert slow_client not in manager.active_connections
    assert fast_client in manager.active_connections


def test_d5_server_side_liveness_timestamp(tmp_path, monkeypatch):
    """Test D5: Liveness dùng giờ nhận của Server, miễn nhiễm với đồng hồ Jetson bị lệch 1 giờ."""
    db_file = tmp_path / "test_liveness.db"
    store = DataStore(db_path=db_file)
    edge_id = "edge-liveness-01"

    store.upsert_node({
        "edge_id": edge_id,
        "name": "Node Liveness Test",
        "latitude": 10.85,
        "longitude": 106.66,
        "last_seen": "2020-01-01T00:00:00"
    })

    monkeypatch.setattr("webgis.backend.services.mqtt_service.store", store)

    class DummyMsg:
        def __init__(self, t, p):
            self.topic = t
            self.payload = p.encode("utf-8")

    # Giả lập Jetson Nano không có RTC, gửi giờ lệch 1 tiếng về quá khứ
    skewed_device_time = "2026-10-29T09:00:00"
    hb_msg = DummyMsg(
        f"traffic/{edge_id}/heartbeat",
        json.dumps({
            "edge_id": edge_id,
            "status": "online",
            "timestamp": skewed_device_time
        })
    )

    t_before = datetime.now()
    mqtt_service._on_message(None, None, hb_msg)
    t_after = datetime.now()

    # NGHIỆM THU D5:
    node = store.nodes[edge_id]
    assert node["status"] == "online"
    # last_seen phải là giờ Server hiện tại, không phải giờ bị lệch 2026-10-29T09:00:00
    last_seen_dt = datetime.fromisoformat(node["last_seen"])
    assert t_before <= last_seen_dt <= t_after
    # Đồng thời lưu giữ lại device_reported_time để đối chiếu độ trễ
    assert node["device_reported_time"] == skewed_device_time


@pytest.mark.asyncio
async def test_d6_websocket_role_authentication_and_filtering():
    """Test D6: WebSocket phân quyền Admin/Manager nhận device_pending, lọc khách vãng lai."""
    manager = WebSocketManager()

    admin_token = jwt.encode({"userId": "admin1", "role": "ADMIN"}, JWT_SECRET, algorithm="HS256")
    user_token = jwt.encode({"userId": "user1", "role": "USER"}, JWT_SECRET, algorithm="HS256")

    class MockWS:
        def __init__(self):
            self.messages = []

        async def accept(self):
            pass

        async def send_text(self, text):
            self.messages.append(json.loads(text))

    ws_guest = MockWS()
    ws_user = MockWS()
    ws_admin = MockWS()

    # Guest kết nối không token, User kết nối có user_token, Admin kết nối có admin_token
    await manager.connect(ws_guest, token=None)
    await manager.connect(ws_user, token=user_token)
    await manager.connect(ws_admin, token=admin_token)

    # 1. Phát tin công khai: cả 3 đều nhận được
    await manager.broadcast({"type": "telemetry", "data": {"speed": 35}})
    assert len(ws_guest.messages) == 1
    assert len(ws_user.messages) == 1
    assert len(ws_admin.messages) == 1

    # 2. Phát tin nhạy cảm quản trị: device_pending (ZTP discovery)
    await manager.broadcast({"type": "device_pending", "edge_id": "edge-new-999"})
    # Guest và User không được nhận, Admin bắt buộc phải nhận được
    assert len(ws_guest.messages) == 1, "Guest không được nhận device_pending"
    assert len(ws_user.messages) == 1, "User không được nhận device_pending"
    assert len(ws_admin.messages) == 2, "Admin phải nhận được device_pending"

    # 3. Guest sau đó đăng nhập và gửi message authenticate qua WebSocket
    manager.set_client_token(ws_guest, admin_token)
    await manager.broadcast({"type": "preview_frame", "edge_id": "edge-01", "image": "base64data"})

    # Giờ đây guest (đã thăng hạng Admin) nhận được preview_frame
    assert len(ws_guest.messages) == 2
    assert ws_guest.messages[-1]["type"] == "preview_frame"


def test_d7_thread_safety_concurrent_reads_and_writes(tmp_path):
    """Test D7: Đa luồng đọc ghi đồng thời giữa MQTT Thread và FastAPI Coroutines không crash."""
    db_file = tmp_path / "test_concurrency.db"
    store = DataStore(db_path=db_file)

    initial_count = len(store.get_all_nodes())
    for i in range(10):
        store.upsert_node({
            "edge_id": f"edge-concur-{i:02d}",
            "name": f"Node {i}",
            "latitude": 10.80 + i * 0.01,
            "longitude": 106.60 + i * 0.01
        })
    expected_count = initial_count + 10

    stop_event = threading.Event()
    exceptions = []

    def writer_thread(tid):
        try:
            for j in range(50):
                if stop_event.is_set():
                    break
                store.update_telemetry(f"edge-concur-0{j % 10}", {
                    "congestion_score": j % 100,
                    "avg_speed_kmh": 20.0 + (j % 30),
                    "current_vehicle_count": j
                })
                time.sleep(0.002)
        except Exception as e:
            exceptions.append(e)

    def reader_thread(tid):
        try:
            for _ in range(50):
                if stop_event.is_set():
                    break
                # Giả lập FastAPI endpoint GET /api/v1/nodes và live states
                nodes = store.get_all_nodes()
                states = store.get_live_states()
                assert len(nodes) >= 10
                assert len(states) >= 10
                time.sleep(0.002)
        except Exception as e:
            exceptions.append(e)

    threads = []
    for t_idx in range(4):
        threads.append(threading.Thread(target=writer_thread, args=(t_idx,)))
        threads.append(threading.Thread(target=reader_thread, args=(t_idx,)))

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=10.0)

    # Dọn dẹp nodes test khỏi store
    for i in range(10):
        store.delete_node(f"edge-concur-{i:02d}")

    # NGHIỆM THU D7: Không phát sinh RuntimeError: dictionary changed size during iteration
    assert len(exceptions) == 0, f"Phát sinh lỗi đa luồng: {exceptions}"


def test_d8_atomic_write_and_no_backup_files():
    """Test D8: Atomic write bảo toàn dữ liệu và dọn sạch các file .backup.json."""
    data_dir = Path(BACKEND_DIR) / "data"
    backup_files = list(data_dir.glob("*.backup.json"))

    # NGHIỆM THU D8: Toàn bộ các file .backup.json thủ công đã được dọn khỏi git/data
    assert len(backup_files) == 0, f"Vẫn còn file backup tồn đọng trong thư mục data: {backup_files}"
