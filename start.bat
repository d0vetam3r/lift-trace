@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1

py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 goto run_py
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 goto run_python
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 goto run_python3

echo Lift Trace requires Python 3.10 or newer.
echo No compatible py, python, or python3 command was found.
echo Install or enable Python, then run this launcher again from a terminal.
set "LIFT_TRACE_EXIT=1"
goto finish

:run_py
py -3 server.py %*
set "LIFT_TRACE_EXIT=%ERRORLEVEL%"
goto finish

:run_python
python server.py %*
set "LIFT_TRACE_EXIT=%ERRORLEVEL%"
goto finish

:run_python3
python3 server.py %*
set "LIFT_TRACE_EXIT=%ERRORLEVEL%"

:finish
popd
exit /b %LIFT_TRACE_EXIT%
