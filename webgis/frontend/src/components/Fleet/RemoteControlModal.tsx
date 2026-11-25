import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
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
import { MediaMTXPlayer } from "../Camera/MediaMTXPlayer";
import { TrafficUsageHelp } from "../Dashboard/TrafficUsageHelp";

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
  trafficContext: "signalized" | "midblock";
}

type DrawMode = "detection" | "analysis" | null;
type Stage = "idle" | "loading_videos" | "selecting_video" | "loading_preview" | "preview_ready" | "drawing" | "saving_roi" | "pipeline_control";
type PipelineSourceType = "csi" | "file";

const parsePipelineSourceType = (value: unknown): PipelineSourceType | null =>
  value === "csi" || value === "file" ? value : null;

interface RemoteControlModalProps {
  edgeId: string;
  nodeName: string;
  onClose: () => void;
  /** Khi true: modal ẩn đi, chỉ hiển thị floating chip */
  isMinimized?: boolean;
  onMinimize?: () => void;
  onRestore?: () => void;
  wsRef?: React.RefObject<WebSocket | null>;
  onRefreshNodes?: () => void;
}

const COLORS = {
  detection: { stroke: "#F97316", fill: "rgba(249, 115, 22, 0.15)" },  // Cam
  analysis: { stroke: "#06B6D4", fill: "rgba(6, 182, 212, 0.15)" },    // Cyan
};

// ── Utility: vẽ polygon trên canvas ───────────────────────────────────────────

const ANALYSIS_POINT_LABELS = [
  "P1 (Gần-Trái)",
  "P2 (Gần-Phải)",
  "P3 (Xa-Phải)",
  "P4 (Xa-Trái)",
];

