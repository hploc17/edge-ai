import React from "react";
import ReactECharts from "echarts-for-react";
import { X, Gauge, Car, AlertTriangle, Cpu, History, Radio, Ruler } from "lucide-react";
import type { NodeDetail } from "../../types/gis";

interface NodeDashboardDrawerProps {
  node: NodeDetail | null;
  onClose: () => void;
  onOpenHealth: () => void;
  onOpenHistoryForSegment: (segmentId: string) => void;
}

export const NodeDashboardDrawer: React.FC<NodeDashboardDrawerProps> = ({
  node,
  onClose,
  onOpenHealth,
  onOpenHistoryForSegment
}) => {
  if (!node) return null;

  const counts = node.counts_by_class || { motorcycle: 0, car: 0, bus: 0, truck: 0 };
  const totalVehicles = Object.values(counts).reduce((a, b) => (a || 0) + (b || 0), 0);

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
    color: ["#3b82f6", "#10b981", "#f59e0b", "#ec4899"],
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
        data: [
          { value: counts.motorcycle || 0, name: "Xe máy" },
          { value: counts.car || 0, name: "Ô tô con" },
          { value: counts.bus || 0, name: "Xe buýt" },
          { value: counts.truck || 0, name: "Xe tải" }
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
            <span className="text-[11px] font-mono font-bold text-slate-500 bg-white px-2 py-0.5 rounded border border-slate-200">
              {node.segment_id || "segment-001"}
            </span>
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
              <span className="text-sm font-bold font-mono text-slate-800">60 km/h</span>
            </div>
          </div>
        </div>

        {/* Vehicle Classification Donut Chart */}
        <div className="p-3 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm">
          <div className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-1 flex items-center justify-between">
            <span>Cơ cấu phương tiện</span>
            <span className="text-xs text-slate-500 font-normal">Tổng: {totalVehicles} xe</span>
          </div>
          <div className="h-44 w-full">
            <ReactECharts option={donutOption} style={{ height: "100%", width: "100%" }} />
          </div>
        </div>

        {/* Latest AI Camera Snapshot */}
        {node.snapshot_url && (
          <div className="p-3 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm">
            <div className="flex items-center justify-between text-xs font-bold text-slate-700 uppercase tracking-wider mb-2">
              <span>Khung hình Camera AI mới nhất</span>
              <span className="text-[10px] text-emerald-700 font-semibold flex items-center gap-1 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                AI BBOX
              </span>
            </div>
            <div className="relative rounded-lg overflow-hidden border border-slate-200 group shadow-sm">
              <img
                src={node.snapshot_url}
                alt="AI Camera Snapshot"
                className="w-full h-36 object-cover transition duration-300 group-hover:scale-105"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-slate-900/60 via-transparent to-transparent flex items-end p-2">
                <span className="text-[11px] font-mono text-white font-medium">
                  {node.last_seen ? new Date(node.last_seen).toLocaleTimeString() : "Live Snapshot"}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Drawer Action Footer */}
      <div className="p-3 bg-slate-50/90 border-t border-slate-200 grid grid-cols-2 gap-2">
        <button
          onClick={onOpenHealth}
          className="flex items-center justify-center space-x-1.5 py-2.5 px-3 rounded-xl bg-blue-50 hover:bg-blue-100 border border-blue-200 text-blue-700 text-xs font-bold transition shadow-sm"
        >
          <Cpu className="w-4 h-4 text-blue-600" />
          <span>Phần cứng</span>
        </button>

        <button
          onClick={() => onOpenHistoryForSegment(node.segment_id || "segment-001")}
          className="flex items-center justify-center space-x-1.5 py-2.5 px-3 rounded-xl bg-indigo-50 hover:bg-indigo-100 border border-indigo-300 text-indigo-700 text-xs font-bold transition shadow-sm"
        >
          <History className="w-4 h-4 text-indigo-600" />
          <span>Lịch sử kẹt xe</span>
        </button>
      </div>
    </div>
  );
};
