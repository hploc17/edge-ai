"""
Router: Node Fleet Management API

Luồng quản lý thiết bị 2 giai đoạn:
  1. Jetson tự báo cáo → pending_nodes (chờ Admin duyệt)
  2. Admin duyệt → approved_nodes (xuất hiện trên bản đồ)

Endpoints:
  GET    /api/v1/nodes               - Danh sách approved nodes
  GET    /api/v1/nodes/pending       - Danh sách nodes chờ duyệt
  GET    /api/v1/nodes/{edge_id}     - Chi tiết 1 approved node
  POST   /api/v1/nodes               - Tạo/đăng ký thủ công (Admin thêm trực tiếp)
  POST   /api/v1/nodes/{edge_id}/approve  - Duyệt thiết bị từ hàng chờ
  DELETE /api/v1/nodes/{edge_id}/pending  - Từ chối thiết bị từ hàng chờ
  PUT    /api/v1/nodes/{edge_id}     - Cập nhật thông số approved node
  DELETE /api/v1/nodes/{edge_id}     - Xóa approved node
"""

import asyncio
from typing import Optional, List, Dict, Any, Tuple
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, model_validator

from services.data_store import store
from services.websocket_manager import ws_manager
from services.auth_middleware import require_staff, get_optional_staff
from services.mqtt_service import mqtt_service

router = APIRouter(prefix="/api/v1/nodes", tags=["Node Fleet Management"])

# ─── Pydantic Models & Coordinate Validation (Mục 3) ─────────────────────────

def _validate_and_normalize_coords(lat: float, lng: float) -> tuple[float, float]:
    """Kiểm tra và tự động đảo chiều nếu tọa độ bị nhầm giữa Kinh độ và Vĩ độ tại Việt Nam."""
    # Phát hiện trường hợp bị đảo ngược: Lat > 100 và Lng < 30
    if lat >= 100.0 and lng <= 30.0:
        lat, lng = lng, lat
    
    # Kiểm tra giới hạn lãnh thổ Việt Nam
    # Kinh độ (Longitude): ~102.0 đến ~110.0
    # Vĩ độ (Latitude): ~8.0 đến ~24.0
    if not (101.5 <= lng <= 110.5 and 7.5 <= lat <= 24.5):
        raise ValueError(
            f"Tọa độ không hợp lệ cho lãnh thổ Việt Nam: Longitude={lng}, Latitude={lat}. "
            "Kinh độ phải thuộc [102.0, 110.0] và Vĩ độ phải thuộc [8.0, 24.0]."
        )
    return lat, lng

class NodeCreateUpdate(BaseModel):
    """Model dùng khi Admin tạo/sửa node thủ công."""
    edge_id: Optional[str] = None
    mac_address: Optional[str] = None
    name: str
    camera_id: Optional[str] = "camera-01"
    segment_id: Optional[str] = None
    road_name: Optional[str] = ""
    latitude: float
    longitude: float
    altitude_m: Optional[float] = 10.0
    camera_heading: Optional[float] = 0.0
    camera_fov: Optional[float] = 65.0
    lane_count: Optional[int] = 2
    road_length_m: Optional[float] = 200.0
    road_width_m: Optional[float] = 7.0
    speed_limit_kmh: Optional[float] = 60.0
    osm_way_id: Optional[int] = None
    osm_road_type: Optional[str] = None
    # Tọa độ tim đường thực tế từ OSM (dùng để vẽ heatmap)
    osm_coordinates: Optional[List[List[float]]] = None

    @model_validator(mode="after")
    def validate_coordinates(self):
        lat, lng = _validate_and_normalize_coords(self.latitude, self.longitude)
        self.latitude = lat
        self.longitude = lng
        return self


class NodeApproveRequest(BaseModel):
    """Model dùng khi Admin phê duyệt một thiết bị từ hàng chờ."""
    edge_id: Optional[str] = None
    name: Optional[str] = None
    mac_address: Optional[str] = None
    latitude: float
    longitude: float
    road_name: str
    segment_id: Optional[str] = None
    lane_count: int = 2
    road_length_m: float = 200.0
    road_width_m: float = 7.0
    speed_limit_kmh: float = 60.0
    camera_heading: float = 0.0
    camera_fov: float = 65.0
    altitude_m: float = 10.0
    osm_way_id: Optional[int] = None
    osm_road_type: Optional[str] = None
    osm_coordinates: Optional[List[List[float]]] = None

    @model_validator(mode="after")
    def validate_coordinates(self):
        lat, lng = _validate_and_normalize_coords(self.latitude, self.longitude)
        self.latitude = lat
        self.longitude = lng
        return self


