@echo off
title Khoi dong WebGIS (Backend + Frontend Dev Mode)
echo ================================================================
echo   KHOI DONG DONG THOI BACKEND (FastAPI) VA FRONTEND (Vite)
echo ================================================================
echo.
echo   [1] Backend API & Docs: http://localhost:8000/docs
echo   [2] Frontend Vite Dev:  http://localhost:5173
echo.
echo   Dang mo 2 cua so tien trinh rieng biet...
echo ================================================================

:: Khoi dong Backend trong cua so moi
start "WebGIS Backend - FastAPI (:8000)" cmd /k "cd /d "%~dp0backend" && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

:: Khoi dong Frontend Vite trong cua so moi
start "WebGIS Frontend - Vite React (:5173)" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo Da khoi chay ca 2 service thanh cong!
