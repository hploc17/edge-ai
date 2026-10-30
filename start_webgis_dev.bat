@echo off
chcp 65001 >nul
title WebGIS Development Mode
cd /d "%~dp0"
call start_webgis.bat
