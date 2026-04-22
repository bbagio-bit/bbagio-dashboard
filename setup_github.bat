@echo off
echo.
echo ============================================================
echo   BBagio - GitHub Pages Setup Guide
echo ============================================================
echo.
echo [Step 1] Create a GitHub account
echo   Go to https://github.com and Sign up
echo.
echo [Step 2] Create a new repository
echo   1. After login, click + at top right
echo   2. Select: New repository
echo   3. Repository name: bbagio-dashboard
echo   4. Select: Public (required for free GitHub Pages)
echo   5. Click: Create repository
echo.
echo [Step 3] Generate a Personal Access Token
echo   1. Click your profile photo (top right)
echo   2. Go to Settings
echo   3. Scroll down to: Developer settings
echo   4. Personal access tokens - Tokens (classic)
echo   5. Click: Generate new token (classic)
echo   6. Note: BBagio Dashboard
echo   7. Expiration: No expiration
echo   8. Scope: check 'repo' (all)
echo   9. Click: Generate token
echo  10. Copy the token (starts with ghp_)
echo.
echo [Step 4] Edit config.json
echo   Open config.json in Notepad
echo   github_token: paste your token
echo   github_user:  your GitHub username
echo   github_repo:  bbagio-dashboard (keep as is)
echo.
echo [Step 5] Run run_all.bat
echo   First run will auto-create the gh-pages branch
echo   Dashboard URL: https://[github_user].github.io/bbagio-dashboard/
echo.
echo [Step 6] Enable GitHub Pages (one time only)
echo   1. Open bbagio-dashboard repo on GitHub
echo   2. Click: Settings tab
echo   3. Click: Pages
echo   4. Source: Deploy from a branch
echo   5. Branch: gh-pages / (root) - Save
echo   (Active in about 1-2 minutes)
echo.
echo ============================================================
echo   After setup, just run run_all.bat every time!
echo ============================================================
echo.
pause
