"""Regras de avisos, travamentos progressivos e cronômetro (servidor)."""

BARULHO, SILENCIO = 90, 0
INTERVALO = 5 * 60 + 1  # um pouco mais que o cooldown padrão (5 min)


def dar_avisos(amb, n=3):
    for _ in range(n):
        amb.passo(INTERVALO, BARULHO)


def test_avisos_antes_de_travar(ambiente):
    dar_avisos(ambiente, 2)
    assert ambiente.ctrl.avisos == 2
    assert ambiente.ctrl.estado_cliente()["mensagem"] == "AVISO 2/3"
    dar_avisos(ambiente, 1)
    assert ambiente.ctrl.estado_cliente()["mensagem"] == "ÚLTIMO AVISO!"
    assert not ambiente.ctrl.travado
    assert ambiente.veyon.comandos == []


def test_intervalo_entre_avisos(ambiente):
    ambiente.passo(1, BARULHO)
    ambiente.passo(60, BARULHO)  # ainda dentro do intervalo
    assert ambiente.ctrl.avisos == 1


def test_travamentos_progressivos_e_destrave_automatico(ambiente):
    dar_avisos(ambiente)
    for duracao in (30, 60, 120, 120):
        ambiente.passo(INTERVALO, BARULHO)
        assert ambiente.ctrl.motivo_trava == "barulho"
        assert ambiente.ctrl.trava_ate - ambiente.relogio.agora == duracao
        ambiente.passo(duracao - 1, BARULHO)  # barulho durante a trava não estende
        assert ambiente.ctrl.travado
        ambiente.passo(1.1, SILENCIO)
        assert not ambiente.ctrl.travado
    assert ambiente.veyon.comandos == ["start", "stop"] * 4


def test_liberar_manual_mantem_progressao(ambiente):
    dar_avisos(ambiente)
    ambiente.passo(INTERVALO, BARULHO)
    ambiente.ctrl.liberar_manual()
    assert not ambiente.ctrl.travado
    assert ambiente.veyon.comandos[-1] == "stop"
    assert ambiente.ctrl.nivel_trava == 1  # a próxima trava será de 1 min


def test_ficha_limpa(ambiente):
    dar_avisos(ambiente)
    ambiente.passo(INTERVALO, BARULHO)
    ambiente.passo(31, SILENCIO)
    ambiente.passo(15 * 60 + 1, SILENCIO)
    assert ambiente.ctrl.avisos == 0
    assert ambiente.ctrl.nivel_trava == 0


def test_automacao_desativada_ignora_barulho(ambiente):
    ambiente.ctrl.definir_automacao(False)
    dar_avisos(ambiente, 5)
    assert ambiente.ctrl.avisos == 0
    assert ambiente.ctrl.estado_cliente()["mostrar"] is False


def test_cronometro_alerta_de_5_minutos(ambiente):
    ambiente.ctrl.iniciar_aula(45)
    ambiente.passo(40 * 60 - 1, SILENCIO)
    assert not ambiente.ctrl.estado_cliente()["alerta"]
    ambiente.passo(1, SILENCIO)
    estado = ambiente.ctrl.estado_cliente()
    assert estado["alerta"]
    assert estado["mensagem"] == "Faltam apenas 5 minutos para o fim da aula!"
    ambiente.passo(21, SILENCIO)
    assert not ambiente.ctrl.estado_cliente()["alerta"]


def test_aula_curta_nao_tem_alerta(ambiente):
    ambiente.ctrl.iniciar_aula(3)
    ambiente.passo(1, SILENCIO)
    assert not ambiente.ctrl.estado_cliente()["alerta"]


def test_fim_da_aula_trava_ate_liberar(ambiente):
    ambiente.ctrl.iniciar_aula(1)
    ambiente.passo(61, SILENCIO)
    cron = ambiente.ctrl.estado_cronometro()
    assert cron == {"ativo": False, "tempo_restante": 0, "encerrada": True}
    assert ambiente.ctrl.motivo_trava == "fim_aula"
    ambiente.passo(3600, BARULHO)  # não destrava sozinho e ignora barulho
    assert ambiente.ctrl.motivo_trava == "fim_aula"
    assert ambiente.ctrl.avisos == 0
    ambiente.ctrl.liberar_manual()
    assert not ambiente.ctrl.travado
    assert not ambiente.ctrl.estado_cronometro()["encerrada"]


def test_reiniciar_aula_libera_e_zera(ambiente):
    dar_avisos(ambiente)
    ambiente.passo(INTERVALO, BARULHO)
    ambiente.ctrl.reiniciar_aula(45)
    assert not ambiente.ctrl.travado
    assert ambiente.ctrl.avisos == 0 and ambiente.ctrl.nivel_trava == 0
    assert ambiente.ctrl.estado_cronometro()["tempo_restante"] == 45 * 60


def test_iniciar_aula_nao_sobrescreve(ambiente):
    assert ambiente.ctrl.iniciar_aula(45)
    assert not ambiente.ctrl.iniciar_aula(10)


def test_teste_de_trava(ambiente):
    assert ambiente.ctrl.testar_trava()
    assert not ambiente.ctrl.testar_trava()  # já está travado
    ambiente.passo(5.1, SILENCIO)
    assert not ambiente.ctrl.travado
