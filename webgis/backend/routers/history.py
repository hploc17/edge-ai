from fastapi import APIRouter, Query, Depends
from typing import Optional
from services.data_store import store
from services.auth_middleware import require_staff

router = APIRouter(prefix="/api/v1/history", tags=["Congestion History & Playback"])

@router.get("/timeline")
def get_timeline(
    segment_id: Optional[str] = Query("segment-001", description="Segment ID to query"),
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format")
):
    """Return 24h time-series congestion data for playback slider from SQLite (Fix D1)."""
    target_seg = str(segment_id) if segment_id and not hasattr(segment_id, "default") else "segment-001"
    clean_date = date if isinstance(date, str) and date.strip() else None
    records = store.get_timeline_records(segment_id=target_seg, date=clean_date)

    # Summary metrics for the day
    # Phút đường vắng lưu avg_speed_kmh = NULL: bỏ qua khi thống kê để tránh TypeError
    scores = [r["congestion_score"] for r in records
              if r.get("congestion_score") is not None
              and r.get("traffic_status", "FREE") in ("FREE", "SLOW", "CONGESTED")]
    speeds = [r["avg_speed_kmh"] for r in records if r.get("avg_speed_kmh") is not None]

    return {
        "segment_id": target_seg,
        "total_intervals": len(records),
        "peak_congestion_score": max(scores) if scores else None,
        "min_speed_kmh": min(speeds) if speeds else 0.0,
        "avg_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else 0.0,
        "records": records
    }

# Ảnh bằng chứng có thể chứa biển số/khuôn mặt: cùng chính sách quyền với /api/v1/snapshots (chỉ Staff)
@router.get("/snapshots", dependencies=[Depends(require_staff)])
def get_congestion_snapshots(
    segment_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100)
):
    """Return list of real congestion snapshots captured by Jetson Nano nodes from SQLite (Fix D1, D3)."""
    return store.get_snapshots(segment_id=segment_id, limit=limit)