def _mask_node_for_public(node_dict: Dict[str, Any], is_staff: bool) -> Dict[str, Any]:
    """Ẩn địa chỉ MAC và Hardware ID đối với người xem công khai (Fix S3)."""
    if is_staff or not node_dict:
        return node_dict
    copied = dict(node_dict)
    copied.pop("mac_address", None)
    copied.pop("actual_hardware_id", None)
    return copied


# ─── Approved Nodes Endpoints ─────────────────────────────────────────────────

@router.get("", response_model=List[Dict[str, Any]])
def list_all_nodes(is_staff: bool = Depends(get_optional_staff)):
    """Trả về danh sách các node đã được Admin phê duyệt (ẩn MAC với khách vãng lai - Fix S3)."""
    return [_mask_node_for_public(n, is_staff) for n in store.get_all_nodes()]


@router.get("/pending", response_model=List[Dict[str, Any]], dependencies=[Depends(require_staff)])
def list_pending_nodes():
    """Trả về danh sách các thiết bị Jetson đang chờ Admin phê duyệt."""
    return store.get_all_pending()


@router.get("/auto-id", response_model=Dict[str, str], dependencies=[Depends(require_staff)])
def get_next_auto_identifiers():
    """Tự động sinh bộ ba định danh kế tiếp (EDGE_xxx, CAM_xxx, SEG_xxx) theo chuẩn ZTP."""
    return store.generate_next_identifiers()


