# -*- coding: utf-8 -*-
"""
=====================================================================
 MONSTRINHO DO BARULHO - Programa do Aluno  (cliente_aluno.pyw)
=====================================================================
Janelinha discreta, sem borda e sempre no topo, logo ACIMA DO RELÓGIO do
Windows (não cobre a barra de tarefas nem os botões das janelas). Mostra:
  * o tempo restante da aula            (GET /cronometro do painel);
  * os avisos do monstrinho desenhado   (GET /status_monstrinho);
  * um ALERTA grande e piscando quando faltam 5 minutos.

CONEXÃO COM O PROFESSOR
  * 1ª abertura: pede o CÓDIGO DO PAINEL (o IP do professor em 7 letras,
    ex.: 30AG-03A), testa a conexão e salva em config_aluno.ini
    (C:\\ProgramData\\Monstrinho, ou ao lado do programa na versão portátil).
  * Abre com o Windows e ESCUTA a rede desde o boot (anúncio UDP 5001 que o
    painel envia a cada 3 s). Se o professor mudar de IP, reencontra o
    MESMO painel pela identidade dele (/info) e atualiza o .ini sozinho.

LINHA DE COMANDO
    MonstrinhoAluno.exe --configurar      abre a tela do código de novo
    MonstrinhoAluno.exe --ip 10.0.0.5     ignora o .ini (testes)
=====================================================================
"""

import configparser
import json
import math
import os
import socket
import sys
import threading
import time
import tkinter as tk
import urllib.request

# ---------------------------------------------------------------------
# Valores padrão
# ---------------------------------------------------------------------
PORTA_PADRAO = 5000
PORTA_DESCOBERTA = 5001          # anúncio UDP do professor (modo auto)
PORTA_INSTANCIA_UNICA = 50555    # impede abrir duas janelas ao mesmo tempo

INTERVALO_CONSULTA = 1.0         # segundos entre consultas ao professor
TIMEOUT_HTTP = 2.0
FALHAS_PARA_SEM_CONEXAO = 3      # evita piscar "sem conexão" por 1 falha
FALHAS_PARA_ALERTA_VERMELHO = 60 # ~1 min procurando antes de mostrar em vermelho

# Tamanhos da janela (em pixels "de 100%"; são ajustados ao zoom do Windows)
TAM_MINI = (96, 34)          # só o relógio da aula
TAM_MONSTRINHO = (186, 205)  # relógio + monstrinho
TAM_ALERTA = (420, 230)      # alerta de 5 minutos
MARGEM = 6                   # distância da barra de tarefas / borda direita
TRANSPARENCIA_MINI = 0.92    # 1.0 = opaco

# Cores (tema escuro, igual ao painel do professor)
FUNDO = "#151c33"
BORDA = "#2f3a66"
TINTA = "#1d1530"            # texto escuro dentro do cartão colorido
CINZA = "#9aa3c7"
VERDE = "#4ade80"
LARANJA = "#fbbf24"
VERMELHO = "#f87171"
COR_TRANSPARENTE = "#010203"  # cor "chave" que o Windows deixa invisível
COR_MONSTRINHO_PADRAO = "#ffcc80"
CORES_ALERTA = ("#fde047", "#fb7185")  # pisca entre amarelo e vermelho

# O professor manda um emoji; aqui ele vira a expressão do monstrinho desenhado.
HUMORES = {"😠": "bravo", "😡": "furioso", "🤨": "desconfiado", "😈": "travesso", "⏰": "alarme"}
CORES_CORPO = {"bravo": "#ff8a3d", "furioso": "#ef4444", "desconfiado": "#f2b51f",
               "travesso": "#8b5cf6", "alarme": "#3b82f6"}

ARQUIVO_INI = "config_aluno.ini"
MODELO_INI = """; Configuração do Monstrinho do Barulho (aluno)
; Para trocar, abra "Configurar código do painel" no Menu Iniciar
; (ou rode: MonstrinhoAluno.exe --configurar).
; ip = IP ou nome do PC do professor, ou "auto" para usar qualquer painel da rede.
[professor]
ip = {ip}
porta = {porta}
; Identidade do painel (preenchida automaticamente). Serve para reencontrar
; o MESMO professor quando o IP dele muda, sem conectar no painel de outra sala.
painel_id = {painel_id}
pc = {pc}
"""


# ---------------------------------------------------------------------
# Código do painel  (o IP do professor escrito de um jeito fácil de digitar)
# ---------------------------------------------------------------------
# 32 bits do IP em 7 letras/números (base32 "Crockford": sem I, L, O e U,
# que se confundem). Ex.: 192.168.0.106 -> "30AG-03A". O painel do professor
# usa exatamente a mesma conta para mostrar o código.
ALFABETO_CODIGO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ip_para_codigo(ip):
    n = int.from_bytes(socket.inet_aton(ip), "big")
    letras = ""
    for _ in range(7):
        n, resto = divmod(n, 32)
        letras = ALFABETO_CODIGO[resto] + letras
    return f"{letras[:4]}-{letras[4:]}"


