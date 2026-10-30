@echo off
chcp 65001 >nul
title Chuyển tiếp khởi động WebGIS Dev Mode
echo ==============================================================================
echo [CHUYỂN TIẾP] Khởi động WebGIS Dev Mode từ kịch bản chuẩn tại thư mục gốc...
echo ==============================================================================
cd /d "%~dp0..\"
call start_webgis_dev.bat
