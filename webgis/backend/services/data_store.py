import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# Initial Seed Data for Road Segments (LineString GeoJSON)
INITIAL_SEGMENTS = [
    {
        "segment_id": "segment-tohuu-01",
        "road_name": "Đường Tố Hữu (Lilama 10 ➔ HH2 Bắc Hà)",
        "lane_count": 3,
        "road_length_m": 310.0,
        "road_width_m": 10.0,
        "speed_limit_kmh": 60.0,
        "coordinates": [
            [105.789650, 20.998850],
            [105.790900, 20.999700],
            [105.792000, 21.000450]
        ],
        "congestion_score": 20,
        "traffic_status": "FREE",
        "traffic_color": "#10B981",
        "avg_speed_kmh": 44.5,
        "current_vehicle_count": 12,
        "density_veh_per_km_lane": 18.2,
        "updated_at": datetime.now().isoformat()
    },
    {
        "segment_id": "segment-tohuu-02",
        "road_name": "Đường Tố Hữu (Khu vực Tòa HH2 Bắc Hà)",
        "lane_count": 3,
        "road_length_m": 215.0,
        "road_width_m": 10.0,
        "speed_limit_kmh": 60.0,
        "coordinates": [
            [105.792000, 21.000450],
            [105.792850, 21.001020],
            [105.793750, 21.001620]
        ],
        "congestion_score": 85,
        "traffic_status": "CONGESTED",
        "traffic_color": "#EF4444",
        "avg_speed_kmh": 9.2,
        "current_vehicle_count": 48,
        "density_veh_per_km_lane": 88.5,
        "updated_at": datetime.now().isoformat()
    },
    {
        "segment_id": "segment-tohuu-03",
        "road_name": "Đường Tố Hữu (Ng. 14 Vũ Hữu ➔ Khuất Duy Tiến)",
        "lane_count": 3,
        "road_length_m": 265.0,
        "road_width_m": 10.0,
        "speed_limit_kmh": 60.0,
        "coordinates": [
            [105.793750, 21.001620],
            [105.794750, 21.002280],
            [105.795800, 21.002980]
        ],
        "congestion_score": 50,
        "traffic_status": "SLOW",
        "traffic_color": "#F59E0B",
        "avg_speed_kmh": 22.8,
        "current_vehicle_count": 28,
        "density_veh_per_km_lane": 48.0,
        "updated_at": datetime.now().isoformat()
    },
    {
        "segment_id": "segment-001",
        "road_name": "Đường Nguyễn Trãi (Hướng đi Hà Đông)",
        "lane_count": 4,
        "road_length_m": 450.0,
        "road_width_m": 16.0,
        "speed_limit_kmh": 60.0,
        "coordinates": [
            [105.798100, 20.999500],
            [105.795123, 20.998412],
            [105.792500, 20.997200],
            [105.789800, 20.995900]
        ],
        "congestion_score": 78,
        "traffic_status": "CONGESTED",
        "traffic_color": "#EF4444",
        "avg_speed_kmh": 12.8,
        "current_vehicle_count": 36,
        "density_veh_per_km_lane": 82.5,
        "updated_at": datetime.now().isoformat()
    }
]

