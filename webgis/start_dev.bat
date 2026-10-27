@echo off
title Khoi dong WebGIS (Backend + Frontend Dev Mode)
echo ================================================================
echo   KHOI DONG DONG THOI AUTH (:5000), BACKEND (:8000), FRONTEND (:5173)
echo ================================================================
echo.
echo   [1] Auth Service (Express): http://localhost:5000/api/health
echo   [2] Backend API (FastAPI):  http://localhost:8000/docs
echo   [3] Frontend Vite Dev:      http://localhost:5173
echo.
echo   Dang mo 3 cua so tien trinh rieng biet...
echo ================================================================

:: Khoi dong Auth Service Express (:5000)
start "WebGIS Auth Service (:5000)" cmd /k "cd /d %~dp0auth-service && npm run dev"

:: Khoi dong Backend trong cua so moi (:8000)
start "WebGIS Backend - FastAPI (:8000)" cmd /k "cd /d %~dp0backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

:: Khoi dong Frontend Vite trong cua so moi (:5173)
start "WebGIS Frontend - Vite React (:5173)" cmd /k "cd /d %~dp0frontend && npm run dev"

echo Da khoi chay ca 3 service thanh cong!
