import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# Initial Seed Data for Road Segments (LineString GeoJSON)
# Real Road Corridor for Edge AI (LineString GeoJSON)
INITIAL_SEGMENTS = [
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
        "congestion_score": 0,
        "traffic_status": "FREE",
        "traffic_color": "#10B981",
        "avg_speed_kmh": 0.0,
        "current_vehicle_count": 0,
        "density_veh_per_km_lane": 0.0,
        "updated_at": datetime.now().isoformat()
    }
]

# Zero mock nodes: Only real Jetson nodes discovered via MQTT registration/heartbeat are stored
INITIAL_NODES = []


class DataStore:
    """In-memory data store with live state updates from MQTT/Edge."""

    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {n["edge_id"]: dict(n) for n in INITIAL_NODES}
        self.segments: Dict[str, Dict[str, Any]] = {s["segment_id"]: dict(s) for s in INITIAL_SEGMENTS}
        self.history_records: List[Dict[str, Any]] = []


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

        # Normalize nested geo dictionary if present (from registration profile)
        if "geo" in node_data and isinstance(node_data["geo"], dict):
            geo = node_data["geo"]
            node_data.setdefault("latitude", geo.get("lat", 20.998412))
            node_data.setdefault("longitude", geo.get("lng", 105.795123))
            node_data.setdefault("segment_id", geo.get("segment_id", "segment-001"))
            node_data.setdefault("road_name", geo.get("road_name", "Đường Nguyễn Trãi"))
            node_data.setdefault("camera_heading", geo.get("heading", 45.0))
            node_data.setdefault("camera_fov", geo.get("fov", 65.0))
            node_data.setdefault("altitude_m", geo.get("altitude_m", 12.5))

        # Default fallbacks for coordinates & names
        node_data.setdefault("name", node_data.get("device_name") or f"Camera AI Jetson ({edge_id})")
        node_data.setdefault("camera_id", "camera-01")
        node_data.setdefault("segment_id", "segment-001")
        node_data.setdefault("road_name", "Đường Nguyễn Trãi")
        node_data.setdefault("latitude", 20.998412)
        node_data.setdefault("longitude", 105.795123)
        node_data.setdefault("camera_heading", 45.0)
        node_data.setdefault("camera_fov", 65.0)
        node_data.setdefault("last_seen", datetime.now().isoformat())
        node_data.setdefault("status", "online")
        node_data.setdefault("traffic_status", "FREE")
        node_data.setdefault("congestion_score", 15)

        existing = self.nodes.get(edge_id, {})
        merged = {**existing, **node_data}
        self.nodes[edge_id] = merged
        return merged

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
