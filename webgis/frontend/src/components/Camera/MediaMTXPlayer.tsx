import React, { useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import {
  startMediaMTXLive,
  sendMediaMTXKeepAlive,
  type MediaMTXStreamInfo,
} from "../../services/liveStream";
import { RefreshCw, AlertTriangle, Video, Zap } from "lucide-react";

interface MediaMTXPlayerProps {
  edgeId: string;
  className?: string;
  onLiveStarted?: (info: MediaMTXStreamInfo) => void;
}

export const MediaMTXPlayer: React.FC<MediaMTXPlayerProps> = ({
  edgeId,
  className = "",
  onLiveStarted,
}) => {
  const [streamInfo, setStreamInfo] = useState<MediaMTXStreamInfo | null>(null);
  const [status, setStatus] = useState<"connecting" | "live" | "error" | "offline">("connecting");
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [mode, setMode] = useState<"webrtc" | "hls">("webrtc");
  const [isMixedContent, setIsMixedContent] = useState<boolean>(false);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const hlsRef = useRef<Hls | null>(null);
  const keepAliveTimerRef = useRef<number | null>(null);

  // 1. Kiểm tra Mixed Content (HTTPS trang chủ vs HTTP MediaMTX)
  useEffect(() => {
    if (typeof window !== "undefined" && window.location.protocol === "https:") {
      setIsMixedContent(true);
    }
  }, []);

  // 2. Vòng đời On-Demand: Kích hoạt luồng, duy trì keep-alive, tự đóng khi unmount
  useEffect(() => {
    let isCancelled = false;

    async function initLive() {
      setStatus("connecting");
      setErrorMessage("");

      try {
        const info = await startMediaMTXLive(edgeId);
        if (isCancelled) return;

        setStreamInfo(info);
        setStatus("live");
        onLiveStarted?.(info);

        // Bật interval ping keep-alive mỗi 20 giây
        keepAliveTimerRef.current = window.setInterval(() => {
          sendMediaMTXKeepAlive(edgeId);
        }, 20000);
      } catch (err: any) {
        if (isCancelled) return;
        setStatus("error");
        const msg = err.response?.data?.detail || err.message || "Không thể kết nối đến camera Jetson";
        setErrorMessage(msg);
      }
    }

    initLive();

    return () => {
      isCancelled = true;
      if (keepAliveTimerRef.current !== null) {
        window.clearInterval(keepAliveTimerRef.current);
        keepAliveTimerRef.current = null;
      }

      // Giải phóng Hls instance
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
    };
  }, [edgeId]);

  // 3. Xử lý HLS Player khi ở chế độ 'hls'
  useEffect(() => {
    if (mode !== "hls" || !streamInfo?.hls_url || !videoRef.current) {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
      return;
    }

    const video = videoRef.current;

    if (Hls.isSupported()) {
      const hls = new Hls({
        lowLatencyMode: true,
        liveSyncDurationCount: 3,
        liveMaxLatencyDurationCount: 5,
        enableWorker: true,
      });
      hls.loadSource(streamInfo.hls_url);
      hls.attachMedia(video);

      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(() => {});
      });

      hls.on(Hls.Events.ERROR, (_, data) => {
        if (data.fatal) {
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              hls.startLoad();
              break;
            case Hls.ErrorTypes.MEDIA_ERROR:
              hls.recoverMediaError();
              break;
            default:
              hls.destroy();
              break;
          }
        }
      });

      hlsRef.current = hls;
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      // Hỗ trợ Safari native HLS
      video.src = streamInfo.hls_url;
      video.play().catch(() => {});
    }

    return () => {
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
    };
  }, [mode, streamInfo?.hls_url]);

  return (
    <div className={`relative bg-slate-950 rounded-lg overflow-hidden flex flex-col ${className}`}>
      {/* Control Bar Header */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-slate-900 border-b border-slate-800 text-xs">
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full ${
              status === "live" ? "bg-emerald-500 animate-pulse" : "bg-amber-500"
            }`}
          />
          <span className="font-semibold text-slate-200">
            {status === "live" ? "TRỰC TIẾP ON-DEMAND" : "ĐANG KẾT NỐI..."}
          </span>
          <span className="text-slate-400 font-mono text-[11px]">({edgeId})</span>
        </div>

        {/* Toggle Mode WebRTC vs HLS */}
        <div className="flex items-center bg-slate-800 rounded p-0.5 border border-slate-700">
          <button
            type="button"
            onClick={() => setMode("webrtc")}
            className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors flex items-center gap-1 ${
              mode === "webrtc"
                ? "bg-indigo-600 text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
            title="Độ trễ siêu thấp (< 500ms) qua WebRTC"
          >
            <Zap className="w-3 h-3" />
            WebRTC
          </button>
          <button
            type="button"
            onClick={() => setMode("hls")}
            className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors flex items-center gap-1 ${
              mode === "hls"
                ? "bg-indigo-600 text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
            title="Độ trễ 1-2s qua LL-HLS (Chống chặn UDP)"
          >
            <Video className="w-3 h-3" />
            LL-HLS
          </button>
        </div>
      </div>

      {/* Cảnh báo Mixed Content */}
      {isMixedContent && (
        <div className="bg-amber-950/80 border-b border-amber-800/60 px-3 py-1 text-[11px] text-amber-300 flex items-center gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 text-amber-400" />
          <span>
            Trang Web chạy HTTPS nhưng luồng MediaMTX là HTTP. Nếu video không hiện, vui lòng bấm biểu tượng ổ khóa trình duyệt và cho phép "Insecure Content".
          </span>
        </div>
      )}

      {/* Media Container */}
      <div className="relative w-full aspect-video bg-black flex items-center justify-center overflow-hidden">
        {status === "connecting" && (
          <div className="flex flex-col items-center gap-2 text-slate-400 p-4 text-center">
            <RefreshCw className="w-6 h-6 animate-spin text-indigo-400" />
            <p className="text-xs font-medium">Đang phát lệnh khởi động camera CSI trên Jetson...</p>
            <span className="text-[11px] text-slate-500">Mở van GStreamer & kích hoạt H.264 phần cứng</span>
          </div>
        )}

        {status === "error" && (
          <div className="flex flex-col items-center gap-2 text-rose-400 p-4 text-center">
            <AlertTriangle className="w-6 h-6 text-rose-500" />
            <p className="text-xs font-semibold">Không thể xem trực tiếp</p>
            <span className="text-[11px] text-slate-400 max-w-sm">{errorMessage}</span>
          </div>
        )}

        {status === "live" && streamInfo && (
          <>
            {mode === "webrtc" ? (
              <iframe
                src={streamInfo.webrtc_url}
                className="w-full h-full border-0 pointer-events-auto"
                allow="autoplay; fullscreen"
                title={`WebRTC Stream ${edgeId}`}
              />
            ) : (
              <video
                ref={videoRef}
                className="w-full h-full object-contain"
                controls
                autoPlay
                playsInline
                muted
              />
            )}
          </>
        )}
      </div>

      {/* Footer Meta */}
      <div className="px-3 py-1 bg-slate-900 border-t border-slate-800 text-[10px] text-slate-500 flex justify-between items-center">
        <span>GStreamer NVENC Baseline • On-Demand (Tự ngắt khi đóng)</span>
        <span className="font-mono text-slate-400">MediaMTX {mode.toUpperCase()}</span>
      </div>
    </div>
  );
};
