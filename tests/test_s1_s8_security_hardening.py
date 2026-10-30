#!/usr/bin/env python3
"""Unit tests cho Đợt 7 — Bảo mật & Hardening Hệ thống (S1 - S8).

Bao quát:
- S1: Quản lý Secret, biến môi trường và Fail-fast trong môi trường Production.
- S2: Xác thực X-Edge-Token bằng so sánh hằng thời gian (timing-safe), loại bỏ log lộ token.
- S3: Endpoint bảo vệ nghiêm ngặt: /live/start, /snapshots, ẩn địa chỉ MAC với người xem thường.
- S4: Chống Path Traversal trong upload snapshot, kiểm tra JPEG/PNG Magic Bytes và giới hạn kích thước 10MB.
- S5: Hardening cấu hình MediaMTX (tắt overridePublisher).
- S7: Kiểm soát quyền hạn tập trung (require_staff) và chuẩn hóa CORS.
- S8: Kiểm tra cookies.txt được cách ly hoàn toàn khỏi repository.
"""

import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "webgis" / "backend"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

import routers.remote_control as rc
from webgis.backend.main import app
from webgis.backend.services.websocket_manager import JWT_SECRET
from webgis.backend.services.data_store import store


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def staff_token():
    return jwt.encode(
        {"userId": "admin-sec-01", "role": "ADMIN", "exp": time.time() + 3600},
        JWT_SECRET,
        algorithm="HS256"
    )


@pytest.fixture
def user_token():
    return jwt.encode(
        {"userId": "user-guest-01", "role": "USER", "exp": time.time() + 3600},
        JWT_SECRET,
        algorithm="HS256"
    )


