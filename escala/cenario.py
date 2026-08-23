"""Gera uma operação sintética, mas com a forma de uma operação real.

Nenhum dado de cliente entra aqui, e isso não é limitação: é requisito. O que
importa reproduzir é a **estrutura** que faz a escala travar na vida real, e
ela é pública:

- posto armado não aceita cobertura de porteiro, mas o contrário acontece;
- férias e afastamento não se distribuem de forma uniforme pelo mês;
- o efetivo é dimensionado no limite, porque folguista parado é custo visível
  e hora extra é custo que aparece só na folha do mês seguinte.

É essa terceira linha que produz o problema. Uma operação com folga de efetivo
não precisa de otimizador nenhum.
"""

from __future__ import annotations

import random

from .dominio import (
    Cenario,
    Colaborador,
    Posto,
    Qualificacao,
    Regime,
    Turno,
    teto_de_turnos,
)

# Valores-hora de referência, na ordem de grandeza da convenção coletiva de
# vigilância. Servem para a comparação ser em reais, não em pontos.
VALOR_HORA: dict[Qualificacao, float] = {
    Qualificacao.ARMADO: 18.50,
    Qualificacao.DESARMADO: 15.20,
    Qualificacao.PORTARIA: 12.80,
}

NOMES = [
    "Adriana", "Alex", "Aline", "Anderson", "Bruno", "Camila", "Carlos",
    "Cíntia", "Daniel", "Débora", "Eduardo", "Elaine", "Fábio", "Fernanda",
    "Gilberto", "Helena", "Igor", "Jaqueline", "João", "Juliana", "Kleber",
    "Larissa", "Lucas", "Márcia", "Marcos", "Nayara", "Otávio", "Patrícia",
    "Rafael", "Renata", "Ricardo", "Sandra", "Sérgio", "Tatiane", "Vagner",
    "Vanessa", "Wagner", "Yasmin",
]