@router.get("/{edge_id}", response_model=Dict[str, Any])
def get_node_detail(edge_id: str, is_staff: bool = Depends(get_optional_staff)):
    """Lấy thông tin chi tiết node (ẩn MAC với khách vãng lai - Fix S3)."""
    node = store.get_node(edge_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{edge_id}' not found or not yet approved.")
    return _mask_node_for_public(node, is_staff)


# ─── Approve / Reject Pending Nodes (Mục 2) ───────────────────────────────────

@router.post("/approve", dependencies=[Depends(require_staff)])
async def approve_node_alias(data: NodeApproveRequest):
    """Alias cho POST /api/v1/nodes/approve (nếu edge_id được gửi kèm trong payload)."""
    if not data.edge_id:
        raise HTTPException(status_code=400, detail="Missing 'edge_id' in approval payload.")
    return await approve_pending_node(data.edge_id, data)

@router.post("/{edge_id}/approve", dependencies=[Depends(require_staff)])
async def approve_pending_node(edge_id: str, data: NodeApproveRequest):
    """
    Admin phê duyệt thiết bị Jetson từ hàng chờ.
    
    Yêu cầu:
      - edge_id phải đang trong danh sách pending hoặc chưa từng đăng ký
      - Bắt buộc phải cung cấp latitude, longitude, road_name
    
    Sau khi approve:
      - Node được lưu vĩnh viễn vào approved_nodes.json
      - Nếu osm_coordinates có dữ liệu, đoạn đường được vẽ trên bản đồ với tọa độ thực tế
      - Broadcast WebSocket node_registered & NODE_ADDED đến tất cả client đang kết nối
    """
    approved_data = data.model_dump()
    if not approved_data.get("segment_id"):
        approved_data["segment_id"] = f"seg-{edge_id}"

    node = store.approve_node(edge_id, approved_data)

    # Tự động đồng bộ và cấp phát Edge ID xuống thiết bị Jetson qua topic provisioning (Zero-Touch)
    mac_addr = node.get("mac_address")
    if mac_addr:
        mqtt_service.publish_provisioning_approval(
            mac_address=mac_addr,
            assigned_edge_id=edge_id,
            approved_data=node
        )

    # Broadcast cả 2 dạng sự kiện để tương thích mọi phiên bản client
    await ws_manager.broadcast({
        "type": "node_registered",
        "edge_id": edge_id,
        "node": node
    })
    await ws_manager.broadcast({
        "type": "NODE_ADDED",
        "edge_id": edge_id,
        "node": node
    })

    # Nếu có segment mới, broadcast cập nhật bản đồ
    seg_id = node.get("segment_id")
    if seg_id and store.get_segment(seg_id):
        await ws_manager.broadcast({
            "type": "segment_updated",
            "segment": store.get_segment(seg_id)
        })

    return {
        "message": f"Node '{edge_id}' approved and activated on map.",
        "node": node,
        "segment_created": bool(approved_data.get("osm_coordinates"))
    }


@router.delete("/{edge_id}/pending", dependencies=[Depends(require_staff)])
def reject_pending_node(edge_id: str):
    """Admin từ chối thiết bị đang trong hàng chờ."""
    success = store.reject_pending(edge_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"No pending device found with edge_id '{edge_id}'.")
    return {"message": f"Pending device '{edge_id}' rejected and removed from queue."}


# ─── Manual Create (Admin đăng ký thủ công, không cần Jetson có mặt) ─────────

@router.post("", dependencies=[Depends(require_staff)])
async def create_node(data: NodeCreateUpdate):
    """
    Admin tạo node thủ công — trực tiếp đưa vào danh sách approved, không qua hàng chờ.
    Thường dùng khi thêm camera mới qua giao diện web trước khi Jetson kết nối lần đầu.
    """
    import time as _time
    node_dict = data.model_dump()
    if not node_dict.get("edge_id"):
        node_dict["edge_id"] = f"edge-{int(_time.time()) % 1000:03d}"
    if not node_dict.get("segment_id"):
        node_dict["segment_id"] = f"seg-{node_dict['edge_id']}"

    approved_data = {**node_dict}
    node = store.approve_node(node_dict["edge_id"], approved_data)

    await ws_manager.broadcast({
        "type": "node_registered",
        "edge_id": node["edge_id"],
        "node": node
    })
    if node_dict.get("osm_coordinates"):
        seg_id = node.get("segment_id")
        if seg_id and store.get_segment(seg_id):
            await ws_manager.broadcast({
                "type": "segment_updated",
                "segment": store.get_segment(seg_id)
            })

    return {"message": "Node created successfully.", "node": node}


# ─── Update / Delete Approved Nodes ──────────────────────────────────────────

@router.put("/{edge_id}", dependencies=[Depends(require_staff)])
async def update_node(edge_id: str, data: NodeCreateUpdate):
    """Cập nhật thông số cấu hình của một approved node đã tồn tại."""
    existing = store.get_node(edge_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Node '{edge_id}' not found.")
    node_dict = data.model_dump()
    node_dict["edge_id"] = edge_id
    # Giữ nguyên dữ liệu telemetry real-time hiện tại
    for k in ("traffic_status", "congestion_score", "avg_speed_kmh",
              "current_vehicle_count", "counts_by_class", "latest_health", "snapshot_url"):
        if k in existing and k not in node_dict:
            node_dict[k] = existing[k]

    # Nếu có cập nhật segment coordinates, upsert segment
    osm_coords = node_dict.pop("osm_coordinates", None)
    if osm_coords and len(osm_coords) >= 2:
        seg_id = node_dict.get("segment_id") or f"seg-{edge_id}"
        node_dict["segment_id"] = seg_id
        store.upsert_segment({
            "segment_id": seg_id,
            "road_name": node_dict.get("road_name", ""),
            "lane_count": node_dict.get("lane_count", 2),
            "road_length_m": node_dict.get("road_length_m", 200.0),
            "road_width_m": node_dict.get("road_width_m", 7.0),
            "speed_limit_kmh": node_dict.get("speed_limit_kmh", 60.0),
            "coordinates": osm_coords,
        })

    saved = store.upsert_node(node_dict)
    await ws_manager.broadcast({
        "type": "node_registered",
        "edge_id": edge_id,
        "node": saved
    })
    return {"message": "Node updated successfully.", "node": saved}


@router.delete("/{edge_id}", dependencies=[Depends(require_staff)])
async def delete_node(edge_id: str):
    """Xóa một approved node khỏi bản đồ và ổ cứng."""
    success = store.delete_node(edge_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Node '{edge_id}' not found.")
    await ws_manager.broadcast({"type": "node_deleted", "edge_id": edge_id})
    return {"message": f"Node '{edge_id}' deleted successfully."}

