"""Testes das teses do projeto.

Cada teste corresponde a uma afirmação do README. Se o README diz que a escala
gerada não viola a CLT, existe um teste que gera a escala e roda o auditor
inteiro em cima dela. Se diz que a linha de base é honesta, existe um teste que
confere que ela de fato produz infrações — linha de base que passa no auditor
não serviria de comparação.

O cenário usado aqui é menor que o do README de propósito: a integração
contínua precisa terminar em segundos, e a tese não depende do tamanho.
"""

from __future__ import annotations

import pytest

from escala.cenario import gerar
from escala.clt import auditar, calcular_custo
from escala.dominio import (
    ADICIONAL_NOTURNO,
    Alocacao,
    Cenario,
    Colaborador,
    FATOR_HORA_NOTURNA,
    Posto,
    Qualificacao,
    Regime,
    Turno,
    pode_cobrir,
)
from escala.manual import supervisor_apressado, supervisor_que_confere
from escala.solver import dimensionar, onde_falta, resolver


@pytest.fixture(scope="module")
def pequeno() -> Cenario:
    return gerar(
        semente=3,
        dias=14,
        postos_24h_armados=3,
        postos_24h_desarmados=2,
        postos_portaria=1,
        postos_admin=2,
    )


@pytest.fixture(scope="module")
def resolvido(pequeno: Cenario):
    return resolver(pequeno, segundos=30)


# ------------------------------------------------------------------- domínio

def test_qualificacao_cobre_para_baixo_e_nao_para_cima():
    """Armado cobre portaria; porteiro não cobre posto armado."""
    assert pode_cobrir(Qualificacao.ARMADO, Qualificacao.PORTARIA)
    assert pode_cobrir(Qualificacao.DESARMADO, Qualificacao.PORTARIA)
    assert not pode_cobrir(Qualificacao.PORTARIA, Qualificacao.ARMADO)
    assert not pode_cobrir(Qualificacao.DESARMADO, Qualificacao.ARMADO)


def test_regime_44h_nao_recebe_turno_de_doze_horas():
    """Jornada de 8h48 num turno de 12h estoura o interjornada do dia seguinte."""
    admin = Colaborador("C1", "Fulano", Regime.QUARENTA_E_QUATRO,
                        Qualificacao.PORTARIA, 12.8)
    assert admin.turnos_permitidos() == (Turno.ADMIN,)
    assert Turno.NOTURNO not in admin.turnos_permitidos()


def test_posto_administrativo_nao_abre_no_fim_de_semana(pequeno: Cenario):
    admin = [p for p in pequeno.postos if not p.vinte_e_quatro_horas]
    assert admin, "o cenário precisa ter posto administrativo"
    vagas_fds = [
        v for v in pequeno.vagas()
        if not v.posto.vinte_e_quatro_horas and pequeno.e_fim_de_semana(v.dia)
    ]
    assert vagas_fds == []


def test_cenario_e_deterministico():
    """Número que muda a cada execução não é número."""
    a, b = gerar(semente=5, dias=10), gerar(semente=5, dias=10)
    assert [c.id for c in a.colaboradores] == [c.id for c in b.colaboradores]
    assert [sorted(c.indisponivel) for c in a.colaboradores] == \
           [sorted(c.indisponivel) for c in b.colaboradores]


# ------------------------------------------------------------------ auditoria

def test_auditor_acusa_dois_dias_seguidos_no_12x36():
    """Art. 59-A é a regra que a escala manual mais quebra."""
    posto = Posto("P1", "Portaria", Qualificacao.ARMADO, True)
    pessoa = Colaborador("C1", "Fulano", Regime.DOZE_TRINTA_SEIS,
                         Qualificacao.ARMADO, 18.5)
    cenario = Cenario(dias=3, postos=[posto], colaboradores=[pessoa])
    escala = {
        ("C1", 0): Alocacao(Turno.DIURNO, "P1"),
        ("C1", 1): Alocacao(Turno.DIURNO, "P1"),
    }
    auditoria = auditar(escala, cenario)
    assert any(i.artigo == "art. 59-A" for i in auditoria.infracoes)


def test_auditor_acusa_trabalho_durante_ferias():
    posto = Posto("P1", "Portaria", Qualificacao.ARMADO, True)
    pessoa = Colaborador("C1", "Fulano", Regime.DOZE_TRINTA_SEIS,
                         Qualificacao.ARMADO, 18.5, indisponivel=frozenset({0}))
    cenario = Cenario(dias=2, postos=[posto], colaboradores=[pessoa])
    escala = {("C1", 0): Alocacao(Turno.DIURNO, "P1")}
    assert any(i.artigo == "art. 134" for i in auditar(escala, cenario).infracoes)


