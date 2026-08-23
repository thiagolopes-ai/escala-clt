"""As duas escalas manuais contra as quais o otimizador precisa ganhar.

Linha de base fraca não mede nada. Se eu comparasse o solver contra um método
propositalmente burro, o número do README seria propaganda — e a primeira
pergunta de qualquer entrevista técnica séria seria exatamente essa.

Por isso são duas:

**Supervisor apressado.** Preenche o buraco com quem estiver disponível, na
ordem da lista. Não é burrice: é o que acontece às seis da manhã quando o
vigilante do posto armado não apareceu e o cliente está ligando. Ela cobre
quase tudo e gera infração.

**Supervisor que confere.** O mesmo método, mas recusa qualquer alocação que
quebre a CLT. Quando não acha ninguém legal para o buraco, deixa o posto
descoberto — porque é isso que um gestor responsável faz. Ela sai conforme e a
conta chega pela multa contratual.

As duas juntas mostram a escolha real que a operação enfrenta hoje: **passivo
trabalhista ou desconto na fatura.** O valor do otimizador é não precisar
escolher.
"""

from __future__ import annotations

from collections import defaultdict

from .dominio import (
    Alocacao,
    Cenario,
    Colaborador,
    Escala,
    MAX_DIAS_SEGUIDOS_SEM_FOLGA,
    Qualificacao,
    Regime,
    Vaga,
    teto_de_turnos,
    pode_cobrir,
)

# Margem de hora extra que um supervisor prudente aceita por conta própria
# antes de escalar o buraco para o gestor. Três turnos no mês.
TOLERANCIA_EXTRA = 3


def _ordem_de_atendimento(cenario: Cenario) -> list[Vaga]:
    """As vagas na ordem em que um supervisor as enfrenta: dia após dia, e
    dentro do dia começando pelo posto mais difícil de cobrir."""
    prioridade = {
        Qualificacao.ARMADO: 0,
        Qualificacao.DESARMADO: 1,
        Qualificacao.PORTARIA: 2,
    }
    return sorted(
        cenario.vagas(),
        key=lambda v: (v.dia, prioridade[v.posto.qualificacao], v.turno.value, v.posto.id),
    )


class _Estado:
    """O que o supervisor consegue lembrar enquanto monta a escala."""

    def __init__(self, cenario: Cenario) -> None:
        self.cenario = cenario
        self.escala: Escala = {}
        self.dias_trabalhados: dict[str, set[int]] = defaultdict(set)
        self.turnos_no_mes: dict[str, int] = defaultdict(int)

    def alocar(self, pessoa: str, vaga: Vaga) -> None:
        self.escala[(pessoa, vaga.dia)] = Alocacao(turno=vaga.turno, posto=vaga.posto.id)
        self.dias_trabalhados[pessoa].add(vaga.dia)
        self.turnos_no_mes[pessoa] += 1

    def ocupado(self, pessoa: str, dia: int) -> bool:
        return dia in self.dias_trabalhados[pessoa]

    def quebraria_descanso(self, colaborador: Colaborador, dia: int) -> bool:
        """Art. 59-A: trabalhou ontem ou trabalha amanhã impede hoje."""
        if colaborador.regime is not Regime.DOZE_TRINTA_SEIS:
            return False
        dias = self.dias_trabalhados[colaborador.id]
        return (dia - 1) in dias or (dia + 1) in dias

    def quebraria_repouso(self, pessoa: str, dia: int) -> bool:
        """Art. 67: não pode fechar sequência acima do limite sem folga."""
        dias = self.dias_trabalhados[pessoa] | {dia}
        seguidos = 0
        for d in range(self.cenario.dias):
            seguidos = seguidos + 1 if d in dias else 0
            if seguidos > MAX_DIAS_SEGUIDOS_SEM_FOLGA:
                return True
        return False


def _elegivel_basico(
    estado: _Estado, colaborador: Colaborador, vaga: Vaga
) -> bool:
    """O que até o supervisor apressado enxerga na hora.

    Pessoa em férias não aparece no posto, e ninguém fica em dois lugares ao
    mesmo tempo. Habilitação e turno permitido também entram aqui: escalar
    porteiro em posto armado não é economia, é interdição.
    """
    return (
        colaborador.disponivel_em(vaga.dia)
        and not estado.ocupado(colaborador.id, vaga.dia)
        and pode_cobrir(colaborador.qualificacao, vaga.posto.qualificacao)
        and vaga.turno in colaborador.turnos_permitidos()
    )


def supervisor_apressado(cenario: Cenario) -> Escala:
    """Cobre o buraco com quem estiver livre. Não confere a lei."""
    estado = _Estado(cenario)
    for vaga in _ordem_de_atendimento(cenario):
        for colaborador in cenario.colaboradores:
            if _elegivel_basico(estado, colaborador, vaga):
                estado.alocar(colaborador.id, vaga)
                break
    return estado.escala


def supervisor_que_confere(cenario: Cenario) -> Escala:
    """O mesmo método, recusando o que quebra a lei.

    Quando não existe ninguém legalmente escalável, o posto fica descoberto.
    """
    estado = _Estado(cenario)
    for vaga in _ordem_de_atendimento(cenario):
        for colaborador in cenario.colaboradores:
            if not _elegivel_basico(estado, colaborador, vaga):
                continue
            if estado.quebraria_descanso(colaborador, vaga.dia):
                continue
            if estado.quebraria_repouso(colaborador.id, vaga.dia):
                continue
            teto = teto_de_turnos(colaborador.regime, cenario.dias) + TOLERANCIA_EXTRA
            if estado.turnos_no_mes[colaborador.id] >= teto:
                continue
            estado.alocar(colaborador.id, vaga)
            break
    return estado.escala


METODOS = {
    "supervisor apressado": supervisor_apressado,
    "supervisor que confere": supervisor_que_confere,
}
