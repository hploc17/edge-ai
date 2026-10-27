@echo off
chcp 65001 >nul
title Đẩy code lên GitHub (Tự động lọc ảnh và video)
echo ==============================================================================
echo       CÔNG CỤ ĐẨY CODE LÊN GITHUB - LOẠI BỎ FILE NẶNG (ẢNH, VIDEO, CACHE)
echo ==============================================================================
echo.

:: 1. Lấy nội dung commit
set "MSG=%~1"
if "%MSG%"=="" (
    set /p "MSG=Nhập ghi chú commit (Ví dụ: cap nhat giao dien): "
)
if "%MSG%"=="" (
    set "MSG=update source code"
)

:: 2. Lấy tên nhánh hiện tại
for /f "tokens=*" %%i in ('git branch --show-current') do set "CURRENT_BRANCH=%%i"
if "%CURRENT_BRANCH%"=="" set "CURRENT_BRANCH=web"
echo [INFO] Nhánh Git hiện tại: %CURRENT_BRANCH%
echo.

:: 3. Gỡ bỏ theo dõi các file nặng lỡ bị dính vào Git cache (vẫn giữ nguyên trên ổ cứng)
echo [1/4] Gỡ bỏ theo dõi các file nặng khỏi Git index (nếu có)...
git rm -r --cached --quiet traffic_backup 2>nul
git rm -r --cached --quiet webgis/backend/data/snapshots/*.jpg 2>nul
git rm -r --cached --quiet webgis/backend/data/snapshots/*.jpeg 2>nul
git rm -r --cached --quiet *.mp4 *.h264 *.avi *.mkv *.filepart 2>nul
git rm -r --cached --quiet *.engine *.onnx *.weights 2>nul

:: 4. Thêm các thay đổi code mới
echo [2/4] Thêm các thay đổi mã nguồn vào Git...
git add .

:: 5. Tạo commit
echo [3/4] Đang tạo commit: "%MSG%"...
git commit -m "%MSG%"

:: 6. Đẩy lên GitHub
echo [4/4] Đang đẩy lên GitHub nhánh %CURRENT_BRANCH%...
git push -u origin %CURRENT_BRANCH%

if %errorlevel% equ 0 (
    echo.
    echo ==============================================================================
    echo ✅ ĐÃ ĐẨY CODE LÊN GITHUB THÀNH CÔNG!
    echo ==============================================================================
) else (
    echo.
    echo ==============================================================================
    echo ❌ Đẩy code thất bại. Vui lòng kiểm tra lại mạng hoặc xung đột nhánh.
    echo ==============================================================================
)
pause
