import axios from "axios";
import type { GeoJSONFeatureCollection, NodeDetail, SummaryKPIs, HistoryRecord, CongestionSnapshot, PendingNodeInfo, OSMRoadInfo } from "../types/gis";

const host = typeof window !== "undefined" ? window.location.hostname : "localhost";
export const API_HOST_URL = `http://${host}:8000`;
const API_BASE = `${API_HOST_URL}/api/v1`;

export const api = {
  // ── GIS Layers ────────────────────────────────────────────────────────────
  getNodesGeoJSON: async () => {
    const res = await axios.get<GeoJSONFeatureCollection<any, any>>(`${API_BASE}/gis/nodes`);
    return res.data;
  },
  getSegmentsGeoJSON: async () => {
    const res = await axios.get<GeoJSONFeatureCollection<any, any>>(`${API_BASE}/gis/segments`);
    return res.data;
  },
  getSummaryKPIs: async () => {
    const res = await axios.get<SummaryKPIs>(`${API_BASE}/gis/summary`);
    return res.data;
  },

  // ── Approved Node Management ──────────────────────────────────────────────
  getAllNodes: async () => {
    const res = await axios.get<NodeDetail[]>(`${API_BASE}/nodes`);
    return res.data;
  },
  getNodeDetail: async (edgeId: string) => {
    const res = await axios.get<NodeDetail>(`${API_BASE}/nodes/${edgeId}`);
    return res.data;
  },
  createNode: async (nodeData: any) => {
    const res = await axios.post(`${API_BASE}/nodes`, nodeData);
    return res.data;
  },
  updateNode: async (edgeId: string, nodeData: any) => {
    const res = await axios.put(`${API_BASE}/nodes/${edgeId}`, nodeData);
    return res.data;
  },
  deleteNode: async (edgeId: string) => {
    const res = await axios.delete(`${API_BASE}/nodes/${edgeId}`);
    return res.data;
  },

  // ── Pending Node Approval Flow ────────────────────────────────────────────
  getPendingNodes: async (): Promise<PendingNodeInfo[]> => {
    const res = await axios.get<PendingNodeInfo[]>(`${API_BASE}/nodes/pending`);
    return res.data;
  },
  approveNode: async (edgeId: string, approvalData: {
    name?: string;
    latitude: number;
    longitude: number;
    road_name: string;
    segment_id?: string;
    lane_count: number;
    road_length_m: number;
    road_width_m: number;
    speed_limit_kmh: number;
    camera_heading: number;
    camera_fov: number;
    altitude_m?: number;
    osm_way_id?: number;
    osm_road_type?: string;
    osm_coordinates?: [number, number][];
  }) => {
    const res = await axios.post(`${API_BASE}/nodes/${edgeId}/approve`, approvalData);
    return res.data;
  },
  rejectPendingNode: async (edgeId: string) => {
    const res = await axios.delete(`${API_BASE}/nodes/${edgeId}/pending`);
    return res.data;
  },

  // ── Commands & Diagnostics ─────────────────────────────────────────────────
  diagnoseHealth: async (edgeId: string) => {
    const res = await axios.post(`${API_BASE}/commands/diagnose/${edgeId}`);
    return res.data;
  },
  sendCommand: async (edgeId: string, action: string, params?: any) => {
    const res = await axios.post(`${API_BASE}/commands/send`, { edge_id: edgeId, action, params });
    return res.data;
  },

  // ── History & Playback ─────────────────────────────────────────────────────
  getTimeline: async (segmentId: string = "segment-001") => {
    const res = await axios.get<{
      segment_id: string;
      total_intervals: number;
      peak_congestion_score: number;
      min_speed_kmh: number;
      avg_speed_kmh: number;
      records: HistoryRecord[];
    }>(`${API_BASE}/history/timeline?segment_id=${segmentId}`);
    return res.data;
  },
  getSnapshots: async (segmentId?: string) => {
    const url = segmentId ? `${API_BASE}/history/snapshots?segment_id=${segmentId}` : `${API_BASE}/history/snapshots`;
    const res = await axios.get<CongestionSnapshot[]>(url);
    return res.data;
  },

  // ── OSM Road Info ──────────────────────────────────────────────────────────
  /** Lấy thông số đường thực tế (tên, làn, tốc độ, tọa độ LineString) từ OpenStreetMap */
  fetchOSMRoadInfo: async (lat: number, lng: number): Promise<OSMRoadInfo> => {
    const res = await axios.get<OSMRoadInfo>(`${API_BASE}/osm/road-info`, { params: { lat, lng } });
    return res.data;
  },
};
