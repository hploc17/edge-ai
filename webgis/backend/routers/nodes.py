from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from services.data_store import store

router = APIRouter(prefix="/api/v1/nodes", tags=["Node Fleet Management"])

class NodeCreateUpdate(BaseModel):
    edge_id: Optional[str] = None
    name: str
    camera_id: Optional[str] = "camera-01"
    segment_id: Optional[str] = "segment-001"
    road_name: Optional[str] = "Đường mới"
    latitude: float
    longitude: float
    altitude_m: Optional[float] = 12.0
    camera_heading: Optional[float] = 45.0
    camera_fov: Optional[float] = 65.0

@router.get("")
def list_all_nodes():
    return store.get_all_nodes()

@router.get("/{edge_id}")
def get_node_detail(edge_id: str):
    node = store.get_node(edge_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node

@router.post("")
def create_node(data: NodeCreateUpdate):
    node_dict = data.model_dump()
    if not node_dict.get("edge_id"):
        import time
        node_dict["edge_id"] = f"edge-{int(time.time()) % 1000:03d}"
    saved = store.upsert_node(node_dict)
    return {"message": "Node created successfully", "node": saved}

@router.put("/{edge_id}")
def update_node(edge_id: str, data: NodeCreateUpdate):
    existing = store.get_node(edge_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Node not found")
    node_dict = data.model_dump()
    node_dict["edge_id"] = edge_id
    # Preserve latest telemetry
    for k in ("traffic_status", "congestion_score", "avg_speed_kmh", "current_vehicle_count", "counts_by_class", "latest_health"):
        if k in existing and k not in node_dict:
            node_dict[k] = existing[k]
    saved = store.upsert_node(node_dict)
    return {"message": "Node updated successfully", "node": saved}

@router.delete("/{edge_id}")
def delete_node(edge_id: str):
    success = store.delete_node(edge_id)
    if not success:
        raise HTTPException(status_code=404, detail="Node not found")
    return {"message": "Node deleted successfully"}
