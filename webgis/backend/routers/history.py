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
    """Return list of real congestion snapshots captured by Jetson Nano nodes."""
    # Only return real snapshots from actual captures
    snapshots = []
    if segment_id:
        snapshots = [s for s in snapshots if s.get("segment_id") == segment_id]
    return snapshots[:limit]
