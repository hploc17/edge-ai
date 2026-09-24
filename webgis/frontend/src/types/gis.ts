export interface GeoJSONFeature<G, P> {
  type: "Feature";
  geometry: G;
  properties: P;
}

export interface GeoJSONFeatureCollection<G, P> {
  type: "FeatureCollection";
  features: GeoJSONFeature<G, P>[];
}

export interface NodeProperties {
  edge_id: string;
  name: string;
  camera_id?: string;
  segment_id?: string;
  road_name?: string;
  heading: number;
  fov: number;
  status: "online" | "offline" | "degraded";
  traffic_status: "FREE" | "SLOW" | "CONGESTED" | "UNKNOWN";
  congestion_score: number;
  avg_speed_kmh: number;
  vehicle_count: number;
  marker_color: string;
  last_seen?: string;
}

export interface SegmentProperties {
  segment_id: string;
  road_name: string;
  lane_count: number;
  road_length_m: number;
  road_width_m: number;
  speed_limit_kmh: number;
  congestion_score: number;
  traffic_status: "FREE" | "SLOW" | "CONGESTED";
  traffic_color: string;
  avg_speed_kmh: number;
  vehicle_count: number;
  updated_at?: string;
}

export interface NodeDetail extends NodeProperties {
  latitude: number;
  longitude: number;
  altitude_m?: number;
  camera_heading?: number;
  camera_fov?: number;
  lane_count?: number;
  road_length_m?: number;
  road_width_m?: number;
  stopped_vehicle_count?: number;
  density_veh_per_km_lane?: number;
  counts_by_class?: {
    motorcycle?: number;
    car?: number;
    bus?: number;
    truck?: number;
  };
  latest_health?: DeviceHealthData;
  snapshot_url?: string;
}

export interface DeviceHealthData {
  timestamp?: string;
  general?: {
    uptime_seconds?: number;
    boot_time?: string;
    service_status?: string;
  };
  network?: {
    local_ip?: string;
    mac_address?: string;
    status?: string;
  };
  hardware?: {
    cpu_usage_pct?: number;
    cpu_cores?: number;
    ram_used_mb?: number;
    ram_total_mb?: number;
    ram_usage_pct?: number;
    swap_used_mb?: number;
    swap_total_mb?: number;
    gpu_usage_pct?: number;
    temperature_c?: number;
    power_mode?: string;
  };
  storage?: {
    disk_total_gb?: number;
    disk_free_gb?: number;
    disk_usage_pct?: number;
    outbox_unsent_images?: number;
  };
  pipeline?: {
    camera_status?: string;
    pipeline_fps?: number;
    inference_latency_ms?: number;
  };
}

export interface SummaryKPIs {
  total_nodes: number;
  online_nodes: number;
  offline_nodes: number;
  total_segments: number;
  congested_segments: number;
  slow_segments: number;
  free_segments: number;
  system_avg_speed_kmh: number;
  active_alerts_count: number;
}

export interface HistoryRecord {
  timestamp: string;
  time_str: string;
  segment_id: string;
  road_name: string;
  congestion_score: number;
  avg_speed_kmh: number;
  traffic_status: string;
  traffic_color: string;
  vehicle_count: number;
}

export interface CongestionSnapshot {
  snapshot_id: string;
  edge_id: string;
  segment_id: string;
  timestamp: string;
  time_str: string;
  location_name: string;
  traffic_status: string;
  congestion_score: number;
  avg_speed_kmh: number;
  vehicle_count: number;
  image_url: string;
}
