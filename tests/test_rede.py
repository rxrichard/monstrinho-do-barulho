"""Código do painel, API HTTP e reencontro do professor (cliente)."""
import time

import pytest


@pytest.mark.parametrize("ip", ["192.168.0.106", "10.0.0.5", "172.16.31.200",
                                "0.0.0.0", "255.255.255.255"])
def test_codigo_ida_e_volta(srv, cli, ip):
    codigo = srv.ip_para_codigo(ip)
    assert codigo == cli.ip_para_codigo(ip)  # servidor e cliente usam a mesma conta
    assert cli.codigo_para_ip(codigo) == ip
    assert cli.codigo_para_ip(codigo.lower().replace("-", "")) == ip


def test_codigo_tolera_letras_parecidas(cli):
    assert cli.codigo_para_ip("3OAG-O3A") == cli.codigo_para_ip("30AG-03A") == "192.168.0.106"


@pytest.mark.parametrize("texto, esperado", [
    ("30ag-03a", "192.168.0.106"),
    ("192.168.0.50", "192.168.0.50"),
    ("SALA-PROF.escola.local", "SALA-PROF.escola.local"),
    ("auto", "auto"),
    ("", None),
    ("a b", None),
])
def test_interpretar_destino(cli, texto, esperado):
    assert cli.interpretar_destino(texto) == esperado


def test_api_flask(srv, ambiente):
    flask = pytest.importorskip("flask")  # noqa: F841
    cliente = srv.criar_app(ambiente.ctrl).test_client()
    ambiente.ctrl.iniciar_aula(45)
    ambiente.passo(1, 0)
    cron = cliente.get("/cronometro").get_json()
    assert cron["ativo"] and cron["tempo_restante"] == 45 * 60 - 1
    assert cliente.get("/status_monstrinho").get_json()["mostrar"] is False
    info = cliente.get("/info").get_json()
    assert info["app"] == "monstrinho" and info["id"] == ambiente.cfg["painel_id"]
    assert cliente.get("/cronometro").headers["Cache-Control"] == "no-store"


def test_painel_ganha_identidade_fixa(srv, ambiente):
    assert len(ambiente.cfg["painel_id"]) == 12
    assert srv.carregar_config()["painel_id"] == ambiente.cfg["painel_id"]  # foi salvo


@pytest.fixture
def config_temporaria(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "caminhos_config", lambda: [str(tmp_path / "config_aluno.ini")])
    return tmp_path


def test_config_do_aluno(cli, config_temporaria):
    assert cli.carregar_config()["configurado"] is False  # 1ª abertura pede o código
    cli.salvar_config("192.168.0.106", 5000, "abc123", "PROF-01")
    cfg = cli.carregar_config()
    assert (cfg["ip"], cfg["painel_id"], cfg["pc"], cfg["configurado"]) == \
           ("192.168.0.106", "abc123", "PROF-01", True)


def conexao(cli, ip="10.9.9.9", painel_id="abc123", pc=""):
    return cli.Conexao({"ip": ip, "porta": 5000, "painel_id": painel_id, "pc": pc,
                        "configurado": bool(ip)})


def test_so_aceita_o_mesmo_painel(cli):
    c = conexao(cli)
    assert c._combina({"id": "abc123"})
    assert not c._combina({"id": "outra-sala"})
    assert conexao(cli, painel_id="", pc="PROF-01")._combina({"pc": "prof-01"})
    assert not conexao(cli, painel_id="")._combina({"id": "x"})  # sem identidade: não arrisca
    assert conexao(cli, ip="")._combina({"id": "qualquer"})      # modo automático


def test_reencontra_professor_que_mudou_de_ip(cli, config_temporaria):
    c = conexao(cli)
    c._falhas = cli.FALHAS_PARA_SEM_CONEXAO
    c._anuncio = ("192.168.0.77", 5000, "abc123", "PROF-01", time.monotonic())
    c._talvez_trocar_de_ip()
    assert c.ip_atual == "192.168.0.77"
    salvo = cli.carregar_config()
    assert (salvo["ip"], salvo["pc"]) == ("192.168.0.77", "PROF-01")  # próximo boot já começa certo


def test_nao_troca_com_anuncio_velho(cli, config_temporaria):
    c = conexao(cli)
    c._falhas = cli.FALHAS_PARA_SEM_CONEXAO
    c._anuncio = ("192.168.0.77", 5000, "abc123", "", time.monotonic() - 60)
    c._talvez_trocar_de_ip()
    assert c.ip_atual == "10.9.9.9"
