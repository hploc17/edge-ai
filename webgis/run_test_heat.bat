@echo off
title Chay Test Hieu Ung Nhiet Ket Xe (WebGIS Heatmap)
echo ================================================================
echo   DANG KHOI CHAY MO PHONG NHIET DO GIAO THONG (EDGE-01)
echo   Topic: traffic/edge-01/telemetry
echo ================================================================
cd /d "%~dp0"
python tools\test_heat_simulation.py
pause
