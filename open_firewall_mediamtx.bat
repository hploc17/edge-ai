@echo off
:: Chay voi quyen Administrator de mo port Windows Firewall cho MediaMTX
echo ==============================================================
echo MO PORT FIREWALL CHO MEDIAMTX LIVE STREAM (8554, 8888, 8889, 8189)
echo ==============================================================

netsh advfirewall firewall add rule name="Allow MediaMTX Live Stream" dir=in action=allow protocol=TCP localport=8554,8888,8889
netsh advfirewall firewall add rule name="Allow MediaMTX WebRTC UDP" dir=in action=allow protocol=UDP localport=8189,8554

echo.
echo ==============================================================
echo DA MO XONG CAC PORT CHO JETSON NANO VA TRINH DUYET!
echo ==============================================================
pause
