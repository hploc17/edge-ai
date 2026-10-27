import asyncio
from typing import Optional
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from config import API_HOST, API_PORT
from services.websocket_manager import ws_manager
from services.mqtt_service import mqtt_service
from routers import gis, nodes, history, commands
from routers import remote_control
from routers import snapshots
from routers import osm as osm_router
from routers import live as live_router

# Thư mục lưu trữ ảnh snapshots tĩnh
import time
from datetime import datetime
from services.data_store import store

SNAPSHOTS_STORAGE_DIR = Path(__file__).resolve().parent / "data" / "snapshots"
SNAPSHOTS_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

def _parse_timestamp(ts) -> float:
    if not ts:
        return 0.0
    if isinstance(ts, (int, float)):
        return float(ts)
    try:
        clean_ts = str(ts).replace("Z", "+00:00")
        return datetime.fromisoformat(clean_ts).timestamp()
    except Exception:
        try:
            return float(ts)
        except Exception:
            return 0.0

async def device_liveness_supervisor():
    """Device Liveness Supervisor Probe: Định kỳ quét kiểm tra trạng thái liveness của Edge Nodes (Mục 4)."""
    while True:
        try:
            await asyncio.sleep(10)
            now = time.time()
            for edge_id, node in list(store.nodes.items()):
                if node.get("status") == "online":
                    last_seen_val = node.get("last_seen")
                    last_seen_sec = _parse_timestamp(last_seen_val)
                    if last_seen_sec > 0 and (now - last_seen_sec > 25):
                        print(f"[LIVENESS SUPERVISOR] Node '{edge_id}' timed out ({int(now - last_seen_sec)}s > 25s) -> marking OFFLINE")
                        store.set_node_status(edge_id, "offline")
                        # Broadcast both device_liveness_event and heartbeat (for UI compatibility)
                        event_payload = {
                            "type": "device_liveness_event",
                            "event": "timeout",
                            "edge_id": edge_id,
                            "status": "offline",
                            "last_seen": node.get("last_seen")
                        }
                        await ws_manager.broadcast(event_payload)
                        await ws_manager.broadcast({
                            "type": "heartbeat",
                            "edge_id": edge_id,
                            "status": "offline",
                            "last_seen": node.get("last_seen")
                        })
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[LIVENESS SUPERVISOR ERROR] {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start MQTT client background service and Liveness Supervisor
    loop = asyncio.get_running_loop()
    mqtt_service.start(loop)
    supervisor_task = asyncio.create_task(device_liveness_supervisor())
    print(f"[FASTAPI] WebGIS Backend Hub started on http://{API_HOST}:{API_PORT}")
    yield
    # Shutdown: Clean up Supervisor & MQTT
    supervisor_task.cancel()
    mqtt_service.stop()
    print("[FASTAPI] WebGIS Backend Hub shutdown cleanly.")

app = FastAPI(
    title="WebGIS Smart Traffic Operations Center API",
    description="FastAPI Backend for Realtime Traffic Monitoring, Edge Device C&C, and WebGIS Map",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for React Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers (Standard /api/v1/ prefix)
app.include_router(gis.router)
app.include_router(nodes.router)
app.include_router(history.router)
app.include_router(commands.router)
app.include_router(remote_control.router)
app.include_router(snapshots.router)
app.include_router(osm_router.router)
app.include_router(live_router.router)

# Mount Static Files cho Snapshots (truy cập tại /snapshots/{filename})
app.mount("/snapshots", StaticFiles(directory=str(SNAPSHOTS_STORAGE_DIR)), name="snapshots")

# WebSocket Endpoint for Live Telemetry & Device Health Streaming
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = None):
    await ws_manager.connect(websocket, token=token)
    try:
        while True:
            data = await websocket.receive_text()
            # Cho phép client gửi auth message sau khi connect: {"type": "authenticate", "token": "..."}
            try:
                import json as _json
                parsed = _json.loads(data)
                if isinstance(parsed, dict) and parsed.get("type") == "authenticate":
                    ws_manager.set_client_token(websocket, parsed.get("token", ""))
            except Exception:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)

# Health check endpoint
@app.get("/api/health")
def api_health():
    return {"status": "healthy", "service": "WebGIS Backend Hub", "version": "1.0.0"}

# Handle browser favicon request to prevent 404
@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    fav = FRONTEND_DIST / "favicon.svg"
    if fav.exists():
        from fastapi.responses import FileResponse
        return FileResponse(fav, media_type="image/svg+xml")
    from fastapi.responses import Response
    return Response(status_code=204)

# Static files mount if frontend is built
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if not FRONTEND_DIST.exists():
    for cand_dist in [
        Path(__file__).resolve().parent / "frontend" / "dist",
        Path(__file__).resolve().parent / "dist",
        Path(__file__).resolve().parent.parent / "dist"
    ]:
        if cand_dist.exists():
            FRONTEND_DIST = cand_dist
            break
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
else:
    @app.get("/")
    def index():
        return JSONResponse({
            "message": "WebGIS Backend Hub is running! Frontend is in development mode or not yet built.",
            "swagger_docs": "/docs",
            "websocket": "/ws"
        })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=API_HOST, port=API_PORT, reload=True)
