; =====================================================================
;  Instalador do Monstrinho do Barulho - PROGRAMA DO ALUNO
;  Compile com o Inno Setup 6.3+ (https://jrsoftware.org/isdl.php)
;  ou rode  scripts\gerar_instalador.bat  (gera os dois instaladores).
;  Antes, dist\MonstrinhoAluno.exe precisa existir (PyInstaller).
; =====================================================================

#define AppNome    "Monstrinho do Barulho"
#define AppVersao  "2.1"
#define AppExe     "MonstrinhoAluno.exe"

[Setup]
; Todos os caminhos abaixo são relativos à raiz do repositório
SourceDir=..
AppId={{8C5D2B1E-3F4A-4E7B-9C61-2A7D5E9F1B34}
AppName={#AppNome}
AppVersion={#AppVersao}
AppVerName={#AppNome} {#AppVersao}
VersionInfoVersion=2.1.0.0
DefaultDirName={autopf}\{#AppNome}
DefaultGroupName={#AppNome}
DisableProgramGroupPage=yes
LicenseFile=installer\regras_de_uso.txt
OutputDir=release
OutputBaseFilename=Instalar_Monstrinho_Aluno
SetupIconFile=installer\monstrinho.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppNome} (aluno)
WizardStyle=modern
WizardImageFile=installer\imagens\aluno_lateral_100.bmp,installer\imagens\aluno_lateral_125.bmp,installer\imagens\aluno_lateral_150.bmp,installer\imagens\aluno_lateral_175.bmp,installer\imagens\aluno_lateral_200.bmp
WizardSmallImageFile=installer\imagens\aluno_topo_100.bmp,installer\imagens\aluno_topo_125.bmp,installer\imagens\aluno_topo_150.bmp,installer\imagens\aluno_topo_175.bmp,installer\imagens\aluno_topo_200.bmp
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
ptbr.WelcomeLabel1=Bem-vindo ao instalador do%n{#AppNome}
ptbr.WelcomeLabel2=Este assistente vai instalar o programa do ALUNO neste computador.%n%nEle abre sozinho sempre que o computador liga, procura o painel do professor na rede e mostra o tempo da aula logo acima do relógio.%n%nNa primeira abertura, tenha em mãos o CÓDIGO DO PAINEL que aparece no topo do painel do professor.
ptbr.FinishedHeadingLabel=Instalação concluída!
ptbr.FinishedLabel=O {#AppNome} foi instalado.%n%nAo abrir, ele pede o CÓDIGO DO PAINEL do professor. Depois disso, ele abre sozinho em todo login e reencontra o painel mesmo se o IP do professor mudar.

[Dirs]
; Configuração compartilhada por todos os usuários (alunos podem alterar)
Name: "{commonappdata}\Monstrinho"; Permissions: users-modify

[Files]
Source: "dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "installer\regras_de_uso.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppNome}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Configurar código do painel"; Filename: "{app}\{#AppExe}"; Parameters: "--configurar"
Name: "{group}\Regras de uso"; Filename: "{app}\regras_de_uso.txt"
Name: "{group}\Desinstalar {#AppNome}"; Filename: "{uninstallexe}"

[Registry]
; Abre SEMPRE que qualquer usuário entra no Windows (aluno comum não consegue remover)
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "MonstrinhoAluno"; ValueData: """{app}\{#AppExe}"""; Flags: uninsdeletevalue

[Run]
; Firewall: deixa o programa ouvir o anúncio do painel (UDP 5001) - é assim
; que ele procura o professor na rede ao ligar o computador.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppNome}"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppNome}"" dir=in action=allow program=""{app}\{#AppExe}"" protocol=UDP localport=5001 enable=yes"; Flags: runhidden
; Última tela: abre o programa (como o usuário logado) para pedir o código
Filename: "{app}\{#AppExe}"; Description: "Abrir agora e informar o código do painel"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "FecharMonstrinho"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppNome}"""; Flags: runhidden; RunOnceId: "FirewallMonstrinho"

[UninstallDelete]
Type: files; Name: "{commonappdata}\Monstrinho\config_aluno.ini"

[Code]
// Fecha o programa se ele estiver aberto (atualização por cima da versão antiga)
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Codigo: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '', SW_HIDE,
       ewWaitUntilTerminated, Codigo);
  Result := '';
end;
