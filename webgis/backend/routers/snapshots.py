import json
import os
import uuid
import aiofiles
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, Form, Header, Request, HTTPException, Query
from services.data_store import store
from services.websocket_manager import ws_manager

router = APIRouter(prefix="/api/v1", tags=["Snapshots & Camera Capture"])

# Thư mục lưu trữ ảnh snapshots tĩnh
BASE_BACKEND_DIR = Path(__file__).resolve().parent.parent
SNAPSHOTS_STORAGE_DIR = BASE_BACKEND_DIR / "data" / "snapshots"
SNAPSHOTS_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


async def _handle_snapshot_upload(
    request: Request,
    image: Optional[UploadFile] = None,
    snapshot: Optional[UploadFile] = None,
    file: Optional[UploadFile] = None,
    edge_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    segment_id: Optional[str] = None,
    traffic_status: Optional[str] = None,
    metrics: Optional[str] = None,
    trigger_reason: Optional[str] = None,
    authorization: Optional[str] = None,
    x_edge_token: Optional[str] = None,
):
    upload_file = image or snapshot or file
    if not upload_file:
        raise HTTPException(status_code=400, detail="Missing image file in multipart upload (expected key 'image', 'snapshot', or 'file')")

    target_edge_id = edge_id or request.headers.get("X-Edge-ID") or "edge-01"
    
    # Đọc metrics JSON nếu có
    parsed_metrics = {}
    if metrics:
        try:
            parsed_metrics = json.loads(metrics) if isinstance(metrics, str) else metrics
        except Exception:
            pass

    # Tạo tên file độc nhất: {edge_id}_{uuid}.jpg
    filename = f"{target_edge_id}_{uuid.uuid4().hex[:8]}.jpg"
    dest_path = SNAPSHOTS_STORAGE_DIR / filename

    # Ghi file bất đồng bộ bằng aiofiles
    content = await upload_file.read()
    async with aiofiles.open(dest_path, "wb") as out_file:
        await out_file.write(content)

    snapshot_url = f"/snapshots/{filename}"
    now = datetime.now()

    # Cập nhật snapshot_url vào Node trong DataStore
    node = store.get_node(target_edge_id)
    resolved_status = traffic_status or parsed_metrics.get("traffic_status") or (node.get("traffic_status") if node else "FREE")
    resolved_score = parsed_metrics.get("congestion_score") or (node.get("congestion_score") if node else 0)
    resolved_speed = parsed_metrics.get("avg_speed_kmh") or (node.get("avg_speed_kmh") if node else 0.0)
    resolved_count = parsed_metrics.get("current_vehicle_count") or (node.get("current_vehicle_count") if node else 0)

    store.update_node_snapshot(target_edge_id, snapshot_url)

    # Lưu bản ghi snapshot vào lịch sử
    record = {
        "snapshot_id": f"snap-{uuid.uuid4().hex[:8]}",
        "edge_id": target_edge_id,
        "camera_id": camera_id or (node.get("camera_id") if node else "camera-01"),
        "segment_id": segment_id or (node.get("segment_id") if node else "segment-001"),
        "timestamp": now.isoformat(),
        "time_str": now.strftime("%H:%M:%S"),
        "location_name": node.get("name") if node else "Đường Nguyễn Trãi",
        "traffic_status": resolved_status,
        "congestion_score": resolved_score,
        "avg_speed_kmh": resolved_speed,
        "vehicle_count": resolved_count,
        "image_url": snapshot_url,
        "trigger_reason": trigger_reason or ("auto_congestion_detected" if resolved_status == "CONGESTED" else "manual_request")
    }
    store.add_snapshot_record(record)

    # Broadcast sự kiện snapshot_updated qua WebSocket cho tất cả WebGIS client
    await ws_manager.broadcast({
        "type": "snapshot_updated",
        "edge_id": target_edge_id,
        "snapshot_url": snapshot_url,
        "traffic_status": resolved_status,
        "trigger_reason": record["trigger_reason"],
        "timestamp": now.isoformat()
    })

    print(f"[SNAPSHOT] Received & saved snapshot for {target_edge_id} -> {snapshot_url} ({len(content)} bytes)")

    return {
        "success": True,
        "status": "success",
        "message": "Snapshot saved and broadcasted successfully",
        "edge_id": target_edge_id,
        "snapshot_url": snapshot_url,
        "record": record
    }


# Hỗ trợ cả 2 endpoint upload: POST /api/v1/congestion-events/snapshot và POST /api/v1/snapshots
@router.post("/congestion-events/snapshot")
async def upload_congestion_event_snapshot(
    request: Request,
    image: Optional[UploadFile] = File(None),
    snapshot: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    edge_id: Optional[str] = Form(None),
    camera_id: Optional[str] = Form(None),
    segment_id: Optional[str] = Form(None),
    traffic_status: Optional[str] = Form(None),
    metrics: Optional[str] = Form(None),
    trigger_reason: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None),
    x_edge_token: Optional[str] = Header(None, alias="X-Edge-Token"),
):
    return await _handle_snapshot_upload(
        request, image, snapshot, file, edge_id, camera_id, segment_id,
        traffic_status, metrics, trigger_reason, authorization, x_edge_token
    )


@router.post("/snapshots")
async def upload_snapshot_generic(
    request: Request,
    image: Optional[UploadFile] = File(None),
    snapshot: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    edge_id: Optional[str] = Form(None),
    camera_id: Optional[str] = Form(None),
    segment_id: Optional[str] = Form(None),
    traffic_status: Optional[str] = Form(None),
    metrics: Optional[str] = Form(None),
    trigger_reason: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None),
    x_edge_token: Optional[str] = Header(None, alias="X-Edge-Token"),
):
    return await _handle_snapshot_upload(
        request, image, snapshot, file, edge_id, camera_id, segment_id,
        traffic_status, metrics, trigger_reason, authorization, x_edge_token
    )


@router.get("/snapshots")
def list_snapshots(
    segment_id: Optional[str] = Query(None),
    edge_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100)
):
    """Lấy danh sách các ảnh chụp snapshot đã lưu."""
    results = store.history_snapshots
    if segment_id:
        results = [s for s in results if s.get("segment_id") == segment_id]
    if edge_id:
        results = [s for s in results if s.get("edge_id") == edge_id]
    return results[:limit]
