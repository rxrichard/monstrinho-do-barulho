@echo off
REM ============================================================
REM  Gera OS DOIS INSTALADORES:
REM    release\Instalar_Monstrinho_Professor.exe
REM    release\Instalar_Monstrinho_Aluno.exe
REM  Precisa (no Windows): Python 3 (64 bits) e Inno Setup 6.3+
REM     Inno Setup: https://jrsoftware.org/isdl.php
REM     ou: winget install JRSoftware.InnoSetup
REM ============================================================
chcp 65001 >nul
REM Roda a partir da raiz do repositório
cd /d "%~dp0.."

set PY=python
where py >nul 2>nul && set PY=py -3

echo [1/5] Instalando dependencias (PyInstaller, Flask, numpy, sounddevice)...
%PY% -m pip install --upgrade pyinstaller -r requirements.txt || goto erro

echo [2/5] Gerando o programa do ALUNO (dist\MonstrinhoAluno.exe)...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name MonstrinhoAluno --icon installer\monstrinho.ico src\cliente_aluno.pyw || goto erro

echo [3/5] Gerando o PAINEL DO PROFESSOR (dist\MonstrinhoProfessor\)...
%PY% -m PyInstaller --noconfirm --clean --onedir --windowed --name MonstrinhoProfessor --icon installer\monstrinho.ico src\servidor_veyon.py || goto erro

set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC goto sem_inno

echo [4/5] Gerando o instalador do PROFESSOR...
%ISCC% installer\instalador_professor.iss || goto erro
echo [5/5] Gerando o instalador do ALUNO...
%ISCC% installer\instalador_aluno.iss || goto erro

echo.
echo PRONTO! Os instaladores estao na pasta "release":
echo    Instalar_Monstrinho_Professor.exe  - no PC do professor
echo    Instalar_Monstrinho_Aluno.exe      - em cada PC de aluno
pause
exit /b 0

:sem_inno
echo.
echo O Inno Setup 6 nao foi encontrado.
echo Instale em https://jrsoftware.org/isdl.php e rode este arquivo de novo.
echo Os programas sem instalador ja estao na pasta dist.
pause
exit /b 1

:erro
echo.
echo ERRO ao gerar. Veja as mensagens acima.
pause
exit /b 1
