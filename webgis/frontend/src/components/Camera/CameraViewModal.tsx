import React, { useState, useEffect } from "react";
import {
  X,
  Camera,
  Download,
  ShieldAlert,
  AlertTriangle,
  CheckCircle2,
  Activity,
  Clock,
  Radio,
  ImageIcon,
  Zap,
} from "lucide-react";
import type { NodeDetail } from "../../types/gis";
import { API_HOST_URL } from "../../services/api";
import { wsService } from "../../services/websocket";
import { MediaMTXPlayer } from "./MediaMTXPlayer";

interface CameraViewModalProps {
  isOpen: boolean;
  onClose: () => void;
  node: NodeDetail | null;
}

export const CameraViewModal: React.FC<CameraViewModalProps> = ({
  isOpen,
  onClose,
  node,
}) => {
  const [viewMode, setViewMode] = useState<"live" | "snapshot">("live");
  const [snapshotUrl, setSnapshotUrl] = useState<string>("");
  const [cacheBuster, setCacheBuster] = useState<number>(Date.now());
  const [flashHighlight, setFlashHighlight] = useState<boolean>(false);
  const [lastCapturedTime, setLastCapturedTime] = useState<string>("");

  // Real-time telemetry overlay states
  const [liveTrafficStatus, setLiveTrafficStatus] = useState<string>(node?.traffic_status || "FREE");
  const [liveSpeed, setLiveSpeed] = useState<number>(Number(node?.avg_speed_kmh) || 0);
  const [liveVehicleCount, setLiveVehicleCount] = useState<number>(Number(node?.current_vehicle_count) || 0);
  const [liveScore, setLiveScore] = useState<number>(Number(node?.congestion_score) || 0);

  // Sync state when node changes or modal opens
  useEffect(() => {
    if (node) {
      setSnapshotUrl(node.snapshot_url || "");
      setLiveTrafficStatus(node.traffic_status || "FREE");
      setLiveSpeed(Number(node.avg_speed_kmh) || 0);
      setLiveVehicleCount(Number(node.current_vehicle_count) || 0);
      setLiveScore(Number(node.congestion_score) || 0);
      setLastCapturedTime(node.last_seen ? new Date(node.last_seen).toLocaleTimeString() : new Date().toLocaleTimeString());
    }
  }, [node, isOpen]);

  // WebSocket Subscription: Lắng nghe snapshot tự động khi kẹt xe và telemetry
  useEffect(() => {
    if (!isOpen || !node) return;

    const unsubscribe = wsService.subscribe((msg: any) => {
      // Nhận ảnh snapshot mới tự động chụp khi kẹt xe
      if (msg.type === "snapshot_updated" && msg.edge_id === node.edge_id) {
        setSnapshotUrl(msg.snapshot_url);
        setCacheBuster(Date.now());
        setLastCapturedTime(new Date().toLocaleTimeString());
        setFlashHighlight(true);
        setTimeout(() => setFlashHighlight(false), 1200);
      }

      // Cập nhật telemetry chỉ số
      if (msg.type === "telemetry" && msg.edge_id === node.edge_id) {
        if (msg.traffic_status) setLiveTrafficStatus(msg.traffic_status);
        if (msg.average_speed !== undefined) setLiveSpeed(msg.average_speed);
        if (msg.vehicle_count !== undefined) setLiveVehicleCount(msg.vehicle_count);
        if (msg.congestion_score !== undefined) setLiveScore(msg.congestion_score);
      }
    });

    return () => {
      unsubscribe();
    };
  }, [isOpen, node]);

  if (!isOpen || !node) return null;

  const resolveImageUrl = (rawUrl: string | undefined): string => {
    if (!rawUrl) return "";
    if (rawUrl.startsWith("data:") || rawUrl.startsWith("blob:")) return rawUrl;
    if (rawUrl.startsWith("http://") || rawUrl.startsWith("https://")) {
      return `${rawUrl}?t=${cacheBuster}`;
    }
    const cleanPath = rawUrl.startsWith("/") ? rawUrl : `/${rawUrl}`;
    return `${API_HOST_URL}${cleanPath}?t=${cacheBuster}`;
  };

  const finalSnapshotUrl = resolveImageUrl(snapshotUrl);
  const currentDisplayUrl = finalSnapshotUrl;

  // Tải ảnh đang xem về máy
  const handleDownload = () => {
    if (!currentDisplayUrl) return;
    const a = document.createElement("a");
    a.href = currentDisplayUrl;
    a.download = `${viewMode}_${node.edge_id}_${Date.now()}.jpg`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const isCongested = liveTrafficStatus === "CONGESTED";
  const isSlow = liveTrafficStatus === "SLOW";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-slate-900/60 backdrop-blur-sm animate-fade-in">
      <div className="relative w-full max-w-5xl bg-white border border-slate-200 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[92vh]">
        
        {/* Header Modal */}
        <div className="flex flex-wrap items-center justify-between px-6 py-3.5 border-b border-slate-200 bg-white gap-3">
          <div className="flex items-center gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-600 shadow-xs">
              <Camera className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h3 className="text-base sm:text-lg font-bold text-slate-900 tracking-tight">
                  {node.name || `Camera AI (${node.edge_id})`}
                </h3>
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  Jetson Nano CSI
                </span>
              </div>
              <p className="text-xs text-slate-500 flex items-center gap-3 mt-0.5 font-medium">
                <span>Mã trạm: <span className="font-mono text-slate-700 font-semibold">{node.edge_id}</span></span>
                <span>•</span>
                <span>Tuyến: <span className="text-slate-700 font-semibold">{node.road_name || "Nguyễn Trãi"}</span></span>
              </p>
            </div>
          </div>

          {/* Toggle View Mode: Live Stream vs Bằng chứng kẹt xe */}
          <div className="flex items-center gap-2">
            <div className="inline-flex p-1 bg-slate-100 rounded-xl border border-slate-200">
              <button
                onClick={() => setViewMode("live")}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  viewMode === "live"
                    ? "bg-white text-blue-600 shadow-xs"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                <Radio className="w-3.5 h-3.5 text-emerald-500 animate-pulse" />
                <span>Trực tiếp (Live)</span>
              </button>
              <button
                onClick={() => setViewMode("snapshot")}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                  viewMode === "snapshot"
                    ? "bg-white text-blue-600 shadow-xs"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                <ImageIcon className="w-3.5 h-3.5 text-amber-500" />
                <span>Bằng chứng kẹt xe</span>
              </button>
            </div>

            <button
              onClick={onClose}
              className="p-2 text-slate-400 hover:text-slate-700 rounded-xl hover:bg-slate-100 transition-colors ml-2"
              title="Đóng modal"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Content Body: Media Viewer */}
        <div className="relative flex-1 bg-slate-950 flex items-center justify-center min-h-[380px] sm:min-h-[500px] overflow-hidden select-none">
          {viewMode === "live" ? (
            /* TAB 1: LIVE STREAM (MediaMTX WebRTC & LL-HLS) */
            <div className="relative w-full h-full flex items-center justify-center">
              <MediaMTXPlayer edgeId={node.edge_id} className="w-full h-full" />
            </div>
          ) : (
            /* TAB 2: ẢNH BẰNG CHỨNG KẸT XE TỰ ĐỘNG */
            <div className="relative w-full h-full flex items-center justify-center">
              {finalSnapshotUrl ? (
                <img
                  src={finalSnapshotUrl}
                  alt={`Snapshot evidence ${node.edge_id}`}
                  className={`max-w-full max-h-[70vh] object-contain transition-all duration-300 ${
                    flashHighlight ? "ring-4 ring-emerald-400 scale-[1.005] shadow-[0_0_40px_rgba(52,211,153,0.6)]" : ""
                  }`}
                />
              ) : (
                <div className="flex flex-col items-center justify-center p-8 text-center text-slate-400 gap-3">
                  <ImageIcon className="w-12 h-12 text-slate-600 stroke-[1.5]" />
                  <p className="text-sm font-medium">Chưa có ảnh bằng chứng kẹt xe từ camera này.</p>
                  <p className="text-xs text-slate-500 max-w-md">
                    Hệ thống sẽ tự động chụp và lưu trữ ảnh kèm bounding box AI khi phát hiện ùn tắc giao thông (<strong className="text-red-400">CONGESTED</strong> liên tục &ge; 15 giây).
                  </p>
                </div>
              )}
            </div>
          )}

          {/* HUD Overlay - Top Left: Traffic Status Badge */}
          <div className="absolute top-4 left-4 flex flex-col gap-2 z-10 pointer-events-none">
            <div
              className={`inline-flex items-center gap-2 px-3.5 py-1.5 rounded-xl font-bold text-xs uppercase tracking-wider shadow-lg backdrop-blur-md border ${
                isCongested
                  ? "bg-white/95 text-red-700 border-red-200 shadow-red-500/10"
                  : isSlow
                  ? "bg-white/95 text-amber-700 border-amber-200 shadow-amber-500/10"
                  : "bg-white/95 text-emerald-700 border-emerald-200 shadow-emerald-500/10"
              }`}
            >
              {isCongested ? (
                <ShieldAlert className="w-4 h-4 animate-bounce text-red-600" />
              ) : isSlow ? (
                <AlertTriangle className="w-4 h-4 text-amber-600" />
              ) : (
                <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              )}
              <span>
                {isCongested ? "ÙN TẮC GIAO THÔNG" : isSlow ? "MẬT ĐỘ ĐÔNG (CHẬM)" : "THÔNG THOÁNG"}
              </span>
              <span className={`ml-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${
                isCongested ? "bg-red-100 text-red-800" : isSlow ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"
              }`}>
                {Math.round(Number(liveScore) || 0)}%
              </span>
            </div>
          </div>

          {/* HUD Overlay - Top Right: Real-time Telemetry Card */}
          <div className="absolute top-4 right-4 z-10 bg-white/95 backdrop-blur-md border border-slate-200 rounded-xl p-3 shadow-xl text-right min-w-[160px] pointer-events-none">
            <div className="flex items-center justify-end gap-1.5 text-xs text-slate-500 mb-1">
              <Activity className="w-3.5 h-3.5 text-blue-600" />
              <span className="font-bold uppercase tracking-wider text-[10px]">Chỉ số tức thời</span>
            </div>
            <div className="text-xl font-black text-slate-900 tracking-tight">
              {(Number(liveSpeed) || 0).toFixed(1)}{" "}
              <span className="text-xs font-semibold text-slate-500">km/h</span>
            </div>
            <div className="text-xs font-bold text-blue-600 mt-0.5">
              {Number(liveVehicleCount) || 0}{" "}
              <span className="text-xs font-medium text-slate-500">xe trong ROI</span>
            </div>
          </div>

          {/* HUD Overlay - Bottom Left: Camera & Segment Info */}
          <div className="absolute bottom-4 left-4 z-10 bg-white/95 backdrop-blur-md border border-slate-200 rounded-lg px-3 py-1.5 text-xs text-slate-700 shadow-md pointer-events-none">
            <div className="flex items-center gap-2 font-medium">
              <span className="text-emerald-600 font-mono font-bold flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                {viewMode === "live" ? "LIVE ON-DEMAND" : "AI EVIDENCE"}
              </span>
              <span>{node.road_name || "Đoạn Nguyễn Trãi"}</span>
              <span className="text-slate-300">•</span>
              <span className="text-slate-500 font-mono">FOV: {node.camera_fov || 65}°</span>
            </div>
          </div>

          {/* HUD Overlay - Bottom Right: Last Updated Clock */}
          <div className="absolute bottom-4 right-4 z-10 bg-white/95 backdrop-blur-md border border-slate-200 rounded-lg px-3 py-1.5 text-xs text-slate-700 shadow-md flex items-center gap-2 font-medium pointer-events-none">
            <Clock className="w-3.5 h-3.5 text-slate-400" />
            <span>Cập nhật: <span className="font-mono text-emerald-600 font-bold">{lastCapturedTime}</span></span>
          </div>
        </div>

        {/* Footer Toolbar */}
        <div className="flex flex-wrap items-center justify-between px-6 py-3.5 border-t border-slate-200 bg-slate-50 gap-3">
          <div className="flex items-center gap-2 text-xs">
            <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white text-slate-700 border border-slate-200 shadow-xs font-medium">
              <Zap className="w-3.5 h-3.5 text-amber-500" />
              <span>Chụp tự động khi kẹt xe: <strong className="text-emerald-600">BẬT (AI Trigger)</strong></span>
            </span>
            <span className="text-xs text-slate-500 hidden sm:inline">
              (Ảnh chụp lưu trữ tự động khi duy trì kẹt xe &ge; 15 giây)
            </span>
          </div>

          <div className="flex items-center gap-2.5">
            <button
              onClick={handleDownload}
              disabled={!currentDisplayUrl}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-white hover:bg-slate-100 text-slate-700 text-xs font-semibold border border-slate-300 shadow-xs transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              title="Tải ảnh JPEG về máy"
            >
              <Download className="w-3.5 h-3.5 text-slate-500" />
              <span>Tải ảnh về máy</span>
            </button>
          </div>
        </div>

      </div>
    </div>
  );
};
