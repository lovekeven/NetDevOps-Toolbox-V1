@echo off
chcp 65001 >nul
echo ========================================
echo   NetDevOps-Toolbox Windows 打包脚本
echo ========================================
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 没有找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

REM 检查 PyInstaller 是否安装
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo [提示] 正在安装 PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
)

echo [1/3] 清理旧的构建文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__

echo [2/3] 开始打包...
pyinstaller build_windows.spec

if errorlevel 1 (
    echo.
    echo [错误] 打包失败！请检查错误信息
    pause
    exit /b 1
)

echo [3/3] 打包完成！
echo.
echo ========================================
echo   输出目录: dist\NetDevOps-Toolbox\
echo   启动程序: dist\NetDevOps-Toolbox\NetDevOps-Toolbox.exe
echo ========================================
echo.
echo 使用方法:
echo   1. 进入 dist\NetDevOps-Toolbox\ 目录
echo   2. 双击 NetDevOps-Toolbox.exe 启动
echo   3. 浏览器访问 http://localhost:5000
echo.
pause
