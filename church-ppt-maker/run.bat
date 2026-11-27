@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 교회 PPT 메이커

where py > nul 2>&1
if %errorlevel%==0 (set PY=py -3) else (set PY=python)

if not exist ".venv\Scripts\python.exe" (
    echo [처음 실행] 프로그램에 필요한 구성 요소를 설치합니다. 몇 분 걸릴 수 있습니다...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo.
        echo 파이썬을 찾을 수 없습니다. https://www.python.org/downloads/ 에서
        echo Python 3.10 이상을 설치하세요. 설치할 때 "Add python.exe to PATH" 를 꼭 체크하세요.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo 설치 중 오류가 발생했습니다. 인터넷 연결을 확인하고 다시 실행하세요.
        rmdir /s /q .venv
        pause
        exit /b 1
    )
)

start "" ".venv\Scripts\pythonw.exe" main.py
