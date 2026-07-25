@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  策略展示站 - 半自动部署
echo ============================================
echo.

echo [1/3] 重新生成 macro407/data.js ...
python build_data.py
if errorlevel 1 (
    echo.
    echo [失败] build_data.py 运行出错，未做任何提交。
    pause
    exit /b 1
)
echo.

git add -A
git diff --cached --quiet
if not errorlevel 1 (
    echo [2/3] 数据无变化，无需提交。网站保持现状。
    echo.
    pause
    exit /b 0
)

echo [2/3] 提交变更 ...
git commit -m "update macro407 %date:~0,4%-%date:~5,2%-%date:~8,2%"
if errorlevel 1 (
    echo.
    echo [失败] git commit 出错。
    pause
    exit /b 1
)
echo.

echo [3/3] 推送到 GitHub ...
git push
if errorlevel 1 (
    echo.
    echo [失败] git push 出错（首次推送可能需要登录授权，请重试）。
    pause
    exit /b 1
)

echo.
echo ============================================
echo  完成！GitHub Pages 约 1 分钟后自动更新。
echo ============================================
pause
