"""O vocabulário da operação e as constantes que vêm da lei.

Este módulo não decide nada. Ele só nomeia — e nomear direito é metade do
projeto, porque escala de posto tem uma estrutura que planilha nenhuma
consegue representar: a pessoa não é alocada a um dia, é alocada a um ciclo.

As constantes com número de artigo ao lado não são comentário decorativo. Elas
são a razão de cada restrição existir, e é por elas que um advogado consegue
auditar este código sem saber Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# --------------------------------------------------------------------- turnos


class Turno(str, Enum):
    """Os três turnos que existem numa operação de segurança patrimonial."""

    DIURNO = "diurno"      # 07h às 19h — posto 24h, regime 12x36
    NOTURNO = "noturno"    # 19h às 07h — posto 24h, regime 12x36
    ADMIN = "admin"        # 08h às 17h48 — posto administrativo, 44h semanais


HORAS_TURNO: dict[Turno, float] = {
    Turno.DIURNO: 12.0,
    Turno.NOTURNO: 12.0,
    Turno.ADMIN: 8.8,      # 44h / 5 dias
}

# Art. 73, § 2º: horário noturno é o das 22h às 5h. O turno noturno de 19h às
# 07h cobre 7 horas de relógio dentro dessa janela.
HORAS_RELOGIO_NOTURNAS: dict[Turno, float] = {
    Turno.DIURNO: 0.0,
    Turno.NOTURNO: 7.0,
    Turno.ADMIN: 0.0,
}

# Art. 73, § 1º: a hora noturna é computada como 52 minutos e 30 segundos.
# Sete horas de relógio viram oito horas de remuneração — é aqui que a maior
# parte das planilhas erra e a diferença aparece na folha.
FATOR_HORA_NOTURNA = 60.0 / 52.5

# Art. 73, caput: adicional noturno de 20% sobre a hora diurna.
ADICIONAL_NOTURNO = 0.20

# Art. 59, § 1º: a hora extra é remunerada com acréscimo de no mínimo 50%.
ACRESCIMO_HORA_EXTRA = 0.50


# --------------------------------------------------------------------- regimes

class Regime(str, Enum):
    """Regime contratual do colaborador."""

    DOZE_TRINTA_SEIS = "12x36"   # art. 59-A
    QUARENTA_E_QUATRO = "44h"    # art. 58, caput


# Art. 59-A: 12 horas seguidas por 36 horas ininterruptas de descanso.
# Consequência prática na alocação: quem trabalha no dia D não pode trabalhar
# em D+1, e volta em D+2.
DIAS_DESCANSO_12X36 = 1

# Turnos por mês que cabem dentro do regime sem gerar hora extra.
# 12x36: dia sim, dia não — 15 turnos de 12h = 180h, dentro do teto de 220h.
TURNOS_CONTRATADOS_MES: dict[Regime, int] = {
    Regime.DOZE_TRINTA_SEIS: 15,
    Regime.QUARENTA_E_QUATRO: 22,
}

DIAS_MES_REFERENCIA = 30

# Art. 67: repouso semanal remunerado de 24 horas consecutivas.
# Em 12x36 ele é automático; no regime 44h precisa ser imposto.
MAX_DIAS_SEGUIDOS_SEM_FOLGA = 6


def teto_de_turnos(regime: Regime, dias: int) -> int:
    """Quantos turnos cabem no horizonte, para este regime.

    A constante mensal sozinha não serve para horizonte diferente de 30 dias, e
    tratá-la como fixa foi um erro real: rodando o mesmo cenário em 14 dias, o
    efetivo era dimensionado como se cada pessoa entregasse 15 turnos em duas
    semanas. O resultado foi uma operação com metade da gente necessária e uma
    escala impossível — o solver estava certo, o cenário é que era absurdo.

    No 12x36 há dois tetos e vale o menor: o proporcional ao contrato e o que a
    alternância permite, que é um dia sim, um dia não.
    """
    proporcional = int(TURNOS_CONTRATADOS_MES[regime] * dias / DIAS_MES_REFERENCIA)
    if regime is Regime.DOZE_TRINTA_SEIS:
        return max(1, min(proporcional, (dias + 1) // 2))
    return max(1, proporcional)


# --------------------------------------------------------------- qualificação

class Qualificacao(str, Enum):
    """O que o posto exige e o que o colaborador pode assumir.

    A ordem importa: quem é armado também pode cobrir posto desarmado, mas o
    contrário não. É essa assimetria que faz a escala travar quando alguém
    falta num posto armado.
    """

    ARMADO = "vigilante_armado"
    DESARMADO = "vigilante_desarmado"
    PORTARIA = "porteiro"


# Quem pode cobrir o quê. Vigilante armado cobre tudo; porteiro cobre portaria.
COBERTURA: dict[Qualificacao, set[Qualificacao]] = {
    Qualificacao.ARMADO: {Qualificacao.ARMADO, Qualificacao.DESARMADO, Qualificacao.PORTARIA},
    Qualificacao.DESARMADO: {Qualificacao.DESARMADO, Qualificacao.PORTARIA},
    Qualificacao.PORTARIA: {Qualificacao.PORTARIA},
}


def pode_cobrir(colaborador: Qualificacao, exigida: Qualificacao) -> bool:
    return exigida in COBERTURA[colaborador]


# ------------------------------------------------------------------ entidades

@dataclass(frozen=True)
class Colaborador:
    id: str
    nome: str
    regime: Regime
    qualificacao: Qualificacao
    valor_hora: float
    # Dias do horizonte em que a pessoa não pode ser escalada: férias,
    # atestado, afastamento. Índice do dia, começando em 0.
    indisponivel: frozenset[int] = field(default_factory=frozenset)

    def disponivel_em(self, dia: int) -> bool:
        return dia not in self.indisponivel

    def turnos_permitidos(self) -> tuple[Turno, ...]:
        """Regime 44h não faz turno noturno de 12 horas.

        Não é proibição da CLT — é decisão de política. Misturar jornada de
        8h48 com turno de 12 horas noturno estoura o interjornada do art. 66 no
        dia seguinte e é o caminho mais rápido para passivo trabalhista.
        """
        if self.regime is Regime.DOZE_TRINTA_SEIS:
            return (Turno.DIURNO, Turno.NOTURNO)
        return (Turno.ADMIN,)


@dataclass(frozen=True)
class Posto:
    """Um ponto que precisa de gente, com a qualificação que ele exige."""

    id: str
    nome: str
    qualificacao: Qualificacao
    vinte_e_quatro_horas: bool  # True: diurno + noturno todos os dias
    # Penalidade contratual por deixar o posto descoberto por um turno.
    # É o que o cliente desconta da fatura — e o que torna comparável uma
    # escala barata que deixa buraco com uma escala completa mais cara.
    multa_descoberto: float = 900.0


@dataclass
class Cenario:
    """Uma operação inteira num horizonte de dias."""

    dias: int
    postos: list[Posto]
    colaboradores: list[Colaborador]
    primeiro_dia_semana: int = 0  # 0 = segunda-feira

    def e_fim_de_semana(self, dia: int) -> bool:
        return (self.primeiro_dia_semana + dia) % 7 >= 5

    def e_domingo(self, dia: int) -> bool:
        return (self.primeiro_dia_semana + dia) % 7 == 6

    def vagas(self) -> list[Vaga]:
        """Todo turno de todo posto que precisa de alguém no horizonte.

        É a unidade de trabalho do problema. Um posto de 24h abre duas vagas
        por dia; um posto administrativo abre uma, e só em dia útil.
        """
        abertas: list[Vaga] = []
        for dia in range(self.dias):
            for posto in self.postos:
                if posto.vinte_e_quatro_horas:
                    turnos = (Turno.DIURNO, Turno.NOTURNO)
                elif self.e_fim_de_semana(dia):
                    continue  # posto administrativo não abre no fim de semana
                else:
                    turnos = (Turno.ADMIN,)
                for turno in turnos:
                    abertas.append(Vaga(dia=dia, turno=turno, posto=posto))
        return abertas

    def demanda(self) -> dict[tuple[int, Turno, Qualificacao], int]:
        """A mesma informação agregada por qualificação.

        Postos da mesma qualificação e do mesmo turno são intercambiáveis para
        efeito de alocação, e trabalhar com a contagem em vez da vaga individual
        reduz o modelo do solver em uma ordem de grandeza.
        """
        exigencia: dict[tuple[int, Turno, Qualificacao], int] = {}
        for vaga in self.vagas():
            chave = (vaga.dia, vaga.turno, vaga.posto.qualificacao)
            exigencia[chave] = exigencia.get(chave, 0) + 1
        return exigencia

    def turnos_a_cobrir(self) -> int:
        return len(self.vagas())


@dataclass(frozen=True)
class Vaga:
    dia: int
    turno: Turno
    posto: Posto


@dataclass(frozen=True)
class Alocacao:
    """Uma pessoa, num dia, num turno, num posto específico.

    Guardar o posto e não só o turno não é preciosismo: sem ele não dá para
    conferir habilitação, e escala que não diz onde a pessoa vai não é escala —
    é previsão de headcount.
    """

    turno: Turno
    posto: str


# Uma escala é o que sai de qualquer método.
Escala = dict[tuple[str, int], Alocacao]  # (id_colaborador, dia) -> alocação
