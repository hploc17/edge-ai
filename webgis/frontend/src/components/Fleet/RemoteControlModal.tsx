import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Camera,
  CheckCircle,
  ChevronDown,
  Loader2,
  Monitor,
  MonitorOff,
  Play,
  RefreshCw,
  Save,
  Square,
  Trash2,
  Video,
  X,
  ZoomIn,
} from "lucide-react";
import axios from "axios";
import { wsService } from "../../services/websocket";
import { API_HOST_URL } from "../../services/api";

const API_BASE = `${API_HOST_URL}/api/v1`;


// ── Kiểu dữ liệu ──────────────────────────────────────────────────────────────

interface RoiPoint {
  x: number; // Normalized [0.0 - 1.0]
  y: number;
}

interface RoiConfig {
  detectionRoi: RoiPoint[];
  analysisRoi: RoiPoint[];
  roadWidthM: number;
  roadLengthM: number;
  laneCount: number;
}

type DrawMode = "detection" | "analysis" | null;
type Stage = "idle" | "loading_videos" | "selecting_video" | "loading_preview" | "preview_ready" | "drawing" | "saving_roi" | "pipeline_control";

interface RemoteControlModalProps {
  edgeId: string;
  nodeName: string;
  onClose: () => void;
  /** Khi true: modal ẩn đi, chỉ hiển thị floating chip */
  isMinimized?: boolean;
  onMinimize?: () => void;
  onRestore?: () => void;
  wsRef?: React.RefObject<WebSocket | null>;
}

const COLORS = {
  detection: { stroke: "#F97316", fill: "rgba(249, 115, 22, 0.15)" },  // Cam
  analysis: { stroke: "#06B6D4", fill: "rgba(6, 182, 212, 0.15)" },    // Cyan
};

// ── Utility: vẽ polygon trên canvas ───────────────────────────────────────────

function drawPolygon(
  ctx: CanvasRenderingContext2D,
  points: RoiPoint[],
  canvasW: number,
  canvasH: number,
  color: { stroke: string; fill: string },
  label: string,
  closing: boolean = true
) {
  if (points.length < 1) return;
  const px = points.map((p) => ({ x: p.x * canvasW, y: p.y * canvasH }));

  ctx.beginPath();
  ctx.moveTo(px[0].x, px[0].y);
  px.slice(1).forEach((p) => ctx.lineTo(p.x, p.y));
  if (closing && px.length >= 3) ctx.closePath();

  ctx.fillStyle = color.fill;
  if (closing && px.length >= 3) ctx.fill();
  ctx.strokeStyle = color.stroke;
  ctx.lineWidth = 2;
  ctx.stroke();

  // Vẽ điểm
  px.forEach((p, i) => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
    ctx.fillStyle = color.stroke;
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.font = "bold 11px monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(i + 1), p.x, p.y);
  });

  // Nhãn
  if (px.length > 0) {
    const cx = px.reduce((s, p) => s + p.x, 0) / px.length;
    const cy = px.reduce((s, p) => s + p.y, 0) / px.length;
    ctx.fillStyle = color.stroke;
    ctx.font = "bold 12px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(label, cx, cy);
  }
}

// ── Component chính ─────────────────────────────────────────────────────────────

