@echo off
chcp 65001 >nul
echo.
echo ============================================================
echo   BBagio 통합 수집 (Meta + 자사몰)
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

:: ── STEP 1: Meta 광고 수집 ──────────────────────────────────────
echo [1/2] Meta 광고 데이터 수집 중...
echo ============================================================
python meta_collector.py
if errorlevel 1 (
    echo.
    echo [WARNING] Meta 수집 중 오류가 발생했습니다.
    echo           자사몰 수집은 계속 진행합니다.
    echo.
) else (
    echo [1/2] Meta 수집 완료
    echo.
)

:: ── STEP 2: 자사몰(Cafe24) 수집 ────────────────────────────────
echo [2/2] 자사몰(Cafe24) 데이터 수집 중...
echo ============================================================
python cafe24_collector.py
if errorlevel 1 (
    echo.
    echo ============================================================
    echo   [ERROR] 자사몰 수집 중 오류가 발생했습니다.
    echo ============================================================
) else (
    echo.
    echo ============================================================
    echo   완료! 모든 수집이 끝났습니다.
    echo ============================================================
    echo.
    echo 저장된 파일 (output 폴더):
    echo   - BBagio_cafe24_YYYYMMDD.xlsx
    echo   - BBagio_cafe24_dashboard.html
    echo   - cafe24_latest.json
    echo   - meta_summary.json
)

echo.
pause