def test_auditor_acusa_porteiro_em_posto_armado():
    posto = Posto("P1", "Blindada", Qualificacao.ARMADO, True)
    pessoa = Colaborador("C1", "Fulano", Regime.DOZE_TRINTA_SEIS,
                         Qualificacao.PORTARIA, 12.8)
    cenario = Cenario(dias=1, postos=[posto], colaboradores=[pessoa])
    escala = {("C1", 0): Alocacao(Turno.DIURNO, "P1")}
    assert any(i.artigo == "Lei 7.102/83" for i in auditar(escala, cenario).infracoes)


def test_posto_vazio_e_multa_e_nao_infracao():
    """Regressão: posto descoberto era contado como infração de habilitação,
    e uma escala conforme aparecia com 23 violações inexistentes."""
    posto = Posto("P1", "Blindada", Qualificacao.ARMADO, True, multa_descoberto=900.0)
    pessoa = Colaborador("C1", "Fulano", Regime.DOZE_TRINTA_SEIS,
                         Qualificacao.ARMADO, 18.5)
    cenario = Cenario(dias=1, postos=[posto], colaboradores=[pessoa])
    auditoria = auditar({}, cenario)  # ninguém escalado
    assert auditoria.infracoes == []
    assert auditoria.custo.turnos_descobertos == 2  # diurno e noturno
    assert auditoria.custo.valor_multa_descoberto == pytest.approx(1800.0)


def test_adicional_noturno_usa_a_hora_reduzida():
    """Art. 73, § 1º: 7 horas de relógio entre 22h e 5h valem 8 de remuneração.

    É a diferença de 14% que some em toda planilha que multiplica hora por
    valor sem olhar o relógio.
    """
    posto = Posto("P1", "Blindada", Qualificacao.ARMADO, True)
    pessoa = Colaborador("C1", "Fulano", Regime.DOZE_TRINTA_SEIS,
                         Qualificacao.ARMADO, 10.0)
    cenario = Cenario(dias=1, postos=[posto], colaboradores=[pessoa])
    custo = calcular_custo({("C1", 0): Alocacao(Turno.NOTURNO, "P1")}, cenario)

    esperado = 7.0 * FATOR_HORA_NOTURNA * 10.0 * ADICIONAL_NOTURNO
    assert custo.valor_adicional_noturno == pytest.approx(esperado)
    assert custo.horas_noturnas_remuneradas == pytest.approx(8.0)


def test_turno_diurno_nao_gera_adicional_noturno():
    posto = Posto("P1", "Blindada", Qualificacao.ARMADO, True)
    pessoa = Colaborador("C1", "Fulano", Regime.DOZE_TRINTA_SEIS,
                         Qualificacao.ARMADO, 10.0)
    cenario = Cenario(dias=1, postos=[posto], colaboradores=[pessoa])
    custo = calcular_custo({("C1", 0): Alocacao(Turno.DIURNO, "P1")}, cenario)
    assert custo.valor_adicional_noturno == 0.0


# --------------------------------------------------------------- linhas de base

def test_linha_de_base_apressada_realmente_viola(pequeno: Cenario):
    """Linha de base que passa no auditor não serviria de comparação.

    Se este teste falhar, o número do README perde o sentido: significaria que
    o método manual já era conforme e o solver não resolve problema nenhum.
    """
    auditoria = auditar(supervisor_apressado(pequeno), pequeno)
    assert len(auditoria.infracoes) > 0
    assert any(i.artigo == "art. 59-A" for i in auditoria.infracoes)


def test_linha_de_base_conferida_e_conforme(pequeno: Cenario):
    """O supervisor cuidadoso não quebra a lei — ele deixa posto descoberto."""
    auditoria = auditar(supervisor_que_confere(pequeno), pequeno)
    assert auditoria.infracoes == []
    assert auditoria.custo.turnos_descobertos > 0


def test_as_duas_linhas_de_base_representam_escolhas_opostas(pequeno: Cenario):
    apressado = auditar(supervisor_apressado(pequeno), pequeno)
    confere = auditar(supervisor_que_confere(pequeno), pequeno)
    assert apressado.cobertura > confere.cobertura      # cobre mais
    assert len(apressado.infracoes) > len(confere.infracoes)  # e infringe mais


