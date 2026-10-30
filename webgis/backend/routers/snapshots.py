import hmac
import json
import os
import re
import uuid
import aiofiles
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, Form, Header, Request, HTTPException, Query, Depends
import jwt
from services.data_store import store
from services.websocket_manager import ws_manager
from services.auth_middleware import JWT_SECRET, JWT_ALGORITHM, STAFF, require_staff

router = APIRouter(prefix="/api/v1", tags=["Snapshots & Camera Capture"])

# Thư mục lưu trữ ảnh snapshots tĩnh
BASE_BACKEND_DIR = Path(__file__).resolve().parent.parent
SNAPSHOTS_STORAGE_DIR = BASE_BACKEND_DIR / "data" / "snapshots"
SNAPSHOTS_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Giới hạn kích thước tối đa của file ảnh tải lên: 10MB (Fix S4)
MAX_SNAPSHOT_SIZE = 10 * 1024 * 1024


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
    timestamp: Optional[str] = None,
    captured_at: Optional[str] = None,
):
    upload_file = image or snapshot or file
    if not upload_file:
        raise HTTPException(
            status_code=400,
            detail="Missing image file in multipart upload (expected key 'image', 'snapshot', or 'file')"
        )

    # 1. Xác thực nguồn upload (Fix S2, S3): Chỉ chấp nhận X-Edge-Token hợp lệ hoặc Staff Bearer JWT
    token_candidate = x_edge_token or request.headers.get("x-edge-token") or request.headers.get("X-Edge-Token")
    expected_token = os.getenv("EDGE_TOKEN", "dev-edge-token")

    is_authenticated = False
    if token_candidate:
        # So sánh hằng thời gian chống timing-attack (Fix S2)
        if hmac.compare_digest(token_candidate.strip().encode("utf-8"), expected_token.strip().encode("utf-8")):
            is_authenticated = True

    if not is_authenticated:
        auth_hdr = authorization or request.headers.get("authorization")
        if auth_hdr and auth_hdr.startswith("Bearer "):
            bearer_token = auth_hdr.split(" ")[1]
            try:
                payload = jwt.decode(bearer_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
                if payload.get("role") in STAFF:
                    is_authenticated = True
            except Exception:
                pass

    if not is_authenticated:
        raise HTTPException(
            status_code=401,
            detail="Xác thực thất bại: Yêu cầu X-Edge-Token hợp lệ từ thiết bị Edge hoặc Bearer Token từ Staff."
        )

    target_edge_id = edge_id or request.headers.get("X-Edge-ID") or "edge-01"

    # 2. Kiểm tra tính hợp lệ của edge_id (Chống Path Traversal - Fix S4)
    # Tuyệt đối từ chối các ký tự lạ, đường dẫn tương đối (../, ..\\)
    if not target_edge_id or not re.match(r"^[a-zA-Z0-9_-]+$", str(target_edge_id)):
        raise HTTPException(
            status_code=400,
            detail="Mã định danh edge_id không hợp lệ (chỉ chấp nhận chữ cái, số, gạch nối và gạch dưới)."
        )

    # 3. Đọc dữ liệu & Giới hạn dung lượng tối đa 10MB (Fix S4)
    content = await upload_file.read()
    if len(content) > MAX_SNAPSHOT_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Dung lượng tệp vượt quá giới hạn cho phép ({MAX_SNAPSHOT_SIZE // (1024*1024)}MB)."
        )

    # 4. Kiểm tra Magic Bytes chống tải lên file độc hại giả mạo đuôi ảnh (Fix S4)
    is_jpeg = content.startswith(b"\xff\xd8\xff")
    is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
    if not (is_jpeg or is_png):
        raise HTTPException(
            status_code=400,
            detail="Định dạng tệp không hợp lệ. Hệ thống chỉ chấp nhận dữ liệu nhị phân ảnh JPEG hoặc PNG thực thụ."
        )

    # Đọc metrics JSON nếu có
    parsed_metrics = {}
    if metrics:
        try:
            parsed_metrics = json.loads(metrics) if isinstance(metrics, str) else metrics
        except Exception:
            pass

    # Tạo tên file độc nhất bằng UUID an toàn: {edge_id}_{uuid}.jpg (Fix S4)
    filename = f"{target_edge_id}_{uuid.uuid4().hex[:8]}.jpg"
    dest_path = (SNAPSHOTS_STORAGE_DIR / filename).resolve()

    # Kiểm tra đường dẫn đích nằm tuyệt đối trong thư mục SNAPSHOTS_STORAGE_DIR
    if not dest_path.is_relative_to(SNAPSHOTS_STORAGE_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Đường dẫn lưu trữ tệp không an toàn.")

    # Ghi file bất đồng bộ bằng aiofiles
    async with aiofiles.open(dest_path, "wb") as out_file:
        await out_file.write(content)

    snapshot_url = f"/snapshots/{filename}"
    now = datetime.now()
    received_at = now.isoformat()

    # D3: Nhận và giữ chuẩn xác timestamp sự kiện thực tế từ Edge (captured_at hoặc timestamp)
    event_ts_raw = captured_at or timestamp
    if not event_ts_raw and parsed_metrics:
        event_ts_raw = parsed_metrics.get("timestamp") or parsed_metrics.get("captured_at")

    if event_ts_raw:
        try:
            if isinstance(event_ts_raw, (int, float)) or (isinstance(event_ts_raw, str) and event_ts_raw.replace('.', '', 1).isdigit()):
                dt_event = datetime.fromtimestamp(float(event_ts_raw))
                event_ts = dt_event.isoformat()
                time_str = dt_event.strftime("%H:%M:%S")
            else:
                clean_ts = str(event_ts_raw).replace("Z", "+00:00")
                dt_event = datetime.fromisoformat(clean_ts)
                event_ts = dt_event.isoformat()
                time_str = dt_event.strftime("%H:%M:%S")
        except Exception:
            event_ts = str(event_ts_raw)
            time_str = now.strftime("%H:%M:%S")
    else:
        event_ts = received_at
        time_str = now.strftime("%H:%M:%S")

    # Cập nhật snapshot_url vào Node trong DataStore
    node = store.get_node(target_edge_id)
    resolved_status = traffic_status or parsed_metrics.get("traffic_status") or (node.get("traffic_status") if node else "FREE")
    resolved_score = parsed_metrics.get("congestion_score") or (node.get("congestion_score") if node else 0)
    resolved_speed = parsed_metrics.get("avg_speed_kmh") or (node.get("avg_speed_kmh") if node else 0.0)
    resolved_count = parsed_metrics.get("current_vehicle_count") or (node.get("current_vehicle_count") if node else 0)

    store.update_node_snapshot(target_edge_id, snapshot_url)

    # Lưu bản ghi snapshot vào lịch sử (Lưu cả mốc sự kiện captured_at và mốc nhận received_at - Fix D1, D3)
    record = {
        "snapshot_id": f"snap-{uuid.uuid4().hex[:8]}",
        "edge_id": target_edge_id,
        "camera_id": camera_id or (node.get("camera_id") if node else "camera-01"),
        "segment_id": segment_id or (node.get("segment_id") if node else "segment-001"),
        "timestamp": event_ts,
        "captured_at": event_ts,
        "received_at": received_at,
        "time_str": time_str,
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
    timestamp: Optional[str] = Form(None),
    captured_at: Optional[str] = Form(None),
):
    return await _handle_snapshot_upload(
        request, image, snapshot, file, edge_id, camera_id, segment_id,
        traffic_status, metrics, trigger_reason, authorization, x_edge_token,
        timestamp, captured_at
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
    timestamp: Optional[str] = Form(None),
    captured_at: Optional[str] = Form(None),
):
    return await _handle_snapshot_upload(
        request, image, snapshot, file, edge_id, camera_id, segment_id,
        traffic_status, metrics, trigger_reason, authorization, x_edge_token,
        timestamp, captured_at
    )


@router.get("/snapshots", dependencies=[Depends(require_staff)])
def list_snapshots(
    segment_id: Optional[str] = Query(None),
    edge_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100)
):
    """Lấy danh sách các ảnh chụp snapshot đã lưu từ SQLite (Fix S3 - Yêu cầu quyền Staff)."""
    return store.get_snapshots(segment_id=segment_id, edge_id=edge_id, limit=limit)
