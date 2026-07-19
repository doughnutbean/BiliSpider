@echo off
REM ========================================
REM  CodeWhale 直连模式启动脚本
REM  用法:
REM    双击            → 在当前目录启动
REM    bat 文件 目录路径 → 在指定目录启动
REM    拖拽文件夹到 bat  → 在拖入的目录启动
REM ========================================

REM ========================================
REM  清除所有代理（环境变量 + 系统代理注册表残留）
REM  根因：codewhale 的 Rust HTTP 库(reqwest)会直接读取
REM  注册表 ProxyServer 值，不检查 ProxyEnable 开关。
REM  FlClash 退出后可能残留 ProxyServer=127.0.0.1:7890
REM  导致直连失败。
REM ========================================
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=
set NO_PROXY=*

REM 清除系统代理注册表残留
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /t REG_SZ /d "" /f >nul 2>&1

REM 如果传入了参数，切换到该目录
if not "%~1"=="" (
    cd /d "%~1"
    echo 工作区: %cd%
) else (
    echo 工作区: %cd%
)

echo 代理已清除，正在启动 CodeWhale...
start "" codewhale