# ---------------------------------------------------------------------- solver

def test_solver_encontra_o_otimo_provado(resolvido):
    """Status ótimo não é 'a melhor que achei': é prova de que não existe melhor."""
    assert resolvido.status == "OPTIMAL"
    assert resolvido.valor_objetivo == pytest.approx(resolvido.limite_inferior, rel=1e-6)


def test_escala_gerada_nao_viola_a_clt(pequeno: Cenario, resolvido):
    """A tese central do projeto, conferida pelo auditor inteiro."""
    auditoria = auditar(resolvido.escala, pequeno)
    assert auditoria.infracoes == [], "\n".join(str(i) for i in auditoria.infracoes[:5])


def test_ninguem_trabalha_dois_dias_seguidos_no_12x36(pequeno: Cenario, resolvido):
    pessoas = {c.id: c for c in pequeno.colaboradores}
    dias_por_pessoa: dict[str, set[int]] = {}
    for (id_pessoa, dia) in resolvido.escala:
        dias_por_pessoa.setdefault(id_pessoa, set()).add(dia)

    for id_pessoa, dias in dias_por_pessoa.items():
        if pessoas[id_pessoa].regime is not Regime.DOZE_TRINTA_SEIS:
            continue
        seguidos = [d for d in dias if d + 1 in dias]
        assert seguidos == [], f"{id_pessoa} trabalhou em {seguidos} e no dia seguinte"


def test_ninguem_e_escalado_em_dia_de_ausencia(pequeno: Cenario, resolvido):
    pessoas = {c.id: c for c in pequeno.colaboradores}
    for (id_pessoa, dia) in resolvido.escala:
        assert pessoas[id_pessoa].disponivel_em(dia)


def test_solver_custa_menos_que_a_escala_conforme(pequeno: Cenario, resolvido):
    """O número que abre o README, na versão pequena."""
    confere = auditar(supervisor_que_confere(pequeno), pequeno)
    otimizada = auditar(resolvido.escala, pequeno)
    assert otimizada.custo.total < confere.custo.total


def test_solver_cobre_mais_que_a_escala_conforme(pequeno: Cenario, resolvido):
    confere = auditar(supervisor_que_confere(pequeno), pequeno)
    otimizada = auditar(resolvido.escala, pequeno)
    assert otimizada.cobertura >= confere.cobertura


def test_solver_respeita_o_teto_de_turnos_do_regime(pequeno: Cenario, resolvido):
    from escala.dominio import teto_de_turnos

    pessoas = {c.id: c for c in pequeno.colaboradores}
    contagem: dict[str, int] = {}
    for (id_pessoa, _dia) in resolvido.escala:
        contagem[id_pessoa] = contagem.get(id_pessoa, 0) + 1
    for id_pessoa, quantos in contagem.items():
        assert quantos <= teto_de_turnos(pessoas[id_pessoa].regime, pequeno.dias)


def test_onde_falta_separa_por_turno_e_qualificacao(pequeno: Cenario, resolvido):
    """'Faltam 19 turnos' leva a contratar errado. O diagnóstico precisa dizer
    qual turno e qual qualificação."""
    faltando = onde_falta(resolvido.escala, pequeno)
    for chave in faltando:
        turno, qualificacao = chave
        assert isinstance(turno, Turno)
        assert isinstance(qualificacao, Qualificacao)


def test_contratar_na_classe_errada_nao_reduz_o_descoberto():
    """A descoberta que o projeto entrega: mais gente não é mais cobertura.

    Contratar vigilante armado não cobre turno administrativo, porque o regime
    44h é outro. O custo entra na folha e a cobertura fica onde estava.
    """
    cenario = gerar(
        semente=3, dias=14,
        postos_24h_armados=2, postos_24h_desarmados=1,
        postos_portaria=1, postos_admin=3,
    )
    linhas = dimensionar(
        cenario, Qualificacao.ARMADO, Regime.DOZE_TRINTA_SEIS,
        ate=2, segundos_por_rodada=15,
    )
    assert linhas[0].descobertos > 0
    # Contratar armado nunca aumenta o descoberto, e o custo total sempre sobe
    # quando a contratação não resolve o gargalo.
    assert linhas[-1].descobertos <= linhas[0].descobertos
    assert linhas[-1].custo_contratacao > 0
