import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from services.mqtt_service import mqtt_service
from services.data_store import store

router = APIRouter(prefix="/api/v1/commands", tags=["Device Command & Control"])

class CommandRequest(BaseModel):
    edge_id: str
    action: str  # get_health, reload_config, restart_analytics, capture_test_snapshot
    params: Optional[Dict[str, Any]] = None

@router.post("/send")
def send_command(req: CommandRequest):
    """Dispatch command to edge device via MQTT topic traffic/{edge_id}/command."""
    node = store.get_node(req.edge_id)
    if not node:
        raise HTTPException(status_code=404, detail="Edge device not found")

    command_id = f"cmd-{uuid.uuid4().hex[:8]}"
    success = mqtt_service.publish_command(
        edge_id=req.edge_id,
        action=req.action,
        command_id=command_id,
        params=req.params
    )

    return {
        "success": success,
        "command_id": command_id,
        "action": req.action,
        "edge_id": req.edge_id,
        "message": f"Command '{req.action}' dispatched to node {req.edge_id}"
    }

@router.post("/diagnose/{edge_id}")
def diagnose_node_health(edge_id: str):
    """Shortcut to request on-demand health diagnostics (Gói 2)."""
    node = store.get_node(edge_id)
    if not node:
        raise HTTPException(status_code=404, detail="Edge device not found")

    command_id = f"diag-{uuid.uuid4().hex[:8]}"
    mqtt_service.publish_command(
        edge_id=edge_id,
        action="get_health",
        command_id=command_id
    )

    # Return latest known health as immediate fallback
    return {
        "command_id": command_id,
        "edge_id": edge_id,
        "status": "dispatched",
        "latest_health": node.get("latest_health", {})
    }