def gerar(
    semente: int = 42,
    dias: int = 30,
    postos_24h_armados: int = 8,
    postos_24h_desarmados: int = 6,
    postos_portaria: int = 4,
    postos_admin: int = 5,
    folga_de_efetivo: float = 0.10,
    taxa_indisponibilidade: float = 0.09,
) -> Cenario:
    """Monta o cenário.

    `folga_de_efetivo` é o parâmetro que decide se o problema é interessante.
    Em 0,0 o efetivo é exatamente o mínimo teórico e qualquer falta descobre
    posto. Acima de 0,25 sobra gente e qualquer método serve. O padrão de 0,10
    é o que se vê em operação real: apertado, mas não impossível.
    """
    sorteio = random.Random(semente)

    postos: list[Posto] = []
    for i in range(postos_24h_armados):
        postos.append(Posto(f"PA{i:02d}", f"Portaria Blindada {i+1}",
                            Qualificacao.ARMADO, True))
    for i in range(postos_24h_desarmados):
        postos.append(Posto(f"PD{i:02d}", f"Ronda Interna {i+1}",
                            Qualificacao.DESARMADO, True))
    for i in range(postos_portaria):
        postos.append(Posto(f"PP{i:02d}", f"Recepção {i+1}",
                            Qualificacao.PORTARIA, True))
    for i in range(postos_admin):
        postos.append(Posto(f"AD{i:02d}", f"Central de Monitoramento {i+1}",
                            Qualificacao.PORTARIA, False))

    cenario_vazio = Cenario(dias=dias, postos=postos, colaboradores=[])
    demanda = cenario_vazio.demanda()

    # Efetivo mínimo teórico por qualificação: total de turnos exigidos que
    # aquela qualificação precisa cobrir, dividido pelos turnos que uma pessoa
    # entrega no mês dentro do regime.
    colaboradores: list[Colaborador] = []
    contador = 0

    for qualificacao in (Qualificacao.ARMADO, Qualificacao.DESARMADO, Qualificacao.PORTARIA):
        turnos_12x36 = sum(
            n for (_, turno, q), n in demanda.items()
            if q is qualificacao and turno.value != "admin"
        )
        turnos_admin = sum(
            n for (_, turno, q), n in demanda.items()
            if q is qualificacao and turno.value == "admin"
        )

        teto_12x36 = teto_de_turnos(Regime.DOZE_TRINTA_SEIS, dias)
        teto_admin = teto_de_turnos(Regime.QUARENTA_E_QUATRO, dias)
        minimo_12x36 = -(-turnos_12x36 // teto_12x36)
        minimo_admin = -(-turnos_admin // teto_admin)

        efetivo_12x36 = int(minimo_12x36 * (1 + folga_de_efetivo))
        efetivo_admin = int(minimo_admin * (1 + folga_de_efetivo))

        for regime, quantos in (
            (Regime.DOZE_TRINTA_SEIS, efetivo_12x36),
            (Regime.QUARENTA_E_QUATRO, efetivo_admin),
        ):
            for _ in range(quantos):
                contador += 1
                colaboradores.append(
                    Colaborador(
                        id=f"C{contador:03d}",
                        nome=f"{NOMES[contador % len(NOMES)]} {chr(65 + contador % 26)}.",
                        regime=regime,
                        qualificacao=qualificacao,
                        valor_hora=VALOR_HORA[qualificacao],
                        indisponivel=_sortear_ausencias(sorteio, dias, taxa_indisponibilidade),
                    )
                )

    return Cenario(dias=dias, postos=postos, colaboradores=colaboradores)


# Fração do efetivo que está de férias em qualquer mês dado. Com 12 meses de
# ciclo e 30 dias de férias, o valor de equilíbrio é 1/12 ≈ 8%.
FRACAO_EM_FERIAS = 1 / 12
DIAS_FERIAS_NO_MES = 15  # metade do período, o parcelamento mais comum


def _sortear_ausencias(
    sorteio: random.Random, dias: int, taxa: float
) -> frozenset[int]:
    """Ausência real não é um dia solto aqui e ali.

    Férias vêm em bloco de quinze dias; atestado vem em um a três dias
    seguidos. Sortear dia a dia produziria um problema mais fácil que o real —
    porque falta espalhada sempre acha quem cubra, e falta em bloco não.

    A primeira versão deste gerador sorteava blocos até atingir uma cota, e um
    único bloco de férias já estourava a cota inteira: o cenário saiu com 23%
    de ausência em vez dos 9% pedidos, e nenhuma escala seria viável. Separar
    férias de falta curta resolveu.
    """
    if sorteio.random() < FRACAO_EM_FERIAS:
        inicio = sorteio.randrange(max(1, dias - DIAS_FERIAS_NO_MES + 1))
        return frozenset(range(inicio, min(dias, inicio + DIAS_FERIAS_NO_MES)))

    # Quem não está de férias responde pelo restante da taxa, em faltas curtas.
    esperado = max(0.0, dias * taxa - FRACAO_EM_FERIAS * DIAS_FERIAS_NO_MES)
    ausentes: set[int] = set()
    while len(ausentes) < esperado:
        inicio = sorteio.randrange(dias)
        duracao = sorteio.choice([1, 1, 2, 3])
        ausentes.update(range(inicio, min(dias, inicio + duracao)))
    return frozenset(ausentes)


def _maximo_de_turnos(colaborador: Colaborador, dias: int) -> int:
    """Quantos turnos esta pessoa consegue entregar, no melhor dos casos.

    Não é o teto contratual: é o teto contratual **depois** de descontar as
    ausências e a alternância do art. 59-A. Percorrer os dias livres pegando um
    sim, um não dá o máximo exato — como os dias formam uma sequência, essa
    escolha simples já coincide com o maior conjunto de dias não vizinhos.
    """
    livres = [d for d in range(dias) if colaborador.disponivel_em(d)]
    teto = teto_de_turnos(colaborador.regime, dias)

    if colaborador.regime is Regime.QUARENTA_E_QUATRO:
        return min(len(livres), teto)

    cabem, ultimo = 0, -10
    for dia in livres:
        if dia - ultimo >= 2:
            cabem += 1
            ultimo = dia
    return min(cabem, teto)


def folga_legal(cenario: Cenario) -> dict[str, tuple[int, int, float]]:
    """A folga real de efetivo, por regime: (capacidade, demanda, folga).

    Este é o número que decide se o problema é difícil, e por isso ele é
    impresso junto com o cenário: **capacidade que a lei permite usar** contra
    demanda. O efetivo contratado engana, porque metade dele está em descanso
    obrigatório em qualquer dia dado, e uma parte está de férias.

    Ele estava no README antes de estar no código, e isso era um defeito: número
    publicado que o leitor não consegue reproduzir vale tanto quanto número
    inventado.
    """
    demanda = cenario.demanda()
    resultado: dict[str, tuple[int, int, float]] = {}

    for regime in Regime:
        pessoas = [c for c in cenario.colaboradores if c.regime is regime]
        capacidade = sum(_maximo_de_turnos(c, cenario.dias) for c in pessoas)
        if regime is Regime.DOZE_TRINTA_SEIS:
            exigido = sum(n for (_, t, _), n in demanda.items() if t is not Turno.ADMIN)
        else:
            exigido = sum(n for (_, t, _), n in demanda.items() if t is Turno.ADMIN)
        folga = (capacidade - exigido) / exigido if exigido else 0.0
        resultado[regime.value] = (capacidade, exigido, folga)

    return resultado


def resumo(cenario: Cenario) -> str:
    linhas = [
        f"Horizonte: {cenario.dias} dias",
        f"Postos: {len(cenario.postos)} "
        f"({sum(1 for p in cenario.postos if p.vinte_e_quatro_horas)} de 24h, "
        f"{sum(1 for p in cenario.postos if not p.vinte_e_quatro_horas)} administrativos)",
        f"Turnos a cobrir: {cenario.turnos_a_cobrir()}",
        f"Colaboradores: {len(cenario.colaboradores)}",
    ]
    for regime in Regime:
        quantos = sum(1 for c in cenario.colaboradores if c.regime is regime)
        capacidade = quantos * teto_de_turnos(regime, cenario.dias)
        linhas.append(f"  {regime.value}: {quantos} pessoas, {capacidade} turnos contratados")

    ausentes = sum(len(c.indisponivel) for c in cenario.colaboradores)
    total_dias = len(cenario.colaboradores) * cenario.dias
    linhas.append(f"Dias de ausência: {ausentes} de {total_dias} ({ausentes/total_dias:.1%})")

    linhas.append("Folga legal de efetivo (capacidade utilizável × demanda):")
    for regime, (capacidade, exigido, folga) in folga_legal(cenario).items():
        linhas.append(f"  {regime}: {capacidade} × {exigido} turnos = {folga:+.1%}")
    return "\n".join(linhas)
