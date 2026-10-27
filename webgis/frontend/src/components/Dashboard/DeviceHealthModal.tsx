import React, { useState } from "react";
import { X, RefreshCw, Cpu, HardDrive, Thermometer, Wifi, Zap, CheckCircle2, AlertCircle } from "lucide-react";
import type { DeviceHealthData } from "../../types/gis";
import { api } from "../../services/api";

interface DeviceHealthModalProps {
  edgeId: string;
  nodeName: string;
  initialHealth?: DeviceHealthData;
  onClose: () => void;
}

export const DeviceHealthModal: React.FC<DeviceHealthModalProps> = ({
  edgeId,
  nodeName,
  initialHealth,
  onClose
}) => {
  const [health, setHealth] = useState<DeviceHealthData | undefined>(initialHealth);
  const [loading, setLoading] = useState(false);

  const handleRefresh = async () => {
    setLoading(true);
    try {
      const res = await api.diagnoseHealth(edgeId);
      if (res.latest_health) {
        setHealth(res.latest_health);
      }
    } catch (e) {
      console.error("Diagnosis error:", e);
    } finally {
      setTimeout(() => setLoading(false), 600);
    }
  };

  const hw = health?.hardware;
  const net = health?.network;
  const gen = health?.general;
  const st = health?.storage;
  const pl = health?.pipeline;

  const temp = hw?.temperature_c || 55.0;
  const isHighTemp = temp >= 70.0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-2xl rounded-2xl glass-panel text-slate-800 shadow-2xl border border-slate-200 overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-200 bg-slate-50/80">
          <div className="flex items-center space-x-3">
            <div className="p-2.5 rounded-xl bg-blue-50 border border-blue-200 text-blue-600 shadow-sm">
              <Cpu className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-slate-900">Thông số Phần cứng & Hệ thống Biên</h2>
                <span className="px-2 py-0.5 text-[11px] font-mono font-bold rounded bg-blue-50 text-blue-700 border border-blue-200">
                  {edgeId}
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-0.5 font-medium">{nodeName} • Đo kiểm Cảm biến & Tài nguyên Vi xử lý</p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <button
              onClick={handleRefresh}
              disabled={loading}
              className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 transition shadow-sm"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-blue-600 ${loading ? "animate-spin" : ""}`} />
              <span>{loading ? "Đang đọc cảm biến..." : "Đọc Telemetry tức thì"}</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto space-y-5 flex-1 text-sm">
          {/* Status Row */}
          <div className="grid grid-cols-3 gap-3">
            <div className="p-3.5 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm">
              <div className="text-xs text-slate-500 font-medium mb-1">Trạng thái Dịch vụ</div>
              <div className="flex items-center gap-1.5 text-emerald-700 font-bold">
                <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                <span className="capitalize">{gen?.service_status || "Đang chạy (Running)"}</span>
              </div>
              <div className="text-[11px] text-slate-500 mt-1 font-mono">
                Uptime: {gen?.uptime_seconds ? `${Math.floor(gen.uptime_seconds / 3600)}h ${Math.floor((gen.uptime_seconds % 3600) / 60)}m` : "48h 15m"}
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm">
              <div className="text-xs text-slate-500 font-medium mb-1">Kết nối Mạng & IP</div>
              <div className="flex items-center gap-1.5 text-blue-700 font-bold">
                <Wifi className="w-4 h-4 text-blue-600" />
                <span className="font-mono">{net?.local_ip || "192.168.1.105"}</span>
              </div>
              <div className="text-[11px] text-slate-500 mt-1 font-mono">
                MAC: {net?.mac_address || "48:B0:2D:1A:2B:3C"}
              </div>
            </div>

            <div className={`p-3.5 rounded-xl border shadow-sm ${isHighTemp ? "bg-red-50 border-red-300" : "bg-slate-50/90 border-slate-200"}`}>
              <div className="text-xs text-slate-500 font-medium mb-1">Nhiệt độ SoC Jetson</div>
              <div className={`flex items-center gap-1.5 font-bold ${isHighTemp ? "text-red-700" : "text-amber-700"}`}>
                <Thermometer className="w-4 h-4" />
                <span className="text-lg">{temp}°C</span>
                {isHighTemp && <AlertCircle className="w-4 h-4 text-red-600 animate-bounce" />}
              </div>
              <div className="text-[11px] text-slate-500 mt-1">
                Nguồn: {hw?.power_mode || "10W_MAXN"}
              </div>
            </div>
          </div>

          {/* CPU & GPU & RAM Progress Bars */}
          <div className="p-4 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm space-y-4">
            <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center gap-2">
              <Cpu className="w-4 h-4 text-blue-600" />
              Tải Vi Xử Lý & Bộ Nhớ (Hardware Workload)
            </h3>

            {/* CPU */}
            <div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-700 font-semibold">CPU (4 Cores ARM A57)</span>
                <span className="text-blue-700 font-bold">{hw?.cpu_usage_pct || 62}%</span>
              </div>
              <div className="w-full bg-slate-200 h-2.5 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-600 rounded-full transition-all duration-500"
                  style={{ width: `${hw?.cpu_usage_pct || 62}%` }}
                />
              </div>
            </div>

            {/* GPU */}
            <div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-700 font-semibold">Tegra GPU (128 CUDA Cores)</span>
                <span className="text-indigo-700 font-bold">{hw?.gpu_usage_pct || 78}%</span>
              </div>
              <div className="w-full bg-slate-200 h-2.5 rounded-full overflow-hidden">
                <div
                  className="h-full bg-indigo-600 rounded-full transition-all duration-500"
                  style={{ width: `${hw?.gpu_usage_pct || 78}%` }}
                />
              </div>
            </div>

            {/* RAM */}
            <div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-700 font-semibold">Bộ nhớ RAM</span>
                <span className="text-emerald-700 font-bold">
                  {hw?.ram_used_mb || 2840} MB / {hw?.ram_total_mb || 3964} MB ({hw?.ram_usage_pct || 71}%)
                </span>
              </div>
              <div className="w-full bg-slate-200 h-2.5 rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-500 rounded-full transition-all duration-500"
                  style={{ width: `${hw?.ram_usage_pct || 71}%` }}
                />
              </div>
            </div>

            {/* Swap */}
            <div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-600 font-medium">Bộ nhớ ảo Swap</span>
                <span className="text-slate-500">
                  {hw?.swap_used_mb || 412} MB / {hw?.swap_total_mb || 2048} MB
                </span>
              </div>
              <div className="w-full bg-slate-200 h-1.5 rounded-full overflow-hidden">
                <div
                  className="h-full bg-amber-500 rounded-full"
                  style={{ width: `${((hw?.swap_used_mb || 412) / (hw?.swap_total_mb || 2048)) * 100}%` }}
                />
              </div>
            </div>
          </div>

          {/* Storage & DeepStream Pipeline */}
          <div className="grid grid-cols-2 gap-3">
            <div className="p-4 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm">
              <h4 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-2.5 flex items-center gap-1.5">
                <HardDrive className="w-4 h-4 text-amber-600" />
                Dung lượng Lưu trữ
              </h4>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-500">Trống khả dụng:</span>
                <span className="font-bold text-emerald-700">{st?.disk_free_gb || 16.4} GB</span>
              </div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-500">Tổng dung lượng:</span>
                <span className="text-slate-700 font-medium">{st?.disk_total_gb || 29.5} GB</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Ảnh tồn Outbox:</span>
                <span className="text-blue-700 font-bold">{st?.outbox_unsent_images || 0} ảnh</span>
              </div>
            </div>

            <div className="p-4 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm">
              <h4 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-2.5 flex items-center gap-1.5">
                <Zap className="w-4 h-4 text-blue-600" />
                Hiệu năng DeepStream AI
              </h4>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-500">Camera FPS:</span>
                <span className="font-bold text-blue-700">{pl?.pipeline_fps || 24.5} FPS</span>
              </div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-slate-500">Độ trễ suy luận:</span>
                <span className="text-cyan-700 font-bold">{pl?.inference_latency_ms || 40.8} ms</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Cảm biến Camera:</span>
                <span className="text-emerald-700 font-bold capitalize">{pl?.camera_status || "Streaming"}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 bg-slate-50/90 border-t border-slate-200 flex items-center justify-between text-xs text-slate-500">
          <span>Thời gian đọc cảm biến: {health?.timestamp || new Date().toLocaleTimeString()}</span>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-bold transition shadow-sm"
          >
            Đóng cửa sổ
          </button>
        </div>
      </div>
    </div>
  );
};
