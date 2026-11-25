@echo off
REM ============================================================
REM  Versão SEM instalador do programa do aluno (cópia manual).
REM  Gera dist\portatil\ com: MonstrinhoAluno.exe, config_aluno.ini
REM  e instalar_no_aluno.bat. Copie essa pasta para cada PC de aluno
REM  e rode instalar_no_aluno.bat como administrador.
REM  (Recomendado: usar o instalador -> scripts\gerar_instalador.bat)
REM ============================================================
chcp 65001 >nul
REM Roda a partir da raiz do repositório
cd /d "%~dp0.."

set PY=python
where py >nul 2>nul && set PY=py -3

echo [1/3] Instalando/atualizando o PyInstaller...
%PY% -m pip install --upgrade pyinstaller || goto erro

echo [2/3] Gerando o executavel...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name MonstrinhoAluno --icon installer\monstrinho.ico src\cliente_aluno.pyw || goto erro

echo [3/3] Montando a pasta dist\portatil...
if not exist dist\portatil mkdir dist\portatil
copy /Y dist\MonstrinhoAluno.exe dist\portatil\ >nul
copy /Y scripts\config_aluno.ini dist\portatil\ >nul
copy /Y scripts\instalar_no_aluno.bat dist\portatil\ >nul

echo.
echo PRONTO! Copie a pasta dist\portatil para cada PC de aluno.
pause
exit /b 0

:erro
echo.
echo ERRO ao gerar o executavel. Veja as mensagens acima.
pause
exit /b 1
