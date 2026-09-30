"""
Router: OSM Road Lookup - Truy vấn thông số đường thực tế từ OpenStreetMap

Chiến lược 2 bước (không dùng Overpass API vì không ổn định):
  Bước 1: Nominatim Reverse Geocode → lấy osm_type + osm_id
  Bước 2: OSM Official Way Full API → lấy tags (name, lanes, maxspeed, width) + tọa độ LineString

Lợi ích:
  - 100% ổn định, không bị chặn 406
  - Trả về tọa độ tim đường (way geometry) thực tế để vẽ Heatmap đoạn đường
  - Miễn phí, không cần API key
"""

import math
from typing import Optional, List, Dict, Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/osm", tags=["OSM Road Lookup"])

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
OSM_WAY_URL = "https://api.openstreetmap.org/api/0.6/way/{way_id}/full.json"

COMMON_HEADERS = {
    "User-Agent": "EdgeTrafficWebGIS/2.0 (Open-source traffic monitoring; github.com/edge-traffic)"
}


# ─── Geometry Utilities ───────────────────────────────────────────────────────

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Khoảng cách Haversine giữa 2 tọa độ, đơn vị mét."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _polyline_length_m(coords: List[List[float]]) -> float:
    """Tính tổng chiều dài đoạn đường (mét) từ danh sách [lng, lat]."""
    total = 0.0
    for i in range(len(coords) - 1):
        total += _haversine_m(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0])
    return total


def _estimate_width_m(lanes: int, road_type: str) -> float:
    """Ước tính chiều rộng mặt đường theo TCVN 4054:2005."""
    lane_width = 3.75 if road_type in ("motorway", "trunk") else (3.5 if road_type in ("primary", "secondary") else 3.0)
    shoulder = 2.0 if lanes >= 4 else 1.0
    return round(lanes * lane_width + shoulder, 1)


# ─── Response Model ────────────────────────────────────────────────────────────

class OSMRoadInfo(BaseModel):
    found: bool
    osm_way_id: Optional[int] = None
    road_name: Optional[str] = None
    road_type: Optional[str] = None
    lanes: Optional[int] = None
    speed_limit_kmh: Optional[int] = None
    road_length_m: Optional[float] = None
    road_width_m: Optional[float] = None
    width_estimated: bool = False
    surface: Optional[str] = None
    oneway: Optional[bool] = None
    # Tọa độ tim đường thực tế dạng [[lng, lat], ...] để vẽ LineString trên bản đồ
    coordinates: Optional[List[List[float]]] = None
    raw_tags: Optional[Dict[str, Any]] = None
    message: str = ""


# ─── Main Endpoint ─────────────────────────────────────────────────────────────

