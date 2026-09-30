import React from "react";
import ReactECharts from "echarts-for-react";
import { X, Gauge, Car, AlertTriangle, Cpu, History, Radio, Ruler, Terminal, Camera } from "lucide-react";
import type { NodeDetail } from "../../types/gis";
import { API_HOST_URL } from "../../services/api";

interface NodeDashboardDrawerProps {
  node: NodeDetail | null;
  onClose: () => void;
  onOpenHealth: () => void;
  onOpenHistoryForSegment: (segmentId: string) => void;
  onOpenRemote?: () => void;
  onOpenCamera?: () => void;
}

export const NodeDashboardDrawer: React.FC<NodeDashboardDrawerProps> = ({
  node,
  onClose,
  onOpenHealth,
  onOpenHistoryForSegment,
  onOpenRemote,
  onOpenCamera
}) => {
  if (!node) return null;

  const counts = node.counts_by_class || {};
  // Hỗ trợ cả hai định dạng: 'motorcycle' (chuẩn WebGIS) và 'motorbike' (raw YOLO/Jetson COCO label)
  const motoCount = (counts.motorcycle ?? counts.motorbike ?? 0);
  const carCount = counts.car ?? 0;
  const busCount = counts.bus ?? 0;
  const truckCount = counts.truck ?? 0;
  const bicycleCount = counts.bicycle ?? 0;
  const totalVehicles = motoCount + carCount + busCount + truckCount + bicycleCount;

  // ECharts Donut Option for Vehicle Classification
  const donutData = [
    { value: motoCount, name: "Xe máy" },
    { value: carCount, name: "Ô tô con" },
    { value: busCount, name: "Xe buýt" },
    { value: truckCount, name: "Xe tải" },
    ...(bicycleCount > 0 ? [{ value: bicycleCount, name: "Xe đạp" }] : []),
  ].filter(d => d.value > 0);

  // Hiển thị placeholder nếu chưa có dữ liệu
  const hasData = totalVehicles > 0;

  // ECharts Donut Option for Vehicle Classification
  const donutOption = {
    tooltip: {
      trigger: "item",
      backgroundColor: "rgba(255, 255, 255, 0.96)",
      borderColor: "#e2e8f0",
      borderWidth: 1,
      textStyle: { color: "#1e293b", fontSize: 12 },
      formatter: "{b}: {c} xe ({d}%)"
    },
    legend: {
      bottom: "0%",
      left: "center",
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: "#475569", fontSize: 11 }
    },
    color: ["#3b82f6", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6"],
    series: [
      {
        name: "Phương tiện",
        type: "pie",
        radius: ["42%", "72%"],
        center: ["50%", "45%"],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 6,
          borderColor: "#ffffff",
          borderWidth: 2
        },
        label: { show: false },
        emphasis: {
          label: {
            show: true,
            fontSize: 12,
            fontWeight: "bold",
            color: "#0f172a"
          }
        },
        data: hasData ? donutData : [
          { value: 1, name: "Chưa có dữ liệu", itemStyle: { color: "#e2e8f0" } }
        ]
      }
    ]
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "CONGESTED":
        return <span className="px-2.5 py-1 text-xs font-bold rounded-full bg-red-100 text-red-700 border border-red-300">ÙN TẮC</span>;
      case "SLOW":
        return <span className="px-2.5 py-1 text-xs font-bold rounded-full bg-amber-100 text-amber-700 border border-amber-300">ĐÔNG XE</span>;
      default:
        return <span className="px-2.5 py-1 text-xs font-bold rounded-full bg-emerald-100 text-emerald-700 border border-emerald-300">THÔNG THOÁNG</span>;
    }
  };

  return (
    <div className="absolute top-20 right-3 bottom-5 w-96 z-20 flex flex-col rounded-2xl glass-panel text-slate-800 shadow-2xl border border-slate-200 animate-in slide-in-from-right duration-300 overflow-hidden">
      {/* Drawer Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-200 bg-slate-50/80">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-ping"></span>
            <span className="text-xs font-mono text-blue-600 font-bold">{node.edge_id}</span>
            {getStatusBadge(node.traffic_status)}
          </div>
          <h2 className="text-sm font-bold text-slate-900 line-clamp-1">{node.name}</h2>
          <p className="text-xs text-slate-500 font-medium">{node.road_name || "Tuyến đường chính"}</p>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Drawer Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3.5">
        {/* Metric Cards Grid */}
        <div className="grid grid-cols-2 gap-2.5">
          <div className="p-3 rounded-xl bg-slate-50/90 border border-slate-200 flex flex-col justify-between shadow-sm">
            <div className="flex items-center justify-between text-xs text-slate-500 font-medium mb-1">
              <span>Vận tốc dòng xe</span>
              <Gauge className="w-4 h-4 text-blue-600" />
            </div>
            <div className="flex items-baseline gap-1">
              <span className="text-2xl font-black text-blue-700">{node.avg_speed_kmh}</span>
              <span className="text-xs text-slate-500">km/h</span>
            </div>
            <div className="w-full bg-slate-200 h-1.5 rounded-full mt-2 overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-red-500 via-amber-400 to-emerald-500 rounded-full"
                style={{ width: `${Math.min(100, (node.avg_speed_kmh / 60) * 100)}%` }}
              />
            </div>
          </div>

          <div className="p-3 rounded-xl bg-slate-50/90 border border-slate-200 flex flex-col justify-between shadow-sm">
            <div className="flex items-center justify-between text-xs text-slate-500 font-medium mb-1">
              <span>Điểm kẹt xe</span>
              <AlertTriangle className="w-4 h-4 text-amber-600" />
            </div>
            <div className="flex items-baseline gap-1">
              <span className={`text-2xl font-black ${node.congestion_score >= 65 ? "text-red-600" : "text-amber-600"}`}>
                {node.congestion_score}
              </span>
              <span className="text-xs text-slate-500">/ 100</span>
            </div>
            <div className="text-[11px] text-slate-500 mt-2">
              Dừng đỗ: <strong className="text-slate-800">{node.stopped_vehicle_count || 0} xe</strong>
            </div>
          </div>

          <div className="p-3 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm">
            <div className="flex items-center justify-between text-xs text-slate-500 font-medium mb-1">
              <span>Lượng xe trong ROI</span>
              <Car className="w-4 h-4 text-indigo-600" />
            </div>
            <div className="text-2xl font-black text-indigo-700">{node.vehicle_count || 0}</div>
            <div className="text-[11px] text-slate-500 mt-1">
              Mật độ: {node.density_veh_per_km_lane || 0} xe/km/làn
            </div>
          </div>

          <div className="p-3 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm">
            <div className="flex items-center justify-between text-xs text-slate-500 font-medium mb-1">
              <span>Góc nhìn Camera</span>
              <Radio className="w-4 h-4 text-cyan-600" />
            </div>
            <div className="text-2xl font-black text-cyan-700">{node.heading || 0}°</div>
            <div className="text-[11px] text-slate-500 mt-1">Góc mở FOV: {node.fov || 65}°</div>
          </div>
        </div>

        {/* Physical Road Dimensions Card */}
        <div className="p-3.5 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm">
          <div className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-2.5 flex items-center justify-between">
            <span className="flex items-center gap-1.5">
              <Ruler className="w-4 h-4 text-emerald-600" />
              Thông số Tuyến đường Thực tế
            </span>
            <div className="flex items-center gap-1">
              {node.osm_road_name && (
                <span className="text-[10px] font-medium text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 flex items-center gap-0.5">
                  🗺️ OSM
                </span>
              )}
              <span className="text-[11px] font-mono font-bold text-slate-500 bg-white px-2 py-0.5 rounded border border-slate-200">
                {node.segment_id || "segment-001"}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="p-2.5 rounded-lg bg-white border border-slate-200">
              <span className="text-slate-500 block text-[11px] mb-0.5">Chiều dài thực tế</span>
              <span className="text-sm font-bold font-mono text-emerald-700">{node.road_length_m || 450.0} m</span>
            </div>
            <div className="p-2.5 rounded-lg bg-white border border-slate-200">
              <span className="text-slate-500 block text-[11px] mb-0.5">Chiều rộng mặt đường</span>
              <span className="text-sm font-bold font-mono text-blue-700">{node.road_width_m || 16.0} m</span>
            </div>
            <div className="p-2.5 rounded-lg bg-white border border-slate-200">
              <span className="text-slate-500 block text-[11px] mb-0.5">Quy mô mặt cắt</span>
              <span className="text-sm font-bold text-slate-800">{node.lane_count || 4} làn xe</span>
            </div>
            <div className="p-2.5 rounded-lg bg-white border border-slate-200">
              <span className="text-slate-500 block text-[11px] mb-0.5">Tốc độ thiết kế</span>
              <span className="text-sm font-bold font-mono text-slate-800">{(node as any).speed_limit_kmh || 60} km/h</span>
            </div>
          </div>
        </div>

        {/* Vehicle Classification Donut Chart */}
        <div className="p-3 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm">
          <div className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-1 flex items-center justify-between">
            <span>Cơ cấu phương tiện</span>
            <span className="text-xs text-slate-500 font-normal">
              {hasData ? `Tổng: ${totalVehicles} xe` : "⏳ Chờ dữ liệu Jetson..."}
            </span>
          </div>
          {hasData ? (
            <>
              {/* Chi tiết từng loại phương tiện */}
              <div className="grid grid-cols-2 gap-1.5 mb-2 text-[11px]">
                {donutData.map((item, idx) => {
                  const colors = ["text-blue-600 bg-blue-50 border-blue-200", "text-emerald-600 bg-emerald-50 border-emerald-200", "text-amber-600 bg-amber-50 border-amber-200", "text-pink-600 bg-pink-50 border-pink-200", "text-violet-600 bg-violet-50 border-violet-200"];
                  return (
                    <div key={item.name} className={`flex justify-between px-2 py-1 rounded-lg border ${colors[idx % colors.length]}`}>
                      <span className="font-medium">{item.name}</span>
                      <span className="font-bold font-mono">{item.value} xe</span>
                    </div>
                  );
                })}
              </div>
              <div className="h-36 w-full">
                <ReactECharts option={donutOption} style={{ height: "100%", width: "100%" }} />
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-24 text-slate-400 gap-1">
              <span className="text-2xl">📹</span>
              <span className="text-[11px] text-center">Chưa nhận dữ liệu từ Jetson.<br/>Đảm bảo Jetson đang chạy và kết nối MQTT.</span>
            </div>
          )}
        </div>

        {/* Latest AI Camera Snapshot Card */}
        {(() => {
          const rawUrl = node.snapshot_url;
          const displayUrl = rawUrl
            ? (rawUrl.startsWith("http") ? rawUrl : `${API_HOST_URL}${rawUrl.startsWith("/") ? "" : "/"}${rawUrl}`)
            : "";

          return (
            <div className="p-3 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm">
              <div className="flex items-center justify-between text-xs font-bold text-slate-700 uppercase tracking-wider mb-2">
                <span className="flex items-center gap-1.5">
                  <Camera className="w-3.5 h-3.5 text-blue-600" />
                  Khung hình Camera AI
                </span>
                <span className="text-[10px] text-emerald-700 font-semibold flex items-center gap-1 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                  LIVE SNAPSHOT
                </span>
              </div>
              <div
                onClick={onOpenCamera}
                className="relative rounded-lg overflow-hidden border border-slate-200 bg-slate-900 group shadow-sm cursor-pointer hover:border-emerald-500 transition aspect-video flex items-center justify-center"
                title="Bấm để mở Modal Xem Cam & Chụp ảnh tức thì"
              >
                {displayUrl ? (
                  <img
                    src={displayUrl}
                    alt="AI Camera Snapshot"
                    className="w-full h-full object-cover transition duration-300 group-hover:scale-105"
                  />
                ) : (
                  <div className="flex flex-col items-center justify-center text-slate-400 gap-1.5 p-4 text-center">
                    <Camera className="w-8 h-8 text-slate-500 group-hover:text-emerald-400 transition" />
                    <span className="text-xs text-slate-300 font-medium">Chưa có ảnh chụp</span>
                    <span className="text-[10px] text-emerald-400 underline font-semibold">Nhấp để mở Cam & Chụp ngay</span>
                  </div>
                )}
                <div className="absolute inset-0 bg-gradient-to-t from-slate-950/70 via-transparent to-transparent flex items-end justify-between p-2 pointer-events-none">
                  <span className="text-[11px] font-mono text-white font-medium">
                    {node.last_seen ? new Date(node.last_seen).toLocaleTimeString() : "Live Snapshot"}
                  </span>
                  <span className="text-[10px] bg-emerald-600 text-white font-bold px-2 py-0.5 rounded shadow">
                    Xem & Chụp
                  </span>
                </div>
              </div>
            </div>
          );
        })()}
      </div>

      {/* Drawer Action Footer */}
      <div className="p-3 bg-slate-50/90 border-t border-slate-200 flex flex-col gap-2">
        {onOpenCamera && (
          <button
            onClick={onOpenCamera}
            className="w-full flex items-center justify-center space-x-2 py-2.5 px-3 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 text-white text-xs font-bold transition shadow-md shadow-emerald-500/25"
          >
            <Camera className="w-4 h-4" />
            <span>📸 Xem Cam & Chụp ảnh theo yêu cầu</span>
          </button>
        )}

        {onOpenRemote && (
          <button
            onClick={onOpenRemote}
            className="w-full flex items-center justify-center space-x-2 py-2 px-3 rounded-xl bg-slate-800 hover:bg-slate-900 text-white text-xs font-bold transition shadow-sm"
          >
            <Terminal className="w-3.5 h-3.5 text-blue-400" />
            <span>Điều khiển từ xa & Cấu hình ROI Jetson</span>
          </button>
        )}
        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={onOpenHealth}
            className="flex items-center justify-center space-x-1.5 py-2 px-3 rounded-xl bg-blue-50 hover:bg-blue-100 border border-blue-200 text-blue-700 text-xs font-bold transition shadow-sm"
          >
            <Cpu className="w-3.5 h-3.5 text-blue-600" />
            <span>Phần cứng</span>
          </button>

          <button
            onClick={() => onOpenHistoryForSegment(node.segment_id || "segment-001")}
            className="flex items-center justify-center space-x-1.5 py-2 px-3 rounded-xl bg-indigo-50 hover:bg-indigo-100 border border-indigo-300 text-indigo-700 text-xs font-bold transition shadow-sm"
          >
            <History className="w-3.5 h-3.5 text-indigo-600" />
            <span>Lịch sử kẹt xe</span>
          </button>
        </div>
      </div>
    </div>
  );
};
