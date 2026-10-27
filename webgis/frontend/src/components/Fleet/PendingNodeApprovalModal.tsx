/**
 * PendingNodeApprovalModal
 *
 * Wizard cấu hình & phê duyệt thiết bị Jetson theo định danh phần cứng (MAC Address):
 * 1. Nhận diện MAC: Hiển thị địa chỉ MAC phần cứng của Jetson.
 * 2. Đọc thông số không gian từ thiết bị qua lệnh MQTT (get_spatial_info) HOẶC tự điền bằng tay / nhấp bản đồ.
 * 3. Tự động tra cứu OpenStreetMap để lấy tên đường và tọa độ tim đường thực tế.
 * 4. Lưu cấu hình vĩnh viễn (gán MAC ↔ Node ↔ Tọa độ) và hiển thị lên WebGIS.
 * 5. Hỗ trợ cấu hình lại (re-configure) cho các Node đã lưu bất cứ lúc nào.
 */

import React, { useState, useCallback, useEffect } from "react";
import {
  X, MapPin, CheckCircle, XCircle, Loader2, Route,
  AlertTriangle, Radio, Clock, ChevronRight, ChevronLeft,
  Search, Navigation, Cpu, Wifi, Settings, ShieldCheck
} from "lucide-react";
import { api } from "../../services/api";
import type { PendingNodeInfo, NodeDetail, OSMRoadInfo } from "../../types/gis";

interface PendingNodeApprovalModalProps {
  onClose: () => void;
  /** Callback khi Admin bấm "Chọn vị trí trên bản đồ" - truyền edge_id đang xử lý */
  onEnablePickMode: (edgeId: string) => void;
  /** Tọa độ Admin đã click trên bản đồ (từ App.tsx) */
  pickedCoords: { lat: number; lng: number } | null;
  onNodeApproved: () => void;
  /** Truyền node đang tồn tại nếu mở modal ở chế độ "Sửa cấu hình" */
  editingNode?: NodeDetail | null;
  initialSelectedEdgeId?: string | null;
}

type Stage = "list" | "configure";

