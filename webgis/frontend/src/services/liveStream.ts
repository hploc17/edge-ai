/**
 * LiveStreamClient: WebSocket Client quản lý luồng video JPEG trực tiếp từ Jetson Nano qua Backend.
 *
 * Tính năng:
 * - Tự động suy ra WebSocket endpoint theo hostname và giao thức (ws/wss).
 * - binaryType = 'blob': Chuyển đổi nhị phân JPEG frame thành Object URL nhanh chóng.
 * - Quản lý bộ nhớ trình duyệt: Tự động thu hồi (URL.revokeObjectURL) frame cũ chống tràn RAM.
 * - Bắt các sự kiện trạng thái (connecting, live, offline, stalled, full).
 */

import axios from "axios";
import { API_BASE } from "./api";

export type LiveStreamState = "connecting" | "live" | "offline" | "stalled" | "full";

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

export interface LiveStreamCallbacks {
  onFrame?: (blobUrl: string) => void;
  onStatus?: (state: LiveStreamState, message?: string) => void;
}

export class LiveStreamClient {
  private edgeId: string;
  private callbacks: LiveStreamCallbacks;
  private ws: WebSocket | null = null;
  private currentBlobUrl: string | null = null;
  private isClosed: boolean = false;

  constructor(edgeId: string, callbacks: LiveStreamCallbacks) {
    this.edgeId = edgeId;
    this.callbacks = callbacks;
    this.connect();
  }

  private getWebSocketUrl(): string {
    const isHttps = typeof window !== "undefined" && window.location.protocol === "https:";
    const protocol = isHttps ? "wss:" : "ws:";
    const host = typeof window !== "undefined" ? window.location.hostname : "localhost";
    return `${protocol}//${host}:8000/ws/live/${this.edgeId}`;
  }

  private connect(): void {
    if (this.isClosed) return;

    const url = this.getWebSocketUrl();
    try {
      this.ws = new WebSocket(url);
      this.ws.binaryType = "blob";

      this.ws.onopen = () => {
        if (this.isClosed) {
          this.ws?.close();
          return;
        }
        this.callbacks.onStatus?.("connecting", "Đang kết nối camera...");
      };

      this.ws.onmessage = (event: MessageEvent) => {
        if (this.isClosed) return;

        // 1. Nhận frame nhị phân JPEG
        if (event.data instanceof Blob) {
          // Thu hồi URL cũ để tránh rò rỉ bộ nhớ browser
          if (this.currentBlobUrl) {
            URL.revokeObjectURL(this.currentBlobUrl);
          }
          const blobUrl = URL.createObjectURL(event.data);
          this.currentBlobUrl = blobUrl;
          this.callbacks.onFrame?.(blobUrl);
          this.callbacks.onStatus?.("live");
          return;
        }

        // 2. Nhận thông điệp trạng thái dạng Text JSON
        if (typeof event.data === "string") {
          try {
            const data = JSON.parse(event.data);
            if (data.type === "status") {
              this.callbacks.onStatus?.(data.state as LiveStreamState, data.message);
            }
          } catch {
            // bỏ qua text không hợp lệ
          }
        }
      };

      this.ws.onerror = () => {
        if (!this.isClosed) {
          this.callbacks.onStatus?.("offline", "Không thể kết nối tới luồng camera");
        }
      };

      this.ws.onclose = (event: CloseEvent) => {
        if (!this.isClosed) {
          if (event.code === 1008) {
            this.callbacks.onStatus?.("full", "Đạt giới hạn số lượng người xem đồng thời");
          } else {
            this.callbacks.onStatus?.("offline", "Luồng camera đã kết thúc");
          }
        }
      };
    } catch (err) {
      this.callbacks.onStatus?.("offline", "Lỗi khởi tạo kết nối");
    }
  }

  public close(): void {
    this.isClosed = true;
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // bỏ qua
      }
      this.ws = null;
    }
    if (this.currentBlobUrl) {
      URL.revokeObjectURL(this.currentBlobUrl);
      this.currentBlobUrl = null;
    }
  }
}