export const RemoteControlModal: React.FC<RemoteControlModalProps> = ({
  edgeId,
  nodeName,
  onClose,
  isMinimized = false,
  onMinimize,
  onRestore,
}) => {
  const [stage, setStage] = useState<Stage>("idle");
  const [sourceType, setSourceType] = useState<"csi" | "file">("csi");
  const [videos, setVideos] = useState<string[]>([]);
  const [selectedVideo, setSelectedVideo] = useState<string>("csi");
  const [previewImage, setPreviewImage] = useState<string>("");
  const [requestId, setRequestId] = useState<string>("");
  const [drawMode, setDrawMode] = useState<DrawMode>(null);
  const [roiConfig, setRoiConfig] = useState<RoiConfig>({
    detectionRoi: [],
    analysisRoi: [],
    roadWidthM: 7.5,
    roadLengthM: 20.0,
    laneCount: 2,
  });
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [displayMode, setDisplayMode] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [errorMessage, setErrorMessage] = useState<string>("");

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  // ── Lắng nghe WebSocket để nhận preview frame và command_result ─────────────

  useEffect(() => {
    const unsubscribe = wsService.subscribe((msg: any) => {
      try {
        if (msg.type === "preview_frame" && msg.edge_id === edgeId) {
          if (msg.image_data) {
            setPreviewImage(msg.image_data);
            setStage("preview_ready");
            setStatusMessage("Đã nhận khung hình từ Jetson. Chọn chế độ vẽ ROI.");
          }
        }
        if (msg.type === "command_result" && msg.edge_id === edgeId) {
          if (msg.action === "set_roi_remote") {
            if (msg.status === "completed") {
              setErrorMessage("");
              setStatusMessage("✅ ROI đã được lưu thành công trên Jetson.");
            } else if (msg.status !== "not_implemented") {
              setErrorMessage("Lỗi lưu ROI: " + JSON.stringify(msg.message));
            }
          }
          if (msg.action === "start_pipeline") {
            if (msg.status === "completed") {
              setPipelineRunning(true);
              setErrorMessage("");
              setStatusMessage("✅ Pipeline khởi động thành công (PID=" + (msg.message?.pid || "?") + ")");
            } else if (!pipelineRunning) {
              setErrorMessage("Lỗi khởi động pipeline: " + JSON.stringify(msg.message));
            }
          }
          if (msg.action === "stop_pipeline") {
            setPipelineRunning(false);
            const stopMsg = typeof msg.message === "string" ? msg.message : "✅ Pipeline đã kết thúc/dừng.";
            setStatusMessage(stopMsg);
          }
          if (msg.action === "list_videos" && msg.status === "completed") {
            const vids = Array.isArray(msg.message) ? msg.message : [];
            setVideos(vids);
            setStage("selecting_video");
          }
        }
      } catch (e) {
        // ignore
      }
    });

    return () => unsubscribe();
  }, [edgeId]);


  // ── Vẽ lại canvas mỗi khi ROI thay đổi ───────────────────────────────────

  const renderCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img || !img.complete || !previewImage) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    canvas.width = img.naturalWidth || img.width || 1280;
    canvas.height = img.naturalHeight || img.height || 720;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    drawPolygon(ctx, roiConfig.detectionRoi, canvas.width, canvas.height, COLORS.detection, "DETECTION ROI", true);
    drawPolygon(ctx, roiConfig.analysisRoi, canvas.width, canvas.height, COLORS.analysis, "ANALYSIS ROI", true);
  }, [roiConfig, previewImage]);

  useEffect(() => {
    renderCanvas();
  }, [renderCanvas]);

  // ── Xử lý click trên canvas để thêm điểm ROI ───────────────────────────────

  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!drawMode) return;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const nx = ((e.clientX - rect.left) * scaleX) / canvas.width;
    const ny = ((e.clientY - rect.top) * scaleY) / canvas.height;
    const pt: RoiPoint = { x: Math.max(0, Math.min(1, nx)), y: Math.max(0, Math.min(1, ny)) };

    setRoiConfig((prev) => {
      if (drawMode === "detection") return { ...prev, detectionRoi: [...prev.detectionRoi, pt] };
      return { ...prev, analysisRoi: [...prev.analysisRoi, pt] };
    });
  };

  const handleCanvasRightClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    if (!drawMode) return;
    setRoiConfig((prev) => {
      if (drawMode === "detection") return { ...prev, detectionRoi: prev.detectionRoi.slice(0, -1) };
      return { ...prev, analysisRoi: prev.analysisRoi.slice(0, -1) };
    });
  };

  // ── Step 1: Tải danh sách video ─────────────────────────────────────────────

  const handleLoadVideos = async () => {
    setStage("loading_videos");
    setErrorMessage("");
    try {
      const res = await axios.get(`${API_BASE}/nodes/${edgeId}/videos`, { timeout: 20000 });
      setVideos(res.data.videos || []);
      setStage("selecting_video");
    } catch (e: any) {
      // Fallback: nếu Jetson offline, gửi qua MQTT và chờ WS
      setStatusMessage("Đang chờ Jetson phản hồi qua MQTT...");
    }
  };

  // ── Step 2: Lấy frame preview ───────────────────────────────────────────────

  const handleGetPreview = async () => {
    if (sourceType === "file" && !selectedVideo) return;
    setStage("loading_preview");
    setErrorMessage("");
    setPreviewImage("");
    setStatusMessage(
      sourceType === "csi"
        ? "Đang gửi lệnh yêu cầu Camera CSI chụp khung hình..."
        : "Đang gửi yêu cầu đến Jetson..."
    );

    try {
      const res = await axios.post(`${API_BASE}/nodes/${edgeId}/preview`, {
        source_type: sourceType,
        source: sourceType === "csi" ? "csi" : selectedVideo,
      });
      const reqId = res.data.request_id || "";
      setRequestId(reqId);
      setStatusMessage(
        sourceType === "csi"
          ? "Đang chờ Jetson chụp ảnh từ Camera CSI và tải lên..."
          : "Đang chờ Jetson trích xuất khung hình..."
      );

      // Polling fallback nếu WebSocket bị trễ
      let attempts = 0;
      const pollTimer = setInterval(async () => {
        attempts++;
        if (attempts > 12) {
          clearInterval(pollTimer);
          return;
        }
        try {
          const pollRes = await axios.get(`${API_BASE}/nodes/${edgeId}/preview/${reqId}`);
          if (pollRes.data && pollRes.data.image_data) {
            clearInterval(pollTimer);
            setPreviewImage(pollRes.data.image_data);
            setStage("preview_ready");
            setStatusMessage("Đã nhận khung hình từ Jetson! Bạn hãy bắt đầu vẽ ROI ở Bước 3.");
          }
        } catch (_) {
          // Chưa có frame, chờ lượt poll tiếp theo
        }
      }, 2000);
    } catch (e: any) {
      setStage("selecting_video");
      setErrorMessage("Không thể gửi yêu cầu preview: " + e.message);
    }
  };


  // ── Step 3: Lưu ROI ─────────────────────────────────────────────────────────

  const handleSaveRoi = async () => {
    if (roiConfig.detectionRoi.length < 3) {
      setErrorMessage("Vùng Detection ROI cần ít nhất 3 điểm.");
      return;
    }
    if (roiConfig.analysisRoi.length !== 4) {
      setErrorMessage("Vùng Analysis ROI (dùng để tính tốc độ) bắt buộc phải có đúng 4 điểm theo chiều chuyển động của xe.");
      return;
    }
    setStage("saving_roi");
    setErrorMessage("");

    try {
      await axios.post(`${API_BASE}/nodes/${edgeId}/roi`, {
        detection_roi: roiConfig.detectionRoi.map((p) => [p.x, p.y]),
        analysis_roi: roiConfig.analysisRoi.map((p) => [p.x, p.y]),
        road_width_m: roiConfig.roadWidthM,
        road_length_m: roiConfig.roadLengthM,
        lane_count: roiConfig.laneCount,
      });
      setStatusMessage("✅ Lệnh lưu ROI đã gửi đến Jetson. Bạn có thể bấm Chạy nhận diện ở Bước 4.");
      setStage("pipeline_control");
    } catch (e: any) {
      setStage("preview_ready");
      setErrorMessage("Lỗi gửi ROI: " + e.message);
    }
  };

  // ── Step 4: Điều khiển Pipeline ─────────────────────────────────────────────

  const handleStartPipeline = async () => {
    setErrorMessage("");
    const isCsi = sourceType === "csi";
    setStatusMessage(`Đang gửi lệnh khởi động nhận diện (${isCsi ? "Camera CSI" : "Video"})...`);
    try {
      await axios.post(`${API_BASE}/nodes/${edgeId}/pipeline/start`, {
        source_type: sourceType,
        source: isCsi ? "csi" : selectedVideo,
        roi_config: "remote",
        display: displayMode,
      });
      setStatusMessage(
        `✅ Đã gửi lệnh khởi động! Jetson đang kích hoạt pipeline nhận diện ${isCsi ? "Camera CSI" : "Video"} với cấu hình ROI vừa vẽ...`
      );
      setPipelineRunning(true);
    } catch (e: any) {
      setErrorMessage("Lỗi khởi động pipeline: " + e.message);
    }
  };


  const handleStopPipeline = async () => {
    setErrorMessage("");
    setStatusMessage("Đang gửi lệnh dừng pipeline...");
    try {
      await axios.post(`${API_BASE}/nodes/${edgeId}/pipeline/stop`);
    } catch (e: any) {
      setErrorMessage("Lỗi dừng pipeline: " + e.message);
    }
  };

  // ── Render ──────────────────────────────────────────────────────────────────

  const isCanvasActive = stage === "preview_ready" || stage === "drawing";
  // Tách biến này ra ngoài để tránh TypeScript type narrowing trong JSX block
  const isSavingRoi = stage === "saving_roi";
  const isLoadingVideos = stage === "loading_videos";
  const isLoadingPreview = stage === "loading_preview";
  const isPipelineStage = stage === "pipeline_control";

  // ── Khi đang minimize: hiển thị floating chip ──────────────────────────────
  if (isMinimized) {
    return (
      <div className="fixed bottom-5 right-5 z-50 flex items-center gap-2 px-4 py-2.5 rounded-2xl bg-slate-900 border border-slate-700 shadow-2xl text-white animate-fade-in">
        <div className={`w-2 h-2 rounded-full ${pipelineRunning ? "bg-emerald-400 animate-pulse" : "bg-slate-400"}`} />
        <div className="text-xs">
          <span className="font-bold">{nodeName}</span>
          <span className="ml-1 text-slate-400">{pipelineRunning ? "· AI đang chạy" : "· Chờ"}</span>
        </div>
        {pipelineRunning && (
          <button
            onClick={handleStopPipeline}
            className="px-2 py-1 bg-red-600 hover:bg-red-700 rounded-lg text-[10px] font-bold transition"
          >
            Dừng
          </button>
        )}
        <button
          onClick={onRestore}
          className="px-2.5 py-1 bg-slate-700 hover:bg-slate-600 rounded-lg text-[10px] font-semibold transition"
        >
          Mở
        </button>
        <button
          onClick={onClose}
          className="p-1 text-slate-400 hover:text-white transition"
          title="Đóng hoàn toàn"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-3 sm:p-6 animate-fade-in">
      <div className="relative w-full max-w-5xl max-h-[92vh] flex flex-col bg-white border border-slate-200 rounded-2xl shadow-2xl overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 bg-white border-b border-slate-200 shrink-0">
          <div className="flex items-center gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-600 shadow-xs">
              <Monitor className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h2 className="text-base sm:text-lg font-bold text-slate-900 tracking-tight">Điều khiển Jetson từ xa</h2>
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200">
                  Remote Control
                </span>
                {pipelineRunning && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" /> LIVE
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-500 font-mono mt-0.5 font-medium">
                {edgeId} · {nodeName}{requestId ? ` · ID: ${requestId.slice(0, 8)}` : ""}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {/* Minimize button */}
            {onMinimize && (
              <button
                onClick={onMinimize}
                className="p-2 text-slate-400 hover:text-slate-700 rounded-xl hover:bg-slate-100 transition-colors"
                title="Thu nhỏ — giữ nguyên trạng thái"
              >
                <span className="w-5 h-5 flex items-center justify-center text-lg font-bold leading-none">─</span>
              </button>
            )}
            <button
              onClick={onClose}
              className="p-2 text-slate-400 hover:text-slate-700 rounded-xl hover:bg-slate-100 transition-colors"
              title="Đóng modal"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="flex flex-1 overflow-hidden">
          {/* Left Panel: Controls */}
          <div className="w-80 flex flex-col gap-4 p-4 bg-slate-50 border-r border-slate-200 overflow-y-auto shrink-0">

            {/* Step 1: Chọn nguồn video / camera */}
            <div className="space-y-2 bg-white p-3 rounded-xl border border-slate-200 shadow-xs">
              <div className="flex items-center justify-between text-xs font-bold text-slate-700 uppercase tracking-wide">
                <span className="flex items-center gap-2">
                  <Video className="w-3.5 h-3.5 text-blue-600" />
                  <span>Bước 1 · Nguồn đầu vào</span>
                </span>
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${
                  sourceType === "csi" ? "bg-emerald-100 text-emerald-700" : "bg-blue-100 text-blue-700"
                }`}>
                  {sourceType === "csi" ? "Camera CSI" : "File Video"}
                </span>
              </div>

              {/* Source Mode Selector */}
              <div className="grid grid-cols-2 p-1 bg-slate-100 rounded-xl gap-1">
                <button
                  type="button"
                  onClick={() => {
                    setSourceType("csi");
                    setSelectedVideo("csi");
                  }}
                  className={`py-1.5 px-2 rounded-lg text-xs font-bold transition flex items-center justify-center gap-1.5 ${
                    sourceType === "csi" ? "bg-white text-blue-700 shadow-xs" : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  <Camera className="w-3.5 h-3.5" />
                  <span>Camera CSI</span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setSourceType("file");
                    setSelectedVideo("");
                  }}
                  className={`py-1.5 px-2 rounded-lg text-xs font-bold transition flex items-center justify-center gap-1.5 ${
                    sourceType === "file" ? "bg-white text-blue-700 shadow-xs" : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  <Video className="w-3.5 h-3.5" />
                  <span>Video file</span>
                </button>
              </div>

              {sourceType === "csi" ? (
                <div className="p-2.5 rounded-xl bg-blue-50/70 border border-blue-100 text-[11px] text-blue-900 space-y-1">
                  <div className="font-bold flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                    <span>CSI Camera (nvarguscamerasrc)</span>
                  </div>
                  <p className="text-slate-600 text-[10px] leading-tight">
                    Jetson Nano sẽ chụp frame trực tiếp từ mắt đọc camera phần cứng để bạn vẽ vùng nhận diện ROI thực tế.
                  </p>
                </div>
              ) : (
                <div className="space-y-2 pt-1">
                  <button
                    id="btn-load-videos"
                    onClick={handleLoadVideos}
                    disabled={isLoadingVideos}
                    className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs font-bold shadow-xs transition"
                  >
                    {isLoadingVideos ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                    Tải danh sách video
                  </button>

                  {videos.length > 0 && (
                    <div className="relative">
                      <select
                        id="select-video"
                        className="w-full pl-3 pr-8 py-2 text-xs rounded-xl bg-white border border-slate-300 text-slate-800 appearance-none focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 shadow-xs font-medium"
                        value={selectedVideo}
                        onChange={(e) => setSelectedVideo(e.target.value)}
                      >
                        <option value="">-- Chọn video --</option>
                        {videos.map((v) => (
                          <option key={v} value={v}>{v}</option>
                        ))}
                      </select>
                      <ChevronDown className="absolute right-3 top-2.5 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Step 2: Preview */}
            <div className="space-y-2 bg-white p-3 rounded-xl border border-slate-200 shadow-xs">
              <div className="flex items-center gap-2 text-xs font-bold text-slate-700 uppercase tracking-wide">
                <Camera className="w-3.5 h-3.5 text-amber-600" />
                <span>Bước 2 · Lấy khung hình</span>
              </div>
              <button
                id="btn-get-preview"
                onClick={handleGetPreview}
                disabled={(sourceType === "file" && !selectedVideo) || isLoadingPreview}
                className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-amber-600 hover:bg-amber-700 disabled:opacity-40 text-white text-xs font-bold shadow-xs transition"
              >
                {isLoadingPreview ? <Loader2 className="w-4 h-4 animate-spin" /> : <ZoomIn className="w-4 h-4" />}
                <span>{sourceType === "csi" ? "📸 Chụp frame từ Camera CSI" : "Lấy khung hình preview"}</span>
              </button>
            </div>

            {/* Step 3: Vẽ ROI */}
            {isCanvasActive && (
              <div className="space-y-2 bg-white p-3 rounded-xl border border-slate-200 shadow-xs">
                <div className="flex items-center gap-2 text-xs font-bold text-slate-700 uppercase tracking-wide">
                  <div className="w-3.5 h-3.5 rounded-sm border-2 border-orange-500" />
                  <span>Bước 3 · Vẽ ROI</span>
                </div>
                <p className="text-[10px] text-slate-500 font-medium">Chuột trái: thêm điểm · Chuột phải: xóa điểm cuối</p>

                {(["detection", "analysis"] as DrawMode[]).map((mode) => {
                  const col = COLORS[mode!];
                  const pts = mode === "detection" ? roiConfig.detectionRoi : roiConfig.analysisRoi;
                  const isActive = drawMode === mode;
                  return (
                    <div key={mode} className="rounded-xl border overflow-hidden bg-slate-50" style={{ borderColor: col.stroke + "66" }}>
                      <button
                        id={`btn-draw-${mode}`}
                        onClick={() => { setDrawMode(isActive ? null : mode); setStage("drawing"); }}
                        className="w-full flex items-center justify-between px-3 py-2 text-xs font-bold transition"
                        style={{ backgroundColor: isActive ? col.stroke + "20" : "transparent", color: col.stroke }}
                      >
                        <span>{mode === "detection" ? "DETECTION ROI" : "ANALYSIS ROI"}</span>
                        <span className="font-mono text-[10px] bg-white border border-slate-200 text-slate-700 px-1.5 py-0.5 rounded shadow-2xs font-semibold">{pts.length} điểm</span>
                      </button>
                      {pts.length > 0 && (
                        <button
                          onClick={() => setRoiConfig((prev) => mode === "detection" ? { ...prev, detectionRoi: [] } : { ...prev, analysisRoi: [] })}
                          className="w-full flex items-center gap-1 px-3 py-1 text-[10px] text-red-600 hover:bg-red-50 transition border-t border-slate-200"
                        >
                          <Trash2 className="w-3 h-3" /> Xóa điểm
                        </button>
                      )}
                    </div>
                  );
                })}

                {/* Thông số đường */}
                <div className="space-y-2 pt-1 border-t border-slate-100">
                  {[
                    { label: "Chiều rộng (m)", key: "roadWidthM", step: 0.5, min: 1 },
                    { label: "Chiều dài (m)", key: "roadLengthM", step: 1, min: 5 },
                    { label: "Số làn xe", key: "laneCount", step: 1, min: 1 },
                  ].map(({ label, key, step, min }) => (
                    <div key={key}>
                      <label className="block text-[10px] font-semibold text-slate-600 mb-1">{label}</label>
                      <input
                        type="number"
                        step={step}
                        min={min}
                        value={(roiConfig as any)[key]}
                        onChange={(e) => setRoiConfig((prev) => ({ ...prev, [key]: parseFloat(e.target.value) || 0 }))}
                        className="w-full px-3 py-1.5 text-xs rounded-lg bg-white border border-slate-300 text-slate-800 shadow-xs focus:outline-none focus:border-blue-500 font-medium"
                      />
                    </div>
                  ))}
                </div>

                <button
                  id="btn-save-roi"
                  onClick={handleSaveRoi}
                  disabled={roiConfig.detectionRoi.length < 3 || roiConfig.analysisRoi.length < 3 || isSavingRoi}
                  className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 text-white text-xs font-bold shadow-xs transition"
                >
                  {isSavingRoi ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                  Lưu cấu hình ROI
                </button>
              </div>
            )}

            {/* Step 4: Pipeline */}
            {isPipelineStage && (
              <div className="space-y-2 bg-white p-3 rounded-xl border border-slate-200 shadow-xs">
                <div className="flex items-center gap-2 text-xs font-bold text-slate-700 uppercase tracking-wide">
                  <Play className="w-3.5 h-3.5 text-emerald-600" />
                  <span>Bước 4 · Pipeline</span>
                </div>

                {/* Toggle display */}
                <button
                  id="btn-toggle-display"
                  onClick={() => setDisplayMode((v) => !v)}
                  className={`w-full flex items-center justify-between px-3 py-2 rounded-xl border text-xs font-semibold transition ${displayMode ? "bg-amber-50 border-amber-300 text-amber-800" : "bg-slate-50 border-slate-300 text-slate-700 hover:bg-slate-100"}`}
                >
                  <span className="flex items-center gap-2">
                    {displayMode ? <Monitor className="w-4 h-4 text-amber-600" /> : <MonitorOff className="w-4 h-4 text-slate-500" />}
                    {displayMode ? "Bật màn hình Jetson" : "Tắt màn hình (sản xuất)"}
                  </span>
                  <span className={`text-[10px] px-2 py-0.5 rounded font-bold ${displayMode ? "bg-amber-500 text-white" : "bg-slate-200 text-slate-600"}`}>
                    {displayMode ? "ON" : "OFF"}
                  </span>
                </button>

                <div className="flex gap-2">
                  <button
                    id="btn-start-pipeline"
                    onClick={handleStartPipeline}
                    disabled={pipelineRunning || (sourceType === "file" && !selectedVideo)}
                    className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 text-white text-xs font-bold shadow-xs transition"
                    title={sourceType === "csi" ? "Khởi động nhận diện CSI với ROI vừa cấu hình" : "Chạy video với ROI vừa cấu hình"}
                  >
                    <Play className="w-4 h-4 fill-current" />
                    <span>{sourceType === "csi" ? "🚀 Chạy nhận diện CSI" : "Chạy Video"}</span>
                  </button>

                  <button
                    id="btn-stop-pipeline"
                    onClick={handleStopPipeline}
                    disabled={!pipelineRunning}
                    className="w-24 flex items-center justify-center gap-1.5 py-2.5 rounded-xl bg-red-600 hover:bg-red-700 disabled:opacity-40 text-white text-xs font-bold shadow-xs transition"
                  >
                    <Square className="w-4 h-4 fill-current" />
                    <span>Dừng</span>
                  </button>
                </div>

                {pipelineRunning && (
                  <div className="space-y-2 pt-1">
                    <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-emerald-50 border border-emerald-200">
                      <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                      <span className="text-[11px] text-emerald-800 font-semibold">AI Pipeline đang phân tích</span>
                    </div>
                    <button
                      id="btn-view-map-results"
                      onClick={onMinimize ? onMinimize : onClose}
                      className="w-full flex items-center justify-center gap-2 py-2.5 px-3 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold transition shadow-md shadow-blue-500/20"
                    >
                      <span>🗺️ Xem lưu lượng trên Bản đồ</span>
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Status / Error */}
            {statusMessage && (
              <div className="flex items-start gap-2 px-3 py-2 rounded-xl bg-blue-50 border border-blue-200 shadow-xs">
                <CheckCircle className="w-3.5 h-3.5 text-blue-600 mt-0.5 shrink-0" />
                <p className="text-[11px] text-blue-800 font-medium">{statusMessage}</p>
              </div>
            )}
            {errorMessage && (
              <div className="px-3 py-2 rounded-xl bg-red-50 border border-red-200 shadow-xs">
                <p className="text-[11px] text-red-800 font-medium">{errorMessage}</p>
              </div>
            )}
          </div>

          {/* Right Panel: Canvas */}
          <div className="flex-1 flex items-center justify-center bg-slate-950 relative overflow-hidden select-none">
            {!previewImage ? (
              <div className="text-center text-slate-500 space-y-3 p-8">
                <Camera className="w-16 h-16 mx-auto text-slate-600 stroke-[1.2]" />
                <p className="text-sm font-semibold text-slate-300">Chưa có khung hình</p>
                <p className="text-xs text-slate-400">Chọn video ở cột bên trái và bấm "Lấy khung hình preview"</p>
              </div>
            ) : (
              <div className="relative w-full h-full flex items-center justify-center p-3">
                {/* Hidden image dùng để vẽ lên canvas */}
                <img
                  ref={imgRef}
                  src={previewImage}
                  onLoad={renderCanvas}
                  className="hidden"
                  alt=""
                />
                <canvas
                  ref={canvasRef}
                  onClick={handleCanvasClick}
                  onContextMenu={handleCanvasRightClick}
                  className="max-w-full max-h-full rounded-xl border border-slate-700 shadow-2xl"
                  style={{ cursor: drawMode ? "crosshair" : "default" }}
                />
                {drawMode && (
                  <div className="absolute top-4 left-1/2 -translate-x-1/2 px-4 py-1.5 rounded-full text-xs font-bold text-white shadow-xl backdrop-blur-md"
                    style={{ backgroundColor: COLORS[drawMode].stroke }}>
                    Đang vẽ {drawMode.toUpperCase()} ROI · Chuột trái: thêm điểm · Chuột phải: xóa
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
