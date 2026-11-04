import React from "react";
import { useAuth } from "../../context/AuthContext";
import type { Role } from "../../types/auth";

interface RoleGateProps {
  roles: Role[];
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

/**
 * Component kiểm tra quyền hiển thị control trên giao diện UI:
 * Chỉ render children nếu người dùng đã đăng nhập và có role nằm trong mảng `roles`.
 */
export const RoleGate: React.FC<RoleGateProps> = ({ roles, children, fallback = null }) => {
  const { user, isAuthenticated } = useAuth();

  if (!isAuthenticated || !user) {
    return <>{fallback}</>;
  }

  if (!roles.includes(user.role)) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
};
