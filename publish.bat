@echo off
chcp 65001 >nul
setlocal

rem ============ 配置区：都写在这儿，平时直接双击就行 ============

rem 版本号（命令行给了就以命令行为准：publish.bat 1.3.0）
set VERSION=1.2.2

rem 更新日志，显示在后台版本列表里
set CHANGELOG=

rem 后台管理端地址 / gRPC 地址（gRPC 会写进产物，插件靠它连服务器）
set PUBLISH_BASE=http://127.0.0.1:8000
set PUBLISH_TARGET=127.0.0.1:8001

rem 后台管理员账号密码
set PUBLISH_USERNAME=admin
set PUBLISH_PASSWORD=k8ztV0StDVJydlKc

rem 1=复用现有产物只上传发布（快）；0=重新构建（改了代码时用）
set PUBLISH_SKIP_BUILD=0

rem 1=设为强制更新，玩家不更新就不能用
set PUBLISH_MANDATORY=0

rem 1=只上传不发布，去后台确认后再手动点发布
set PUBLISH_NO_PUBLISH=0

rem ==============================================================

if not "%~1"=="" set VERSION=%~1

set PY=%~dp0.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

echo 版本     : %VERSION%
echo 后台     : %PUBLISH_BASE%  gRPC %PUBLISH_TARGET%
if "%PUBLISH_SKIP_BUILD%"=="1" (echo 重新构建 : 否  复用现有产物) else (echo 重新构建 : 是  重新编译)
echo.

"%PY%" "%~dp0tools\publish.py" "%VERSION%" "%CHANGELOG%"
exit /b %ERRORLEVEL%
