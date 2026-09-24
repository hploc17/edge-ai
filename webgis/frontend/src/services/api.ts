import axios from "axios";
import type { GeoJSONFeatureCollection, NodeDetail, SummaryKPIs, HistoryRecord, CongestionSnapshot } from "../types/gis";

const API_BASE = "http://localhost:8000/api/v1";

export const api = {
  // GIS layers
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

  // Node Management
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
  deleteNode: async (edgeId: string) => {
    const res = await axios.delete(`${API_BASE}/nodes/${edgeId}`);
    return res.data;
  },

  // Commands & Diagnostics
  diagnoseHealth: async (edgeId: string) => {
    const res = await axios.post(`${API_BASE}/commands/diagnose/${edgeId}`);
    return res.data;
  },
  sendCommand: async (edgeId: string, action: string, params?: any) => {
    const res = await axios.post(`${API_BASE}/commands/send`, {
      edge_id: edgeId,
      action,
      params
    });
    return res.data;
  },

  // History & Playback
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
  }
};
