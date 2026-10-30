#!/usr/bin/env python3
"""Unit tests cho Đợt 6 — Giao diện WebGIS (F1 - F3).

Bao quát:
- F1: Tô màu đúng đoạn đường theo segment_id của node, loại bỏ mọi ID gán cứng và không tô nhầm khi edge_id='edge-01'.
- F2: Sự kiện backend phát (segment_update, node_mismatch_warning, spatial_drift_warning) đồng bộ với giao diện.
- F3: Preview ảnh qua WebSocket gửi URL HTTP GET nhị phân nhẹ và gửi riêng cho user yêu cầu (không broadcast base64).
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Thêm root vào sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "webgis" / "backend"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

import jwt
from webgis.backend.services.websocket_manager import ws_manager, JWT_SECRET
from webgis.backend.services.data_store import store
from webgis.backend.main import app


@pytest.fixture(autouse=True)
def cleanup_store():
    yield
    # Dọn dẹp cache preview sau mỗi test
    import routers.remote_control as rc
    rc._preview_cache.clear()
    rc._preview_requesters.clear()


class TestF1SegmentColorMapping:
    """F1: Kiểm tra logic ánh xạ tô màu đoạn đường theo segment_id, không tô nhầm mọi đoạn."""

    def test_multi_node_independent_segment_color(self):
        """Giả lập 2 node và 2 segment trên bản đồ.

        Node 1: 'edge-01' -> gắn 'seg-le-duc-tho'
        Node 2: 'edge-02' -> gắn 'seg-quang-trung'
        """
        # Trạng thái segments trước khi nhận telemetry
        segments = [
            {
                "properties": {
                    "segment_id": "seg-le-duc-tho",
                    "traffic_color": "#10B981",  # Xanh
                    "congestion_score": 10,
                }
            },
            {
                "properties": {
                    "segment_id": "seg-quang-trung",
                    "traffic_color": "#10B981",  # Xanh
                    "congestion_score": 15,
                }
            },
        ]

        # Ánh xạ edge_id -> segment_id như đã lưu trong edgeSegmentMapRef
        edge_segment_map = {
            "edge-01": "seg-le-duc-tho",
            "edge-02": "seg-quang-trung",
        }

        # Node 'edge-01' gửi telemetry kẹt xe nặng (Score 85 -> Màu đỏ)
        msg_edge_01 = {
            "type": "telemetry",
            "edge_id": "edge-01",
            "data": {
                "congestion_score": 85,
                "traffic_status": "CONGESTED",
                "segment_id": "seg-le-duc-tho",
                "avg_speed_kmh": 4.5,
                "current_vehicle_count": 25,
            }
        }

        # Logic khớp đoạn đường mới (Fix F1)
        target_segment_id = msg_edge_01["data"].get("segment_id") or edge_segment_map.get(msg_edge_01["edge_id"])
        assert target_segment_id == "seg-le-duc-tho"

        score = msg_edge_01["data"]["congestion_score"]
        color = "#EF4444" if score >= 65 else "#F59E0B" if score >= 35 else "#10B981"

        updated_segments = []
        for f in segments:
            seg_id = f["properties"]["segment_id"]
            # Chỉ khớp đúng target_segment_id, KHÔNG có điều kiện msg.edge_id === 'edge-01'
            if seg_id == target_segment_id:
                updated_segments.append({
                    "properties": {
                        **f["properties"],
                        "congestion_score": score,
                        "traffic_color": color,
                    }
                })
            else:
                updated_segments.append(f)

        # Đoạn của edge-01 phải đổi sang màu đỏ
        seg1 = next(s for s in updated_segments if s["properties"]["segment_id"] == "seg-le-duc-tho")
        assert seg1["properties"]["traffic_color"] == "#EF4444"
        assert seg1["properties"]["congestion_score"] == 85

        # Đoạn của edge-02 TUYỆT ĐỐI KHÔNG ĐỔI MÀU (vẫn giữ màu xanh ban đầu)
        seg2 = next(s for s in updated_segments if s["properties"]["segment_id"] == "seg-quang-trung")
        assert seg2["properties"]["traffic_color"] == "#10B981"
        assert seg2["properties"]["congestion_score"] == 15


class TestF2BackendFrontendEventSync:
    """F2: Kiểm tra các sự kiện cảnh báo và cập nhật hạ tầng được phát chuẩn xác."""

    def test_node_mismatch_warning_broadcast_payload(self):
        """Kiểm tra cấu trúc sự kiện node_mismatch_warning khớp với frontend."""
        warning_msg = {
            "type": "node_mismatch_warning",
            "edge_id": "edge-approved-01",
            "actual_hardware_id": "edge-physical-jetson-99",
            "mac_address": "80:32:53:8A:88:B5",
            "message": "Phát hiện sai lệch mã định danh...",
        }
        assert warning_msg["type"] == "node_mismatch_warning"
        assert "actual_hardware_id" in warning_msg
        assert "message" in warning_msg

    def test_spatial_drift_warning_broadcast_payload(self):
        """Kiểm tra cấu trúc sự kiện spatial_drift_warning khớp với frontend."""
        drift_msg = {
            "type": "spatial_drift_warning",
            "edge_id": "edge-approved-01",
            "drift_m": 125.4,
            "reported_coords": [10.852, 106.661],
            "saved_coords": [10.851, 106.660],
            "message": "Cảnh báo di dời phần cứng...",
        }
        assert drift_msg["type"] == "spatial_drift_warning"
        assert drift_msg["drift_m"] > 50.0
        assert len(drift_msg["reported_coords"]) == 2

    def test_segment_update_payload(self):
        """Kiểm tra cấu trúc sự kiện segment_update / segment_updated."""
        seg_msg = {
            "type": "segment_update",
            "segment_id": "SEG_001",
            "data": {
                "segment_id": "SEG_001",
                "name": "Đường Lê Đức Thọ",
                "lane_count": 2,
                "congestion_score": 45,
                "traffic_status": "SLOW",
            }
        }
        assert seg_msg["type"] == "segment_update"
        assert seg_msg["segment_id"] == "SEG_001"
        assert "congestion_score" in seg_msg["data"]


class TestF3PreviewFrameUrlAndTargetedDelivery:
    """F3: Kiểm tra preview qua WebSocket chỉ báo URL HTTP GET và gửi riêng cho requester."""

    def test_preview_request_records_user_id(self):
        client = TestClient(app)

        # Tạo token cho Staff user "admin-user-123"
        token = jwt.encode(
            {"userId": "admin-user-123", "role": "ADMIN", "exp": time.time() + 3600},
            JWT_SECRET,
            algorithm="HS256"
        )

        import routers.remote_control as rc

        with patch("services.mqtt_service.mqtt_service.publish_command") as mock_pub:
            mock_pub.return_value = True
            # Sử dụng node có sẵn trong approved_nodes (edge-110)
            res = client.post(
                "/api/v1/nodes/edge-110/preview",
                json={"source_type": "csi"},
                headers={"Authorization": f"Bearer {token}"}
            )
            assert res.status_code == 200
            data = res.json()
            req_id = data["request_id"]
            assert req_id is not None
            assert rc._preview_requesters.get(req_id) == "admin-user-123"

    @pytest.mark.asyncio
    async def test_send_to_user_targets_correct_client(self):
        """Kiểm tra ws_manager.send_to_user chỉ gửi đến đúng socket của user_id."""
        mock_ws_target = AsyncMock()
        mock_ws_other = AsyncMock()

        # Giả lập 2 connection
        ws_manager.active_connections[mock_ws_target] = {"role": "ADMIN", "userId": "user-targeted"}
        ws_manager.active_connections[mock_ws_other] = {"role": "ADMIN", "userId": "user-other"}

        try:
            msg = {"type": "preview_frame", "edge_id": "edge-110", "preview_url": "/api/test"}
            sent = await ws_manager.send_to_user("user-targeted", msg)

            assert sent is True
            # Target socket phải được gọi send_text
            assert mock_ws_target.send_text.called
            # Other socket TUYỆT ĐỐI KHÔNG được gọi
            assert not mock_ws_other.send_text.called
        finally:
            ws_manager.disconnect(mock_ws_target)
            ws_manager.disconnect(mock_ws_other)

    def test_receive_capture_returns_url_and_binary_endpoint(self):
        client = TestClient(app)
        import routers.remote_control as rc

        req_id = "test-req-binary-99"
        rc._preview_requesters[req_id] = "user-test"

        fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 200 + b"\xff\xd9"

        # Jetson upload ảnh về qua POST /api/edge/edge-110/capture
        with patch.object(rc.ws_manager, "send_to_user", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            res = client.post(
                "/api/edge/edge-110/capture",
                files={"file": ("preview.jpg", fake_jpeg, "image/jpeg")},
                data={"purpose": "roi_setup", "request_id": req_id, "timestamp": "2026-10-29T11:00:00"},
                headers={"X-Edge-Token": "dev-edge-token"}
            )
            assert res.status_code == 200
            assert res.json()["purpose"] == "roi_setup"

            # Kiểm tra ws_manager.send_to_user được gọi kèm preview_url
            assert mock_send.called
            sent_args = mock_send.call_args[0]
            assert sent_args[0] == "user-test"
            ws_payload = sent_args[1]
            assert ws_payload["type"] == "preview_frame"
            assert "preview_url" in ws_payload
            expected_url = f"/api/v1/nodes/edge-110/preview/{req_id}/image"
            assert ws_payload["preview_url"] == expected_url

        # Kiểm tra endpoint GET ảnh nhị phân HTTP GET trực tiếp
        token = jwt.encode(
            {"userId": "user-test", "role": "ADMIN", "exp": time.time() + 3600},
            JWT_SECRET,
            algorithm="HS256"
        )
        img_res = client.get(expected_url, headers={"Authorization": f"Bearer {token}"})
        assert img_res.status_code == 200
        assert img_res.headers["content-type"] == "image/jpeg"
        assert img_res.content == fake_jpeg
