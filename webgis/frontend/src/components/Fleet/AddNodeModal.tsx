import React, { useState, useCallback, useEffect } from "react";
import { X, MapPin, Plus, Crosshair, Search, CheckCircle, AlertTriangle, Loader2, Route, ChevronDown, ChevronUp } from "lucide-react";
import { api } from "../../services/api";
import type { OSMRoadInfo } from "../../types/gis";

interface AddNodeModalProps {
  onClose: () => void;
  onNodeAdded: () => void;
  pickedCoords: { lng: number; lat: number } | null;
  onEnablePickMode: () => void;
}

const ROAD_TYPE_LABEL: Record<string, string> = {
  motorway: "Đường cao tốc", trunk: "Quốc lộ chính",
  primary: "Đường phố chính", secondary: "Đường phố cấp 2",
  tertiary: "Đường phố cấp 3", residential: "Đường dân sinh",
  unclassified: "Đường không phân loại",
};

export const AddNodeModal: React.FC<AddNodeModalProps> = ({
  onClose,
  onNodeAdded,
  pickedCoords,
  onEnablePickMode
}) => {
  const [name, setName] = useState("");
  const [edgeId, setEdgeId] = useState("");
  const [segmentId, setSegmentId] = useState("segment-001");
  const [roadName, setRoadName] = useState("");
  const [lat, setLat] = useState<number>(pickedCoords ? pickedCoords.lat : 20.9984);
  const [lng, setLng] = useState<number>(pickedCoords ? pickedCoords.lng : 105.7951);
  const [heading, setHeading] = useState<number>(45);
  const [fov, setFov] = useState<number>(65);
  const [saving, setSaving] = useState(false);

  // OSM Road Lookup state
  const [osmInfo, setOsmInfo] = useState<OSMRoadInfo | null>(null);
  const [osmLoading, setOsmLoading] = useState(false);
  const [osmError, setOsmError] = useState<string | null>(null);
  const [osmApplied, setOsmApplied] = useState(false);
  const [showOsmDetail, setShowOsmDetail] = useState(false);

  // Road dimension state (có thể được điền từ OSM hoặc nhập tay)
  const [laneCount, setLaneCount] = useState<number>(4);
  const [roadLengthM, setRoadLengthM] = useState<number>(450);
  const [roadWidthM, setRoadWidthM] = useState<number>(16);
  const [speedLimitKmh, setSpeedLimitKmh] = useState<number>(60);

  // Synchronize when picked coordinates change from map click
  useEffect(() => {
    if (pickedCoords) {
      const newLat = Number(pickedCoords.lat.toFixed(6));
      const newLng = Number(pickedCoords.lng.toFixed(6));
      setLat(newLat);
      setLng(newLng);
      // Tự động tra cứu OSM khi click chọn điểm trên bản đồ
      handleOSMLookup(newLat, newLng);
    }
  }, [pickedCoords]);

  const handleOSMLookup = useCallback(async (lookupLat?: number, lookupLng?: number) => {
    const queryLat = lookupLat ?? lat;
    const queryLng = lookupLng ?? lng;

    if (!queryLat || !queryLng) return;
    setOsmLoading(true);
    setOsmError(null);
    setOsmApplied(false);

    try {
      const info = await api.fetchOSMRoadInfo(queryLat, queryLng);
      setOsmInfo(info);
      if (info.found) {
        // Tự động áp dụng dữ liệu OSM vào form
        if (info.road_name && info.road_name !== "Chưa có tên") {
          setRoadName(info.road_name);
          if (!name) setName(`Camera ${info.road_name}`);
        }
        if (info.lanes) setLaneCount(info.lanes);
        if (info.road_length_m) setRoadLengthM(Math.round(info.road_length_m));
        if (info.road_width_m) setRoadWidthM(info.road_width_m);
        if (info.speed_limit_kmh) setSpeedLimitKmh(info.speed_limit_kmh);
        setOsmApplied(true);
        setShowOsmDetail(true);
      } else {
        setOsmError(info.message || "Không tìm thấy dữ liệu đoạn đường.");
      }
    } catch (err: any) {
      setOsmError("Không thể kết nối OpenStreetMap. Kiểm tra kết nối Internet.");
    } finally {
      setOsmLoading(false);
    }
  }, [lat, lng, name]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name) return alert("Vui lòng nhập tên trạm camera");
    setSaving(true);
    try {
      await api.createNode({
        edge_id: edgeId || undefined,
        name,
        segment_id: segmentId,
        road_name: roadName || "Đường chưa xác định",
        latitude: lat,
        longitude: lng,
        camera_heading: heading,
        camera_fov: fov,
        altitude_m: 12.0,
        // Thông số đường (từ OSM hoặc nhập tay)
        lane_count: laneCount,
        road_length_m: roadLengthM,
        road_width_m: roadWidthM,
        speed_limit_kmh: speedLimitKmh,
        // Metadata OSM
        osm_way_id: osmInfo?.osm_way_id,
        osm_road_type: osmInfo?.road_type,
        osm_road_name: osmInfo?.road_name,
      });
      onNodeAdded();
      onClose();
    } catch (err) {
      console.error("Failed to create node:", err);
      alert("Lỗi khi thêm trạm camera");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-xl rounded-2xl bg-white text-slate-800 shadow-2xl border border-slate-200 overflow-hidden max-h-[92vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-100 bg-slate-50/80 shrink-0">
          <div className="flex items-center space-x-2">
            <div className="p-2 rounded-lg bg-blue-50 text-blue-600 border border-blue-100">
              <Plus className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-900">Thêm Trạm Camera Mới Lên Bản Đồ</h2>
              <p className="text-[11px] text-slate-500">Đăng ký thiết bị biên — Thông số đường tự động từ OpenStreetMap</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded text-slate-400 hover:text-slate-700 transition">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form - scrollable */}
        <form onSubmit={handleSubmit} className="overflow-y-auto flex-1 p-5 space-y-4 text-xs">
          {/* Tên trạm */}
          <div>
            <label className="block text-slate-700 font-semibold mb-1">Tên Trạm Camera / Vị trí *</label>
            <input
              type="text"
              required
              placeholder="VD: Camera Nút giao Giải Phóng - Trường Chinh"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 focus:outline-none focus:border-blue-500 focus:bg-white transition"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-slate-700 font-semibold mb-1">Mã Edge ID (Tùy chọn)</label>
              <input
                type="text"
                placeholder="Tự động sinh nếu để trống"
                value={edgeId}
                onChange={(e) => setEdgeId(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 font-mono focus:outline-none focus:border-blue-500 focus:bg-white transition"
              />
            </div>
            <div>
              <label className="block text-slate-700 font-semibold mb-1">Tuyến đường liên kết</label>
              <select
                value={segmentId}
                onChange={(e) => setSegmentId(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 focus:outline-none focus:border-blue-500 focus:bg-white transition"
              >
                <option value="segment-001">segment-001 (Đường Nguyễn Trãi)</option>
                <option value="segment-002">segment-002 (Đường Khuất Duy Tiến)</option>
                <option value="segment-003">segment-003 (Đường Lê Văn Lương)</option>
              </select>
            </div>
          </div>

          {/* Tọa độ + OSM Lookup */}
          <div className="p-3.5 rounded-xl bg-slate-50/80 border border-slate-200 space-y-3">
            <div className="flex items-center justify-between">
              <span className="font-bold text-slate-800 flex items-center gap-1.5">
                <MapPin className="w-4 h-4 text-emerald-600" />
                Tọa độ Địa lý (WGS84)
              </span>
              <button
                type="button"
                onClick={onEnablePickMode}
                className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 text-emerald-700 text-[11px] font-bold transition shadow-sm"
              >
                <Crosshair className="w-3.5 h-3.5" />
                <span>Click chọn trên bản đồ</span>
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-slate-500 mb-0.5 font-medium">Vĩ độ (Latitude)</label>
                <input
                  type="number"
                  step="any"
                  required
                  value={lat}
                  onChange={(e) => setLat(Number(e.target.value))}
                  className="w-full px-3 py-1.5 rounded-lg bg-white border border-slate-200 text-blue-700 font-mono font-bold"
                />
              </div>
              <div>
                <label className="block text-slate-500 mb-0.5 font-medium">Kinh độ (Longitude)</label>
                <input
                  type="number"
                  step="any"
                  required
                  value={lng}
                  onChange={(e) => setLng(Number(e.target.value))}
                  className="w-full px-3 py-1.5 rounded-lg bg-white border border-slate-200 text-blue-700 font-mono font-bold"
                />
              </div>
            </div>

            {/* Nút tra cứu OSM thủ công */}
            <button
              type="button"
              disabled={osmLoading}
              onClick={() => handleOSMLookup()}
              className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-[11px] font-bold transition shadow-sm"
            >
              {osmLoading ? (
                <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Đang tra cứu OpenStreetMap...</>
              ) : (
                <><Search className="w-3.5 h-3.5" /> 🗺️ Tra cứu thông số đường từ OpenStreetMap</>
              )}
            </button>

            {/* OSM Result Banner */}
            {osmApplied && osmInfo?.found && (
              <div
                className="rounded-lg border border-emerald-200 bg-emerald-50 p-2.5 cursor-pointer"
                onClick={() => setShowOsmDetail(!showOsmDetail)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <CheckCircle className="w-4 h-4 text-emerald-600 shrink-0" />
                    <div>
                      <p className="font-bold text-emerald-800 text-[11px]">{osmInfo.road_name}</p>
                      <p className="text-[10px] text-emerald-600">
                        {ROAD_TYPE_LABEL[osmInfo.road_type || ""] || osmInfo.road_type} •{" "}
                        {osmInfo.lanes} làn • {osmInfo.speed_limit_kmh} km/h •{" "}
                        {osmInfo.road_length_m ? `${osmInfo.road_length_m} m` : "?"}
                        {osmInfo.width_estimated && " (chiều rộng ước tính TCVN)"}
                      </p>
                    </div>
                  </div>
                  {showOsmDetail ? <ChevronUp className="w-3.5 h-3.5 text-emerald-600" /> : <ChevronDown className="w-3.5 h-3.5 text-emerald-600" />}
                </div>
                {showOsmDetail && (
                  <div className="mt-2 pt-2 border-t border-emerald-200 grid grid-cols-2 gap-1 text-[10px]">
                    <span className="text-emerald-700"><b>OSM Way ID:</b> #{osmInfo.osm_way_id}</span>
                    <span className="text-emerald-700"><b>Mặt đường:</b> {osmInfo.surface || "Không có dữ liệu"}</span>
                    <span className="text-emerald-700"><b>Chiều rộng:</b> {osmInfo.road_width_m}m {osmInfo.width_estimated ? "(ước tính)" : "(OSM)"}</span>
                    <span className="text-emerald-700"><b>Một chiều:</b> {osmInfo.oneway ? "✅ Có" : "❌ Không"}</span>
                  </div>
                )}
              </div>
            )}

            {osmError && !osmLoading && (
              <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5">
                <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
                <p className="text-[11px] text-amber-800">{osmError}</p>
              </div>
            )}
          </div>

          {/* Thông số đường (có thể chỉnh sửa sau khi OSM fill) */}
          <div className="p-3.5 rounded-xl bg-slate-50/80 border border-slate-200 space-y-3">
            <div className="flex items-center gap-1.5 font-bold text-slate-800">
            <Route className="w-4 h-4 text-indigo-600" />
              Thông số Tuyến đường Thực tế
              {osmApplied && (
                <span className="ml-auto text-[10px] text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 font-semibold">
                  🗺️ Đã điền từ OSM
                </span>
              )}
            </div>

            <div>
              <label className="block text-slate-500 mb-0.5 font-medium">Tên đường chính thức</label>
              <input
                type="text"
                placeholder="VD: Đường Nguyễn Trãi"
                value={roadName}
                onChange={(e) => setRoadName(e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg bg-white border border-slate-200 text-slate-800 focus:outline-none focus:border-blue-500 transition"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-slate-500 mb-0.5 font-medium">Số làn xe</label>
                <input
                  type="number"
                  min={1} max={12} step={1}
                  value={laneCount}
                  onChange={(e) => setLaneCount(Number(e.target.value))}
                  className="w-full px-3 py-1.5 rounded-lg bg-white border border-slate-200 text-slate-800 font-mono font-bold focus:outline-none focus:border-blue-500 transition"
                />
              </div>
              <div>
                <label className="block text-slate-500 mb-0.5 font-medium">Tốc độ giới hạn (km/h)</label>
                <input
                  type="number"
                  min={10} max={130} step={5}
                  value={speedLimitKmh}
                  onChange={(e) => setSpeedLimitKmh(Number(e.target.value))}
                  className="w-full px-3 py-1.5 rounded-lg bg-white border border-slate-200 text-slate-800 font-mono font-bold focus:outline-none focus:border-blue-500 transition"
                />
              </div>
              <div>
                <label className="block text-slate-500 mb-0.5 font-medium">Chiều dài đoạn (m)</label>
                <input
                  type="number"
                  min={1} step={1}
                  value={roadLengthM}
                  onChange={(e) => setRoadLengthM(Number(e.target.value))}
                  className="w-full px-3 py-1.5 rounded-lg bg-white border border-slate-200 text-slate-800 font-mono font-bold focus:outline-none focus:border-blue-500 transition"
                />
              </div>
              <div>
                <label className="block text-slate-500 mb-0.5 font-medium">
                  Chiều rộng (m)
                  {osmInfo?.width_estimated && (
                    <span className="ml-1 text-amber-600 font-normal">(ước tính)</span>
                  )}
                </label>
                <input
                  type="number"
                  min={1} step={0.5}
                  value={roadWidthM}
                  onChange={(e) => setRoadWidthM(Number(e.target.value))}
                  className="w-full px-3 py-1.5 rounded-lg bg-white border border-slate-200 text-slate-800 font-mono font-bold focus:outline-none focus:border-blue-500 transition"
                />
              </div>
            </div>
          </div>

          {/* Heading & FOV Sliders */}
          <div className="grid grid-cols-2 gap-4 p-3.5 rounded-xl bg-slate-50/80 border border-slate-200">
            <div>
              <div className="flex justify-between font-semibold text-slate-700 mb-1">
                <span>Hướng xoay Camera</span>
                <span className="text-blue-600 font-mono font-bold">{heading}°</span>
              </div>
              <input
                type="range" min={0} max={360}
                value={heading}
                onChange={(e) => setHeading(Number(e.target.value))}
                className="w-full accent-blue-600 cursor-pointer"
              />
            </div>
            <div>
              <div className="flex justify-between font-semibold text-slate-700 mb-1">
                <span>Góc mở ống kính (FOV)</span>
                <span className="text-indigo-600 font-mono font-bold">{fov}°</span>
              </div>
              <input
                type="range" min={30} max={120}
                value={fov}
                onChange={(e) => setFov(Number(e.target.value))}
                className="w-full accent-indigo-600 cursor-pointer"
              />
            </div>
          </div>

          {/* Submit */}
          <div className="pt-1 flex items-center justify-end space-x-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold transition"
            >
              Hủy bỏ
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-5 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-bold transition shadow-md shadow-blue-500/20"
            >
              {saving ? "Đang lưu..." : "Xác nhận thêm Node"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
