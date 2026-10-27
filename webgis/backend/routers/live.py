"""
Live Streaming Router:
1. Ingest Endpoint (Jetson -> Backend): WS /ws/ingest/{edge_id}
2. Viewer Endpoint (Backend -> WebGIS Client): WS /ws/live/{edge_id}
3. REST Endpoint: GET /api/v1/live/{edge_id}/status
"""

import asyncio
import json
import logging
import os
import time
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Header, HTTPException, status
from fastapi.responses import JSONResponse

from config import EDGE_TOKEN, LIVE_REQUIRE_AUTH
from services.live_stream_manager import live_stream_manager
from services.data_store import store

logger = logging.getLogger("LiveRouter")

router = APIRouter(tags=["Live Video Streaming"])

VALID_TOKENS = {
    EDGE_TOKEN,
    "dev-edge-token",
    "my_secret_traffic_token_2026",
    "CHANGE_ME_EDGE_TOKEN_RANDOM_STRING"
}


MEDIAMTX_HOST = os.getenv("MEDIAMTX_HOST", "192.168.88.193")
MEDIAMTX_WEBRTC_PORT = int(os.getenv("MEDIAMTX_WEBRTC_PORT", "8889"))
MEDIAMTX_HLS_PORT = int(os.getenv("MEDIAMTX_HLS_PORT", "8888"))
MEDIAMTX_RTSP_PORT = int(os.getenv("MEDIAMTX_RTSP_PORT", "8554"))


def _build_stream_urls(edge_id: str) -> dict:
    host = os.getenv("MEDIAMTX_HOST", "192.168.88.193")
    webrtc_base = os.getenv("MEDIAMTX_PUBLIC_WEBRTC_URL", f"http://{host}:{MEDIAMTX_WEBRTC_PORT}").rstrip("/")
    hls_base = os.getenv("MEDIAMTX_PUBLIC_HLS_URL", f"http://{host}:{MEDIAMTX_HLS_PORT}").rstrip("/")
    rtsp_base = os.getenv("MEDIAMTX_PUBLIC_RTSP_URL", f"rtsp://{host}:{MEDIAMTX_RTSP_PORT}").rstrip("/")

    return {
        "webrtc_url": f"{webrtc_base}/live/{edge_id}/",
        "whep_url": f"{webrtc_base}/live/{edge_id}/whep",
        "hls_url": f"{hls_base}/live/{edge_id}/index.m3u8",
        "rtsp_url": f"{rtsp_base}/live/{edge_id}",
    }


async def _send_live_mqtt_command(edge_id: str, action: str, timeout_s: float = 8.0) -> dict:
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

    sent = mqtt_service.publish_command(edge_id=edge_id, action=action, command_id=command_id)
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


@router.post("/api/v1/devices/{edge_id}/live/start")
@router.post("/api/v1/nodes/{edge_id}/live/start")
async def start_device_live(edge_id: str):
    """Bật luồng phát trực tiếp camera CSI từ Jetson Nano lên MediaMTX (On-Demand)."""
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

    urls = _build_stream_urls(edge_id)
    try:
        res = await _send_live_mqtt_command(edge_id, "start_live", timeout_s=8.0)
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


@router.post("/api/v1/devices/{edge_id}/live/stop")
@router.post("/api/v1/nodes/{edge_id}/live/stop")
async def stop_device_live(edge_id: str):
    """Dừng luồng phát trực tiếp camera CSI trên Jetson Nano."""
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


@router.post("/api/v1/devices/{edge_id}/live/keepalive")
@router.post("/api/v1/nodes/{edge_id}/live/keepalive")
async def keepalive_device_live(edge_id: str):
    """Gửi ping keep-alive định kỳ từ người xem WebGIS để duy trì luồng."""
    from services.mqtt_service import mqtt_service
    from routers.remote_control import _new_command_id

    cmd_id = _new_command_id("ping")
    mqtt_service.publish_command(edge_id=edge_id, action="live_keepalive", command_id=cmd_id)
    return {"edge_id": edge_id, "status": "ok"}


