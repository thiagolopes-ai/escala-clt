"""Testes da importação e exportação de planilha.

A tese aqui é uma só: **o que entra sai, e o que sai volta a entrar igual.**
Se a ida e volta perder informação, o gestor audita uma escala e recebe o
diagnóstico de outra — e não teria como saber.
"""

from __future__ import annotations

import pytest

from escala.cenario import gerar
from escala.clt import auditar
from escala.dominio import Qualificacao, Regime, Turno
from escala.manual import supervisor_apressado
from escala.planilha import PlanilhaInvalida, escrever, ler

MINIMA = """dia,turno,posto,posto_exige,colaborador,regime,qualificacao
1,diurno,PA01,armado,Carlos,12x36,armado
1,noturno,PA01,armado,Marcos,12x36,armado
3,diurno,PA01,armado,Carlos,12x36,armado
"""


def test_le_o_minimo_necessario():
    cenario, escala = ler(MINIMA)
    assert len(escala) == 3
    assert cenario.dias == 3
    assert len(cenario.postos) == 1
    assert cenario.postos[0].vinte_e_quatro_horas is True
    assert {c.id for c in cenario.colaboradores} == {"Carlos", "Marcos"}


def test_ida_e_volta_preserva_a_auditoria():
    """O teste que sustenta a ferramenta inteira."""
    cenario = gerar(semente=3, dias=14, postos_24h_armados=2,
                    postos_24h_desarmados=1, postos_portaria=1, postos_admin=1)
    escala = supervisor_apressado(cenario)
    antes = auditar(escala, cenario)

    cenario2, escala2 = ler(escrever(escala, cenario))
    depois = auditar(escala2, cenario2)

    assert len(escala2) == len(escala)
    assert len(depois.infracoes) == len(antes.infracoes)
    assert depois.por_artigo() == antes.por_artigo()
    assert depois.custo.folha == pytest.approx(antes.custo.folha, rel=1e-9)
    assert depois.custo.turnos_descobertos == antes.custo.turnos_descobertos


def test_data_real_revela_o_dia_da_semana():
    """Com data, o repouso semanal passa a ser conferível de verdade."""
    texto = ("dia,turno,posto,posto_exige,colaborador,regime,qualificacao\n"
             "2026-08-03,diurno,PA01,armado,Carlos,12x36,armado\n")
    cenario, _ = ler(texto)
    assert cenario.primeiro_dia_semana == 0  # 3 de agosto de 2026 é segunda


def test_aceita_data_no_formato_brasileiro():
    texto = ("dia,turno,posto,posto_exige,colaborador,regime,qualificacao\n"
             "03/08/2026,diurno,PA01,armado,Carlos,12x36,armado\n")
    cenario, _ = ler(texto)
    assert cenario.dias == 1


def test_colaborador_vazio_e_turno_descoberto_e_nao_erro():
    """Escala real tem buraco. Esconder o buraco na importação esconderia
    justamente o que precisa ser medido."""
    texto = ("dia,turno,posto,posto_exige,colaborador,regime,qualificacao\n"
             "1,diurno,PA01,armado,Carlos,12x36,armado\n"
             "1,noturno,PA01,armado,,,\n")
    cenario, escala = ler(texto)
    assert len(escala) == 1
    assert auditar(escala, cenario).custo.turnos_descobertos == 1


def test_dupla_alocacao_no_mesmo_dia_nao_se_sobrescreve():
    """Duas linhas para a mesma pessoa no mesmo dia precisam sobreviver à
    importação — se uma apagasse a outra, a infração sumiria em silêncio."""
    texto = ("dia,turno,posto,posto_exige,colaborador,regime,qualificacao\n"
             "1,diurno,PA01,armado,Carlos,12x36,armado\n"
             "1,diurno,PA02,armado,Carlos,12x36,armado\n")
    _, escala = ler(texto)
    assert len(escala) == 2


def test_apelidos_de_coluna_sao_aceitos():
    """Planilha de operação não usa o vocabulário do código."""
    texto = ("dia,turno,posto,posto_exige,colaborador,regime,qualificacao\n"
             "1,noite,Recepção 3,portaria,Ana,12/36,recepcao\n")
    cenario, escala = ler(texto)
    assert list(escala.values())[0].turno is Turno.NOTURNO
    assert cenario.postos[0].qualificacao is Qualificacao.PORTARIA
    assert cenario.colaboradores[0].regime is Regime.DOZE_TRINTA_SEIS


