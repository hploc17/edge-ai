@echo off
title WebGIS Traffic Operations Center
echo ================================================================
echo   WEBGIS TRAFFIC OPERATIONS CENTER (FastAPI + React MapLibre)
echo ================================================================
echo.
echo   [1] Backend API: http://localhost:8000/api/v1/gis/nodes
echo   [2] Swagger Docs: http://localhost:8000/docs
echo   [3] WebGIS Interface: http://localhost:8000/
echo.
echo   Dang khoi dong he thong...
echo ================================================================
cd /d "%~dp0backend"
python -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