def codigo_para_ip(codigo):
    """Converte o código em IP. Devolve None se o texto não for um código."""
    c = codigo.upper().replace("-", "").replace(" ", "")
    c = c.replace("O", "0").replace("I", "1").replace("L", "1")
    if len(c) != 7 or any(ch not in ALFABETO_CODIGO for ch in c):
        return None
    n = 0
    for ch in c:
        n = n * 32 + ALFABETO_CODIGO.index(ch)
    if n >= 2 ** 32:
        return None
    return socket.inet_ntoa(n.to_bytes(4, "big"))


def interpretar_destino(texto):
    """Código, IP ou nome do PC -> endereço a usar. None se inválido."""
    t = texto.strip()
    if not t:
        return None
    if t.lower() == "auto":
        return "auto"
    ip = codigo_para_ip(t)
    if ip:
        return ip
    if all(ch.isalnum() or ch in ".-_" for ch in t):
        return t  # IP digitado ou nome do computador
    return None


# ---------------------------------------------------------------------
# Configuração (arquivo .ini)
# ---------------------------------------------------------------------
def pasta_do_programa():
    """Pasta do .exe (PyInstaller) ou do .pyw."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def caminhos_config():
    """Onde procurar/gravar o .ini, em ordem de preferência.

    1) ao lado do programa (instalação "portátil", copiando a pasta);
    2) C:\\ProgramData\\Monstrinho (instalação pelo instalador: em
       "Arquivos de Programas" o aluno não tem permissão de escrita).
    """
    caminhos = [os.path.join(pasta_do_programa(), ARQUIVO_INI)]
    for var in ("PROGRAMDATA", "APPDATA"):
        base = os.environ.get(var)
        if base:
            caminhos.append(os.path.join(base, "Monstrinho", ARQUIVO_INI))
    return caminhos


def arquivo_config_atual():
    return next((c for c in caminhos_config() if os.path.exists(c)), None)


def carregar_config():
    """Lê o .ini. Retorna um dict:
    ip ('' = automático), porta, painel_id, pc e configurado (True/False)."""
    cfg = {"ip": "", "porta": PORTA_PADRAO, "painel_id": "", "pc": "", "configurado": False}
    caminho = arquivo_config_atual()
    if caminho:
        cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
        try:
            cp.read(caminho, encoding="utf-8-sig")  # aceita arquivo salvo pelo Bloco de Notas
            cfg["ip"] = cp.get("professor", "ip", fallback="").strip()
            cfg["porta"] = cp.getint("professor", "porta", fallback=PORTA_PADRAO)
            cfg["painel_id"] = cp.get("professor", "painel_id", fallback="").strip()
            cfg["pc"] = cp.get("professor", "pc", fallback="").strip()
            cfg["configurado"] = bool(cfg["ip"])
        except (configparser.Error, ValueError, OSError):
            pass

    # Linha de comando tem prioridade
    args = sys.argv[1:]
    for i, arg in enumerate(args[:-1]):
        if arg == "--ip":
            cfg["ip"], cfg["configurado"] = args[i + 1].strip(), True
            cfg["painel_id"] = cfg["pc"] = ""
        elif arg == "--porta":
            try:
                cfg["porta"] = int(args[i + 1])
            except ValueError:
                pass

    if cfg["ip"].lower() == "auto":
        cfg["ip"] = ""
    return cfg


def salvar_config(ip, porta, painel_id="", pc=""):
    """Grava o .ini no primeiro lugar que aceitar. Retorna o caminho ou None."""
    # Arquivo já existente primeiro; senão ProgramData (vale para todos os
    # usuários do PC), depois a pasta do programa, depois o APPDATA.
    atual = arquivo_config_atual()
    caminhos = caminhos_config()
    candidatos = ([atual] if atual else []) + caminhos[1:2] + caminhos[:1] + caminhos[2:]
    texto = MODELO_INI.format(ip=ip or "auto", porta=porta, painel_id=painel_id, pc=pc)
    for caminho in candidatos:
        try:
            os.makedirs(os.path.dirname(caminho), exist_ok=True)
            with open(caminho, "w", encoding="utf-8") as f:
                f.write(texto)
            return caminho
        except OSError:
            continue
    return None


def ler_json(abridor, host, porta, rota, timeout=TIMEOUT_HTTP):
    with abridor.open(f"http://{host}:{porta}{rota}", timeout=timeout) as resp:
        dados = json.loads(resp.read().decode("utf-8"))
    if not isinstance(dados, dict):
        raise ValueError("resposta inesperada")
    return dados


def abridor_sem_proxy():
    """Ignora proxies do Windows: o professor está na rede local."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ---------------------------------------------------------------------
