"""Configuração comum dos testes.

Os dois programas ficam em src/ e são carregados direto do arquivo (o do
aluno tem extensão .pyw). Se o Python não tiver Tkinter (ex.: servidor de CI
mínimo), um substituto vazio é usado: os testes só exercitam a lógica.
"""
import importlib.machinery
import importlib.util
import pathlib
import sys
import types

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def _garantir_tkinter():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        tk = types.ModuleType("tkinter")
        tk.Label = object
        tk.TclError = Exception
        tk.messagebox = types.ModuleType("tkinter.messagebox")
        tk.ttk = types.ModuleType("tkinter.ttk")
        sys.modules.update({"tkinter": tk, "tkinter.messagebox": tk.messagebox,
                            "tkinter.ttk": tk.ttk})


def _carregar(nome, arquivo):
    _garantir_tkinter()
    loader = importlib.machinery.SourceFileLoader(nome, str(RAIZ / "src" / arquivo))
    spec = importlib.util.spec_from_loader(nome, loader)
    modulo = importlib.util.module_from_spec(spec)
    loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="session")
def srv():
    return _carregar("servidor_veyon", "servidor_veyon.py")


@pytest.fixture(scope="session")
def cli():
    return _carregar("cliente_aluno", "cliente_aluno.pyw")


class VeyonFalso:
    """Registra os comandos em vez de chamar o veyon-cli."""

    def __init__(self):
        self.comandos = []

    def enviar(self, acao, computadores, recurso):
        self.comandos.append(acao)


class Relogio:
    """Relógio controlado pelo teste (segundos)."""

    def __init__(self):
        self.agora = 1000.0

    def __call__(self):
        return self.agora


@pytest.fixture
def ambiente(srv, tmp_path, monkeypatch):
    """Controlador com Veyon falso, relógio falso e config em pasta temporária."""
    monkeypatch.setattr(srv, "ARQUIVO_CONFIG", str(tmp_path / "config_professor.json"))
    cfg = srv.carregar_config()
    veyon, relogio = VeyonFalso(), Relogio()
    ctrl = srv.Controlador(cfg, veyon, relogio=relogio)

    def passo(segundos, volume):
        relogio.agora += segundos
        ctrl.ciclo(volume)

    return types.SimpleNamespace(ctrl=ctrl, veyon=veyon, relogio=relogio, passo=passo, cfg=cfg)
