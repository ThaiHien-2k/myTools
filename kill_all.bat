@echo off
title myTools Cleanup
echo ---------------------------------------------------
echo       DANG DON DEP TOAN BO HE THONG MYTOOLS
echo ---------------------------------------------------
echo.
echo [+] Dang tim va tieu diet cac tien trinh python.exe...
taskkill /F /IM python.exe /T 2>nul
echo.
echo [+] Dang tim va tieu diet cac tien trinh pythonw.exe...
taskkill /F /IM pythonw.exe /T 2>nul
echo.
echo ---------------------------------------------------
echo  DA DON DEP SACH SE! BAN CO THE CHAY LAI DASHBOARD.
echo ---------------------------------------------------
pause
