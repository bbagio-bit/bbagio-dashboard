@echo off
echo.
echo  =====================================================
echo   BBagio Cafe24 - Manual Data Processing
echo  =====================================================
echo.
echo  [How to use]
echo  1. Cafe24 Admin ^> Orders ^> Export CSV (use Jashamol format)
echo  2. Put the downloaded CSV into the manual_data folder
echo  3. Run this file
echo.

python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

python cafe24_manual.py
