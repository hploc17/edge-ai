import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import type { User } from "../types/auth";
import { authApi } from "../services/authApi";

interface AuthContextType {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isAdmin: boolean;
  isManager: boolean;
  isStaff: boolean;
  login: (credentials: { email: string; password: string }) => Promise<void>;
  register: (data: { name: string; email: string; password: string }) => Promise<void>;
  logout: () => void;
  updateProfile: (data: { name?: string; email?: string; currentPassword?: string; newPassword?: string }) => Promise<User>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("webgis_auth_token"));
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // Khôi phục phiên làm việc khi tải lại trang (F5)
  const refreshUser = useCallback(async () => {
    const storedToken = localStorage.getItem("webgis_auth_token");
    if (!storedToken) {
      setUser(null);
      setToken(null);
      setIsLoading(false);
      return;
    }

    try {
      const currentUser = await authApi.getMe();
      setUser(currentUser);
      setToken(storedToken);
      localStorage.setItem("webgis_auth_user", JSON.stringify(currentUser));
    } catch (error) {
      console.warn("[AUTH] Phiên đăng nhập không hợp lệ hoặc đã hết hạn, tiến hành đăng xuất.");
      localStorage.removeItem("webgis_auth_token");
      localStorage.removeItem("webgis_auth_user");
      setUser(null);
      setToken(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  const login = async (credentials: { email: string; password: string }) => {
    const data = await authApi.login(credentials);
    setToken(data.token);
    setUser(data.user);
    localStorage.setItem("webgis_auth_token", data.token);
    localStorage.setItem("webgis_auth_user", JSON.stringify(data.user));
  };

  const register = async (userData: { name: string; email: string; password: string }) => {
    const data = await authApi.register(userData);
    setToken(data.token);
    setUser(data.user);
    localStorage.setItem("webgis_auth_token", data.token);
    localStorage.setItem("webgis_auth_user", JSON.stringify(data.user));
  };

  const logout = () => {
    localStorage.removeItem("webgis_auth_token");
    localStorage.removeItem("webgis_auth_user");
    setUser(null);
    setToken(null);
  };

  const updateProfile = async (data: { name?: string; email?: string; currentPassword?: string; newPassword?: string }) => {
    const updated = await authApi.updateProfile(data);
    setUser(updated);
    localStorage.setItem("webgis_auth_user", JSON.stringify(updated));
    return updated;
  };

  const isAuthenticated = !!user && !!token;
  const isAdmin = user?.role === "ADMIN";
  const isManager = user?.role === "MANAGER";
  const isStaff = isAdmin || isManager;

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isLoading,
        isAuthenticated,
        isAdmin,
        isManager,
        isStaff,
        login,
        register,
        logout,
        updateProfile,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