export const PendingNodeApprovalModal: React.FC<PendingNodeApprovalModalProps> = ({
  onClose,
  onEnablePickMode,
  pickedCoords,
  onNodeApproved,
  editingNode = null,
  initialSelectedEdgeId = null,
}) => {
  const [pendingNodes, setPendingNodes] = useState<PendingNodeInfo[]>([]);
  const [loading, setLoading] = useState(!editingNode);
  const [stage, setStage] = useState<Stage>(editingNode ? "configure" : "list");
  const [selectedNode, setSelectedNode] = useState<PendingNodeInfo | NodeDetail | null>(editingNode || null);

  // Form state
  const [macAddress, setMacAddress] = useState<string>(
    editingNode?.mac_address || (editingNode?.latest_health?.network?.mac_address as string) || ""
  );
  const [lat, setLat] = useState(editingNode ? String(editingNode.latitude) : "");
  const [lng, setLng] = useState(editingNode ? String(editingNode.longitude) : "");
  const [roadName, setRoadName] = useState(editingNode?.road_name || "");
  const [laneCount, setLaneCount] = useState(editingNode?.lane_count || 2);
  const [roadLengthM, setRoadLengthM] = useState(editingNode?.road_length_m || 200);
  const [roadWidthM, setRoadWidthM] = useState(editingNode?.road_width_m || 7.0);
  const [speedLimit, setSpeedLimit] = useState(60);
  const [cameraHeading, setCameraHeading] = useState(editingNode?.camera_heading || editingNode?.heading || 0);
  const [cameraFov, setCameraFov] = useState(editingNode?.camera_fov || editingNode?.fov || 65);
  const [osmInfo, setOsmInfo] = useState<OSMRoadInfo | null>(null);
  const [osmCoordinates, setOsmCoordinates] = useState<[number, number][] | null>(null);
  const [osmWayId, setOsmWayId] = useState<number | undefined>(undefined);
  const [osmRoadType, setOsmRoadType] = useState<string | undefined>(undefined);
  const [osmLoading, setOsmLoading] = useState(false);
  const [readingSpatial, setReadingSpatial] = useState(false);
  const [spatialSuccessMsg, setSpatialSuccessMsg] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [nodeName, setNodeName] = useState(editingNode?.name || "");

  // Load danh sách pending
  const loadPending = useCallback(async () => {
    if (editingNode) return;
    setLoading(true);
    try {
      const list = await api.getPendingNodes();
      setPendingNodes(list);
      // Nếu có yêu cầu mở thẳng 1 edge_id hoặc chỉ có 1 node
      if (initialSelectedEdgeId) {
        const found = list.find(n => n.edge_id === initialSelectedEdgeId);
        if (found) handleSelectNode(found);
      } else if (list.length === 1) {
        handleSelectNode(list[0]);
      }
    } catch (e) {
      console.error("Failed to load pending nodes:", e);
    } finally {
      setLoading(false);
    }
  }, [editingNode, initialSelectedEdgeId]);

  useEffect(() => {
    loadPending();
  }, [loadPending]);

  // Khi Admin click bản đồ và quay lại modal
  useEffect(() => {
    if (pickedCoords && stage === "configure" && selectedNode) {
      setLat(pickedCoords.lat.toFixed(7));
      setLng(pickedCoords.lng.toFixed(7));
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
      setError("Không thể tra cứu OSM tự động. Vui lòng điền thông số thủ công.");
    } finally {
      setOsmLoading(false);
    }
  };

  const handleSelectNode = (node: PendingNodeInfo | NodeDetail) => {
    setSelectedNode(node);
    setNodeName(node.name || `Camera AI (${node.edge_id})`);
    const mac = node.mac_address || (node as any).raw_payload?.mac_address || (node as any).raw_payload?.latest_health?.network?.mac_address || "";
    setMacAddress(mac);
    setLat(node.latitude?.toString() ?? "");
    setLng(node.longitude?.toString() ?? "");
    if (node.camera_heading != null) setCameraHeading(node.camera_heading);
    if (node.camera_fov != null) setCameraFov(node.camera_fov);
    setRoadName(node.road_name ?? "");
    setOsmInfo(null);
    setError("");
    setSpatialSuccessMsg("");
    setStage("configure");

    // Nếu thiết bị đã có GPS hợp lệ, tự động tra cứu OSM
    if (node.latitude && node.longitude && Math.abs(node.latitude) > 0.1) {
      lookupOSM(node.latitude, node.longitude);
    }
  };

  // Đọc thông số không gian & MAC từ Jetson qua MQTT
  const handleReadSpatialInfo = async () => {
    if (!selectedNode) return;
    setReadingSpatial(true);
    setError("");
    setSpatialSuccessMsg("");
    try {
      const res = await api.readSpatialInfo(selectedNode.edge_id);
      const info = res.spatial_info || {};

      if (info.mac_address) {
        setMacAddress(info.mac_address);
      }
      if (info.latitude != null && info.latitude !== 0) {
        setLat(String(info.latitude));
      }
      if (info.longitude != null && info.longitude !== 0) {
        setLng(String(info.longitude));
      }
      if (info.camera_heading != null) {
        setCameraHeading(Number(info.camera_heading));
      }
      if (info.camera_fov != null) {
        setCameraFov(Number(info.camera_fov));
      }
      if (info.road_name) {
        setRoadName(info.road_name);
      }

      setSpatialSuccessMsg(
        res.status === "timeout_fallback"
          ? "Đã nạp thông số không gian lưu trữ hiện có."
          : `✓ Đã kết nối thiết bị thành công! Đọc được MAC ${info.mac_address || ""} và tọa độ GPS.`
      );

      if (info.latitude && info.longitude && Math.abs(info.latitude) > 0.1) {
        lookupOSM(Number(info.latitude), Number(info.longitude));
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Không thể kết nối Jetson để đọc thông số. Bạn có thể tự điền bằng tay.");
    } finally {
      setReadingSpatial(false);
    }
  };

  const handleSave = async () => {
    if (!selectedNode) return;
    const latNum = parseFloat(lat);
    const lngNum = parseFloat(lng);
    if (isNaN(latNum) || isNaN(lngNum)) {
      setError("Vui lòng nhập hoặc chọn tọa độ vị trí camera hợp lệ.");
      return;
    }
    if (!roadName.trim()) {
      setError("Vui lòng nhập tên đường.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const payload = {
        name: nodeName,
        mac_address: macAddress.trim() || undefined,
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
      };

      if (editingNode) {
        await api.updateNode(selectedNode.edge_id, payload);
      } else {
        await api.approveNode(selectedNode.edge_id, payload);
        setPendingNodes(prev => prev.filter(n => n.edge_id !== selectedNode.edge_id));
      }

      onNodeApproved();

      if (!editingNode && pendingNodes.length > 1) {
        setStage("list");
        setSelectedNode(null);
      } else {
        onClose();
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Lỗi lưu cấu hình Node. Vui lòng thử lại.");
    } finally {
      setSaving(false);
    }
  };

  const handleReject = async (edgeId: string) => {
    try {
      await api.rejectPendingNode(edgeId);
      setPendingNodes(prev => prev.filter(n => n.edge_id !== edgeId));
      if (selectedNode?.edge_id === edgeId) {
        setSelectedNode(null);
        setStage("list");
      }
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
      <div className="relative w-full max-w-2xl max-h-[92vh] flex flex-col bg-white rounded-2xl shadow-2xl overflow-hidden border border-slate-200">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 bg-gradient-to-r from-blue-50 via-slate-50 to-indigo-50 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-blue-100 border border-blue-200 flex items-center justify-center text-blue-700 shadow-sm">
              {editingNode ? <Settings className="w-5 h-5 text-blue-600" /> : <Radio className="w-5 h-5 text-blue-600" />}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold text-slate-900">
                  {editingNode ? `Cấu hình Node: ${editingNode.name}` : "Thiết lập & Kích hoạt Node (Hardware MAC)"}
                </h2>
                {!editingNode && pendingNodes.length > 0 && (
                  <span className="px-2 py-0.5 bg-amber-500 text-white text-[10px] font-bold rounded-full animate-pulse">
                    {pendingNodes.length} chờ thiết lập
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-500 font-medium">
                {editingNode
                  ? "Chỉnh sửa thông số không gian & liên kết phần cứng"
                  : "Quản lý vòng đời Node theo định danh phần cứng MAC vĩnh viễn"}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* ── Danh sách chờ (chỉ hiển thị khi có nhiều thiết bị pending và không phải edit) ── */}
        {stage === "list" && !editingNode && (
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {loading ? (
              <div className="flex flex-col items-center justify-center py-12 text-slate-400">
                <Loader2 className="w-8 h-8 animate-spin mb-2" />
                <span className="text-xs">Đang quét hàng chờ thiết bị...</span>
              </div>
            ) : pendingNodes.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-slate-400 text-center">
                <CheckCircle className="w-10 h-10 text-emerald-400 mb-2" />
                <p className="text-xs font-semibold text-slate-700">Tất cả thiết bị đều đã được cấu hình</p>
                <p className="text-[11px] text-slate-500 mt-1">
                  Khi có Jetson Nano mới kết nối MQTT, thiết bị sẽ tự động xuất hiện tại đây.
                </p>
              </div>
            ) : (
              pendingNodes.map((node) => (
                <div
                  key={node.edge_id}
                  className="p-3.5 rounded-xl border border-slate-200 bg-slate-50 hover:bg-white hover:border-blue-400 hover:shadow-md transition"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-bold text-blue-700">{node.edge_id}</span>
                        {node.mac_address && (
                          <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-slate-200 text-slate-700 border border-slate-300 font-semibold flex items-center gap-1">
                            <Cpu className="w-3 h-3 text-slate-500" /> {node.mac_address}
                          </span>
                        )}
                      </div>
                      <div className="text-xs font-bold text-slate-900">{node.name}</div>
                      <div className="flex items-center gap-3 text-[11px] text-slate-500">
                        <span className="flex items-center gap-0.5"><Clock className="w-3 h-3" /> {formatTime(node.first_seen)}</span>
                        {node.latitude ? (
                          <span className="flex items-center gap-0.5 text-emerald-600 font-medium">
                            <Navigation className="w-3 h-3" /> GPS: {node.latitude?.toFixed(4)}, {node.longitude?.toFixed(4)}
                          </span>
                        ) : (
                          <span className="flex items-center gap-0.5 text-amber-600 font-medium">
                            <AlertTriangle className="w-3 h-3" /> Chưa gắn vị trí
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        onClick={() => handleReject(node.edge_id)}
                        className="p-1.5 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition"
                        title="Bỏ qua thiết bị này"
                      >
                        <XCircle className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleSelectNode(node)}
                        className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold rounded-lg transition shadow-sm"
                      >
                        Cấu hình & Lưu <ChevronRight className="w-3.5 h-3.5" />
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

            {/* Thông tin phần cứng & MAC Address Badge */}
            <div className="p-3.5 rounded-xl border border-blue-200 bg-blue-50/70 space-y-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-blue-600" />
                  <span className="text-xs font-bold text-blue-900 uppercase tracking-wide">
                    Định danh phần cứng (Hardware MAC Binding)
                  </span>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-200 text-blue-800 font-bold">
                  {editingNode ? "Đã xác thực" : "Chờ lưu vị trí"}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] font-semibold text-slate-600 mb-1">Mã thiết bị (Edge ID)</label>
                  <input
                    value={selectedNode.edge_id}
                    disabled
                    className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-slate-300 bg-slate-100 text-slate-700 font-mono font-bold"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-semibold text-slate-600 mb-1">Địa chỉ MAC phần cứng</label>
                  <input
                    value={macAddress}
                    onChange={e => setMacAddress(e.target.value)}
                    placeholder="XX:XX:XX:XX:XX:XX"
                    className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-blue-300 bg-white text-blue-800 font-mono font-bold focus:outline-none focus:border-blue-500 uppercase"
                  />
                </div>
              </div>

              {/* Nút hành động đọc trực tiếp từ thiết bị */}
              <div className="pt-1 flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={handleReadSpatialInfo}
                  disabled={readingSpatial}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition shadow-xs"
                >
                  {readingSpatial ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>Đang gửi lệnh đọc từ Jetson...</span>
                    </>
                  ) : (
                    <>
                      <Wifi className="w-3.5 h-3.5" />
                      <span>📡 Đọc thông số không gian từ thiết bị</span>
                    </>
                  )}
                </button>
                <span className="text-[10px] text-slate-500 italic">
                  Gửi lệnh MQTT 'get_spatial_info' để nhận GPS, Heading, FOV
                </span>
              </div>

              {spatialSuccessMsg && (
                <div className="flex items-center gap-1.5 text-emerald-700 bg-emerald-50 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-emerald-200 animate-in fade-in">
                  <CheckCircle className="w-3.5 h-3.5 shrink-0" />
                  <span>{spatialSuccessMsg}</span>
                </div>
              )}
            </div>

            {/* Bước 1: Chọn vị trí tọa độ */}
            <div className="space-y-2.5 p-3.5 rounded-xl border border-slate-200 bg-slate-50">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs font-bold text-slate-700 uppercase tracking-wide">
                  <MapPin className="w-3.5 h-3.5 text-blue-600" />
                  <span>Bước 1 · Tọa độ địa lý camera (GPS)</span>
                </div>
                <span className="text-[10px] text-slate-500 font-medium">Tự điền hoặc nhấp bản đồ</span>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[10px] font-semibold text-slate-600 mb-1">Vĩ độ (Latitude)</label>
                  <input
                    type="number" step="any" value={lat}
                    onChange={e => { setLat(e.target.value); setOsmInfo(null); }}
                    placeholder="20.998412..."
                    className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-slate-300 bg-white focus:outline-none focus:border-blue-500 font-mono"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-semibold text-slate-600 mb-1">Kinh độ (Longitude)</label>
                  <input
                    type="number" step="any" value={lng}
                    onChange={e => { setLng(e.target.value); setOsmInfo(null); }}
                    placeholder="105.795123..."
                    className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-slate-300 bg-white focus:outline-none focus:border-blue-500 font-mono"
                  />
                </div>
              </div>

              <div className="flex gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => onEnablePickMode(selectedNode.edge_id)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold rounded-lg transition flex-1 justify-center shadow-xs"
                >
                  <MapPin className="w-3.5 h-3.5" /> Nhấp bản đồ để chọn vị trí
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const la = parseFloat(lat), lo = parseFloat(lng);
                    if (!isNaN(la) && !isNaN(lo)) lookupOSM(la, lo);
                  }}
                  disabled={osmLoading || !lat || !lng}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white text-xs font-bold rounded-lg transition shadow-xs"
                >
                  {osmLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
                  Tra cứu OSM
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

            {/* Bước 2: Thông số đoạn đường & góc nhìn camera */}
            <div className="space-y-3 p-3.5 rounded-xl border border-slate-200 bg-slate-50">
              <div className="flex items-center gap-2 text-xs font-bold text-slate-700 uppercase tracking-wide">
                <Route className="w-3.5 h-3.5 text-indigo-600" />
                <span>Bước 2 · Thông số đoạn đường & Tầm nhìn camera</span>
              </div>

              <div>
                <label className="block text-[10px] font-semibold text-slate-600 mb-1">Tên Node / Camera gán với MAC này *</label>
                <input
                  value={nodeName}
                  onChange={e => setNodeName(e.target.value)}
                  placeholder="Ví dụ: Camera Tố Hữu - Hướng Lê Văn Lương"
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-slate-300 bg-white focus:outline-none focus:border-blue-500 font-medium"
                />
              </div>

              <div>
                <label className="block text-[10px] font-semibold text-slate-600 mb-1">Tên tuyến đường *</label>
                <input
                  value={roadName}
                  onChange={e => setRoadName(e.target.value)}
                  placeholder="Ví dụ: Phố Tố Hữu"
                  className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-slate-300 bg-white focus:outline-none focus:border-blue-500 font-medium"
                />
              </div>

              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: "Số làn xe", val: laneCount, set: setLaneCount, step: 1, min: 1 },
                  { label: "Chiều dài đường (m)", val: roadLengthM, set: setRoadLengthM, step: 10, min: 10 },
                  { label: "Chiều rộng đường (m)", val: roadWidthM, set: setRoadWidthM, step: 0.5, min: 2 },
                  { label: "Tốc độ giới hạn (km/h)", val: speedLimit, set: setSpeedLimit, step: 10, min: 10 },
                  { label: "Hướng camera Heading (°)", val: cameraHeading, set: setCameraHeading, step: 5, min: 0 },
                  { label: "Góc quan sát FOV (°)", val: cameraFov, set: setCameraFov, step: 5, min: 20 },
                ].map(({ label, val, set, step, min }) => (
                  <div key={label}>
                    <label className="block text-[10px] font-semibold text-slate-600 mb-1">{label}</label>
                    <input
                      type="number" step={step} min={min} value={val}
                      onChange={e => set(parseFloat(e.target.value) || 0)}
                      className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-slate-300 bg-white focus:outline-none focus:border-blue-500 font-mono"
                    />
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
              {!editingNode && pendingNodes.length > 1 && (
                <button
                  type="button"
                  onClick={() => setStage("list")}
                  className="flex items-center gap-1.5 px-3 py-2 border border-slate-300 text-slate-700 hover:bg-slate-100 text-xs font-semibold rounded-xl transition"
                >
                  <ChevronLeft className="w-3.5 h-3.5" /> Danh sách chờ
                </button>
              )}
              {!editingNode && (
                <button
                  type="button"
                  onClick={() => handleReject(selectedNode.edge_id)}
                  className="flex items-center gap-1.5 px-3 py-2 border border-red-200 text-red-600 hover:bg-red-50 text-xs font-semibold rounded-xl transition"
                >
                  <XCircle className="w-3.5 h-3.5" /> Bỏ qua
                </button>
              )}
              <button
                type="button"
                onClick={handleSave}
                disabled={saving || !lat || !lng || !roadName.trim()}
                className="flex-1 flex items-center justify-center gap-2 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-40 text-white text-xs font-bold rounded-xl transition shadow-md shadow-emerald-500/20"
              >
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle className="w-3.5 h-3.5" />}
                {editingNode ? "Lưu cập nhật cấu hình" : "Lưu cấu hình & Kích hoạt lên WebGIS"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