function drawPolygon(
  ctx: CanvasRenderingContext2D,
  points: RoiPoint[],
  canvasW: number,
  canvasH: number,
  color: { stroke: string; fill: string },
  label: string,
  closing: boolean = true,
  isAnalysisRoi: boolean = false
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

  // Vẽ điểm và nhãn từng điểm
  px.forEach((p, i) => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, isAnalysisRoi ? 7 : 5, 0, Math.PI * 2);
    ctx.fillStyle = color.stroke;
    ctx.fill();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.5;
    ctx.stroke();

    ctx.fillStyle = "#fff";
    ctx.font = "bold 10px monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(isAnalysisRoi ? `P${i + 1}` : String(i + 1), p.x, p.y);

    if (isAnalysisRoi && i < ANALYSIS_POINT_LABELS.length) {
      const pointName = ANALYSIS_POINT_LABELS[i];
      ctx.font = "bold 11px sans-serif";
      const tw = ctx.measureText(pointName).width;
      ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
      ctx.fillRect(p.x + 8, p.y - 10, tw + 8, 20);
      ctx.fillStyle = "#38bdf8";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(pointName, p.x + 12, p.y);
    }
  });

  // Nhãn đa giác ở tâm
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
  onRefreshNodes,
}) => {
  const [stage, setStage] = useState<Stage>("idle");
  const [algorithmVersion, setAlgorithmVersion] = useState("v3");
  const [configLoaded, setConfigLoaded] = useState(false);
  const [trafficConfig, setTrafficConfig] = useState({ reference_speed_kmh: "", minimum_valid_tracks: "3", status_confirm_seconds: "10", free_flow_speed_kmh: "" });
  const roiCommandIdRef = useRef("");
  const [sourceType, setSourceType] = useState<"csi" | "file">("csi");
  const [videos, setVideos] = useState<string[]>([]);
  const [selectedVideo, setSelectedVideo] = useState<string>("csi");
  const [previewImage, setPreviewImage] = useState<string>("");
  const [isSynthetic, setIsSynthetic] = useState<boolean>(false);
  const [requestId, setRequestId] = useState<string>("");
  const requestIdRef = useRef("");
  const previewCommandIdRef = useRef("");
  const previewPollTimerRef = useRef<number | null>(null);
  const ignoreTelemetryUntilRef = useRef(0);
  const [drawMode, setDrawMode] = useState<DrawMode>(null);
  const [roiConfig, setRoiConfig] = useState<RoiConfig>({
    detectionRoi: [],
    analysisRoi: [],
    roadWidthM: 7.5,
    roadLengthM: 20.0,
    laneCount: 2,
    trafficContext: "signalized",
  });
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineSourceType, setPipelineSourceType] = useState<PipelineSourceType | null>(null);
  const [pipelineSourceName, setPipelineSourceName] = useState<string>("");
  const [pendingPipelineAction, setPendingPipelineAction] = useState<"start" | "stop" | null>(null);
  const [displayMode, setDisplayMode] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [activeTab, setActiveTab] = useState<"stream" | "roi">("roi");

  // Telemetry và tóm tắt kết quả khi video hoàn thành
  const latestTelemetryRef = useRef<{
    vehicleCount: number;
    avgSpeed: number;
    status: string;
    timestamp: string;
  } | null>(null);
  const pipelineSourceTypeRef = useRef<PipelineSourceType | null>(null);
  const pipelineSourceNameRef = useRef("");

  const [, setLastCompletedSummary] = useState<{
    sourceType: PipelineSourceType | null;
    sourceName: string;
    vehicleCount: number;
    avgSpeed: number;
    status: string;
    completedAt: string;
  } | null>(null);

  // Bộ đếm Cooldown 2s bảo vệ phần cứng camera CSI & MediaMTX
  const [cooldownSeconds, setCooldownSeconds] = useState<number>(0);

  useEffect(() => {
    if (cooldownSeconds <= 0) return;
    const timer = window.setInterval(() => {
      setCooldownSeconds((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [cooldownSeconds]);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const updateActivePipelineSource = useCallback((sourceType: unknown, sourceName: unknown) => {
    const parsedType = parsePipelineSourceType(sourceType);
    const parsedName = typeof sourceName === "string" ? sourceName : "";
    setPipelineSourceType(parsedType);
    setPipelineSourceName(parsedName);
    pipelineSourceTypeRef.current = parsedType;
    pipelineSourceNameRef.current = parsedName;
    if (parsedType === "csi") {
      setSourceType("csi");
      setSelectedVideo("csi");
    } else if (parsedType === "file") {
      setSourceType("file");
      if (parsedName) setSelectedVideo(parsedName);
    }
  }, []);

  // Chỉ Camera CSI mới có Live Stream; video file luôn giữ giao diện video/ROI.
  useEffect(() => {
    if (pipelineRunning && pipelineSourceType === "csi") {
      setActiveTab("stream");
    } else if (pipelineSourceType === "file") {
      setActiveTab("roi");
    }
  }, [pipelineRunning, pipelineSourceType]);

  // ── Khôi phục trạng thái Pipeline khi mở Modal ──────────────────────────────
  useEffect(() => {
    let isMounted = true;
    const checkPipelineStatus = async () => {
      try {
        const res = await axios.get(`${API_BASE}/nodes/${edgeId}`);
        if (!isMounted) return;
        const current = res.data;
        if (["v1", "v2", "v3"].includes(current?.algorithm_version)) setAlgorithmVersion(current.algorithm_version);
        if (current && Object.prototype.hasOwnProperty.call(current, "reference_speed_kmh")) {
          setTrafficConfig({
            reference_speed_kmh: current.reference_speed_kmh == null ? "" : String(current.reference_speed_kmh),
            free_flow_speed_kmh: current.free_flow_speed_kmh == null ? "" : String(current.free_flow_speed_kmh),
            minimum_valid_tracks: String(current.minimum_valid_tracks ?? 3),
            status_confirm_seconds: String(current.status_confirm_seconds ?? 10),
          });
          setConfigLoaded(true);
        }
        const isRun = Boolean(res.data?.pipeline_running);
        setPipelineRunning(isRun);
        updateActivePipelineSource(
          isRun ? res.data?.pipeline_source_type : null,
          isRun ? res.data?.pipeline_source_name : ""
        );
        if (isRun) {
          setStage("pipeline_control");
          setStatusMessage("✅ AI Pipeline đang hoạt động trên Jetson.");
        }
      } catch (e) {
        try {
          const statRes = await axios.get(`${API_BASE}/nodes/${edgeId}/pipeline/status`);
          if (!isMounted) return;
          const isRun = Boolean(statRes.data?.pipeline_running);
          setPipelineRunning(isRun);
          updateActivePipelineSource(
            isRun ? statRes.data?.pipeline_source_type : null,
            isRun ? statRes.data?.pipeline_source_name : ""
          );
          if (isRun) {
            setStage("pipeline_control");
            setStatusMessage("✅ AI Pipeline đang hoạt động trên Jetson.");
          }
        } catch (_) {}
      }
    };
    checkPipelineStatus();
    return () => {
      isMounted = false;
      if (previewPollTimerRef.current !== null) {
        window.clearInterval(previewPollTimerRef.current);
      }
    };
  }, [edgeId, updateActivePipelineSource]);

  // ── Lắng nghe WebSocket để nhận preview frame, command_result, heartbeat, telemetry ──

  useEffect(() => {
    const unsubscribe = wsService.subscribe((msg: any) => {
      try {
        // Backend đã quy mọi bản tin về mã do Web đặt, nên so khớp trực tiếp (không gắn cứng cặp mã)
        const isTargetNode = msg.edge_id === edgeId;

        // Lắng nghe heartbeat để đồng bộ trạng thái pipeline realtime
        if ((msg.type === "heartbeat" || msg.type === "node_registered") && isTargetNode) {
          if (typeof msg.pipeline_running === "boolean") {
            // Sau khi người dùng chủ động dừng, bỏ qua heartbeat "running" còn tồn
            // trong mạng để không tự bật lại giao diện/live stream.
            if (msg.pipeline_running && Date.now() < ignoreTelemetryUntilRef.current) {
              return;
            }
            setPipelineRunning((prevRunning) => {
              if (prevRunning && !msg.pipeline_running) {
                // Pipeline vừa hoàn thành / dừng
                setLastCompletedSummary({
                  sourceType: pipelineSourceTypeRef.current,
                  sourceName: pipelineSourceNameRef.current,
                  vehicleCount: latestTelemetryRef.current?.vehicleCount ?? 0,
                  avgSpeed: latestTelemetryRef.current?.avgSpeed ?? 0,
                  status: latestTelemetryRef.current?.status ?? "FREE",
                  completedAt: new Date().toLocaleTimeString(),
                });
                setCooldownSeconds(2);
              }
              return msg.pipeline_running;
            });
            if (msg.pipeline_running) {
              setStage((prev) => (prev === "idle" ? "pipeline_control" : prev));
              setStatusMessage("✅ AI Pipeline đang hoạt động trên Jetson.");
              if (Object.prototype.hasOwnProperty.call(msg, "pipeline_source_type")) {
                updateActivePipelineSource(msg.pipeline_source_type, msg.pipeline_source_name);
              }
            } else {
              updateActivePipelineSource(null, "");
            }
          }
        }

        // Lắng nghe telemetry — nếu nhận được telemetry nghĩa là pipeline đang chạy
        if (msg.type === "telemetry" && isTargetNode) {
          // Telemetry có thể đến trễ sau lệnh stop. Không để nó mở lại trạng thái chạy.
          if (Date.now() < ignoreTelemetryUntilRef.current) {
            return;
          }
          setPipelineRunning(true);
          setStage((prev) => (prev === "idle" ? "pipeline_control" : prev));
          const telemetry = {
            vehicleCount: Number(msg.current_vehicle_count ?? msg.vehicle_count ?? 0),
            avgSpeed: Number(msg.avg_speed_kmh ?? msg.speed ?? 0),
            status: msg.traffic_status || "FREE",
            timestamp: new Date().toLocaleTimeString(),
          };
          latestTelemetryRef.current = telemetry;
        }

        if (
          msg.type === "preview_frame" &&
          isTargetNode &&
          msg.request_id === requestIdRef.current
        ) {
          const rawUrl = msg.preview_url || msg.image_data;
          if (rawUrl) {
            // Hỗ trợ cả URL HTTP GET (Fix F3) và Base64 fallback
            const imgSrc = rawUrl.startsWith("data:") 
              ? rawUrl 
              : rawUrl.startsWith("http") 
                ? rawUrl 
                : `${API_HOST_URL}${rawUrl}?t=${Date.now()}`;

            setPreviewImage(imgSrc);
            const synth = Boolean(msg.is_synthetic);
            setIsSynthetic(synth);
            setStage("preview_ready");
            if (synth) {
              setStatusMessage("⚠️ Đã nhận khung hình giả lập (Synthetic Canvas). Camera phần cứng không sẵn sàng!");
            } else {
              setStatusMessage("Đã nhận khung hình từ Jetson. Chọn chế độ vẽ ROI.");
            }
          }
        }
        if (msg.type === "command_result" && isTargetNode) {
          if (msg.action === "set_roi_remote" && msg.command_id === roiCommandIdRef.current) {
            roiCommandIdRef.current = "";
            if (msg.status === "completed") {
              setStatusMessage("Jetson đã lưu ROI và thuật toán đã chọn. Dừng rồi Chạy lại pipeline để áp dụng; tùy chọn CLI tường minh có thể ghi đè cấu hình đã lưu.");
            } else {
              setErrorMessage("Jetson chưa lưu cấu hình: " + (msg.error || msg.message || msg.status));
            }
          }
          if (msg.action === "capture_preview" && msg.command_id === previewCommandIdRef.current) {
            if (msg.status !== "completed" && msg.status !== "not_implemented") {
              setErrorMessage("Lỗi chụp preview: " + (msg.error || msg.message || "Không thể chụp ảnh từ Camera"));
              setStatusMessage("");
              setStage("selecting_video");
            }
            previewCommandIdRef.current = "";
          }
          if (msg.action === "request_status" && msg.status === "completed") {
            const isRun = typeof msg.message === "object" ? Boolean(msg.message?.pipeline_running) : false;
            setPipelineRunning(isRun);
            updateActivePipelineSource(
              isRun ? msg.pipeline_source_type || msg.message?.source_type : null,
              isRun ? msg.pipeline_source_name || msg.message?.source_name || "" : ""
            );
            if (isRun) {
              setStage("pipeline_control");
              setStatusMessage(`✅ Pipeline đang chạy (PID=${msg.message?.pid || "?"}, uptime=${msg.message?.uptime_sec || 0}s)`);
            } else {
              setStatusMessage("ℹ️ AI Pipeline hiện đang dừng trên Jetson.");
              setStage((prev) => (prev === "pipeline_control" ? "idle" : prev));
            }
          }
          if (msg.action === "start_pipeline" || msg.action === "start_csi") {
            if (msg.status === "completed") {
              setPipelineRunning(true);
              updateActivePipelineSource(
                msg.pipeline_source_type || msg.message?.source_type,
                msg.pipeline_source_name || msg.message?.source_name || ""
              );
              setPendingPipelineAction(null);
              setErrorMessage("");
              setStatusMessage("✅ Pipeline khởi động thành công (PID=" + (msg.message?.pid || "?") + ")");
            } else {
              setPendingPipelineAction(null);
              setErrorMessage("Lỗi khởi động pipeline: " + JSON.stringify(msg.message));
            }
          }
          if (msg.action === "stop_pipeline") {
            setPendingPipelineAction(null);
            if (msg.status === "completed") {
              setPipelineRunning((wasRunning) => {
                if (wasRunning) {
                  setLastCompletedSummary({
                    sourceType: pipelineSourceTypeRef.current,
                    sourceName: pipelineSourceNameRef.current,
                    vehicleCount: latestTelemetryRef.current?.vehicleCount ?? 0,
                    avgSpeed: latestTelemetryRef.current?.avgSpeed ?? 0,
                    status: latestTelemetryRef.current?.status ?? "FREE",
                    completedAt: new Date().toLocaleTimeString(),
                  });
                  setCooldownSeconds(2);
                }
                return false;
              });
              updateActivePipelineSource(null, "");
              const stopText = typeof msg.message === "object" ? msg.message?.text : msg.message;
              setStatusMessage(stopText || "✅ Pipeline đã hoàn thành/dừng.");
              setStage("idle");
            } else {
              setErrorMessage("Lỗi dừng pipeline: " + JSON.stringify(msg.message));
            }
          }
        }
      } catch (e) {
        // ignore
      }
    });

    return () => unsubscribe();
  }, [edgeId, updateActivePipelineSource]);


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

    drawPolygon(ctx, roiConfig.detectionRoi, canvas.width, canvas.height, COLORS.detection, "DETECTION ROI", true, false);
    drawPolygon(ctx, roiConfig.analysisRoi, canvas.width, canvas.height, COLORS.analysis, "ANALYSIS ROI", true, true);
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

  const resetSourcePreview = (nextStage: Stage) => {
    if (previewPollTimerRef.current !== null) {
      window.clearInterval(previewPollTimerRef.current);
      previewPollTimerRef.current = null;
    }
    requestIdRef.current = "";
    previewCommandIdRef.current = "";
    setRequestId("");
    setPreviewImage("");
    setIsSynthetic(false);
    latestTelemetryRef.current = null;
    setLastCompletedSummary(null);
    setDrawMode(null);
    setRoiConfig((prev) => ({ ...prev, detectionRoi: [], analysisRoi: [] }));
    setStage(nextStage);
  };

  // ── Step 1: Tải danh sách video ─────────────────────────────────────────────

  const handleLoadVideos = async () => {
    setStage("loading_videos");
    setErrorMessage("");
    setStatusMessage("");
    try {
      const res = await axios.get(`${API_BASE}/nodes/${edgeId}/videos`, { timeout: 20000 });
      const loadedVideos = Array.isArray(res.data?.videos) ? res.data.videos : [];
      setVideos(loadedVideos);
      setStage("selecting_video");
      if (loadedVideos.length === 0) {
        setErrorMessage("Jetson không có file video khả dụng.");
      }
    } catch (e: any) {
      setStage("selecting_video");
      setErrorMessage("Không thể tải danh sách video: " + (e.response?.data?.detail || e.message));
    }
  };

  // ── Step 2: Lấy frame preview ───────────────────────────────────────────────

  const handleGetPreview = async () => {
    if (sourceType === "file" && !selectedVideo) return;
    setStage("loading_preview");
    setErrorMessage("");
    setPreviewImage("");
    setIsSynthetic(false);
    latestTelemetryRef.current = null;
    setLastCompletedSummary(null);
    requestIdRef.current = "";
    previewCommandIdRef.current = "";
    setRequestId("");
    if (previewPollTimerRef.current !== null) {
      window.clearInterval(previewPollTimerRef.current);
      previewPollTimerRef.current = null;
    }
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
      previewCommandIdRef.current = res.data.command_id || "";
      if (!reqId) {
        throw new Error("Backend không trả về mã yêu cầu preview.");
      }
      requestIdRef.current = reqId;
      setRequestId(reqId);
      setStatusMessage(
        sourceType === "csi"
          ? "Đang chờ Jetson chụp ảnh từ Camera CSI và tải lên..."
          : "Đang chờ Jetson trích xuất khung hình..."
      );

      // Polling fallback nếu WebSocket bị trễ
      let attempts = 0;
      previewPollTimerRef.current = window.setInterval(async () => {
        attempts++;
        if (attempts > 12) {
          if (previewPollTimerRef.current !== null) {
            window.clearInterval(previewPollTimerRef.current);
            previewPollTimerRef.current = null;
          }
          if (requestIdRef.current === reqId) {
            setStage("selecting_video");
            setErrorMessage("Jetson không trả frame preview trong thời gian chờ.");
          }
          return;
        }
        try {
          const pollRes = await axios.get(`${API_BASE}/nodes/${edgeId}/preview/${reqId}`);
          const pollUrl = pollRes.data?.preview_url || pollRes.data?.image_data;
          if (pollUrl && requestIdRef.current === reqId) {
            if (previewPollTimerRef.current !== null) {
              window.clearInterval(previewPollTimerRef.current);
              previewPollTimerRef.current = null;
            }
            const imgSrc = pollUrl.startsWith("data:")
              ? pollUrl
              : pollUrl.startsWith("http")
                ? pollUrl
                : `${API_HOST_URL}${pollUrl}?t=${Date.now()}`;

            setPreviewImage(imgSrc);
            const synth = Boolean(pollRes.data.is_synthetic);
            setIsSynthetic(synth);
            setStage("preview_ready");
            if (synth) {
              setStatusMessage("⚠️ Đã nhận khung hình giả lập (Synthetic Canvas). Không phát hiện Camera phần cứng!");
            } else {
              setStatusMessage("Đã nhận khung hình từ Jetson! Bạn hãy bắt đầu vẽ ROI ở Bước 3.");
            }
          }
        } catch (_) {
          // Chưa có frame, chờ lượt poll tiếp theo
        }
      }, 2000);
    } catch (e: any) {
      if (previewPollTimerRef.current !== null) {
        window.clearInterval(previewPollTimerRef.current);
        previewPollTimerRef.current = null;
      }
      setStage("selecting_video");
      setErrorMessage("Không thể gửi yêu cầu preview: " + (e.response?.data?.detail || e.message));
    }
  };


  // ── Step 3: Lưu ROI ─────────────────────────────────────────────────────────

  const handleSaveRoi = async () => {
    const reference = trafficConfig.reference_speed_kmh.trim() === "" ? null : Number(trafficConfig.reference_speed_kmh);
    const freeFlow = trafficConfig.free_flow_speed_kmh.trim() === "" ? null : Number(trafficConfig.free_flow_speed_kmh);
    const tracks = Number(trafficConfig.minimum_valid_tracks);
    const confirmSeconds = Number(trafficConfig.status_confirm_seconds);
    if ((reference !== null && (!Number.isFinite(reference) || reference <= 0)) ||
        (freeFlow !== null && (!Number.isFinite(freeFlow) || freeFlow <= 0)) ||
        !Number.isInteger(tracks) || tracks < 1 || !Number.isFinite(confirmSeconds) || confirmSeconds < 0 || trafficConfig.status_confirm_seconds.trim() === "") {
      setErrorMessage("Tốc độ phải dương hoặc để trống; số xe là số nguyên ≥ 1; thời gian xác nhận ≥ 0 giây.");
      return;
    }
    if (roiConfig.detectionRoi.length < 3) {
      setErrorMessage("Vùng Detection ROI cần ít nhất 3 điểm.");
      return;
    }
    if (roiConfig.analysisRoi.length !== 4) {
      setErrorMessage("Vùng Analysis ROI (dùng để tính tốc độ) bắt buộc phải có đúng 4 điểm theo thứ tự P1->P2->P3->P4.");
      return;
    }

    // R2: Kiểm tra thứ tự và luật phối cảnh trước khi gửi
    const [p1, p2, p3, p4] = roiConfig.analysisRoi;
    const yNear = (p1.y + p2.y) / 2;
    const yFar = (p3.y + p4.y) / 2;
    if (yNear <= yFar) {
      setErrorMessage("Thứ tự điểm sai: P1, P2 (Gần) phải nằm phía dưới khung hình hơn P3, P4 (Xa). Hãy xóa và vẽ lại theo đúng thứ tự: P1 (Gần-Trái) → P2 (Gần-Phải) → P3 (Xa-Phải) → P4 (Xa-Trái).");
      return;
    }
    const distNear = Math.hypot(p2.x - p1.x, p2.y - p1.y);
    const distFar = Math.hypot(p3.x - p4.x, p3.y - p4.y);
    if (distNear > 0.001 && distFar > 1.35 * distNear) {
      setErrorMessage("Cảnh báo phối cảnh: Cạnh xa (P4-P3) rộng hơn cạnh gần (P1-P2) do hiệu ứng phối cảnh. Vui lòng kiểm tra lại thứ tự điểm.");
      return;
    }
    setStage("saving_roi");
    setErrorMessage("");

    try {
      const response = await axios.post(`${API_BASE}/nodes/${edgeId}/roi`, {
        detection_roi: roiConfig.detectionRoi.map((p) => [p.x, p.y]),
        analysis_roi: roiConfig.analysisRoi.map((p) => [p.x, p.y]),
        road_width_m: roiConfig.roadWidthM,
        road_length_m: roiConfig.roadLengthM,
        lane_count: roiConfig.laneCount,
        traffic_context: roiConfig.trafficContext,
        algorithm_version: algorithmVersion,
        reference_speed_kmh: reference,
        minimum_valid_tracks: tracks,
        status_confirm_seconds: confirmSeconds,
        free_flow_speed_kmh: freeFlow,
      });
      roiCommandIdRef.current = response.data.command_id;
      setStatusMessage("Đã gửi cấu hình; đang chờ Jetson xác nhận lưu. Sau xác nhận, Dừng rồi Chạy lại pipeline để áp dụng.");
      setStage("pipeline_control");
    } catch (e: any) {
      setStage("preview_ready");
      setErrorMessage("Lỗi gửi ROI: " + (e.response?.data?.detail || e.message));
    }
  };

  // ── Step 4: Điều khiển Pipeline ─────────────────────────────────────────────

  const handleStartPipeline = async () => {
    setErrorMessage("");
    setLastCompletedSummary(null);
    setPreviewImage("");
    setIsSynthetic(false);
    setDrawMode(null);
    ignoreTelemetryUntilRef.current = 0;
    const isCsi = sourceType === "csi";
    setStatusMessage(`Đang gửi lệnh khởi động nhận diện (${isCsi ? "Camera CSI" : "Video"})...`);
    setPipelineSourceType(sourceType);
    setPipelineSourceName(isCsi ? "Camera CSI" : selectedVideo);
    setPendingPipelineAction("start");
    try {
      await axios.post(`${API_BASE}/nodes/${edgeId}/pipeline/start`, {
        source_type: sourceType,
        source: isCsi ? "csi" : selectedVideo,
        roi_config: "remote",
        display: displayMode,
      });
      setStatusMessage(
        `Đã gửi lệnh khởi động ${isCsi ? "Camera CSI" : `video ${selectedVideo}`} đến Jetson; đang chờ xác nhận...`
      );
      onRefreshNodes?.();
    } catch (e: any) {
      setPendingPipelineAction(null);
      setPipelineSourceType(null);
      setPipelineSourceName("");
      setErrorMessage("Lỗi khởi động pipeline: " + (e.response?.data?.detail || e.message));
    }
  };


  const handleStopPipeline = async () => {
    setErrorMessage("");
    setStatusMessage("Đang gửi lệnh dừng pipeline; đang giải phóng phần cứng...");
    setPendingPipelineAction("stop");
    // Chặn telemetry/heartbeat trễ trong 3 giây và tháo player ngay lập tức.
    ignoreTelemetryUntilRef.current = Date.now() + 3000;
    setCooldownSeconds(2); // Kích hoạt 2s cooldown dọn dẹp phần cứng ngay
    setPipelineRunning(false);
    setActiveTab("roi");
    try {
      await axios.post(`${API_BASE}/nodes/${edgeId}/pipeline/stop`);
      onRefreshNodes?.();
    } catch (e: any) {
      setPendingPipelineAction(null);
      ignoreTelemetryUntilRef.current = 0;
      setCooldownSeconds(0);
      setErrorMessage("Lỗi dừng pipeline: " + (e.response?.data?.detail || e.message));
    }
  };

  // ── Render ──────────────────────────────────────────────────────────────────

  const isCanvasActive = stage === "preview_ready" || stage === "drawing";
  // Tách biến này ra ngoài để tránh TypeScript type narrowing trong JSX block
  const isSavingRoi = stage === "saving_roi";
  const isLoadingVideos = stage === "loading_videos";
  const isLoadingPreview = stage === "loading_preview";
  const isPipelineStage = stage === "pipeline_control";
  const displayedSourceType = pipelineRunning ? pipelineSourceType : sourceType;

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
            <TrafficUsageHelp />
            <fieldset className="space-y-2 rounded-xl border border-slate-200 bg-white p-3">
              <legend className="text-xs font-bold">Cấu hình thuật toán Jetson</legend>
              <label className="block text-xs text-slate-600">Phiên bản (so sánh A/B hoặc quay lại)
                <select value={algorithmVersion} onChange={e => setAlgorithmVersion(e.target.value)} className="mt-1 w-full rounded border border-slate-300 px-2 py-1">
                  <option value="v3">v3 · SPI tốc độ trung vị</option>
                  <option value="v2">v2 · Thuật toán trước</option>
                  <option value="v1">v1 · Thuật toán gốc</option>
                </select>
              </label>
              <p className="text-[11px] text-amber-800">{configLoaded ? "Giá trị lấy từ dữ liệu node gần nhất, chưa phải bản đọc trực tiếp cấu hình trên Jetson. Kiểm tra trước khi lưu." : "Chưa đọc được cấu hình hiện tại. Đây là giá trị khởi tạo; hãy nhập lại cấu hình mong muốn trước khi lưu để tránh ghi đè nhầm."}</p>
              {([
                ["reference_speed_kmh", "Tốc độ tham chiếu / giới hạn (km/h)", "0.1", "0.1"],
                ["minimum_valid_tracks", "Số xe hợp lệ tối thiểu", "1", "1"],
                ["status_confirm_seconds", "Thời gian xác nhận (giây)", "0", "1"],
                ["free_flow_speed_kmh", "Tốc độ dòng tự do (tùy chọn, km/h)", "0.1", "0.1"],
              ] as const).map(([key, label, min, step]) => <label key={key} className="block text-xs text-slate-600">
                {label}
                <input type="number" min={min} step={step} value={trafficConfig[key]} onChange={e => setTrafficConfig(prev => ({ ...prev, [key]: e.target.value }))} className="mt-1 w-full rounded border border-slate-300 px-2 py-1" />
              </label>)}
              <p className="text-[11px] text-slate-600">Ngưỡng SPI cố định 50/25. Để trống tham chiếu: chưa đủ cấu hình, hiển thị UNKNOWN. Các giá trị trên được gửi cùng nút Lưu cấu hình ROI sau khi vẽ đủ ROI.</p>
            </fieldset>

            {/* Step 1: Chọn nguồn video / camera */}
            <div className="space-y-2 bg-white p-3 rounded-xl border border-slate-200 shadow-xs">
              <div className="flex items-center justify-between text-xs font-bold text-slate-700 uppercase tracking-wide">
                <span className="flex items-center gap-2">
                  <Video className="w-3.5 h-3.5 text-blue-600" />
                  <span>Bước 1 · Nguồn đầu vào</span>
                </span>
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${
                  displayedSourceType === "csi" ? "bg-emerald-100 text-emerald-700" : "bg-blue-100 text-blue-700"
                }`}>
                  {displayedSourceType === "csi"
                    ? "Camera CSI"
                    : displayedSourceType === "file"
                      ? "File Video"
                      : "Nguồn đang chạy chưa rõ"}
                </span>
              </div>

              {/* Source Mode Selector */}
              <div className="grid grid-cols-2 p-1 bg-slate-100 rounded-xl gap-1">
                <button
                  type="button"
                  disabled={pipelineRunning || pendingPipelineAction !== null || isLoadingPreview || isLoadingVideos}
                  onClick={() => {
                    setSourceType("csi");
                    setSelectedVideo("csi");
                    setErrorMessage("");
                    resetSourcePreview("idle");
                  }}
                  className={`py-1.5 px-2 rounded-lg text-xs font-bold transition flex items-center justify-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed ${
                    displayedSourceType === "csi" ? "bg-white text-blue-700 shadow-xs" : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  <Camera className="w-3.5 h-3.5" />
                  <span>Camera CSI</span>
                </button>
                <button
                  type="button"
                  disabled={pipelineRunning || pendingPipelineAction !== null || isLoadingPreview || isLoadingVideos}
                  onClick={() => {
                    setSourceType("file");
                    setSelectedVideo("");
                    setErrorMessage("");
                    resetSourcePreview("selecting_video");
                  }}
                  className={`py-1.5 px-2 rounded-lg text-xs font-bold transition flex items-center justify-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed ${
                    displayedSourceType === "file" ? "bg-white text-blue-700 shadow-xs" : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  <Video className="w-3.5 h-3.5" />
                  <span>Video file</span>
                </button>
              </div>

              {pipelineRunning && !pipelineSourceType ? (
                <div className="p-2.5 rounded-xl bg-amber-50 border border-amber-200 text-[11px] text-amber-900">
                  Jetson báo pipeline đang chạy nhưng chưa có thông tin nguồn đầu vào.
                </div>
              ) : displayedSourceType === "csi" ? (
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
                    disabled={isLoadingVideos || isLoadingPreview || pipelineRunning || pendingPipelineAction !== null}
                    className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs font-bold shadow-xs transition"
                  >
                    {isLoadingVideos ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                    Tải danh sách video
                  </button>

                  {videos.length > 0 && (
                    <div className="relative">
                      <select
                        id="select-video"
                        disabled={pipelineRunning || pendingPipelineAction !== null || isLoadingPreview || isLoadingVideos}
                        className="w-full pl-3 pr-8 py-2 text-xs rounded-xl bg-white border border-slate-300 text-slate-800 appearance-none focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 shadow-xs font-medium"
                        value={selectedVideo}
                        onChange={(e) => {
                          setSelectedVideo(e.target.value);
                          setErrorMessage("");
                          resetSourcePreview("selecting_video");
                        }}
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

                {/* Hướng dẫn thứ tự 4 điểm P1-P4 khi vẽ Analysis ROI (Fix R2) */}
                {drawMode === "analysis" && (
                  <div className="p-2.5 rounded-xl bg-cyan-50 border border-cyan-200 text-[10px] space-y-1">
                    <div className="font-bold text-cyan-800 flex items-center gap-1">
                      <span>📐 Thứ tự 4 điểm hiệu chuẩn vận tốc (P1 - P4):</span>
                    </div>
                    <div className="space-y-0.5 text-slate-700">
                      <div className={roiConfig.analysisRoi.length === 0 ? "font-bold text-cyan-700 bg-cyan-100/60 px-1 py-0.5 rounded" : ""}>
                        • <b>P1 (Gần-Trái)</b>: Mép đường gần camera, bên trái
                      </div>
                      <div className={roiConfig.analysisRoi.length === 1 ? "font-bold text-cyan-700 bg-cyan-100/60 px-1 py-0.5 rounded" : ""}>
                        • <b>P2 (Gần-Phải)</b>: Mép đường gần camera, bên phải
                      </div>
                      <div className={roiConfig.analysisRoi.length === 2 ? "font-bold text-cyan-700 bg-cyan-100/60 px-1 py-0.5 rounded" : ""}>
                        • <b>P3 (Xa-Phải)</b>: Mép đường phía xa camera, bên phải
                      </div>
                      <div className={roiConfig.analysisRoi.length === 3 ? "font-bold text-cyan-700 bg-cyan-100/60 px-1 py-0.5 rounded" : ""}>
                        • <b>P4 (Xa-Trái)</b>: Mép đường phía xa camera, bên trái
                      </div>
                    </div>
                    <div className="text-[9px] text-cyan-900 font-semibold pt-0.5 border-t border-cyan-100">
                      {roiConfig.analysisRoi.length < 4
                        ? `👉 Hãy click để đặt điểm P${roiConfig.analysisRoi.length + 1}`
                        : "✅ Đã đủ 4 điểm hiệu chuẩn!"}
                    </div>
                  </div>
                )}

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

                {/* Ngữ cảnh đèn tín hiệu giao thông (V2 Dwell-Time) */}
                <div className="pt-2 border-t border-slate-100 space-y-1.5">
                  <label className="block text-[10px] font-bold text-slate-700 uppercase tracking-wide">
                    Ngữ cảnh đèn giao thông
                  </label>
                  <div className="grid grid-cols-2 gap-1.5">
                    <button
                      type="button"
                      onClick={() => setRoiConfig((prev) => ({ ...prev, trafficContext: "signalized" }))}
                      className={`p-2 rounded-xl text-left border transition cursor-pointer ${
                        roiConfig.trafficContext === "signalized"
                          ? "bg-blue-50 border-blue-500 text-blue-900 shadow-2xs"
                          : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      <div className="font-bold text-[11px] flex items-center gap-1">
                        <span>🚦 Có đèn tín hiệu</span>
                      </div>
                      <p className="text-[10px] text-slate-500 mt-0.5 leading-tight">
                        ROI có xe chờ đèn: cần đối chiếu chu kỳ đèn
                      </p>
                    </button>

                    <button
                      type="button"
                      onClick={() => setRoiConfig((prev) => ({ ...prev, trafficContext: "midblock" }))}
                      className={`p-2 rounded-xl text-left border transition cursor-pointer ${
                        roiConfig.trafficContext === "midblock"
                          ? "bg-blue-50 border-blue-500 text-blue-900 shadow-2xs"
                          : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      <div className="font-bold text-[11px] flex items-center gap-1">
                        <span>🛣️ Không có đèn</span>
                      </div>
                      <p className="text-[10px] text-slate-500 mt-0.5 leading-tight">
                        Đoạn giữa nút giao, hiệu chuẩn đúng kích thước
                      </p>
                    </button>
                  </div>
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
            {(isPipelineStage || pipelineRunning) && (
              <div className="space-y-2 bg-white p-3 rounded-xl border border-slate-200 shadow-xs">
                <div className="flex items-center gap-2 text-xs font-bold text-slate-700 uppercase tracking-wide">
                  <Play className="w-3.5 h-3.5 text-emerald-600" />
                  <span>Bước 4 · Pipeline</span>
                </div>
                {pipelineRunning && (
                  <div className="text-[11px] font-semibold text-slate-700">
                    Nguồn đang chạy: {pipelineSourceType === "csi" ? "Camera CSI" : pipelineSourceType === "file" ? `Video · ${pipelineSourceName || "không rõ tên"}` : "Chưa xác định"}
                  </div>
                )}
                {pendingPipelineAction && (
                  <div className="text-[11px] font-semibold text-amber-700">
                    {pendingPipelineAction === "start" ? "Đang chờ Jetson xác nhận lệnh chạy..." : "Đang chờ Jetson xác nhận lệnh dừng..."}
                  </div>
                )}

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
                    disabled={pipelineRunning || pendingPipelineAction !== null || (sourceType === "file" && !selectedVideo) || cooldownSeconds > 0}
                    className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 text-white text-xs font-bold shadow-xs transition"
                    title={sourceType === "csi" ? "Khởi động nhận diện CSI với ROI vừa cấu hình" : "Chạy video với ROI vừa cấu hình"}
                  >
                    <Play className="w-4 h-4 fill-current" />
                    <span>
                      {cooldownSeconds > 0
                        ? `⏳ Nhả phần cứng (${cooldownSeconds}s)`
                        : sourceType === "csi"
                          ? "🚀 Chạy nhận diện CSI"
                          : "Chạy Video"}
                    </span>
                  </button>

                  <button
                    id="btn-stop-pipeline"
                    onClick={handleStopPipeline}
                    disabled={!pipelineRunning || pendingPipelineAction !== null || cooldownSeconds > 0}
                    className="w-24 flex items-center justify-center gap-1.5 py-2.5 rounded-xl bg-red-600 hover:bg-red-700 disabled:opacity-40 text-white text-xs font-bold shadow-xs transition"
                  >
                    <Square className="w-4 h-4 fill-current" />
                    <span>{cooldownSeconds > 0 ? "..." : "Dừng"}</span>
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

          {/* Right Panel: Canvas & Live Stream */}
          <div className="flex-1 flex flex-col bg-slate-950 relative overflow-hidden select-none">
            {pipelineRunning && pipelineSourceType === "csi" && (
              <div className="flex items-center justify-between px-4 py-2 bg-slate-900/90 border-b border-slate-800 shrink-0 z-10">
                <div className="flex items-center gap-1.5 p-0.5 bg-slate-800/80 rounded-lg border border-slate-700/60">
                  <button
                    type="button"
                    onClick={() => setActiveTab("stream")}
                    className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-semibold transition ${
                      activeTab === "stream"
                        ? "bg-indigo-600 text-white shadow-xs"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                    <span>🎥 Live Stream Trực Tiếp</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab("roi")}
                    className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-semibold transition ${
                      activeTab === "roi"
                        ? "bg-slate-700 text-white shadow-xs"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <span>📐 Vùng ROI Đã Cấu Hình</span>
                  </button>
                </div>
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded text-[11px] bg-indigo-500/10 text-indigo-300 border border-indigo-500/30 font-medium">
                    📷 Camera CSI
                  </span>
                  <div className="text-[11px] text-slate-400 font-medium hidden sm:block">
                    {activeTab === "stream" ? "Luồng trực tiếp MediaMTX" : "Khung hình cố định & Tọa độ"}
                  </div>
                </div>
              </div>
            )}

            <div className="flex-1 flex items-center justify-center relative overflow-hidden">
              {previewImage ? (
                <div className="relative w-full h-full flex items-center justify-center p-3">
                  {isSynthetic && (
                    <div className="absolute top-4 left-4 right-4 z-20 flex items-center gap-2 p-3 rounded-xl bg-amber-500/95 border border-amber-400 text-amber-950 font-bold text-xs shadow-lg backdrop-blur-md">
                      <AlertTriangle className="w-5 h-5 shrink-0 text-amber-950 animate-bounce" />
                      <span>⚠️ CẢNH BÁO: Khung hình mô phỏng (Synthetic Canvas). Camera phần cứng đang bị ngắt kết nối hoặc không phản hồi! Vui lòng kiểm tra camera trước khi vẽ ROI thực tế.</span>
                    </div>
                  )}
                  <img ref={imgRef} src={previewImage} onLoad={renderCanvas} className="hidden" alt="" />
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
              ) : activeTab === "stream" && pipelineRunning && pipelineSourceType === "csi" && pendingPipelineAction !== "stop" ? (
                <div className="relative w-full h-full flex flex-col items-center justify-center p-3">
                  <MediaMTXPlayer edgeId={edgeId} className="w-full h-full" />
                </div>
              ) : (
                <div className="text-center text-slate-500 space-y-3 p-8">
                  <Camera className="w-16 h-16 mx-auto text-slate-600 stroke-[1.2]" />
                  <p className="text-sm font-semibold text-slate-300">Chưa có khung hình</p>
                  <p className="text-xs text-slate-400">Chọn video hoặc Camera CSI ở cột bên trái và bấm "Lấy khung hình"</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