@router.get("/road-info", response_model=OSMRoadInfo)
async def get_road_info_at_coords(lat: float, lng: float):
    """
    Truy vấn thông số đường thực tế tại tọa độ (lat, lng).

    **Bước 1:** Gọi Nominatim reverse geocode để xác định đường gần nhất và lấy osm_way_id.
    **Bước 2:** Gọi OSM Official Way API để lấy chi tiết đường: tên, số làn, tốc độ, bề rộng, và toàn bộ tọa độ tim đường.

    - **lat**: Vĩ độ (ví dụ: 10.7769)
    - **lng**: Kinh độ (ví dụ: 106.7009)

    Returns: Thông số đường + `coordinates` (danh sách tọa độ để vẽ LineString trên bản đồ)
    """
    async with httpx.AsyncClient(headers=COMMON_HEADERS, timeout=10.0) as client:

        # ── Bước 1: Nominatim reverse geocode ────────────────────────────────
        try:
            nom_resp = await client.get(
                NOMINATIM_URL,
                params={
                    "lat": lat,
                    "lon": lng,
                    "format": "json",
                    "zoom": 16,         # Độ chi tiết đủ để lấy tên đường
                    "addressdetails": 1,
                }
            )
            nom_resp.raise_for_status()
            nom_data = nom_resp.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Nominatim timeout. Hãy thử lại sau.")
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Nominatim error: {e}")

        # Nominatim trả về osm_type="way" khi điểm nằm trên đường
        osm_type = nom_data.get("osm_type")
        osm_id = nom_data.get("osm_id")
        nom_class = nom_data.get("class")
        nom_type = nom_data.get("type")       # primary, secondary, residential...

        # Nếu điểm click không nằm ngay trên đường, Nominatim trả về building/amenity...
        # Vẫn dùng osm_id nếu là loại highway
        if osm_type != "way" or nom_class != "highway":
            return OSMRoadInfo(
                found=False,
                message=(
                    f"Tọa độ ({lat:.5f}, {lng:.5f}) không nằm trên đường giao thông. "
                    f"Nominatim trả về: {nom_class}/{nom_type}. "
                    "Hãy thử click chính xác trên tim đường."
                )
            )

        road_name_from_nominatim = nom_data.get("name") or nom_data.get("display_name", "").split(",")[0]

        # ── Bước 2: OSM Way Full API (lấy nodes + tags) ───────────────────────
        try:
            way_resp = await client.get(OSM_WAY_URL.format(way_id=osm_id))
            way_resp.raise_for_status()
            way_data = way_resp.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="OSM Way API timeout.")
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"OSM Way API error: {e}")

        elements = way_data.get("elements", [])
        if not elements:
            return OSMRoadInfo(
                found=False,
                message=f"Không tìm thấy dữ liệu đường cho OSM way ID {osm_id}."
            )

        # Tách nodes (tọa độ) và way (tags)
        node_map: Dict[int, Dict[str, float]] = {}
        way_tags: Dict[str, str] = {}
        way_node_refs: List[int] = []

        for el in elements:
            if el["type"] == "node":
                node_map[el["id"]] = {"lat": el["lat"], "lon": el["lon"]}
            elif el["type"] == "way":
                way_tags = el.get("tags", {})
                way_node_refs = el.get("nodes", [])

        # Xây dựng LineString tọa độ theo thứ tự của way [[lng, lat], ...]
        coordinates: List[List[float]] = []
        for node_id in way_node_refs:
            if node_id in node_map:
                n = node_map[node_id]
                coordinates.append([n["lon"], n["lat"]])

        # ── Parse tags ──────────────────────────────────────────────────────

        # Tên đường (ưu tiên tag tiếng Việt → tag name chung → Nominatim fallback)
        road_name = (
            way_tags.get("name:vi")
            or way_tags.get("name")
            or way_tags.get("ref")
            or road_name_from_nominatim
            or "Chưa có tên"
        )

        # Số làn xe
        lanes_str = way_tags.get("lanes") or way_tags.get("lanes:forward")
        try:
            lanes = int(lanes_str) if lanes_str else None
        except (ValueError, TypeError):
            lanes = None
        if lanes is None:
            default_lanes = {"motorway": 4, "trunk": 4, "primary": 4, "secondary": 2, "tertiary": 2}
            lanes = default_lanes.get(way_tags.get("highway", ""), 2)

        # Tốc độ giới hạn
        speed_raw = way_tags.get("maxspeed", "").strip().replace(" km/h", "").replace("km/h", "").replace(" mph", "").replace("mph", "")
        try:
            speed_limit_kmh = int(speed_raw) if speed_raw.isdigit() else None
        except (ValueError, TypeError, AttributeError):
            speed_limit_kmh = None
        if speed_limit_kmh is None:
            default_speed = {"motorway": 120, "trunk": 90, "primary": 60, "secondary": 60, "tertiary": 50, "residential": 40}
            speed_limit_kmh = default_speed.get(way_tags.get("highway", ""), 60)

        # Chiều rộng mặt đường
        width_estimated = False
        width_raw = way_tags.get("width", "").replace(" m", "").replace("m", "").strip()
        try:
            road_width_m = round(float(width_raw), 1) if width_raw else None
        except (ValueError, TypeError):
            road_width_m = None
        if road_width_m is None:
            road_width_m = _estimate_width_m(lanes, way_tags.get("highway", ""))
            width_estimated = True

        # Chiều dài tính từ tọa độ thực tế
        road_length_m = round(_polyline_length_m(coordinates), 1) if len(coordinates) >= 2 else None

        return OSMRoadInfo(
            found=True,
            osm_way_id=osm_id,
            road_name=road_name,
            road_type=way_tags.get("highway"),
            lanes=lanes,
            speed_limit_kmh=speed_limit_kmh,
            road_length_m=road_length_m,
            road_width_m=road_width_m,
            width_estimated=width_estimated,
            surface=way_tags.get("surface"),
            oneway=way_tags.get("oneway") == "yes",
            coordinates=coordinates,
            raw_tags=dict(way_tags),
            message=f"✅ {road_name} ({way_tags.get('highway', 'unknown')}) — {len(coordinates)} điểm tọa độ"
        )
