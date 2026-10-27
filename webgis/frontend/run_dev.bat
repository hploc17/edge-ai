@echo off
title WebGIS Frontend Dev Server
echo ================================================================
echo   Starting Vite React Dev Server on http://localhost:5173...
echo ================================================================
cd /d "%~dp0"
npm run dev
pause
