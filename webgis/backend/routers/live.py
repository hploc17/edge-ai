"""
Live Streaming Router:
Quản lý luồng phát trực tiếp On-Demand camera CSI từ Jetson Nano qua MediaMTX (WebRTC / WHEP / HLS).
"""

import asyncio
import logging
import os
import socket
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Security
from fastapi.responses import JSONResponse
from services.auth_middleware import require_staff, security_bearer

try:
    from config import LIVE_REQUIRE_AUTH
except ImportError:
    LIVE_REQUIRE_AUTH = os.getenv("LIVE_REQUIRE_AUTH", "false").lower() in ("true", "1", "yes")

async def require_live_access(credentials = Security(security_bearer)):
    """Kiểm tra quyền bật/tắt luồng camera. Nếu LIVE_REQUIRE_AUTH=False thì cho phép truy cập mở."""
    if not LIVE_REQUIRE_AUTH:
        return {"userId": "guest", "role": "GUEST"}
    return require_staff(credentials)

try:
    from services.data_store import store
except ImportError:
    try:
        from webgis.backend.services.data_store import store
    except ImportError:
        store = None

logger = logging.getLogger("LiveRouter")

router = APIRouter(tags=["Live Video Streaming"])

MEDIAMTX_HOST = os.getenv("MEDIAMTX_HOST", "")
MEDIAMTX_WEBRTC_PORT = int(os.getenv("MEDIAMTX_WEBRTC_PORT", "8889"))
MEDIAMTX_HLS_PORT = int(os.getenv("MEDIAMTX_HLS_PORT", "8888"))
MEDIAMTX_RTSP_PORT = int(os.getenv("MEDIAMTX_RTSP_PORT", "8554"))


