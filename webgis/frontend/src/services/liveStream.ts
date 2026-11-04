/**
 * Quản lý luồng video On-Demand trực tiếp từ MediaMTX (WebRTC / WHEP / HLS).
 */

import axios from "axios";
import { API_BASE } from "./api";

export interface MediaMTXStreamInfo {
  edge_id: string;
  status: string;
  message?: string;
  webrtc_url: string;
  whep_url: string;
  hls_url: string;
  rtsp_url: string;
}

export async function startMediaMTXLive(edgeId: string): Promise<MediaMTXStreamInfo> {
  const res = await axios.post(`${API_BASE}/devices/${edgeId}/live/start`);
  return res.data;
}

export async function stopMediaMTXLive(edgeId: string): Promise<void> {
  try {
    await axios.post(`${API_BASE}/devices/${edgeId}/live/stop`);
  } catch (e) {
    // ignore
  }
}

export async function sendMediaMTXKeepAlive(edgeId: string): Promise<void> {
  try {
    await axios.post(`${API_BASE}/devices/${edgeId}/live/keepalive`);
  } catch (e) {
    // ignore
  }
}

export async function getMediaMTXLiveInfo(edgeId: string): Promise<MediaMTXStreamInfo> {
  const res = await axios.get(`${API_BASE}/devices/${edgeId}/live`);
  return res.data;
}
