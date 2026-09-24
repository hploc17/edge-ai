import React, { useState, useEffect } from "react";
import ReactECharts from "echarts-for-react";
import { X, Play, Pause, RotateCcw, Calendar, TrendingDown, Image } from "lucide-react";
import type { HistoryRecord, CongestionSnapshot } from "../../types/gis";
import { api } from "../../services/api";

interface CongestionHistoryModalProps {
  initialSegmentId: string;
  onClose: () => void;
  onPlaybackUpdate?: (record: HistoryRecord) => void;
}

export const CongestionHistoryModal: React.FC<CongestionHistoryModalProps> = ({
  initialSegmentId,
  onClose,
  onPlaybackUpdate
}) => {
  const [selectedSegment, setSelectedSegment] = useState(initialSegmentId || "segment-001");
  const [records, setRecords] = useState<HistoryRecord[]>([]);
  const [snapshots, setSnapshots] = useState<CongestionSnapshot[]>([]);

  // Playback slider state
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [timelineData, snaps] = await Promise.all([
          api.getTimeline(selectedSegment),
          api.getSnapshots(selectedSegment)
        ]);
        setRecords(timelineData.records);
        setSnapshots(snaps);
        setCurrentIndex(0);
      } catch (e) {
        console.error("Failed to load history:", e);
      }
    };

    fetchData();
  }, [selectedSegment]);

  // Handle Playback Interval
  useEffect(() => {
    let timer: any = null;
    if (isPlaying && records.length > 0) {
      timer = setInterval(() => {
        setCurrentIndex((prev) => {
          const next = prev + 1 >= records.length ? 0 : prev + 1;
          if (onPlaybackUpdate) onPlaybackUpdate(records[next]);
          return next;
        });
      }, 500);
    }
    return () => clearInterval(timer);
  }, [isPlaying, records, onPlaybackUpdate]);

  const handleSliderChange = (idx: number) => {
    setCurrentIndex(idx);
    if (records[idx] && onPlaybackUpdate) {
      onPlaybackUpdate(records[idx]);
    }
  };

  const currentRecord = records[currentIndex];

  // ECharts Line Option for 24h Trend on Light Theme
  const chartOption = {
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" },
    grid: { left: "4%", right: "4%", bottom: "10%", top: "15%", containLabel: true },
    xAxis: {
      type: "category",
      data: records.map((r) => r.time_str),
      axisLine: { lineStyle: { color: "#94a3b8" } },
      axisLabel: { color: "#475569", interval: 7, fontSize: 11 }
    },
    yAxis: [
      {
        type: "value",
        name: "Điểm kẹt",
        min: 0,
        max: 100,
        axisLabel: { color: "#dc2626" },
        splitLine: { lineStyle: { color: "rgba(0,0,0,0.06)" } }
      },
      {
        type: "value",
        name: "Vận tốc (km/h)",
        min: 0,
        max: 60,
        axisLabel: { color: "#0284c7" },
        splitLine: { show: false }
      }
    ],
    series: [
      {
        name: "Điểm kẹt xe",
        type: "line",
        smooth: true,
        data: records.map((r) => r.congestion_score),
        lineStyle: { width: 3, color: "#ef4444" },
        areaStyle: {
          color: {
            type: "linear",
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(239, 68, 68, 0.35)" },
              { offset: 1, color: "rgba(239, 68, 68, 0.0)" }
            ]
          }
        }
      },
      {
        name: "Vận tốc trung bình",
        type: "line",
        yAxisIndex: 1,
        smooth: true,
        data: records.map((r) => r.avg_speed_kmh),
        lineStyle: { width: 2.5, color: "#0284c7" }
      }
    ]
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-4xl rounded-2xl glass-panel text-slate-800 shadow-2xl border border-slate-200 overflow-hidden flex flex-col max-h-[92vh]">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-200 bg-slate-50/80">
          <div>
            <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <Calendar className="w-5 h-5 text-indigo-600" />
              Lịch sử Ùn tắc & Tua Lại Theo Thời Gian (24H Playback)
            </h2>
            <p className="text-xs text-slate-500 mt-0.5 font-medium">
              Phân tích nhịp sinh học ùn tắc giao thông và ảnh bằng chứng theo đoạn đường
            </p>
          </div>

          <div className="flex items-center space-x-3">
            <select
              value={selectedSegment}
              onChange={(e) => setSelectedSegment(e.target.value)}
              className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-white border border-slate-300 text-slate-700 shadow-sm focus:outline-none focus:border-blue-500"
            >
              <option value="segment-001">Đường Nguyễn Trãi (Hà Đông)</option>
              <option value="segment-002">Đường Khuất Duy Tiến (Vành Đai 3)</option>
              <option value="segment-003">Đường Lê Văn Lương (Hoàng Minh Giám)</option>
            </select>

            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto space-y-6 flex-1 text-sm">
          {/* 1. Time Playback Slider Section */}
          <div className="p-4 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <button
                  onClick={() => setIsPlaying(!isPlaying)}
                  className={`flex items-center space-x-1.5 px-3.5 py-1.5 rounded-lg font-bold text-xs transition shadow-sm ${
                    isPlaying ? "bg-amber-600 hover:bg-amber-700 text-white" : "bg-blue-600 hover:bg-blue-700 text-white"
                  }`}
                >
                  {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                  <span>{isPlaying ? "Tạm dừng" : "Tua lại tự động"}</span>
                </button>

                <button
                  onClick={() => handleSliderChange(0)}
                  className="p-1.5 rounded-lg bg-white hover:bg-slate-100 border border-slate-300 text-slate-600 transition shadow-sm"
                  title="Về đầu ngày (00:00)"
                >
                  <RotateCcw className="w-4 h-4" />
                </button>
              </div>

              {currentRecord && (
                <div className="flex items-center space-x-4 text-xs">
                  <span className="font-mono text-base font-bold text-blue-700 bg-blue-50 px-2.5 py-1 rounded-lg border border-blue-200">
                    🕒 {currentRecord.time_str}
                  </span>
                  <span className="text-slate-600 font-medium">
                    Điểm kẹt:{" "}
                    <strong className={currentRecord.congestion_score >= 65 ? "text-red-600" : "text-amber-600"}>
                      {currentRecord.congestion_score}/100
                    </strong>
                  </span>
                  <span className="text-slate-600 font-medium">
                    Vận tốc: <strong className="text-blue-700">{currentRecord.avg_speed_kmh} km/h</strong>
                  </span>
                </div>
              )}
            </div>

            {/* Slider track */}
            <input
              type="range"
              min={0}
              max={records.length > 0 ? records.length - 1 : 0}
              value={currentIndex}
              onChange={(e) => handleSliderChange(Number(e.target.value))}
              className="w-full h-2.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
            />
            <div className="flex justify-between text-[11px] text-slate-500 font-mono font-medium">
              <span>00:00</span>
              <span>06:00</span>
              <span>12:00</span>
              <span>18:00</span>
              <span>23:45</span>
            </div>
          </div>

          {/* 2. 24h Trend Chart */}
          <div className="p-4 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm">
            <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-2 flex items-center gap-2">
              <TrendingDown className="w-4 h-4 text-blue-600" />
              Biểu đồ Diễn biến Mức độ Ùn tắc trong 24 Giờ
            </h3>
            <div className="h-56 w-full">
              <ReactECharts option={chartOption} style={{ height: "100%", width: "100%" }} />
            </div>
          </div>

          {/* 3. Snapshot Gallery */}
          <div className="p-4 rounded-xl bg-slate-50/90 border border-slate-200 shadow-sm">
            <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-3 flex items-center gap-2">
              <Image className="w-4 h-4 text-emerald-600" />
              Ảnh Bằng chứng Kẹt xe Tự động Ghi nhận ({snapshots.length})
            </h3>

            <div className="grid grid-cols-3 gap-3">
              {snapshots.map((snap) => (
                <div
                  key={snap.snapshot_id}
                  className="rounded-xl overflow-hidden border border-slate-200 bg-white group hover:border-blue-400 hover:shadow-md transition"
                >
                  <div className="relative h-28 overflow-hidden">
                    <img
                      src={snap.image_url}
                      alt={snap.location_name}
                      className="w-full h-full object-cover group-hover:scale-105 transition duration-300"
                    />
                    <span className="absolute top-2 left-2 px-1.5 py-0.5 text-[10px] font-bold rounded bg-red-600 text-white shadow">
                      {snap.time_str}
                    </span>
                    <span className="absolute bottom-2 right-2 px-1.5 py-0.5 text-[10px] font-bold rounded bg-slate-900/80 text-white">
                      {snap.avg_speed_kmh} km/h
                    </span>
                  </div>
                  <div className="p-2.5">
                    <div className="text-xs font-bold text-slate-800 line-clamp-1">{snap.location_name}</div>
                    <div className="flex justify-between text-[11px] text-slate-500 mt-1 font-medium">
                      <span>Điểm kẹt: {snap.congestion_score}/100</span>
                      <span>{snap.vehicle_count} xe</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
