import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { User, Mail, Shield, CheckCircle, AlertCircle, ArrowLeft, Loader2, KeyRound } from "lucide-react";

export const ProfilePage: React.FC = () => {
  const { user, updateProfile } = useAuth();

  const [name, setName] = useState(user?.name || "");
  const [email, setEmail] = useState(user?.email || "");

  // Đổi mật khẩu state
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");

  const [infoMessage, setInfoMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [pwMessage, setPwMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const [isUpdatingInfo, setIsUpdatingInfo] = useState(false);
  const [isUpdatingPw, setIsUpdatingPw] = useState(false);

  if (!user) return null;

  // Xử lý đổi tên / email
  const handleUpdateInfo = async (e: React.FormEvent) => {
    e.preventDefault();
    setInfoMessage(null);

    try {
      setIsUpdatingInfo(true);
      await updateProfile({ name: name.trim(), email: email.trim() });
      setInfoMessage({ type: "success", text: "Cập nhật thông tin cá nhân thành công!" });
    } catch (err: any) {
      setInfoMessage({
        type: "error",
        text: err.response?.data?.message || "Cập nhật thông tin thất bại.",
      });
    } finally {
      setIsUpdatingInfo(false);
    }
  };

  // Xử lý đổi mật khẩu
  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwMessage(null);

    if (!currentPassword) {
      setPwMessage({ type: "error", text: "Vui lòng nhập mật khẩu hiện tại." });
      return;
    }

    if (newPassword.length < 8) {
      setPwMessage({ type: "error", text: "Mật khẩu mới phải có tối thiểu 8 ký tự." });
      return;
    }

    if (newPassword !== confirmNewPassword) {
      setPwMessage({ type: "error", text: "Mật khẩu xác nhận không khớp." });
      return;
    }

    try {
      setIsUpdatingPw(true);
      await updateProfile({ currentPassword, newPassword });
      setPwMessage({ type: "success", text: "Đổi mật khẩu thành công!" });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmNewPassword("");
    } catch (err: any) {
      setPwMessage({
        type: "error",
        text: err.response?.data?.message || "Đổi mật khẩu thất bại. Vui lòng kiểm tra lại mật khẩu hiện tại.",
      });
    } finally {
      setIsUpdatingPw(false);
    }
  };

  const getRoleBadge = () => {
    if (user.role === "ADMIN") {
      return (
        <span className="px-3 py-1 rounded-full text-xs font-bold bg-red-500/20 text-red-300 border border-red-500/30 flex items-center gap-1.5">
          <Shield className="w-3.5 h-3.5 text-red-400" /> Quản Trị Viên Tối Cao (ADMIN)
        </span>
      );
    }
    if (user.role === "MANAGER") {
      return (
        <span className="px-3 py-1 rounded-full text-xs font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 flex items-center gap-1.5">
          <Shield className="w-3.5 h-3.5 text-amber-400" /> Quản Lý Vận Hành (MANAGER)
        </span>
      );
    }
    return (
      <span className="px-3 py-1 rounded-full text-xs font-bold bg-blue-500/20 text-blue-300 border border-blue-500/30 flex items-center gap-1.5">
        <User className="w-3.5 h-3.5 text-blue-400" /> Người Dùng Hệ Thống (USER)
      </span>
    );
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 sm:p-8">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Top bar */}
        <div className="flex items-center justify-between">
          <Link
            to="/"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 text-xs font-semibold border border-slate-800 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Về Bản Đồ GIS
          </Link>
          {getRoleBadge()}
        </div>

        {/* Header Profile Card */}
        <div className="p-6 sm:p-8 rounded-3xl bg-slate-900 border border-slate-800 shadow-xl flex flex-col sm:flex-row items-center gap-6">
          <div className="w-20 h-20 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center text-3xl font-bold text-white shadow-lg shadow-blue-500/20">
            {user.name.charAt(0).toUpperCase()}
          </div>
          <div className="text-center sm:text-left space-y-1">
            <h1 className="text-2xl font-bold text-white">{user.name}</h1>
            <p className="text-sm text-slate-400 flex items-center justify-center sm:justify-start gap-1.5">
              <Mail className="w-4 h-4 text-slate-500" /> {user.email}
            </p>
            {user.createdAt && (
              <p className="text-xs text-slate-500">
                Thành viên từ: {new Date(user.createdAt).toLocaleDateString("vi-VN")}
              </p>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Card 1: Thông tin cơ bản */}
          <div className="p-6 rounded-3xl bg-slate-900 border border-slate-800 shadow-xl space-y-5">
            <div className="flex items-center gap-2.5 pb-3 border-b border-slate-800">
              <User className="w-5 h-5 text-blue-400" />
              <h2 className="text-base font-bold text-white">Cập Nhật Thông Tin Cá Nhân</h2>
            </div>

            {infoMessage && (
              <div
                className={`p-3 rounded-xl text-xs flex items-center gap-2 ${
                  infoMessage.type === "success"
                    ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                    : "bg-red-500/10 text-red-400 border border-red-500/20"
                }`}
              >
                {infoMessage.type === "success" ? <CheckCircle className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
                <span>{infoMessage.text}</span>
              </div>
            )}

            <form onSubmit={handleUpdateInfo} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1.5">Họ và tên</label>
                <input
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800/80 border border-slate-700 text-sm text-slate-100 focus:border-blue-500 outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1.5">Email</label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800/80 border border-slate-700 text-sm text-slate-100 focus:border-blue-500 outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1.5">Vai trò (Role)</label>
                <input
                  type="text"
                  disabled
                  value={user.role}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800/40 border border-slate-800 text-sm text-slate-500 cursor-not-allowed"
                />
                <p className="text-[10px] text-slate-500 mt-1">Vai trò được quản lý tập trung bởi Hệ thống.</p>
              </div>

              <button
                type="submit"
                disabled={isUpdatingInfo}
                className="w-full py-2.5 px-4 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs transition-colors flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
              >
                {isUpdatingInfo ? <Loader2 className="w-4 h-4 animate-spin" /> : "Lưu Thay Đổi"}
              </button>
            </form>
          </div>

          {/* Card 2: Đổi mật khẩu */}
          <div className="p-6 rounded-3xl bg-slate-900 border border-slate-800 shadow-xl space-y-5">
            <div className="flex items-center gap-2.5 pb-3 border-b border-slate-800">
              <KeyRound className="w-5 h-5 text-indigo-400" />
              <h2 className="text-base font-bold text-white">Đổi Mật Khẩu</h2>
            </div>

            {pwMessage && (
              <div
                className={`p-3 rounded-xl text-xs flex items-center gap-2 ${
                  pwMessage.type === "success"
                    ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                    : "bg-red-500/10 text-red-400 border border-red-500/20"
                }`}
              >
                {pwMessage.type === "success" ? <CheckCircle className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
                <span>{pwMessage.text}</span>
              </div>
            )}

            <form onSubmit={handleChangePassword} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1.5">Mật khẩu hiện tại</label>
                <input
                  type="password"
                  required
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800/80 border border-slate-700 text-sm text-slate-100 focus:border-indigo-500 outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1.5">Mật khẩu mới (tối thiểu 8 ký tự)</label>
                <input
                  type="password"
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800/80 border border-slate-700 text-sm text-slate-100 focus:border-indigo-500 outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1.5">Xác nhận mật khẩu mới</label>
                <input
                  type="password"
                  required
                  value={confirmNewPassword}
                  onChange={(e) => setConfirmNewPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-800/80 border border-slate-700 text-sm text-slate-100 focus:border-indigo-500 outline-none"
                />
              </div>

              <button
                type="submit"
                disabled={isUpdatingPw}
                className="w-full py-2.5 px-4 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs transition-colors flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
              >
                {isUpdatingPw ? <Loader2 className="w-4 h-4 animate-spin" /> : "Cập Nhật Mật Khẩu"}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
};
