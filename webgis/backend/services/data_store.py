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
import os
import re
import threading
import time
import uuid
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
NODE_STATE_CACHE_FILE = DATA_DIR / "node_state_cache.json"


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
    """Ghi file JSON an toàn (atomic write với unique temp file và retry chống Windows file lock)."""
    tmp = None
    try:
        tmp = path.with_name(f"{path.stem}_{uuid.uuid4().hex[:8]}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        for attempt in range(4):
            try:
                tmp.replace(path)
                tmp = None
                break
            except PermissionError:
                if attempt < 3:
                    time.sleep(0.04 * (attempt + 1))
                else:
                    raise
    except Exception as e:
        print(f"[DataStore] Cannot save {path.name}: {e}")
    finally:
        if tmp and tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


# ─── Seed data cho đoạn đường mẫu ─────────────────────────────────────────────
INITIAL_SEGMENTS: List[Dict[str, Any]] = []  # Không tạo segment giả sẵn


class DataStore:
    """In-memory data store với hệ thống xác nhận thiết bị 2 giai đoạn."""

    def __init__(self):
        self._lock = threading.RLock()
        # ── Approved nodes: đã được Admin phê duyệt, vẽ lên bản đồ ──────────
        saved_nodes = _load_json_file(APPROVED_NODES_FILE)
        self.nodes: Dict[str, Dict[str, Any]] = saved_nodes
        print(f"[DataStore] Loaded {len(self.nodes)} approved node(s) from disk.")

        # ── Khôi phục snapshot trạng thái gần nhất nếu có (Persistent State) ──
        self._last_cache_save = 0.0
        saved_cache = _load_json_file(NODE_STATE_CACHE_FILE)
        if saved_cache and isinstance(saved_cache, dict):
            restored_count = 0
            for edge_id, cached in saved_cache.items():
                if edge_id in self.nodes:
                    node = self.nodes[edge_id]
                    for k in (
                        "traffic_status", "congestion_score", "avg_speed_kmh",
                        "current_vehicle_count", "stopped_vehicle_count",
                        "density_veh_per_km_lane", "counts_by_class",
                        "traffic", "system", "latest_health", "last_seen", "status"
                    ):
                        if k in cached and cached[k] is not None:
                            node[k] = cached[k]
                    restored_count += 1
            print(f"[DataStore] Restored live state snapshot for {restored_count} node(s) from disk cache.")

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

    # ─── ZTP & Auto-Increment Naming (Zero-Touch Provisioning) ─────────────

    def generate_next_identifiers(self) -> Dict[str, str]:
        """Tự động tìm số thứ tự lớn nhất hiện có và sinh mã tăng dần: EDGE_xxx, CAM_xxx, SEG_xxx."""
        existing_numbers = []
        for eid in list(self.nodes.keys()) + list(self.pending_nodes.keys()):
            match = re.search(r"(\d+)$", str(eid))
            if match:
                existing_numbers.append(int(match.group(1)))

        next_idx = (max(existing_numbers) + 1) if existing_numbers else 1
        formatted_idx = f"{next_idx:03d}"

        return {
            "edge_id": f"EDGE_{formatted_idx}",
            "camera_id": f"CAM_{formatted_idx}",
            "segment_id": f"SEG_{formatted_idx}",
            "sequence_number": next_idx,
        }

    def process_ztp_announcement(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Xử lý bản tin tự động báo danh từ Jetson (traffic/discovery/announce)."""
        mac_addr = payload.get("mac_address")
        if not mac_addr and isinstance(payload.get("hardware_profile"), dict):
            mac_addr = payload["hardware_profile"].get("mac_address")
        if not mac_addr and isinstance(payload.get("network"), dict):
            mac_addr = payload["network"].get("mac_address")

        if mac_addr:
            mac_addr = str(mac_addr).strip().upper()
            payload["mac_address"] = mac_addr

        # 1. Kiểm tra trong danh sách Approved Nodes (Đã quản lý trước đó -> Auto-resume)
        approved = self.get_node_by_mac(mac_addr) if mac_addr else None
        if not approved and payload.get("edge_id"):
            approved = self.get_node(payload.get("edge_id"))

        if approved:
            target_id = approved["edge_id"]
            node = self.nodes[target_id]
            node["status"] = "online"
            node["last_seen"] = datetime.now().isoformat()
            if mac_addr:
                node["mac_address"] = mac_addr
            if payload.get("ip_address"):
                node["ip_address"] = payload["ip_address"]
            if payload.get("hardware_profile"):
                node["hardware_profile"] = payload["hardware_profile"]
            self._persist_nodes()
            print(f"[ZTP RESUME] Thiết bị quen thuộc '{target_id}' (MAC: {mac_addr or 'N/A'}) đã online trở lại.")
            return {"action": "resumed", "edge_id": target_id, "node": node}

        # 2. Kiểm tra trong danh sách Pending Nodes
        pending_id = None
        for pid, pdata in self.pending_nodes.items():
            if mac_addr and pdata.get("mac_address") == mac_addr:
                pending_id = pid
                break

        if pending_id:
            self.touch_pending(pending_id, payload)
            print(f"[ZTP PENDING UPDATE] Cập nhật thông số cho thiết bị chờ '{pending_id}' (MAC: {mac_addr})")
            return {"action": "pending_updated", "edge_id": pending_id, "node": self.pending_nodes[pending_id]}

        # 3. Thiết bị mới hoàn toàn: Cấp phát tự động mã tăng dần
        ids = self.generate_next_identifiers()
        assigned_edge_id = ids["edge_id"]

        pending_data = {
            "edge_id": assigned_edge_id,
            "camera_id": ids["camera_id"],
            "segment_id": ids["segment_id"],
            "mac_address": mac_addr,
            "ip_address": payload.get("ip_address"),
            "hardware_profile": payload.get("hardware_profile", {}),
            "spatial_config": payload.get("default_spatial", {}),
            "raw_payload": payload,
            "name": f"Trạm Camera AI ({assigned_edge_id})",
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "status": "pending_setup",
        }
        self.pending_nodes[assigned_edge_id] = pending_data
        print(f"[ZTP NEW DISCOVERY] Cấp phát tự động {assigned_edge_id} cho MAC: {mac_addr or 'unknown'}")
        return {"action": "discovered_created", "edge_id": assigned_edge_id, "node": pending_data}

    # ─── Pending Node API ─────────────────────────────────────────────────────

    def add_pending_node(self, edge_id: str, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Thêm thiết bị Jetson vào hàng chờ phê duyệt.
        KHÔNG tự động gán tọa độ mặc định.
        Chỉ lưu thông tin kỹ thuật do Jetson tự báo cáo.
        """
        mac_address = raw_data.get("mac_address")
        if not mac_address and isinstance(raw_data.get("latest_health"), dict):
            mac_address = raw_data["latest_health"].get("network", {}).get("mac_address")
        if not mac_address and isinstance(raw_data.get("network"), dict):
            mac_address = raw_data["network"].get("mac_address")
        if not mac_address and isinstance(raw_data.get("raw_payload"), dict):
            mac_address = raw_data["raw_payload"].get("mac_address")

        pending = {
            "edge_id": edge_id,
            "mac_address": str(mac_address).strip().upper() if mac_address else None,
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
            new_mac = payload.get("mac_address")
            if new_mac and not self.pending_nodes[edge_id].get("mac_address"):
                self.pending_nodes[edge_id]["mac_address"] = str(new_mac).strip().upper()
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
        mac_address = (
            approved_data.get("mac_address")
            or raw.get("mac_address")
            or (raw.get("raw_payload", {}).get("mac_address") if isinstance(raw.get("raw_payload"), dict) else None)
        )
        if mac_address:
            mac_address = str(mac_address).strip().upper()

        node = {
            # Thông tin từ Jetson (raw)
            "edge_id": edge_id,
            "mac_address": mac_address,
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

    def get_node_by_mac(self, mac_address: Optional[str]) -> Optional[Dict[str, Any]]:
        """Tìm approved node theo địa chỉ phần cứng MAC (hỗ trợ cả chuẩn có dấu hai chấm và clean hex)."""
        if not mac_address:
            return None
        target = str(mac_address).replace(":", "").replace("-", "").strip().upper()
        if not target or target == "000000000000":
            return None
        for edge_id, node in self.nodes.items():
            if not isinstance(node, dict):
                continue
            candidates = []
            if node.get("mac_address"):
                candidates.append(str(node.get("mac_address")).replace(":", "").replace("-", "").strip().upper())
            if isinstance(node.get("latest_health"), dict):
                net_mac = node["latest_health"].get("network", {}).get("mac_address")
                if net_mac:
                    candidates.append(str(net_mac).replace(":", "").replace("-", "").strip().upper())
            if target in candidates:
                return self._enrich_node(node)
        return None

    def get_pending_by_mac(self, mac_address: Optional[str]) -> Optional[Dict[str, Any]]:
        """Tìm pending node theo địa chỉ phần cứng MAC (hỗ trợ cả chuẩn có dấu hai chấm và clean hex)."""
        if not mac_address:
            return None
        target = str(mac_address).replace(":", "").replace("-", "").strip().upper()
        if not target or target == "000000000000":
            return None
        for edge_id, pending in self.pending_nodes.items():
            if not isinstance(pending, dict):
                continue
            mac = str(pending.get("mac_address") or "").replace(":", "").replace("-", "").strip().upper()
            if mac and mac == target:
                return pending
        return None

    def upsert_node(self, node_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cập nhật thông số của một approved node (dùng khi Admin sửa thủ công).
        KHÔNG được dùng để thêm node mới chưa qua approval flow.
        """
        edge_id = node_data.get("edge_id", f"edge-{int(time.time()) % 1000}")
        node_data["edge_id"] = edge_id

        # Preserve existing mac_address if present
        if not node_data.get("mac_address") and edge_id in self.nodes:
            existing_mac = self.nodes[edge_id].get("mac_address")
            if existing_mac:
                node_data["mac_address"] = existing_mac

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

    # ─── State Cache & Watchdog Helpers ───────────────────────────────────────

    def _save_state_cache(self, force: bool = False):
        """Lưu snapshot trạng thái động hiện tại xuống file cache (debounce 3s, thread-safe)."""
        now = time.time()
        if not force and (now - self._last_cache_save < 3.0):
            return
        self._last_cache_save = now
        snapshot = {}
        with self._lock:
            nodes_items = list(self.nodes.items())
        for edge_id, node in nodes_items:
            snapshot[edge_id] = {
                "edge_id": edge_id,
                "status": node.get("status", "offline"),
                "last_seen": node.get("last_seen"),
                "traffic_status": node.get("traffic_status", "FREE"),
                "congestion_score": node.get("congestion_score", 0),
                "avg_speed_kmh": node.get("avg_speed_kmh", 0.0),
                "current_vehicle_count": node.get("current_vehicle_count", 0),
                "stopped_vehicle_count": node.get("stopped_vehicle_count", 0),
                "density_veh_per_km_lane": node.get("density_veh_per_km_lane", 0.0),
                "counts_by_class": node.get("counts_by_class", {}),
                "latest_health": node.get("latest_health"),
                "traffic": node.get("traffic", {}),
                "system": node.get("system", {}),
            }
        _save_json_file(NODE_STATE_CACHE_FILE, snapshot)

    def set_node_status(self, edge_id: str, status: str):
        """Watchdog cập nhật trạng thái node (vd: 'offline')."""
        with self._lock:
            node = self.nodes.get(edge_id)
            if node:
                node["status"] = status
        self._save_state_cache(force=True)

    def get_live_states(self) -> Dict[str, Any]:
        """Trả về toàn bộ snapshot trạng thái động hiện tại của tất cả approved nodes."""
        states = {}
        with self._lock:
            nodes_items = list(self.nodes.items())
        for edge_id, node in nodes_items:
            states[edge_id] = {
                "edge_id": edge_id,
                "name": node.get("name"),
                "status": node.get("status", "offline"),
                "last_seen": node.get("last_seen"),
                "traffic_status": node.get("traffic_status", "FREE"),
                "congestion_score": node.get("congestion_score", 0),
                "avg_speed_kmh": node.get("avg_speed_kmh", 0.0),
                "current_vehicle_count": node.get("current_vehicle_count", 0),
                "stopped_vehicle_count": node.get("stopped_vehicle_count", 0),
                "density_veh_per_km_lane": node.get("density_veh_per_km_lane", 0.0),
                "counts_by_class": node.get("counts_by_class", {}),
                "traffic": node.get("traffic", {}),
                "system": node.get("system", {}),
                "latest_health": node.get("latest_health"),
                "coordinates": [float(node.get("longitude", 106.65)), float(node.get("latitude", 10.84))]
            }
        return states

    # ─── Telemetry ─────────────────────────────────────────────────────────────

    def update_telemetry(self, edge_id: str, telemetry: Dict[str, Any]):
        """Cập nhật dữ liệu lưu lượng real-time cho approved node (Deep Merge, Thread-Safe)."""
        with self._lock:
            node = self.nodes.get(edge_id)
            if node:
                node["last_seen"] = datetime.now().isoformat()
                node["status"] = "online"
                node["traffic_status"] = telemetry.get("traffic_status", node.get("traffic_status", "UNKNOWN"))
                node["congestion_score"] = telemetry.get("congestion_score", node.get("congestion_score", 0))
                node["avg_speed_kmh"] = telemetry.get("avg_speed_kmh", node.get("avg_speed_kmh", 0.0))
                node["current_vehicle_count"] = telemetry.get("current_vehicle_count", 0)
                node["stopped_vehicle_count"] = telemetry.get("stopped_vehicle_count", 0)
                node["density_veh_per_km_lane"] = telemetry.get("density_veh_per_km_lane", 0.0)
                raw_counts = telemetry.get("counts_by_class", node.get("counts_by_class", {}))
                node["counts_by_class"] = normalize_counts_by_class(raw_counts)

                # Chuẩn hóa cấu trúc lồng node["traffic"]
                node["traffic"] = {
                    "vehicle_count": node["current_vehicle_count"],
                    "average_speed": node["avg_speed_kmh"],
                    "congestion_level": node["traffic_status"],
                    "congestion_score": node["congestion_score"],
                    "stopped_vehicle_count": node["stopped_vehicle_count"],
                    "density_veh_per_km_lane": node["density_veh_per_km_lane"],
                    "counts_by_class": node["counts_by_class"]
                }

                # Nếu telemetry gửi kèm edge_metrics (CPU, GPU, RAM, Temp) thì gộp vào nhánh system
                edge_metrics = telemetry.get("edge_metrics")
                if edge_metrics and isinstance(edge_metrics, dict):
                    node.setdefault("system", {})
                    node["system"].update({
                        "cpu_usage": edge_metrics.get("cpu_percent") or edge_metrics.get("cpu_usage_pct") or node["system"].get("cpu_usage", 0.0),
                        "gpu_usage": edge_metrics.get("gpu_percent") or edge_metrics.get("gpu_usage_pct") or node["system"].get("gpu_usage", 0.0),
                        "ram_usage": edge_metrics.get("ram_percent") or edge_metrics.get("ram_usage_pct") or node["system"].get("ram_usage", 0.0),
                        "temperature": edge_metrics.get("temperature_c") or node["system"].get("temperature", 0.0),
                        "fps": edge_metrics.get("fps") or node["system"].get("fps", 0.0),
                    })

                # Propagate to segment
                segment_id = node.get("segment_id") or telemetry.get("segment_id")
                if segment_id and segment_id in self.segments:
                    seg = self.segments[segment_id]
                    score = node["congestion_score"]
                    seg["congestion_score"] = score
                    seg["avg_speed_kmh"] = node["avg_speed_kmh"]
                    seg["current_vehicle_count"] = node["current_vehicle_count"]
                    seg["traffic_status"] = node["traffic_status"]
                    seg["traffic_color"] = "#EF4444" if score >= 65 else ("#F59E0B" if score >= 35 else "#10B981")
                    seg["updated_at"] = datetime.now().isoformat()

        self._save_state_cache()

    def update_node_health(self, edge_id: str, health_data: Dict[str, Any]):
        node = self.nodes.get(edge_id)
        if node:
            node["latest_health"] = health_data
            node["last_seen"] = datetime.now().isoformat()
            node["status"] = "online"

            # Cập nhật vào cấu trúc lồng node["system"]
            hw = health_data.get("hardware", {})
            node.setdefault("system", {})
            node["system"].update({
                "cpu_usage": hw.get("cpu_usage_pct", node["system"].get("cpu_usage", 0.0)),
                "gpu_usage": hw.get("gpu_usage_pct", node["system"].get("gpu_usage", 0.0)),
                "ram_usage": hw.get("ram_usage_pct", node["system"].get("ram_usage", 0.0)),
                "temperature": hw.get("temperature_c", node["system"].get("temperature", 0.0)),
                "fps": hw.get("fps", node["system"].get("fps", 0.0)),
            })
            self._save_state_cache()

    def update_node_snapshot(self, edge_id: str, snapshot_url: str):
        node = self.nodes.get(edge_id)
        if node:
            node["snapshot_url"] = snapshot_url
            node["last_seen"] = datetime.now().isoformat()
            self._save_state_cache()

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
