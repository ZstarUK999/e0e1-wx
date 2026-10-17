@echo off
chcp 65001 >nul
setlocal

rem 插件一键发布：构建 → 上传 → 发布
rem   用法：publish.bat 1.2.0 "修了斗法的刷新逻辑"
rem   只上传不发布：publish.bat 1.2.0 --no-publish
rem   复用现有产物：publish.bat 1.2.0 --skip-build
rem 密码可用环境变量 E0E1_PUBLISH_PASSWORD 预设，免得每次手输。

if "%~1"=="" (
  echo 用法：publish.bat ^<版本号^> [更新日志] [--skip-build] [--mandatory] [--no-publish]
  exit /b 1
)

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" "%~dp0tools\publish.py" %*
exit /b %ERRORLEVEL%
