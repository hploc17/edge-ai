import React, { useEffect, useRef, useState, useCallback } from "react";
import Hls from "hls.js";
import {
  startMediaMTXLive,
  stopMediaMTXLive,
  getMediaMTXLiveInfo,
  sendMediaMTXKeepAlive,
  type MediaMTXStreamInfo,
} from "../../services/liveStream";
import { RefreshCw, AlertTriangle, Video, Zap, RotateCcw } from "lucide-react";

interface MediaMTXPlayerProps {
  edgeId: string;
  className?: string;
  onLiveStarted?: (info: MediaMTXStreamInfo) => void;
}

/**
 * Tự động chuẩn hóa địa chỉ máy chủ stream sang hostname trình duyệt đang truy cập.
 * Giúp người dùng dù truy cập qua localhost, IP mạng LAN hay tên miền đều kết nối đúng cổng MediaMTX.
 */
function normalizeStreamUrls(info: MediaMTXStreamInfo): MediaMTXStreamInfo {
  if (typeof window === "undefined") return info;
  const currentHost = window.location.hostname;
  if (!currentHost) return info;

  const replaceHost = (urlStr: string) => {
    if (!urlStr) return urlStr;
    try {
      const u = new URL(urlStr);
      // Giữ nguyên cổng (8889, 8888, 8554) nhưng đồng bộ hostname với trình duyệt
      u.hostname = currentHost;
      return u.toString();
    } catch {
      return urlStr;
    }
  };

  return {
    ...info,
    webrtc_url: replaceHost(info.webrtc_url),
    whep_url: replaceHost(info.whep_url),
    hls_url: replaceHost(info.hls_url),
  };
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
  const [retryCount, setRetryCount] = useState<number>(0);

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

      let info: MediaMTXStreamInfo | null = null;

      try {
        // Thử phát lệnh bật luồng camera
        info = await startMediaMTXLive(edgeId);
      } catch (err: any) {
        // Fallback: nếu lệnh start bị 401 hoặc lỗi, thử đọc thông tin luồng có sẵn
        try {
          info = await getMediaMTXLiveInfo(edgeId);
        } catch (readErr) {
          // Fallback cuối: tự tạo URL stream MediaMTX theo hostname hiện tại
          const currentHost = (typeof window !== "undefined" && window.location.hostname) || "localhost";
          info = {
            edge_id: edgeId,
            status: "ready",
            webrtc_url: `http://${currentHost}:8889/live/${edgeId}/`,
            whep_url: `http://${currentHost}:8889/live/${edgeId}/whep`,
            hls_url: `http://${currentHost}:8888/live/${edgeId}/index.m3u8`,
            rtsp_url: `rtsp://${currentHost}:8554/live/${edgeId}`,
          };
        }
      }

      if (isCancelled) return;

      if (info) {
        const normalized = normalizeStreamUrls(info);
        setStreamInfo(normalized);
        setStatus("live");
        onLiveStarted?.(normalized);

        // Bật interval ping keep-alive mỗi 20 giây
        if (keepAliveTimerRef.current !== null) {
          window.clearInterval(keepAliveTimerRef.current);
        }
        keepAliveTimerRef.current = window.setInterval(() => {
          sendMediaMTXKeepAlive(edgeId);
        }, 20000);
      } else {
        setStatus("error");
        setErrorMessage("Không thể kết nối đến camera Jetson.");
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

      // Unmount là tín hiệu đóng phiên on-demand; không để keep-alive hoặc
      // phiên live cũ tiếp tục giữ quyền mở luồng sau khi người dùng dừng.
      void stopMediaMTXLive(edgeId);
    };
  }, [edgeId, retryCount]);

  const handleRetry = useCallback(() => {
    setRetryCount((prev) => prev + 1);
  }, []);

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
            <button
              type="button"
              onClick={handleRetry}
              className="mt-2 inline-flex items-center gap-1.5 px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs font-medium border border-slate-700 transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Thử lại</span>
            </button>
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
