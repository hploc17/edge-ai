"""
Middleware và Dependencies Phân quyền & Xác thực JWT cho FastAPI Backend.
Đồng bộ và chia sẻ cùng JWT_SECRET với Node.js Express Auth Service.
"""

import time
from typing import List, Optional, Dict
import jwt
from fastapi import Request, HTTPException, Security, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os

import hmac

# JWT_SECRET được config.py nạp và kiểm tra (dùng chung với Express auth-service)
from config import JWT_SECRET, EDGE_TOKEN
JWT_ALGORITHM = "HS256"


def verify_edge_token(candidate: Optional[str]) -> bool:
    """So khớp token thiết bị Edge (hằng thời gian). Từ chối nếu server chưa cấu hình EDGE_TOKEN."""
    if not EDGE_TOKEN or not candidate:
        return False
    return hmac.compare_digest(candidate.strip().encode("utf-8"), EDGE_TOKEN.encode("utf-8"))


def edge_token_from_request(request: Request, x_edge_token: Optional[str] = None) -> str:
    """Lấy token thiết bị từ X-Edge-Token, hoặc từ 'Authorization: Bearer <EDGE_TOKEN>' (tương thích ngược)."""
    token = x_edge_token or request.headers.get("x-edge-token") or ""
    if token:
        return token
    auth_hdr = request.headers.get("authorization") or ""
    if auth_hdr.startswith("Bearer "):
        return auth_hdr[7:]
    return ""

# Hằng số phân quyền dùng chung
STAFF = ["ADMIN", "MANAGER"]
ADMIN_ONLY = ["ADMIN"]
ALL_ROLES = ["ADMIN", "MANAGER", "USER"]

security_bearer = HTTPBearer(auto_error=False)


def authenticate(credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer)) -> dict:
    """
    Xác thực Bearer JWT token từ header Authorization.
    Trả về dict payload: {"userId": ..., "role": ...}.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bạn chưa đăng nhập hoặc thiếu Bearer Token hợp lệ",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("userId")
        role = payload.get("role")
        if not user_id or not role:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token không chứa đủ thông tin định danh (userId, role)",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return {"userId": user_id, "role": role}
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên làm việc đã hết hạn. Vui lòng đăng nhập lại.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ hoặc sai chữ ký bảo mật",
            headers={"WWW-Authenticate": "Bearer"},
        )


def authorize_roles(allowed_roles: List[str]):
    """
    Factory tạo FastAPI Dependency kiểm tra role.
    Yêu cầu token phải hợp lệ và role phải nằm trong allowed_roles.
    """
    def role_checker(user: dict = Depends(authenticate)) -> dict:
        user_role = user.get("role")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Bạn không có quyền thực hiện chức năng này. Yêu cầu một trong các quyền: {allowed_roles}",
            )
        return user

    return role_checker


# Fast dependencies tiện lợi
require_staff = authorize_roles(STAFF)
require_admin = authorize_roles(ADMIN_ONLY)


def get_optional_staff(credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer)) -> bool:
    """Trả về True nếu request mang token hợp lệ của Staff (ADMIN, MANAGER), ngược lại False (Fix S3)."""
    if not credentials:
        return False
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("role") in STAFF
    except Exception:
        return False


# ── In-Memory Rate Limiter cho Snapshot Công Khai (1 req / 10s / IP) ─────────
_snapshot_rate_limits: Dict[str, float] = {}
SNAPSHOT_COOLDOWN_SECONDS = 10.0


def check_snapshot_rate_limit(request: Request):
    """
    Áp dụng Rate-limit cho chức năng chụp snapshot theo yêu cầu:
    Tối đa 1 request / 10 giây trên mỗi địa chỉ IP client.
    """
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    last_time = _snapshot_rate_limits.get(client_ip, 0)
    elapsed = now - last_time

    if elapsed < SNAPSHOT_COOLDOWN_SECONDS:
        wait_time = int(SNAPSHOT_COOLDOWN_SECONDS - elapsed) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Yêu cầu chụp snapshot quá nhanh. Vui lòng đợi {wait_time} giây trước khi chụp lại.",
            headers={"Retry-After": str(wait_time)},
        )

    _snapshot_rate_limits[client_ip] = now
