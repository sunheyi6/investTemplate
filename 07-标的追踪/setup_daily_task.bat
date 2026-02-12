@echo off
chcp 65001
cls

echo ==========================================
echo 港股标的自动追踪 - 定时任务设置
echo ==========================================
echo.

REM 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

echo [1/4] 检查Python环境... 通过

REM 安装依赖
echo [2/4] 安装依赖包...
pip install yfinance pandas matplotlib -q
if errorlevel 1 (
    echo [警告] 依赖安装可能失败，尝试继续...
)

echo [3/4] 创建定时任务...

REM 获取当前目录
set "SCRIPT