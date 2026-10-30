@echo off
chcp 65001 >nul
title Chuyển tiếp khởi động WebGIS
echo ==============================================================================
echo [CHUYỂN TIẾP] Khởi động WebGIS từ kịch bản chuẩn tại thư mục gốc...
echo ==============================================================================
cd /d "%~dp0..\"
call start_webgis.bat
