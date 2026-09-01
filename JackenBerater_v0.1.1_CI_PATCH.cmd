@echo off
setlocal EnableExtensions

if "%~1"=="" (
  echo.
  echo JackenBerater v0.1.1 CI-Patch
  echo --------------------------------
  echo Ziehe deinen lokalen GitHub-Repository-Ordner auf diese CMD-Datei.
  echo Beispiel: den Ordner "Jackenberater" auf diese Datei ziehen.
  echo.
  pause
  exit /b 1
)

set "REPO=%~1"
set "TARGET=%REPO%\custom_components\jackenberater"

if not exist "%TARGET%" (
  echo.
  echo FEHLER: "%TARGET%" wurde nicht gefunden.
  echo Bitte den Stammordner deines JackenBerater-GitHub-Repositories auf die CMD-Datei ziehen.
  echo.
  pause
  exit /b 2
)

echo.
echo JackenBerater v0.1.1 CI-Patch
echo Repository: %REPO%
echo.

if exist "%TARGET%\strings.json" (
  del /f /q "%TARGET%\strings.json"
  echo [OK] Alte strings.json entfernt.
) else (
  echo [OK] strings.json war bereits entfernt.
)

for /r "%TARGET%" %%F in (*.pyc) do (
  del /f /q "%%F" >nul 2>&1
)

for /d /r "%TARGET%" %%D in (__pycache__) do (
  if exist "%%D" rd /s /q "%%D" >nul 2>&1
)

if exist "%TARGET%\translations\en.json" (
  echo [OK] translations\en.json vorhanden.
) else (
  echo [WARNUNG] translations\en.json fehlt.
)

if exist "%TARGET%\translations\de.json" (
  echo [OK] translations\de.json vorhanden.
) else (
  echo [WARNUNG] translations\de.json fehlt.
)

if exist "%TARGET%\brand\icon.png" (
  echo [OK] brand\icon.png vorhanden.
) else (
  echo [WARNUNG] brand\icon.png fehlt.
)

where git >nul 2>&1
if %errorlevel%==0 (
  echo.
  echo Git-Status:
  git -C "%REPO%" status --short
)

echo.
echo Fertig.
echo Jetzt GitHub Desktop oeffnen, die Loeschung committen und Push origin ausfuehren.
echo.
pause