# Comunicação com o professor (roda em threads; nunca mexe na tela)
# ---------------------------------------------------------------------
class Conexao:
    """Fala com o painel do professor e o REENCONTRA sozinho se ele mudar de IP.

    * Consulta o endereço salvo a cada segundo.
    * Escuta SEMPRE o anúncio que o painel faz na rede (UDP 5001, a cada 3 s).
    * Se o endereço salvo parar de responder e o MESMO painel (mesma
      identidade) aparecer em outro IP, troca para o novo IP e salva no .ini.
    """

    ANUNCIO_VALIDO_S = 15       # anúncio mais velho que isso é ignorado

    def __init__(self, cfg):
        self._lock = threading.Lock()
        self._abridor = abridor_sem_proxy()
        self._falhas = 0
        self._cronometro = None
        self._monstrinho = None
        self._anuncio = None    # (ip, porta, id, pc, momento) do painel certo
        self._aplicar(cfg)

    def _aplicar(self, cfg):
        self.ip_salvo = cfg["ip"]               # '' = modo automático
        self.ip_atual = cfg["ip"] or None
        self.porta = cfg["porta"]
        self.painel_id = cfg["painel_id"]
        self.pc = cfg["pc"]
        self._identidade_ok = bool(self.painel_id) or not self.ip_salvo

    def iniciar(self):
        threading.Thread(target=self._laco_consulta, daemon=True).start()
        threading.Thread(target=self._laco_descoberta, daemon=True).start()

    def definir_destino(self, cfg):
        """Troca o professor sem reiniciar (quando o .ini é alterado)."""
        with self._lock:
            mudou = (cfg["ip"], cfg["porta"], cfg["painel_id"]) != \
                    (self.ip_salvo, self.porta, self.painel_id)
            self._aplicar(cfg)
            if mudou:
                self._falhas, self._cronometro, self._monstrinho = 0, None, None
                self._anuncio = None

    def foto(self):
        """Cópia do último estado recebido (lida pela interface)."""
        with self._lock:
            return {"falhas": self._falhas, "cronometro": self._cronometro,
                    "monstrinho": self._monstrinho}

    # ------------------------------------------------------- consulta
    def _laco_consulta(self):
        while True:
            inicio = time.monotonic()
            with self._lock:
                ip, porta = self.ip_atual, self.porta
            try:
                if not ip:
                    raise ConnectionError("professor ainda não encontrado")
                cronometro = ler_json(self._abridor, ip, porta, "/cronometro")
                monstrinho = ler_json(self._abridor, ip, porta, "/status_monstrinho")
                with self._lock:
                    self._cronometro, self._monstrinho, self._falhas = cronometro, monstrinho, 0
                if not self._identidade_ok:
                    self._aprender_identidade(ip, porta)
            except Exception:  # rede, timeout, JSON inválido... tenta de novo
                with self._lock:
                    self._falhas += 1
                self._talvez_trocar_de_ip()
            time.sleep(max(0.1, INTERVALO_CONSULTA - (time.monotonic() - inicio)))

    def _aprender_identidade(self, ip, porta):
        """Config antiga (só IP): pergunta ao painel quem ele é e salva."""
        self._identidade_ok = True
        try:
            info = ler_json(self._abridor, ip, porta, "/info")
        except Exception:
            return  # painel de versão antiga: segue só com o IP
        with self._lock:
            self.painel_id = str(info.get("id", ""))
            self.pc = str(info.get("pc", ""))
        if self.painel_id:
            salvar_config(self.ip_salvo, porta, self.painel_id, self.pc)

    def _talvez_trocar_de_ip(self):
        with self._lock:
            a = self._anuncio
            if (self._falhas < FALHAS_PARA_SEM_CONEXAO or not a
                    or time.monotonic() - a[4] > self.ANUNCIO_VALIDO_S
                    or (a[0] == self.ip_atual and a[1] == self.porta)):
                return
            ip, porta, painel_id, pc, _ = a
            self.ip_atual, self.porta, self._falhas = ip, porta, 0
            fixo = bool(self.ip_salvo)
            if fixo:  # guarda o novo endereço para o próximo boot já começar certo
                self.ip_salvo = ip
                self.painel_id = painel_id or self.painel_id
                self.pc = pc or self.pc
        if fixo:
            salvar_config(ip, porta, self.painel_id, self.pc)

    # ------------------------------------------------------ descoberta
    def _combina(self, msg):
        """Este anúncio é do NOSSO professor?"""
        if not self.ip_salvo:          # modo automático: qualquer painel serve
            return True
        if self.painel_id:
            return msg.get("id") == self.painel_id
        if self.pc:
            return str(msg.get("pc", "")).lower() == self.pc.lower()
        return False                   # sem identidade: só o endereço salvo

    def _laco_descoberta(self):
        """Escuta o anúncio UDP do painel (desde o boot, o tempo todo)."""
        while True:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind(("", PORTA_DESCOBERTA))
                    while True:
                        dados, (ip, _) = s.recvfrom(2048)
                        try:
                            msg = json.loads(dados.decode("utf-8"))
                        except ValueError:
                            continue
                        if not isinstance(msg, dict) or msg.get("app") != "monstrinho":
                            continue
                        with self._lock:
                            if self._combina(msg):
                                try:
                                    porta = int(msg.get("porta", self.porta))
                                except (TypeError, ValueError):
                                    porta = self.porta
                                self._anuncio = (ip, porta, str(msg.get("id", "")),
                                                 str(msg.get("pc", "")), time.monotonic())
                                if not self.ip_atual:   # automático: usa o 1º que achar
                                    self.ip_atual, self.porta = ip, porta
            except OSError:
                time.sleep(5)  # rede ainda não está pronta (boot): tenta de novo


# ---------------------------------------------------------------------
# Janela (tudo é desenhado num Canvas: cartão arredondado + monstrinho)
# ---------------------------------------------------------------------
def formatar_tempo(segundos):
    segundos = max(0, int(segundos))
    return f"{segundos // 60:02d}:{segundos % 60:02d}"


def cor_do_tempo(restante):
    if restante <= 300:
        return VERMELHO
    if restante <= 600:
        return LARANJA
    return VERDE