@router.get("/api/v1/devices/{edge_id}/live")
@router.get("/api/v1/nodes/{edge_id}/live")
async def get_device_live_info(edge_id: str):
    """Lấy thông tin và URL xem trực tiếp (WebRTC / HLS) của node camera."""
    node = store.get_node(edge_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Thiết bị '{edge_id}' không tồn tại")

    urls = _build_stream_urls(edge_id)
    return {
        "edge_id": edge_id,
        "device_name": node.get("device_name", edge_id),
        "status": node.get("status", "unknown"),
        **urls
    }


@router.get("/api/v1/live/{edge_id}/status")
async def get_live_status(edge_id: str):
    """Lấy trạng thái kết nối và người xem của camera live stream."""
    return JSONResponse(live_stream_manager.get_status(edge_id))


@router.websocket("/ws/ingest/{edge_id}")
async def websocket_ingest(
    websocket: WebSocket,
    edge_id: str,
    token: Optional[str] = Query(None)
):
    """
    WS Ingest từ Jetson Nano lên Backend:
    - Xác thực qua X-Edge-Token hoặc ?token=
    - Handshake đầu tiên: {"type": "hello", "edge_id": "...", "width": ..., "height": ..., "fps": ...}
    - Backend gửi {"type": "start", "fps": 10} khi có viewer, {"type": "stop"} khi hết viewer
    - Jetson bơm từng frame JPEG dạng binary bytes
    """
    # 1. Kiểm tra xác thực Token
    auth_header = websocket.headers.get("x-edge-token") or websocket.headers.get("X-Edge-Token")
    client_token = auth_header or token or ""

    if client_token not in VALID_TOKENS:
        logger.warning("[Ingest:%s] Rejected connection: Invalid token '%s'", edge_id, client_token)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized edge token")
        return

    await websocket.accept()
    logger.info("[Ingest:%s] Ingest connection accepted", edge_id)

    try:
        # 2. Chờ handshake hello message
        first_msg = await websocket.receive_text()
        try:
            hello_data = json.loads(first_msg)
            if hello_data.get("type") != "hello":
                raise ValueError("Expected type 'hello'")
        except Exception as e:
            logger.error("[Ingest:%s] Invalid handshake: %s", edge_id, e)
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid handshake")
            return

        # 3. Đăng ký Jetson vào LiveStreamManager
        await live_stream_manager.register_jetson(edge_id, websocket, hello_data)

        # 4. Vòng lặp nhận binary JPEG frame từ Jetson
        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"]:
                await live_stream_manager.receive_frame(edge_id, message["bytes"])
            elif "text" in message and message["text"]:
                try:
                    data = json.loads(message["text"])
                    if data.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                except Exception:
                    pass

    except WebSocketDisconnect:
        logger.info("[Ingest:%s] Jetson disconnected normally", edge_id)
    except Exception as e:
        logger.error("[Ingest:%s] Ingest error: %s", edge_id, e)
    finally:
        await live_stream_manager.unregister_jetson(edge_id, websocket)


@router.websocket("/ws/live/{edge_id}")
async def websocket_live_viewer(
    websocket: WebSocket,
    edge_id: str,
    token: Optional[str] = Query(None)
):
    """
    WS Live Viewer cho người dùng WebGIS:
    - Khi hover vào node camera, browser mở kết nối
    - Backend gửi trạng thái: {"type": "status", "state": "connecting|live|offline|stalled|full"}
    - Bơm trực tiếp binary JPEG theo cơ chế Zero-Queue
    """
    await websocket.accept()

    # 1. Đăng ký viewer
    success, reason = await live_stream_manager.add_viewer(edge_id, websocket)
    if not success:
        logger.warning("[LiveViewer:%s] Viewer rejected: %s", edge_id, reason)
        await websocket.send_text(json.dumps({
            "type": "status",
            "state": "full",
            "message": "Số lượng người xem đồng thời vượt quá giới hạn"
        }))
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Max viewers limit reached")
        return

    # 2. Gửi trạng thái ban đầu
    initial_status = live_stream_manager.get_status(edge_id)
    curr_state = initial_status["state"]
    if curr_state == "ready":
        curr_state = "connecting"
    await websocket.send_text(json.dumps({"type": "status", "state": curr_state}))

    # 3. Task nền phát hiện client browser đóng tab hoặc ngắt kết nối
    async def detect_disconnect():
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            pass

    disconnect_task = asyncio.create_task(detect_disconnect())

    stream = await live_stream_manager.get_or_create(edge_id)
    seen_seq = 0
    last_state_sent = curr_state

    try:
        while True:
            if disconnect_task.done():
                break

            # Chờ frame mới được notify từ Jetson qua asyncio.Condition
            async with stream.condition:
                try:
                    await asyncio.wait_for(stream.condition.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass

            # Ra ngoài khối condition lock để gửi qua mạng
            if not stream.jetson_ws:
                if last_state_sent != "offline":
                    await websocket.send_text(json.dumps({"type": "status", "state": "offline"}))
                    last_state_sent = "offline"
            elif stream.last_frame_time > 0 and (time.time() - stream.last_frame_time > 5.0):
                if last_state_sent != "stalled":
                    await websocket.send_text(json.dumps({"type": "status", "state": "stalled"}))
                    last_state_sent = "stalled"
            elif stream.latest_frame and stream.frame_seq > seen_seq:
                frame_bytes = stream.latest_frame
                seen_seq = stream.frame_seq
                if last_state_sent != "live":
                    await websocket.send_text(json.dumps({"type": "status", "state": "live"}))
                    last_state_sent = "live"
                await websocket.send_bytes(frame_bytes)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("[LiveViewer:%s] Viewer loop error: %s", edge_id, e)
    finally:
        disconnect_task.cancel()
        await live_stream_manager.remove_viewer(edge_id, websocket)
