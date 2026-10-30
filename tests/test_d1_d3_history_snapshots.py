import os
import sys
import sqlite3
import pytest
from datetime import datetime
from pathlib import Path

BACKEND_DIR = str(Path(__file__).resolve().parent.parent / "webgis" / "backend")
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

import services.data_store as ds_module
from services.data_store import DataStore, _init_history_db


def test_d1_timeline_sqlite_aggregation_and_persistence(tmp_path):
    """Test D1: Tổng hợp telemetry theo phút vào SQLite và khôi phục sau khi restart."""
    db_file = tmp_path / "test_history.db"
    store = DataStore(db_path=db_file)
    seg_id = "test-seg-001"
    edge_id = "test-edge-01"

    store.upsert_segment({
        "segment_id": seg_id,
        "name": "Đường Nguyễn Trãi Test",
        "road_length_m": 500.0,
        "lane_count": 3
    })
    store.upsert_node({
        "edge_id": edge_id,
        "segment_id": seg_id,
        "name": "Node Test 01",
        "latitude": 10.84,
        "longitude": 106.65
    })

    # 1. Gửi telemetry mẫu 1
    t1 = {
        "segment_id": seg_id,
        "avg_speed_kmh": 40.0,
        "congestion_score": 20,
        "traffic_status": "FREE",
        "current_vehicle_count": 5
    }
    store.update_telemetry(edge_id, t1)

    # 2. Gửi telemetry mẫu 2 trong cùng 1 phút (UPSERT running average)
    t2 = {
        "segment_id": seg_id,
        "avg_speed_kmh": 30.0,
        "congestion_score": 40,
        "traffic_status": "SLOW",
        "current_vehicle_count": 10
    }
    store.update_telemetry(edge_id, t2)

    # Kiểm tra bản ghi timeline
    records = store.get_timeline_records(seg_id)
    assert len(records) == 1, "Các mẫu trong cùng 1 phút phải được gộp thành 1 bản ghi"
    rec = records[0]
    assert rec["segment_id"] == seg_id
    assert rec["avg_speed_kmh"] == 35.0, "Vận tốc phải là trung bình của 40 và 30"
    assert rec["congestion_score"] == 40
    assert rec["traffic_status"] == "SLOW"
    assert rec["vehicle_count"] == 10

    # 3. NGHIỆM THU D1: Giả lập restart Backend (tạo instance DataStore mới từ database SQLite cũ)
    restarted_store = DataStore(db_path=db_file)
    restarted_records = restarted_store.get_timeline_records(seg_id)
    assert len(restarted_records) == 1, "Sau khi restart backend, dữ liệu lịch sử vẫn tồn tại từ SQLite"
    assert restarted_records[0]["avg_speed_kmh"] == 35.0
    assert restarted_records[0]["congestion_score"] == 40


def test_d3_snapshot_captured_at_preservation(tmp_path):
    """Test D3: Ảnh gửi bù từ Outbox giữ đúng giờ chụp captured_at, không bị đè giờ upload."""
    db_file = tmp_path / "test_history_snap.db"
    store = DataStore(db_path=db_file)
    event_captured_at = "2026-10-29T08:15:30"
    now_received_at = "2026-10-29T09:30:00"

    snap_record = {
        "snapshot_id": "snap-outbox-001",
        "edge_id": "edge-01",
        "camera_id": "cam-01",
        "segment_id": "segment-001",
        "timestamp": event_captured_at,
        "captured_at": event_captured_at,
        "received_at": now_received_at,
        "time_str": "08:15:30",
        "location_name": "Đoạn A",
        "traffic_status": "CONGESTED",
        "congestion_score": 85,
        "avg_speed_kmh": 8.5,
        "vehicle_count": 45,
        "image_url": "/snapshots/edge-01_test.jpg",
        "trigger_reason": "auto_congestion_detected"
    }

    store.add_snapshot_record(snap_record)

    # Kiểm tra truy vấn snapshots
    snaps = store.get_snapshots(segment_id="segment-001")
    assert len(snaps) == 1
    assert snaps[0]["captured_at"] == event_captured_at
    assert snaps[0]["time_str"] == "08:15:30"
    assert snaps[0]["traffic_status"] == "CONGESTED"

    # NGHIỆM THU D1 + D3: Restart backend -> snapshot vẫn còn nguyên và giữ đúng captured_at
    restarted_store = DataStore(db_path=db_file)
    restored_snaps = restarted_store.get_snapshots(segment_id="segment-001")
    assert len(restored_snaps) == 1
    assert restored_snaps[0]["captured_at"] == event_captured_at
    assert restored_snaps[0]["snapshot_id"] == "snap-outbox-001"