# Initial Seed Data for Edge Camera Nodes (Point GeoJSON)
INITIAL_NODES = [
    {
        "edge_id": "edge-tohuu",
        "name": "Camera AI Tòa HH2 Bắc Hà (P. Tố Hữu)",
        "camera_id": "camera-tohuu-01",
        "segment_id": "segment-tohuu-02",
        "road_name": "Đường Tố Hữu",
        "latitude": 21.001150,
        "longitude": 105.792550,
        "altitude_m": 15.0,
        "camera_heading": 55.0,
        "camera_fov": 65.0,
        "status": "online",
        "traffic_status": "CONGESTED",
        "congestion_score": 85,
        "avg_speed_kmh": 9.2,
        "current_vehicle_count": 48,
        "stopped_vehicle_count": 18,
        "density_veh_per_km_lane": 88.5,
        "counts_by_class": {
            "motorcycle": 32,
            "car": 12,
            "bus": 3,
            "truck": 1
        },
        "last_seen": datetime.now().isoformat(),
        "latest_health": {
            "general": {"uptime_seconds": 214500, "service_status": "running"},
            "network": {"local_ip": "192.168.1.108", "mac_address": "48:B0:2D:AA:BB:CC", "status": "connected"},
            "hardware": {
                "cpu_usage_pct": 68,
                "cpu_cores": 4,
                "ram_used_mb": 2980,
                "ram_total_mb": 3964,
                "ram_usage_pct": 75,
                "swap_used_mb": 310,
                "swap_total_mb": 2048,
                "gpu_usage_pct": 89,
                "temperature_c": 63.8,
                "power_mode": "10W_MAXN"
            },
            "storage": {"disk_total_gb": 29.5, "disk_free_gb": 15.2, "disk_usage_pct": 48, "outbox_unsent_images": 0},
            "pipeline": {"camera_status": "streaming", "pipeline_fps": 25.0, "inference_latency_ms": 39.5}
        },
        "snapshot_url": "https://images.unsplash.com/photo-1568605117036-5fe5e7bab0b7?auto=format&fit=crop&w=800&q=80"
    },
    {
        "edge_id": "edge-01",
        "name": "Camera Nút giao Nguyễn Trãi - Khuất Duy Tiến",
        "camera_id": "camera-01",
        "segment_id": "segment-001",
        "road_name": "Đường Nguyễn Trãi",
        "latitude": 20.998412,
        "longitude": 105.795123,
        "altitude_m": 12.5,
        "camera_heading": 45.0,
        "camera_fov": 65.0,
        "status": "online",
        "traffic_status": "CONGESTED",
        "congestion_score": 78,
        "avg_speed_kmh": 12.8,
        "current_vehicle_count": 36,
        "stopped_vehicle_count": 14,
        "density_veh_per_km_lane": 82.5,
        "counts_by_class": {
            "motorcycle": 24,
            "car": 9,
            "bus": 2,
            "truck": 1
        },
        "last_seen": datetime.now().isoformat(),
        "latest_health": {
            "general": {"uptime_seconds": 184500, "service_status": "running"},
            "network": {"local_ip": "192.168.1.105", "mac_address": "48:B0:2D:1A:2B:3C", "status": "connected"},
            "hardware": {
                "cpu_usage_pct": 64,
                "cpu_cores": 4,
                "ram_used_mb": 2840,
                "ram_total_mb": 3964,
                "ram_usage_pct": 71,
                "swap_used_mb": 412,
                "swap_total_mb": 2048,
                "gpu_usage_pct": 86,
                "temperature_c": 62.4,
                "power_mode": "10W_MAXN"
            },
            "storage": {"disk_total_gb": 29.5, "disk_free_gb": 16.4, "disk_usage_pct": 44, "outbox_unsent_images": 0},
            "pipeline": {"camera_status": "streaming", "pipeline_fps": 24.5, "inference_latency_ms": 40.8}
        },
        "snapshot_url": "https://images.unsplash.com/photo-1568605117036-5fe5e7bab0b7?auto=format&fit=crop&w=800&q=80"
    },
    {
        "edge_id": "edge-02",
        "name": "Camera Vành Đai 3 - Khuất Duy Tiến",
        "camera_id": "camera-02",
        "segment_id": "segment-002",
        "road_name": "Đường Khuất Duy Tiến",
        "latitude": 20.996500,
        "longitude": 105.795800,
        "altitude_m": 14.0,
        "camera_heading": 180.0,
        "camera_fov": 70.0,
        "status": "online",
        "traffic_status": "SLOW",
        "congestion_score": 42,
        "avg_speed_kmh": 24.5,
        "current_vehicle_count": 22,
        "stopped_vehicle_count": 4,
        "density_veh_per_km_lane": 46.0,
        "counts_by_class": {
            "motorcycle": 14,
            "car": 6,
            "bus": 1,
            "truck": 1
        },
        "last_seen": datetime.now().isoformat(),
        "latest_health": {
            "general": {"uptime_seconds": 92300, "service_status": "running"},
            "network": {"local_ip": "192.168.1.106", "mac_address": "48:B0:2D:3C:4D:5E", "status": "connected"},
            "hardware": {
                "cpu_usage_pct": 52,
                "cpu_cores": 4,
                "ram_used_mb": 2410,
                "ram_total_mb": 3964,
                "ram_usage_pct": 60,
                "swap_used_mb": 128,
                "swap_total_mb": 2048,
                "gpu_usage_pct": 74,
                "temperature_c": 56.8,
                "power_mode": "10W_MAXN"
            },
            "storage": {"disk_total_gb": 29.5, "disk_free_gb": 18.1, "disk_usage_pct": 38, "outbox_unsent_images": 0},
            "pipeline": {"camera_status": "streaming", "pipeline_fps": 26.2, "inference_latency_ms": 38.1}
        },
        "snapshot_url": "https://images.unsplash.com/photo-1545179605-1296651e4d43?auto=format&fit=crop&w=800&q=80"
    },
    {
        "edge_id": "edge-03",
        "name": "Camera Lê Văn Lương - Hoàng Minh Giám",
        "camera_id": "camera-03",
        "segment_id": "segment-003",
        "road_name": "Đường Lê Văn Lương",
        "latitude": 21.004100,
        "longitude": 105.797200,
        "altitude_m": 11.0,
        "camera_heading": 290.0,
        "camera_fov": 60.0,
        "status": "online",
        "traffic_status": "FREE",
        "congestion_score": 18,
        "avg_speed_kmh": 44.0,
        "current_vehicle_count": 8,
        "stopped_vehicle_count": 0,
        "density_veh_per_km_lane": 15.2,
        "counts_by_class": {
            "motorcycle": 5,
            "car": 3,
            "bus": 0,
            "truck": 0
        },
        "last_seen": datetime.now().isoformat(),
        "latest_health": {
            "general": {"uptime_seconds": 341000, "service_status": "running"},
            "network": {"local_ip": "192.168.1.107", "mac_address": "48:B0:2D:7F:8A:9B", "status": "connected"},
            "hardware": {
                "cpu_usage_pct": 48,
                "cpu_cores": 4,
                "ram_used_mb": 2250,
                "ram_total_mb": 3964,
                "ram_usage_pct": 56,
                "swap_used_mb": 64,
                "swap_total_mb": 2048,
                "gpu_usage_pct": 68,
                "temperature_c": 54.2,
                "power_mode": "10W_MAXN"
            },
            "storage": {"disk_total_gb": 29.5, "disk_free_gb": 21.5, "disk_usage_pct": 27, "outbox_unsent_images": 0},
            "pipeline": {"camera_status": "streaming", "pipeline_fps": 28.0, "inference_latency_ms": 35.7}
        },
        "snapshot_url": "https://images.unsplash.com/photo-1506521781263-d8422e82f27a?auto=format&fit=crop&w=800&q=80"
    }
]


