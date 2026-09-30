import React, { useState, useEffect } from "react";
import { X, Camera, Download, RefreshCw, AlertTriangle, CheckCircle2, ShieldAlert, Clock, Activity, Zap } from "lucide-react";
import type { NodeDetail } from "../../types/gis";
import { api, API_HOST_URL } from "../../services/api";
import { wsService } from "../../services/websocket";

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
  const [snapshotUrl, setSnapshotUrl] = useState<string>("");
  const [cacheBuster, setCacheBuster] = useState<number>(Date.now());
  const [isCapturing, setIsCapturing] = useState<boolean>(false);
  const [flashHighlight, setFlashHighlight] = useState<boolean>(false);
  const [actionMessage, setActionMessage] = useState<string>("");
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
      setIsCapturing(false);
      setActionMessage("");
    }
  }, [node, isOpen]);

  // WebSocket Subscription: Lắng nghe snapshot_updated và telemetry
  useEffect(() => {
    if (!isOpen || !node) return;

    const unsubscribe = wsService.subscribe((msg: any) => {
      // Nhận ảnh snapshot mới từ Jetson (chụp theo yêu cầu hoặc tự động khi kẹt xe)
      if (msg.type === "snapshot_updated" && msg.edge_id === node.edge_id) {
        setSnapshotUrl(msg.snapshot_url);
        setCacheBuster(Date.now());
        setFlashHighlight(true);
        setIsCapturing(false);
        setLastCapturedTime(new Date().toLocaleTimeString());
        
        const reasonText = msg.trigger_reason === "auto_congestion_detected" 
          ? "🚨 Tự động chụp do phát hiện kẹt xe!" 
          : "📸 Đã nhận ảnh chụp mới từ Jetson!";
        setActionMessage(reasonText);

        setTimeout(() => setFlashHighlight(false), 1500);
      }

      // Cập nhật số liệu telemetry thời gian thực trên HUD
      if (msg.type === "telemetry" && msg.edge_id === node.edge_id) {
        const t = msg.data || {};
        if (t.traffic_status) setLiveTrafficStatus(t.traffic_status);
        if (t.avg_speed_kmh !== undefined && t.avg_speed_kmh !== null) setLiveSpeed(Number(t.avg_speed_kmh) || 0);
        if (t.current_vehicle_count !== undefined && t.current_vehicle_count !== null) setLiveVehicleCount(Number(t.current_vehicle_count) || 0);
        if (t.congestion_score !== undefined && t.congestion_score !== null) setLiveScore(Number(t.congestion_score) || 0);
      }
    });

    return () => unsubscribe();
  }, [isOpen, node]);

  if (!isOpen || !node) return null;

  // Chuẩn hóa đường dẫn ảnh (gắn host IP động nếu là đường dẫn tương đối)
  const resolveImageUrl = (rawUrl?: string): string => {
    if (!rawUrl) return "";
    if (rawUrl.startsWith("http://") || rawUrl.startsWith("https://")) {
      return `${rawUrl}?t=${cacheBuster}`;
    }
    const cleanPath = rawUrl.startsWith("/") ? rawUrl : `/${rawUrl}`;
    return `${API_HOST_URL}${cleanPath}?t=${cacheBuster}`;
  };

  const finalImageUrl = resolveImageUrl(snapshotUrl);

  // Gửi lệnh chụp ảnh theo yêu cầu
  const handleRequestSnapshot = async () => {
    if (isCapturing) return;
    setIsCapturing(true);
    setActionMessage("Đang gửi lệnh chụp Camera CSI tới Jetson...");

    try {
      const res = await api.sendCommand(node.edge_id, "capture_test_snapshot", {
        source_type: "csi",
        reason: "manual_on_demand"
      });
      if (res && res.success) {
        setActionMessage("Đã gửi lệnh chụp Camera CSI. Đang chờ Jetson phản hồi ảnh...");
        // Timeout 12s nếu Jetson không phản hồi
        setTimeout(() => {
          setIsCapturing((prev) => {
            if (prev) setActionMessage("Hết thời gian chờ phản hồi từ Jetson. Vui lòng thử lại.");
            return false;
          });
        }, 12000);
      } else {
        setIsCapturing(false);
        setActionMessage("Gửi lệnh thất bại. Vui lòng kiểm tra kết nối MQTT.");
      }
    } catch (err: any) {
      console.error("Failed to request snapshot:", err);
      setIsCapturing(false);
      setActionMessage("Lỗi kết nối khi gửi lệnh chụp.");
    }
  };

  // Tải ảnh về máy
  const handleDownload = () => {
    if (!finalImageUrl) return;
    const a = document.createElement("a");
    a.href = finalImageUrl;
    a.download = `snapshot_${node.edge_id}_${Date.now()}.jpg`;
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
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-white">
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
                  Live CCTV
                </span>
              </div>
              <p className="text-xs text-slate-500 flex items-center gap-3 mt-0.5 font-medium">
                <span>Mã trạm: <span className="font-mono text-slate-700 font-semibold">{node.edge_id}</span></span>
                <span>•</span>
                <span>Tuyến: <span className="text-slate-700 font-semibold">{node.road_name || "Nguyễn Trãi"}</span></span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="p-2 text-slate-400 hover:text-slate-700 rounded-xl hover:bg-slate-100 transition-colors"
              title="Đóng modal"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Content Body: Image Frame & HUD Overlay */}
        <div className="relative flex-1 bg-slate-950 flex items-center justify-center min-h-[380px] sm:min-h-[500px] overflow-hidden select-none">
          {finalImageUrl ? (
            <div className="relative w-full h-full flex items-center justify-center">
              <img
                src={finalImageUrl}
                alt={`Camera preview ${node.edge_id}`}
                className={`max-w-full max-h-[70vh] object-contain transition-all duration-300 ${
                  flashHighlight ? "ring-4 ring-emerald-400 scale-[1.005] shadow-[0_0_40px_rgba(52,211,153,0.6)]" : ""
                }`}
              />

              {/* HUD Overlay - Top Left: Traffic Status Badge */}
              <div className="absolute top-4 left-4 flex flex-col gap-2 z-10">
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
              <div className="absolute top-4 right-4 z-10 bg-white/95 backdrop-blur-md border border-slate-200 rounded-xl p-3 shadow-xl text-right min-w-[160px]">
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
              <div className="absolute bottom-4 left-4 z-10 bg-white/95 backdrop-blur-md border border-slate-200 rounded-lg px-3 py-1.5 text-xs text-slate-700 shadow-md">
                <div className="flex items-center gap-2 font-medium">
                  <span className="text-emerald-600 font-mono font-bold flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                    REC
                  </span>
                  <span>{node.road_name || "Đoạn Nguyễn Trãi"}</span>
                  <span className="text-slate-300">•</span>
                  <span className="text-slate-500 font-mono">FOV: {node.camera_fov || 65}°</span>
                </div>
              </div>

              {/* HUD Overlay - Bottom Right: Last Updated Clock */}
              <div className="absolute bottom-4 right-4 z-10 bg-white/95 backdrop-blur-md border border-slate-200 rounded-lg px-3 py-1.5 text-xs text-slate-700 shadow-md flex items-center gap-2 font-medium">
                <Clock className="w-3.5 h-3.5 text-slate-400" />
                <span>Cập nhật: <span className="font-mono text-emerald-600 font-bold">{lastCapturedTime}</span></span>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center p-8 text-center text-slate-400 gap-3">
              <Camera className="w-12 h-12 text-slate-600 stroke-[1.5]" />
              <p className="text-sm">Chưa có ảnh chụp mới nhất từ camera này.</p>
              <button
                onClick={handleRequestSnapshot}
                disabled={isCapturing}
                className="mt-2 inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold transition-all shadow-md shadow-blue-500/20 active:scale-95"
              >
                <Camera className="w-4 h-4" />
                <span>Chụp ảnh ngay</span>
              </button>
            </div>
          )}

          {/* Loading Spinner Overlay when Capturing */}
          {isCapturing && (
            <div className="absolute inset-0 bg-slate-900/70 backdrop-blur-sm flex flex-col items-center justify-center z-20 gap-3">
              <div className="w-10 h-10 border-3 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-sm font-semibold text-white tracking-wide animate-pulse">
                Đang gửi lệnh và chờ Jetson chụp ảnh...
              </p>
            </div>
          )}
        </div>

        {/* Footer Toolbar */}
        <div className="flex flex-wrap items-center justify-between px-6 py-3.5 border-t border-slate-200 bg-slate-50 gap-3">
          <div className="flex items-center gap-2 text-xs">
            <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white text-slate-700 border border-slate-200 shadow-xs font-medium">
              <Zap className="w-3.5 h-3.5 text-amber-500" />
              <span>Chụp tự động khi kẹt xe: <strong className="text-emerald-600">BẬT</strong></span>
            </span>
            {actionMessage && (
              <span className="text-xs text-blue-600 font-semibold animate-fade-in">
                {actionMessage}
              </span>
            )}
          </div>

          <div className="flex items-center gap-2.5">
            <button
              onClick={handleDownload}
              disabled={!finalImageUrl}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-white hover:bg-slate-100 text-slate-700 text-xs font-semibold border border-slate-300 shadow-xs transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              title="Tải ảnh JPEG về máy"
            >
              <Download className="w-3.5 h-3.5 text-slate-500" />
              <span>Tải ảnh về máy</span>
            </button>

            <button
              onClick={handleRequestSnapshot}
              disabled={isCapturing}
              className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold text-white shadow-md transition-all ${
                isCapturing
                  ? "bg-blue-600/60 cursor-not-allowed"
                  : "bg-blue-600 hover:bg-blue-700 shadow-blue-500/20 active:scale-95"
              }`}
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isCapturing ? "animate-spin" : ""}`} />
              <span>{isCapturing ? "Đang chụp..." : "📸 Yêu cầu chụp ảnh mới"}</span>
            </button>
          </div>
        </div>

      </div>
    </div>
  );
};