def test_history_endpoints_with_sqlite_data(tmp_path, monkeypatch):
    """Kiểm tra hai endpoint GET /api/v1/history/timeline và GET /api/v1/history/snapshots."""
    from routers.history import get_timeline, get_congestion_snapshots

    db_file = tmp_path / "test_api_history.db"
    store = DataStore(db_path=db_file)
    monkeypatch.setitem(get_timeline.__globals__, "store", store)
    monkeypatch.setitem(get_congestion_snapshots.__globals__, "store", store)

    seg_id = "segment-001"
    store.upsert_segment({"segment_id": seg_id, "name": "Đoạn 01"})
    store.upsert_node({"edge_id": "edge-01", "segment_id": seg_id})

    # Ban đầu khi chưa có dữ liệu: trả về danh sách rỗng, không crash
    empty_timeline = get_timeline(segment_id=seg_id)
    assert empty_timeline["total_intervals"] == 0
    assert empty_timeline["records"] == []

    empty_snaps = get_congestion_snapshots(segment_id=seg_id)
    assert empty_snaps == []

    # Thêm dữ liệu telemetry
    store.update_telemetry("edge-01", {
        "segment_id": seg_id,
        "avg_speed_kmh": 28.5,
        "congestion_score": 55,
        "traffic_status": "SLOW",
        "current_vehicle_count": 18
    })

    # Thêm snapshot với captured_at
    snap_data = {
        "snapshot_id": "snap-test-http",
        "edge_id": "edge-01",
        "segment_id": seg_id,
        "timestamp": "2026-10-29T07:45:00",
        "captured_at": "2026-10-29T07:45:00",
        "received_at": "2026-10-29T09:40:00",
        "time_str": "07:45:00",
        "traffic_status": "CONGESTED",
        "congestion_score": 90,
        "avg_speed_kmh": 5.0,
        "vehicle_count": 50,
        "image_url": "/snapshots/snap-test-http.jpg"
    }
    store.add_snapshot_record(snap_data)

    # 1. Kiểm tra timeline endpoint trả về dữ liệu thật
    res_timeline = get_timeline(segment_id=seg_id)
    assert res_timeline["total_intervals"] == 1
    assert res_timeline["peak_congestion_score"] == 55
    assert res_timeline["avg_speed_kmh"] == 28.5
    assert len(res_timeline["records"]) == 1
    assert res_timeline["records"][0]["traffic_status"] == "SLOW"

    # 2. Kiểm tra snapshots endpoint trả về ảnh thật từ SQLite
    res_snaps = get_congestion_snapshots(segment_id=seg_id)
    assert len(res_snaps) == 1
    assert res_snaps[0]["snapshot_id"] == "snap-test-http"
    assert res_snaps[0]["captured_at"] == "2026-10-29T07:45:00"
    assert res_snaps[0]["traffic_status"] == "CONGESTED"


@pytest.mark.asyncio
async def test_d3_upload_snapshot_multipart_endpoint(tmp_path, monkeypatch):
    """Test D3: Upload HTTP endpoint nhận captured_at từ Edge Outbox và bảo toàn mốc thời gian."""
    import routers.snapshots as snap_router
    from routers.snapshots import _handle_snapshot_upload
    from starlette.datastructures import UploadFile
    import io

    db_file = tmp_path / "test_upload_snap.db"
    store = DataStore(db_path=db_file)
    monkeypatch.setattr(snap_router, "store", store)
    monkeypatch.setattr(snap_router, "SNAPSHOTS_STORAGE_DIR", tmp_path / "snapshots")
    (tmp_path / "snapshots").mkdir(parents=True, exist_ok=True)

    class DummyRequest:
        headers = {"x-edge-token": "dev-edge-token"}
    dummy_req = DummyRequest()

    fake_img = UploadFile(filename="test.jpg", file=io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 100))
    captured_time = "2026-10-29T08:20:15"

    res = await _handle_snapshot_upload(
        request=dummy_req,
        image=fake_img,
        edge_id="edge-outbox-test",
        segment_id="segment-001",
        captured_at=captured_time,
        traffic_status="CONGESTED",
        trigger_reason="auto_congestion_detected",
        x_edge_token="dev-edge-token"
    )

    assert res["success"] is True
    record = res["record"]
    assert record["captured_at"] == captured_time
    assert record["time_str"] == "08:20:15"
    assert record["traffic_status"] == "CONGESTED"

    # Kiểm tra đã lưu vào SQLite
    saved_snaps = store.get_snapshots(segment_id="segment-001")
    assert len(saved_snaps) == 1
    assert saved_snaps[0]["captured_at"] == captured_time


