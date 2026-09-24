import React, { useState } from "react";
import { Layers, Map as MapIcon, Compass } from "lucide-react";

interface LayerControlProps {
  currentBasemap: string;
  onSelectBasemap: (basemap: string) => void;
  layers: {
    nodes: boolean;
    segments: boolean;
    fovCones: boolean;
    speedLabels: boolean;
  };
  onToggleLayer: (layerName: string) => void;
}

export const LayerControl: React.FC<LayerControlProps> = ({
  currentBasemap,
  onSelectBasemap,
  layers,
  onToggleLayer
}) => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="absolute top-20 right-3 z-10 flex flex-col items-end">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center space-x-2 px-3.5 py-2.5 rounded-xl glass-panel text-slate-700 hover:text-slate-900 border border-slate-200 transition shadow-md"
        title="Quản lý lớp bản đồ"
      >
        <Layers className="w-4 h-4 text-blue-600" />
        <span className="text-xs font-bold">Lớp bản đồ</span>
      </button>

      {isOpen && (
        <div className="mt-2 w-64 p-4 rounded-xl glass-panel text-slate-800 shadow-2xl border border-slate-200 animate-in fade-in slide-in-from-top-2 duration-200">
          <div className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2.5 flex items-center gap-1.5">
            <MapIcon className="w-3.5 h-3.5 text-blue-600" />
            Bản đồ nền (Basemap)
          </div>

          <div className="grid grid-cols-2 gap-1.5 mb-4">
            {[
              { id: "google", label: "🗺️ Google Maps" },
              { id: "google_satellite", label: "🛰️ Google Vệ tinh" },
              { id: "light", label: "🏙️ Carto Sáng" },
              { id: "streets", label: "🛣️ OpenStreetMap" }
            ].map((b) => (
              <button
                key={b.id}
                onClick={() => onSelectBasemap(b.id)}
                className={`py-2 px-2.5 text-xs rounded-lg border transition font-semibold text-center ${
                  currentBasemap === b.id
                    ? "bg-blue-600 border-blue-600 text-white shadow-sm shadow-blue-500/30"
                    : "bg-slate-50 border-slate-200 text-slate-700 hover:bg-slate-100"
                }`}
              >
                {b.label}
              </button>
            ))}
          </div>

          <div className="h-px bg-slate-200 my-3" />

          <div className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Compass className="w-3.5 h-3.5 text-indigo-600" />
            Lớp dữ liệu hiển thị
          </div>

          <div className="space-y-2 text-xs">
            <label className="flex items-center justify-between p-2 rounded-lg bg-slate-50 hover:bg-slate-100 cursor-pointer border border-slate-200">
              <span className="flex items-center gap-2 font-medium">
                <span className="w-2.5 h-2.5 rounded-full bg-blue-500"></span>
                Dấu chấm Node Camera
              </span>
              <input
                type="checkbox"
                checked={layers.nodes}
                onChange={() => onToggleLayer("nodes")}
                className="rounded accent-blue-600"
              />
            </label>

            <label className="flex items-center justify-between p-2 rounded-lg bg-slate-50 hover:bg-slate-100 cursor-pointer border border-slate-200">
              <span className="flex items-center gap-2 font-medium">
                <span className="w-2.5 h-2.5 rounded-full bg-amber-500"></span>
                Đoạn đường tô màu Heatmap
              </span>
              <input
                type="checkbox"
                checked={layers.segments}
                onChange={() => onToggleLayer("segments")}
                className="rounded accent-blue-600"
              />
            </label>

            <label className="flex items-center justify-between p-2 rounded-lg bg-slate-50 hover:bg-slate-100 cursor-pointer border border-slate-200">
              <span className="flex items-center gap-2 font-medium">
                <span className="w-2.5 h-2.5 rounded-full bg-cyan-600"></span>
                Quạt góc nhìn Camera (FOV)
              </span>
              <input
                type="checkbox"
                checked={layers.fovCones}
                onChange={() => onToggleLayer("fovCones")}
                className="rounded accent-blue-600"
              />
            </label>
          </div>
        </div>
      )}
    </div>
  );
};
