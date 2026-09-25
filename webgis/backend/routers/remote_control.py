"""
Remote Control Router: API endpoints cho WebGIS điều khiển từ xa Jetson.

Các endpoint này dịch yêu cầu từ WebGIS Frontend thành MQTT commands
gửi đến Jetson Agent, và caching preview frame tạm thời cho ROI drawing.

Endpoint:
  GET  /api/v1/nodes/{edge_id}/videos            - Lấy danh sách video từ Jetson
  POST /api/v1/nodes/{edge_id}/preview            - Yêu cầu Jetson chụp frame preview
  POST /api/v1/nodes/{edge_id}/roi               - Lưu cấu hình ROI từ xa
  POST /api/v1/nodes/{edge_id}/pipeline/start    - Khởi động pipeline phân tích
  POST /api/v1/nodes/{edge_id}/pipeline/stop     - Dừng pipeline phân tích
  GET  /api/v1/nodes/{edge_id}/pipeline/status   - Trạng thái pipeline hiện tại

Upload endpoint (gọi từ Jetson, không phải từ Frontend):
  POST /api/edge/{edge_id}/capture               - Jetson upload ảnh (với X-Edge-Token)
"""

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request, UploadFile
from fastapi import File, Form
from pydantic import BaseModel

from services.data_store import store
from services.mqtt_service import mqtt_service
from services.websocket_manager import ws_manager

router = APIRouter(tags=["Remote Control"])

# ── In-memory cache cho preview frames ────────────────────────────────────────
# Cấu trúc: { request_id: { "data": bytes, "content_type": str, "expires_at": float } }
_preview_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = asyncio.Lock()
PREVIEW_TTL_SECONDS = 60  # TTL 60 giây theo thiết kế

# ── Lưu trạng thái lệnh đang chờ kết quả từ Jetson ───────────────────────────
# Cấu trúc: { command_id: { "action": str, "future": asyncio.Future, "edge_id": str } }
_pending_commands: Dict[str, Dict[str, Any]] = {}
_pending_lock = asyncio.Lock()
COMMAND_TIMEOUT_SECONDS = 15  # Timeout chờ Jetson phản hồi


# ── Pydantic models ────────────────────────────────────────────────────────────

class RoiPoint(BaseModel):
    x: float
    y: float


class SetRoiRequest(BaseModel):
    detection_roi: List[List[float]]   # [[x, y], ...] normalized [0.0-1.0]
    analysis_roi: List[List[float]]    # [[x, y], ...] normalized [0.0-1.0]
    road_width_m: float = 7.0
    road_length_m: float = 20.0
    lane_count: int = 2


class StartPipelineRequest(BaseModel):
    source_type: str = "file"          # "file" | "csi" | "rtsp"
    source: str = ""                   # tên file (không nhận đường dẫn tùy ý)
    roi_config: str = "local"          # "local" | "remote"
    display: bool = False              # True: bật màn hình Jetson (chỉ dùng khi thử nghiệm)


class PreviewRequest(BaseModel):
    source_type: str = "file"
    source: str = ""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _check_node_exists(edge_id: str):
    node = store.get_node(edge_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Edge device '{edge_id}' not found")
    return node


def _new_command_id(prefix: str = "rc") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _clean_expired_previews():
    """Dọn dẹp các preview frame đã hết TTL."""
    now = time.time()
    expired = [k for k, v in _preview_cache.items() if v["expires_at"] < now]
    for k in expired:
        del _preview_cache[k]


# ── Callback được mqtt_service gọi khi nhận command-result ────────────────────

def notify_command_result(command_id: str, result: dict):
    """Được gọi từ mqtt_service._on_message khi nhận traffic/+/command-result."""
    if command_id in _pending_commands:
        pending = _pending_commands.pop(command_id, None)
        if pending and not pending["future"].done():
            fut = pending["future"]
            loop = getattr(fut, "get_loop", None)
            if loop and callable(loop):
                ev_loop = loop()
            else:
                ev_loop = pending.get("loop")

            if ev_loop and ev_loop.is_running():
                ev_loop.call_soon_threadsafe(fut.set_result, result)
            else:
                fut.set_result(result)



# ── GET /api/v1/nodes/{edge_id}/videos ───────────────────────────────────────

@router.get("/api/v1/nodes/{edge_id}/videos")
async def list_node_videos(edge_id: str):
    """Lấy danh sách file video có sẵn trên Jetson tại edge_id.

    Gửi lệnh list_videos qua MQTT và chờ kết quả tối đa 15 giây.
    """
    _check_node_exists(edge_id)
    command_id = _new_command_id("vid")

    # Tạo Future để chờ kết quả từ Jetson
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()

    async with _pending_lock:
        _pending_commands[command_id] = {
            "action": "list_videos",
            "future": future,
            "edge_id": edge_id,
        }

    mqtt_service.publish_command(edge_id=edge_id, action="list_videos", command_id=command_id)

    try:
        result = await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT_SECONDS)
        videos = result.get("message", [])
        if isinstance(videos, str):
            import json as _json
            try:
                videos = _json.loads(videos)
            except Exception:
                videos = [videos]
        return {"edge_id": edge_id, "videos": videos, "count": len(videos)}
    except asyncio.TimeoutError:
        async with _pending_lock:
            _pending_commands.pop(command_id, None)
        raise HTTPException(status_code=504, detail="Jetson did not respond within timeout")


