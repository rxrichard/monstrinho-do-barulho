# Histórico de versões

## 2.1
- Instalador do **painel do professor** (sem precisar de Python), com aviso se o Veyon não estiver instalado.
- O programa do aluno **abre com o Windows e procura o painel desde o boot**.
- **Identidade do painel**: se o IP do professor mudar, o aluno reencontra o mesmo painel sozinho
  e nunca conecta no painel de outra sala.
- Nova rota `GET /info`. O anúncio UDP agora leva a identidade e o nome do PC.
- Testes automatizados (pytest) e GitHub Actions que gera os instaladores.

## 2.0
- **Travamentos progressivos**: 30 s → 1 min → 2 min, com destrave automático e "ficha limpa".
- Cronômetro com **alerta de 5 minutos** e trava automática em 00:00.
- Painel do professor com tema escuro, medidor de som em segmentos e registro colorido.
- Monstrinho desenhado em vetor, com 5 expressões e animação.
- Janelinha do aluno discreta, acima do relógio do Windows.
- **Código do painel**: o aluno digita um código curto na primeira abertura.
- Instalador do aluno (Inno Setup) com regras de uso.
- Diagnóstico do Veyon com a saída completa do `veyon-cli`.

## 1.0
- Versão original: monitor de barulho, avisos do monstrinho e trava pelo Veyon.