def get_local_lan_ip() -> str:
    """Tự động phát hiện IP mạng LAN thực tế của máy chủ (dù dùng Wi-Fi, Ethernet, DHCP đổi IP)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _build_stream_urls(edge_id: str, request: Optional[Request] = None) -> dict:
    """Tự động suy ra URL phát trực tiếp (WebRTC / HLS / RTSP).
    
    Cơ chế tự động:
      - Phía Client xem (WebRTC / HLS): Tự động ưu tiên hostname mà trình duyệt đang truy cập (localhost, IP LAN, domain).
      - Phía Ingest Jetson (RTSP): Tự động phát hiện IP LAN thực tế của server để Jetson ngoài mạng LAN đẩy luồng về đúng chỗ.
    """
    server_lan_ip = get_local_lan_ip()
    host_env = os.getenv("MEDIAMTX_HOST", "").strip()

    client_host = None
    client_scheme = "http"
    if request:
        client_host = request.url.hostname
        proto_hdr = request.headers.get("x-forwarded-proto") or request.url.scheme
        if proto_hdr:
            client_scheme = proto_hdr.lower()

    # 1. Host cho trình duyệt xem WebRTC/HLS:
    # Nếu client truy cập qua domain / IP nào (kể cả localhost hay IP LAN), dùng chính hostname đó!
    if client_host and client_host not in ("", "0.0.0.0"):
        chosen_client_host = client_host
    elif server_lan_ip and server_lan_ip not in ("", "127.0.0.1"):
        chosen_client_host = server_lan_ip
    elif host_env and host_env not in ("", "0.0.0.0"):
        chosen_client_host = host_env
    else:
        chosen_client_host = "localhost"

    webrtc_base = os.getenv("MEDIAMTX_PUBLIC_WEBRTC_URL", f"{client_scheme}://{chosen_client_host}:{MEDIAMTX_WEBRTC_PORT}").rstrip("/")
    hls_base = os.getenv("MEDIAMTX_PUBLIC_HLS_URL", f"{client_scheme}://{chosen_client_host}:{MEDIAMTX_HLS_PORT}").rstrip("/")

    # 2. Host cho Jetson Nano đẩy RTSP về MediaMTX:
    # Jetson là thiết bị biên riêng biệt trong mạng LAN, BẮT BUỘC dùng IP LAN thực tế của máy chủ!
    ingest_env = os.getenv("MEDIAMTX_INGEST_HOST", "").strip()
    if ingest_env and ingest_env not in ("localhost", "127.0.0.1", ""):
        ingest_host = ingest_env
    elif server_lan_ip and server_lan_ip not in ("localhost", "127.0.0.1", ""):
        ingest_host = server_lan_ip
    elif host_env and host_env not in ("localhost", "127.0.0.1", ""):
        ingest_host = host_env
    else:
        ingest_host = "localhost"

    rtsp_base = os.getenv("MEDIAMTX_PUBLIC_RTSP_URL", f"rtsp://{ingest_host}:{MEDIAMTX_RTSP_PORT}").rstrip("/")

    return {
        "webrtc_url": f"{webrtc_base}/live/{edge_id}/",
        "whep_url": f"{webrtc_base}/live/{edge_id}/whep",
        "hls_url": f"{hls_base}/live/{edge_id}/index.m3u8",
        "rtsp_url": f"{rtsp_base}/live/{edge_id}",
    }


async def _send_live_mqtt_command(edge_id: str, action: str, params: Optional[dict] = None, timeout_s: float = 30.0) -> dict:
    from routers.remote_control import _pending_commands, _pending_lock, _new_command_id
    from services.mqtt_service import mqtt_service

    command_id = _new_command_id("live")
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    async with _pending_lock:
        _pending_commands[command_id] = {
            "action": action,
            "future": future,
            "edge_id": edge_id,
            "loop": loop
        }

    sent = mqtt_service.publish_command(edge_id=edge_id, action=action, params=params or {}, command_id=command_id)
    if not sent:
        async with _pending_lock:
            _pending_commands.pop(command_id, None)
        raise HTTPException(status_code=502, detail=f"Không thể gửi lệnh MQTT '{action}' tới thiết bị Jetson")

    try:
        result = await asyncio.wait_for(future, timeout=timeout_s)
        return result
    except asyncio.TimeoutError:
        async with _pending_lock:
            _pending_commands.pop(command_id, None)
        raise HTTPException(
            status_code=504,
            detail=f"Quá thời gian ({timeout_s}s) chờ Jetson phản hồi '{action}'. Kiểm tra xem pipeline AI có đang chạy không."
        )


@router.post("/api/v1/devices/{edge_id}/live/start", dependencies=[Depends(require_live_access)])
@router.post("/api/v1/nodes/{edge_id}/live/start", dependencies=[Depends(require_live_access)])
async def start_device_live(edge_id: str, request: Request):
    """Bật luồng phát trực tiếp camera CSI từ Jetson Nano lên MediaMTX (On-Demand)."""
    node = store.get_node(edge_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Thiết bị '{edge_id}' không tồn tại")

    # Kiểm tra trạng thái thiết bị linh hoạt (tránh chặn nhầm khi có trễ mạng)
    is_active = (
        node.get("status") == "online" or
        node.get("pipeline_running", False) or
        node.get("data_status") in ("live", "stale")
    )
    if not is_active:
        logger.warning(f"Node '{edge_id}' đang ở trạng thái '{node.get('status')}'. Vẫn thử gửi lệnh start_live qua MQTT...")

    # Mã Web là chuẩn; chỉ dùng mã phần cứng khi thiết bị đang lệch mã (chưa đổi xong)
    stream_edge_id = node.get("actual_hardware_id") if (node.get("id_mismatch") and node.get("actual_hardware_id")) else edge_id
    urls = _build_stream_urls(stream_edge_id, request=request)
    try:
        # Fix V6: Gửi kèm địa chỉ RTSP ingest URL qua MQTT để Jetson tự nhận diện máy chủ MediaMTX (timeout 30s)
        res = await _send_live_mqtt_command(
            edge_id=edge_id,
            action="start_live",
            params={"rtsp_url": urls["rtsp_url"]},
            timeout_s=30.0
        )
        if res.get("status") in ("error", "failed", "rejected"):
            err_msg = res.get("message") or "LiveStreamController chưa sẵn sàng"
            raise HTTPException(status_code=500, detail=f"Jetson báo lỗi: {err_msg}")
        return {
            "edge_id": edge_id,
            "status": "started",
            "message": "Đã kích hoạt luồng camera CSI trên Jetson",
            "details": res.get("message", {}),
            **urls
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/devices/{edge_id}/live/stop", dependencies=[Depends(require_live_access)])
@router.post("/api/v1/nodes/{edge_id}/live/stop", dependencies=[Depends(require_live_access)])
async def stop_device_live(edge_id: str):
    """Dừng luồng phát trực tiếp camera CSI trên Jetson Nano."""
    node = store.get_node(edge_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Thiết bị '{edge_id}' không tồn tại")

    try:
        res = await _send_live_mqtt_command(edge_id, "stop_live", timeout_s=15.0)
        return {
            "edge_id": edge_id,
            "status": "stopped",
            "message": "Đã tắt luồng camera CSI trên Jetson",
            "details": res.get("message", {})
        }
    except Exception as e:
        logger.warning("Error stopping live on %s: %s", edge_id, e)
        return {"edge_id": edge_id, "status": "stopped", "message": str(e)}


@router.post("/api/v1/devices/{edge_id}/live/keepalive", dependencies=[Depends(require_live_access)])
@router.post("/api/v1/nodes/{edge_id}/live/keepalive", dependencies=[Depends(require_live_access)])
async def keepalive_device_live(edge_id: str):
    """Gửi ping keep-alive định kỳ từ người xem WebGIS để duy trì luồng."""
    from services.mqtt_service import mqtt_service
    from routers.remote_control import _new_command_id

    cmd_id = _new_command_id("ping")
    mqtt_service.publish_command(edge_id=edge_id, action="live_keepalive", command_id=cmd_id)
    return {"edge_id": edge_id, "status": "ok"}


@router.get("/api/v1/devices/{edge_id}/live")
@router.get("/api/v1/nodes/{edge_id}/live")
async def get_device_live_info(edge_id: str, request: Request):
    """Lấy thông tin và URL xem trực tiếp (WebRTC / HLS) của node camera."""
    node = store.get_node(edge_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Thiết bị '{edge_id}' không tồn tại")

    # Mã Web là chuẩn; chỉ dùng mã phần cứng khi thiết bị đang lệch mã (chưa đổi xong)
    stream_edge_id = node.get("actual_hardware_id") if (node.get("id_mismatch") and node.get("actual_hardware_id")) else edge_id
    urls = _build_stream_urls(stream_edge_id, request=request)
    return {
        "edge_id": edge_id,
        "device_name": node.get("device_name", edge_id),
        "status": node.get("status", "unknown"),
        **urls
    }