class DataStore:
    """In-memory data store with live state updates from MQTT/Edge."""

    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {n["edge_id"]: dict(n) for n in INITIAL_NODES}
        self.segments: Dict[str, Dict[str, Any]] = {s["segment_id"]: dict(s) for s in INITIAL_SEGMENTS}
        self.history_records: List[Dict[str, Any]] = []
        self._generate_seed_history()

    def _generate_seed_history(self):
        """Pre-populate 24h historical congestion timeline for playback demonstration."""
        now = datetime.now()
        base_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for i in range(24 * 4):  # every 15 mins for 24h
            t = base_time + timedelta(minutes=i * 15)
            hour = t.hour + t.minute / 60.0

            # Simulate morning peak (7:00 - 8:45) and evening peak (17:00 - 18:45)
            if 7.0 <= hour <= 8.75:
                score1 = int(75 + 20 * (1.0 - abs(hour - 7.75)))
                speed1 = round(10.0 + 5.0 * abs(hour - 7.75), 1)
            elif 17.0 <= hour <= 18.75:
                score1 = int(80 + 15 * (1.0 - abs(hour - 17.75)))
                speed1 = round(8.0 + 6.0 * abs(hour - 17.75), 1)
            elif 11.5 <= hour <= 13.0:
                score1 = 45
                speed1 = 28.0
            else:
                score1 = max(10, int(15 + 10 * (hour / 24.0)))
                speed1 = 45.0

            status1 = "CONGESTED" if score1 >= 65 else ("SLOW" if score1 >= 35 else "FREE")
            color1 = "#EF4444" if score1 >= 65 else ("#F59E0B" if score1 >= 35 else "#10B981")

            self.history_records.append({
                "timestamp": t.isoformat(),
                "time_str": t.strftime("%H:%M"),
                "segment_id": "segment-001",
                "road_name": "Đường Nguyễn Trãi",
                "congestion_score": score1,
                "avg_speed_kmh": speed1,
                "traffic_status": status1,
                "traffic_color": color1,
                "vehicle_count": int(score1 * 0.45) + 5
            })

    # Nodes API
    def _enrich_node(self, node: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not node:
            return None
        n = dict(node)
        seg_id = n.get("segment_id")
        if seg_id and seg_id in self.segments:
            seg = self.segments[seg_id]
            n.setdefault("road_length_m", seg.get("road_length_m", 450.0))
            n.setdefault("road_width_m", seg.get("road_width_m", 16.0))
            n.setdefault("lane_count", seg.get("lane_count", 4))
        return n

    def get_all_nodes(self) -> List[Dict[str, Any]]:
        return [self._enrich_node(n) for n in self.nodes.values() if n is not None]

    def get_node(self, edge_id: str) -> Optional[Dict[str, Any]]:
        return self._enrich_node(self.nodes.get(edge_id))

    def upsert_node(self, node_data: Dict[str, Any]) -> Dict[str, Any]:
        edge_id = node_data.get("edge_id", f"edge-{int(time.time()) % 1000}")
        node_data["edge_id"] = edge_id
        node_data.setdefault("last_seen", datetime.now().isoformat())
        node_data.setdefault("status", "online")
        node_data.setdefault("traffic_status", "FREE")
        node_data.setdefault("congestion_score", 15)
        self.nodes[edge_id] = node_data
        return node_data

    def delete_node(self, edge_id: str) -> bool:
        if edge_id in self.nodes:
            del self.nodes[edge_id]
            return True
        return False

    # Segments API
    def get_all_segments(self) -> List[Dict[str, Any]]:
        return list(self.segments.values())

    def get_segment(self, segment_id: str) -> Optional[Dict[str, Any]]:
        return self.segments.get(segment_id)

    def update_telemetry(self, edge_id: str, telemetry: Dict[str, Any]):
        node = self.nodes.get(edge_id)
        if node:
            node["last_seen"] = datetime.now().isoformat()
            node["traffic_status"] = telemetry.get("traffic_status", node.get("traffic_status", "UNKNOWN"))
            node["congestion_score"] = telemetry.get("congestion_score", node.get("congestion_score", 0))
            node["avg_speed_kmh"] = telemetry.get("avg_speed_kmh", node.get("avg_speed_kmh", 0.0))
            node["current_vehicle_count"] = telemetry.get("current_vehicle_count", 0)
            node["stopped_vehicle_count"] = telemetry.get("stopped_vehicle_count", 0)
            node["density_veh_per_km_lane"] = telemetry.get("density_veh_per_km_lane", 0.0)
            node["counts_by_class"] = telemetry.get("counts_by_class", node.get("counts_by_class", {}))

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

    # GeoJSON Converters
    def get_nodes_geojson(self) -> Dict[str, Any]:
        features = []
        for n in self.nodes.values():
            score = n.get("congestion_score", 0)
            status = n.get("status", "offline")
            color = "#9CA3AF" if status == "offline" else ("#EF4444" if score >= 65 else ("#F59E0B" if score >= 35 else "#10B981"))
            seg = self.segments.get(n.get("segment_id", ""), {})

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(n.get("longitude", 0.0)), float(n.get("latitude", 0.0))]
                },
                "properties": {
                    "edge_id": n.get("edge_id"),
                    "name": n.get("name"),
                    "camera_id": n.get("camera_id"),
                    "segment_id": n.get("segment_id"),
                    "road_name": n.get("road_name"),
                    "lane_count": n.get("lane_count") or seg.get("lane_count", 4),
                    "road_length_m": n.get("road_length_m") or seg.get("road_length_m", 450.0),
                    "road_width_m": n.get("road_width_m") or seg.get("road_width_m", 16.0),
                    "heading": float(n.get("camera_heading", 0.0)),
                    "fov": float(n.get("camera_fov", 60.0)),
                    "status": status,
                    "traffic_status": n.get("traffic_status", "UNKNOWN"),
                    "congestion_score": score,
                    "avg_speed_kmh": n.get("avg_speed_kmh", 0.0),
                    "vehicle_count": n.get("current_vehicle_count", 0),
                    "marker_color": color,
                    "last_seen": n.get("last_seen")
                }
            })
        return {"type": "FeatureCollection", "features": features}

    def get_segments_geojson(self) -> Dict[str, Any]:
        features = []
        for s in self.segments.values():
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": s.get("coordinates", [])
                },
                "properties": {
                    "segment_id": s.get("segment_id"),
                    "road_name": s.get("road_name"),
                    "lane_count": s.get("lane_count", 4),
                    "road_length_m": s.get("road_length_m", 450.0),
                    "road_width_m": s.get("road_width_m", 16.0),
                    "speed_limit_kmh": s.get("speed_limit_kmh", 60.0),
                    "congestion_score": s.get("congestion_score", 0),
                    "traffic_status": s.get("traffic_status", "FREE"),
                    "traffic_color": s.get("traffic_color", "#10B981"),
                    "avg_speed_kmh": s.get("avg_speed_kmh", 0.0),
                    "vehicle_count": s.get("current_vehicle_count", 0),
                    "updated_at": s.get("updated_at")
                }
            })
        return {"type": "FeatureCollection", "features": features}


store = DataStore()
