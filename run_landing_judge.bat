@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Run Landing Judge using a local Python 3.12 virtual environment
rem - Creates .venv if missing
rem - Installs dependencies
rem - Starts the server and shows console logs

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul

rem Default port; will be overridden by .env if present
set "PORT=5010"
if exist ".env" (
  rem Parse .env for PORT=... (ignore lines starting with '#')
  for /f "usebackq tokens=1,* delims== eol=#" %%A in (".env") do (
    set "k=%%~A"
    set "v=%%~B"
    if /I "!k!"=="PORT" (
      rem Assign raw value and trim basic whitespace
      for /f "tokens=*" %%P in ("!v!") do set "PORT=%%P"
    )
  )
)

rem Strip single/double quotes if present (from .env values like PORT='5010')
set "PORT=%PORT:"=%"
set "PORT=%PORT:'=%"

rem Default to silent mode unless --debug is passed
set "SILENT=1"
if /I "%~1"=="--debug" set "SILENT=0"

rem Launch themed non-interactive splash in silent mode; auto-closes when ready flag appears
if "%SILENT%"=="1" (
  set "READY_FLAG=%TEMP%\landing_judge_ready.flag"
  if exist "%READY_FLAG%" del /q "%READY_FLAG%" >nul 2>&1
  powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command ^
    "Start-Process -FilePath 'powershell' -ArgumentList '-NoProfile -ExecutionPolicy Bypass -STA -File ""%SCRIPT_DIR%splash.ps1"" -FlagPath ""%READY_FLAG%""' -WindowStyle Hidden"
)

rem Detect if an environment is already active; if so, use it and skip setup
set "USING_CURRENT=0"
if defined USE_CURRENT_ENV (
  if "%SILENT%"=="0" echo [setup] Forcing use of current shell environment (USE_CURRENT_ENV=1)
  set "USING_CURRENT=1"
)
if defined VIRTUAL_ENV (
  if "%SILENT%"=="0" echo [setup] Detected active virtual environment: %VIRTUAL_ENV%
  set "USING_CURRENT=1"
)

if "%USING_CURRENT%"=="0" (
  set "VENV_PY=.\.venv\Scripts\python.exe"
  if not exist "%VENV_PY%" (
    if "%SILENT%"=="1" (
      powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command ^
        "$ErrorActionPreference='SilentlyContinue';" ^
        "$scriptDir=[System.IO.Path]::GetFullPath('%SCRIPT_DIR%');" ^
        "$venvDir=Join-Path $scriptDir '.venv';" ^
        "try { & py -3.12 -m venv $venvDir } catch { & python -m venv $venvDir }"
    ) else (
      echo [setup] Creating Python 3.12 virtual environment at .venv ...
      py -3.12 -m venv .venv 2>nul
      if not exist "%VENV_PY%" (
        echo [setup] Python launcher 'py' not available or 3.12 missing. Trying 'python'...
        python -m venv .venv 2>nul
      )
    )
  )

  if not exist "%VENV_PY%" (
    echo [error] Could not create .venv. Ensure Python 3.12 is installed.
    echo         Try: winget install Python.Python.3.12
    exit /b 1
  )

  if "%SILENT%"=="1" (
    powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command ^
      "$ErrorActionPreference='Stop'; $scriptDir=[System.IO.Path]::GetFullPath('%SCRIPT_DIR%'); $venvPy=Join-Path $scriptDir '.venv\\Scripts\\python.exe'; & $venvPy -m pip install --upgrade pip wheel; & $venvPy -m pip install -r (Join-Path $scriptDir 'requirements.txt');"
  ) else (
    echo [setup] Upgrading pip and installing dependencies...
    "%VENV_PY%" -m pip install --upgrade pip wheel || (
      echo [error] pip upgrade failed. Check Python and network connectivity.
      exit /b 1
    )
    "%VENV_PY%" -m pip install -r requirements.txt || (
      echo [error] requirements install failed. Inspect error above.
      exit /b 1
    )
  )
)

if "%SILENT%"=="0" (
  echo ============================================================
  echo 🛬 Landing Judge — starting on http://127.0.0.1:%PORT%
  echo Open overlay: http://127.0.0.1:%PORT%/overlay
  echo ============================================================
)

rem Prefer running inside an activated venv environment; fallback to direct venv python
set "PYTHONUNBUFFERED=1"
if not defined VENV_WPY set "VENV_WPY=.\.venv\Scripts\pythonw.exe"

set "RUNNER="
if "%USING_CURRENT%"=="1" (
  if "%SILENT%"=="0" echo [setup] Using already-activated environment Python: %VIRTUAL_ENV%
  set "RUNNER=pythonw"
) else (
  set "ACTIVATED=0"
  if exist ".\.venv\Scripts\activate.bat" (
    if "%SILENT%"=="0" echo [setup] Activating virtual environment...
    call ".\.venv\Scripts\activate.bat"
    set "ACTIVATED=1"
  )
  if "%ACTIVATED%"=="1" (
    set "RUNNER=pythonw"
  ) else (
    if exist "%VENV_WPY%" (
      set "RUNNER=%VENV_WPY%"
    ) else if exist "%VENV_PY%" (
      set "RUNNER=%VENV_PY%"
    ) else (
      echo [error] Virtual environment Python not found at "%VENV_PY%".
      echo         Ensure .venv exists or activate a Python environment and rerun.
      exit /b 1
    )
  )
)

  if "%SILENT%"=="1" (
    rem Detach and hide console while starting the app
    powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command ^
    "Start-Process -FilePath '%RUNNER%' -ArgumentList '""%SCRIPT_DIR%main.py""' -WorkingDirectory '%SCRIPT_DIR%' -WindowStyle Normal;" ^
    "$flag=[System.IO.Path]::Combine($env:TEMP,'landing_judge_ready.flag'); $url='http://127.0.0.1:%PORT%/overlay'; $deadline=(Get-Date).AddSeconds(30); while((Get-Date) -lt $deadline){ try { Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Milliseconds 500 } }; New-Item -ItemType File -Path $flag -Force | Out-Null"
    goto end
  ) else (
    "%RUNNER%" "%SCRIPT_DIR%main.py"
  )

:end
popd >nul
endlocal
exit /b 0