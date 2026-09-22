@echo off
rem ============================================================
rem  Empacota o servidor web em um UNICO .exe (PyInstaller)
rem  O .exe final carrega Flask + Playwright + Chromium embutido,
rem  entao funciona em qualquer PC SEM instalar nada.
rem ============================================================
cd /d "%~dp0"
title Empacotar Buscador Google Maps (.exe)

setlocal

rem ---- garante venv ----
if not exist "venv\Scripts\python.exe" (
    echo [1/4] Criando ambiente virtual...
    python -m venv venv || py -3 -m venv venv || goto falha
)

echo [2/4] Instalando dependencias + PyInstaller...
"venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
"venv\Scripts\python.exe" -m pip install --quiet -r requirements-web.txt pyinstaller
if errorlevel 1 goto falha

echo [3/4] Baixando o Chromium headless (usado pelo servidor)...
"venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto falha

rem ---- localiza a pasta do chromium headless baixado ----
set "PW=%LocalAppData%\ms-playwright"
for /d %%d in ("%PW%\chromium_headless_shell-*") do set "HS=%%~fd"

if not defined HS (
    echo [ERRO] Nao achei o chromium_headless_shell em "%PW%".
    goto falha
)
for %%d in ("%HS%") do set "HSN=%%~nxd"
echo     Chromium headless: %HSN%

echo [4/4] Gerando o executavel (pode demorar alguns minutos)...
rmdir /s /q build 2>nul
del /q "Buscador_Google_Maps.exe" 2>nul

"venv\Scripts\pyinstaller.exe" --noconfirm --onefile --windowed ^
  --name "Buscador_Google_Maps" ^
  --add-data "%HS%;browsers\%HSN%" ^
  --add-data "templates;templates" ^
  --collect-all playwright ^
  --hidden-import waitress ^
  webapp.py
if errorlevel 1 goto falha

rem ---- copia o exe pra raiz ----
copy /y "dist\Buscador_Google_Maps.exe" "Buscador_Google_Maps.exe" >nul
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

echo.
echo ==============================================
echo   PRONTO! Envie o arquivo:
echo       Buscador_Google_Maps.exe
echo   (funciona em qualquer Windows, sem instalar nada)
echo ==============================================
pause
exit /b 0

:falha
echo.
echo [ERRO] Algo deu errado. Leia as mensagens acima.
pause
exit /b 1