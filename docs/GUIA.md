# Guia completo: Monstrinho do Barulho

> Visão geral, telas e estrutura do projeto: veja o [README](../README.md).

## 1. Gerar os instaladores (uma vez, num PC com Windows)
1. Instale o **Python 3 64 bits** (marque "Add Python to PATH") e o **Inno Setup 6.3+**
   (https://jrsoftware.org/isdl.php ou `winget install JRSoftware.InnoSetup`).
2. Dê dois cliques em **`scripts\gerar_instalador.bat`**. Ele instala as dependências e gera os programas com o PyInstaller.
   Depois gera os instaladores.
3. Na pasta `release\` ficam:
   - **`Instalar_Monstrinho_Professor.exe`**: para o PC do professor
   - **`Instalar_Monstrinho_Aluno.exe`**: para cada PC de aluno

## 2. PC do professor
1. Instale o **Veyon** com o componente *Veyon Master* (os alunos precisam do Veyon também).
2. Rode `Instalar_Monstrinho_Professor.exe`. As telas são: boas-vindas → informações e requisitos →
   pasta → atalhos (Área de Trabalho, abrir com o Windows) → instalar → concluir.
   - Avisa se o Veyon não estiver instalado.
   - Libera a porta TCP 5000 no firewall sozinho.
   - Não precisa instalar o Python.
3. Abra o painel e anote o **CÓDIGO DO PAINEL** (caixa roxa no topo, ex.: `30AG-03A`).

A configuração fica em `C:\ProgramData\Monstrinho\config_professor.json`. Ali também fica a
**identidade do painel**, que é mantida mesmo se você desinstalar e instalar de novo.

## 3. PCs dos alunos
1. Rode `Instalar_Monstrinho_Aluno.exe` (pede senha de administrador). As telas são: boas-vindas →
   **regras de uso** ("Eu aceito") → **pasta** → instalar → concluir.
2. Na última tela deixe marcado "Abrir agora". O programa **pede o código do painel**.
   Digite o código e clique em **Conectar**: ele testa a conexão e salva.
   - **Procurar na rede** acha o painel sozinho e mostra o nome do PC do professor.
   - Também aceita o IP ou o nome do PC do professor.
3. Pronto. A partir daí:
   - **Ele abre sozinho sempre que o computador liga**, para qualquer usuário (registro do Windows;
     o aluno não consegue tirar da inicialização).
   - **Ele procura o painel na rede desde o boot.** Enquanto procura, a janelinha mostra "procurando...".
   - **Se o IP do professor mudar, ele reencontra o MESMO painel sozinho** (pela identidade) e salva
     o novo endereço. Não precisa reconfigurar e ele não conecta no painel de outra sala.

Para trocar de professor/sala: Menu Iniciar → *Monstrinho do Barulho* → **Configurar código do painel**.
A configuração fica em `C:\ProgramData\Monstrinho\config_aluno.ini`.

*Sem instalador:* `scripts\gerar_exe_aluno.bat` gera a pasta `dist\portatil` (copie para o aluno e rode `instalar_no_aluno.bat`).
Nesse caso o painel pode rodar direto do código: `py -m pip install -r requirements.txt` e `py src\servidor_veyon.py`.

## 4. No dia a dia
- **▶ Iniciar aula**: começa o cronômetro com os minutos digitados (padrão 45).
  Faltando 5 min, os alunos recebem um alerta grande e piscando por 20 s.
  Em 00:00 as telas travam e só destravam pelo professor.
- **↻ Reiniciar e liberar**: recomeça o cronômetro, destrava as telas e zera os avisos.
- **■ Parar**: cancela o cronômetro (e destrava se a trava era de fim de aula).
- **🔓 LIBERAR TELAS AGORA**: destrava a qualquer momento, inclusive após o fim da aula.
- **Barulho**: cada vez que passa do limite, respeitando o intervalo, gera um aviso.
  Depois do máximo de avisos, cada nova vez trava **30 s → 1 min → 2 min → 2 min…** e destrava sozinho.
  Após "ficha limpa" minutos sem avisos (padrão 15), tudo volta ao zero.
- **Zerar avisos**: volta a progressão ao zero manualmente.
- Clique em **💾 Salvar alterações** depois de mudar computadores/regras (a sensibilidade vale na hora).
  Tudo fica salvo em `config_professor.json`.
- Abra o painel antes da aula: os alunos se conectam sozinhos em poucos segundos.

## 5. As telas não travam? (Veyon)
1. No painel, clique em **🩺 Diagnóstico do Veyon**. Ele mostra a saída completa do `veyon-cli`:
   versão, lista de recursos, chaves, e um teste que trava o 1º computador da lista por 5 s.
   Todo comando de travar/destravar também aparece no **Registro** como `Veyon OK` ou `Veyon FALHOU`.
2. **Nome do recurso**: o nome no campo "Recurso de travamento" precisa aparecer na lista
   "Recursos disponíveis" do diagnóstico. Se for diferente, copie o nome exato para o campo.
3. **Autenticação** (causa mais comum): o `veyon-cli` usa o mesmo método do Veyon Master.
   - Com **arquivos de chave**: crie o par de chaves no PC do professor
     (Veyon Configurator > Chaves de autenticação), importe a chave **pública** em todos os alunos
     e use o mesmo nome de chave nos dois lados.
   - O usuário do professor precisa ter acesso à chave privada. Para testar, abra o painel
     "como administrador".
   - Primeiro confirme que o **Veyon Master** consegue bloquear a tela pela própria janela dele.
     Se nem ele consegue, o problema está na configuração do Veyon, não no painel.
4. **Teste manual** num Prompt de Comando do PC do professor:
   `"C:\Program Files\Veyon\veyon-cli.exe" feature start NOME-DO-PC ScreenLock`
5. **Lista de computadores**: use o mesmo nome ou IP que aparece no Veyon Master.
   A lista agora vale assim que você digita.
