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
import os
import re
import sqlite3
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
HISTORY_DB_FILE = DATA_DIR / "history.db"

# Cột trung bình theo phút phục vụ dự báo (score/vehicle/density/flow...).
# speed_sample_count đếm riêng số mẫu có vận tốc (vận tốc có thể NULL khi đường vắng).
TIMELINE_FEATURE_COLUMNS = (
    ("algorithm_version", "TEXT"),
    ("score_sample_count", "INTEGER DEFAULT 0"),
    ("score_mean", "REAL"),
    ("vehicle_count_mean", "REAL"),
    ("density_mean", "REAL"),
    ("density_pce_mean", "REAL"),
    ("entry_rate_mean", "REAL"),
    ("flow_mean", "REAL"),
    ("stopped_ratio_mean", "REAL"),
    ("speed_sample_count", "INTEGER DEFAULT 0"),
)

SPI_FIELDS = (
    "algorithm_version", "method", "spi", "spi_level", "traffic_state",
    "reference_speed_kmh", "score_thresholds", "speed_ratio_percent",
    "speed_reduction_index", "valid_speed_tracks", "status_pending",
    "status_pending_seconds", "status_confirm_seconds", "raw_traffic_status",
    "representative_speed_kmh", "representative_speed_method", "hcm_los_proxy",
    "free_flow_speed_kmh", "data_quality", "reason", "stopped_ratio", "pce",
    "spi_thresholds", "raw_traffic_state", "stable_traffic_state", "minimum_valid_tracks",
    "hcm_los_proxy_is_official", "hcm_los_proxy_thresholds", "density_pce_per_km_lane",
    "density_pcu_per_km_lane", "pcu_weight_basis",
    "median_speed_kmh", "forecast",
)


def _spi_fields(data):
    return {key: data.get(key) for key in SPI_FIELDS}