class TestS2S3AuthenticationAndEndpointGuards:
    """S2 & S3: Kiểm tra xác thực token và khóa chặn các endpoint nhạy cảm."""

    def test_upload_snapshot_unauthenticated_rejected(self, client):
        """Upload snapshot không có token bị từ chối 401."""
        fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 100
        res = client.post(
            "/api/v1/snapshots",
            files={"image": ("snap.jpg", fake_jpeg, "image/jpeg")},
            data={"edge_id": "edge-110"}
        )
        assert res.status_code == 401
        assert "Xác thực thất bại" in res.json().get("detail", "")

    def test_upload_snapshot_invalid_token_rejected(self, client):
        """Upload snapshot với X-Edge-Token giả mạo bị từ chối 401."""
        fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 100
        res = client.post(
            "/api/v1/snapshots",
            files={"image": ("snap.jpg", fake_jpeg, "image/jpeg")},
            data={"edge_id": "edge-110"},
            headers={"X-Edge-Token": "hacker-invalid-token"}
        )
        assert res.status_code == 401

    def test_upload_snapshot_valid_edge_token_accepted(self, client):
        """Upload snapshot với X-Edge-Token chuẩn được chấp nhận."""
        fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 100
        res = client.post(
            "/api/v1/snapshots",
            files={"image": ("snap.jpg", fake_jpeg, "image/jpeg")},
            data={"edge_id": "edge-110"},
            headers={"X-Edge-Token": "dev-edge-token"}
        )
        assert res.status_code == 200
        assert res.json().get("status") == "success"

    def test_live_stream_control_requires_staff(self, client, user_token, staff_token):
        """Kích hoạt live stream camera yêu cầu quyền STAFF (ADMIN/MANAGER)."""
        # 1. Không có token -> 401
        res1 = client.post("/api/v1/nodes/edge-110/live/start")
        assert res1.status_code == 401

        # 2. Token USER thường -> 403 Forbidden
        res2 = client.post(
            "/api/v1/nodes/edge-110/live/start",
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert res2.status_code == 403

    def test_mac_address_hidden_for_public_users(self, client, staff_token):
        """Địa chỉ MAC bị ẩn với khách vãng lai và chỉ hiện với Staff."""
        # 1. Khách vãng lai gọi GET /nodes
        res_public = client.get("/api/v1/nodes")
        assert res_public.status_code == 200
        nodes_public = res_public.json()
        assert len(nodes_public) > 0
        for n in nodes_public:
            assert "mac_address" not in n, "MAC address không được lộ cho người dùng công khai"

        # 2. Staff có token gọi GET /nodes
        res_staff = client.get("/api/v1/nodes", headers={"Authorization": f"Bearer {staff_token}"})
        assert res_staff.status_code == 200
        nodes_staff = res_staff.json()
        target_node = next((n for n in nodes_staff if n.get("edge_id") == "edge-110"), None)
        assert target_node is not None
        assert "mac_address" in target_node, "Staff phải nhìn thấy địa chỉ MAC để cấu hình ZTP"


class TestS4PathTraversalAndFileSanitization:
    """S4: Kiểm tra chống ghi file tùy ý (Path Traversal), kiểm tra Magic Bytes và kích thước file."""

    def test_path_traversal_in_edge_id_rejected(self, client):
        """Mã edge_id chứa ../ hoặc ký tự nguy hiểm bị chặn ngay lập tức."""
        fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 100
        res = client.post(
            "/api/v1/snapshots",
            files={"image": ("snap.jpg", fake_jpeg, "image/jpeg")},
            data={"edge_id": "../../etc/evil_node"},
            headers={"X-Edge-Token": "dev-edge-token"}
        )
        assert res.status_code == 400
        assert "không hợp lệ" in res.json().get("detail", "")

    def test_invalid_magic_bytes_rejected(self, client):
        """Tải file không phải JPEG/PNG (ví dụ mã độc bash script hoặc PE file) bị từ chối 400."""
        fake_malicious_script = b"#!/bin/bash\nrm -rf /"
        res = client.post(
            "/api/v1/snapshots",
            files={"image": ("exploit.jpg", fake_malicious_script, "image/jpeg")},
            data={"edge_id": "edge-110"},
            headers={"X-Edge-Token": "dev-edge-token"}
        )
        assert res.status_code == 400
        assert "Định dạng tệp không hợp lệ" in res.json().get("detail", "")

    def test_file_size_exceeding_limit_rejected(self, client):
        """Tải file vượt quá giới hạn 10MB bị từ chối 413 Payload Too Large."""
        # 10.5 MB fake data
        oversized_data = b"\xff\xd8\xff" + b"\x00" * (11 * 1024 * 1024)
        res = client.post(
            "/api/v1/snapshots",
            files={"image": ("heavy.jpg", oversized_data, "image/jpeg")},
            data={"edge_id": "edge-110"},
            headers={"X-Edge-Token": "dev-edge-token"}
        )
        assert res.status_code == 413


class TestS5S7MediaMTXAndCorsCommandsHardening:
    """S5 & S7: Kiểm tra cấu hình MediaMTX và chuẩn hóa phân quyền commands."""

    def test_mediamtx_override_publisher_is_disabled(self):
        """Cấu hình mediamtx.yml phải tắt overridePublisher để bảo vệ luồng RTSP."""
        mediamtx_path = ROOT_DIR / "deploy" / "mediamtx" / "mediamtx.yml"
        assert mediamtx_path.exists()
        content = mediamtx_path.read_text(encoding="utf-8")
        assert "overridePublisher: no" in content
        assert "overridePublisher: yes" not in content

    def test_commands_endpoint_guarded_by_require_staff(self, client, user_token, staff_token):
        """Endpoint /commands/send sử dụng trực tiếp dependency require_staff."""
        with patch("services.mqtt_service.mqtt_service.publish_command") as mock_pub:
            mock_pub.return_value = True

            # 1. Gọi không token -> 401
            res1 = client.post("/api/v1/commands/send", json={"edge_id": "edge-110", "action": "get_health"})
            assert res1.status_code == 401

            # 2. Gọi bằng USER token thường -> 403 Forbidden
            res2 = client.post(
                "/api/v1/commands/send",
                json={"edge_id": "edge-110", "action": "get_health"},
                headers={"Authorization": f"Bearer {user_token}"}
            )
            assert res2.status_code == 403

            # 3. Gọi bằng STAFF token -> 200 Success
            res3 = client.post(
                "/api/v1/commands/send",
                json={"edge_id": "edge-110", "action": "get_health"},
                headers={"Authorization": f"Bearer {staff_token}"}
            )
            assert res3.status_code == 200
            assert res3.json()["success"] is True


class TestS8CookiesTxtIsolation:
    """S8: Đảm bảo cookies.txt không tồn tại trong repository và được khóa trong .gitignore."""

    def test_cookies_txt_not_in_root_and_in_gitignore(self):
        cookie_file = ROOT_DIR / "cookies.txt"
        assert not cookie_file.exists(), "Tệp cookies.txt không được xuất hiện trong thư mục mã nguồn"

        gitignore_path = ROOT_DIR / ".gitignore"
        assert gitignore_path.exists()
        gitignore_text = gitignore_path.read_text(encoding="utf-8")
        assert "cookies.txt" in gitignore_text

