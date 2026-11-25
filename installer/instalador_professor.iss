; =====================================================================
;  Instalador do Monstrinho do Barulho - PAINEL DO PROFESSOR
;  Compile com o Inno Setup 6.3+ (https://jrsoftware.org/isdl.php)
;  ou rode  scripts\gerar_instalador.bat  (gera os dois instaladores).
;  Antes, a pasta dist\MonstrinhoProfessor\ precisa existir (PyInstaller).
; =====================================================================

#define AppNome    "Monstrinho do Barulho - Professor"
#define AppCurto   "Monstrinho do Barulho"
#define AppVersao  "2.1"
#define AppExe     "MonstrinhoProfessor.exe"

[Setup]
; Todos os caminhos abaixo são relativos à raiz do repositório
SourceDir=..
AppId={{4E1B7A9C-6D2F-4C8A-B3E5-91F0A7C2D684}
AppName={#AppNome}
AppVersion={#AppVersao}
AppVerName={#AppNome} {#AppVersao}
VersionInfoVersion=2.1.0.0
DefaultDirName={autopf}\Monstrinho do Barulho Professor
DefaultGroupName={#AppCurto}
DisableProgramGroupPage=yes
InfoBeforeFile=installer\informacoes_professor.txt
OutputDir=release
OutputBaseFilename=Instalar_Monstrinho_Professor
SetupIconFile=installer\monstrinho.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppNome}
WizardStyle=modern
WizardImageFile=installer\imagens\professor_lateral_100.bmp,installer\imagens\professor_lateral_125.bmp,installer\imagens\professor_lateral_150.bmp,installer\imagens\professor_lateral_175.bmp,installer\imagens\professor_lateral_200.bmp
WizardSmallImageFile=installer\imagens\professor_topo_100.bmp,installer\imagens\professor_topo_125.bmp,installer\imagens\professor_topo_150.bmp,installer\imagens\professor_topo_175.bmp,installer\imagens\professor_topo_200.bmp
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
ptbr.WelcomeLabel1=Bem-vindo ao instalador do%nPainel do Professor
ptbr.WelcomeLabel2=Este assistente vai instalar o PAINEL DO PROFESSOR do {#AppCurto} neste computador.%n%nO painel mede o barulho da sala pelo microfone, mostra os avisos do monstrinho nos computadores dos alunos, controla o cronômetro da aula e trava as telas pelo Veyon.%n%nNão é preciso instalar o Python: tudo já vem incluído.
ptbr.FinishedHeadingLabel=Painel instalado!
ptbr.FinishedLabel=O painel do professor foi instalado.%n%nAo abrir, anote o CÓDIGO DO PAINEL (caixa roxa no topo) para digitar na primeira abertura do programa de cada aluno.

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"
Name: "iniciar"; Description: "Abrir o painel automaticamente quando o Windows iniciar"; GroupDescription: "Atalhos:"; Flags: unchecked

[Dirs]
; Configuração do painel (e a identidade que os alunos usam para reencontrá-lo)
Name: "{commonappdata}\Monstrinho"; Permissions: users-modify

[Files]
Source: "dist\MonstrinhoProfessor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installer\informacoes_professor.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "docs\GUIA.md"; DestDir: "{app}"; DestName: "LEIA-ME.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\Painel do Professor"; Filename: "{app}\{#AppExe}"
Name: "{group}\Leia-me (ajuda)"; Filename: "{app}\LEIA-ME.txt"
Name: "{group}\Desinstalar o Painel do Professor"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Monstrinho - Painel"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{commonstartup}\Monstrinho - Painel"; Filename: "{app}\{#AppExe}"; Tasks: iniciar

[Run]
; Firewall: os alunos consultam o painel pela porta TCP 5000
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppNome}"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppNome}"" dir=in action=allow program=""{app}\{#AppExe}"" protocol=TCP localport=5000 enable=yes"; Flags: runhidden
Filename: "{app}\{#AppExe}"; Description: "Abrir o painel agora"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "FecharPainel"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppNome}"""; Flags: runhidden; RunOnceId: "FirewallPainel"

; Obs.: C:\ProgramData\Monstrinho\config_professor.json NÃO é apagado na
; desinstalação: ele guarda a identidade do painel. Assim, reinstalando, os
; alunos continuam encontrando este professor sem reconfigurar.

[Code]
function VeyonInstalado(): Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf64}\Veyon\veyon-cli.exe')) or
            FileExists(ExpandConstant('{commonpf32}\Veyon\veyon-cli.exe'));
end;

// Avisa (sem impedir) se o Veyon não estiver instalado
function InitializeSetup(): Boolean;
begin
  Result := True;
  if not VeyonInstalado() then
    Result := MsgBox('O Veyon não foi encontrado neste computador.' + #13#10 + #13#10 +
      'Sem ele o painel funciona (monstrinho e cronômetro), mas NÃO consegue ' +
      'travar as telas dos alunos.' + #13#10 + #13#10 +
      'Instale o Veyon com o componente "Veyon Master" (https://veyon.io).' + #13#10 + #13#10 +
      'Continuar a instalação mesmo assim?', mbConfirmation, MB_YESNO) = IDYES;
end;

// Fecha o painel se estiver aberto (atualização por cima da versão antiga)
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Codigo: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE,
       ewWaitUntilTerminated, Codigo);
  Result := '';
end;
