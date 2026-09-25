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

const API_BASE = "http://localhost:8000/api/v1";

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
  wsRef,
}) => {
  const [stage, setStage] = useState<Stage>("idle");
  const [videos, setVideos] = useState<string[]>([]);
  const [selectedVideo, setSelectedVideo] = useState<string>("");
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
    const ws = wsRef?.current;
    if (!ws) return;

    const handler = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "preview_frame" && msg.edge_id === edgeId && msg.request_id === requestId) {
          setPreviewImage(msg.image_data);
          setStage("preview_ready");
          setStatusMessage("Đã nhận khung hình từ Jetson. Chọn chế độ vẽ ROI.");
        }
        if (msg.type === "command_result" && msg.edge_id === edgeId) {
          if (msg.action === "set_roi_remote") {
            if (msg.status === "completed") {
              setStatusMessage("✅ ROI đã được lưu thành công trên Jetson.");
            } else {
              setErrorMessage("Lỗi lưu ROI: " + JSON.stringify(msg.message));
            }
          }
          if (msg.action === "start_pipeline") {
            if (msg.status === "completed") {
              setPipelineRunning(true);
              setStatusMessage("✅ Pipeline khởi động thành công (PID=" + (msg.message?.pid || "?") + ")");
            } else {
              setErrorMessage("Lỗi khởi động pipeline: " + JSON.stringify(msg.message));
            }
          }
          if (msg.action === "stop_pipeline") {
            setPipelineRunning(false);
            setStatusMessage("✅ Pipeline đã dừng.");
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
    };

    ws.addEventListener("message", handler);
    return () => ws.removeEventListener("message", handler);
  }, [wsRef, edgeId, requestId]);

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
    if (!selectedVideo) return;
    setStage("loading_preview");
    setErrorMessage("");
    setPreviewImage("");
    setStatusMessage("Đang gửi yêu cầu đến Jetson...");

    try {
      const res = await axios.post(`${API_BASE}/nodes/${edgeId}/preview`, {
        source_type: "file",
        source: selectedVideo,
      });
      setRequestId(res.data.request_id || "");
      setStatusMessage("Đang chờ Jetson chụp khung hình (tối đa 30s)...");
    } catch (e: any) {
      setStage("selecting_video");
      setErrorMessage("Không thể gửi yêu cầu preview: " + e.message);
    }
  };

  // ── Step 3: Lưu ROI ─────────────────────────────────────────────────────────

  const handleSaveRoi = async () => {
    if (roiConfig.detectionRoi.length < 3 || roiConfig.analysisRoi.length < 3) {
      setErrorMessage("Cần ít nhất 3 điểm cho cả Detection ROI và Analysis ROI.");
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
      setStatusMessage("Lệnh lưu ROI đã gửi. Đang chờ Jetson xác nhận...");
      setStage("pipeline_control");
    } catch (e: any) {
      setStage("preview_ready");
      setErrorMessage("Lỗi gửi ROI: " + e.message);
    }
  };

  // ── Step 4: Điều khiển Pipeline ─────────────────────────────────────────────

  const handleStartPipeline = async () => {
    setErrorMessage("");
    setStatusMessage("Đang gửi lệnh khởi động pipeline...");
    try {
      await axios.post(`${API_BASE}/nodes/${edgeId}/pipeline/start`, {
        source_type: "file",
        source: selectedVideo,
        roi_config: "remote",
        display: displayMode,
      });
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="relative w-full max-w-5xl max-h-[95vh] flex flex-col bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 bg-slate-800 border-b border-slate-700 shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-blue-600/20 border border-blue-500/40">
              <Monitor className="w-5 h-5 text-blue-400" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-white">Điều khiển Jetson từ xa</h2>
              <p className="text-[11px] text-slate-400 font-mono">{edgeId} · {nodeName}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex flex-1 overflow-hidden">
          {/* Left Panel: Controls */}
          <div className="w-72 flex flex-col gap-4 p-4 bg-slate-850 border-r border-slate-700 overflow-y-auto shrink-0">

            {/* Step 1: Danh sách video */}
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs font-bold text-slate-300 uppercase tracking-wide">
                <Video className="w-3.5 h-3.5 text-blue-400" />
                <span>Bước 1 · Chọn nguồn video</span>
              </div>
              <button
                id="btn-load-videos"
                onClick={handleLoadVideos}
                disabled={isLoadingVideos}
                className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-bold transition"
              >
                {isLoadingVideos ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                Tải danh sách video
              </button>

              {videos.length > 0 && (
                <div className="relative">
                  <select
                    id="select-video"
                    className="w-full pl-3 pr-8 py-2 text-xs rounded-xl bg-slate-700 border border-slate-600 text-white appearance-none focus:outline-none focus:border-blue-500"
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

            {/* Step 2: Preview */}
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs font-bold text-slate-300 uppercase tracking-wide">
                <Camera className="w-3.5 h-3.5 text-orange-400" />
                <span>Bước 2 · Lấy khung hình</span>
              </div>
              <button
                id="btn-get-preview"
                onClick={handleGetPreview}
                disabled={!selectedVideo || isLoadingPreview}
                className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-orange-600 hover:bg-orange-500 disabled:opacity-40 text-white text-xs font-bold transition"
              >
                {isLoadingPreview ? <Loader2 className="w-4 h-4 animate-spin" /> : <ZoomIn className="w-4 h-4" />}
                Lấy khung hình preview
              </button>
            </div>

            {/* Step 3: Vẽ ROI */}
            {isCanvasActive && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs font-bold text-slate-300 uppercase tracking-wide">
                  <div className="w-3.5 h-3.5 rounded-sm border-2 border-orange-400" />
                  <span>Bước 3 · Vẽ ROI</span>
                </div>
                <p className="text-[10px] text-slate-500">Chuột trái: thêm điểm · Chuột phải: xóa điểm cuối</p>

                {(["detection", "analysis"] as DrawMode[]).map((mode) => {
                  const col = COLORS[mode!];
                  const pts = mode === "detection" ? roiConfig.detectionRoi : roiConfig.analysisRoi;
                  const isActive = drawMode === mode;
                  return (
                    <div key={mode} className="rounded-xl border overflow-hidden" style={{ borderColor: col.stroke + "66" }}>
                      <button
                        id={`btn-draw-${mode}`}
                        onClick={() => { setDrawMode(isActive ? null : mode); setStage("drawing"); }}
                        className="w-full flex items-center justify-between px-3 py-2 text-xs font-bold transition"
                        style={{ backgroundColor: isActive ? col.stroke + "33" : "transparent", color: col.stroke }}
                      >
                        <span>{mode === "detection" ? "DETECTION ROI" : "ANALYSIS ROI"}</span>
                        <span className="font-mono text-[10px] bg-black/30 px-1.5 py-0.5 rounded">{pts.length} điểm</span>
                      </button>
                      {pts.length > 0 && (
                        <button
                          onClick={() => setRoiConfig((prev) => mode === "detection" ? { ...prev, detectionRoi: [] } : { ...prev, analysisRoi: [] })}
                          className="w-full flex items-center gap-1 px-3 py-1 text-[10px] text-red-400 hover:bg-red-500/10 transition"
                        >
                          <Trash2 className="w-3 h-3" /> Xóa điểm
                        </button>
                      )}
                    </div>
                  );
                })}

                {/* Thông số đường */}
                <div className="space-y-2 pt-1">
                  {[
                    { label: "Chiều rộng (m)", key: "roadWidthM", step: 0.5, min: 1 },
                    { label: "Chiều dài (m)", key: "roadLengthM", step: 1, min: 5 },
                    { label: "Số làn xe", key: "laneCount", step: 1, min: 1 },
                  ].map(({ label, key, step, min }) => (
                    <div key={key}>
                      <label className="block text-[10px] text-slate-400 mb-1">{label}</label>
                      <input
                        type="number"
                        step={step}
                        min={min}
                        value={(roiConfig as any)[key]}
                        onChange={(e) => setRoiConfig((prev) => ({ ...prev, [key]: parseFloat(e.target.value) || 0 }))}
                        className="w-full px-3 py-1.5 text-xs rounded-lg bg-slate-700 border border-slate-600 text-white focus:outline-none focus:border-blue-500"
                      />
                    </div>
                  ))}
                </div>

                <button
                  id="btn-save-roi"
                  onClick={handleSaveRoi}
                  disabled={roiConfig.detectionRoi.length < 3 || roiConfig.analysisRoi.length < 3 || isSavingRoi}
                  className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white text-xs font-bold transition"
                >
                  {isSavingRoi ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                  Lưu cấu hình ROI
                </button>
              </div>
            )}

            {/* Step 4: Pipeline */}
            {isPipelineStage && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs font-bold text-slate-300 uppercase tracking-wide">
                  <Play className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Bước 4 · Pipeline</span>
                </div>

                {/* Toggle display */}
                <button
                  id="btn-toggle-display"
                  onClick={() => setDisplayMode((v) => !v)}
                  className={`w-full flex items-center justify-between px-3 py-2 rounded-xl border text-xs font-semibold transition ${displayMode ? "bg-yellow-500/20 border-yellow-500/50 text-yellow-300" : "bg-slate-700 border-slate-600 text-slate-300"}`}
                >
                  <span className="flex items-center gap-2">
                    {displayMode ? <Monitor className="w-4 h-4" /> : <MonitorOff className="w-4 h-4" />}
                    {displayMode ? "Bật màn hình Jetson" : "Tắt màn hình (sản xuất)"}
                  </span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${displayMode ? "bg-yellow-500 text-black" : "bg-slate-600 text-slate-300"}`}>
                    {displayMode ? "ON" : "OFF"}
                  </span>
                </button>

                <div className="flex gap-2">
                  <button
                    id="btn-start-pipeline"
                    onClick={handleStartPipeline}
                    disabled={pipelineRunning}
                    className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white text-xs font-bold transition"
                  >
                    <Play className="w-4 h-4" /> Chạy
                  </button>
                  <button
                    id="btn-stop-pipeline"
                    onClick={handleStopPipeline}
                    disabled={!pipelineRunning}
                    className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl bg-red-600 hover:bg-red-500 disabled:opacity-40 text-white text-xs font-bold transition"
                  >
                    <Square className="w-4 h-4" /> Dừng
                  </button>
                </div>

                {pipelineRunning && (
                  <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-emerald-500/10 border border-emerald-500/30">
                    <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                    <span className="text-[11px] text-emerald-300 font-semibold">Pipeline đang chạy</span>
                  </div>
                )}
              </div>
            )}

            {/* Status / Error */}
            {statusMessage && (
              <div className="flex items-start gap-2 px-3 py-2 rounded-xl bg-blue-500/10 border border-blue-500/30">
                <CheckCircle className="w-3.5 h-3.5 text-blue-400 mt-0.5 shrink-0" />
                <p className="text-[11px] text-blue-300">{statusMessage}</p>
              </div>
            )}
            {errorMessage && (
              <div className="px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/30">
                <p className="text-[11px] text-red-300">{errorMessage}</p>
              </div>
            )}
          </div>

          {/* Right Panel: Canvas */}
          <div className="flex-1 flex items-center justify-center bg-slate-950 relative overflow-hidden">
            {!previewImage ? (
              <div className="text-center text-slate-600 space-y-3">
                <Camera className="w-16 h-16 mx-auto opacity-30" />
                <p className="text-sm font-medium">Chưa có khung hình</p>
                <p className="text-[11px]">Chọn video và bấm "Lấy khung hình preview"</p>
              </div>
            ) : (
              <div className="relative w-full h-full flex items-center justify-center p-2">
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
                  className="max-w-full max-h-full rounded-xl border border-slate-700 shadow-lg"
                  style={{ cursor: drawMode ? "crosshair" : "default" }}
                />
                {drawMode && (
                  <div className="absolute top-4 left-1/2 -translate-x-1/2 px-4 py-1.5 rounded-full text-xs font-bold text-white shadow-lg"
                    style={{ backgroundColor: COLORS[drawMode].stroke }}>
                    Đang vẽ {drawMode.toUpperCase()} ROI · Chuột trái: thêm · Chuột phải: xóa
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