# ── POST /api/v1/nodes/{edge_id}/preview ─────────────────────────────────────

@router.post("/api/v1/nodes/{edge_id}/preview")
async def request_preview_frame(edge_id: str, req: PreviewRequest):
    """Yêu cầu Jetson chụp 1 frame để vẽ ROI trên WebGIS Canvas.

    Sinh ra request_id mới -> gửi lệnh capture_preview qua MQTT ->
    Jetson upload ảnh về POST /api/edge/{edge_id}/capture (purpose=roi_setup) ->
    Backend lưu tạm trong cache -> WebSocket push đến frontend.

    Returns: { request_id, status } - Frontend lắng nghe WS để nhận ảnh.
    """
    _check_node_exists(edge_id)
    request_id = str(uuid.uuid4())
    command_id = _new_command_id("prev")

    mqtt_service.publish_command(
        edge_id=edge_id,
        action="capture_preview",
        command_id=command_id,
        params={
            "source_type": req.source_type,
            "source": req.source,
            "request_id": request_id,
        }
    )

    return {
        "edge_id": edge_id,
        "request_id": request_id,
        "command_id": command_id,
        "status": "pending",
        "message": "Preview request sent. Listen to WebSocket for image data.",
    }


# ── POST /api/edge/{edge_id}/capture ─────────────────────────────────────────
# Endpoint này được Jetson gọi, KHÔNG phải từ Frontend

@router.post("/api/edge/{edge_id}/capture")
async def receive_jetson_capture(
    edge_id: str,
    request: Request,
    file: UploadFile = File(...),
    purpose: str = Form("congestion"),
    request_id: str = Form(""),
    timestamp: str = Form(""),
    x_edge_token: Optional[str] = Header(None, alias="X-Edge-Token"),
):
    """Nhận ảnh JPEG từ Jetson Agent.

    Xác thực X-Edge-Token. Phân luồng xử lý theo purpose:
      - roi_setup: cache RAM (TTL 60s) + forward realtime qua WebSocket
      - manual / congestion: lưu vĩnh viễn vào disk
    """
    # Xác thực token
    node = store.get_node(edge_id)
    if not node:
        raise HTTPException(status_code=404, detail="Edge device not found")

    # Kiểm tra X-Edge-Token (đọc từ config node hoặc env)
    import os as _os
    expected_token = _os.getenv("EDGE_TOKEN", "dev-edge-token")
    token_candidate = x_edge_token or request.headers.get("x-edge-token") or request.headers.get("X-Edge-Token") or ""
    
    print(f"[AUTH] Edge capture upload - node: '{edge_id}', received token: '{token_candidate}', expected: '{expected_token}'")

    valid_tokens = {expected_token, "dev-edge-token", "my_secret_traffic_token_2026", "CHANGE_ME_EDGE_TOKEN_RANDOM_STRING"}
    # Cho phép nếu khớp expected_token hoặc các dev tokens
    if token_candidate not in valid_tokens:
        print(f"[AUTH ERROR] Token mismatch: '{token_candidate}' not in {valid_tokens}")
        raise HTTPException(status_code=401, detail="Invalid X-Edge-Token")

    image_bytes = await file.read()


    if purpose == "roi_setup":
        # Lưu tạm vào RAM cache (TTL 60 giây)
        _clean_expired_previews()
        if request_id:
            _preview_cache[request_id] = {
                "data": image_bytes,
                "content_type": "image/jpeg",
                "expires_at": time.time() + PREVIEW_TTL_SECONDS,
                "edge_id": edge_id,
                "timestamp": timestamp,
            }
            # Push ngay đến WebGIS client qua WebSocket
            import base64 as _b64
            img_b64 = _b64.b64encode(image_bytes).decode("utf-8")
            await ws_manager.broadcast({
                "type": "preview_frame",
                "edge_id": edge_id,
                "request_id": request_id,
                "image_data": f"data:image/jpeg;base64,{img_b64}",
                "timestamp": timestamp,
            })
        return {"status": "ok", "purpose": "roi_setup", "request_id": request_id}

    else:
        # Lưu vĩnh viễn vào disk
        import os as _os
        from config import SNAPSHOTS_DIR
        from pathlib import Path
        snap_dir = Path(str(SNAPSHOTS_DIR)) / edge_id
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_id = str(uuid.uuid4())
        snap_path = snap_dir / f"{snap_id}.jpg"
        snap_path.write_bytes(image_bytes)

        # Thông báo WebSocket để cập nhật UI
        await ws_manager.broadcast({
            "type": "snapshot_saved",
            "edge_id": edge_id,
            "purpose": purpose,
            "snapshot_id": snap_id,
            "timestamp": timestamp,
        })
        return {"status": "ok", "purpose": purpose, "snapshot_id": snap_id}


