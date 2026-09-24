import React, { useState } from "react";
import { X, MapPin, Plus, Crosshair } from "lucide-react";
import { api } from "../../services/api";

interface AddNodeModalProps {
  onClose: () => void;
  onNodeAdded: () => void;
  pickedCoords: { lng: number; lat: number } | null;
  onEnablePickMode: () => void;
}

export const AddNodeModal: React.FC<AddNodeModalProps> = ({
  onClose,
  onNodeAdded,
  pickedCoords,
  onEnablePickMode
}) => {
  const [name, setName] = useState("");
  const [edgeId, setEdgeId] = useState("");
  const [segmentId, setSegmentId] = useState("segment-001");
  const [roadName, setRoadName] = useState("Đường Nguyễn Trãi");
  const [lat, setLat] = useState<number>(pickedCoords ? pickedCoords.lat : 20.9984);
  const [lng, setLng] = useState<number>(pickedCoords ? pickedCoords.lng : 105.7951);
  const [heading, setHeading] = useState<number>(45);
  const [fov, setFov] = useState<number>(65);
  const [saving, setSaving] = useState(false);

  // Synchronize when picked coordinates change from map click
  React.useEffect(() => {
    if (pickedCoords) {
      setLat(Number(pickedCoords.lat.toFixed(6)));
      setLng(Number(pickedCoords.lng.toFixed(6)));
    }
  }, [pickedCoords]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name) return alert("Vui lòng nhập tên trạm camera");
    setSaving(true);
    try {
      await api.createNode({
        edge_id: edgeId || undefined,
        name,
        segment_id: segmentId,
        road_name: roadName,
        latitude: lat,
        longitude: lng,
        camera_heading: heading,
        camera_fov: fov,
        altitude_m: 12.0
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
      <div className="w-full max-w-lg rounded-2xl bg-white text-slate-800 shadow-2xl border border-slate-200 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-100 bg-slate-50/80">
          <div className="flex items-center space-x-2">
            <div className="p-2 rounded-lg bg-blue-50 text-blue-600 border border-blue-100">
              <Plus className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-900">Thêm Trạm Camera Mới Lên Bản Đồ</h2>
              <p className="text-[11px] text-slate-500">Đăng ký thiết bị biên và gán vào tuyến đường</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded text-slate-400 hover:text-slate-700 transition">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4 text-xs">
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
                onChange={(e) => {
                  setSegmentId(e.target.value);
                  if (e.target.value === "segment-001") setRoadName("Đường Nguyễn Trãi");
                  if (e.target.value === "segment-002") setRoadName("Đường Khuất Duy Tiến");
                  if (e.target.value === "segment-003") setRoadName("Đường Lê Văn Lương");
                }}
                className="w-full px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 focus:outline-none focus:border-blue-500 focus:bg-white transition"
              >
                <option value="segment-001">segment-001 (Đường Nguyễn Trãi)</option>
                <option value="segment-002">segment-002 (Đường Khuất Duy Tiến)</option>
                <option value="segment-003">segment-003 (Đường Lê Văn Lương)</option>
              </select>
            </div>
          </div>

          {/* Location Coordinates & Pick on Map Button */}
          <div className="p-3.5 rounded-xl bg-slate-50/80 border border-slate-200 space-y-2.5">
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
          </div>

          {/* Heading & FOV Sliders */}
          <div className="grid grid-cols-2 gap-4 p-3.5 rounded-xl bg-slate-50/80 border border-slate-200">
            <div>
              <div className="flex justify-between font-semibold text-slate-700 mb-1">
                <span>Hướng xoay Camera</span>
                <span className="text-blue-600 font-mono font-bold">{heading}°</span>
              </div>
              <input
                type="range"
                min={0}
                max={360}
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
                type="range"
                min={30}
                max={120}
                value={fov}
                onChange={(e) => setFov(Number(e.target.value))}
                className="w-full accent-indigo-600 cursor-pointer"
              />
            </div>
          </div>

          {/* Submit */}
          <div className="pt-2 flex items-center justify-end space-x-2">
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
