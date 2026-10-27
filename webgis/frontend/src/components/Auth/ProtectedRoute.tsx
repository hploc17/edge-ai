import React from "react";
import { Navigate, useLocation, Link } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import type { Role } from "../../types/auth";
import { ShieldAlert, ArrowLeft, Loader2 } from "lucide-react";

interface ProtectedRouteProps {
  allowedRoles?: Role[];
  children?: React.ReactNode;
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ allowedRoles, children }) => {
  const { user, isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  // 1. Đang kiểm tra phiên làm việc -> hiển thị spinner
  if (isLoading) {
    return (
      <div className="min-h-screen w-full flex flex-col items-center justify-center bg-slate-900 text-slate-100">
        <Loader2 className="w-10 h-10 animate-spin text-blue-500 mb-4" />
        <p className="text-sm text-slate-400 font-medium">Đang xác thực thông tin tài khoản...</p>
      </div>
    );
  }

  // 2. Chưa đăng nhập -> Chuyển hướng tới trang login, lưu lại state location để quay lại
  if (!isAuthenticated || !user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // 3. Đã đăng nhập nhưng không đủ role được cấp phép -> Báo lỗi 403
  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return (
      <div className="min-h-screen w-full flex flex-col items-center justify-center bg-slate-900 text-slate-100 px-4">
        <div className="max-w-md w-full bg-slate-800/80 border border-red-500/30 rounded-2xl p-8 shadow-2xl backdrop-blur-md text-center">
          <div className="w-16 h-16 bg-red-500/10 border border-red-500/20 rounded-2xl flex items-center justify-center mx-auto mb-5 text-red-400">
            <ShieldAlert className="w-9 h-9" />
          </div>
          <h2 className="text-xl font-bold text-slate-100 mb-2">Quyền Truy Cập Bị Từ Chối (403)</h2>
          <p className="text-sm text-slate-400 mb-6">
            Tài khoản của bạn với vai trò <span className="font-semibold text-amber-400">{user.role}</span> không có quyền truy cập vào khu vực quản trị này.
          </p>
          <div className="flex gap-3 justify-center">
            <Link
              to="/"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-medium text-sm transition-colors shadow-lg shadow-blue-600/30"
            >
              <ArrowLeft className="w-4 h-4" />
              Về Trang Bản Đồ
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // 4. Quyền hợp lệ
  return <>{children}</>;
};
