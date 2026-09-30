"""
DataStore: Lưu trữ in-memory cho WebGIS Edge Traffic.

Kiến trúc quản lý Node 2 giai đoạn:
  - pending_nodes: Các Jetson thiết bị tự báo cáo qua MQTT nhưng chưa được Admin phê duyệt.
                   KHÔNG được vẽ lên bản đồ để tránh sai lệch tọa độ.
  - approved_nodes (self.nodes): Các Node đã được Admin xác nhận vị trí và thông số.
                   Được lưu vĩnh viễn vào approved_nodes.json.
                   Tự động khôi phục khi backend khởi động lại.
"""

import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

# ─── Bản đồ chuẩn hóa tên lớp xe ─────────────────────────────────────────────
# Model DeepStream/YOLO trên Jetson dùng 'motorbike' (COCO label),
# WebGIS frontend dùng 'motorcycle'. Hàm normalize_counts_by_class() hợp nhất.
CLASS_NAME_ALIASES: Dict[str, str] = {
    "motorbike": "motorcycle",
    "bike": "motorcycle",
    "moto": "motorcycle",
    "auto": "car",
    "van": "truck",
    "lorry": "truck",
}


def normalize_counts_by_class(counts: Dict[str, Any]) -> Dict[str, Any]:
    """Chuẩn hóa tên lớp phương tiện về chuẩn WebGIS."""
    if not counts:
        return counts
    normalized: Dict[str, int] = {}
    for key, value in counts.items():
        canonical = CLASS_NAME_ALIASES.get(key, key)
        normalized[canonical] = normalized.get(canonical, 0) + int(value or 0)
    return normalized


# ─── File persistence ─────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
APPROVED_NODES_FILE = DATA_DIR / "approved_nodes.json"
APPROVED_SEGMENTS_FILE = DATA_DIR / "approved_segments.json"


def _load_json_file(path: Path) -> dict:
    """Đọc file JSON, trả về {} nếu file không tồn tại hoặc bị hỏng."""
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[DataStore] Cannot load {path.name}: {e}")
    return {}


def _save_json_file(path: Path, data: dict):
    """Ghi file JSON an toàn (atomic write)."""
    try:
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(path)
    except Exception as e:
        print(f"[DataStore] Cannot save {path.name}: {e}")


# ─── Seed data cho đoạn đường mẫu ─────────────────────────────────────────────
INITIAL_SEGMENTS: List[Dict[str, Any]] = []  # Không tạo segment giả sẵn


