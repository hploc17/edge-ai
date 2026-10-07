@echo off
chcp 65001 >nul
title Giả lập dữ liệu Edge Traffic gửi về WebGIS
echo ==============================================================================
echo   GIẢ LẬP DỮ LIỆU TELEMETRY & HEARTBEAT TỪ THIẾT BỊ EDGE (MÔ PHỎNG CAMERA)
echo ==============================================================================
echo.
echo Đang kết nối HiveMQ Cloud MQTT và phát dữ liệu xe ảo về WebGIS...
echo Nhấn Ctrl+C để dừng mô phỏng.
echo ==============================================================================
python "%~dp0webgis\tools\simulate_edge.py"
pause
