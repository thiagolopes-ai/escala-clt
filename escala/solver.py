"""Monta a escala por programação por restrições, com a CLT como restrição dura.

A diferença de método em relação à planilha não é "usar computador". É esta: o
supervisor decide um turno de cada vez e nunca volta atrás numa decisão
anterior. O solver considera as 1.190 decisões ao mesmo tempo e refaz quantas
precisar para achar o conjunto que fecha. Num problema onde a folga de efetivo
é de 1,8%, essa diferença é a diferença entre cobrir tudo e não cobrir.

Modelagem, em uma frase: uma variável booleana por (pessoa, dia, turno)
possível; as regras da CLT viram restrições que o solver não pode violar; o
custo em reais vira a função a minimizar.

**A cobertura entre qualificações usa uma propriedade que a operação já tem.**
Vigilante armado cobre posto desarmado e portaria; desarmado cobre portaria;
porteiro cobre só portaria. As classes são encaixadas uma dentro da outra, e
para famílias encaixadas basta exigir que cada prefixo do encaixe tenha gente
suficiente — é a condição de Hall. Sem isso, seria preciso uma variável por
(pessoa, dia, turno, classe), e o modelo triplicaria de tamanho para responder
exatamente a mesma coisa.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ortools.sat.python import cp_model

from .dominio import (
    ADICIONAL_NOTURNO,
    Alocacao,
    Cenario,
    Escala,
    FATOR_HORA_NOTURNA,
    HORAS_RELOGIO_NOTURNAS,
    HORAS_TURNO,
    MAX_DIAS_SEGUIDOS_SEM_FOLGA,
    Qualificacao,
    Regime,
    Turno,
    teto_de_turnos,
    pode_cobrir,
)

# Da mais restritiva para a menos. A ordem é o que torna a condição de Hall
# aplicável: quem cobre a classe i cobre todas as classes seguintes.
ORDEM_QUALIFICACAO = (Qualificacao.ARMADO, Qualificacao.DESARMADO, Qualificacao.PORTARIA)


@dataclass
class Resultado:
    escala: Escala
    status: str
    segundos: float
    limite_inferior: float
    valor_objetivo: float

    @property
    def otimo(self) -> bool:
        return self.status == "OPTIMAL"


def _centavos(valor: float) -> int:
    """CP-SAT trabalha com inteiros. Reais viram centavos, sem perda."""
    return int(round(valor * 100))


def _custo_do_turno(colaborador, turno: Turno) -> int:
    """Quanto custa colocar esta pessoa neste turno, em centavos.

    Inclui o adicional noturno com a hora reduzida do art. 73, § 1º — é ele que
    torna o turno noturno mais caro que o diurno e faz o solver distribuir as
    noites em vez de concentrá-las nas mesmas pessoas.
    """
    horas = HORAS_TURNO[turno]
    base = horas * colaborador.valor_hora
    noturnas = HORAS_RELOGIO_NOTURNAS[turno] * FATOR_HORA_NOTURNA
    adicional = noturnas * colaborador.valor_hora * ADICIONAL_NOTURNO
    return _centavos(base + adicional)


def resolver(
    cenario: Cenario,
    segundos: float = 60.0,
    trabalhadores: int = 2,
    registrar: bool = False,
) -> Resultado:
    modelo = cp_model.CpModel()
    demanda = cenario.demanda()
    postos_por_classe = {
        q: [p for p in cenario.postos if p.qualificacao is q] for q in ORDEM_QUALIFICACAO
    }
    multa = {
        q: (postos_por_classe[q][0].multa_descoberto if postos_por_classe[q] else 900.0)
        for q in ORDEM_QUALIFICACAO
    }

    # ---------------------------------------------------------------- variáveis
    x: dict[tuple[str, int, Turno], cp_model.IntVar] = {}
    for colaborador in cenario.colaboradores:
        for dia in range(cenario.dias):
            if not colaborador.disponivel_em(dia):
                continue  # art. 134: férias e afastamento não entram no modelo
            for turno in colaborador.turnos_permitidos():
                if (dia, turno, Qualificacao.PORTARIA) not in demanda and \
                   (dia, turno, Qualificacao.DESARMADO) not in demanda and \
                   (dia, turno, Qualificacao.ARMADO) not in demanda:
                    continue  # não há vaga desse turno nesse dia
                x[(colaborador.id, dia, turno)] = modelo.NewBoolVar(
                    f"x_{colaborador.id}_{dia}_{turno.value}"
                )

    descoberto: dict[tuple[int, Turno, Qualificacao], cp_model.IntVar] = {}
    for (dia, turno, qualificacao), quantos in demanda.items():
        descoberto[(dia, turno, qualificacao)] = modelo.NewIntVar(
            0, quantos, f"desc_{dia}_{turno.value}_{qualificacao.value}"
        )

    # -------------------------------------------------------------- restrições

    # Ninguém em dois turnos no mesmo dia.
    for colaborador in cenario.colaboradores:
        for dia in range(cenario.dias):
            do_dia = [
                x[(colaborador.id, dia, t)]
                for t in colaborador.turnos_permitidos()
                if (colaborador.id, dia, t) in x
            ]
            if len(do_dia) > 1:
                modelo.AddAtMostOne(do_dia)

    # Art. 59-A: 12h de trabalho por 36h ininterruptas de descanso.
    # Quem trabalha no dia D não trabalha em D+1.
    for colaborador in cenario.colaboradores:
        if colaborador.regime is not Regime.DOZE_TRINTA_SEIS:
            continue
        for dia in range(cenario.dias - 1):
            hoje = [x[(colaborador.id, dia, t)] for t in Turno
                    if (colaborador.id, dia, t) in x]
            amanha = [x[(colaborador.id, dia + 1, t)] for t in Turno
                      if (colaborador.id, dia + 1, t) in x]
            if hoje and amanha:
                modelo.AddAtMostOne(hoje + amanha)

    # Art. 67: repouso semanal remunerado.
    # Em 12x36 é consequência da regra acima; aqui vale para o regime 44h.
    janela = MAX_DIAS_SEGUIDOS_SEM_FOLGA + 1
    for colaborador in cenario.colaboradores:
        if colaborador.regime is Regime.DOZE_TRINTA_SEIS:
            continue
        for inicio in range(cenario.dias - janela + 1):
            na_janela = [
                x[(colaborador.id, d, t)]
                for d in range(inicio, inicio + janela)
                for t in colaborador.turnos_permitidos()
                if (colaborador.id, d, t) in x
            ]
            if len(na_janela) >= janela:
                modelo.Add(sum(na_janela) <= MAX_DIAS_SEGUIDOS_SEM_FOLGA)

    # Art. 59 combinado com o regime: teto de turnos no mês.
    for colaborador in cenario.colaboradores:
        do_mes = [
            x[(colaborador.id, d, t)]
            for d in range(cenario.dias)
            for t in colaborador.turnos_permitidos()
            if (colaborador.id, d, t) in x
        ]
        if do_mes:
            modelo.Add(sum(do_mes) <= teto_de_turnos(colaborador.regime, cenario.dias))

    # Cobertura com substituição entre classes (condição de Hall).
    for dia in range(cenario.dias):
        for turno in Turno:
            exigencias = {
                q: demanda.get((dia, turno, q), 0) for q in ORDEM_QUALIFICACAO
            }
            if not any(exigencias.values()):
                continue

            acumulado_gente: list[cp_model.IntVar] = []
            acumulado_exigido = 0
            acumulado_descoberto: list[cp_model.IntVar] = []

            for classe in ORDEM_QUALIFICACAO:
                acumulado_gente += [
                    x[(c.id, dia, turno)]
                    for c in cenario.colaboradores
                    if (c.id, dia, turno) in x and pode_cobrir(c.qualificacao, classe)
                    and c.qualificacao is classe
                ]
                acumulado_exigido += exigencias[classe]
                if (dia, turno, classe) in descoberto:
                    acumulado_descoberto.append(descoberto[(dia, turno, classe)])

                if acumulado_exigido:
                    # Cada prefixo do encaixe precisa de gente suficiente.
                    modelo.Add(
                        sum(acumulado_gente)
                        >= acumulado_exigido - sum(acumulado_descoberto)
                    )

            # E ninguém trabalha sem posto: o total bate exatamente.
            modelo.Add(
                sum(acumulado_gente)
                == acumulado_exigido - sum(acumulado_descoberto)
            )

    # -------------------------------------------------------------- objetivo
    pessoas = {c.id: c for c in cenario.colaboradores}
    termos = []
    for (id_pessoa, dia, turno), variavel in x.items():
        termos.append(_custo_do_turno(pessoas[id_pessoa], turno) * variavel)
    for (dia, turno, classe), variavel in descoberto.items():
        termos.append(_centavos(multa[classe]) * variavel)
    modelo.Minimize(sum(termos))

    # ---------------------------------------------------------------- resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = segundos
    solver.parameters.num_workers = trabalhadores
    solver.parameters.log_search_progress = registrar

    inicio = time.perf_counter()
    status = solver.Solve(modelo)
    decorrido = time.perf_counter() - inicio

    escala: Escala = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        escala = _materializar(solver, x, cenario)

    return Resultado(
        escala=escala,
        status=solver.StatusName(status),
        segundos=decorrido,
        limite_inferior=solver.BestObjectiveBound() / 100.0,
        valor_objetivo=solver.ObjectiveValue() / 100.0 if escala else float("nan"),
    )


@dataclass
class Dimensionamento:
    contratacoes: int
    descobertos: int
    custo_operacional: float   # folha + multa contratual
    custo_contratacao: float   # salário das contratações no mês
    total: float
    status: str


def onde_falta(escala: Escala, cenario: Cenario) -> dict[tuple[Turno, Qualificacao], int]:
    """Quais turnos ficaram descobertos, separados por tipo.

    É a saída que muda a conversa de orçamento. "Faltam 19 turnos" leva a
    contratar mais do mesmo. "Faltam 11 administrativos e 8 noturnos armados"
    leva a contratar a pessoa certa — e mostra que contratar a errada não
    resolve nada, por mais gente que se contrate.
    """
    preenchidas = {(a.posto, dia, a.turno) for (_p, dia), a in escala.items()}
    faltando: dict[tuple[Turno, Qualificacao], int] = {}
    for vaga in cenario.vagas():
        if (vaga.posto.id, vaga.dia, vaga.turno) not in preenchidas:
            chave = (vaga.turno, vaga.posto.qualificacao)
            faltando[chave] = faltando.get(chave, 0) + 1
    return dict(sorted(faltando.items(), key=lambda kv: -kv[1]))


def dimensionar(
    cenario: Cenario,
    qualificacao: Qualificacao = Qualificacao.ARMADO,
    regime: Regime = Regime.DOZE_TRINTA_SEIS,
    ate: int = 6,
    segundos_por_rodada: float = 30.0,
) -> list[Dimensionamento]:
    """Responde a pergunta que precede a escala: contratar compensa?

    O solver já prova, ao terminar com status ótimo, quantos turnos são
    impossíveis de cobrir com o efetivo atual. Essa informação sozinha vale
    pouco para quem decide orçamento — o que ele precisa saber é se o salário
    de mais uma pessoa sai mais barato que a multa que ela evita.

    A varredura responde exatamente isso, e responde **por tipo de contratação**.
    Contratar na qualificação errada é o erro caro: o custo entra na folha
    todo mês e a cobertura não sobe um turno sequer, porque quem falta não é
    quem se contratou.
    """
    from .cenario import VALOR_HORA
    from .clt import auditar
    from .dominio import Colaborador

    valor_hora = VALOR_HORA[qualificacao]
    turno_referencia = (
        Turno.DIURNO if regime is Regime.DOZE_TRINTA_SEIS else Turno.ADMIN
    )
    salario_mensal = (
        teto_de_turnos(regime, cenario.dias)
        * HORAS_TURNO[turno_referencia]
        * valor_hora
    )

    linhas: list[Dimensionamento] = []
    for quantos in range(ate + 1):
        reforco = [
            Colaborador(
                id=f"R{i:02d}",
                nome=f"Reserva {i + 1}",
                regime=regime,
                qualificacao=qualificacao,
                valor_hora=valor_hora,
            )
            for i in range(quantos)
        ]
        ampliado = Cenario(
            dias=cenario.dias,
            postos=cenario.postos,
            colaboradores=list(cenario.colaboradores) + reforco,
            primeiro_dia_semana=cenario.primeiro_dia_semana,
        )
        resultado = resolver(ampliado, segundos=segundos_por_rodada)
        auditoria = auditar(resultado.escala, ampliado)
        custo_contratacao = quantos * salario_mensal

        linhas.append(Dimensionamento(
            contratacoes=quantos,
            descobertos=auditoria.custo.turnos_descobertos,
            custo_operacional=auditoria.custo.total,
            custo_contratacao=custo_contratacao,
            total=auditoria.custo.total + custo_contratacao,
            status=resultado.status,
        ))
        if auditoria.custo.turnos_descobertos == 0:
            break
    return linhas


def _materializar(solver, x, cenario: Cenario) -> Escala:
    """Traduz a solução em postos concretos.

    O modelo raciocina por classe de qualificação, porque postos da mesma
    classe são intercambiáveis. Aqui a escolha vira endereço: cada pessoa
    escalada recebe um posto específico daquele turno, começando pelos postos
    mais exigentes para que os habilitados não sejam gastos em portaria.
    """
    escolhidos: dict[tuple[int, Turno], list[str]] = {}
    for (id_pessoa, dia, turno), variavel in x.items():
        if solver.Value(variavel):
            escolhidos.setdefault((dia, turno), []).append(id_pessoa)

    pessoas = {c.id: c for c in cenario.colaboradores}
    vagas_por_chave: dict[tuple[int, Turno], list] = {}
    for vaga in cenario.vagas():
        vagas_por_chave.setdefault((vaga.dia, vaga.turno), []).append(vaga)

    escala: Escala = {}
    for chave, ids in escolhidos.items():
        vagas = sorted(
            vagas_por_chave.get(chave, []),
            key=lambda v: ORDEM_QUALIFICACAO.index(v.posto.qualificacao),
        )
        candidatos = sorted(
            ids, key=lambda i: ORDEM_QUALIFICACAO.index(pessoas[i].qualificacao)
        )
        for vaga in vagas:
            for indice, id_pessoa in enumerate(candidatos):
                if pode_cobrir(pessoas[id_pessoa].qualificacao, vaga.posto.qualificacao):
                    escala[(id_pessoa, vaga.dia)] = Alocacao(
                        turno=vaga.turno, posto=vaga.posto.id
                    )
                    candidatos.pop(indice)
                    break
    return escala