def test_coluna_extra_e_ignorada_em_silencio():
    texto = ("dia,turno,posto,posto_exige,colaborador,regime,qualificacao,centro_de_custo\n"
             "1,diurno,PA01,armado,Carlos,12x36,armado,CC-4471\n")
    _, escala = ler(texto)
    assert len(escala) == 1


def test_valor_hora_da_planilha_prevalece():
    texto = ("dia,turno,posto,posto_exige,colaborador,regime,qualificacao,valor_hora\n"
             "1,diurno,PA01,armado,Carlos,12x36,armado,\"27,90\"\n")
    cenario, _ = ler(texto)
    assert cenario.colaboradores[0].valor_hora == pytest.approx(27.90)


# ------------------------------------------------------------------- erros

@pytest.mark.parametrize("texto,trecho", [
    ("", "vazio"),
    ("dia,turno\n1,diurno\n", "faltam colunas"),
    ("dia,turno,posto,colaborador\n", "nenhuma linha"),
    ("dia,turno,posto,colaborador\nabc,diurno,P1,X\n", "não é número nem data"),
    ("dia,turno,posto,colaborador\n1,madrugada,P1,X\n", "não reconhecido"),
])
def test_erro_de_formato_fala_com_quem_montou_a_planilha(texto, trecho):
    """Mensagem de erro que só faz sentido para quem escreveu o código faz o
    gestor desistir da ferramenta na primeira tentativa."""
    with pytest.raises(PlanilhaInvalida, match=trecho):
        ler(texto)


# ------------------------------------------------------- recorte x mês fechado

RECORTE = """dia,turno,posto,posto_exige,colaborador,regime,qualificacao
1,diurno,PA01,armado,Carlos,12x36,armado
3,diurno,PA01,armado,Carlos,12x36,armado
5,diurno,PA01,armado,Carlos,12x36,armado
"""


def test_recorte_nao_e_acusado_de_estourar_teto_mensal():
    """Três turnos em cinco dias, alternando direito, é escala legal.

    A versão anterior acusava art. 59 aqui, porque o teto mensal era
    proporcionalizado para cinco dias. Mostrar resultado errado com ressalva é
    pior que não mostrar: quem lê guarda o número e esquece a ressalva.
    """
    cenario, escala = ler(RECORTE)
    auditoria = auditar(escala, cenario)
    assert auditoria.regras_mensais_avaliadas is False
    assert not any(i.artigo == "art. 59" for i in auditoria.infracoes)


def test_regra_diaria_continua_valendo_em_recorte():
    """O descanso de 36h não depende do fechamento do mês."""
    texto = ("dia,turno,posto,posto_exige,colaborador,regime,qualificacao\n"
             "1,diurno,PA01,armado,Carlos,12x36,armado\n"
             "2,diurno,PA01,armado,Carlos,12x36,armado\n")
    cenario, escala = ler(texto)
    auditoria = auditar(escala, cenario)
    assert auditoria.regras_mensais_avaliadas is False
    assert any(i.artigo == "art. 59-A" for i in auditoria.infracoes)


def test_a_avaliacao_mensal_pode_ser_forcada():
    """Quem sabe que o recorte representa o mês inteiro consegue pedir."""
    cenario, escala = ler(RECORTE)
    assert auditar(escala, cenario, mes_fechado=True).infracoes
    assert not auditar(escala, cenario, mes_fechado=False).infracoes


def test_mes_inteiro_avalia_as_regras_mensais():
    cenario = gerar(semente=3, dias=30, postos_24h_armados=1,
                    postos_24h_desarmados=0, postos_portaria=0, postos_admin=0)
    auditoria = auditar(supervisor_apressado(cenario), cenario)
    assert auditoria.regras_mensais_avaliadas is True


def test_erro_aponta_a_linha():
    texto = ("dia,turno,posto,colaborador\n"
             "1,diurno,P1,X\n"
             "2,madrugada,P1,X\n")
    with pytest.raises(PlanilhaInvalida, match="linha 3"):
        ler(texto)
