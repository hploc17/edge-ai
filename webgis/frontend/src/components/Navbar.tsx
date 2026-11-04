import React, { useState, useRef, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Activity,
  ShieldCheck,
  Video,
  History,
  Settings,
  PlusCircle,
  AlertTriangle,
  Radio,
  LogIn,
  LogOut,
  User as UserIcon,
  Shield,
  ChevronDown,
  Users,
} from "lucide-react";
import type { SummaryKPIs } from "../types/gis";
import { useAuth } from "../context/AuthContext";

interface NavbarProps {
  kpis: SummaryKPIs | null;
  pendingCount?: number;
  onOpenHistory: () => void;
  onOpenFleet: () => void;
  onOpenAddNode: () => void;
  onOpenPendingApproval?: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  kpis,
  pendingCount = 0,
  onOpenHistory,
  onOpenFleet,
  onOpenAddNode,
  onOpenPendingApproval,
}) => {
  const { user, isAuthenticated, isAdmin, isStaff, logout } = useAuth();
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  // Đóng dropdown khi click bên ngoài
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleLogout = () => {
    logout();
    setIsDropdownOpen(false);
    navigate("/");
  };

  const getRoleBadge = (role?: string) => {
    if (role === "ADMIN") {
      return (
        <span className="px-2 py-0.5 text-[10px] font-extrabold bg-red-100 text-red-700 border border-red-300 rounded-full flex items-center gap-1">
          <Shield className="w-2.5 h-2.5 text-red-600" /> ADMIN
        </span>
      );
    }
    if (role === "MANAGER") {
      return (
        <span className="px-2 py-0.5 text-[10px] font-extrabold bg-amber-100 text-amber-700 border border-amber-300 rounded-full flex items-center gap-1">
          <Shield className="w-2.5 h-2.5 text-amber-600" /> MANAGER
        </span>
      );
    }
    return (
      <span className="px-2 py-0.5 text-[10px] font-bold bg-blue-100 text-blue-700 border border-blue-300 rounded-full">
        USER
      </span>
    );
  };

  return (
    <header className="absolute top-3 left-3 right-3 z-20 flex items-center justify-between px-5 py-3 rounded-xl glass-panel text-slate-800">
      {/* Brand & System Status */}
      <div className="flex items-center space-x-3">
        <Link to="/" className="flex items-center space-x-3 group">
          <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-blue-50 border border-blue-200 text-blue-600 shadow-sm group-hover:bg-blue-100 transition-colors">
            <Video className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="font-extrabold text-lg tracking-wide bg-gradient-to-r from-blue-700 via-indigo-600 to-cyan-600 bg-clip-text text-transparent">
                TRAFFIC OPERATIONS CENTER
              </h1>
              <span className="px-2 py-0.5 text-xs font-bold bg-emerald-100 text-emerald-700 border border-emerald-300 rounded-full flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                LIVE GIS
              </span>
            </div>
            <p className="text-xs text-slate-500 font-medium">Nền tảng Giám sát Giao thông Đô thị & Thiết bị Biên AI</p>
          </div>
        </Link>
      </div>

      {/* Real-time KPIs */}
      {kpis && (
        <div className="hidden lg:flex items-center space-x-6 px-4 py-1.5 rounded-lg bg-slate-50/90 border border-slate-200 text-sm shadow-inner">
          <div className="flex items-center space-x-2">
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
            <span className="text-slate-500 text-xs font-medium">Nodes Online:</span>
            <span className="font-bold text-emerald-700">
              {kpis.online_nodes}/{kpis.total_nodes}
            </span>
          </div>

          <div className="h-4 w-px bg-slate-200" />

          <div className="flex items-center space-x-2">
            <AlertTriangle className="w-4 h-4 text-amber-600" />
            <span className="text-slate-500 text-xs font-medium">Điểm ùn tắc:</span>
            <span className={`font-bold ${kpis.congested_segments > 0 ? "text-red-600 animate-pulse" : "text-slate-700"}`}>
              {kpis.congested_segments} đoạn
            </span>
          </div>

          <div className="h-4 w-px bg-slate-200" />

          <div className="flex items-center space-x-2">
            <Activity className="w-4 h-4 text-blue-600" />
            <span className="text-slate-500 text-xs font-medium">Vận tốc TB:</span>
            <span className="font-bold text-blue-700">{kpis.system_avg_speed_kmh} km/h</span>
          </div>
        </div>
      )}

      {/* Navigation Buttons & Auth Control */}
      <div className="flex items-center space-x-2.5">
        {/* Lịch sử kẹt xe: CÔNG KHAI */}
        <button
          onClick={onOpenHistory}
          className="flex items-center space-x-1.5 px-3.5 py-2 text-xs font-semibold rounded-lg bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 text-indigo-700 transition shadow-sm cursor-pointer"
        >
          <History className="w-4 h-4 text-indigo-600" />
          <span>Lịch sử Kẹt xe</span>
        </button>

        {/* Các nút dành riêng cho STAFF (MANAGER, ADMIN) */}
        {isStaff && (
          <>
            {pendingCount > 0 && onOpenPendingApproval && (
              <button
                onClick={onOpenPendingApproval}
                className="relative flex items-center space-x-1.5 px-3.5 py-2 text-xs font-bold rounded-lg bg-amber-500 hover:bg-amber-600 text-white shadow-md shadow-amber-500/30 transition animate-pulse cursor-pointer"
              >
                <Radio className="w-4 h-4" />
                <span>{pendingCount} thiết bị mới</span>
                <span className="absolute -top-1 -right-1 w-3.5 h-3.5 bg-red-500 rounded-full text-[8px] flex items-center justify-center font-bold">
                  {pendingCount}
                </span>
              </button>
            )}

            <button
              onClick={onOpenFleet}
              className="flex items-center space-x-1.5 px-3.5 py-2 text-xs font-semibold rounded-lg bg-slate-100 hover:bg-slate-200 border border-slate-300 text-slate-700 transition shadow-sm cursor-pointer"
            >
              <Settings className="w-4 h-4 text-slate-500" />
              <span>Quản lý Nodes</span>
            </button>

            <button
              onClick={onOpenAddNode}
              className="flex items-center space-x-1.5 px-3.5 py-2 text-xs font-bold rounded-lg bg-blue-600 hover:bg-blue-700 text-white shadow-md shadow-blue-500/25 transition cursor-pointer"
            >
              <PlusCircle className="w-4 h-4" />
              <span>Thêm Node</span>
            </button>
          </>
        )}

        <div className="h-6 w-px bg-slate-300 mx-1" />

        {/* Khối Đăng Nhập / Thông Tin Tài Khoản */}
        {!isAuthenticated || !user ? (
          <Link
            to="/login"
            className="flex items-center space-x-1.5 px-4 py-2 text-xs font-bold rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white shadow-md shadow-blue-600/30 transition"
          >
            <LogIn className="w-4 h-4" />
            <span>Đăng Nhập</span>
          </Link>
        ) : (
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setIsDropdownOpen(!isDropdownOpen)}
              className="flex items-center space-x-2 pl-2 pr-2.5 py-1.5 rounded-lg bg-white/80 hover:bg-white border border-slate-200 text-slate-800 shadow-sm transition cursor-pointer"
            >
              <div className="w-7 h-7 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-bold">
                {user.name.charAt(0).toUpperCase()}
              </div>
              <div className="text-left hidden sm:block">
                <div className="text-xs font-bold leading-tight line-clamp-1">{user.name}</div>
              </div>
              {getRoleBadge(user.role)}
              <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
            </button>

            {/* User Dropdown Menu */}
            {isDropdownOpen && (
              <div className="absolute right-0 mt-2 w-56 rounded-2xl bg-white border border-slate-200 shadow-2xl py-2 z-50 animate-fadeIn text-slate-700">
                <div className="px-4 py-2.5 border-b border-slate-100">
                  <p className="text-xs font-bold text-slate-900 truncate">{user.name}</p>
                  <p className="text-[11px] text-slate-500 truncate">{user.email}</p>
                  <div className="mt-1.5">{getRoleBadge(user.role)}</div>
                </div>

                <div className="py-1">
                  <Link
                    to="/profile"
                    onClick={() => setIsDropdownOpen(false)}
                    className="flex items-center space-x-2 px-4 py-2 text-xs hover:bg-slate-50 text-slate-700 transition"
                  >
                    <UserIcon className="w-4 h-4 text-blue-600" />
                    <span>Thông tin cá nhân</span>
                  </Link>

                  {/* Mục Quản lý Manager chỉ hiển thị cho ADMIN */}
                  {isAdmin && (
                    <Link
                      to="/admin/managers"
                      onClick={() => setIsDropdownOpen(false)}
                      className="flex items-center space-x-2 px-4 py-2 text-xs hover:bg-amber-50 text-amber-800 transition"
                    >
                      <Users className="w-4 h-4 text-amber-600" />
                      <span className="font-semibold">Quản lý Manager</span>
                    </Link>
                  )}
                </div>

                <div className="pt-1 border-t border-slate-100">
                  <button
                    onClick={handleLogout}
                    className="w-full flex items-center space-x-2 px-4 py-2 text-xs text-red-600 hover:bg-red-50 transition cursor-pointer text-left"
                  >
                    <LogOut className="w-4 h-4" />
                    <span>Đăng xuất</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </header>
  );
};
