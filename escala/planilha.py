"""Lê a escala que já existe e devolve a escala gerada, em CSV.

Nenhuma operação vai trocar de método antes de ver o próprio erro. Por isso
esta é a porta de entrada da ferramenta: o supervisor exporta o mês que ele já
montou, joga aqui, e recebe a lista de infrações com o artigo ao lado.

O formato é o menor possível para não obrigar ninguém a reformatar planilha:

    dia,turno,posto,posto_exige,colaborador,regime,qualificacao

- `dia` aceita número (1, 2, 3...) ou data ISO (2026-08-01). No segundo caso o
  dia da semana passa a ser conhecido, o que melhora a checagem de repouso.
- `turno` é diurno, noturno ou admin.
- `posto_exige` e `qualificacao` são vigilante_armado, vigilante_desarmado ou
  porteiro.
- `regime` é 12x36 ou 44h.
- `colaborador` vazio significa turno que ficou descoberto. Aceitar isso é
  importante: escala real tem buraco, e esconder o buraco na importação
  esconderia justamente o que precisa ser medido.

Colunas extras são ignoradas em silêncio, porque planilha de operação sempre
tem colunas a mais.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from .dominio import (
    Alocacao,
    Cenario,
    Colaborador,
    Escala,
    Posto,
    Qualificacao,
    Regime,
    Turno,
)

COLUNAS_MINIMAS = {"dia", "turno", "posto", "colaborador"}

# Valor-hora usado quando a planilha não traz a coluna. Não muda a lista de
# infrações — só a estimativa de custo, que fica marcada como estimativa.
VALOR_HORA_PADRAO: dict[Qualificacao, float] = {
    Qualificacao.ARMADO: 18.50,
    Qualificacao.DESARMADO: 15.20,
    Qualificacao.PORTARIA: 12.80,
}

APELIDOS_TURNO = {
    "diurno": Turno.DIURNO, "dia": Turno.DIURNO, "d": Turno.DIURNO,
    "noturno": Turno.NOTURNO, "noite": Turno.NOTURNO, "n": Turno.NOTURNO,
    "admin": Turno.ADMIN, "administrativo": Turno.ADMIN, "a": Turno.ADMIN,
}

APELIDOS_QUALIFICACAO = {
    "vigilante_armado": Qualificacao.ARMADO, "armado": Qualificacao.ARMADO,
    "vigilante armado": Qualificacao.ARMADO,
    "vigilante_desarmado": Qualificacao.DESARMADO,
    "vigilante desarmado": Qualificacao.DESARMADO,
    "desarmado": Qualificacao.DESARMADO,
    "porteiro": Qualificacao.PORTARIA, "portaria": Qualificacao.PORTARIA,
    "recepcao": Qualificacao.PORTARIA, "recepção": Qualificacao.PORTARIA,
}

APELIDOS_REGIME = {
    "12x36": Regime.DOZE_TRINTA_SEIS, "12/36": Regime.DOZE_TRINTA_SEIS,
    "12 x 36": Regime.DOZE_TRINTA_SEIS,
    "44h": Regime.QUARENTA_E_QUATRO, "44": Regime.QUARENTA_E_QUATRO,
    "clt": Regime.QUARENTA_E_QUATRO, "administrativo": Regime.QUARENTA_E_QUATRO,
}


class PlanilhaInvalida(ValueError):
    """Erro de formato, escrito para quem montou a planilha — não para quem
    escreveu o código."""


def _normalizar(texto: str) -> str:
    return (texto or "").strip().lower()


def _traduzir(valor: str, tabela: dict, campo: str, linha: int):
    chave = _normalizar(valor)
    if chave not in tabela:
        aceitos = ", ".join(sorted(set(str(v.value) for v in tabela.values())))
        raise PlanilhaInvalida(
            f"linha {linha}: {campo} '{valor}' não reconhecido. Aceitos: {aceitos}"
        )
    return tabela[chave]


def _ler_dia(valor: str, linha: int) -> date | int:
    bruto = (valor or "").strip()
    if not bruto:
        raise PlanilhaInvalida(f"linha {linha}: coluna 'dia' vazia")
    if bruto.isdigit():
        return int(bruto)
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            from datetime import datetime
            return datetime.strptime(bruto, formato).date()
        except ValueError:
            continue
    raise PlanilhaInvalida(
        f"linha {linha}: dia '{bruto}' não é número nem data (use 2026-08-01 ou 01/08/2026)"
    )


def ler(texto: str) -> tuple[Cenario, Escala]:
    """Converte o CSV em cenário e escala, prontos para `clt.auditar`."""
    leitor = csv.DictReader(io.StringIO(texto.strip()))
    if leitor.fieldnames is None:
        raise PlanilhaInvalida("arquivo vazio")

    cabecalho = {_normalizar(c) for c in leitor.fieldnames}
    faltando = COLUNAS_MINIMAS - cabecalho
    if faltando:
        raise PlanilhaInvalida(
            "faltam colunas obrigatórias: " + ", ".join(sorted(faltando))
        )

    registros = []
    for numero, bruta in enumerate(leitor, start=2):
        linha = {_normalizar(k): (v or "").strip() for k, v in bruta.items() if k}
        if not any(linha.values()):
            continue
        registros.append((numero, linha))

    if not registros:
        raise PlanilhaInvalida("nenhuma linha de dados além do cabeçalho")

    dias_brutos = [_ler_dia(l["dia"], n) for n, l in registros]
    primeiro_dia_semana = 0
    datas = [d for d in dias_brutos if isinstance(d, date)]
    if datas:
        origem = min(datas)
        primeiro_dia_semana = origem.weekday()
        indice = {d: (d - origem).days for d in set(datas)}
        dias = [indice[d] if isinstance(d, date) else d - 1 for d in dias_brutos]
    else:
        menor = min(dias_brutos)  # type: ignore[type-var]
        dias = [d - menor for d in dias_brutos]  # type: ignore[operator]

    postos: dict[str, Posto] = {}
    pessoas: dict[str, Colaborador] = {}
    escala: Escala = {}
    turnos_por_posto: dict[str, set[Turno]] = {}

    for (numero, linha), dia in zip(registros, dias):
        turno = _traduzir(linha["turno"], APELIDOS_TURNO, "turno", numero)
        id_posto = linha["posto"] or f"POSTO-{turno.value}"
        exige = _traduzir(
            linha.get("posto_exige") or linha.get("qualificacao") or "porteiro",
            APELIDOS_QUALIFICACAO, "posto_exige", numero,
        )
        turnos_por_posto.setdefault(id_posto, set()).add(turno)
        postos[id_posto] = Posto(
            id=id_posto,
            nome=linha.get("posto_nome") or id_posto,
            qualificacao=exige,
            vinte_e_quatro_horas=bool(
                turnos_por_posto[id_posto] & {Turno.DIURNO, Turno.NOTURNO}
            ),
        )

        id_pessoa = linha["colaborador"]
        if not id_pessoa:
            continue  # turno declarado como descoberto

        if id_pessoa not in pessoas:
            regime = _traduzir(
                linha.get("regime") or ("admin" if turno is Turno.ADMIN else "12x36"),
                APELIDOS_REGIME, "regime", numero,
            )
            qualificacao = _traduzir(
                linha.get("qualificacao") or linha.get("posto_exige") or "porteiro",
                APELIDOS_QUALIFICACAO, "qualificacao", numero,
            )
            valor = linha.get("valor_hora", "").replace(",", ".")
            pessoas[id_pessoa] = Colaborador(
                id=id_pessoa,
                nome=linha.get("colaborador_nome") or id_pessoa,
                regime=regime,
                qualificacao=qualificacao,
                valor_hora=float(valor) if valor else VALOR_HORA_PADRAO[qualificacao],
            )

        if (id_pessoa, dia) in escala:
            # Duas linhas para a mesma pessoa no mesmo dia. Não sobrescreve: a
            # dupla alocação é justamente uma das infrações que o auditor
            # precisa enxergar, e sobrescrever a esconderia.
            escala[(id_pessoa, dia)] = Alocacao(turno=turno, posto=id_posto)
            escala[(f"{id_pessoa} (2ª alocação)", dia)] = Alocacao(
                turno=turno, posto=id_posto
            )
            if f"{id_pessoa} (2ª alocação)" not in pessoas:
                pessoas[f"{id_pessoa} (2ª alocação)"] = pessoas[id_pessoa]
        else:
            escala[(id_pessoa, dia)] = Alocacao(turno=turno, posto=id_posto)

    cenario = Cenario(
        dias=max(dias) + 1,
        postos=list(postos.values()),
        colaboradores=list(pessoas.values()),
        primeiro_dia_semana=primeiro_dia_semana,
    )
    return cenario, escala


def escrever(escala: Escala, cenario: Cenario) -> str:
    """Devolve a escala no mesmo formato que a ferramenta lê.

    Fechar o ciclo importa: o gestor exporta, audita, gera a corrigida e
    reimporta no sistema dele sem passar por conversão manual — que é onde
    normalmente o erro volta a entrar.
    """
    pessoas = {c.id: c for c in cenario.colaboradores}
    postos = {p.id: p for p in cenario.postos}

    saida = io.StringIO()
    escritor = csv.writer(saida)
    escritor.writerow([
        "dia", "turno", "posto", "posto_exige",
        "colaborador", "colaborador_nome", "regime", "qualificacao", "valor_hora",
    ])

    preenchidas = {(a.posto, dia, a.turno) for (_p, dia), a in escala.items()}

    for (id_pessoa, dia), alocacao in sorted(escala.items(), key=lambda kv: (kv[0][1], kv[1].posto)):
        pessoa = pessoas.get(id_pessoa)
        posto = postos.get(alocacao.posto)
        escritor.writerow([
            dia + 1, alocacao.turno.value, alocacao.posto,
            posto.qualificacao.value if posto else "",
            id_pessoa, pessoa.nome if pessoa else "",
            pessoa.regime.value if pessoa else "",
            pessoa.qualificacao.value if pessoa else "",
            f"{pessoa.valor_hora:.2f}" if pessoa else "",
        ])

    # Os turnos que ninguém cobriu entram como linha sem colaborador, para que
    # o buraco continue visível depois da exportação.
    for vaga in cenario.vagas():
        if (vaga.posto.id, vaga.dia, vaga.turno) not in preenchidas:
            escritor.writerow([
                vaga.dia + 1, vaga.turno.value, vaga.posto.id,
                vaga.posto.qualificacao.value, "", "", "", "", "",
            ])

    return saida.getvalue()
