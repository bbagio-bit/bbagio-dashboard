@echo off
chcp 65001 >nul
echo.
echo ============================================
echo   BBagio GA4 트래픽 수집
echo ============================================
echo.

:: Python 경로 자동 탐색
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo       https://python.org 에서 설치 후 다시 실행하세요.
    pause
    exit /b
)

:: 필요한 패키지 확인 / 설치
echo [패키지 확인 중...]
python -c "from google.analytics.data_v1beta import BetaAnalyticsDataClient" >nul 2>&1
if %errorlevel% neq 0 (
    echo google-analytics-data 패키지를 설치합니다...
    pip install google-analytics-data -q
)

:: 서비스 계정 키 파일 확인
if not exist "ga4_service_account.json" (
    echo.
    echo [경고] ga4_service_account.json 파일이 없습니다!
    echo.
    echo   GCP 서비스 계정 키 파일을 이 폴더에 복사하세요:
    echo   파일명: ga4_service_account.json
    echo.
    pause
    exit /b
)

:: config.json에서 GA4 Property ID 확인
python -c "
import json
cfg = json.load(open('config.json', encoding='utf-8'))
pid = cfg.get('ga4_property_id','').strip()
if not pid:
    print('NO_PROPERTY_ID')
else:
    print('OK: ' + pid)
" > .ga4_check.tmp
set /p GA4CHECK=<.ga4_check.tmp
del .ga4_check.tmp

if "%GA4CHECK%"=="NO_PROPERTY_ID" (
    echo.
    echo [경고] GA4 Property ID가 설정되지 않았습니다!
    echo.
    echo   config.json 파일을 메모장으로 열어서
    echo   "ga4_property_id" 항목에 숫자 ID를 입력하세요.
    echo.
    echo   GA4 숫자 Property ID 찾는 방법:
    echo   analytics.google.com → 관리(톱니바퀴) → 속성 설정 → 속성 ID
    echo   예: 12345678  (숫자만, G-로 시작하는 코드 아님!)
    echo.
    pause
    exit /b
)

echo   Property ID: %GA4CHECK%
echo.

:: GA4 수집 실행
echo [GA4 데이터 수집 중...]
python ga4_collector.py
if %errorlevel% neq 0 (
    echo.
    echo [오류] GA4 수집 실패. 위의 오류 메시지를 확인하세요.
    pause
    exit /b
)

:: GitHub Pages 업로드
echo.
echo [GitHub 업로드 중...]
python -c "
import json
from uploader import upload_github_pages
cfg = json.load(open('config.json', encoding='utf-8'))
url = upload_github_pages(
    'ga4_latest.json', 'ga4_latest.json',
    cfg['github_token'], cfg['github_user'], cfg['github_repo']
)
print('  업로드 완료:', url)
"

echo.
echo ============================================
echo   완료! 대시보드에서 GA4 섹션을 확인하세요.
echo ============================================
echo.
pause