def _float_or_none(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _init_history_db(db_path: Path):
    """Khởi tạo cấu trúc bảng SQLite cho lịch sử ùn tắc và snapshot (Fix D1, D3)."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS traffic_timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    segment_id TEXT NOT NULL,
                    minute_bucket TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    time_str TEXT NOT NULL,
                    road_name TEXT,
                    congestion_score INTEGER,
                    avg_speed_kmh REAL,
                    traffic_status TEXT,
                    traffic_color TEXT,
                    vehicle_count INTEGER,
                    sample_count INTEGER DEFAULT 1,
                    UNIQUE(segment_id, minute_bucket)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timeline_seg_time ON traffic_timeline(segment_id, timestamp);")

            # Bổ sung cột đặc trưng trung bình theo phút cho module dự báo (D2).
            # ALTER TABLE ADD COLUMN để DB cũ vẫn dùng được, không mất dữ liệu.
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(traffic_timeline)")}
            for col_name, col_type in TIMELINE_FEATURE_COLUMNS:
                if col_name not in existing_cols:
                    conn.execute("ALTER TABLE traffic_timeline ADD COLUMN %s %s" % (col_name, col_type))
            if "score_sample_count" not in existing_cols:
                # Historical mixed buckets cannot be reconstructed. Exclude buckets
                # whose latest status was UNKNOWN rather than interpreting zero as free.
                conn.execute("""UPDATE traffic_timeline SET score_sample_count =
                    CASE WHEN traffic_status IN ('FREE', 'SLOW', 'CONGESTED')
                    THEN sample_count ELSE 0 END,
                    score_mean = CASE WHEN traffic_status IN ('FREE', 'SLOW', 'CONGESTED')
                    THEN COALESCE(score_mean, congestion_score) ELSE NULL END""")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS congestion_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT UNIQUE NOT NULL,
                    edge_id TEXT NOT NULL,
                    camera_id TEXT,
                    segment_id TEXT,
                    timestamp TEXT NOT NULL,
                    captured_at TEXT,
                    received_at TEXT,
                    time_str TEXT NOT NULL,
                    location_name TEXT,
                    traffic_status TEXT,
                    congestion_score INTEGER,
                    avg_speed_kmh REAL,
                    vehicle_count INTEGER,
                    image_url TEXT NOT NULL,
                    trigger_reason TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_seg_time ON congestion_snapshots(segment_id, timestamp);")
    finally:
        conn.close()


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
    """Ghi file JSON an toàn (atomic write với unique temp file, flush+fsync và retry chống Windows file lock) (Fix D4, D8)."""
    tmp = None
    try:
        tmp = path.with_name(f"{path.stem}_{uuid.uuid4().hex[:8]}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        for attempt in range(5):
            try:
                tmp.replace(path)
                tmp = None
                break
            except PermissionError:
                if attempt < 4:
                    time.sleep(0.05 * (attempt + 1))
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

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else HISTORY_DB_FILE
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
                        "traffic", "system", "latest_health", "last_seen", "status",
                        "pipeline_running", "pipeline_pid", "pipeline_source_type",
                        "pipeline_source_name", "last_telemetry_at", "data_status"
                    ):
                        if k in cached and cached[k] is not None:
                            node[k] = cached[k]
                    for key in SPI_FIELDS:
                        if key in cached:
                            node[key] = cached[key]
                    restored_count += 1
            print(f"[DataStore] Restored live state snapshot for {restored_count} node(s) from disk cache.")

        # ── Approved segments: đường thực tế đã được xác nhận ─────────────────
        saved_segments = _load_json_file(APPROVED_SEGMENTS_FILE)
        self.segments: Dict[str, Dict[str, Any]] = saved_segments
        print(f"[DataStore] Loaded {len(self.segments)} segment(s) from disk.")

        # ── Pending nodes: Jetson đã báo cáo, chưa được Admin phê duyệt ──────
        # Không lưu vào file — hàng đợi phát hiện bị reset khi backend khởi động lại.
        self.pending_nodes: Dict[str, Dict[str, Any]] = {}

        # ── SQLite Database cho Timeline & Snapshots (Fix D1, D3) ────────────
        self._db_lock = threading.Lock()
        _init_history_db(self.db_path)

        # Nạp snapshot gần nhất từ SQLite vào RAM cache để phục vụ tức thì
        self.history_snapshots: List[Dict[str, Any]] = self.get_snapshots(limit=200)

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
            if "pipeline_running" in payload:
                node["pipeline_running"] = bool(payload["pipeline_running"])
                node["pipeline_pid"] = payload.get("pipeline_pid")
            else:
                node["pipeline_running"] = False
                node["pipeline_pid"] = None
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
        with self._lock:
            self.pending_nodes[edge_id] = pending
        return pending

    def get_pending_node(self, edge_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            p = self.pending_nodes.get(edge_id)
            return dict(p) if p else None

    def get_all_pending(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(p) for p in self.pending_nodes.values()]

    def touch_pending(self, edge_id: str, payload: Dict[str, Any]):
        """Cập nhật last_seen và thông số mới nhất cho node đang pending."""
        with self._lock:
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
        with self._lock:
            if edge_id in self.pending_nodes:
                del self.pending_nodes[edge_id]
                return True
            return False

    def approve_node(self, edge_id: str, approved_data: Dict[str, Any],
                     assigned_edge_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Admin xác nhận thiết bị: merge thông số Admin cung cấp vào thông tin raw của Jetson,
        chuyển từ pending sang approved, lưu xuống ổ cứng.

        approved_data phải có ít nhất: latitude, longitude, road_name, lane_count.
        """
        with self._lock:
            raw = self.pending_nodes.get(edge_id, {})
            final_id = assigned_edge_id or edge_id  # edge_id = mã thiết bị tự báo (pending); final_id = mã do Web đặt
            mac_address = (
                approved_data.get("mac_address")
                or raw.get("mac_address")
                or (raw.get("raw_payload", {}).get("mac_address") if isinstance(raw.get("raw_payload"), dict) else None)
            )
            if mac_address:
                mac_address = str(mac_address).strip().upper()
            raw_payload = raw.get("raw_payload") if isinstance(raw.get("raw_payload"), dict) else {}
            serial_number = approved_data.get("serial_number") or raw.get("serial_number") or raw_payload.get("serial_number")

            node = {
                # Thông tin từ Jetson (raw)
                "edge_id": final_id,
                "mac_address": mac_address,
                "serial_number": serial_number,
                "actual_hardware_id": (edge_id if final_id != edge_id else None),
                "id_mismatch": final_id != edge_id,
                "name": approved_data.get("name") or raw.get("name") or f"Camera AI Jetson ({final_id})",
                "camera_id": raw.get("camera_id", "camera-01"),
                "model_version": raw.get("model_version", ""),
                # Thông số Admin xác nhận (bắt buộc)
                "latitude": float(approved_data["latitude"]),
                "longitude": float(approved_data["longitude"]),
                "road_name": approved_data.get("road_name", "Chưa xác định"),
                "segment_id": approved_data.get("segment_id", f"seg-{final_id}"),
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
            self.nodes[final_id] = node
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

        print(f"[DataStore] Node {final_id} APPROVED by Admin (device-reported id: {edge_id}) and persisted to disk.")
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
        n.setdefault("pipeline_running", False)
        n.setdefault("pipeline_pid", None)
        n.setdefault("pipeline_source_type", None)
        n.setdefault("pipeline_source_name", None)
        n.setdefault("last_telemetry_at", None)
        n.setdefault("data_status", "idle")
        return n

    def get_all_nodes(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._enrich_node(dict(n)) for n in list(self.nodes.values()) if n is not None]

    def get_node(self, edge_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            node = self.nodes.get(edge_id)
            return self._enrich_node(dict(node)) if node else None

    def get_node_by_mac(self, mac_address: Optional[str]) -> Optional[Dict[str, Any]]:
        """Tìm approved node theo địa chỉ phần cứng MAC (hỗ trợ cả chuẩn có dấu hai chấm và clean hex)."""
        if not mac_address:
            return None
        target = str(mac_address).replace(":", "").replace("-", "").strip().upper()
        if not target or target == "000000000000":
            return None
        with self._lock:
            for edge_id, node in list(self.nodes.items()):
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
                    return self._enrich_node(dict(node))
            return None

    def get_pending_by_mac(self, mac_address: Optional[str]) -> Optional[Dict[str, Any]]:
        """Tìm pending node theo địa chỉ phần cứng MAC (hỗ trợ cả chuẩn có dấu hai chấm và clean hex)."""
        if not mac_address:
            return None
        target = str(mac_address).replace(":", "").replace("-", "").strip().upper()
        if not target or target == "000000000000":
            return None
        with self._lock:
            for edge_id, pending in list(self.pending_nodes.items()):
                if not isinstance(pending, dict):
                    continue
                mac = str(pending.get("mac_address") or "").replace(":", "").replace("-", "").strip().upper()
                if mac and mac == target:
                    return dict(pending)
            return None

    @staticmethod
    def _norm_mac(value) -> str:
        v = str(value or "").replace(":", "").replace("-", "").strip().upper()
        return "" if (not v or v == "000000000000") else v

    def resolve_node(self, edge_id: Optional[str] = None, mac_address: Optional[str] = None,
                     serial_number: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Nhận diện NODE QUẢN TRỊ (mã do Web đặt) từ danh tính mà thiết bị tự báo. Quy tắc DUY NHẤT cho mọi loại tin:
          1) Chỉ xét node có khớp danh tính: serial board (mạnh nhất) > MAC (mac_address / known_macs) > mã id > actual_hardware_id.
          2) Nhiều node cùng khớp (dữ liệu trùng/test) -> ưu tiên node ĐÃ DUYỆT qua Web (có approved_at),
             sau đó điểm khớp cao hơn, sau đó last_seen mới hơn.
        Trả về bản sao node (đã enrich) hoặc None.
        """
        mac = self._norm_mac(mac_address)
        serial = str(serial_number or "").strip()
        best_id, best_key = None, None
        with self._lock:
            for nid, node in self.nodes.items():
                if not isinstance(node, dict):
                    continue
                score = 0
                if serial and str(node.get("serial_number") or "").strip() == serial:
                    score += 100
                if mac:
                    macs = [node.get("mac_address")] + list(node.get("known_macs") or [])
                    if any(self._norm_mac(m) == mac for m in macs):
                        score += 60
                    else:
                        lh = node.get("latest_health")
                        lh_mac = (lh.get("network") or {}).get("mac_address") if isinstance(lh, dict) else None
                        if self._norm_mac(lh_mac) == mac:
                            score += 10
                if edge_id and nid == edge_id:
                    score += 40
                elif edge_id and node.get("actual_hardware_id") == edge_id:
                    score += 20
                if score <= 0:
                    continue
                key = (1 if node.get("approved_at") else 0, score, str(node.get("last_seen") or ""))
                if best_key is None or key > best_key:
                    best_id, best_key = nid, key
            return self._enrich_node(dict(self.nodes[best_id])) if best_id else None

    def log_identity_conflicts(self):
        """Cảnh báo khi nhiều node cùng serial/MAC (thường do dữ liệu test lẫn vào dữ liệu thật)."""
        seen: Dict[Any, List[str]] = {}
        for nid, n in self.nodes.items():
            if not isinstance(n, dict):
                continue
            for kind, val in (("serial", str(n.get("serial_number") or "").strip()),
                              ("mac", self._norm_mac(n.get("mac_address")))):
                if val:
                    seen.setdefault((kind, val), []).append(nid)
        for (kind, val), ids in seen.items():
            if len(ids) > 1:
                print(f"[DataStore] CẢNH BÁO TRÙNG ĐỊNH DANH {kind}={val}: {ids} "
                      f"- chỉ node đã duyệt qua Web (approved_at) được nhận dữ liệu; nên xóa các node thừa/test.")

    def upsert_node(self, node_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cập nhật thông số của một approved node (dùng khi Admin sửa thủ công).
        KHÔNG được dùng để thêm node mới chưa qua approval flow.
        """
        with self._lock:
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
            return dict(merged)

    def delete_node(self, edge_id: str) -> bool:
        with self._lock:
            if edge_id in self.nodes:
                del self.nodes[edge_id]
                self._persist_nodes()
                return True
            return False

    # ─── Segments API ─────────────────────────────────────────────────────────

    def get_all_segments(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(s) for s in list(self.segments.values())]

    def get_segment(self, segment_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            seg = self.segments.get(segment_id)
            return dict(seg) if seg else None

    def upsert_segment(self, segment_data: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            seg_id = segment_data.get("segment_id")
            if not seg_id:
                return segment_data
            existing = self.segments.get(seg_id, {})
            merged = {**existing, **segment_data}
            self.segments[seg_id] = merged
            self._persist_segments()
            return dict(merged)

    def delete_segment(self, segment_id: str) -> bool:
        with self._lock:
            if segment_id in self.segments:
                del self.segments[segment_id]
                self._persist_segments()
                return True
            return False

    # ─── State Cache & Watchdog Helpers ───────────────────────────────────────

    def _save_state_cache(self, force: bool = False):
        """Lưu snapshot trạng thái động hiện tại xuống file cache (debounce 30s, thread-safe) (Fix D4)."""
        now = time.time()
        if not force and (now - self._last_cache_save < 30.0):
            return
        self._last_cache_save = now
        snapshot = {}
        with self._lock:
            nodes_items = list(self.nodes.items())
        for edge_id, node in nodes_items:
            snapshot[edge_id] = {
                **_spi_fields(node),
                "edge_id": edge_id,
                "status": node.get("status", "offline"),
                "last_seen": node.get("last_seen"),
                "traffic_status": node.get("traffic_status", "FREE"),
                "congestion_score": node.get("congestion_score", 0),
                    "algorithm_version": node.get("algorithm_version"),
                    "speed_ratio_percent": node.get("speed_ratio_percent"),
                    "speed_reduction_index": node.get("speed_reduction_index"),
                    "reference_speed_kmh": node.get("reference_speed_kmh"),
                    "data_quality": node.get("data_quality"),
                    "status_pending": node.get("status_pending", False),
                    "status_pending_seconds": node.get("status_pending_seconds", 0.0),
                    "status_confirm_seconds": node.get("status_confirm_seconds", 0.0),
                "avg_speed_kmh": node.get("avg_speed_kmh", 0.0),
                "current_vehicle_count": node.get("current_vehicle_count", 0),
                "stopped_vehicle_count": node.get("stopped_vehicle_count", 0),
                "density_veh_per_km_lane": node.get("density_veh_per_km_lane", 0.0),
                "counts_by_class": node.get("counts_by_class", {}),
                "latest_health": node.get("latest_health"),
                "traffic": node.get("traffic", {}),
                "system": node.get("system", {}),
                "pipeline_running": node.get("pipeline_running", False),
                "pipeline_pid": node.get("pipeline_pid"),
                "pipeline_source_type": node.get("pipeline_source_type"),
                "pipeline_source_name": node.get("pipeline_source_name"),
                "last_telemetry_at": node.get("last_telemetry_at"),
                "data_status": node.get("data_status", "idle"),
            }
        _save_json_file(NODE_STATE_CACHE_FILE, snapshot)

    def set_node_status(self, edge_id: str, status: str):
        """Watchdog cập nhật trạng thái node (vd: 'offline')."""
        with self._lock:
            node = self.nodes.get(edge_id)
            if node:
                node["status"] = status
                if status == "offline":
                    node["pipeline_running"] = False
                    node["data_status"] = "stale"
        if status == "offline":
            self.mark_node_telemetry_stale(edge_id)
        else:
            self._save_state_cache(force=True)

    def mark_node_telemetry_stale(self, edge_id: str):
        """Đánh dấu dữ liệu telemetry của node bị quá hạn (stale), làm mờ/reset trạng thái giao thông (Fix L7)."""
        with self._lock:
            node = self.nodes.get(edge_id)
            if not node:
                return
            node["data_status"] = "stale"
            node["traffic_status"] = "STALE"
            node["congestion_score"] = 0
            node["current_vehicle_count"] = 0
            node["stopped_vehicle_count"] = 0
            node["avg_speed_kmh"] = 0.0
            if "traffic" in node and isinstance(node["traffic"], dict):
                node["traffic"]["congestion_level"] = "STALE"
                node["traffic"]["congestion_score"] = 0
                node["traffic"]["vehicle_count"] = 0
                node["traffic"]["average_speed"] = 0.0

            seg_id = node.get("segment_id")
            if seg_id and seg_id in self.segments:
                seg = self.segments[seg_id]
                seg["traffic_status"] = "STALE"
                seg["congestion_score"] = 0
                seg["current_vehicle_count"] = 0
                seg["traffic_color"] = "#9CA3AF"
                seg["updated_at"] = datetime.now().isoformat()
        self._save_state_cache(force=False)

    def update_pipeline_status(
        self,
        edge_id: str,
        running: bool,
        pid: Optional[int] = None,
        source_type: Optional[str] = None,
        source_name: Optional[str] = None,
    ):
        """Cập nhật trạng thái chạy của AI Pipeline trên Jetson."""
        with self._lock:
            node = self.nodes.get(edge_id)
            if node:
                node["pipeline_running"] = running
                node["pipeline_source_type"] = source_type if running else None
                node["pipeline_source_name"] = source_name if running else None
                if pid is not None:
                    node["pipeline_pid"] = pid
                elif not running:
                    node["pipeline_pid"] = None
                    node["data_status"] = "idle"
        if not running:
            self.mark_node_telemetry_stale(edge_id)
        else:
            self._save_state_cache(force=True)

    def get_live_states(self) -> Dict[str, Any]:
        """Trả về toàn bộ snapshot trạng thái động hiện tại của tất cả approved nodes."""
        states = {}
        with self._lock:
            nodes_items = list(self.nodes.items())
        for edge_id, node in nodes_items:
            states[edge_id] = {
                **_spi_fields(node),
                "edge_id": edge_id,
                "name": node.get("name"),
                "status": node.get("status", "offline"),
                "pipeline_running": node.get("pipeline_running", False),
                "pipeline_pid": node.get("pipeline_pid"),
                "pipeline_source_type": node.get("pipeline_source_type"),
                "pipeline_source_name": node.get("pipeline_source_name"),
                "data_status": node.get("data_status", "idle"),
                "last_telemetry_at": node.get("last_telemetry_at"),
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
                now_iso = datetime.now().isoformat()
                node["last_seen"] = now_iso
                node["last_telemetry_at"] = now_iso
                node["data_status"] = "live"
                node["status"] = "online"
                node["pipeline_running"] = True
                node["traffic_status"] = telemetry.get("traffic_status", node.get("traffic_status", "UNKNOWN"))
                node["congestion_score"] = telemetry.get("congestion_score", node.get("congestion_score", 0))
                node["avg_speed_kmh"] = telemetry.get("avg_speed_kmh", node.get("avg_speed_kmh", 0.0))
                node["current_vehicle_count"] = telemetry.get("current_vehicle_count", 0)
                node["stopped_vehicle_count"] = telemetry.get("stopped_vehicle_count", 0)
                node["density_veh_per_km_lane"] = telemetry.get("density_veh_per_km_lane", 0.0)
                # Clear omitted fields to avoid leaking a previous v3/reference state.
                node.update(_spi_fields(telemetry))
                # V3 indicator fields; congestion_score carries the display-only
                # speed-reduction index for compatibility with existing clients.
                for key in ("algorithm_version", "method", "spi", "spi_level",
                            "traffic_state", "reference_speed_kmh",
                            "speed_ratio_percent", "speed_reduction_index",
                            "status_pending", "status_pending_seconds",
                            "status_confirm_seconds",
                            "valid_speed_tracks", "stopped_ratio", "pce",
                            "data_quality", "reason", "spi_signalized"):
                    if key in telemetry:
                        node[key] = telemetry[key]
                raw_counts = telemetry.get("counts_by_class", node.get("counts_by_class", {}))
                node["counts_by_class"] = normalize_counts_by_class(raw_counts)

                # Chuẩn hóa cấu trúc lồng node["traffic"]
                node["traffic"] = {
                    **_spi_fields(node),
                    "vehicle_count": node["current_vehicle_count"],
                    "average_speed": node["avg_speed_kmh"],
                    "congestion_level": node["traffic_status"],
                    "congestion_score": node["congestion_score"],
                    "stopped_vehicle_count": node["stopped_vehicle_count"],
                    "density_veh_per_km_lane": node["density_veh_per_km_lane"],
                    "counts_by_class": node["counts_by_class"],
                    "algorithm_version": node.get("algorithm_version"),
                    "method": node.get("method"),
                    "spi": node.get("spi"),
                    "spi_level": node.get("spi_level"),
                    "speed_ratio_percent": node.get("speed_ratio_percent"),
                    "speed_reduction_index": node.get("speed_reduction_index"),
                    "status_pending": node.get("status_pending"),
                    "status_pending_seconds": node.get("status_pending_seconds"),
                    "status_confirm_seconds": node.get("status_confirm_seconds"),
                    "reference_speed_kmh": node.get("reference_speed_kmh"),
                    "data_quality": node.get("data_quality"),
                    "reason": node.get("reason"),
                }

                # Nếu telemetry gửi kèm edge_metrics (CPU, GPU, RAM, Temp) thì gộp vào nhánh system & latest_health
                edge_metrics = telemetry.get("edge_metrics")
                if edge_metrics and isinstance(edge_metrics, dict):
                    cpu_pct = edge_metrics.get("cpu_percent") or edge_metrics.get("cpu_usage_pct") or node["system"].get("cpu_usage", 0.0) if "system" in node else (edge_metrics.get("cpu_percent") or edge_metrics.get("cpu_usage_pct") or 0.0)
                    gpu_pct = edge_metrics.get("gpu_percent") or edge_metrics.get("gpu_usage_pct") or node["system"].get("gpu_usage", 0.0) if "system" in node else (edge_metrics.get("gpu_percent") or edge_metrics.get("gpu_usage_pct") or 0.0)
                    ram_pct = edge_metrics.get("ram_percent") or edge_metrics.get("ram_usage_pct") or node["system"].get("ram_usage", 0.0) if "system" in node else (edge_metrics.get("ram_percent") or edge_metrics.get("ram_usage_pct") or 0.0)
                    temp_c = edge_metrics.get("temperature_c") or node["system"].get("temperature", 40.0) if "system" in node else (edge_metrics.get("temperature_c") or 40.0)
                    fps_val = edge_metrics.get("fps") or node["system"].get("fps", 0.0) if "system" in node else (edge_metrics.get("fps") or 0.0)

                    node.setdefault("system", {})
                    node["system"].update({
                        "cpu_usage": cpu_pct,
                        "gpu_usage": gpu_pct,
                        "ram_usage": ram_pct,
                        "temperature": temp_c,
                        "fps": fps_val,
                    })

                    # Cập nhật hoặc khởi tạo cấu trúc latest_health đầy đủ cho modal phần cứng
                    if not node.get("latest_health"):
                        node["latest_health"] = {}
                    lh = node["latest_health"]
                    lh.setdefault("general", {})
                    lh["general"]["service_status"] = "running"
                    lh["general"].setdefault("uptime_seconds", 3600)
                    lh.setdefault("network", {})
                    if node.get("mac_address") and not lh["network"].get("mac_address"):
                        lh["network"]["mac_address"] = node["mac_address"]
                    lh["network"]["status"] = "connected"
                    lh.setdefault("hardware", {})
                    lh["hardware"].update({
                        "cpu_usage_pct": cpu_pct,
                        "gpu_usage_pct": gpu_pct,
                        "ram_usage_pct": ram_pct,
                        "temperature_c": temp_c,
                        "power_mode": lh["hardware"].get("power_mode", "10W_MAXN"),
                    })
                    lh.setdefault("pipeline", {})
                    lh["pipeline"].update({
                        "camera_status": "streaming",
                        "pipeline_fps": fps_val,
                        "inference_latency_ms": round(1000.0 / max(float(fps_val), 1.0), 1) if float(fps_val) > 0 else 0.0,
                    })

                # Propagate to segment
                segment_id = node.get("segment_id") or telemetry.get("segment_id")
                if segment_id and segment_id in self.segments:
                    seg = self.segments[segment_id]
                    seg.update(_spi_fields(node))
                    score = node["congestion_score"]
                    seg["congestion_score"] = score
                    seg["avg_speed_kmh"] = node["avg_speed_kmh"]
                    seg["current_vehicle_count"] = node["current_vehicle_count"]
                    seg["traffic_status"] = node["traffic_status"]
                    seg["traffic_color"] = (
                        "#EF4444" if node["traffic_status"] == "CONGESTED"
                        else "#F59E0B" if node["traffic_status"] == "SLOW"
                        else "#10B981" if node["traffic_status"] == "FREE"
                        else "#6B7280"
                    )
                    for key in ("algorithm_version", "method", "spi", "spi_level",
                                "traffic_state", "reference_speed_kmh",
                                "speed_ratio_percent", "speed_reduction_index",
                                "status_pending", "status_pending_seconds",
                                "status_confirm_seconds",
                                "valid_speed_tracks", "stopped_ratio", "pce",
                                "data_quality", "reason", "spi_signalized"):
                        if key in node:
                            seg[key] = node[key]
                    seg["updated_at"] = datetime.now().isoformat()

                # Ghi nhận và tổng hợp dữ liệu lưu lượng vào SQLite theo phút (Fix D1)
                if segment_id:
                    now_dt = datetime.now()
                    minute_bucket = now_dt.strftime("%Y-%m-%dT%H:%M")
                    time_str = now_dt.strftime("%H:%M")
                    road_name = node.get("name") or (self.segments.get(segment_id, {}).get("road_name") if segment_id in self.segments else "Đoạn đường")
                    score = int(node.get("congestion_score") or 0)
                    # Đường vắng: Edge gửi avg_speed_kmh = null -> lưu NULL, không làm hỏng cả bản ghi phút
                    speed = _float_or_none(node.get("avg_speed_kmh"))
                    status = str(node.get("traffic_status", "FREE"))
                    color = {"CONGESTED": "#EF4444", "SLOW": "#F59E0B", "FREE": "#10B981"}.get(status, "#6B7280")
                    vcount = int(node.get("current_vehicle_count") or 0)

                    self._record_timeline_sample(
                        segment_id=segment_id,
                        minute_bucket=minute_bucket,
                        timestamp=now_dt.isoformat(),
                        time_str=time_str,
                        road_name=road_name,
                        congestion_score=score,
                        avg_speed_kmh=speed,
                        traffic_status=status,
                        traffic_color=color,
                        vehicle_count=vcount,
                        algorithm_version=node.get("algorithm_version"),
                        features={
                            "density": _float_or_none(telemetry.get("density_veh_per_km_lane")) or 0.0,
                            "density_pce": _float_or_none(
                                telemetry.get("density_pce_per_km_lane",
                                              telemetry.get("density_veh_per_km_lane"))) or 0.0,
                            "entry_rate": _float_or_none(telemetry.get("roi_entry_rate_veh_per_min")) or 0.0,
                            "flow": _float_or_none(telemetry.get("estimated_flow_veh_per_min")) or 0.0,
                            "stopped_ratio": _float_or_none(telemetry.get("stopped_vehicle_ratio")) or 0.0,
                        },
                    )

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
        """Lưu bản ghi snapshot vào SQLite DB và cập nhật RAM cache (Fix D1, D3)."""
        with self._db_lock:
            try:
                conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO congestion_snapshots (
                            snapshot_id, edge_id, camera_id, segment_id,
                            timestamp, captured_at, received_at, time_str,
                            location_name, traffic_status, congestion_score,
                            avg_speed_kmh, vehicle_count, image_url, trigger_reason
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        record.get("snapshot_id"),
                        record.get("edge_id"),
                        record.get("camera_id"),
                        record.get("segment_id"),
                        record.get("timestamp"),
                        record.get("captured_at") or record.get("timestamp"),
                        record.get("received_at") or datetime.now().isoformat(),
                        record.get("time_str"),
                        record.get("location_name"),
                        record.get("traffic_status"),
                        record.get("congestion_score", 0),
                        record.get("avg_speed_kmh", 0.0),
                        record.get("vehicle_count", 0),
                        record.get("image_url"),
                        record.get("trigger_reason"),
                    ))
                conn.close()
            except Exception as e:
                print(f"[DataStore] Error saving snapshot to SQLite: {e}")

        # Đồng thời lưu vào in-memory cache để truy cập tức thì
        self.history_snapshots.insert(0, record)
        if len(self.history_snapshots) > 200:
            self.history_snapshots.pop()

    def get_snapshots(self, segment_id: Optional[str] = None, edge_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Truy vấn danh sách snapshots từ SQLite (Fix D1, D3)."""
        try:
            lim = int(limit)
        except Exception:
            lim = 20

        with self._db_lock:
            try:
                conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                query = "SELECT * FROM congestion_snapshots WHERE 1=1"
                params = []
                if segment_id:
                    query += " AND segment_id = ?"
                    params.append(segment_id)
                if edge_id:
                    query += " AND edge_id = ?"
                    params.append(edge_id)
                query += " ORDER BY id DESC LIMIT ?"
                params.append(lim)
                cursor.execute(query, params)
                rows = cursor.fetchall()
                conn.close()
                return [dict(r) for r in rows]
            except Exception as e:
                print(f"[DataStore] Error querying snapshots: {e}")
                results = self.history_snapshots
                if segment_id:
                    results = [s for s in results if s.get("segment_id") == segment_id]
                if edge_id:
                    results = [s for s in results if s.get("edge_id") == edge_id]
                return results[:lim]

    def _record_timeline_sample(self, segment_id: str, minute_bucket: str, timestamp: str,
                                time_str: str, road_name: str, congestion_score: int,
                                avg_speed_kmh: Optional[float], traffic_status: str, traffic_color: str,
                                vehicle_count: int, features: Optional[Dict[str, float]] = None,
                                algorithm_version: Optional[str] = None):
        """Ghi nhận và tổng hợp dữ liệu lưu lượng theo phút vào SQLite (Fix D1).

        congestion_score/vehicle_count/traffic_status giữ giá trị MỚI NHẤT trong phút
        (tương thích biểu đồ cũ). Các cột *_mean là TRUNG BÌNH của mọi mẫu trong phút,
        dùng làm đầu vào cho module dự báo (D2). Trong UPDATE của SQLite mọi biểu thức
        đều đọc giá trị cũ của hàng, nên sample_count ở vế phải là số mẫu trước khi cộng.
        """
        f = features or {}
        has_speed = 1 if avg_speed_kmh is not None else 0
        has_score = int(traffic_status in ("FREE", "SLOW", "CONGESTED"))
        with self._db_lock:
            try:
                conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                with conn:
                    # A/B switches reset this minute's aggregate; never average
                    # incompatible score models. The latest algorithm owns the bucket.
                    conn.execute("""DELETE FROM traffic_timeline
                        WHERE segment_id = ? AND minute_bucket = ?
                        AND algorithm_version IS NOT ?""",
                        (segment_id, minute_bucket, algorithm_version))
                    conn.execute("""
                        INSERT INTO traffic_timeline (
                            segment_id, minute_bucket, timestamp, time_str, road_name,
                            congestion_score, avg_speed_kmh, traffic_status, traffic_color,
                            vehicle_count, sample_count,
                            score_mean, vehicle_count_mean, density_mean, density_pce_mean,
                            entry_rate_mean, flow_mean, stopped_ratio_mean, speed_sample_count,
                            score_sample_count, algorithm_version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(segment_id, minute_bucket) DO UPDATE SET
                            congestion_score = excluded.congestion_score,
                            avg_speed_kmh = CASE
                                WHEN excluded.avg_speed_kmh IS NULL THEN traffic_timeline.avg_speed_kmh
                                WHEN traffic_timeline.avg_speed_kmh IS NULL
                                     OR COALESCE(traffic_timeline.speed_sample_count, 0) = 0
                                    THEN excluded.avg_speed_kmh
                                ELSE ROUND((traffic_timeline.avg_speed_kmh * traffic_timeline.speed_sample_count
                                            + excluded.avg_speed_kmh) / (traffic_timeline.speed_sample_count + 1), 1)
                            END,
                            speed_sample_count = COALESCE(traffic_timeline.speed_sample_count, 0) + excluded.speed_sample_count,
                            vehicle_count = excluded.vehicle_count,
                            traffic_status = excluded.traffic_status,
                            traffic_color = excluded.traffic_color,
                            score_mean = (COALESCE(traffic_timeline.score_mean, 0) * traffic_timeline.score_sample_count + COALESCE(excluded.score_mean, 0)) / NULLIF(traffic_timeline.score_sample_count + excluded.score_sample_count, 0),
                            score_sample_count = traffic_timeline.score_sample_count + excluded.score_sample_count,
                            vehicle_count_mean = (COALESCE(traffic_timeline.vehicle_count_mean, traffic_timeline.vehicle_count) * traffic_timeline.sample_count + excluded.vehicle_count_mean) / (traffic_timeline.sample_count + 1),
                            density_mean = (COALESCE(traffic_timeline.density_mean, excluded.density_mean) * traffic_timeline.sample_count + excluded.density_mean) / (traffic_timeline.sample_count + 1),
                            density_pce_mean = (COALESCE(traffic_timeline.density_pce_mean, excluded.density_pce_mean) * traffic_timeline.sample_count + excluded.density_pce_mean) / (traffic_timeline.sample_count + 1),
                            entry_rate_mean = (COALESCE(traffic_timeline.entry_rate_mean, excluded.entry_rate_mean) * traffic_timeline.sample_count + excluded.entry_rate_mean) / (traffic_timeline.sample_count + 1),
                            flow_mean = (COALESCE(traffic_timeline.flow_mean, excluded.flow_mean) * traffic_timeline.sample_count + excluded.flow_mean) / (traffic_timeline.sample_count + 1),
                            stopped_ratio_mean = (COALESCE(traffic_timeline.stopped_ratio_mean, excluded.stopped_ratio_mean) * traffic_timeline.sample_count + excluded.stopped_ratio_mean) / (traffic_timeline.sample_count + 1),
                            sample_count = traffic_timeline.sample_count + 1,
                            timestamp = excluded.timestamp,
                            time_str = excluded.time_str;
                    """, (
                        segment_id, minute_bucket, timestamp, time_str, road_name,
                        congestion_score, avg_speed_kmh, traffic_status, traffic_color, vehicle_count,
                        float(congestion_score) if has_score else None, float(vehicle_count),
                        float(f.get("density", 0.0)), float(f.get("density_pce", 0.0)),
                        float(f.get("entry_rate", 0.0)), float(f.get("flow", 0.0)),
                        float(f.get("stopped_ratio", 0.0)), has_speed, has_score, algorithm_version,
                    ))
                conn.close()
            except Exception as e:
                print(f"[DataStore] Error updating timeline in SQLite: {e}")

    def get_forecast_series(self, segment_id: str, max_minutes: int = 240) -> List[Dict[str, Any]]:
        """Chuỗi đặc trưng theo phút (cũ -> mới) cho module dự báo, tối đa max_minutes bản ghi gần nhất."""
        with self._db_lock:
            try:
                conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT minute_bucket, timestamp, time_str, algorithm_version,
                           score_mean AS score,
                           avg_speed_kmh AS speed,
                           COALESCE(vehicle_count_mean, vehicle_count) AS vehicles,
                           density_mean AS density, density_pce_mean AS density_pce,
                           entry_rate_mean AS entry_rate, flow_mean AS flow,
                           stopped_ratio_mean AS stopped_ratio, traffic_status, sample_count
                    FROM traffic_timeline
                    WHERE segment_id = ?
                    ORDER BY minute_bucket DESC
                    LIMIT ?
                """, (segment_id, int(max_minutes))).fetchall()
                conn.close()
                return [dict(r) for r in reversed(rows)]
            except Exception as e:
                print(f"[DataStore] Error querying forecast series: {e}")
                return []

    def get_timeline_records(self, segment_id: str = "segment-001", date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Truy vấn chuỗi thời gian 24h từ SQLite cho đoạn đường (Fix D1)."""
        clean_date = date if isinstance(date, str) and date.strip() else None
        with self._db_lock:
            try:
                conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                if clean_date:
                    cursor.execute("""
                        SELECT timestamp, time_str, segment_id, road_name, algorithm_version,
                               congestion_score, avg_speed_kmh, traffic_status,
                               traffic_color, vehicle_count
                        FROM traffic_timeline
                        WHERE segment_id = ? AND timestamp LIKE ?
                        ORDER BY minute_bucket ASC
                    """, (segment_id, f"{clean_date}%"))
                else:
                    cursor.execute("""
                        SELECT timestamp, time_str, segment_id, road_name, algorithm_version,
                               congestion_score, avg_speed_kmh, traffic_status,
                               traffic_color, vehicle_count
                        FROM traffic_timeline
                        WHERE segment_id = ?
                        ORDER BY minute_bucket DESC
                        LIMIT 1440
                    """, (segment_id,))
                rows = cursor.fetchall()
                conn.close()
                # Không lọc theo ngày: lấy 1440 phút GẦN NHẤT (DESC) rồi đảo lại cho biểu đồ cũ -> mới
                if not clean_date:
                    rows = list(reversed(rows))
                return [dict(r) for r in rows]
            except Exception as e:
                print(f"[DataStore] Error querying timeline records: {e}")
                return []

    @property
    def history_records(self) -> List[Dict[str, Any]]:
        """Thuộc tính tương thích ngược cho store.history_records (Fix D1)."""
        return self.get_timeline_records("segment-001")

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
            is_running = n.get("pipeline_running", False)
            data_status = n.get("data_status", "idle")

            if status == "offline":
                color = "#9CA3AF"
            elif not is_running or data_status == "idle":
                color = "#64748B"
            elif data_status == "stale":
                color = "#94A3B8"
            elif n.get("traffic_status") == "CONGESTED":
                color = "#EF4444"
            elif n.get("traffic_status") == "SLOW":
                color = "#F59E0B"
            elif n.get("traffic_status") == "FREE":
                color = "#10B981"
            else:
                color = "#6B7280"
            seg = self.segments.get(n.get("segment_id", ""), {})

            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(lng), float(lat)]},
                "properties": {
                    **_spi_fields(n),
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
                    "pipeline_running": is_running,
                    "pipeline_pid": n.get("pipeline_pid"),
                    "data_status": data_status,
                    "last_telemetry_at": n.get("last_telemetry_at"),
                    "snapshot_url": n.get("snapshot_url"),
                    "last_seen": n.get("last_seen"),
                    "algorithm_version": n.get("algorithm_version"),
                    "method": n.get("method"),
                    "spi": n.get("spi"),
                    "spi_level": n.get("spi_level"),
                    "speed_ratio_percent": n.get("speed_ratio_percent"),
                    "speed_reduction_index": n.get("speed_reduction_index"),
                    "reference_speed_kmh": n.get("reference_speed_kmh"),
                    "valid_speed_tracks": n.get("valid_speed_tracks"),
                    "stopped_ratio": n.get("stopped_ratio"),
                    "pce": n.get("pce"),
                    "data_quality": n.get("data_quality"),
                    "reason": n.get("reason"),
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
                    **_spi_fields(s),
                    "segment_id": s.get("segment_id"),
                    "road_name": s.get("road_name"),
                    "lane_count": s.get("lane_count", 2),
                    "road_length_m": s.get("road_length_m", 200.0),
                    "road_width_m": s.get("road_width_m", 7.0),
                    "speed_limit_kmh": s.get("speed_limit_kmh", 60.0),
                    "congestion_score": s.get("congestion_score", 0),
                    "traffic_status": s.get("traffic_status", "FREE"),
                    "traffic_color": ("#6B7280" if s.get("traffic_status") == "UNKNOWN"
                                      else s.get("traffic_color", "#6B7280")),
                    "avg_speed_kmh": s.get("avg_speed_kmh", 0.0),
                    "vehicle_count": s.get("current_vehicle_count", 0),
                    "updated_at": s.get("updated_at"),
                    "algorithm_version": s.get("algorithm_version"),
                    "method": s.get("method"),
                    "spi": s.get("spi"),
                    "spi_level": s.get("spi_level"),
                    "speed_ratio_percent": s.get("speed_ratio_percent"),
                    "speed_reduction_index": s.get("speed_reduction_index"),
                    "reference_speed_kmh": s.get("reference_speed_kmh"),
                    "data_quality": s.get("data_quality"),
                }
            })
        return {"type": "FeatureCollection", "features": features}


import sys

# Singleton instance
if "webgis.backend.services.data_store" in sys.modules and hasattr(sys.modules["webgis.backend.services.data_store"], "store"):
    store = sys.modules["webgis.backend.services.data_store"].store
elif "services.data_store" in sys.modules and hasattr(sys.modules["services.data_store"], "store"):
    store = sys.modules["services.data_store"].store
else:
    store = DataStore()

_curr_mod = sys.modules.get(__name__)
if _curr_mod:
    sys.modules["services.data_store"] = _curr_mod

try:
    store.log_identity_conflicts()
except Exception:
    pass
    sys.modules["webgis.backend.services.data_store"] = _curr_mod
