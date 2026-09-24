from fastapi import APIRouter, Query
from typing import Optional
from services.data_store import store

router = APIRouter(prefix="/api/v1/history", tags=["Congestion History & Playback"])

@router.get("/timeline")
def get_timeline(
    segment_id: Optional[str] = Query("segment-001", description="Segment ID to query"),
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format")
):
    """Return 24h time-series congestion data for playback slider."""
    records = [r for r in store.history_records if r.get("segment_id") == segment_id]
    if not records:
        records = store.history_records

    # Summary metrics for the day
    scores = [r["congestion_score"] for r in records]
    speeds = [r["avg_speed_kmh"] for r in records]

    return {
        "segment_id": segment_id,
        "total_intervals": len(records),
        "peak_congestion_score": max(scores) if scores else 0,
        "min_speed_kmh": min(speeds) if speeds else 0.0,
        "avg_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else 0.0,
        "records": records
    }

@router.get("/snapshots")
def get_congestion_snapshots(
    segment_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100)
):
    """Return list of congestion snapshots captured by Jetson Nano nodes."""
    snapshots = [
        {
            "snapshot_id": "snap-001",
            "edge_id": "edge-01",
            "segment_id": "segment-001",
            "timestamp": "2026-09-21T07:45:12+07:00",
            "time_str": "07:45",
            "location_name": "Ngã tư Nguyễn Trãi - Khuất Duy Tiến",
            "traffic_status": "CONGESTED",
            "congestion_score": 88,
            "avg_speed_kmh": 7.5,
            "vehicle_count": 42,
            "image_url": "https://images.unsplash.com/photo-1568605117036-5fe5e7bab0b7?auto=format&fit=crop&w=800&q=80"
        },
        {
            "snapshot_id": "snap-002",
            "edge_id": "edge-01",
            "segment_id": "segment-001",
            "timestamp": "2026-09-21T08:15:30+07:00",
            "time_str": "08:15",
            "location_name": "Ngã tư Nguyễn Trãi - Khuất Duy Tiến",
            "traffic_status": "CONGESTED",
            "congestion_score": 82,
            "avg_speed_kmh": 9.2,
            "vehicle_count": 38,
            "image_url": "https://images.unsplash.com/photo-1545179605-1296651e4d43?auto=format&fit=crop&w=800&q=80"
        },
        {
            "snapshot_id": "snap-003",
            "edge_id": "edge-02",
            "segment_id": "segment-002",
            "timestamp": "2026-09-21T17:35:10+07:00",
            "time_str": "17:35",
            "location_name": "Vành Đai 3 - Khuất Duy Tiến",
            "traffic_status": "CONGESTED",
            "congestion_score": 85,
            "avg_speed_kmh": 8.0,
            "vehicle_count": 35,
            "image_url": "https://images.unsplash.com/photo-1506521781263-d8422e82f27a?auto=format&fit=crop&w=800&q=80"
        }
    ]
    if segment_id:
        snapshots = [s for s in snapshots if s["segment_id"] == segment_id]
    return snapshots[:limit]
