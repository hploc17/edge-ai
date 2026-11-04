import React, { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import { authApi } from "../services/authApi";
import type { User, ManagerPagination } from "../types/auth";
import {
  Users,
  UserPlus,
  Search,
  Edit2,
  Trash2,
  Shield,
  ArrowLeft,
  Loader2,
  AlertCircle,
  CheckCircle,
  X,
  RefreshCw,
} from "lucide-react";

export const ManagerManagementPage: React.FC = () => {
  const [managers, setManagers] = useState<User[]>([]);
  const [pagination, setPagination] = useState<ManagerPagination>({ total: 0, page: 1, limit: 10, totalPages: 1 });
  const [search, setSearch] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  // Modal states
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [editingManager, setEditingManager] = useState<User | null>(null);
  const [deletingManager, setDeletingManager] = useState<User | null>(null);

  // Form states
  const [formData, setFormData] = useState({ name: "", email: "", password: "" });
  const [modalError, setModalError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Global alert
  const [bannerAlert, setBannerAlert] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const fetchManagers = useCallback(async (page = 1, searchQuery = "") => {
    try {
      setIsLoading(true);
      const data = await authApi.getManagers({ page, limit: 10, search: searchQuery });
      setManagers(data.managers);
      setPagination(data.pagination);
    } catch (err: any) {
      setBannerAlert({
        type: "error",
        text: err.response?.data?.message || "Không thể tải danh sách tài khoản Manager.",
      });
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchManagers(1, search);
  }, [fetchManagers]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchManagers(1, search);
  };

  // Mở modal thêm mới
  const handleOpenAdd = () => {
    setFormData({ name: "", email: "", password: "" });
    setModalError("");
    setIsAddModalOpen(true);
  };

  // Mở modal sửa
  const handleOpenEdit = (m: User) => {
    setEditingManager(m);
    setFormData({ name: m.name, email: m.email, password: "" });
    setModalError("");
  };

  // Submit thêm mới
  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setModalError("");

    if (!formData.name.trim() || !formData.email.trim() || !formData.password) {
      setModalError("Vui lòng điền đầy đủ Họ tên, Email và Mật khẩu");
      return;
    }

    if (formData.password.length < 8) {
      setModalError("Mật khẩu phải có độ dài tối thiểu 8 ký tự");
      return;
    }

    try {
      setIsSubmitting(true);
      await authApi.createManager(formData);
      setIsAddModalOpen(false);
      setBannerAlert({ type: "success", text: `Đã tạo tài khoản Manager (${formData.email}) thành công!` });
      fetchManagers(pagination.page, search);
    } catch (err: any) {
      setModalError(err.response?.data?.message || "Không thể tạo tài khoản Manager.");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Submit sửa
  const handleUpdateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingManager) return;
    setModalError("");

    try {
      setIsSubmitting(true);
      const payload: any = { name: formData.name.trim(), email: formData.email.trim() };
      if (formData.password) {
        if (formData.password.length < 8) {
          setModalError("Mật khẩu đặt lại phải từ 8 ký tự trở lên");
          setIsSubmitting(false);
          return;
        }
        payload.password = formData.password;
      }

      await authApi.updateManager(editingManager.id, payload);
      setEditingManager(null);
      setBannerAlert({ type: "success", text: `Đã cập nhật tài khoản (${editingManager.email}) thành công!` });
      fetchManagers(pagination.page, search);
    } catch (err: any) {
      setModalError(err.response?.data?.message || "Không thể cập nhật tài khoản Manager.");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Submit xóa
  const handleDeleteConfirm = async () => {
    if (!deletingManager) return;

    try {
      setIsSubmitting(true);
      await authApi.deleteManager(deletingManager.id);
      setBannerAlert({ type: "success", text: `Đã xóa tài khoản Manager (${deletingManager.email}) thành công.` });
      setDeletingManager(null);
      fetchManagers(pagination.page, search);
    } catch (err: any) {
      setBannerAlert({
        type: "error",
        text: err.response?.data?.message || "Không thể xóa tài khoản Manager này.",
      });
      setDeletingManager(null);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 sm:p-8">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Top bar */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Link
              to="/"
              className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 text-xs font-semibold border border-slate-800 transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              Về Bản Đồ
            </Link>
            <div>
              <h1 className="text-xl sm:text-2xl font-bold text-white flex items-center gap-2.5">
                <Users className="w-6 h-6 text-amber-400" />
                Quản Lý Tài Khoản Manager
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Khu vực dành riêng cho Quản Trị Viên Tối Cao (ADMIN) cấp phát và phân quyền
              </p>
            </div>
          </div>

          <button
            onClick={handleOpenAdd}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-400 hover:to-orange-500 text-slate-950 font-bold text-xs shadow-lg shadow-amber-500/20 transition-all cursor-pointer"
          >
            <UserPlus className="w-4 h-4" />
            Thêm Manager Mới
          </button>
        </div>

        {/* Global Banner Alert */}
        {bannerAlert && (
          <div
            className={`p-4 rounded-2xl text-xs flex items-center justify-between gap-3 animate-fadeIn ${
              bannerAlert.type === "success"
                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                : "bg-red-500/10 text-red-400 border border-red-500/20"
            }`}
          >
            <div className="flex items-center gap-2.5">
              {bannerAlert.type === "success" ? <CheckCircle className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
              <span>{bannerAlert.text}</span>
            </div>
            <button onClick={() => setBannerAlert(null)} className="text-slate-400 hover:text-slate-200">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Search & Actions Bar */}
        <div className="p-4 rounded-2xl bg-slate-900 border border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-3">
          <form onSubmit={handleSearchSubmit} className="w-full sm:w-80 relative">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Tìm theo tên hoặc email..."
              className="w-full pl-9 pr-4 py-2 rounded-xl bg-slate-800/80 border border-slate-700 text-xs text-slate-100 placeholder-slate-500 focus:border-amber-500 outline-none"
            />
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5 pointer-events-none" />
          </form>

          <button
            onClick={() => fetchManagers(pagination.page, search)}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            Làm mới
          </button>
        </div>

        {/* Managers Table */}
        <div className="rounded-2xl bg-slate-900 border border-slate-800 overflow-hidden shadow-xl">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-800/60 text-slate-400 uppercase tracking-wider font-semibold border-b border-slate-800">
                <tr>
                  <th className="py-3.5 px-4">Tài Khoản</th>
                  <th className="py-3.5 px-4">Email</th>
                  <th className="py-3.5 px-4">Vai Trò</th>
                  <th className="py-3.5 px-4">Ngày Tạo</th>
                  <th className="py-3.5 px-4 text-right">Thao Tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {isLoading ? (
                  <tr>
                    <td colSpan={5} className="py-12 text-center text-slate-400">
                      <Loader2 className="w-6 h-6 animate-spin mx-auto text-amber-500 mb-2" />
                      Đang tải danh sách tài khoản...
                    </td>
                  </tr>
                ) : managers.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-12 text-center text-slate-500">
                      Không tìm thấy tài khoản Manager nào.
                    </td>
                  </tr>
                ) : (
                  managers.map((m) => (
                    <tr key={m.id} className="hover:bg-slate-800/30 transition-colors">
                      <td className="py-3.5 px-4 font-semibold text-white flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-amber-500/20 border border-amber-500/30 text-amber-300 flex items-center justify-center font-bold text-xs">
                          {m.name.charAt(0).toUpperCase()}
                        </div>
                        {m.name}
                      </td>
                      <td className="py-3.5 px-4 text-slate-300">{m.email}</td>
                      <td className="py-3.5 px-4">
                        <span className="px-2.5 py-1 rounded-full text-[11px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20 inline-flex items-center gap-1">
                          <Shield className="w-3 h-3" /> MANAGER
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-slate-400">
                        {m.createdAt ? new Date(m.createdAt).toLocaleDateString("vi-VN") : "—"}
                      </td>
                      <td className="py-3.5 px-4 text-right space-x-2">
                        <button
                          onClick={() => handleOpenEdit(m)}
                          className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors cursor-pointer"
                          title="Sửa thông tin / Đổi mật khẩu"
                        >
                          <Edit2 className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => setDeletingManager(m)}
                          className="p-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400 hover:text-red-300 transition-colors cursor-pointer"
                          title="Xóa tài khoản"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {pagination.totalPages > 1 && (
            <div className="p-4 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
              <span>
                Tổng số {pagination.total} tài khoản (Trang {pagination.page} / {pagination.totalPages})
              </span>
              <div className="flex gap-1.5">
                <button
                  disabled={pagination.page <= 1}
                  onClick={() => fetchManagers(pagination.page - 1, search)}
                  className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Trang trước
                </button>
                <button
                  disabled={pagination.page >= pagination.totalPages}
                  onClick={() => fetchManagers(pagination.page + 1, search)}
                  className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Trang sau
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Modal Thêm Manager ──────────────────────────────────────────────── */}
      {isAddModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-2xl relative">
            <button
              onClick={() => setIsAddModalOpen(false)}
              className="absolute top-5 right-5 text-slate-400 hover:text-white"
            >
              <X className="w-5 h-5" />
            </button>
            <h2 className="text-lg font-bold text-white mb-1 flex items-center gap-2">
              <UserPlus className="w-5 h-5 text-amber-400" /> Tạo Tài Khoản Manager Mới
            </h2>
            <p className="text-xs text-slate-400 mb-5">
              Tài khoản này sẽ có toàn quyền điều khiển trạm Jetson, cấu hình ROI, bật CSI và quản lý node.
            </p>

            {modalError && (
              <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{modalError}</span>
              </div>
            )}

            <form onSubmit={handleCreateSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Họ và tên</label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="Quản lý khu vực A"
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-sm text-slate-100 focus:border-amber-500 outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Email</label>
                <input
                  type="email"
                  required
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  placeholder="manager@traffic.gis.local"
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-sm text-slate-100 focus:border-amber-500 outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Mật khẩu (tối thiểu 8 ký tự)</label>
                <input
                  type="password"
                  required
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  placeholder="••••••••"
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-sm text-slate-100 focus:border-amber-500 outline-none"
                />
              </div>

              <div className="pt-2 flex gap-3">
                <button
                  type="button"
                  onClick={() => setIsAddModalOpen(false)}
                  className="flex-1 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold cursor-pointer"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex-1 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs flex items-center justify-center gap-1.5 cursor-pointer disabled:opacity-50"
                >
                  {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : "Tạo Manager"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Modal Sửa Manager ────────────────────────────────────────────────── */}
      {editingManager && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-2xl relative">
            <button
              onClick={() => setEditingManager(null)}
              className="absolute top-5 right-5 text-slate-400 hover:text-white"
            >
              <X className="w-5 h-5" />
            </button>
            <h2 className="text-lg font-bold text-white mb-1 flex items-center gap-2">
              <Edit2 className="w-5 h-5 text-blue-400" /> Sửa Thông Tin Manager
            </h2>
            <p className="text-xs text-slate-400 mb-5">
              Cập nhật thông tin hoặc đặt lại mật khẩu cho tài khoản ({editingManager.email})
            </p>

            {modalError && (
              <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{modalError}</span>
              </div>
            )}

            <form onSubmit={handleUpdateSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Họ và tên</label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-sm text-slate-100 focus:border-blue-500 outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Email</label>
                <input
                  type="email"
                  required
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-sm text-slate-100 focus:border-blue-500 outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Mật khẩu mới (bỏ trống nếu không muốn đổi)
                </label>
                <input
                  type="password"
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  placeholder="Để trống nếu giữ nguyên"
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-sm text-slate-100 focus:border-blue-500 outline-none"
                />
              </div>

              <div className="pt-2 flex gap-3">
                <button
                  type="button"
                  onClick={() => setEditingManager(null)}
                  className="flex-1 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold cursor-pointer"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex-1 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs flex items-center justify-center gap-1.5 cursor-pointer disabled:opacity-50"
                >
                  {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : "Lưu Thay Đổi"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Modal Xác Nhận Xóa Manager ──────────────────────────────────────── */}
      {deletingManager && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
          <div className="w-full max-w-sm bg-slate-900 border border-red-500/30 rounded-3xl p-6 shadow-2xl text-center">
            <div className="w-14 h-14 rounded-2xl bg-red-500/10 border border-red-500/20 text-red-400 flex items-center justify-center mx-auto mb-4">
              <Trash2 className="w-7 h-7" />
            </div>
            <h3 className="text-base font-bold text-white mb-2">Xác Nhận Xóa Tài Khoản?</h3>
            <p className="text-xs text-slate-400 mb-6">
              Bạn có chắc chắn muốn xóa tài khoản Manager <span className="font-semibold text-red-400">{deletingManager.name} ({deletingManager.email})</span>? Thao tác này không thể hoàn tác!
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setDeletingManager(null)}
                className="flex-1 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold cursor-pointer"
              >
                Hủy
              </button>
              <button
                onClick={handleDeleteConfirm}
                disabled={isSubmitting}
                className="flex-1 py-2.5 rounded-xl bg-red-600 hover:bg-red-500 text-white font-bold text-xs flex items-center justify-center gap-1.5 cursor-pointer disabled:opacity-50"
              >
                {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : "Xác Nhận Xóa"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
