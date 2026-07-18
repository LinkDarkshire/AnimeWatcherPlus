@echo off
setlocal enabledelayedexpansion

rem Builds an installable AnimeWatcherPlus release: PyInstaller-freezes the
rem Python core into the Tauri sidecar location, builds the frontend, then
rem lets `cargo tauri build` produce a signed NSIS installer + update
rem manifest. Only rebuild the pieces that actually changed by commenting
rem out the corresponding step below -- each is independent.
rem
rem Output (never committed -- see .gitignore) lands under
rem shell\src-tauri\target\release\bundle\nsis\.

set ROOT=%~dp0
set CORE_DIR=%ROOT%core
set UI_DIR=%ROOT%shell\ui
set SHELL_DIR=%ROOT%shell
set BINARIES_DIR=%SHELL_DIR%\src-tauri\binaries
set TARGET_TRIPLE=x86_64-pc-windows-msvc

if not defined TAURI_SIGNING_PRIVATE_KEY (
    set TAURI_SIGNING_PRIVATE_KEY=%USERPROFILE%\.awp-secrets\awp-updater.key
)
if not exist "%TAURI_SIGNING_PRIVATE_KEY%" (
    echo [FEHLER] Updater-Signierschluessel nicht gefunden: %TAURI_SIGNING_PRIVATE_KEY%
    echo Einmalig erzeugen mit: cargo tauri signer generate -w "%TAURI_SIGNING_PRIVATE_KEY%" --ci
    echo Danach erneut versuchen.
    exit /b 1
)
rem CI=true is required here even for a genuinely passwordless key -- without
rem it, `cargo tauri build` tries to interactively prompt for the key's
rem password and hangs forever in a non-interactive shell (this is a known
rem tauri-cli quirk, not something specific to this project).
set CI=true

echo.
echo [1/3] Baue Python-Core ^(PyInstaller^)...
cd /d "%CORE_DIR%"
call .venv\Scripts\python.exe -m PyInstaller core.spec --distpath "%BINARIES_DIR%" --noconfirm
if errorlevel 1 (
    echo [FEHLER] PyInstaller-Build fehlgeschlagen.
    exit /b 1
)
move /y "%BINARIES_DIR%\core.exe" "%BINARIES_DIR%\core-%TARGET_TRIPLE%.exe" >nul
if errorlevel 1 (
    echo [FEHLER] Konnte core.exe nicht zu core-%TARGET_TRIPLE%.exe umbenennen.
    exit /b 1
)

echo.
echo [2/3] Baue Frontend ^(Vite^)...
cd /d "%UI_DIR%"
call npm run build
if errorlevel 1 (
    echo [FEHLER] Frontend-Build fehlgeschlagen.
    exit /b 1
)

echo.
echo [3/3] Baue Tauri-Installer...
cd /d "%SHELL_DIR%"
call cargo tauri build
if errorlevel 1 (
    echo [FEHLER] Tauri-Build fehlgeschlagen.
    exit /b 1
)

echo.
echo ============================================
echo Build abgeschlossen.
echo ============================================
echo Installer:  %SHELL_DIR%\src-tauri\target\release\bundle\nsis\*.exe
echo Signatur:   %SHELL_DIR%\src-tauri\target\release\bundle\nsis\*.exe.sig
echo.
echo Naechste Schritte fuer ein Release ^(manuell, kein gh-CLI auf dieser Maschine^):
echo   1. Version in shell\src-tauri\tauri.conf.json hochzaehlen, falls noch nicht geschehen
echo   2. Neuen Release unter github.com/LinkDarkshire/AnimeWatcherPlus/releases/new anlegen
echo   3. Den .exe-Installer UND die .exe.sig-Datei als Release-Assets hochladen
echo   4. latest.json als weiteres Asset hochladen ^(Version, Notes, pub_date,
echo      platforms.windows-x86_64.signature = Inhalt der .sig-Datei,
echo      platforms.windows-x86_64.url = Download-Link des Installers^)
echo.

endlocal
