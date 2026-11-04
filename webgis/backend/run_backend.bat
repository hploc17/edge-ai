@echo off
chcp 65001 >nul
title WebGIS FastAPI Backend Debug
echo ==============================================================================
echo   DEBUG ĐỘC LẬP: WebGIS FastAPI Backend Hub (:8000)
echo   (Để khởi động toàn bộ hệ thống gồm Auth, Backend, Frontend, MediaMTX:
echo    vui lòng chạy 'start_webgis.bat' ở thư mục gốc)
echo ==============================================================================
cd /d "%~dp0"
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