def misturar(cor1, cor2, fator):
    """Mistura duas cores '#rrggbb' (fator 0 = cor1, 1 = cor2)."""
    try:
        a = [int(cor1[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(cor2[i:i + 2], 16) for i in (1, 3, 5)]
    except (ValueError, TypeError, IndexError):
        return cor1
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * fator) for x, y in zip(a, b))


def cor_valida(cor, padrao):
    cor = str(cor or "")
    if len(cor) == 7 and cor.startswith("#"):
        try:
            int(cor[1:], 16)
            return cor
        except ValueError:
            pass
    return padrao


def retangulo_arredondado(cv, x1, y1, x2, y2, raio, **kw):
    r = raio
    pontos = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
              x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pontos, smooth=True, **kw)


def desenhar_monstrinho(cv, cx, cy, tamanho, humor, t, fundo, sombra=True):
    """Desenha o monstrinho centralizado em (cx, cy).

    tamanho = altura aproximada em pixels; humor = bravo | furioso |
    desconfiado | travesso | alarme; t = tempo (s) para animar; fundo = cor
    do cartão (para a sombra e a fumaça).
    """
    u = tamanho / 100.0
    lw = max(1, int(round(3 * u)))           # espessura dos traços
    agitado = humor in ("furioso", "alarme")

    # Animação: pulinho, tremedeira (furioso) e piscada
    pulo = abs(math.sin(t * (7 if agitado else 3))) * (5 if agitado else 3) * u
    tremor = math.sin(t * 45) * 1.6 * u if humor == "furioso" else 0
    piscando = humor != "alarme" and (t % 3.4) < 0.13
    olhar = math.sin(t * 0.9) * 2.2 if humor in ("bravo", "desconfiado") else 0

    ox, oy = cx - 50 * u + tremor, cy - 50 * u - pulo

    def P(*xy):
        return [ox + v * u if i % 2 == 0 else oy + v * u for i, v in enumerate(xy)]

    corpo = CORES_CORPO.get(humor, CORES_CORPO["bravo"])
    escuro = misturar(corpo, "#000000", 0.28)
    claro = misturar(corpo, "#ffffff", 0.38)
    tinta = "#22172e"
    boca = "#5a1530"

    # Sombra no chão (não pula)
    if sombra:
        cv.create_oval(cx - 28 * u, cy + 45 * u, cx + 28 * u, cy + 51 * u,
                       fill=misturar(fundo, "#000000", 0.18), outline="")

    # Fumaça saindo da cabeça (furioso)
    if humor == "furioso":
        fumaca = misturar(fundo, "#ffffff", 0.55)
        for lado, fase in ((14, 0.0), (86, 0.5)):
            for k in range(2):
                f = (t * 0.9 + fase + k * 0.5) % 1.0
                r = (2.5 + 4 * f) * u
                x = ox + lado * u + (lado - 50) * 0.15 * f * u
                y = oy + (18 - 12 * f) * u
                cv.create_oval(x - r, y - r, x + r, y + r, fill=fumaca, outline="")

    # Chifres
    chifre = "#fff1d6"
    cv.create_polygon(P(28, 26, 33, 5, 43, 20), fill=chifre, outline="", smooth=False)
    cv.create_polygon(P(57, 20, 67, 5, 72, 26), fill=chifre, outline="", smooth=False)

    # Pés
    cv.create_oval(P(24, 84, 44, 98), fill=escuro, outline="")
    cv.create_oval(P(56, 84, 76, 98), fill=escuro, outline="")

    # Braços (para cima quando agitado)
    if agitado:
        cv.create_oval(P(4, 26, 20, 48), fill=escuro, outline="")
        cv.create_oval(P(80, 26, 96, 48), fill=escuro, outline="")
    else:
        cv.create_oval(P(6, 56, 22, 74), fill=escuro, outline="")
        cv.create_oval(P(78, 56, 94, 74), fill=escuro, outline="")

    # Corpo e barriga
    cv.create_oval(P(14, 16, 86, 92), fill=corpo, outline=escuro, width=max(1, int(2 * u)))
    cv.create_oval(P(31, 60, 69, 89), fill=claro, outline="")

    # Bochechas (travesso)
    if humor == "travesso":
        for x in (22, 70):
            cv.create_oval(P(x, 54, x + 9, 60), fill="#ff9ec4", outline="")

    # Olhos
    grande = humor == "alarme"
    for ex in (38, 62):
        if piscando:
            cv.create_line(P(ex - 8, 46, ex + 8, 46), fill=tinta, width=lw, capstyle="round")
            continue
        r = 11 if grande else 9
        cv.create_oval(P(ex - r, 46 - r, ex + r, 46 + r), fill="white", outline="")
        rp = 3 if grande else 4.2
        px = ex + olhar
        cv.create_oval(P(px - rp, 47 - rp, px + rp, 47 + rp), fill=tinta, outline="")
        cv.create_oval(P(px - rp + 1, 44.5, px - rp + 3, 46.5), fill="white", outline="")
        # Pálpebra meio fechada (desconfiado, olho esquerdo)
        if humor == "desconfiado" and ex == 38:
            cv.create_polygon(P(ex - 10, 35, ex + 10, 35, ex + 10, 46, ex - 10, 46),
                              fill=corpo, outline="")
            cv.create_line(P(ex - 9, 46, ex + 9, 46), fill=escuro, width=lw)

    # Sobrancelhas
    sob = dict(fill=tinta, width=lw + 1, capstyle="round")
    if humor == "bravo":
        cv.create_line(P(28, 32, 46, 38), **sob)
        cv.create_line(P(72, 32, 54, 38), **sob)
    elif humor == "furioso":
        cv.create_line(P(26, 28, 47, 39), **sob)
        cv.create_line(P(74, 28, 53, 39), **sob)
    elif humor == "travesso":
        cv.create_line(P(29, 33, 46, 37), **sob)
        cv.create_line(P(71, 33, 54, 37), **sob)
    elif humor == "desconfiado":
        cv.create_line(P(28, 37, 47, 36), **sob)
        cv.create_line(P(53, 31, 62, 26, 72, 30), smooth=True, **sob)
    else:  # alarme
        cv.create_line(P(28, 31, 38, 26, 47, 30), smooth=True, **sob)
        cv.create_line(P(53, 30, 62, 26, 72, 31), smooth=True, **sob)

    # Boca
    if humor == "bravo":
        cv.create_arc(P(40, 68, 60, 84), start=25, extent=130, style="arc",
                      outline=tinta, width=lw)
    elif humor == "furioso":
        cv.create_oval(P(37, 64, 63, 82), fill=boca, outline="")
        cv.create_polygon(P(40, 65, 46, 65, 43, 71), fill="white", outline="")
        cv.create_polygon(P(54, 65, 60, 65, 57, 71), fill="white", outline="")
    elif humor == "desconfiado":
        cv.create_line(P(41, 73, 47, 70, 53, 74, 59, 71), smooth=True, fill=tinta,
                       width=lw, capstyle="round")
    elif humor == "travesso":
        cv.create_arc(P(35, 56, 65, 82), start=200, extent=140, style="chord",
                      fill=boca, outline="")
        cv.create_polygon(P(53, 70, 58, 70, 55.5, 75), fill="white", outline="")
    else:  # alarme: boca de "Ó!"
        cv.create_oval(P(44, 65, 56, 80), fill=boca, outline="")

    # Pontos de exclamação piscando (alarme)
    if humor == "alarme" and int(t * 3) % 2 == 0:
        for x in (-2, 102):
            cv.create_text(ox + x * u, oy + 14 * u, text="!", fill=VERMELHO,
                           font=("Arial", max(8, int(14 * u)), "bold"))


