import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { WebGISDashboard } from "./pages/WebGISDashboard";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { ProfilePage } from "./pages/ProfilePage";
import { ManagerManagementPage } from "./pages/ManagerManagementPage";
import { ProtectedRoute } from "./components/Auth/ProtectedRoute";

export const App: React.FC = () => {
  return (
    <Routes>
      {/* 1. Bản đồ WebGIS: CÔNG KHAI (Khách, USER, MANAGER, ADMIN đều truy cập được) */}
      <Route path="/" element={<WebGISDashboard />} />

      {/* 2. Đăng nhập & Đăng ký: CÔNG KHAI */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      {/* 3. Trang Thông tin cá nhân & Đổi mật khẩu: Yêu cầu ĐÃ ĐĂNG NHẬP (mọi Role) */}
      <Route
        path="/profile"
        element={
          <ProtectedRoute>
            <ProfilePage />
          </ProtectedRoute>
        }
      />

      {/* 4. Quản lý tài khoản MANAGER: BẢO VỆ CAO CẤP CHỈ DÀNH CHO ADMIN */}
      <Route
        path="/admin/managers"
        element={
          <ProtectedRoute allowedRoles={["ADMIN"]}>
            <ManagerManagementPage />
          </ProtectedRoute>
        }
      />

      {/* 5. Fallback: Điều hướng về trang chủ */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

export default App;
