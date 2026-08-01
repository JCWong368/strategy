@echo off
cd /d "%~dp0"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%i

echo ============================================
echo  策略展示站 - 半自动部署 (%TODAY%)
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
if errorlevel 1 (
    echo [2/3] 提交变更 ...
    git commit -m "update macro407 %TODAY%"
    if errorlevel 1 (
        echo.
        echo [失败] git commit 出错。
        pause
        exit /b 1
    )
) else (
    echo [2/3] 数据无变化，跳过提交（仍会执行推送，补推之前未成功的提交）。
)
echo.

echo [3/3] 推送到 GitHub（网络不稳时自动重试，最多 5 次）...
set RETRY=0
:push_retry
git push
if not errorlevel 1 goto push_ok
set /a RETRY+=1
if %RETRY% geq 5 (
    echo.
    echo [失败] 已重试 5 次仍推送失败（网络问题）。
    echo        本地提交已保留，稍后重新运行本脚本即可补推，无需担心数据变化。
    pause
    exit /b 1
)
echo [重试] 第 %RETRY% 次推送失败，5 秒后重试 ...
timeout /t 5 /nobreak >nul
goto push_retry
:push_ok

echo.
echo ============================================
echo  完成！GitHub Pages 约 1 分钟后自动更新。
echo ============================================
pause
