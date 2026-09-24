import React, { useState } from "react";
import { X, Search, Video, Plus, Trash2, MapPin, Gauge } from "lucide-react";
import type { NodeDetail } from "../../types/gis";
import { api } from "../../services/api";

interface NodeManagementPanelProps {
  nodes: NodeDetail[];
  onClose: () => void;
  onSelectNode: (edgeId: string) => void;
  onOpenAddNode: () => void;
  onRefreshNodes: () => void;
}

export const NodeManagementPanel: React.FC<NodeManagementPanelProps> = ({
  nodes,
  onClose,
  onSelectNode,
  onOpenAddNode,
  onRefreshNodes
}) => {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");

  const filteredNodes = nodes.filter((n) => {
    const matchSearch = n.name.toLowerCase().includes(search.toLowerCase()) || n.edge_id.toLowerCase().includes(search.toLowerCase());
    if (!matchSearch) return false;
    if (filter === "online") return n.status === "online";
    if (filter === "congested") return n.traffic_status === "CONGESTED";
    if (filter === "offline") return n.status === "offline";
    return true;
  });

  const handleDelete = async (edgeId: string) => {
    if (confirm(`Bạn có chắc chắn muốn xóa trạm camera ${edgeId} khỏi bản đồ không?`)) {
      try {
        await api.deleteNode(edgeId);
        onRefreshNodes();
      } catch (e) {
        console.error("Delete failed:", e);
      }
    }
  };

  return (
    <div className="fixed inset-y-0 left-0 w-96 z-30 flex flex-col glass-panel border-r border-slate-200 text-slate-800 shadow-2xl animate-in slide-in-from-left duration-300">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-200 bg-slate-50/80">
        <div className="flex items-center space-x-2.5">
          <div className="p-2 rounded-xl bg-blue-50 border border-blue-200 text-blue-600 shadow-sm">
            <Video className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-slate-900">Quản lý Mạng lưới Nodes</h2>
            <p className="text-[11px] text-slate-500 font-medium">Danh mục thiết bị biên & góc camera</p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Search & Actions */}
      <div className="p-4 space-y-3 border-b border-slate-200 bg-slate-50/60">
        <div className="relative">
          <Search className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Tìm theo tên trạm hoặc mã edge_id..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-xs rounded-xl bg-white border border-slate-300 text-slate-800 placeholder-slate-400 focus:outline-none focus:border-blue-500 shadow-sm"
          />
        </div>

        {/* Filter Badges */}
        <div className="flex items-center space-x-1.5 overflow-x-auto pb-1 text-[11px]">
          {[
            { id: "all", label: `Tất cả (${nodes.length})` },
            { id: "online", label: `Online (${nodes.filter((n) => n.status === "online").length})` },
            { id: "congested", label: `Ùn tắc (${nodes.filter((n) => n.traffic_status === "CONGESTED").length})` }
          ].map((f) => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={`px-2.5 py-1 rounded-lg font-semibold border transition shadow-sm ${
                filter === f.id
                  ? "bg-blue-600 border-blue-600 text-white"
                  : "bg-white border-slate-300 text-slate-700 hover:bg-slate-100"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        <button
          onClick={onOpenAddNode}
          className="w-full flex items-center justify-center space-x-1.5 py-2 px-3 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold transition shadow-md shadow-blue-500/20"
        >
          <Plus className="w-4 h-4" />
          <span>Thêm trạm Camera mới lên Bản đồ</span>
        </button>
      </div>

      {/* Node List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
        {filteredNodes.map((node) => (
          <div
            key={node.edge_id}
            onClick={() => onSelectNode(node.edge_id)}
            className="p-3.5 rounded-xl bg-white hover:bg-slate-50 border border-slate-200 hover:border-blue-300 cursor-pointer transition group shadow-sm"
          >
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2 mb-1">
                <span className={`w-2 h-2 rounded-full ${node.status === "online" ? "bg-emerald-500" : "bg-slate-400"}`} />
                <span className="font-mono text-xs font-bold text-blue-700">{node.edge_id}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${
                  node.traffic_status === "CONGESTED" ? "bg-red-100 text-red-700 border border-red-300" : "bg-emerald-100 text-emerald-700 border border-emerald-300"
                }`}>
                  {node.traffic_status}
                </span>
              </div>

              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(node.edge_id);
                }}
                className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-100 text-red-600 transition"
                title="Xóa trạm này"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="text-xs font-bold text-slate-900 line-clamp-1">{node.name}</div>
            <div className="text-[11px] text-slate-500 flex items-center gap-1 mt-0.5 font-medium">
              <MapPin className="w-3 h-3 text-slate-400" />
              <span>{node.road_name || "Đoạn đường liên kết"}</span>
            </div>

            <div className="flex items-center justify-between text-[11px] text-slate-500 mt-2.5 pt-2 border-t border-slate-100 font-mono">
              <span className="flex items-center gap-1 font-semibold text-blue-700">
                <Gauge className="w-3 h-3 text-blue-600" />
                {node.avg_speed_kmh} km/h
              </span>
              <span>Xe trong ROI: <strong className="text-slate-800 font-semibold">{node.vehicle_count}</strong></span>
              <span>Góc: {node.heading}°</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