class DataStore:
    """In-memory data store với hệ thống xác nhận thiết bị 2 giai đoạn."""

    def __init__(self):
        # ── Approved nodes: đã được Admin phê duyệt, vẽ lên bản đồ ──────────
        saved_nodes = _load_json_file(APPROVED_NODES_FILE)
        self.nodes: Dict[str, Dict[str, Any]] = saved_nodes
        print(f"[DataStore] Loaded {len(self.nodes)} approved node(s) from disk.")

        # ── Approved segments: đường thực tế đã được xác nhận ─────────────────
        saved_segments = _load_json_file(APPROVED_SEGMENTS_FILE)
        self.segments: Dict[str, Dict[str, Any]] = saved_segments
        print(f"[DataStore] Loaded {len(self.segments)} segment(s) from disk.")

        # ── Pending nodes: Jetson đã báo cáo, chưa được Admin phê duyệt ──────
        # Không lưu vào file — hàng đợi phát hiện bị reset khi backend khởi động lại.
        self.pending_nodes: Dict[str, Dict[str, Any]] = {}

        # ── Telemetry & history (in-memory only) ──────────────────────────────
        self.history_records: List[Dict[str, Any]] = []
        self.history_snapshots: List[Dict[str, Any]] = []

    # ─── Persistence helpers ──────────────────────────────────────────────────

    def _persist_nodes(self):
        """Ghi danh sách approved nodes xuống ổ cứng."""
        _save_json_file(APPROVED_NODES_FILE, self.nodes)

    def _persist_segments(self):
        """Ghi danh sách segments xuống ổ cứng."""
        _save_json_file(APPROVED_SEGMENTS_FILE, self.segments)

    # ─── Pending Node API ─────────────────────────────────────────────────────

    def add_pending_node(self, edge_id: str, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Thêm thiết bị Jetson vào hàng chờ phê duyệt.
        KHÔNG tự động gán tọa độ mặc định.
        Chỉ lưu thông tin kỹ thuật do Jetson tự báo cáo.
        """
        pending = {
            "edge_id": edge_id,
            "name": raw_data.get("name") or raw_data.get("device_name") or f"Thiết bị mới ({edge_id})",
            "camera_id": raw_data.get("camera_id", "unknown"),
            "model_version": raw_data.get("model_version", "unknown"),
            "segment_id": raw_data.get("segment_id"),       # Có thể None
            "latitude": raw_data.get("latitude"),           # Có thể None nếu chưa có GPS
            "longitude": raw_data.get("longitude"),         # Có thể None
            "road_name": raw_data.get("road_name"),         # Có thể None
            "camera_heading": raw_data.get("camera_heading"),
            "camera_fov": raw_data.get("camera_fov"),
            "raw_payload": raw_data,                        # Lưu toàn bộ payload gốc để Admin xem
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "status": "pending",
        }
        self.pending_nodes[edge_id] = pending
        return pending

    def get_pending_node(self, edge_id: str) -> Optional[Dict[str, Any]]:
        return self.pending_nodes.get(edge_id)

    def get_all_pending(self) -> List[Dict[str, Any]]:
        return list(self.pending_nodes.values())

    def touch_pending(self, edge_id: str, payload: Dict[str, Any]):
        """Cập nhật last_seen và thông số mới nhất cho node đang pending."""
        if edge_id in self.pending_nodes:
            self.pending_nodes[edge_id]["last_seen"] = datetime.now().isoformat()
            # Cập nhật thông số kỹ thuật nếu Jetson gửi thêm
            for key in ("model_version", "camera_id", "latitude", "longitude"):
                if payload.get(key) is not None:
                    self.pending_nodes[edge_id][key] = payload[key]

    def reject_pending(self, edge_id: str) -> bool:
        """Từ chối thiết bị — xóa khỏi hàng chờ."""
        if edge_id in self.pending_nodes:
            del self.pending_nodes[edge_id]
            return True
        return False

    def approve_node(self, edge_id: str, approved_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Admin xác nhận thiết bị: merge thông số Admin cung cấp vào thông tin raw của Jetson,
        chuyển từ pending sang approved, lưu xuống ổ cứng.

        approved_data phải có ít nhất: latitude, longitude, road_name, lane_count.
        """
        raw = self.pending_nodes.get(edge_id, {})
        node = {
            # Thông tin từ Jetson (raw)
            "edge_id": edge_id,
            "name": approved_data.get("name") or raw.get("name") or f"Camera AI Jetson ({edge_id})",
            "camera_id": raw.get("camera_id", "camera-01"),
            "model_version": raw.get("model_version", ""),
            # Thông số Admin xác nhận (bắt buộc)
            "latitude": float(approved_data["latitude"]),
            "longitude": float(approved_data["longitude"]),
            "road_name": approved_data.get("road_name", "Chưa xác định"),
            "segment_id": approved_data.get("segment_id", f"seg-{edge_id}"),
            "lane_count": int(approved_data.get("lane_count", 2)),
            "road_length_m": float(approved_data.get("road_length_m", 200.0)),
            "road_width_m": float(approved_data.get("road_width_m", 7.0)),
            "speed_limit_kmh": float(approved_data.get("speed_limit_kmh", 60.0)),
            "camera_heading": float(approved_data.get("camera_heading", 0.0)),
            "camera_fov": float(approved_data.get("camera_fov", 65.0)),
            "altitude_m": float(approved_data.get("altitude_m", 10.0)),
            "osm_way_id": approved_data.get("osm_way_id"),
            "osm_road_type": approved_data.get("osm_road_type"),
            # Trạng thái hoạt động
            "status": "online",
            "traffic_status": "FREE",
            "congestion_score": 0,
            "avg_speed_kmh": 0.0,
            "current_vehicle_count": 0,
            "stopped_vehicle_count": 0,
            "density_veh_per_km_lane": 0.0,
            "counts_by_class": {"motorcycle": 0, "car": 0, "bus": 0, "truck": 0},
            "last_seen": datetime.now().isoformat(),
            "approved_at": datetime.now().isoformat(),
        }

        # Lưu vào approved list và ổ cứng
        self.nodes[edge_id] = node
        self._persist_nodes()

        # Xóa khỏi pending
        self.pending_nodes.pop(edge_id, None)

        # Tự động upsert segment đường nếu có coordinates từ OSM
        osm_coordinates = approved_data.get("osm_coordinates")
        if osm_coordinates and len(osm_coordinates) >= 2:
            seg_id = node["segment_id"]
            segment = {
                "segment_id": seg_id,
                "road_name": node["road_name"],
                "lane_count": node["lane_count"],
                "road_length_m": node["road_length_m"],
                "road_width_m": node["road_width_m"],
                "speed_limit_kmh": node["speed_limit_kmh"],
                "coordinates": osm_coordinates,  # [[lng, lat], ...]
                "congestion_score": 0,
                "traffic_status": "FREE",
                "traffic_color": "#10B981",
                "avg_speed_kmh": 0.0,
                "current_vehicle_count": 0,
                "density_veh_per_km_lane": 0.0,
                "updated_at": datetime.now().isoformat(),
            }
            self.segments[seg_id] = segment
            self._persist_segments()
            print(f"[DataStore] Auto-created segment {seg_id} with {len(osm_coordinates)} OSM coordinates.")

        print(f"[DataStore] Node {edge_id} APPROVED by Admin and persisted to disk.")
        return node

    # ─── Approved Nodes API ───────────────────────────────────────────────────

    def _enrich_node(self, node: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not node:
            return None
        n = dict(node)
        seg_id = n.get("segment_id")
        if seg_id and seg_id in self.segments:
            seg = self.segments[seg_id]
            n.setdefault("road_length_m", seg.get("road_length_m", 200.0))
            n.setdefault("road_width_m", seg.get("road_width_m", 7.0))
            n.setdefault("lane_count", seg.get("lane_count", 2))
        return n

    def get_all_nodes(self) -> List[Dict[str, Any]]:
        return [self._enrich_node(n) for n in self.nodes.values() if n is not None]

    def get_node(self, edge_id: str) -> Optional[Dict[str, Any]]:
        return self._enrich_node(self.nodes.get(edge_id))

    def upsert_node(self, node_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cập nhật thông số của một approved node (dùng khi Admin sửa thủ công).
        KHÔNG được dùng để thêm node mới chưa qua approval flow.
        """
        edge_id = node_data.get("edge_id", f"edge-{int(time.time()) % 1000}")
        node_data["edge_id"] = edge_id

        # Normalize nested geo dict
        if "geo" in node_data and isinstance(node_data["geo"], dict):
            geo = node_data["geo"]
            node_data.setdefault("latitude", geo.get("lat"))
            node_data.setdefault("longitude", geo.get("lng"))
            node_data.setdefault("segment_id", geo.get("segment_id"))
            node_data.setdefault("road_name", geo.get("road_name"))
            node_data.setdefault("camera_heading", geo.get("heading", 0.0))
            node_data.setdefault("camera_fov", geo.get("fov", 65.0))
            node_data.setdefault("altitude_m", geo.get("altitude_m", 10.0))

        node_data.setdefault("name", node_data.get("device_name") or f"Camera AI Jetson ({edge_id})")
        node_data.setdefault("camera_id", "camera-01")
        node_data.setdefault("last_seen", datetime.now().isoformat())
        node_data.setdefault("status", "online")
        node_data.setdefault("traffic_status", "FREE")
        node_data.setdefault("congestion_score", 0)

        existing = self.nodes.get(edge_id, {})
        merged = {**existing, **node_data}
        self.nodes[edge_id] = merged
        self._persist_nodes()
        return merged

    def delete_node(self, edge_id: str) -> bool:
        if edge_id in self.nodes:
            del self.nodes[edge_id]
            self._persist_nodes()
            return True
        return False

    # ─── Segments API ─────────────────────────────────────────────────────────

    def get_all_segments(self) -> List[Dict[str, Any]]:
        return list(self.segments.values())

    def get_segment(self, segment_id: str) -> Optional[Dict[str, Any]]:
        return self.segments.get(segment_id)

    def upsert_segment(self, segment_data: Dict[str, Any]) -> Dict[str, Any]:
        seg_id = segment_data.get("segment_id")
        if not seg_id:
            return segment_data
        existing = self.segments.get(seg_id, {})
        merged = {**existing, **segment_data}
        self.segments[seg_id] = merged
        self._persist_segments()
        return merged

    # ─── Telemetry ─────────────────────────────────────────────────────────────

    def update_telemetry(self, edge_id: str, telemetry: Dict[str, Any]):
        """Cập nhật dữ liệu lưu lượng real-time cho approved node."""
        node = self.nodes.get(edge_id)
        if node:
            node["last_seen"] = datetime.now().isoformat()
            node["traffic_status"] = telemetry.get("traffic_status", node.get("traffic_status", "UNKNOWN"))
            node["congestion_score"] = telemetry.get("congestion_score", node.get("congestion_score", 0))
            node["avg_speed_kmh"] = telemetry.get("avg_speed_kmh", node.get("avg_speed_kmh", 0.0))
            node["current_vehicle_count"] = telemetry.get("current_vehicle_count", 0)
            node["stopped_vehicle_count"] = telemetry.get("stopped_vehicle_count", 0)
            node["density_veh_per_km_lane"] = telemetry.get("density_veh_per_km_lane", 0.0)
            raw_counts = telemetry.get("counts_by_class", node.get("counts_by_class", {}))
            node["counts_by_class"] = normalize_counts_by_class(raw_counts)

            # Propagate to segment
            segment_id = node.get("segment_id")
            if segment_id and segment_id in self.segments:
                seg = self.segments[segment_id]
                score = node["congestion_score"]
                seg["congestion_score"] = score
                seg["avg_speed_kmh"] = node["avg_speed_kmh"]
                seg["current_vehicle_count"] = node["current_vehicle_count"]
                seg["traffic_status"] = node["traffic_status"]
                seg["traffic_color"] = "#EF4444" if score >= 65 else ("#F59E0B" if score >= 35 else "#10B981")
                seg["updated_at"] = datetime.now().isoformat()

    def update_node_health(self, edge_id: str, health_data: Dict[str, Any]):
        node = self.nodes.get(edge_id)
        if node:
            node["latest_health"] = health_data
            node["last_seen"] = datetime.now().isoformat()
            node["status"] = "online"

    def update_node_snapshot(self, edge_id: str, snapshot_url: str):
        node = self.nodes.get(edge_id)
        if node:
            node["snapshot_url"] = snapshot_url
            node["last_seen"] = datetime.now().isoformat()

    def add_snapshot_record(self, record: Dict[str, Any]):
        self.history_snapshots.insert(0, record)
        if len(self.history_snapshots) > 200:
            self.history_snapshots.pop()

    # ─── GeoJSON Converters ────────────────────────────────────────────────────

    def get_nodes_geojson(self) -> Dict[str, Any]:
        features = []
        for n in self.nodes.values():
            lat = n.get("latitude")
            lng = n.get("longitude")
            if lat is None or lng is None:
                continue  # Bỏ qua node chưa có tọa độ (không nên xảy ra với approved nodes)
            score = n.get("congestion_score", 0)
            status = n.get("status", "offline")
            color = "#9CA3AF" if status == "offline" else ("#EF4444" if score >= 65 else ("#F59E0B" if score >= 35 else "#10B981"))
            seg = self.segments.get(n.get("segment_id", ""), {})

            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(lng), float(lat)]},
                "properties": {
                    "edge_id": n.get("edge_id"),
                    "name": n.get("name"),
                    "camera_id": n.get("camera_id"),
                    "segment_id": n.get("segment_id"),
                    "road_name": n.get("road_name"),
                    "lane_count": n.get("lane_count") or seg.get("lane_count", 2),
                    "road_length_m": n.get("road_length_m") or seg.get("road_length_m", 200.0),
                    "road_width_m": n.get("road_width_m") or seg.get("road_width_m", 7.0),
                    "heading": float(n.get("camera_heading", 0.0)),
                    "fov": float(n.get("camera_fov", 60.0)),
                    "status": status,
                    "traffic_status": n.get("traffic_status", "UNKNOWN"),
                    "congestion_score": score,
                    "avg_speed_kmh": n.get("avg_speed_kmh", 0.0),
                    "vehicle_count": n.get("current_vehicle_count", 0),
                    "marker_color": color,
                    "snapshot_url": n.get("snapshot_url"),
                    "last_seen": n.get("last_seen"),
                }
            })
        return {"type": "FeatureCollection", "features": features}

    def get_segments_geojson(self) -> Dict[str, Any]:
        features = []
        for s in self.segments.values():
            coords = s.get("coordinates", [])
            if len(coords) < 2:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "segment_id": s.get("segment_id"),
                    "road_name": s.get("road_name"),
                    "lane_count": s.get("lane_count", 2),
                    "road_length_m": s.get("road_length_m", 200.0),
                    "road_width_m": s.get("road_width_m", 7.0),
                    "speed_limit_kmh": s.get("speed_limit_kmh", 60.0),
                    "congestion_score": s.get("congestion_score", 0),
                    "traffic_status": s.get("traffic_status", "FREE"),
                    "traffic_color": s.get("traffic_color", "#10B981"),
                    "avg_speed_kmh": s.get("avg_speed_kmh", 0.0),
                    "vehicle_count": s.get("current_vehicle_count", 0),
                    "updated_at": s.get("updated_at"),
                }
            })
        return {"type": "FeatureCollection", "features": features}


store = DataStore()
