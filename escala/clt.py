"""Audita uma escala contra a CLT e calcula quanto ela custa.

Este é o módulo que dá nome ao projeto, e ele foi escrito para ser lido por
duas pessoas diferentes: quem programa e quem responde pelo passivo
trabalhista. Cada regra é uma função curta, com o artigo no nome do achado e a
explicação em linguagem de gente — não de código.

Ele audita **qualquer** escala: a que veio da planilha do supervisor, a que
saiu do sistema legado, a que este projeto gerou. Isso é de propósito. Um
validador que só sabe conferir a própria saída não serve para diagnóstico, e
diagnóstico é o que uma operação precisa antes de trocar de método.

Ele também não tem nenhuma dependência externa, e isso não é acaso: é o que
permite que este mesmo arquivo rode dentro do navegador do cliente, sem que a
escala — que tem nome de gente — precise ser enviada para servidor nenhum.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .dominio import (
    ACRESCIMO_HORA_EXTRA,
    ADICIONAL_NOTURNO,
    Cenario,
    Colaborador,
    Escala,
    FATOR_HORA_NOTURNA,
    HORAS_RELOGIO_NOTURNAS,
    HORAS_TURNO,
    MAX_DIAS_SEGUIDOS_SEM_FOLGA,
    Regime,
    Turno,
    teto_de_turnos,
    pode_cobrir,
)

# Marcador de infração que não é de um dia, e sim do mês fechado — o limite de
# horas extras é o caso. Sem isso a saída imprimia "dia -1", que não quer dizer
# nada para quem vai ler o relatório.
SEM_DIA = -1


@dataclass(frozen=True)
class Infracao:
    artigo: str
    regra: str
    colaborador: str
    dia: int
    detalhe: str

    def __str__(self) -> str:
        quando = "no mês" if self.dia == SEM_DIA else f"dia {self.dia + 1:>2}"
        return f"[{self.artigo}] {self.colaborador} {quando}: {self.detalhe}"


@dataclass
class Custo:
    """Onde o dinheiro vai. Separado, porque o total sozinho não decide nada."""

    horas_normais: float = 0.0
    horas_extras: float = 0.0
    horas_noturnas_remuneradas: float = 0.0
    valor_normal: float = 0.0
    valor_extra: float = 0.0
    valor_adicional_noturno: float = 0.0
    valor_multa_descoberto: float = 0.0
    turnos_descobertos: int = 0

    @property
    def total(self) -> float:
        return (
            self.valor_normal
            + self.valor_extra
            + self.valor_adicional_noturno
            + self.valor_multa_descoberto
        )

    @property
    def folha(self) -> float:
        """Só o que sai em folha, sem a multa contratual."""
        return self.valor_normal + self.valor_extra + self.valor_adicional_noturno


@dataclass
class Auditoria:
    infracoes: list[Infracao] = field(default_factory=list)
    custo: Custo = field(default_factory=Custo)
    turnos_alocados: int = 0
    turnos_exigidos: int = 0

    @property
    def conforme(self) -> bool:
        return not self.infracoes

    @property
    def cobertura(self) -> float:
        if not self.turnos_exigidos:
            return 1.0
        return self.turnos_alocados / self.turnos_exigidos

    def por_artigo(self) -> dict[str, int]:
        contagem: dict[str, int] = defaultdict(int)
        for i in self.infracoes:
            contagem[f"{i.artigo} — {i.regra}"] += 1
        return dict(sorted(contagem.items()))


# ------------------------------------------------------------------- as regras

def _um_turno_por_dia(escala: Escala) -> list[Infracao]:
    """Ninguém está em dois lugares ao mesmo tempo.

    Não é artigo da CLT — é física. Mas entra na auditoria porque é o erro
    número um de planilha compartilhada entre supervisores de sites diferentes,
    e ele só aparece quando o holerite fecha.
    """
    vistos: dict[tuple[str, int], int] = defaultdict(int)
    for (pessoa, dia) in escala:
        vistos[(pessoa, dia)] += 1
    return [
        Infracao("física", "dupla alocação", pessoa, dia,
                 f"escalado em {n} turnos no mesmo dia")
        for (pessoa, dia), n in vistos.items() if n > 1
    ]


def _descanso_12x36(escala: Escala, pessoas: dict[str, Colaborador]) -> list[Infracao]:
    """Art. 59-A: 12 horas de trabalho por 36 ininterruptas de descanso.

    Consequência na alocação: quem trabalhou no dia D não pode trabalhar em
    D+1. Esta é a regra que a escala manual mais quebra, porque na hora de
    tapar buraco o supervisor olha quem está de folga hoje — e quem está de
    folga hoje é justamente quem trabalhou ontem.
    """
    achados = []
    dias_por_pessoa: dict[str, set[int]] = defaultdict(set)
    for (pessoa, dia) in escala:
        dias_por_pessoa[pessoa].add(dia)

    for pessoa, dias in dias_por_pessoa.items():
        colaborador = pessoas.get(pessoa)
        if colaborador is None or colaborador.regime is not Regime.DOZE_TRINTA_SEIS:
            continue
        for dia in sorted(dias):
            if dia + 1 in dias:
                achados.append(Infracao(
                    "art. 59-A", "descanso de 36h no regime 12x36", pessoa, dia,
                    f"trabalhou no dia {dia + 1} e voltou no dia {dia + 2}, sem as 36h de descanso",
                ))
    return achados


def _interjornada(escala: Escala, pessoas: dict[str, Colaborador]) -> list[Infracao]:
    """Art. 66: mínimo de 11 horas consecutivas entre duas jornadas.

    No regime 44h com turno administrativo de 08h às 17h48, dois dias seguidos
    deixam mais de 14 horas de intervalo — está sempre folgado. A regra pega o
    caso em que alguém de 44h é jogado num turno de 12 horas para tapar buraco,
    que é o atalho mais comum e o mais caro.
    """
    achados = []
    turnos_por_pessoa: dict[str, dict[int, Turno]] = defaultdict(dict)
    for (pessoa, dia), alocacao in escala.items():
        turnos_por_pessoa[pessoa][dia] = alocacao.turno

    for pessoa, por_dia in turnos_por_pessoa.items():
        colaborador = pessoas.get(pessoa)
        if colaborador is None:
            continue
        for dia, turno in sorted(por_dia.items()):
            if turno not in colaborador.turnos_permitidos():
                achados.append(Infracao(
                    "art. 66", "intervalo de 11h entre jornadas", pessoa, dia,
                    f"regime {colaborador.regime.value} escalado em turno {turno.value}, "
                    "o que não fecha o interjornada do dia seguinte",
                ))
    return achados


def _repouso_semanal(escala: Escala, cenario: Cenario) -> list[Infracao]:
    """Art. 67: repouso semanal remunerado de 24 horas consecutivas.

    Em 12x36 o repouso é automático — quem trabalha dia sim, dia não, folga
    metade do mês. A regra existe para o regime 44h e para o caso em que o
    12x36 é distorcido por horas extras seguidas.
    """
    achados = []
    dias_por_pessoa: dict[str, set[int]] = defaultdict(set)
    for (pessoa, dia) in escala:
        dias_por_pessoa[pessoa].add(dia)

    for pessoa, dias in dias_por_pessoa.items():
        seguidos = 0
        for dia in range(cenario.dias):
            seguidos = seguidos + 1 if dia in dias else 0
            if seguidos > MAX_DIAS_SEGUIDOS_SEM_FOLGA:
                achados.append(Infracao(
                    "art. 67", "repouso semanal remunerado", pessoa, dia,
                    f"{seguidos} dias seguidos de trabalho sem folga de 24h",
                ))
                seguidos = 0
    return achados


def _qualificacao(escala: Escala, cenario: Cenario) -> list[Infracao]:
    """Posto armado não aceita cobertura de quem não é habilitado.

    Não é CLT: é a Lei 7.102/1983 e a portaria da Polícia Federal. Entra aqui
    porque a consequência é mais grave que hora extra — é interdição do posto e
    responsabilidade do preposto.

    Repare no que esta regra **não** faz: ela não acusa posto vazio. Posto sem
    ninguém é problema contratual e aparece na multa; posto com a pessoa errada
    é problema regulatório e aparece aqui. Na primeira versão os dois estavam
    juntos, e o resultado era uma escala conforme aparecendo com 23 infrações
    que não existiam.
    """
    pessoas = {c.id: c for c in cenario.colaboradores}
    postos = {p.id: p for p in cenario.postos}
    achados = []

    for (pessoa, dia), alocacao in escala.items():
        colaborador = pessoas.get(pessoa)
        posto = postos.get(alocacao.posto)
        if colaborador is None or posto is None:
            continue
        if not pode_cobrir(colaborador.qualificacao, posto.qualificacao):
            achados.append(Infracao(
                "Lei 7.102/83", "habilitação do posto", pessoa, dia,
                f"{colaborador.qualificacao.value} escalado em posto "
                f"{posto.id} que exige {posto.qualificacao.value}",
            ))
    return achados


def _limite_de_extras(
    escala: Escala, pessoas: dict[str, Colaborador], dias: int
) -> list[Infracao]:
    """Art. 59: a jornada só pode ser acrescida de até 2 horas suplementares.

    Traduzido para escala de 12 horas: turno extra inteiro não cabe no limite
    diário, então a hora extra aqui aparece como turno além do contratado no
    mês. O teto usado é o do art. 59 aplicado ao mês — 2h por dia útil.
    """
    achados = []
    turnos_no_mes: dict[str, int] = defaultdict(int)
    for (pessoa, _dia) in escala:
        turnos_no_mes[pessoa] += 1

    for pessoa, quantos in turnos_no_mes.items():
        colaborador = pessoas.get(pessoa)
        if colaborador is None:
            continue
        contratado = teto_de_turnos(colaborador.regime, dias)
        horas_extras = max(0, quantos - contratado) * HORAS_TURNO[
            Turno.DIURNO if colaborador.regime is Regime.DOZE_TRINTA_SEIS else Turno.ADMIN
        ]
        teto_mensal = 2.0 * 22 * dias / 30  # 2h por dia útil, art. 59
        if horas_extras > teto_mensal:
            achados.append(Infracao(
                "art. 59", "limite de horas suplementares", pessoa, SEM_DIA,
                f"{horas_extras:.0f}h extras no mês, acima do teto de {teto_mensal:.0f}h",
            ))
    return achados


def _trabalho_em_dia_indisponivel(
    escala: Escala, pessoas: dict[str, Colaborador]
) -> list[Infracao]:
    """Quem está de férias ou afastado não pode aparecer na escala.

    Art. 134: as férias são concedidas em período único ou parcelado, e durante
    elas o contrato fica suspenso quanto à prestação de serviço. Escalar alguém
    de férias é o erro que a planilha comete em silêncio e que só aparece
    quando a pessoa não chega.
    """
    return [
        Infracao("art. 134", "trabalho durante ausência prevista", pessoa, dia,
                 "escalado em dia de férias ou afastamento")
        for (pessoa, dia) in escala
        if pessoa in pessoas and not pessoas[pessoa].disponivel_em(dia)
    ]


REGRAS = (
    "física — dupla alocação",
    "art. 59-A — descanso de 36h",
    "art. 66 — interjornada de 11h",
    "art. 67 — repouso semanal",
    "art. 59 — limite de horas extras",
    "art. 134 — trabalho durante ausência",
    "Lei 7.102/83 — habilitação do posto",
)


# ---------------------------------------------------------------------- custo

def calcular_custo(escala: Escala, cenario: Cenario) -> Custo:
    """Quanto essa escala custa, separado por origem.

    O adicional noturno usa a hora reduzida do art. 73, § 1º: sete horas de
    relógio entre 22h e 5h valem oito horas de remuneração. É uma diferença de
    14% sobre a parcela noturna, e ela some em toda planilha que multiplica
    horas por valor sem olhar o relógio.
    """
    pessoas = {c.id: c for c in cenario.colaboradores}
    custo = Custo()
    turnos_no_mes: dict[str, int] = defaultdict(int)

    for (pessoa, _dia) in escala:
        turnos_no_mes[pessoa] += 1

    contados: dict[str, int] = defaultdict(int)
    for (pessoa, dia), alocacao in sorted(escala.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        colaborador = pessoas.get(pessoa)
        if colaborador is None:
            continue

        turno = alocacao.turno
        horas = HORAS_TURNO[turno]
        contados[pessoa] += 1
        contratado = teto_de_turnos(colaborador.regime, cenario.dias)
        e_extra = contados[pessoa] > contratado

        if e_extra:
            custo.horas_extras += horas
            custo.valor_extra += horas * colaborador.valor_hora * (1 + ACRESCIMO_HORA_EXTRA)
        else:
            custo.horas_normais += horas
            custo.valor_normal += horas * colaborador.valor_hora

        noturnas = HORAS_RELOGIO_NOTURNAS[turno] * FATOR_HORA_NOTURNA
        if noturnas:
            custo.horas_noturnas_remuneradas += noturnas
            custo.valor_adicional_noturno += (
                noturnas * colaborador.valor_hora * ADICIONAL_NOTURNO
            )

    descobertos, multa = _turnos_descobertos(escala, cenario)
    custo.turnos_descobertos = descobertos
    custo.valor_multa_descoberto = multa
    return custo


def _turnos_descobertos(escala: Escala, cenario: Cenario) -> tuple[int, float]:
    """Posto sem gente é o custo que a escala barata esconde.

    Sem contabilizar isso, qualquer método que simplesmente deixe de escalar
    ganha da escala completa — e é assim que se escolhe a pior opção com
    planilha na mão.
    """
    postos = {p.id: p for p in cenario.postos}
    preenchidas = {(a.posto, dia, a.turno) for (_pessoa, dia), a in escala.items()}

    descobertos = 0
    multa = 0.0
    for vaga in cenario.vagas():
        if (vaga.posto.id, vaga.dia, vaga.turno) not in preenchidas:
            descobertos += 1
            multa += postos[vaga.posto.id].multa_descoberto
    return descobertos, multa


# ------------------------------------------------------------------- auditoria

def auditar(escala: Escala, cenario: Cenario) -> Auditoria:
    """Roda todas as regras e o custo. É a única porta de entrada do módulo."""
    pessoas = {c.id: c for c in cenario.colaboradores}

    infracoes: list[Infracao] = []
    infracoes += _um_turno_por_dia(escala)
    infracoes += _descanso_12x36(escala, pessoas)
    infracoes += _interjornada(escala, pessoas)
    infracoes += _repouso_semanal(escala, cenario)
    infracoes += _limite_de_extras(escala, pessoas, cenario.dias)
    infracoes += _trabalho_em_dia_indisponivel(escala, pessoas)
    infracoes += _qualificacao(escala, cenario)

    return Auditoria(
        infracoes=infracoes,
        custo=calcular_custo(escala, cenario),
        turnos_alocados=len(escala),
        turnos_exigidos=cenario.turnos_a_cobrir(),
    )
