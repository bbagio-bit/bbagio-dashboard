@echo off
echo.
echo ============================================================
echo   BBagio - Run All (Meta + Cafe24)
echo ============================================================
echo.

python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Run install.bat first.
    pause
    exit /b 1
)

if not exist "config.json" (
    echo [ERROR] config.json not found.
    pause
    exit /b 1
)

:: STEP 1: Meta Ads
echo [1/2] Collecting Meta Ads data...
echo ------------------------------------------------------------
python meta_collector.py
if errorlevel 1 (
    echo.
    echo [WARNING] Meta collection failed. Continuing with Cafe24...
    echo.
) else (
    echo [1/2] Meta - Done.
    echo.
)

:: STEP 2: Cafe24
echo [2/2] Collecting Cafe24 data...
echo ------------------------------------------------------------
python cafe24_collector.py
if errorlevel 1 (
    echo.
    echo ============================================================
    echo   [ERROR] Cafe24 collection failed. Check error above.
    echo ============================================================
) else (
    echo.
    echo ============================================================
    echo   All Done!
    echo ============================================================
    echo.
    echo Output files saved in 'output' folder:
    echo   - BBagio_cafe24_YYYYMMDD.xlsx
    echo   - BBagio_cafe24_dashboard.html
    echo   - cafe24_latest.json
    echo   - meta_summary.json
)

echo.
pause
