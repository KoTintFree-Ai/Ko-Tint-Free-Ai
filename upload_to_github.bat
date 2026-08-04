@echo off
echo ========================================
echo   GitHub Auto Upload Tool (V6.5)
echo ========================================
echo.

echo 1. Adding changes...
git add .

echo.
echo 2. Committing changes...
git commit -m "Update MovieRecap to V6.5 (Fixed Myanmar Rendering)"

echo.
echo 3. Pushing to GitHub...
git push

echo.
echo ========================================
echo   Done! Your changes are uploaded.
echo ========================================
pause
