import React from "react";
import { Activity, ShieldCheck, Video, History, Settings, PlusCircle, AlertTriangle } from "lucide-react";
import type { SummaryKPIs } from "../types/gis";

interface NavbarProps {
  kpis: SummaryKPIs | null;
  onOpenHistory: () => void;
  onOpenFleet: () => void;
  onOpenAddNode: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  kpis,
  onOpenHistory,
  onOpenFleet,
  onOpenAddNode
}) => {
  return (
    <header className="absolute top-3 left-3 right-3 z-20 flex items-center justify-between px-5 py-3 rounded-xl glass-panel text-slate-800">
      {/* Brand & System Status */}
      <div className="flex items-center space-x-3">
        <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-blue-50 border border-blue-200 text-blue-600 shadow-sm">
          <Video className="w-5 h-5" />
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="font-extrabold text-lg tracking-wide bg-gradient-to-r from-blue-700 via-indigo-600 to-cyan-600 bg-clip-text text-transparent">
              TRAFFIC OPERATIONS CENTER
            </h1>
            <span className="px-2 py-0.5 text-xs font-bold bg-emerald-100 text-emerald-700 border border-emerald-300 rounded-full flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
              LIVE GIS
            </span>
          </div>
          <p className="text-xs text-slate-500 font-medium">Nền tảng Giám sát Giao thông Đô thị & Thiết bị Biên AI</p>
        </div>
      </div>

      {/* Real-time KPIs */}
      {kpis && (
        <div className="hidden lg:flex items-center space-x-6 px-4 py-1.5 rounded-lg bg-slate-50/90 border border-slate-200 text-sm shadow-inner">
          <div className="flex items-center space-x-2">
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
            <span className="text-slate-500 text-xs font-medium">Nodes Online:</span>
            <span className="font-bold text-emerald-700">
              {kpis.online_nodes}/{kpis.total_nodes}
            </span>
          </div>

          <div className="h-4 w-px bg-slate-200" />

          <div className="flex items-center space-x-2">
            <AlertTriangle className="w-4 h-4 text-amber-600" />
            <span className="text-slate-500 text-xs font-medium">Điểm ùn tắc:</span>
            <span className={`font-bold ${kpis.congested_segments > 0 ? "text-red-600 animate-pulse" : "text-slate-700"}`}>
              {kpis.congested_segments} đoạn
            </span>
          </div>

          <div className="h-4 w-px bg-slate-200" />

          <div className="flex items-center space-x-2">
            <Activity className="w-4 h-4 text-blue-600" />
            <span className="text-slate-500 text-xs font-medium">Vận tốc TB:</span>
            <span className="font-bold text-blue-700">{kpis.system_avg_speed_kmh} km/h</span>
          </div>
        </div>
      )}

      {/* Navigation Buttons */}
      <div className="flex items-center space-x-2.5">
        <button
          onClick={onOpenHistory}
          className="flex items-center space-x-1.5 px-3.5 py-2 text-xs font-semibold rounded-lg bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 text-indigo-700 transition shadow-sm"
        >
          <History className="w-4 h-4 text-indigo-600" />
          <span>Lịch sử Kẹt xe</span>
        </button>

        <button
          onClick={onOpenFleet}
          className="flex items-center space-x-1.5 px-3.5 py-2 text-xs font-semibold rounded-lg bg-slate-100 hover:bg-slate-200 border border-slate-300 text-slate-700 transition shadow-sm"
        >
          <Settings className="w-4 h-4 text-slate-500" />
          <span>Quản lý Nodes</span>
        </button>

        <button
          onClick={onOpenAddNode}
          className="flex items-center space-x-1.5 px-3.5 py-2 text-xs font-bold rounded-lg bg-blue-600 hover:bg-blue-700 text-white shadow-md shadow-blue-500/25 transition"
        >
          <PlusCircle className="w-4 h-4" />
          <span>Thêm Node</span>
        </button>
      </div>
    </header>
  );
};