def assinatura_config():
    """(arquivo, data de modificação) do .ini, para notar alterações."""
    caminho = arquivo_config_atual()
    try:
        return (caminho, os.path.getmtime(caminho)) if caminho else None
    except OSError:
        return None


def area_de_trabalho(root):
    """(esq, topo, dir, baixo) da área útil da tela, SEM a barra de tarefas."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            r = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0):
                return r.left, r.top, r.right, r.bottom   # SPI_GETWORKAREA
        except Exception:
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight() - 48


def ativar_dpi_windows():
    """Evita janela borrada/posição errada com zoom do Windows em 125%, 150%..."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class JanelaAluno:
    QUADRO_MS = 50   # ~20 quadros/s enquanto o monstrinho aparece

    def __init__(self, root, conexao):
        self.root = root
        self.conexao = conexao
        self.modo = None            # "mini" | "monstrinho" | "alerta"
        self.t0 = time.monotonic()
        self._ultimo_mini = None
        try:
            self.escala = max(1.0, root.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            self.escala = 1.0

        root.title("Tempo de Aula")
        root.overrideredirect(True)           # sem borda / sem barra de título
        root.attributes("-topmost", True)     # sempre no topo
        root.protocol("WM_DELETE_WINDOW", lambda: None)  # ignora Alt+F4

        # No Windows, uma cor "chave" fica transparente -> cantos arredondados de verdade
        fundo_janela = FUNDO
        if sys.platform == "win32":
            try:
                root.attributes("-transparentcolor", COR_TRANSPARENTE)
                fundo_janela = COR_TRANSPARENTE
            except tk.TclError:
                pass
        root.configure(bg=fundo_janela)
        self.cv = tk.Canvas(root, bg=fundo_janela, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)

        self._assinatura_cfg = assinatura_config()
        self._mudar_modo("mini")
        root.after(100, self._quadro)
        root.after(3000, self._reforcar_topo)
        root.after(5000, self._verificar_config)

    def _verificar_config(self):
        """Se o código do painel for trocado (--configurar), aplica na hora."""
        try:
            atual = assinatura_config()
            if atual != self._assinatura_cfg:
                self._assinatura_cfg = atual
                cfg = carregar_config()
                if cfg["configurado"]:
                    self.conexao.definir_destino(cfg)
        finally:
            self.root.after(5000, self._verificar_config)

    def _px(self, v):
        return v * self.escala

    # ----------------------------------------------------------- layout
    def _mudar_modo(self, modo):
        """Ajusta tamanho/posição só quando o modo muda.

        A janela fica ancorada logo acima do relógio do Windows e cresce
        PARA CIMA quando o monstrinho aparece.
        """
        if modo == self.modo:
            return
        self.modo = modo
        self._ultimo_mini = None
        largura, altura = {"mini": TAM_MINI, "monstrinho": TAM_MONSTRINHO,
                           "alerta": TAM_ALERTA}[modo]
        w, h, m = (int(round(self._px(v))) for v in (largura, altura, MARGEM))
        self.w, self.h = w, h
        _, _, direita, baixo = area_de_trabalho(self.root)
        self.root.geometry(f"{w}x{h}+{direita - w - m}+{baixo - h - m}")
        self.root.attributes("-alpha", TRANSPARENCIA_MINI if modo == "mini" else 1.0)
        self.root.lift()

    # ------------------------------------------------------- animação
    def _quadro(self):
        try:
            self._desenhar(self._interpretar(self.conexao.foto()))
        except Exception:
            pass  # nunca deixa a janela parar
        finally:
            self.root.after(self.QUADRO_MS if self.modo != "mini" else 250, self._quadro)

    def _interpretar(self, f):
        """Transforma os dados do professor no que deve aparecer na tela."""
        cron = f["cronometro"]
        if f["falhas"] >= FALHAS_PARA_SEM_CONEXAO or cron is None:
            if f["falhas"] < FALHAS_PARA_SEM_CONEXAO:
                tempo = ("conectando...", CINZA, 8)
            elif f["falhas"] < FALHAS_PARA_ALERTA_VERMELHO:
                tempo = ("procurando...", CINZA, 8)   # escutando a rede
            else:
                tempo = ("sem conexão", VERMELHO, 8)
            return {"modo": "mini", "tempo": tempo}

        if cron.get("encerrada"):
            tempo = ("FIM DA AULA", VERMELHO, 9)
        elif cron.get("ativo"):
            restante = int(cron.get("tempo_restante", 0) or 0)
            tempo = (formatar_tempo(restante), cor_do_tempo(restante), 13)
        else:
            tempo = ("--:--", CINZA, 13)

        m = f["monstrinho"] or {}
        if not m.get("mostrar"):
            return {"modo": "mini", "tempo": tempo}
        return {
            "modo": "alerta" if m.get("alerta") else "monstrinho",
            "tempo": tempo,
            "humor": "alarme" if m.get("alerta") else HUMORES.get(m.get("rosto"), "bravo"),
            "mensagem": str(m.get("mensagem", "")),
            "cor": cor_valida(m.get("cor"), COR_MONSTRINHO_PADRAO),
        }

    def _desenhar(self, e):
        self._mudar_modo(e["modo"])
        texto, cor, tam = e["tempo"]

        if self.modo == "mini":
            chave = (texto, cor, tam)
            if chave == self._ultimo_mini:
                return  # nada mudou: economiza CPU do aluno
            self._ultimo_mini = chave

        cv, w, h, px = self.cv, self.w, self.h, self._px
        cv.delete("all")
        retangulo_arredondado(cv, 1, 1, w - 1, h - 1, px(12), fill=FUNDO, outline=BORDA)

        if self.modo == "mini":
            cv.create_text(w / 2, h / 2, text=texto, fill=cor, font=("Segoe UI", tam, "bold"))
            return

        t = time.monotonic() - self.t0
        cv.create_text(w / 2, px(15), text=texto, fill=cor, font=("Segoe UI", 10, "bold"))

        # Cartão colorido (no alerta pisca entre amarelo e vermelho)
        cartao = e["cor"]
        if self.modo == "alerta":
            cartao = CORES_ALERTA[int(t * 3) % 2]
        x1, y1, x2, y2 = px(7), px(30), w - px(7), h - px(7)
        retangulo_arredondado(cv, x1, y1, x2, y2, px(12), fill=cartao, outline="")

        if self.modo == "alerta":
            # Monstrinho à esquerda, mensagem grande à direita
            tam_m = px(118)
            cx, cy = x1 + px(72), (y1 + y2) / 2 + px(2)
            desenhar_monstrinho(cv, cx, cy, tam_m, e["humor"], t, cartao)
            esq = cx + px(66)
            cv.create_text((esq + x2) / 2, (y1 + y2) / 2, text=e["mensagem"],
                           fill=TINTA, font=("Segoe UI", 15, "bold"), justify="center",
                           width=x2 - esq - px(12))
        else:
            # Monstrinho em cima, mensagem embaixo
            tam_m = px(98)
            cy = y1 + px(58)
            desenhar_monstrinho(cv, w / 2, cy, tam_m, e["humor"], t, cartao)
            cv.create_text(w / 2, (cy + px(54) + y2) / 2, text=e["mensagem"], fill=TINTA,
                           font=("Segoe UI", 10, "bold"), justify="center",
                           width=x2 - x1 - px(12))

    def _reforcar_topo(self):
        """Alguns programas 'roubam' o topo; reafirma periodicamente."""
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
        finally:
            self.root.after(3000, self._reforcar_topo)


# ---------------------------------------------------------------------
# Tela de configuração (1ª abertura ou "--configurar")
# ---------------------------------------------------------------------
def testar_painel(host, porta, timeout=3.0):
    """Tenta falar com o painel. Retorna (ok, mensagem, info).

    info = {"id": ..., "pc": ...} (vazio se o painel for de versão antiga).
    """
    abridor = abridor_sem_proxy()
    try:
        dados = ler_json(abridor, host, porta, "/cronometro", timeout)
        if "ativo" not in dados:
            return False, "Algo respondeu nesse endereço, mas não é o painel do Monstrinho.", {}
    except Exception:
        return False, (f"Não encontrei o painel em {host}. Confira se o painel está aberto "
                       "no PC do professor e se o código está certo."), {}
    try:
        info = ler_json(abridor, host, porta, "/info", timeout)
    except Exception:
        info = {}
    return True, "Painel encontrado!", info


def procurar_paineis(segundos=6.0):
    """Escuta o anúncio UDP dos painéis. Retorna [{'ip', 'porta', 'id', 'pc'}]."""
    achados = {}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", PORTA_DESCOBERTA))
            fim = time.monotonic() + segundos
            while time.monotonic() < fim:
                s.settimeout(max(0.1, fim - time.monotonic()))
                try:
                    dados, (ip, _) = s.recvfrom(2048)
                except socket.timeout:
                    break
                try:
                    msg = json.loads(dados.decode("utf-8"))
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("app") == "monstrinho":
                    chave = msg.get("id") or ip
                    achados[chave] = {"ip": ip, "porta": msg.get("porta", PORTA_PADRAO),
                                      "id": str(msg.get("id", "")), "pc": str(msg.get("pc", ""))}
    except OSError:
        pass
    return list(achados.values())


class TelaConfiguracao:
    """Janela que pede o código do painel do professor e testa a conexão."""

    ROXO = "#7c5cff"
    CAMPO = "#1e2645"

    def __init__(self, root, valor_inicial="", porta=PORTA_PADRAO):
        self.root = root
        self.porta = porta
        self.resultado = None          # (ip, porta) quando salvar
        self._fila = []                # respostas das threads (lidas pelo after)
        self._ocupado = False
        self.t0 = time.monotonic()

        root.title("Monstrinho do Barulho - Configuração")
        root.configure(bg=FUNDO)
        root.resizable(False, False)
        # Com zoom do Windows (125%, 150%...) os textos crescem: a janela acompanha.
        try:
            self.esc = max(1.0, root.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            self.esc = 1.0
        largura, altura = int(480 * self.esc), int(500 * self.esc)
        x = (root.winfo_screenwidth() - largura) // 2
        y = (root.winfo_screenheight() - altura) // 2
        root.geometry(f"{largura}x{altura}+{x}+{y}")
        root.attributes("-topmost", True)

        self.cv = tk.Canvas(root, width=largura, height=int(150 * self.esc), bg=FUNDO, highlightthickness=0)
        self.cv.pack()

        tk.Label(root, text="Vamos conectar este computador", font=("Segoe UI", 16, "bold"),
                 fg="#e9edfb", bg=FUNDO).pack()
        tk.Label(root, text="Digite o CÓDIGO DO PAINEL que aparece no topo\n"
                            "do painel do professor (ex.: 30AG-03A).",
                 font=("Segoe UI", 10), fg=CINZA, bg=FUNDO, justify="center").pack(pady=(6, 14))

        self.var = tk.StringVar(value=valor_inicial)
        # Código em maiúsculas enquanto digita (IP e nome de PC ficam como estão)
        self.var.trace_add("write", lambda *a: self._maiusculas())
        self.entrada = tk.Entry(root, textvariable=self.var, font=("Consolas", 20, "bold"),
                                justify="center", width=16, bg=self.CAMPO, fg="#ffffff",
                                insertbackground="#ffffff", relief="flat", bd=0,
                                highlightthickness=2, highlightbackground=BORDA,
                                highlightcolor=self.ROXO)
        self.entrada.pack(ipady=8)
        self.entrada.focus_set()
        self.entrada.bind("<Return>", lambda e: self.conectar())

        tk.Label(root, text="Também aceita o IP (ex.: 192.168.0.106) ou o nome do PC do professor.",
                 font=("Segoe UI", 8), fg="#5d6690", bg=FUNDO).pack(pady=(6, 0))

        self.lbl_status = tk.Label(root, text="", font=("Segoe UI", 10, "bold"), bg=FUNDO,
                                   fg=CINZA, wraplength=int(420 * self.esc), justify="center", height=2)
        self.lbl_status.pack(pady=(10, 6))

        botoes = tk.Frame(root, bg=FUNDO)
        botoes.pack()
        self.btn_procurar = self._botao(botoes, "Procurar na rede", self.procurar, self.CAMPO)
        self.btn_procurar.pack(side="left", padx=6)
        self.btn_conectar = self._botao(botoes, "Conectar", self.conectar, self.ROXO)
        self.btn_conectar.pack(side="left", padx=6)
        self.btn_mesmo_assim = self._botao(root, "Salvar mesmo assim", self.salvar_mesmo_assim,
                                           "#3a2a4a")

        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.after(50, self._animar)
        root.after(100, self._ler_fila)

    def _botao(self, pai, texto, comando, cor):
        b = tk.Label(pai, text=texto, bg=cor, fg="#ffffff", font=("Segoe UI", 10, "bold"),
                     padx=18, pady=9, cursor="hand2")
        claro = misturar(cor, "#ffffff", 0.12)
        b.bind("<Enter>", lambda e: b.config(bg=claro))
        b.bind("<Leave>", lambda e: b.config(bg=cor))
        b.bind("<ButtonRelease-1>", lambda e: comando())
        return b

    def _maiusculas(self):
        texto = self.var.get()
        if "." not in texto and texto != texto.upper():
            pos = self.entrada.index("insert") if hasattr(self, "entrada") else None
            self.var.set(texto.upper())
            if pos is not None:
                self.entrada.icursor(pos)

    def _status(self, texto, cor=CINZA):
        self.lbl_status.config(text=texto, fg=cor)

    def _animar(self):
        if not self.root.winfo_exists():
            return
        self.cv.delete("all")
        humor = "alarme" if self._ocupado else "travesso"
        e = self.esc
        desenhar_monstrinho(self.cv, 240 * e, 78 * e, 118 * e, humor,
                            time.monotonic() - self.t0, FUNDO)
        self.root.after(50, self._animar)

    def _ler_fila(self):
        while self._fila:
            self._fila.pop(0)()
        if self.root.winfo_exists():
            self.root.after(100, self._ler_fila)

    # ------------------------------------------------------------ ações
    def conectar(self):
        if self._ocupado:
            return
        destino = interpretar_destino(self.var.get())
        if destino is None:
            self._status("Digite o código do painel (ex.: 30AG-03A).", VERMELHO)
            return
        if destino == "auto":
            self._salvar("", "Modo automático salvo!")
            return
        self.btn_mesmo_assim.pack_forget()
        self._ocupado = True
        self._status(f"Testando conexão com {destino}...", LARANJA)

        def tarefa():
            ok, msg, info = testar_painel(destino, self.porta)
            self._fila.append(lambda: self._fim_teste(destino, ok, msg, info))

        threading.Thread(target=tarefa, daemon=True).start()

    def _fim_teste(self, destino, ok, msg, info):
        self._ocupado = False
        if ok:
            pc = str(info.get("pc", ""))
            self._salvar(destino, "Conectado! Tudo pronto." + (f"  (PC {pc})" if pc else ""),
                         str(info.get("id", "")), pc)
        else:
            self._destino_pendente = destino
            self._status(msg, VERMELHO)
            self.btn_mesmo_assim.pack(pady=(10, 0))

    def salvar_mesmo_assim(self):
        self._salvar(getattr(self, "_destino_pendente", ""), "Configuração salva.")

    def _salvar(self, destino, msg, painel_id="", pc=""):
        caminho = salvar_config(destino, self.porta, painel_id, pc)
        if not caminho:
            self._status("Não consegui salvar a configuração (sem permissão). "
                         "Rode o instalador novamente como administrador.", VERMELHO)
            return
        self.resultado = (destino, self.porta)
        self._status(msg, VERDE)
        self.root.after(1200, self.root.destroy)

    def procurar(self):
        if self._ocupado:
            return
        self._ocupado = True
        self._status("Procurando painéis do professor na rede (até 6 s)...", LARANJA)

        def tarefa():
            achados = procurar_paineis()
            self._fila.append(lambda: self._fim_procura(achados))

        threading.Thread(target=tarefa, daemon=True).start()

    def _fim_procura(self, achados):
        self._ocupado = False
        if not achados:
            self._status("Nenhum painel encontrado. Confira se o painel está aberto e "
                         "digite o código manualmente.", VERMELHO)
            return
        p = achados[0]
        self.var.set(ip_para_codigo(p["ip"]))
        nome = f"do PC {p['pc']}" if p["pc"] else f"em {p['ip']}"
        if len(achados) > 1:
            outros = ", ".join(a["pc"] or a["ip"] for a in achados[1:])
            self._status(f"{len(achados)} painéis na rede! Mostrando o {nome}. Outros: {outros}. "
                         "Confira o código com o professor antes de conectar.", LARANJA)
        else:
            self._status(f"Painel {nome} encontrado. Clique em Conectar.", VERDE)


def pedir_configuracao(ip_atual="", porta=PORTA_PADRAO):
    """Mostra a tela de configuração. Retorna True se salvou."""
    root = tk.Tk()
    inicial = ""
    if ip_atual:
        try:
            inicial = ip_para_codigo(ip_atual)
        except OSError:
            inicial = ip_atual  # é um nome de computador
    tela = TelaConfiguracao(root, inicial, porta)
    root.mainloop()
    return tela.resultado is not None


# ---------------------------------------------------------------------
# Início
# ---------------------------------------------------------------------
def garantir_instancia_unica():
    """Ocupa uma porta local; se já estiver ocupada, outra cópia está aberta."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", PORTA_INSTANCIA_UNICA))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


def main():
    ativar_dpi_windows()
    cfg = carregar_config()

    # 1ª abertura (sem código salvo) ou pedido explícito: mostra a configuração
    if "--configurar" in sys.argv[1:] or not cfg["configurado"]:
        salvou = pedir_configuracao(cfg["ip"], cfg["porta"])
        if not salvou and not cfg["configurado"]:
            return  # fechou sem configurar: pergunta de novo no próximo login
        cfg = carregar_config()

    trava = garantir_instancia_unica()
    if trava is None:
        return  # já está aberto (e vai recarregar a configuração sozinho)

    # Abre junto com o Windows e fica procurando o painel até encontrar
    conexao = Conexao(cfg)
    conexao.iniciar()

    root = tk.Tk()
    JanelaAluno(root, conexao)
    root.mainloop()
    trava.close()


if __name__ == "__main__":
    main()
