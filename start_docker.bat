@echo off
chcp 65001 >nul
title WebGIS Docker Operations Center
cd /d "%~dp0"
echo ==============================================================================
echo        KHỞI ĐỘNG TOÀN BỘ HỆ THỐNG WEBGIS QUA DOCKER COMPOSE
echo ==============================================================================
echo.
echo [1/2] Đang kiểm tra Docker daemon...
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [LỖI] Docker Desktop chưa được bật! Vui lòng mở ứng dụng Docker Desktop trước.
    pause
    exit /b 1
)

echo.
echo [2/2] Đang build và khởi động 4 dịch vụ (MediaMTX, Auth, Backend, Frontend)...
docker compose up -d --build

echo.
echo ==============================================================================
echo [THÀNH CÔNG] Toàn bộ hệ thống WebGIS đã được khởi chạy trong Docker:
echo   - Frontend Dashboard:      http://localhost:5173
echo   - Backend GIS Hub API:     http://localhost:8000 (Swagger: /docs)
echo   - Auth Service:            http://localhost:5000
echo   - MediaMTX Stream Server:  rtsp://localhost:8554
echo ==============================================================================
echo.
echo Để xem log thời gian thực: docker compose logs -f
echo Để dừng hệ thống:         docker compose down
echo.
pause

