import uuid
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
from services.mqtt_service import mqtt_service
from services.data_store import store
from services.auth_middleware import authenticate, require_staff, check_snapshot_rate_limit, STAFF

router = APIRouter(prefix="/api/v1/commands", tags=["Device Command & Control"])

class CommandRequest(BaseModel):
    edge_id: str
    action: str  # get_health, reload_config, restart_analytics, capture_test_snapshot
    params: Optional[Dict[str, Any]] = None

@router.post("/send")
def send_command(req: CommandRequest, user: dict = Depends(require_staff)):
    node = store.get_node(req.edge_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy thiết bị '{req.edge_id}'")

    command_id = f"cmd-{uuid.uuid4().hex[:8]}"
    success = mqtt_service.publish_command(
        edge_id=req.edge_id,
        action=req.action,
        command_id=command_id,
        params=req.params
    )

    if not success:
        raise HTTPException(status_code=502, detail="Không thể gửi lệnh qua MQTT Broker tới Jetson")

    return {
        "success": success,
        "command_id": command_id,
        "action": req.action,
        "edge_id": req.edge_id,
        "message": f"Command '{req.action}' dispatched to node {req.edge_id}"
    }

@router.post("/diagnose/{edge_id}", dependencies=[Depends(require_staff)])
def diagnose_node_health(edge_id: str):
    """Shortcut to request on-demand health diagnostics (Yêu cầu STAFF)."""
    node = store.get_node(edge_id)
    if not node:
        raise HTTPException(status_code=404, detail="Edge device not found")

    command_id = f"diag-{uuid.uuid4().hex[:8]}"
    mqtt_service.publish_command(
        edge_id=edge_id,
        action="get_health",
        command_id=command_id
    )

    curr_health = node.get("latest_health")
    if not curr_health and node.get("actual_hardware_id"):
        hw_node = store.get_node(node["actual_hardware_id"])
        if hw_node and hw_node.get("latest_health"):
            curr_health = hw_node["latest_health"]

    if not curr_health and node.get("system"):
        sys_info = node["system"]
        curr_health = {
            "timestamp": node.get("last_seen"),
            "general": {"service_status": "running", "uptime_seconds": 3600},
            "network": {"mac_address": node.get("mac_address", "00:04:4B:E7:44:E8"), "status": "connected"},
            "hardware": {
                "cpu_usage_pct": sys_info.get("cpu_usage", 0.0),
                "gpu_usage_pct": sys_info.get("gpu_usage", 0.0),
                "ram_usage_pct": sys_info.get("ram_usage", 0.0),
                "temperature_c": sys_info.get("temperature", 40.0),
                "fps": sys_info.get("fps", 0.0),
            },
            "pipeline": {
                "camera_status": "streaming" if node.get("pipeline_running") else "idle",
                "pipeline_fps": sys_info.get("fps", 0.0),
            }
        }

    # Return latest known health as immediate fallback
    return {
        "command_id": command_id,
        "edge_id": edge_id,
        "status": "dispatched",
        "latest_health": curr_health or {}
    }
