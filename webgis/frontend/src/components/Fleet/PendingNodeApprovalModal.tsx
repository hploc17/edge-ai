/**
 * PendingNodeApprovalModal
 *
 * Wizard phê duyệt thiết bị Jetson chưa được định vị.
 * Admin chọn 1 thiết bị pending → Click bản đồ để chọn vị trí →
 * Hệ thống tự tra cứu OSM → Admin xác nhận/chỉnh sửa → Phê duyệt.
 */

import React, { useState, useCallback, useEffect } from "react";
import {
  X, MapPin, CheckCircle, XCircle, Loader2, Route,
  AlertTriangle, Radio, Clock, Cpu, ChevronRight, ChevronLeft,
  Search, Navigation
} from "lucide-react";
import { api } from "../../services/api";
import type { PendingNodeInfo, OSMRoadInfo } from "../../types/gis";

interface PendingNodeApprovalModalProps {
  onClose: () => void;
  /** Callback khi Admin bấm "Chọn vị trí trên bản đồ" - truyền edge_id đang xử lý */
  onEnablePickMode: (edgeId: string) => void;
  /** Tọa độ Admin đã click trên bản đồ (từ App.tsx) */
  pickedCoords: { lat: number; lng: number } | null;
  onNodeApproved: () => void;
}

type Stage = "list" | "configure" | "confirming";

