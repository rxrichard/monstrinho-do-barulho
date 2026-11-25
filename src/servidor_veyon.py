# -*- coding: utf-8 -*-
"""
=====================================================================
 MONSTRINHO DO BARULHO - Painel do Professor  (servidor_veyon.py)
=====================================================================
Roda no computador do PROFESSOR. Funções:

  * Mede o barulho da sala pelo microfone, em tempo real.
  * Envia avisos visuais ("monstrinho") para os alunos por uma API HTTP
    local (Flask, porta 5000):
        GET /status_monstrinho   -> o que o monstrinho deve mostrar
        GET /cronometro          -> estado do cronômetro da aula
        GET /info                -> identidade do painel
  * Depois do número máximo de avisos, trava as telas pelo Veyon por um
    tempo PROGRESSIVO (padrão 30 s -> 1 min -> 2 min) e destrava sozinho.
  * "Ficha limpa": um bom tempo sem avisos zera avisos e progressão.
  * Cronômetro: alerta os alunos faltando 5 minutos e, em 00:00, trava
    as telas até o professor clicar em "Liberar telas".
  * Anuncia-se na rede a cada 3 s (broadcast UDP 5001) com uma
    identidade fixa: os alunos o encontram sozinhos, mesmo se o IP mudar.

Dependências:  pip install -r requirements.txt   (flask, numpy, sounddevice)

Configurações: config_professor.json, ao lado deste arquivo; na versão
instalada (.exe), em C:\\ProgramData\\Monstrinho.
=====================================================================
"""

import json
import logging
import math
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import uuid
from tkinter import messagebox, ttk

# Áudio é opcional: sem ele o painel abre, mas não mede o barulho.
try:
    import numpy as np
    import sounddevice as sd
    AUDIO_OK = True
except Exception:  # ImportError ou falha ao carregar o PortAudio
    AUDIO_OK = False

# Flask é necessário para os alunos verem o monstrinho e o cronômetro.
try:
    from flask import Flask, jsonify
    from werkzeug.serving import make_server
    FLASK_OK = True
except ImportError:
    FLASK_OK = False


# =====================================================================
# CONSTANTES
# =====================================================================
PORTA_HTTP = 5000               # porta que os alunos consultam
PORTA_DESCOBERTA = 5001         # porta UDP do anúncio automático de IP
INTERVALO_CICLO_MS = 100        # frequência da lógica/tela do painel
DURACAO_AVISO_VISUAL = 5        # segundos que o monstrinho de aviso aparece
DURACAO_VISUAL_DESTRAVE = 8     # segundos do recado depois de destravar
DURACAO_TESTE_TRAVA = 5         # segundos do botão "Testar trava"
AVISO_FIM_AULA_SEGUNDOS = 5 * 60  # quando avisar que a aula está acabando
DURACAO_ALERTA_FIM_AULA = 20      # segundos que o alerta forte fica na tela
MSG_ALERTA_FIM_AULA = "Faltam apenas 5 minutos para o fim da aula!"
TIMEOUT_VEYON = 20              # segundos máximos por comando do veyon-cli
TEMPOS_TRAVA_PADRAO = [30, 60, 120]


def pasta_base():
    """Pasta do programa (funciona como .py e como .exe)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def pasta_config():
    """Onde salvar o config_professor.json.

    Instalado (.exe em "Arquivos de Programas", sem permissão de escrita):
    C:\\ProgramData\\Monstrinho. Rodando como .py: ao lado do script.
    """
    if getattr(sys, "frozen", False) and os.environ.get("PROGRAMDATA"):
        pasta = os.path.join(os.environ["PROGRAMDATA"], "Monstrinho")
        try:
            os.makedirs(pasta, exist_ok=True)
            return pasta
        except OSError:
            pass
    return pasta_base()


ARQUIVO_CONFIG = os.path.join(pasta_config(), "config_professor.json")
NOME_PC = socket.gethostname()

CONFIG_PADRAO = {
    "computadores": ["SMEL-97244.pml.com.br"],
    "recurso_travar": "ScreenLock",
    "limite_ruido": 60,
    "max_avisos": 3,
    "cooldown_minutos": 5,
    "ficha_limpa_minutos": 15,
    "tempos_trava_segundos": TEMPOS_TRAVA_PADRAO,
    "duracao_aula_minutos": 45,
    "microfone": "",
    "veyon_cli": r"C:\Program Files\Veyon\veyon-cli.exe",
    "automacao_ativa": True,
    # Identidade fixa deste painel (gerada na 1ª execução). Os alunos usam
    # para reencontrar ESTE professor mesmo se o IP mudar.
    "painel_id": "",
}


# =====================================================================
# UTILITÁRIOS
# =====================================================================
# Fila de mensagens do "Registro". Qualquer thread pode escrever nela;
# só a interface (thread principal) lê e mostra na tela.
FILA_LOG = queue.Queue()


def registrar(msg):
    FILA_LOG.put(f"[{time.strftime('%H:%M:%S')}] {msg}")


def obter_ip_local():
    """Descobre o IP desta máquina na rede local (sem enviar nada)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


MEU_IP = obter_ip_local()

# "Código do painel": o IP escrito em 7 letras/números fáceis de digitar
# (sem I, L, O, U). O aluno digita esse código na 1ª abertura do programa.
# A conta é a mesma do cliente_aluno.pyw (codigo_para_ip).
ALFABETO_CODIGO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ip_para_codigo(ip):
    n = int.from_bytes(socket.inet_aton(ip), "big")
    letras = ""
    for _ in range(7):
        n, resto = divmod(n, 32)
        letras = ALFABETO_CODIGO[resto] + letras
    return f"{letras[:4]}-{letras[4:]}"


CODIGO_PAINEL = ip_para_codigo(MEU_IP)


def formatar_duracao(seg):
    """30 -> '30 s', 60 -> '1 min', 90 -> '1 min 30 s'."""
    seg = max(0, int(round(seg)))
    m, s = divmod(seg, 60)
    if m == 0:
        return f"{s} s"
    if s == 0:
        return f"{m} min"
    return f"{m} min {s} s"


def formatar_relogio(seg):
    """Segundos -> 'MM:SS' (arredonda para cima)."""
    seg = max(0, int(math.ceil(seg)))
    m, s = divmod(seg, 60)
    return f"{m:02d}:{s:02d}"


def cor_do_tempo(restante):
    if restante <= 300:
        return "#c62828"
    if restante <= 600:
        return "#f57c00"
    return "#2e7d32"


def carregar_config():
    """Lê o JSON de configuração, completando com os valores padrão."""
    cfg = json.loads(json.dumps(CONFIG_PADRAO))  # cópia profunda
    try:
        with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
            dados = json.load(f)
        if isinstance(dados, dict):
            for chave, padrao in CONFIG_PADRAO.items():
                valor = dados.get(chave)
                if valor is not None and type(valor) is type(padrao):
                    cfg[chave] = valor
    except FileNotFoundError:
        pass
    except Exception as e:
        registrar(f"Arquivo de configuração inválido ({e}). Usando valores padrão.")

    # Sanidade dos tempos de travamento
    try:
        tempos = [int(t) for t in cfg["tempos_trava_segundos"] if int(t) > 0]
    except (TypeError, ValueError):
        tempos = []
    cfg["tempos_trava_segundos"] = tempos or list(TEMPOS_TRAVA_PADRAO)

    if not cfg["painel_id"]:
        cfg["painel_id"] = uuid.uuid4().hex[:12]
        try:
            salvar_config_arquivo(cfg)
        except OSError:
            pass  # sem permissão: o id vale só nesta execução
    return cfg


def salvar_config_arquivo(cfg):
    """Grava o JSON de forma atômica (não corrompe se o PC desligar no meio)."""
    tmp = ARQUIVO_CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ARQUIVO_CONFIG)


def decodificar(dados):
    """Texto do veyon-cli (UTF-8, ou a página de código do console do Windows)."""
    for cod in ("utf-8", "cp850", "cp1252"):
        try:
            return dados.decode(cod)
        except UnicodeDecodeError:
            continue
    return dados.decode("utf-8", errors="replace")


def parece_erro(texto):
    t = texto.lower()
    return any(p in t for p in ("fail", "error", "invalid", "incorrect", "denied",
                                "falh", "erro", "inválid", "negad"))


