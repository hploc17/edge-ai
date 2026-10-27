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
def send_command(req: CommandRequest, request: Request):
    node = store.get_node(req.edge_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy thiết bị '{req.edge_id}'")

    # Tất cả lệnh điều khiển thiết bị: BẮT BUỘC token role STAFF (ADMIN, MANAGER)
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Lệnh điều khiển thiết bị yêu cầu đăng nhập tài khoản Quản lý (STAFF)",
        )
    token = auth_header.split(" ")[1]
    import jwt, os
    jwt_secret = os.getenv("JWT_SECRET", "super_secret_jwt_key_traffic_gis_2026_change_in_production")
    try:
        payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
        user_role = payload.get("role")
        if user_role not in STAFF:
            raise HTTPException(
                status_code=403,
                detail=f"Tài khoản của bạn ({user_role}) không có quyền điều khiển thiết bị.",
            )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token không hợp lệ hoặc đã hết hạn")

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

    # Return latest known health as immediate fallback
    return {
        "command_id": command_id,
        "edge_id": edge_id,
        "status": "dispatched",
        "latest_health": node.get("latest_health", {})
    }
