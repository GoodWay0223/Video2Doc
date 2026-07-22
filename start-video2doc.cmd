@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 goto try_py
python -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto run_python

:try_py
where py >nul 2>&1
if errorlevel 1 goto missing_python
py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto run_py

:missing_python
echo [Video2Doc] 未找到 Python 3.10 或更高版本。
echo 请从 https://www.python.org/downloads/windows/ 安装 Python，并勾选 "Add Python to PATH"。
exit /b 1

:run_py
py -3 webui.py %*
exit /b %errorlevel%

:run_python
python webui.py %*
exit /b %errorlevel%
