from fastapi import APIRouter
from services.data_store import store

router = APIRouter(prefix="/api/v1/gis", tags=["WebGIS Layer Endpoints"])

@router.get("/nodes")
def get_nodes_geojson():
    """Return Point GeoJSON FeatureCollection of all camera nodes."""
    return store.get_nodes_geojson()

@router.get("/segments")
def get_segments_geojson():
    """Return LineString GeoJSON FeatureCollection of all road corridors with congestion colors."""
    return store.get_segments_geojson()

@router.get("/summary")
def get_gis_summary():
    """Return high-level summary KPIs for top dashboard bar."""
    nodes = store.get_all_nodes()
    segments = store.get_all_segments()
    
    online_count = sum(1 for n in nodes if n.get("status") == "online")
    congested_count = sum(1 for s in segments if s.get("traffic_status") == "CONGESTED")
    slow_count = sum(1 for s in segments if s.get("traffic_status") == "SLOW")
    free_count = sum(1 for s in segments if s.get("traffic_status") == "FREE")
    
    speeds = [s.get("avg_speed_kmh", 0) for s in segments if s.get("avg_speed_kmh")]
    avg_speed = round(sum(speeds) / len(speeds), 1) if speeds else 0.0

    return {
        "total_nodes": len(nodes),
        "online_nodes": online_count,
        "offline_nodes": len(nodes) - online_count,
        "total_segments": len(segments),
        "congested_segments": congested_count,
        "slow_segments": slow_count,
        "free_segments": free_count,
        "system_avg_speed_kmh": avg_speed,
        "active_alerts_count": congested_count
    }
