@echo off
cd /d "%~dp0"
title Buscador Google Maps - Servidor

rem ===== se a porta 8000 ja estiver em uso, so abrir o navegador =====
netstat -ano | findstr ":8000" | findstr "LISTENING" > nul
if not errorlevel 1 (
    echo Servidor ja esta rodando. Abrindo navegador...
    start "" "http://localhost:8000"
    exit /b 0
)

rem ===== descobre o comando Python =====
where python > nul
if not errorlevel 1 set "PYCMD=python"
where py > nul
if not defined PYCMD set "PYCMD=py -3"

rem ===== 1/3 ambiente virtual =====
if exist "venv\Scripts\python.exe" goto dep
echo [1/3] Criando ambiente virtual (primeira vez)...
%PYCMD% -m venv venv
if errorlevel 1 goto falha

:dep
echo [2/3] Verificando dependencias...
"venv\Scripts\python.exe" -m pip install --quiet -r requirements-web.txt
if errorlevel 1 goto falha

rem ===== 3/3 navegador Chromium =====
set "MSPW=%LocalAppData%\ms-playwright"
if exist "%MSPW%\chromium-*" goto cok
if exist "%MSPW%\chromium_headless_shell-*" goto cok
echo [3/3] Baixando o Chromium (primeira vez, pode demorar)...
"venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto falha

:cok
echo.
echo ==============================================
echo   Servidor no ar!
echo   Local:  http://localhost:8000
echo   Rede:   http://IP_DESTA_MAQUINA:8000
echo ==============================================
echo   Para PARAR basta fechar esta janela.
echo ==============================================
echo.
start "" "http://localhost:8000"
"venv\Scripts\python.exe" webapp.py
pause
exit /b 0

:falha
echo.
echo [ERRO] Algo deu errado. Leia as mensagens acima.
pause
exit /b 1