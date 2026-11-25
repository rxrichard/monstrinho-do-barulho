@echo off
REM ============================================================
REM  Instala o Monstrinho no PC do aluno e faz abrir com o Windows.
REM  Coloque este .bat junto com MonstrinhoAluno.exe e config_aluno.ini
REM  e execute COMO ADMINISTRADOR (botao direito > Executar como admin).
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"
set DESTINO=%ProgramData%\Monstrinho
set INICIAR=%ProgramData%\Microsoft\Windows\Start Menu\Programs\StartUp

taskkill /IM MonstrinhoAluno.exe /F >nul 2>nul
if not exist "%DESTINO%" mkdir "%DESTINO%"
copy /Y MonstrinhoAluno.exe "%DESTINO%\" || goto erro
REM so copia o .ini se ainda nao existir (preserva IP ja configurado)
if not exist "%DESTINO%\config_aluno.ini" copy /Y config_aluno.ini "%DESTINO%\" >nul

powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%INICIAR%\Monstrinho.lnk'); $s.TargetPath='%DESTINO%\MonstrinhoAluno.exe'; $s.WorkingDirectory='%DESTINO%'; $s.Save()" || goto erro

start "" "%DESTINO%\MonstrinhoAluno.exe"
echo Instalado em %DESTINO% e configurado para abrir com o Windows.
pause
exit /b 0
:erro
echo ERRO na instalacao (executou como administrador?).
pause
exit /b 1