# =====================================================================
# VEYON (travar / destravar telas)
# =====================================================================
class Veyon:
    """Envia comandos ao veyon-cli sem travar a interface.

    Os comandos vão para uma fila e são executados em ordem (assim um
    "destravar" nunca passa na frente do "travar" anterior). Dentro de cada
    comando, todos os computadores são acionados em paralelo.
    """

    def __init__(self, caminho_configurado):
        self.exe = self.localizar(caminho_configurado)
        self._fila = queue.Queue()
        threading.Thread(target=self._despachante, daemon=True).start()

    @staticmethod
    def localizar(caminho_configurado):
        candidatos = [
            caminho_configurado,
            r"C:\Program Files\Veyon\veyon-cli.exe",
            r"C:\Program Files (x86)\Veyon\veyon-cli.exe",
        ]
        for c in candidatos:
            if c and os.path.isfile(c):
                return c
        return shutil.which("veyon-cli")

    @property
    def disponivel(self):
        return bool(self.exe)

    def _preparar(self, computadores):
        if not self.exe:
            registrar("ERRO: veyon-cli não encontrado - comando de tela NÃO enviado.")
            return []
        pcs = [p.strip() for p in computadores if p.strip()]
        if not pcs:
            registrar("Aviso: a lista de computadores está vazia.")
        return pcs

    def enviar(self, acao, computadores, recurso):
        """acao = 'start' (travar) ou 'stop' (destravar). Não bloqueia."""
        pcs = self._preparar(computadores)
        if pcs:
            self._fila.put((acao, pcs, recurso))

    def enviar_e_aguardar(self, acao, computadores, recurso):
        """Versão bloqueante (usada ao fechar o painel)."""
        pcs = self._preparar(computadores)
        if pcs:
            self._executar_lote(acao, pcs, recurso)

    def _despachante(self):
        while True:
            acao, pcs, recurso = self._fila.get()
            try:
                self._executar_lote(acao, pcs, recurso)
            except Exception as e:  # nunca deixa a thread morrer
                registrar(f"Erro inesperado no Veyon: {e}")

    def _executar_lote(self, acao, pcs, recurso):
        threads = [
            threading.Thread(target=self._executar_um, args=(acao, pc, recurso), daemon=True)
            for pc in pcs
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(TIMEOUT_VEYON + 5)

    def rodar(self, *args, timeout=TIMEOUT_VEYON):
        """Executa 'veyon-cli <args>' e devolve (codigo, saida_texto).

        codigo = None quando nem conseguiu executar (timeout/erro do Windows).
        """
        if not self.exe:
            return None, "veyon-cli não encontrado."
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW: sem janela preta
        try:
            r = subprocess.run([self.exe, *args], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               timeout=timeout, **kwargs)
        except subprocess.TimeoutExpired:
            return None, f"sem resposta em {timeout} s (PC desligado ou fora da rede?)"
        except OSError as e:
            return None, f"não foi possível executar o veyon-cli: {e}"
        return r.returncode, decodificar(r.stdout).strip()

    def _executar_um(self, acao, pc, recurso):
        codigo, saida = self.rodar("feature", acao, pc, recurso)
        nome = "TRAVAR" if acao == "start" else "DESTRAVAR"
        # O veyon-cli às vezes devolve código 0 mesmo com erro, então olhamos o texto também.
        if codigo == 0 and not parece_erro(saida):
            registrar(f"Veyon OK: {nome} {pc}" + (f" -> {saida}" if saida else ""))
        else:
            registrar(f"Veyon FALHOU: {nome} {pc} (código {codigo}): {saida or 'sem detalhes'}"
                      " -> use o botão 'Diagnóstico do Veyon'.")


# =====================================================================
# MICROFONE
# =====================================================================
class Microfone:
    """Captura o áudio e guarda o PICO de volume entre uma leitura e outra."""

    ESCALA = 2000  # mesma escala da versão anterior (o limite continua calibrado)

    def __init__(self):
        self._stream = None
        self._lock = threading.Lock()
        self._pico = 0.0
        self._ultimo_audio = 0.0

    @staticmethod
    def listar():
        """Lista de opções no formato 'índice - nome (driver)'."""
        if not AUDIO_OK:
            return []
        try:
            apis = sd.query_hostapis()
            dispositivos = sd.query_devices()
        except Exception as e:
            registrar(f"Não foi possível listar os microfones: {e}")
            return []
        opcoes = []
        for i, d in enumerate(dispositivos):
            if d.get("max_input_channels", 0) > 0:
                try:
                    api = apis[d["hostapi"]]["name"]
                except Exception:
                    api = "?"
                opcoes.append(f"{i} - {d['name']} ({api})")
        return opcoes

    @staticmethod
    def indice_padrao():
        if not AUDIO_OK:
            return None
        try:
            dev = sd.default.device
            idx = dev[0] if not isinstance(dev, int) else dev
            return int(idx) if idx is not None and int(idx) >= 0 else None
        except Exception:
            return None

    def iniciar(self, opcao):
        """Abre o microfone escolhido. Retorna True se deu certo."""
        self.parar()
        if not AUDIO_OK:
            return False
        try:
            idx = int(str(opcao).split(" - ", 1)[0])
        except ValueError:
            idx = None  # usa o padrão do sistema
        try:
            self._stream = sd.InputStream(device=idx, channels=1, callback=self._callback)
            self._stream.start()
            return True
        except Exception as e:
            self._stream = None
            registrar(f"Erro ao abrir o microfone: {e}")
            return False

    def parar(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _callback(self, indata, frames, time_info, status):
        # Roda numa thread do driver de áudio: só calcula e guarda o número.
        rms = float(np.sqrt(np.mean(indata.astype(np.float64) ** 2)))
        with self._lock:
            if rms > self._pico:
                self._pico = rms
            self._ultimo_audio = time.monotonic()

    def ler(self):
        """Volume 0-100 desde a última leitura, ou None se não há áudio."""
        with self._lock:
            pico, ultimo = self._pico, self._ultimo_audio
            self._pico = 0.0
        if self._stream is None or time.monotonic() - ultimo > 2.0:
            return None
        return min(100, int(pico * self.ESCALA))


# =====================================================================
# LÓGICA PRINCIPAL (avisos, travamentos progressivos e cronômetro)
# =====================================================================
class Controlador:
    """Regras do sistema, sem nada de interface.

    Como funciona o barulho:
      * "Violação" = barulho acima do limite, desde que já tenha passado o
        INTERVALO (cooldown) desde a última violação e as telas não estejam
        travadas.
      * Enquanto avisos < máximo, cada violação gera um AVISO (monstrinho).
      * Depois de atingir o máximo, cada nova violação TRAVA as telas por um
        tempo progressivo: tempos[0], tempos[1], tempos[2], tempos[2]...
      * Quando o tempo acaba, as telas destravam sozinhas e o intervalo
        recomeça a contar (a turma ganha um respiro).
      * Se passar "ficha_limpa_minutos" sem nenhum aviso/trava, avisos e
        progressão voltam a zero.

    Todos os métodos públicos são thread-safe. ciclo() deve ser chamado
    periodicamente pela interface (~5x por segundo).
    """

    def __init__(self, cfg, veyon, relogio=time.monotonic):
        self.cfg = cfg
        self.veyon = veyon
        self._agora = relogio
        self.lock = threading.RLock()

        # Avisos e progressão de travamentos
        self.avisos = 0               # avisos dados na "ficha" atual
        self.nivel_trava = 0          # travamentos por barulho na ficha atual
        self.ultima_violacao = None   # controla o intervalo entre avisos
        self.ultima_atividade = None  # controla a "ficha limpa"

        # Travamento atual
        self.motivo_trava = None      # None | "barulho" | "fim_aula" | "teste"
        self.trava_ate = None         # fim da trava temporária

        # Mensagem visual temporária para os alunos
        self._visual = None           # (rosto, mensagem, cor)
        self._visual_ate = 0.0

        # Cronômetro da aula
        self.timer_ativo = False
        self.timer_fim = 0.0
        self.aula_encerrada = False
        self.alerta_5min_enviado = False
        self.timer_total = 0          # duração da aula em segundos (barra de progresso)
        self._alerta_ate = 0.0        # até quando o alerta forte fica na tela

        # Última medição
        self.volume = None
        self.acima_limite = False

        self._cliente = {"mostrar": False, "rosto": "", "mensagem": "", "cor": ""}

    # ------------------------------------------------------------- helpers
    @property
    def travado(self):
        return self.motivo_trava is not None

    def _tempos(self):
        return self.cfg.get("tempos_trava_segundos") or TEMPOS_TRAVA_PADRAO

    def _duracao_do_nivel(self, nivel):
        tempos = self._tempos()
        return tempos[min(nivel, len(tempos) - 1)]

    def _travar(self, motivo, duracao=None):
        ja_travado = self.travado
        self.motivo_trava = motivo
        self.trava_ate = (self._agora() + duracao) if duracao else None
        if not ja_travado:
            self.veyon.enviar("start", self.cfg["computadores"], self.cfg["recurso_travar"])

    def _destravar(self):
        self.motivo_trava = None
        self.trava_ate = None
        # Sempre envia o "stop", mesmo que o painel ache que já está livre:
        # corrige casos em que o Veyon ficou dessincronizado.
        self.veyon.enviar("stop", self.cfg["computadores"], self.cfg["recurso_travar"])

    def _mostrar_visual(self, rosto, mensagem, cor, segundos):
        self._visual = (rosto, mensagem, cor)
        self._visual_ate = self._agora() + segundos

    def _zerar(self):
        self.avisos = 0
        self.nivel_trava = 0
        self.ultima_violacao = None
        self.ultima_atividade = None

    # --------------------------------------------------------------- ciclo
    def ciclo(self, volume):
        """Executa uma rodada da lógica. volume = 0-100, ou None sem áudio."""
        with self.lock:
            agora = self._agora()
            self.volume = volume

            # 1a) Cronômetro: faltam 5 minutos?
            if (self.timer_ativo and not self.alerta_5min_enviado
                    and self.timer_fim - agora <= AVISO_FIM_AULA_SEGUNDOS):
                self.alerta_5min_enviado = True
                self._alerta_ate = agora + DURACAO_ALERTA_FIM_AULA
                registrar("Alerta enviado aos alunos: faltam 5 minutos para o fim da aula.")

            # 1b) Cronômetro: acabou a aula?
            if self.timer_ativo and agora >= self.timer_fim:
                self.timer_ativo = False
                self.aula_encerrada = True
                self._visual = None
                self._alerta_ate = 0.0
                self._travar("fim_aula")
                registrar("FIM DA AULA: telas travadas até o professor liberar.")

            # 2) Fim de uma trava temporária (barulho ou teste)
            if self.motivo_trava in ("barulho", "teste") and agora >= self.trava_ate:
                era_barulho = self.motivo_trava == "barulho"
                self._destravar()
                if era_barulho:
                    self.ultima_violacao = agora   # intervalo recomeça agora
                    self.ultima_atividade = agora
                    prox = formatar_duracao(self._duracao_do_nivel(self.nivel_trava))
                    self._mostrar_visual("🤨", f"LIBERADO!\nPróxima: {prox}",
                                         "#fff9c4", DURACAO_VISUAL_DESTRAVE)
                    registrar("Tempo de travamento acabou: telas destravadas.")
                else:
                    registrar("Teste de trava concluído: telas destravadas.")

            # 3) Ficha limpa: muito tempo sem avisos/travas
            if (not self.travado and (self.avisos or self.nivel_trava)
                    and self.ultima_atividade is not None
                    and agora - self.ultima_atividade >= self.cfg["ficha_limpa_minutos"] * 60):
                self._zerar()
                registrar("Ficha limpa! Avisos e travamentos progressivos zerados.")

            # 4) Barulho
            self.acima_limite = volume is not None and volume > self.cfg["limite_ruido"]
            if (self.cfg["automacao_ativa"] and self.acima_limite
                    and not self.travado and not self.aula_encerrada):
                cooldown = self.cfg["cooldown_minutos"] * 60
                if self.ultima_violacao is None or agora - self.ultima_violacao >= cooldown:
                    self._registrar_violacao(agora)

            # 5) O que os alunos devem ver
            self._montar_estado_cliente(agora)

    def _registrar_violacao(self, agora):
        self.ultima_violacao = agora
        self.ultima_atividade = agora
        maximo = self.cfg["max_avisos"]

        if self.avisos < maximo:
            self.avisos += 1
            if self.avisos >= maximo:
                msg, cor = "ÚLTIMO AVISO!", "#ffab91"
            else:
                msg, cor = f"AVISO {self.avisos}/{maximo}", "#ffcc80"
            self._mostrar_visual("😠", msg, cor, DURACAO_AVISO_VISUAL)
            registrar(f"Barulho! Aviso {self.avisos}/{maximo} enviado.")
        else:
            duracao = self._duracao_do_nivel(self.nivel_trava)
            self.nivel_trava += 1
            self._visual = None
            self._travar("barulho", duracao)
            registrar(f"Barulho depois de {maximo} avisos: travamento nº {self.nivel_trava} "
                      f"por {formatar_duracao(duracao)}.")

    def _montar_estado_cliente(self, agora):
        # "alerta": True pede ao aluno a janela grande e piscando.
        c = {"mostrar": False, "rosto": "", "mensagem": "", "cor": "", "alerta": False}
        if self.motivo_trava is None and agora < self._alerta_ate:
            c.update(mostrar=True, rosto="⏰", mensagem=MSG_ALERTA_FIM_AULA,
                     cor="#ffeb3b", alerta=True)
        elif self.motivo_trava == "barulho":
            c.update(mostrar=True, rosto="😡", cor="#ffcdd2",
                     mensagem=f"TELA TRAVADA\n{formatar_relogio(self.trava_ate - agora)}")
        elif self.motivo_trava == "teste":
            c.update(mostrar=True, rosto="😈", mensagem="TESTE DE\nTRAVA", cor="#ffcc80")
        elif self.motivo_trava is None and self._visual and agora < self._visual_ate:
            rosto, msg, cor = self._visual
            c.update(mostrar=True, rosto=rosto, mensagem=msg, cor=cor)
        self._cliente = c

    # ------------------------------------------------ ações do professor
    def liberar_manual(self):
        with self.lock:
            era_barulho = self.motivo_trava == "barulho"
            self._destravar()
            self.aula_encerrada = False
            self._visual = None
            self._alerta_ate = 0.0
            if era_barulho:
                agora = self._agora()
                self.ultima_violacao = agora
                self.ultima_atividade = agora
            registrar("Telas liberadas manualmente pelo professor.")

    def zerar_historico(self):
        with self.lock:
            self._zerar()
            self._visual = None
            registrar("Avisos e travamentos progressivos zerados pelo professor.")

    def iniciar_aula(self, minutos):
        """Retorna False se já existe um cronômetro rodando."""
        with self.lock:
            if self.timer_ativo:
                return False
            if self.motivo_trava == "fim_aula":
                self._destravar()
            self._ligar_cronometro(minutos)
            registrar(f"Cronômetro iniciado: {minutos} min.")
            return True

    def reiniciar_aula(self, minutos):
        with self.lock:
            self._destravar()
            self._zerar()
            self._visual = None
            self._ligar_cronometro(minutos)
            registrar(f"Aula reiniciada ({minutos} min): telas liberadas e avisos zerados.")

    def _ligar_cronometro(self, minutos):
        self.aula_encerrada = False
        self.timer_fim = self._agora() + minutos * 60
        self.timer_ativo = True
        self.timer_total = minutos * 60
        self._alerta_ate = 0.0
        # Aula de 5 min ou menos: não faz sentido avisar "faltam 5 minutos".
        self.alerta_5min_enviado = minutos * 60 <= AVISO_FIM_AULA_SEGUNDOS

    def parar_cronometro(self):
        with self.lock:
            self.timer_ativo = False
            self._alerta_ate = 0.0
            if self.motivo_trava == "fim_aula":
                self._destravar()
            self.aula_encerrada = False
            registrar("Cronômetro parado.")

    def testar_visual(self):
        with self.lock:
            self._mostrar_visual("😈", "TESTE VISUAL!", "#ffcc80", 5)
            registrar("Teste do bonequinho enviado (5 s).")

    def testar_trava(self):
        """Trava por alguns segundos para testar o Veyon."""
        with self.lock:
            if self.travado:
                return False
            self._travar("teste", DURACAO_TESTE_TRAVA)
            registrar(f"Teste de trava enviado ({DURACAO_TESTE_TRAVA} s).")
            return True

    def definir_automacao(self, ativa):
        with self.lock:
            self.cfg["automacao_ativa"] = ativa
            if not ativa:
                self._visual = None
                if self.motivo_trava == "barulho":
                    self._destravar()
            registrar("Automação " + ("ATIVADA." if ativa else "DESATIVADA."))

    def aplicar_config(self, novos):
        with self.lock:
            self.cfg.update(novos)

    # ------------------------------------------- leituras (API e painel)
    def estado_cliente(self):
        with self.lock:
            return dict(self._cliente)

    def estado_cronometro(self):
        with self.lock:
            restante = 0
            if self.timer_ativo:
                restante = max(0, int(math.ceil(self.timer_fim - self._agora())))
            return {"ativo": self.timer_ativo, "tempo_restante": restante,
                    "encerrada": self.aula_encerrada}

    def resumo(self):
        """Textos prontos para o painel do professor."""
        with self.lock:
            agora = self._agora()
            cfg = self.cfg
            maximo = cfg["max_avisos"]
            cooldown = cfg["cooldown_minutos"] * 60
            em_pausa = (self.ultima_violacao is not None
                        and agora - self.ultima_violacao < cooldown)

            # Linha de status do monitor de som
            if not cfg["automacao_ativa"]:
                status = ("Automação pausada", "gray")
            elif self.aula_encerrada:
                status = ("Aula encerrada - telas travadas", "#c62828")
            elif self.motivo_trava == "barulho":
                status = (f"TELAS TRAVADAS - faltam {formatar_relogio(self.trava_ate - agora)}",
                          "#c62828")
            elif self.motivo_trava == "teste":
                status = ("Testando a trava...", "#f57c00")
            elif self.volume is None:
                status = ("Microfone sem sinal!", "#c62828")
            elif self._visual and agora < self._visual_ate and self.avisos:
                status = (f"AVISO {self.avisos} ENVIADO!", "#f57c00")
            elif self.acima_limite and em_pausa:
                falta = cooldown - (agora - self.ultima_violacao)
                status = (f"Barulho! Próximo aviso em {formatar_relogio(falta)}", "#f57c00")
            else:
                status = (f"Ouvindo... (avisos {self.avisos}/{maximo})", "black")

            # Telas
            # (valor, legenda, cor)
            if self.motivo_trava == "barulho":
                telas = ("Travadas", f"barulho · faltam {formatar_relogio(self.trava_ate - agora)}",
                         "#c62828")
            elif self.motivo_trava == "fim_aula":
                telas = ("Travadas", "fim da aula", "#c62828")
            elif self.motivo_trava == "teste":
                telas = ("Travadas", "teste", "#f57c00")
            else:
                telas = ("Liberadas", "tudo certo", "#2e7d32")

            # Ficha limpa
            if self.travado or not (self.avisos or self.nivel_trava) or self.ultima_atividade is None:
                ficha = ("-", "nada a zerar")
            else:
                falta = cfg["ficha_limpa_minutos"] * 60 - (agora - self.ultima_atividade)
                ficha = (formatar_relogio(falta), "para zerar tudo")

            # Cronômetro
            restante, progresso = None, None
            if self.timer_ativo:
                restante = max(0.0, self.timer_fim - agora)
                crono = (formatar_relogio(restante), cor_do_tempo(restante))
                progresso = restante / self.timer_total if self.timer_total else None
            elif self.aula_encerrada:
                crono = ("ENCERRADA", "#c62828")
            else:
                crono = ("--:--", "gray")

            proxima = formatar_duracao(self._duracao_do_nivel(self.nivel_trava))
            return {
                "volume": self.volume or 0,
                "acima": self.acima_limite,
                "status": status,
                "avisos": (f"{self.avisos} / {maximo}",
                           "próxima: trava" if self.avisos >= maximo else "antes de travar"),
                "travamentos": (str(self.nivel_trava), f"próximo: {proxima}"),
                "telas": telas,
                "ficha": ficha,
                "cronometro": crono,
                "restante": restante,     # segundos, ou None sem aula
                "progresso": progresso,   # fração restante (1.0 -> 0.0) ou None
            }


# =====================================================================
# REDE: API para os alunos + anúncio automático de IP
# =====================================================================
def criar_app(ctrl):
    """API que os alunos consultam (uma vez por segundo).

    GET /status_monstrinho  -> o que o monstrinho deve mostrar
    GET /cronometro         -> estado do cronômetro da aula
    GET /info               -> identidade do painel (para reencontrá-lo)
    """
    app = Flask(__name__)

    @app.route("/status_monstrinho", methods=["GET"])
    def status_monstrinho():
        return jsonify(ctrl.estado_cliente())

    @app.route("/cronometro", methods=["GET"])
    def cronometro():
        return jsonify(ctrl.estado_cronometro())

    @app.route("/info", methods=["GET"])
    def info():
        # Identidade do painel: o aluno guarda para reencontrá-lo se o IP mudar
        return jsonify({"app": "monstrinho", "id": ctrl.cfg["painel_id"], "pc": NOME_PC,
                        "codigo": CODIGO_PAINEL})

    @app.after_request
    def sem_cache(resp):
        resp.headers["Cache-Control"] = "no-store"
        return resp

    return app


def iniciar_servidor_http(ctrl):
    if not FLASK_OK:
        registrar("ERRO: Flask não instalado (pip install flask). Os alunos não verão "
                  "o monstrinho nem o cronômetro; o travamento continua funcionando.")
        return

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app = criar_app(ctrl)

    def rodar():
        try:
            servidor = make_server("0.0.0.0", PORTA_HTTP, app, threaded=True)
        except OSError as e:
            registrar(f"ERRO: não foi possível abrir a porta {PORTA_HTTP} "
                      f"(o painel já está aberto?): {e}")
            return
        registrar(f"Servidor dos alunos ativo em http://{MEU_IP}:{PORTA_HTTP}")
        servidor.serve_forever()

    threading.Thread(target=rodar, daemon=True).start()


def iniciar_anuncio_ip(painel_id):
    """Avisa a rede "estou aqui" a cada 3 s (broadcast UDP na porta 5001).

    Os alunos escutam isso desde que o computador liga: assim encontram o
    painel sozinhos e o reencontram se o IP do professor mudar.
    """
    def laco():
        while True:
            ip = obter_ip_local()  # pode mudar (DHCP, troca de rede)
            mensagem = json.dumps({"app": "monstrinho", "porta": PORTA_HTTP, "id": painel_id,
                                   "pc": NOME_PC, "codigo": ip_para_codigo(ip)}).encode("utf-8")
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    try:
                        s.bind((ip, 0))  # sai pela placa de rede certa
                    except OSError:
                        pass
                    s.sendto(mensagem, ("255.255.255.255", PORTA_DESCOBERTA))
            except OSError:
                pass  # rede caiu? tenta de novo depois
            time.sleep(3)

    threading.Thread(target=laco, daemon=True).start()


# =====================================================================
# INTERFACE DO PROFESSOR  (tema escuro)
# =====================================================================
T = {
    "fundo": "#0d1222",     # fundo da janela
    "card": "#151c33",      # cartões
    "campo": "#1e2645",     # campos de texto / botões neutros
    "borda": "#28315a",
    "texto": "#e9edfb",
    "suave": "#9aa3c7",
    "apagado": "#5d6690",
    "roxo": "#7c5cff",
    "verde": "#22c55e",
    "amarelo": "#facc15",
    "laranja": "#fb923c",
    "vermelho": "#f43f5e",
    "azul": "#3b82f6",
}
# O Controlador usa cores pensadas para fundo claro; aqui viram as do tema.
CORES_TEMA = {"black": T["texto"], "gray": T["suave"], "#c62828": T["vermelho"],
              "#f57c00": T["laranja"], "#2e7d32": T["verde"]}
FONTE_UI = "Segoe UI"


def fonte(tamanho, peso="normal"):
    return (FONTE_UI, tamanho, peso)


def misturar(cor1, cor2, fator):
    """Mistura duas cores '#rrggbb' (fator 0 = cor1, 1 = cor2)."""
    a = [int(cor1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(cor2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * fator) for x, y in zip(a, b))


class Botao(tk.Label):
    """Botão plano com efeito ao passar o mouse (mesmo visual em qualquer Windows)."""

    def __init__(self, pai, texto, comando, cor, cor_texto="#ffffff", tam=10,
                 peso="bold", padx=14, pady=8):
        super().__init__(pai, text=texto, fg=cor_texto, font=fonte(tam, peso),
                         padx=padx, pady=pady, cursor="hand2")
        self.comando = comando
        self.pintar(cor)
        self.bind("<Enter>", lambda e: self.config(bg=self._hover))
        self.bind("<Leave>", lambda e: self.config(bg=self._cor))
        self.bind("<ButtonPress-1>", lambda e: self.config(bg=self._apertado))
        self.bind("<ButtonRelease-1>", self._soltar)

    def pintar(self, cor):
        self._cor = cor
        self._hover = misturar(cor, "#ffffff", 0.12)
        self._apertado = misturar(cor, "#000000", 0.18)
        self.config(bg=cor)

    def _soltar(self, e):
        dentro = 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()
        self.config(bg=self._hover if dentro else self._cor)
        if dentro and self.comando:
            self.comando()


def criar_card(pai, titulo=None):
    """Cartão com borda fina. Retorna (moldura, conteúdo)."""
    moldura = tk.Frame(pai, bg=T["borda"])
    corpo = tk.Frame(moldura, bg=T["card"], padx=18, pady=14)
    corpo.pack(fill="both", expand=True, padx=1, pady=1)
    if titulo:
        tk.Label(corpo, text=titulo.upper(), font=fonte(8, "bold"), fg=T["suave"],
                 bg=T["card"]).pack(anchor="w", pady=(0, 10))
    return moldura, corpo


def rotulo(pai, texto, tam=9, cor=None, peso="normal", bg=None):
    return tk.Label(pai, text=texto, font=fonte(tam, peso), fg=cor or T["suave"],
                    bg=bg or T["card"])


def estilizar_campo(w, **extra):
    w.config(bg=T["campo"], fg=T["texto"], insertbackground=T["texto"], relief="flat",
             bd=0, highlightthickness=1, highlightbackground=T["borda"],
             highlightcolor=T["roxo"], font=fonte(10), selectbackground=T["roxo"],
             selectforeground="#ffffff", **extra)


def desenhar_logo(cv):
    """Mini monstrinho do cabeçalho (44x44)."""
    cv.create_polygon(12, 13, 15, 2, 21, 10, fill="#ffe2b8", outline="")
    cv.create_polygon(23, 10, 29, 2, 32, 13, fill="#ffe2b8", outline="")
    cv.create_oval(5, 7, 39, 42, fill=T["roxo"], outline="")
    cv.create_oval(12, 16, 21, 26, fill="white", outline="")
    cv.create_oval(23, 16, 32, 26, fill="white", outline="")
    cv.create_oval(15, 19, 19, 24, fill="#141428", outline="")
    cv.create_oval(26, 19, 30, 24, fill="#141428", outline="")
    cv.create_arc(14, 24, 30, 36, start=200, extent=140, style="chord",
                  fill="#2a0f3a", outline="")


class Painel:
    def __init__(self, root, cfg, ctrl, mic, veyon):
        self.root = root
        self.cfg = cfg
        self.ctrl = ctrl
        self.mic = mic
        self.veyon = veyon
        self._vol_exibido = 0.0

        root.title("Monstrinho do Barulho - Painel do Professor")
        root.configure(bg=T["fundo"])
        root.geometry("1180x800")
        root.minsize(1080, 740)
        root.protocol("WM_DELETE_WINDOW", self.ao_fechar)

        self._estilos_ttk()
        self._montar_interface()
        self._registrar_avisos_iniciais()

        root.after(300, self._abrir_microfone_inicial)
        root.after(INTERVALO_CICLO_MS, self._ciclo)

    # ----------------------------------------------------------- estilo
    def _estilos_ttk(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Escuro.TCombobox", fieldbackground=T["campo"], background=T["campo"],
                     foreground=T["texto"], arrowcolor=T["texto"], bordercolor=T["borda"],
                     lightcolor=T["campo"], darkcolor=T["campo"], padding=6)
        st.map("Escuro.TCombobox",
               fieldbackground=[("readonly", T["campo"]), ("disabled", T["card"])],
               foreground=[("readonly", T["texto"]), ("disabled", T["apagado"])],
               selectbackground=[("readonly", T["campo"])],
               selectforeground=[("readonly", T["texto"])],
               background=[("active", T["borda"])])
        r = self.root
        r.option_add("*TCombobox*Listbox.background", T["campo"])
        r.option_add("*TCombobox*Listbox.foreground", T["texto"])
        r.option_add("*TCombobox*Listbox.selectBackground", T["roxo"])
        r.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        r.option_add("*TCombobox*Listbox.font", fonte(10))

    def _pilula(self, pai, texto, cor_ponto):
        f = tk.Frame(pai, bg=T["campo"], padx=12, pady=7)
        ponto = tk.Label(f, text="●", fg=cor_ponto, bg=T["campo"], font=fonte(9))
        ponto.pack(side="left")
        tk.Label(f, text=texto, fg=T["texto"], bg=T["campo"],
                 font=fonte(9)).pack(side="left", padx=(6, 0))
        return f

    # ----------------------------------------------------------- layout
    def _montar_interface(self):
        r = self.root

        # ======================= CABEÇALHO =======================
        topo = tk.Frame(r, bg=T["fundo"])
        topo.pack(fill="x", padx=24, pady=(18, 14))
        logo = tk.Canvas(topo, width=44, height=44, bg=T["fundo"], highlightthickness=0)
        logo.pack(side="left")
        desenhar_logo(logo)
        titulos = tk.Frame(topo, bg=T["fundo"])
        titulos.pack(side="left", padx=12)
        tk.Label(titulos, text="Monstrinho do Barulho", font=fonte(18, "bold"),
                 fg=T["texto"], bg=T["fundo"]).pack(anchor="w")
        tk.Label(titulos, text="Painel do professor", font=fonte(10),
                 fg=T["suave"], bg=T["fundo"]).pack(anchor="w")

        self.btn_auto = Botao(topo, "", self.alternar_automacao, T["verde"], padx=16, pady=9)
        self.btn_auto.pack(side="right")
        self._pintar_botao_automacao()
        codigo = tk.Frame(topo, bg=T["roxo"], padx=14, pady=4)
        codigo.pack(side="right", padx=(0, 10))
        tk.Label(codigo, text="CÓDIGO DO PAINEL", font=fonte(7, "bold"), fg="#d9d0ff",
                 bg=T["roxo"]).pack(anchor="w")
        tk.Label(codigo, text=f"{CODIGO_PAINEL}", font=("Consolas", 14, "bold"), fg="#ffffff",
                 bg=T["roxo"]).pack(anchor="w")
        self._pilula(topo, f"IP {MEU_IP}:{PORTA_HTTP}", T["azul"]).pack(side="right",
                                                                        padx=(0, 10))
        if self.veyon.disponivel:
            self._pilula(topo, "Veyon encontrado", T["verde"]).pack(side="right", padx=(0, 10))
        else:
            self._pilula(topo, "Veyon NÃO encontrado",
                         T["vermelho"]).pack(side="right", padx=(0, 10))

        # ======================= CORPO (2 colunas) =======================
        corpo = tk.Frame(r, bg=T["fundo"])
        corpo.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        corpo.columnconfigure(0, weight=3, uniform="col")
        corpo.columnconfigure(1, weight=2, uniform="col")
        corpo.rowconfigure(0, weight=1)
        esq = tk.Frame(corpo, bg=T["fundo"])
        esq.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        dir_ = tk.Frame(corpo, bg=T["fundo"])
        dir_.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        self._montar_cronometro(esq)
        self._montar_monitor(esq)
        self._montar_situacao(esq)
        self._montar_acoes(esq)
        self._montar_configuracao(dir_)
        self._montar_registro(dir_)

    def _montar_cronometro(self, pai):
        m, c = criar_card(pai, "Cronômetro da aula")
        m.pack(fill="x")
        linha = tk.Frame(c, bg=T["card"])
        linha.pack(fill="x")
        self.lbl_crono = tk.Label(linha, text="--:--", font=fonte(44, "bold"),
                                  fg=T["suave"], bg=T["card"])
        self.lbl_crono.pack(side="left")

        lado = tk.Frame(linha, bg=T["card"])
        lado.pack(side="right", anchor="e")
        dur = tk.Frame(lado, bg=T["card"])
        dur.pack(anchor="e", pady=(0, 8))
        rotulo(dur, "Duração").pack(side="left")
        self.ent_duracao = tk.Entry(dur, width=5, justify="center")
        estilizar_campo(self.ent_duracao)
        self.ent_duracao.insert(0, str(self.cfg["duracao_aula_minutos"]))
        self.ent_duracao.pack(side="left", padx=8, ipady=4)
        rotulo(dur, "min").pack(side="left")
        botoes = tk.Frame(lado, bg=T["card"])
        botoes.pack(anchor="e")
        Botao(botoes, "▶  Iniciar aula", self.iniciar_aula, T["roxo"]).pack(side="left")
        Botao(botoes, "↻  Reiniciar e liberar", self.reiniciar_aula,
              T["verde"]).pack(side="left", padx=6)
        Botao(botoes, "■  Parar", self.parar_cronometro, T["campo"],
              cor_texto=T["texto"]).pack(side="left")

        self.cv_prog = tk.Canvas(c, height=6, bg=T["card"], highlightthickness=0)
        self.cv_prog.pack(fill="x", pady=(12, 0))
        self.lbl_crono_info = rotulo(c, "Nenhuma aula em andamento")
        self.lbl_crono_info.pack(anchor="w", pady=(6, 0))

    def _montar_monitor(self, pai):
        m, c = criar_card(pai, "Monitor de som ao vivo")
        m.pack(fill="x", pady=(16, 0))
        self.cv_medidor = tk.Canvas(c, height=44, bg=T["card"], highlightthickness=0)
        self.cv_medidor.pack(fill="x")
        self.lbl_status = tk.Label(c, text="Iniciando...", font=fonte(13, "bold"),
                                   fg=T["texto"], bg=T["card"])
        self.lbl_status.pack(anchor="w", pady=(10, 8))

        sens = tk.Frame(c, bg=T["card"])
        sens.pack(fill="x")
        rotulo(sens, "Sensibilidade (limite de barulho)").pack(side="left")
        self.lbl_limite = rotulo(sens, "", 10, T["texto"], "bold")
        self.lbl_limite.pack(side="right")
        self.scale_limite = tk.Scale(
            c, from_=5, to=100, orient="horizontal", showvalue=0, bg=T["roxo"],
            troughcolor=T["campo"], activebackground="#9b85ff", highlightthickness=0,
            bd=0, sliderrelief="flat", sliderlength=26, width=14,
            command=self._mudou_limite)
        self.scale_limite.set(self.cfg["limite_ruido"])
        self.scale_limite.pack(fill="x", pady=(6, 0))

    def _montar_situacao(self, pai):
        grade = tk.Frame(pai, bg=T["fundo"])
        grade.pack(fill="x", pady=(16, 0))
        self.lbl_info = {}
        itens = [("telas", "Telas"), ("avisos", "Avisos"),
                 ("travamentos", "Travamentos"), ("ficha", "Ficha limpa")]
        for i, (chave, titulo) in enumerate(itens):
            grade.columnconfigure(i, weight=1, uniform="tile")
            m, c = criar_card(grade)
            m.grid(row=0, column=i, sticky="nsew",
                   padx=(0 if i == 0 else 6, 0 if i == len(itens) - 1 else 6))
            rotulo(c, titulo.upper(), 8, peso="bold").pack(anchor="w")
            valor = tk.Label(c, text="-", font=fonte(16, "bold"), fg=T["texto"], bg=T["card"])
            valor.pack(anchor="w", pady=(4, 0))
            legenda = rotulo(c, "", 8, T["apagado"])
            legenda.pack(anchor="w")
            self.lbl_info[chave] = (valor, legenda)

    def _montar_acoes(self, pai):
        Botao(pai, "🔓  LIBERAR TELAS AGORA", self.liberar, T["amarelo"],
              cor_texto="#1d1600", tam=13, pady=14).pack(fill="x", pady=(16, 8))
        acoes = tk.Frame(pai, bg=T["fundo"])
        acoes.pack(fill="x")
        itens = [("Zerar avisos", self.zerar),
                 ("Testar bonequinho", self.ctrl.testar_visual),
                 ("Testar trava (5 s)", self.testar_trava),
                 ("Diagnóstico do Veyon", self.diagnostico_veyon)]
        for i, (txt, cmd) in enumerate(itens):
            acoes.columnconfigure(i, weight=1, uniform="acao")
            Botao(acoes, txt, cmd, T["campo"], cor_texto=T["texto"], tam=9,
                  peso="normal").grid(row=0, column=i, sticky="ew",
                                      padx=(0 if i == 0 else 4, 0 if i == len(itens) - 1 else 4))

    def _montar_configuracao(self, pai):
        m, c = criar_card(pai, "Configuração")
        m.pack(fill="x")

        rotulo(c, "Computadores a travar (um por linha, como no Veyon Master)").pack(anchor="w")
        self.txt_pcs = tk.Text(c, height=4, width=30, wrap="none", padx=8, pady=6)
        estilizar_campo(self.txt_pcs)
        self.txt_pcs.pack(fill="x", pady=(4, 12))
        self.txt_pcs.insert("1.0", "\n".join(self.cfg["computadores"]))
        self.txt_pcs.bind("<KeyRelease>", lambda e: self._aplicar_pcs_e_recurso())
        self.txt_pcs.bind("<FocusOut>", lambda e: self._aplicar_pcs_e_recurso())

        rotulo(c, "Recurso de travamento do Veyon").pack(anchor="w")
        self.ent_recurso = tk.Entry(c)
        estilizar_campo(self.ent_recurso)
        self.ent_recurso.insert(0, self.cfg["recurso_travar"])
        self.ent_recurso.pack(fill="x", pady=(4, 12), ipady=5)
        self.ent_recurso.bind("<KeyRelease>", lambda e: self._aplicar_pcs_e_recurso())

        rotulo(c, "Microfone").pack(anchor="w")
        self.opcoes_mic = Microfone.listar()
        self.cmb_mic = ttk.Combobox(c, values=self.opcoes_mic, state="readonly",
                                    style="Escuro.TCombobox", font=fonte(10))
        self.cmb_mic.pack(fill="x", pady=(4, 12))
        self.cmb_mic.bind("<<ComboboxSelected>>", lambda e: self._trocar_microfone())
        if not AUDIO_OK:
            self.cmb_mic.set("Instale: pip install numpy sounddevice")
            self.cmb_mic.configure(state="disabled")
        elif not self.opcoes_mic:
            self.cmb_mic.set("Nenhum microfone encontrado")

        grade = tk.Frame(c, bg=T["card"])
        grade.pack(fill="x")
        grade.columnconfigure(0, weight=1)
        grade.columnconfigure(1, weight=1)
        self.spin_avisos = self._campo_regra(grade, 0, 0, "Avisos antes de travar", 1, 20,
                                             self.cfg["max_avisos"])
        self.spin_cooldown = self._campo_regra(grade, 0, 1, "Intervalo entre avisos (min)",
                                               1, 60, self.cfg["cooldown_minutos"])
        self.spin_ficha = self._campo_regra(grade, 1, 0, "Ficha limpa após (min)", 1, 180,
                                            self.cfg["ficha_limpa_minutos"])
        caixa = tk.Frame(grade, bg=T["card"])
        caixa.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(0, 10))
        rotulo(caixa, "Tempos de trava (s)").pack(anchor="w")
        self.ent_tempos = tk.Entry(caixa)
        estilizar_campo(self.ent_tempos)
        self.ent_tempos.insert(0, ", ".join(str(t) for t in self.cfg["tempos_trava_segundos"]))
        self.ent_tempos.pack(fill="x", pady=(4, 0), ipady=4)

        rotulo(c, "30, 60, 120 = 1ª trava 30 s, 2ª 1 min, da 3ª em diante 2 min.", 8,
               T["apagado"]).pack(anchor="w", pady=(0, 12))
        Botao(c, "Salvar alterações", self.salvar, T["roxo"]).pack(fill="x")

    def _campo_regra(self, pai, linha, coluna, texto, minimo, maximo, valor):
        caixa = tk.Frame(pai, bg=T["card"])
        caixa.grid(row=linha, column=coluna, sticky="ew",
                   padx=(0, 6) if coluna == 0 else (6, 0), pady=(0, 10))
        rotulo(caixa, texto).pack(anchor="w")
        sp = tk.Spinbox(caixa, from_=minimo, to=maximo, justify="center")
        estilizar_campo(sp, buttonbackground=T["campo"])
        sp.delete(0, "end")
        sp.insert(0, str(valor))
        sp.pack(fill="x", pady=(4, 0), ipady=4)
        return sp

    def _montar_registro(self, pai):
        m, c = criar_card(pai, "Registro")
        m.pack(fill="both", expand=True, pady=(16, 0))
        self.txt_log = tk.Text(c, height=6, font=("Consolas", 9), bg=T["card"],
                               fg=T["suave"], relief="flat", bd=0, highlightthickness=0,
                               wrap="word", state="disabled", spacing1=2, spacing3=2)
        self.txt_log.pack(fill="both", expand=True)
        self.txt_log.tag_configure("hora", foreground=T["apagado"])
        self.txt_log.tag_configure("erro", foreground=T["vermelho"])
        self.txt_log.tag_configure("ok", foreground=T["verde"])
        self.txt_log.tag_configure("aviso", foreground=T["laranja"])
        self.txt_log.tag_configure("info", foreground=T["suave"])

    def _registrar_avisos_iniciais(self):
        registrar(f"Painel iniciado. Código para os alunos: {CODIGO_PAINEL} (IP {MEU_IP}).")
        if not AUDIO_OK:
            registrar("ERRO: áudio indisponível (pip install numpy sounddevice).")
        if not self.veyon.disponivel:
            registrar("ERRO: veyon-cli.exe não encontrado. Instale o Veyon Master ou "
                      "ajuste 'veyon_cli' no config_professor.json.")

    def _aplicar_pcs_e_recurso(self):
        """A lista de computadores e o recurso valem assim que são digitados."""
        pcs = [p.strip() for p in self.txt_pcs.get("1.0", "end").splitlines() if p.strip()]
        recurso = self.ent_recurso.get().strip() or "ScreenLock"
        self.ctrl.aplicar_config({"computadores": pcs, "recurso_travar": recurso})

    # ------------------------------------------------- diagnóstico Veyon
    def diagnostico_veyon(self):
        """Roda testes do veyon-cli e mostra a saída COMPLETA numa janela."""
        self._aplicar_pcs_e_recurso()
        pcs = list(self.cfg["computadores"])
        recurso = self.cfg["recurso_travar"]

        jan = tk.Toplevel(self.root, bg=T["fundo"])
        jan.title("Diagnóstico do Veyon")
        jan.geometry("780x540")
        m, c = criar_card(jan, "Diagnóstico do Veyon")
        m.pack(fill="both", expand=True, padx=16, pady=16)
        txt = tk.Text(c, font=("Consolas", 9), wrap="word", bg=T["card"], fg=T["texto"],
                      relief="flat", bd=0, highlightthickness=0, insertbackground=T["texto"])
        txt.pack(fill="both", expand=True)
        saida = queue.Queue()

        def escrever(t=""):
            saida.put(t + "\n")

        def passo(titulo, *args, timeout=TIMEOUT_VEYON):
            escrever(f"=== {titulo} ===")
            escrever("> veyon-cli " + " ".join(f'"{a}"' if " " in a else a for a in args))
            codigo, texto = self.veyon.rodar(*args, timeout=timeout)
            escrever(texto or "(sem saída)")
            escrever(f"[código de saída: {codigo}]\n")
            return codigo, texto

        def testes():
            escrever(f"veyon-cli: {self.veyon.exe or 'NÃO ENCONTRADO'}")
            escrever(f"Computadores: {pcs or '(lista vazia!)'}")
            escrever(f"Recurso: {recurso}\n")
            if not self.veyon.disponivel:
                escrever("Instale o Veyon (com o componente Master) neste PC.")
                return
            passo("Versão", "about")
            _, lista = passo("Recursos disponíveis (procure o nome da trava de tela)",
                             "feature", "list")
            if lista and recurso.lower() not in lista.lower():
                escrever(f"*** ATENÇÃO: '{recurso}' não aparece na lista acima. Copie o nome "
                         "exato do recurso de travar tela para o campo do painel. ***\n")
            passo("Chaves de autenticação", "authkeys", "list")
            if not pcs:
                escrever("Lista de computadores vazia: nada para testar.")
                return
            pc = pcs[0]
            escrever(f">>> Travando {pc} por 5 segundos (olhe a tela desse aluno)...\n")
            passo(f"Travar {pc}", "feature", "start", pc, recurso)
            time.sleep(5)
            passo(f"Destravar {pc}", "feature", "stop", pc, recurso)
            escrever("Fim do diagnóstico. Se a tela não travou, veja as mensagens acima "
                     "(principalmente erros de autenticação) e o LEIA-ME.")

        def mostrar():
            if not jan.winfo_exists():
                return
            while not saida.empty():
                txt.insert("end", saida.get())
                txt.see("end")
            jan.after(200, mostrar)

        threading.Thread(target=testes, daemon=True).start()
        mostrar()

    # -------------------------------------------------------- microfone
    def _abrir_microfone_inicial(self):
        if not AUDIO_OK or not self.opcoes_mic:
            return
        escolha = None
        salvo = self.cfg.get("microfone", "")
        if salvo:  # procura pelo nome (o índice pode mudar entre reinícios)
            escolha = next((o for o in self.opcoes_mic if o.split(" - ", 1)[-1] == salvo), None)
        if escolha is None:
            idx = Microfone.indice_padrao()
            if idx is not None:
                escolha = next((o for o in self.opcoes_mic if o.startswith(f"{idx} - ")), None)
        escolha = escolha or self.opcoes_mic[0]
        self.cmb_mic.set(escolha)
        self._trocar_microfone(salvar=False)

    def _trocar_microfone(self, salvar=True):
        opcao = self.cmb_mic.get()
        if self.mic.iniciar(opcao):
            registrar(f"Microfone: {opcao}")
            if salvar:
                self.cfg["microfone"] = opcao.split(" - ", 1)[-1]
                self._gravar_arquivo(silencioso=True)
        else:
            messagebox.showwarning("Microfone", "Não foi possível abrir este microfone.\n"
                                   "Escolha outro na lista.")

    # ------------------------------------------------------------ ações
    def _mudou_limite(self, valor):
        self.ctrl.aplicar_config({"limite_ruido": int(float(valor))})

    def _ler_duracao(self):
        try:
            minutos = int(self.ent_duracao.get())
            if minutos <= 0:
                raise ValueError
        except ValueError:
            minutos = 45
            self.ent_duracao.delete(0, "end")
            self.ent_duracao.insert(0, "45")
        if minutos != self.cfg["duracao_aula_minutos"]:
            self.cfg["duracao_aula_minutos"] = minutos
            self._gravar_arquivo(silencioso=True)
        return minutos

    def iniciar_aula(self):
        if not self.ctrl.iniciar_aula(self._ler_duracao()):
            messagebox.showinfo("Cronômetro", "O cronômetro já está rodando.\n"
                                "Use \"Reiniciar e liberar\" para começar de novo.")

    def reiniciar_aula(self):
        self.ctrl.reiniciar_aula(self._ler_duracao())

    def parar_cronometro(self):
        if messagebox.askyesno("Cronômetro", "Parar o cronômetro da aula?"):
            self.ctrl.parar_cronometro()

    def liberar(self):
        self.ctrl.liberar_manual()

    def zerar(self):
        self.ctrl.zerar_historico()

    def testar_trava(self):
        if not self.ctrl.testar_trava():
            messagebox.showinfo("Teste", "As telas já estão travadas.")

    def alternar_automacao(self):
        self.ctrl.definir_automacao(not self.cfg["automacao_ativa"])
        self._pintar_botao_automacao()
        self._gravar_arquivo(silencioso=True)

    def _pintar_botao_automacao(self):
        if self.cfg["automacao_ativa"]:
            self.btn_auto.config(text="●  Automação ativa")
            self.btn_auto.pintar(T["verde"])
        else:
            self.btn_auto.config(text="○  Automação pausada")
            self.btn_auto.pintar(T["vermelho"])

    def salvar(self):
        """Valida os campos, aplica na hora e grava no arquivo."""
        def inteiro(spin, nome, minimo, maximo):
            try:
                v = int(spin.get())
            except ValueError:
                raise ValueError(f"\"{nome}\" precisa ser um número inteiro.")
            if not minimo <= v <= maximo:
                raise ValueError(f"\"{nome}\" deve estar entre {minimo} e {maximo}.")
            return v

        try:
            pcs = [p.strip() for p in self.txt_pcs.get("1.0", "end").splitlines() if p.strip()]
            recurso = self.ent_recurso.get().strip()
            if not recurso:
                raise ValueError("Informe o recurso de travamento do Veyon (ex.: ScreenLock).")
            max_avisos = inteiro(self.spin_avisos, "Avisos antes de travar", 1, 20)
            cooldown = inteiro(self.spin_cooldown, "Intervalo entre avisos", 1, 60)
            ficha = inteiro(self.spin_ficha, "Ficha limpa", 1, 180)
            try:
                tempos = [int(t) for t in self.ent_tempos.get().replace(";", ",").split(",")
                          if t.strip()]
            except ValueError:
                raise ValueError("Tempos de trava: use números separados por vírgula "
                                 "(ex.: 30, 60, 120).")
            if not tempos or any(t <= 0 or t > 3600 for t in tempos):
                raise ValueError("Tempos de trava: cada valor deve estar entre 1 e 3600 s.")
        except ValueError as e:
            messagebox.showerror("Configuração inválida", str(e))
            return

        if not pcs:
            if not messagebox.askyesno("Atenção", "A lista de computadores está vazia: "
                                       "nenhuma tela será travada. Salvar mesmo assim?"):
                return

        self.ctrl.aplicar_config({
            "computadores": pcs,
            "recurso_travar": recurso,
            "limite_ruido": int(self.scale_limite.get()),
            "max_avisos": max_avisos,
            "cooldown_minutos": cooldown,
            "ficha_limpa_minutos": ficha,
            "tempos_trava_segundos": tempos,
        })
        self.ent_tempos.delete(0, "end")
        self.ent_tempos.insert(0, ", ".join(str(t) for t in tempos))

        if self._gravar_arquivo():
            msg = "Configurações aplicadas e salvas!"
            if ficha <= cooldown:
                msg += ("\n\nAtenção: a \"ficha limpa\" está menor ou igual ao intervalo "
                        "entre avisos. Assim os avisos zeram antes de acumular e as telas "
                        "quase nunca travam.")
            messagebox.showinfo("Salvo", msg)
            registrar("Configurações salvas.")

    def _gravar_arquivo(self, silencioso=False):
        try:
            with self.ctrl.lock:
                salvar_config_arquivo(self.cfg)
            return True
        except OSError as e:
            if not silencioso:
                messagebox.showwarning("Aviso", f"As configurações valem agora, mas não "
                                       f"puderam ser gravadas no arquivo:\n{e}")
            return False

    # ------------------------------------------------------ laço da tela
    def _ciclo(self):
        try:
            self.ctrl.ciclo(self.mic.ler())
            self._atualizar_tela()
            self._mostrar_registros()
        except Exception as e:  # um erro nunca pode parar o painel
            registrar(f"Erro interno: {e!r}")
        finally:
            self.root.after(INTERVALO_CICLO_MS, self._ciclo)

    def _atualizar_tela(self):
        r = self.ctrl.resumo()
        tema = lambda cor: CORES_TEMA.get(cor, cor)

        self._desenhar_medidor(r["volume"])
        texto, cor = r["status"]
        self.lbl_status.config(text=texto, fg=tema(cor))
        self.lbl_limite.config(text=f"{self.cfg['limite_ruido']}%")

        texto, legenda, cor = r["telas"]
        self.lbl_info["telas"][0].config(text=texto, fg=tema(cor))
        self.lbl_info["telas"][1].config(text=legenda)
        for chave in ("avisos", "travamentos", "ficha"):
            texto, legenda = r[chave]
            self.lbl_info[chave][0].config(text=texto)
            self.lbl_info[chave][1].config(text=legenda)

        texto, cor = r["cronometro"]
        self.lbl_crono.config(text=texto, fg=tema(cor),
                              font=fonte(44 if ":" in texto else 30, "bold"))
        self._desenhar_progresso(r["progresso"], tema(cor))
        if r["restante"] is not None:
            fim = time.strftime("%H:%M", time.localtime(time.time() + r["restante"]))
            info = f"Termina às {fim}  ·  alerta aos alunos quando faltar 5 min"
        elif texto == "ENCERRADA":
            info = "Aula encerrada: telas travadas até você liberar"
        else:
            info = "Nenhuma aula em andamento"
        self.lbl_crono_info.config(text=info)

    def _desenhar_medidor(self, volume):
        """Medidor em segmentos (verde -> amarelo -> vermelho) com a linha do limite."""
        cv = self.cv_medidor
        cv.delete("all")
        largura = max(cv.winfo_width(), 100)
        altura = 44
        # Sobe na hora e desce devagar: fica mais fácil de ler
        self._vol_exibido = max(float(volume), self._vol_exibido * 0.8)
        limite = self.cfg["limite_ruido"]
        n, espaco = 40, 3
        seg = (largura - espaco * (n - 1)) / n
        acesos = round(self._vol_exibido / 100 * n)
        for i in range(n):
            pct = (i + 0.5) / n * 100
            if pct > limite:
                cor = T["vermelho"]
            elif pct > limite * 0.75:
                cor = T["amarelo"]
            else:
                cor = T["verde"]
            if i >= acesos:
                cor = misturar(T["campo"], cor, 0.15)
            x = i * (seg + espaco)
            cv.create_rectangle(x, 12, x + seg, altura - 4, fill=cor, outline="")
        xl = min(largura - 2, max(2, limite / 100 * largura))
        cv.create_line(xl, 8, xl, altura, fill=T["texto"], width=2)
        cv.create_polygon(xl - 6, 0, xl + 6, 0, xl, 8, fill=T["texto"], outline="")

    def _desenhar_progresso(self, fracao, cor):
        cv = self.cv_prog
        cv.delete("all")
        largura = max(cv.winfo_width(), 100)
        cv.create_rectangle(0, 0, largura, 6, fill=T["campo"], outline="")
        if fracao:
            cv.create_rectangle(0, 0, largura * fracao, 6, fill=cor, outline="")

    def _mostrar_registros(self):
        linhas = []
        while True:
            try:
                linhas.append(FILA_LOG.get_nowait())
            except queue.Empty:
                break
        if not linhas:
            return
        self.txt_log.configure(state="normal")
        for linha in linhas:
            hora, _, msg = linha.partition("] ")
            if any(p in msg for p in ("FALHOU", "ERRO", "Erro", "FIM DA AULA")):
                tag = "erro"
            elif "OK" in msg or "liberadas" in msg or "Ficha limpa" in msg:
                tag = "ok"
            elif any(p in msg for p in ("Aviso", "Barulho", "travamento", "Alerta")):
                tag = "aviso"
            else:
                tag = "info"
            self.txt_log.insert("end", hora + "]  ", "hora")
            self.txt_log.insert("end", msg + "\n", tag)
            if "FIM DA AULA" in msg:
                self.root.bell()
        excesso = int(self.txt_log.index("end-1c").split(".")[0]) - 300
        if excesso > 0:
            self.txt_log.delete("1.0", f"{excesso + 1}.0")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def ao_fechar(self):
        if self.ctrl.travado:
            r = messagebox.askyesnocancel(
                "Sair", "As telas dos alunos estão TRAVADAS.\n\nDestravar antes de sair?")
            if r is None:
                return
            if r:
                self.root.config(cursor="watch")
                self.root.update()
                self.veyon.enviar_e_aguardar("stop", self.cfg["computadores"],
                                             self.cfg["recurso_travar"])
        self.mic.parar()
        self.root.destroy()


# =====================================================================
# INÍCIO
# =====================================================================
def main():
    cfg = carregar_config()
    veyon = Veyon(cfg["veyon_cli"])
    ctrl = Controlador(cfg, veyon)
    mic = Microfone()

    iniciar_servidor_http(ctrl)
    iniciar_anuncio_ip(cfg["painel_id"])

    root = tk.Tk()
    Painel(root, cfg, ctrl, mic, veyon)
    root.mainloop()


if __name__ == "__main__":
    main()
