@echo off
chcp 65001 >nul
title WebGIS Frontend Vite Debug
echo ==============================================================================
echo   DEBUG ĐỘC LẬP: WebGIS Frontend Dev Server (:5173)
echo   (Để khởi động toàn bộ hệ thống gồm Auth, Backend, Frontend, MediaMTX:
echo    vui lòng chạy 'start_webgis.bat' ở thư mục gốc)
echo ==============================================================================
cd /d "%~dp0"
npm run dev
pause
