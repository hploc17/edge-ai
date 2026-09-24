import asyncio
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start MQTT client background service
    loop = asyncio.get_running_loop()
    mqtt_service.start(loop)
    print(f"[FASTAPI] WebGIS Backend Hub started on http://{API_HOST}:{API_PORT}")
    yield
    # Shutdown: Clean up MQTT
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

# Register API Routers
app.include_router(gis.router)
app.include_router(nodes.router)
app.include_router(history.router)
app.include_router(commands.router)

# WebSocket Endpoint for Live Telemetry & Device Health Streaming
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, listen for client messages
            data = await websocket.receive_text()
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