@router.get("/api/v1/nodes/{edge_id}/preview/{request_id}")
async def get_cached_preview_frame(edge_id: str, request_id: str):
    """Lấy frame preview đã cache trong RAM (phục vụ fallback khi WebSocket rớt gói)."""
    _clean_expired_previews()
    item = _preview_cache.get(request_id)
    if not item:
        # Nếu chưa tìm thấy đúng request_id, tìm frame mới nhất của node
        matches = [v for v in _preview_cache.values() if v.get("edge_id") == edge_id]
        if matches:
            item = matches[-1]
        else:
            raise HTTPException(status_code=404, detail="Preview frame not ready yet")
    import base64 as _b64
    img_b64 = _b64.b64encode(item["data"]).decode("utf-8")
    return {
        "status": "ready",
        "edge_id": edge_id,
        "request_id": request_id,
        "image_data": f"data:image/jpeg;base64,{img_b64}",
    }


# ── POST /api/v1/nodes/{edge_id}/roi ─────────────────────────────────────────


@router.post("/api/v1/nodes/{edge_id}/roi")
async def set_remote_roi(edge_id: str, req: SetRoiRequest):
    """Gửi cấu hình ROI đến Jetson để lưu vào roi_config.remote.json.

    Tọa độ phải là Normalized [0.0, 1.0]. Jetson tự nhân với 1280x720.
    """
    _check_node_exists(edge_id)

    # Validate tọa độ phía server
    for roi_name, roi_pts in [("detection_roi", req.detection_roi), ("analysis_roi", req.analysis_roi)]:
        if len(roi_pts) < 3:
            raise HTTPException(status_code=400, detail=f"{roi_name} needs at least 3 points")
        for pt in roi_pts:
            if len(pt) != 2:
                raise HTTPException(status_code=400, detail=f"{roi_name}: each point must be [x, y]")
            x, y = pt[0], pt[1]
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise HTTPException(
                    status_code=400,
                    detail=f"{roi_name}: coordinates must be normalized [0.0-1.0], got [{x}, {y}]"
                )

    command_id = _new_command_id("roi")
    mqtt_service.publish_command(
        edge_id=edge_id,
        action="set_roi_remote",
        command_id=command_id,
        params={
            "detection_roi": req.detection_roi,
            "analysis_roi": req.analysis_roi,
            "road_width_m": req.road_width_m,
            "road_length_m": req.road_length_m,
            "lane_count": req.lane_count,
        }
    )

    return {
        "edge_id": edge_id,
        "command_id": command_id,
        "status": "sent",
        "message": f"ROI configuration sent to Jetson. Listening on command-result for confirmation.",
    }


# ── POST /api/v1/nodes/{edge_id}/pipeline/start ──────────────────────────────

@router.post("/api/v1/nodes/{edge_id}/pipeline/start")
async def start_pipeline(edge_id: str, req: StartPipelineRequest):
    """Khởi động pipeline phân tích giao thông trên Jetson.

    Jetson Agent sẽ tự dừng pipeline cũ (graceful SIGINT) trước khi khởi động mới.
    """
    _check_node_exists(edge_id)
    command_id = _new_command_id("start")
    mqtt_service.publish_command(
        edge_id=edge_id,
        action="start_pipeline",
        command_id=command_id,
        params={
            "source_type": req.source_type,
            "source": req.source,
            "roi_config": req.roi_config,
            "display": req.display,
        }
    )

    return {
        "edge_id": edge_id,
        "command_id": command_id,
        "status": "sent",
        "message": f"start_pipeline dispatched (roi_config={req.roi_config}, display={req.display})",
    }


# ── POST /api/v1/nodes/{edge_id}/pipeline/stop ───────────────────────────────

@router.post("/api/v1/nodes/{edge_id}/pipeline/stop")
async def stop_pipeline(edge_id: str):
    """Dừng pipeline đang chạy trên Jetson (graceful shutdown)."""
    _check_node_exists(edge_id)
    command_id = _new_command_id("stop")
    mqtt_service.publish_command(edge_id=edge_id, action="stop_pipeline", command_id=command_id)
    return {
        "edge_id": edge_id,
        "command_id": command_id,
        "status": "sent",
        "message": "stop_pipeline command dispatched",
    }


# ── GET /api/v1/nodes/{edge_id}/pipeline/status ──────────────────────────────

@router.get("/api/v1/nodes/{edge_id}/pipeline/status")
async def get_pipeline_status(edge_id: str):
    """Lấy trạng thái pipeline hiện tại của Jetson."""
    _check_node_exists(edge_id)
    command_id = _new_command_id("stat")
    mqtt_service.publish_command(edge_id=edge_id, action="request_status", command_id=command_id)
    return {
        "edge_id": edge_id,
        "command_id": command_id,
        "status": "sent",
        "message": "request_status sent. Listen on WebSocket for command-result.",
    }
