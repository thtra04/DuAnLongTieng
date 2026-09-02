@echo off
setlocal
chcp 65001 >nul
title VSub Studio

cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo [X] Khong tim thay "uv". Cai bang lenh:
    echo     powershell -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    echo Sau khi cai xong, mo lai cua so nay va chay lai file.
    pause
    exit /b 1
)

if not exist ".venv\" (
    echo [*] Lan dau chay: dang cai dependencies bang uv sync ...
    uv sync --extra cuda --extra tts
    if errorlevel 1 (
        echo [X] uv sync that bai. Kiem tra loi phia tren.
        pause
        exit /b 1
    )
)

echo [*] Khoi dong VSub Studio tai http://127.0.0.1:8000 ...
uv run python run.py %*

endlocal
