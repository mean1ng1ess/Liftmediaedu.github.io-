@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo 교회 PPT 메이커 - 실행 파일(ChurchPPT.exe) 만들기

where py > nul 2>&1
if %errorlevel%==0 (set PY=py -3) else (set PY=python)

if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :fail

".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed ^
    --name ChurchPPT --collect-data pptx main.py
if errorlevel 1 goto :fail

".venv\Scripts\python.exe" -c "import subprocess,sys; sys.exit(subprocess.call([r'dist\ChurchPPT.exe','--selftest',r'dist\selftest.pptx']))"
if errorlevel 1 goto :fail
del dist\selftest.pptx

echo.
echo 완료! dist\ChurchPPT.exe 를 원하는 곳에 복사해서 실행하세요.
explorer dist
pause
exit /b 0

:fail
echo.
echo 오류가 발생했습니다. 위의 메시지를 확인하세요.
pause
exit /b 1
