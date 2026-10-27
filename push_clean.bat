@echo off
chcp 65001 >nul
title Đẩy code lên GitHub (Tự động lọc bỏ file nặng và bảo mật)
echo ==============================================================================
echo       CÔNG CỤ ĐẨY CODE LÊN GITHUB - TỰ ĐỘNG LOẠI BỎ FILE NẶNG VÀ FILE RÁC
echo ==============================================================================
echo.

:: 1. Kiểm tra liên kết GitHub Remote
git remote get-url origin >nul 2>&1
if %errorlevel% neq 0 (
    echo [CHÚ Ý] Bạn chưa liên kết với kho lưu trữ GitHub nào!
    echo.
    echo   1. Mở trình duyệt vào https://github.com/new để tạo repository mới
    echo      (Đặt tên bất kỳ, ví dụ: edge-ai-web, chọn Public hoặc Private)
    echo   2. Copy link HTTPS vừa tạo (Ví dụ: https://github.com/username/edge-ai-web.git)
    echo.
    set /p "REPO_URL=Dán đường link GitHub của bạn vào đây rồi nhấn Enter: "
    if not "%REPO_URL%"=="" (
        git remote add origin %REPO_URL%
        echo [OK] Đã liên kết thành công với: %REPO_URL%
        echo.
    ) else (
        echo [LỖI] Bạn chưa nhập đường link. Vui lòng mở lại file để thử lại.
        pause
        exit /b 1
    )
)

:: 2. Xác định nhánh hiện tại (mặc định main)
for /f "tokens=*" %%i in ('git branch --show-current') do set "CURRENT_BRANCH=%%i"
if "%CURRENT_BRANCH%"=="" set "CURRENT_BRANCH=main"
echo [INFO] Nhánh Git hiện tại: %CURRENT_BRANCH%
echo.

:: 3. Lấy nội dung ghi chú commit
set "MSG=%~1"
if "%MSG%"=="" (
    set /p "MSG=Nhập ghi chú commit (Nhấn Enter để dùng mặc định 'Cap nhat he thong'): "
)
if "%MSG%"=="" (
    set "MSG=Cap nhat he thong Edge AI va WebGIS"
)

:: 4. Thêm các thay đổi (đã được .gitignore lọc sạch file nặng)
echo [1/3] Đang chuẩn bị các tệp mã nguồn sạch (đã loại bỏ video, node_modules, .env)...
git add .

:: 5. Tạo commit (nếu có thay đổi mới)
echo [2/3] Đang ghi nhận phiên bản: "%MSG%"...
git commit -m "%MSG%" 2>nul

:: 6. Đẩy lên GitHub
echo [3/3] Đang đẩy lên GitHub (nhánh %CURRENT_BRANCH%)...
git push -u origin %CURRENT_BRANCH%

if %errorlevel% equ 0 (
    echo.
    echo ==============================================================================
    echo ✅ ĐÃ ĐẨY TOÀN BỘ CODE LÊN GITHUB THÀNH CÔNG!
    echo ==============================================================================
) else (
    echo.
    echo ==============================================================================
    echo ⚠️ Đẩy code chưa hoàn tất. Có thể do:
    echo    1. GitHub yêu cầu đăng nhập (trình duyệt sẽ hiện cửa sổ xác thực Sign In).
    echo    2. Kho lưu trữ trên GitHub đã có sẵn file README (chạy: git pull origin %CURRENT_BRANCH% --rebase rồi thử lại).
    echo ==============================================================================
)
echo.
pause
