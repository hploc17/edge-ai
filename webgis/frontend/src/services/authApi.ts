import axios from "axios";
import type { User, AuthResponse, ManagerListResponse } from "../types/auth";

const host = typeof window !== "undefined" ? window.location.hostname : "localhost";
export const AUTH_API_URL = import.meta.env.VITE_AUTH_API_URL || `http://${host}:5000/api`;

export const authClient = axios.create({
  baseURL: AUTH_API_URL,
});

// Tự động gắn Bearer Token vào header mỗi request
authClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("webgis_auth_token");
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Xử lý response: nếu 401 thì xóa token
authClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("webgis_auth_token");
      localStorage.removeItem("webgis_auth_user");
      // Nếu không ở trang login thì redirect về login
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        // window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export const authApi = {
  login: async (credentials: { email: string; password: string }) => {
    const res = await authClient.post<{ success: boolean; data: AuthResponse }>("/auth/login", credentials);
    return res.data.data;
  },

  register: async (userData: { name: string; email: string; password: string }) => {
    const res = await authClient.post<{ success: boolean; data: AuthResponse }>("/auth/register", userData);
    return res.data.data;
  },

  getMe: async () => {
    const res = await authClient.get<{ success: boolean; data: { user: User } }>("/auth/me");
    return res.data.data.user;
  },

  updateProfile: async (data: { name?: string; email?: string; currentPassword?: string; newPassword?: string }) => {
    const res = await authClient.patch<{ success: boolean; data: { user: User } }>("/auth/me", data);
    return res.data.data.user;
  },

  // ── Quản lý MANAGER (Admin only) ──────────────────────────────────────────
  getManagers: async (params?: { page?: number; limit?: number; search?: string }) => {
    const res = await authClient.get<{ success: boolean; data: ManagerListResponse }>("/admin/managers", {
      params,
    });
    return res.data.data;
  },

  createManager: async (data: { name: string; email: string; password: string }) => {
    const res = await authClient.post<{ success: boolean; data: { manager: User } }>("/admin/managers", data);
    return res.data.data.manager;
  },

  updateManager: async (id: string, data: { name?: string; email?: string; password?: string }) => {
    const res = await authClient.put<{ success: boolean; data: { manager: User } }>(`/admin/managers/${id}`, data);
    return res.data.data.manager;
  },

  deleteManager: async (id: string) => {
    const res = await authClient.delete<{ success: boolean; message: string }>(`/admin/managers/${id}`);
    return res.data;
  },
};
