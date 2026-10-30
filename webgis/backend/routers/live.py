"""
Live Streaming Router:
Quản lý luồng phát trực tiếp On-Demand camera CSI từ Jetson Nano qua MediaMTX (WebRTC / WHEP / HLS).
"""

import asyncio
import logging
import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from services.auth_middleware import require_staff

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


def _build_stream_urls(edge_id: str, request: Optional[Request] = None) -> dict:
    """Tự động suy ra URL phát trực tiếp (WebRTC / HLS / RTSP).
    
    Fix V6: Tự động nhận diện hostname của client thay vì gán chết IP LAN 192.168.88.193.
    Hỗ trợ chuyển đổi HTTP/HTTPS chống chặn mixed content và hỗ trợ URL cloud/domain reverse proxy.
    """
    host_env = os.getenv("MEDIAMTX_HOST", "").strip()

    client_host = None
    client_scheme = "http"
    if request:
        client_host = request.url.hostname
        # Nhận diện scheme HTTPS khi đứng sau Reverse Proxy (Nginx/Cloudflare)
        proto_hdr = request.headers.get("x-forwarded-proto") or request.url.scheme
        if proto_hdr:
            client_scheme = proto_hdr.lower()

    if client_host and client_host not in ("localhost", "127.0.0.1"):
        chosen_host = client_host
    elif host_env and host_env not in ("localhost", "127.0.0.1", ""):
        chosen_host = host_env
    else:
        chosen_host = host_env or client_host or "localhost"

    webrtc_base = os.getenv("MEDIAMTX_PUBLIC_WEBRTC_URL", f"{client_scheme}://{chosen_host}:{MEDIAMTX_WEBRTC_PORT}").rstrip("/")
    hls_base = os.getenv("MEDIAMTX_PUBLIC_HLS_URL", f"{client_scheme}://{chosen_host}:{MEDIAMTX_HLS_PORT}").rstrip("/")

    # Host mà Jetson Nano đẩy luồng RTSP về:
    ingest_host = os.getenv("MEDIAMTX_INGEST_HOST", chosen_host)
    rtsp_base = os.getenv("MEDIAMTX_PUBLIC_RTSP_URL", f"rtsp://{ingest_host}:{MEDIAMTX_RTSP_PORT}").rstrip("/")

    return {
        "webrtc_url": f"{webrtc_base}/live/{edge_id}/",
        "whep_url": f"{webrtc_base}/live/{edge_id}/whep",
        "hls_url": f"{hls_base}/live/{edge_id}/index.m3u8",
        "rtsp_url": f"{rtsp_base}/live/{edge_id}",
    }


async def _send_live_mqtt_command(edge_id: str, action: str, params: Optional[dict] = None, timeout_s: float = 8.0) -> dict:
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


@router.post("/api/v1/devices/{edge_id}/live/start", dependencies=[Depends(require_staff)])
@router.post("/api/v1/nodes/{edge_id}/live/start", dependencies=[Depends(require_staff)])
async def start_device_live(edge_id: str, request: Request):
    """Bật luồng phát trực tiếp camera CSI từ Jetson Nano lên MediaMTX (On-Demand - Yêu cầu Staff)."""
    node = store.get_node(edge_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Thiết bị '{edge_id}' không tồn tại")

    # Chỉ cho phép bật Live Stream khi AI Pipeline trên Jetson đang chạy (Online)
    is_online = node.get("status") == "online"
    if not is_online:
        raise HTTPException(
            status_code=400,
            detail="AI Pipeline chưa khởi động trên Jetson (Camera đang tự do để setup ROI). Hãy chạy main.py trước khi xem Live Cam."
        )

    urls = _build_stream_urls(edge_id, request=request)
    try:
        # Fix V6: Gửi kèm địa chỉ RTSP ingest URL qua MQTT để Jetson tự nhận diện máy chủ MediaMTX
        res = await _send_live_mqtt_command(
            edge_id=edge_id,
            action="start_live",
            params={"rtsp_url": urls["rtsp_url"]},
            timeout_s=8.0
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


@router.post("/api/v1/devices/{edge_id}/live/stop", dependencies=[Depends(require_staff)])
@router.post("/api/v1/nodes/{edge_id}/live/stop", dependencies=[Depends(require_staff)])
async def stop_device_live(edge_id: str):
    """Dừng luồng phát trực tiếp camera CSI trên Jetson Nano (Yêu cầu Staff)."""
    node = store.get_node(edge_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Thiết bị '{edge_id}' không tồn tại")

    try:
        res = await _send_live_mqtt_command(edge_id, "stop_live", timeout_s=8.0)
        return {
            "edge_id": edge_id,
            "status": "stopped",
            "message": "Đã tắt luồng camera CSI trên Jetson",
            "details": res.get("message", {})
        }
    except Exception as e:
        logger.warning("Error stopping live on %s: %s", edge_id, e)
        return {"edge_id": edge_id, "status": "stopped", "message": str(e)}


@router.post("/api/v1/devices/{edge_id}/live/keepalive", dependencies=[Depends(require_staff)])
@router.post("/api/v1/nodes/{edge_id}/live/keepalive", dependencies=[Depends(require_staff)])
async def keepalive_device_live(edge_id: str):
    """Gửi ping keep-alive định kỳ từ người xem WebGIS để duy trì luồng (Yêu cầu Staff)."""
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

    urls = _build_stream_urls(edge_id, request=request)
    return {
        "edge_id": edge_id,
        "device_name": node.get("device_name", edge_id),
        "status": node.get("status", "unknown"),
        **urls
    }

