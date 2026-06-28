@echo off
rem wiki.cmd - launcher on PATH. Resolves the repo's tools\wiki.pyz relative to
rem this script and runs it with the Python launcher (py) or python.
setlocal enableextensions

set "BIN=%~dp0"
for %%I in ("%BIN%..") do set "ROOT=%%~fI"
set "PYZ=%ROOT%\tools\wiki.pyz"

if not exist "%PYZ%" (
  echo wiki: cannot find "%PYZ%". 1>&2
  echo Build it once with: python "%ROOT%\tools\build_pyz.py" 1>&2
  exit /b 1
)

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%PYZ%" %*
  exit /b %errorlevel%
)
where python >nul 2>nul
if %errorlevel%==0 (
  python "%PYZ%" %*
  exit /b %errorlevel%
)
echo wiki: no python interpreter found on PATH. 1>&2
exit /b 1