export const PendingNodeApprovalModal: React.FC<PendingNodeApprovalModalProps> = ({
  onClose,
  onEnablePickMode,
  pickedCoords,
  onNodeApproved,
}) => {
  const [pendingNodes, setPendingNodes] = useState<PendingNodeInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [stage, setStage] = useState<Stage>("list");
  const [selectedNode, setSelectedNode] = useState<PendingNodeInfo | null>(null);

  // Form state
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [roadName, setRoadName] = useState("");
  const [laneCount, setLaneCount] = useState(2);
  const [roadLengthM, setRoadLengthM] = useState(200);
  const [roadWidthM, setRoadWidthM] = useState(7.0);
  const [speedLimit, setSpeedLimit] = useState(60);
  const [cameraHeading, setCameraHeading] = useState(0);
  const [cameraFov, setCameraFov] = useState(65);
  const [osmInfo, setOsmInfo] = useState<OSMRoadInfo | null>(null);
  const [osmCoordinates, setOsmCoordinates] = useState<[number, number][] | null>(null);
  const [osmWayId, setOsmWayId] = useState<number | undefined>(undefined);
  const [osmRoadType, setOsmRoadType] = useState<string | undefined>(undefined);
  const [osmLoading, setOsmLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [nodeName, setNodeName] = useState("");

  // Load danh sách pending
  const loadPending = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.getPendingNodes();
      setPendingNodes(list);
    } catch (e) {
      console.error("Failed to load pending nodes:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPending();
  }, [loadPending]);

  // Khi Admin click bản đồ và quay lại modal
  useEffect(() => {
    if (pickedCoords && stage === "configure" && selectedNode) {
      setLat(pickedCoords.lat.toFixed(7));
      setLng(pickedCoords.lng.toFixed(7));
      // Tự động tra cứu OSM
      lookupOSM(pickedCoords.lat, pickedCoords.lng);
    }
  }, [pickedCoords]);

  const lookupOSM = async (latVal: number, lngVal: number) => {
    setOsmLoading(true);
    setOsmInfo(null);
    setError("");
    try {
      const info = await api.fetchOSMRoadInfo(latVal, lngVal);
      setOsmInfo(info);
      if (info.found) {
        setRoadName(info.road_name || "");
        if (info.lanes) setLaneCount(info.lanes);
        if (info.road_length_m) setRoadLengthM(Math.round(info.road_length_m));
        if (info.road_width_m) setRoadWidthM(info.road_width_m);
        if (info.speed_limit_kmh) setSpeedLimit(info.speed_limit_kmh);
        if (info.coordinates) setOsmCoordinates(info.coordinates);
        if (info.osm_way_id) setOsmWayId(info.osm_way_id);
        if (info.road_type) setOsmRoadType(info.road_type);
      }
    } catch {
      setError("Không thể tra cứu OSM. Vui lòng nhập thủ công.");
    } finally {
      setOsmLoading(false);
    }
  };

  const handleSelectNode = (node: PendingNodeInfo) => {
    setSelectedNode(node);
    setNodeName(node.name);
    setLat(node.latitude?.toString() ?? "");
    setLng(node.longitude?.toString() ?? "");
    if (node.camera_heading != null) setCameraHeading(node.camera_heading);
    if (node.camera_fov != null) setCameraFov(node.camera_fov);
    setRoadName(node.road_name ?? "");
    setOsmInfo(null);
    setError("");
    setStage("configure");

    // Nếu Jetson đã gửi GPS hợp lệ, tự động tra cứu luôn
    if (node.latitude && node.longitude && Math.abs(node.latitude) > 0.1) {
      lookupOSM(node.latitude, node.longitude);
    }
  };

  const handleApprove = async () => {
    if (!selectedNode) return;
    const latNum = parseFloat(lat);
    const lngNum = parseFloat(lng);
    if (isNaN(latNum) || isNaN(lngNum)) {
      setError("Vui lòng nhập hoặc chọn tọa độ hợp lệ.");
      return;
    }
    if (!roadName.trim()) {
      setError("Vui lòng nhập tên đường.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api.approveNode(selectedNode.edge_id, {
        name: nodeName,
        latitude: latNum,
        longitude: lngNum,
        road_name: roadName,
        lane_count: laneCount,
        road_length_m: roadLengthM,
        road_width_m: roadWidthM,
        speed_limit_kmh: speedLimit,
        camera_heading: cameraHeading,
        camera_fov: cameraFov,
        osm_way_id: osmWayId,
        osm_road_type: osmRoadType,
        osm_coordinates: osmCoordinates ?? undefined,
      });
      onNodeApproved();
      // Xóa khỏi danh sách local rồi hiển thị tiếp
      setPendingNodes(prev => prev.filter(n => n.edge_id !== selectedNode.edge_id));
      setStage("list");
      setSelectedNode(null);
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Lỗi phê duyệt. Vui lòng thử lại.");
    } finally {
      setSaving(false);
    }
  };

  const handleReject = async (edgeId: string) => {
    try {
      await api.rejectPendingNode(edgeId);
      setPendingNodes(prev => prev.filter(n => n.edge_id !== edgeId));
    } catch {
      // silent fail
    }
  };

  const formatTime = (iso: string) => {
    try {
      return new Date(iso).toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });
    } catch { return iso; }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4 animate-fade-in">
      <div className="relative w-full max-w-2xl max-h-[90vh] flex flex-col bg-white rounded-2xl shadow-2xl overflow-hidden border border-slate-200">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 bg-gradient-to-r from-amber-50 to-orange-50 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-amber-100 border border-amber-200 flex items-center justify-center">
              <Radio className="w-4 h-4 text-amber-600" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold text-slate-900">Phê duyệt Thiết bị Mới</h2>
                {pendingNodes.length > 0 && (
                  <span className="px-2 py-0.5 bg-amber-500 text-white text-[10px] font-bold rounded-full animate-pulse">
                    {pendingNodes.length} chờ duyệt
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-500 mt-0.5">
                {stage === "list" ? "Danh sách thiết bị Jetson đã kết nối chưa được định vị" : `Cấu hình: ${selectedNode?.name}`}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {stage === "configure" && (
              <button
                onClick={() => setStage("list")}
                className="flex items-center gap-1 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 rounded-lg transition"
              >
                <ChevronLeft className="w-3.5 h-3.5" /> Quay lại
              </button>
            )}
            <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-xl transition">
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* ── Danh sách chờ duyệt ── */}
        {stage === "list" && (
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-6 h-6 text-amber-600 animate-spin" />
                <span className="ml-2 text-sm text-slate-500">Đang tải danh sách thiết bị...</span>
              </div>
            ) : pendingNodes.length === 0 ? (
              <div className="text-center py-12 space-y-2">
                <CheckCircle className="w-10 h-10 text-emerald-500 mx-auto" />
                <p className="text-sm font-semibold text-slate-700">Không có thiết bị nào chờ duyệt</p>
                <p className="text-xs text-slate-400">Mọi thiết bị Jetson đã được phê duyệt và đang hoạt động trên bản đồ.</p>
              </div>
            ) : (
              pendingNodes.map((node) => (
                <div key={node.edge_id} className="p-3 rounded-xl border border-amber-200 bg-amber-50/50 hover:bg-amber-50 transition">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
                        <span className="text-xs font-bold text-slate-900 truncate">{node.name}</span>
                        <code className="text-[9px] bg-white border border-slate-200 px-1.5 py-0.5 rounded font-mono text-slate-600">{node.edge_id}</code>
                      </div>
                      <div className="flex flex-wrap gap-2 text-[10px] text-slate-500">
                        <span className="flex items-center gap-0.5"><Cpu className="w-3 h-3" /> {node.camera_id || "?"}</span>
                        <span className="flex items-center gap-0.5"><Clock className="w-3 h-3" /> {formatTime(node.first_seen)}</span>
                        {node.latitude ? (
                          <span className="flex items-center gap-0.5 text-emerald-600">
                            <Navigation className="w-3 h-3" /> GPS: {node.latitude?.toFixed(4)}, {node.longitude?.toFixed(4)}
                          </span>
                        ) : (
                          <span className="flex items-center gap-0.5 text-amber-600">
                            <AlertTriangle className="w-3 h-3" /> Chưa có GPS
                          </span>
                        )}
                        {node.model_version && <span>v{node.model_version}</span>}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        onClick={() => handleReject(node.edge_id)}
                        className="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition"
                        title="Từ chối"
                      >
                        <XCircle className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleSelectNode(node)}
                        className="flex items-center gap-1 px-3 py-1.5 bg-amber-600 hover:bg-amber-700 text-white text-xs font-bold rounded-lg transition shadow-sm"
                      >
                        Cấu hình <ChevronRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* ── Form cấu hình thiết bị ── */}
        {stage === "configure" && selectedNode && (
          <div className="flex-1 overflow-y-auto p-4 space-y-4">

            {/* Chọn vị trí */}
            <div className="space-y-2 p-3 rounded-xl border border-slate-200 bg-slate-50">
              <div className="flex items-center gap-2 text-xs font-bold text-slate-700 uppercase tracking-wide">
                <MapPin className="w-3.5 h-3.5 text-blue-600" />
                <span>Bước 1 · Xác định vị trí đặt camera</span>
              </div>
              <div className="flex gap-2">
                <div className="flex-1 space-y-2">
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-[10px] font-semibold text-slate-600 mb-1">Vĩ độ (Lat)</label>
                      <input
                        type="number" step="any" value={lat}
                        onChange={e => { setLat(e.target.value); setOsmInfo(null); }}
                        placeholder="10.7769..."
                        className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-slate-300 bg-white focus:outline-none focus:border-blue-500 font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] font-semibold text-slate-600 mb-1">Kinh độ (Lng)</label>
                      <input
                        type="number" step="any" value={lng}
                        onChange={e => { setLng(e.target.value); setOsmInfo(null); }}
                        placeholder="106.7009..."
                        className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-slate-300 bg-white focus:outline-none focus:border-blue-500 font-mono"
                      />
                    </div>
                  </div>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => onEnablePickMode(selectedNode.edge_id)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold rounded-lg transition flex-1 justify-center"
                >
                  <MapPin className="w-3.5 h-3.5" /> Nhấp bản đồ để chọn vị trí
                </button>
                <button
                  onClick={() => {
                    const la = parseFloat(lat), lo = parseFloat(lng);
                    if (!isNaN(la) && !isNaN(lo)) lookupOSM(la, lo);
                  }}
                  disabled={osmLoading || !lat || !lng}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white text-xs font-bold rounded-lg transition"
                >
                  {osmLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
                  Tra OSM
                </button>
              </div>

              {/* OSM Result Badge */}
              {osmInfo && (
                <div className={`flex items-center gap-2 px-3 py-2 rounded-lg text-[11px] font-medium ${osmInfo.found ? "bg-emerald-50 border border-emerald-200 text-emerald-800" : "bg-amber-50 border border-amber-200 text-amber-800"}`}>
                  {osmInfo.found ? <CheckCircle className="w-3.5 h-3.5 shrink-0" /> : <AlertTriangle className="w-3.5 h-3.5 shrink-0" />}
                  <span>{osmInfo.message}</span>
                  {osmInfo.found && osmInfo.coordinates && (
                    <span className="ml-auto text-emerald-600 font-bold flex items-center gap-1">
                      <Route className="w-3 h-3" /> {osmInfo.coordinates.length} điểm tọa độ
                    </span>
                  )}
                </div>
              )}
            </div>

            {/* Thông số đường */}
            <div className="space-y-3 p-3 rounded-xl border border-slate-200 bg-slate-50">
              <div className="flex items-center gap-2 text-xs font-bold text-slate-700 uppercase tracking-wide">
                <Route className="w-3.5 h-3.5 text-indigo-600" />
                <span>Bước 2 · Thông số đoạn đường</span>
              </div>

              <div>
                <label className="block text-[10px] font-semibold text-slate-600 mb-1">Tên thiết bị / Camera</label>
                <input value={nodeName} onChange={e => setNodeName(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-slate-300 bg-white focus:outline-none focus:border-blue-500" />
              </div>
              <div>
                <label className="block text-[10px] font-semibold text-slate-600 mb-1">Tên đường *</label>
                <input value={roadName} onChange={e => setRoadName(e.target.value)}
                  placeholder="Ví dụ: Phố Tố Hữu"
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-slate-300 bg-white focus:outline-none focus:border-blue-500" />
              </div>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: "Số làn xe", val: laneCount, set: setLaneCount, step: 1, min: 1 },
                  { label: "Chiều dài (m)", val: roadLengthM, set: setRoadLengthM, step: 10, min: 10 },
                  { label: "Chiều rộng (m)", val: roadWidthM, set: setRoadWidthM, step: 0.5, min: 2 },
                  { label: "Tốc độ tối đa", val: speedLimit, set: setSpeedLimit, step: 10, min: 10 },
                  { label: "Hướng cam (°)", val: cameraHeading, set: setCameraHeading, step: 5, min: 0 },
                  { label: "FOV cam (°)", val: cameraFov, set: setCameraFov, step: 5, min: 20 },
                ].map(({ label, val, set, step, min }) => (
                  <div key={label}>
                    <label className="block text-[10px] font-semibold text-slate-600 mb-1">{label}</label>
                    <input type="number" step={step} min={min} value={val}
                      onChange={e => set(parseFloat(e.target.value) || 0)}
                      className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-slate-300 bg-white focus:outline-none focus:border-blue-500 font-mono" />
                  </div>
                ))}
              </div>
            </div>

            {error && (
              <div className="flex items-center gap-2 px-3 py-2 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0" /> {error}
              </div>
            )}

            {/* Action buttons */}
            <div className="flex gap-2 pt-1">
              <button
                onClick={() => handleReject(selectedNode.edge_id)}
                className="flex items-center gap-1.5 px-4 py-2 border border-red-200 text-red-600 hover:bg-red-50 text-xs font-semibold rounded-xl transition"
              >
                <XCircle className="w-3.5 h-3.5" /> Từ chối thiết bị
              </button>
              <button
                onClick={handleApprove}
                disabled={saving || !lat || !lng || !roadName.trim()}
                className="flex-1 flex items-center justify-center gap-2 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 text-white text-xs font-bold rounded-xl transition shadow-md shadow-emerald-500/20"
              >
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle className="w-3.5 h-3.5" />}
                Phê duyệt & Kích hoạt trên Bản đồ
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
