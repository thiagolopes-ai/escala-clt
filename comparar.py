"""Roda os três métodos no mesmo cenário e imprime a comparação.

É este script que produz os números do README. Ele existe para que qualquer
pessoa possa contestar o resultado sem acreditar em mim: mesmo cenário, mesma
semente, mesma auditoria para os três.

Uso:
    python comparar.py                      # comparação dos métodos
    python comparar.py --dimensionar        # e a análise de contratação
    python comparar.py --semente 7 --json saida.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from escala.cenario import gerar, resumo
from escala.clt import Auditoria, auditar
from escala.dominio import Qualificacao, Regime
from escala.manual import METODOS
from escala.solver import dimensionar, onde_falta, resolver


def _linha(nome: str, auditoria: Auditoria, segundos: float | None = None) -> str:
    custo = auditoria.custo
    tempo = f"{segundos:>6.1f}s" if segundos is not None else "     —"
    return (
        f"{nome:<27} {auditoria.cobertura:>8.1%} {custo.turnos_descobertos:>7} "
        f"{len(auditoria.infracoes):>10} {custo.horas_extras:>9.0f} "
        f"{custo.folha:>13,.0f} {custo.valor_multa_descoberto:>11,.0f} "
        f"{custo.total:>13,.0f} {tempo}"
    )


def _cabecalho() -> str:
    titulo = (
        f"{'método':<27} {'cobertura':>8} {'descob.':>7} {'infrações':>10} "
        f"{'h extras':>9} {'folha R$':>13} {'multa R$':>11} {'TOTAL R$':>13} {'tempo':>7}"
    )
    return titulo + "\n" + "-" * len(titulo)


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--semente", type=int, default=42)
    analisador.add_argument("--dias", type=int, default=30)
    analisador.add_argument("--segundos", type=float, default=60.0)
    analisador.add_argument("--dimensionar", action="store_true")
    analisador.add_argument("--json", help="grava os números neste arquivo")
    argumentos = analisador.parse_args()

    cenario = gerar(semente=argumentos.semente, dias=argumentos.dias)
    print("CENÁRIO")
    print(resumo(cenario))
    print()

    print("COMPARAÇÃO DOS MÉTODOS")
    print(_cabecalho())

    resultados: dict[str, dict] = {}
    auditorias: dict[str, Auditoria] = {}

    for nome, metodo in METODOS.items():
        auditoria = auditar(metodo(cenario), cenario)
        auditorias[nome] = auditoria
        print(_linha(nome, auditoria))

    otimizado = resolver(cenario, segundos=argumentos.segundos)
    auditoria_solver = auditar(otimizado.escala, cenario)
    auditorias["programação por restrições"] = auditoria_solver
    print(_linha("programação por restrições", auditoria_solver, otimizado.segundos))

    for nome, auditoria in auditorias.items():
        resultados[nome] = {
            "cobertura": round(auditoria.cobertura, 4),
            "descobertos": auditoria.custo.turnos_descobertos,
            "infracoes": len(auditoria.infracoes),
            "por_artigo": auditoria.por_artigo(),
            "horas_extras": round(auditoria.custo.horas_extras, 1),
            "folha": round(auditoria.custo.folha, 2),
            "multa": round(auditoria.custo.valor_multa_descoberto, 2),
            "total": round(auditoria.custo.total, 2),
        }

    print()
    print(f"Status do solver: {otimizado.status} — o ótimo está provado, "
          f"não é o melhor que ele achou no tempo disponível." if otimizado.otimo
          else f"Status do solver: {otimizado.status} — melhor solução dentro do tempo.")

    referencia = auditorias["supervisor que confere"]
    economia = referencia.custo.total - auditoria_solver.custo.total
    print(f"Economia sobre a escala conforme: R$ {economia:,.0f} "
          f"({economia / referencia.custo.total:.1%}) — com {len(auditoria_solver.infracoes)} infrações.")

    apressado = auditorias["supervisor apressado"]
    economia_apressado = apressado.custo.total - auditoria_solver.custo.total
    print(f"Economia sobre a escala apressada: R$ {economia_apressado:,.0f} "
          f"({economia_apressado / apressado.custo.total:.1%}) — e {len(apressado.infracoes)} "
          "infrações a menos.")

    print()
    print("O QUE O ÓTIMO NÃO CONSEGUE COBRIR")
    faltando = onde_falta(otimizado.escala, cenario)
    if not faltando:
        print("  nada — o efetivo atual fecha o mês")
    for (turno, qualificacao), quantos in faltando.items():
        print(f"  {quantos:>3} turnos {turno.value} de {qualificacao.value}")
    print("  Como o solver terminou em ótimo, estes turnos não são falha do método:")
    print("  são prova de que o efetivo atual não os cobre sem quebrar a lei.")
    resultados["descoberto_por_tipo"] = {
        f"{t.value}/{q.value}": n for (t, q), n in faltando.items()
    }

    if argumentos.dimensionar:
        print()
        print("CONTRATAR RESOLVE? DEPENDE DE QUEM")
        for rotulo, qualificacao, regime in (
            ("vigilante armado 12x36", Qualificacao.ARMADO, Regime.DOZE_TRINTA_SEIS),
            ("porteiro 44h", Qualificacao.PORTARIA, Regime.QUARENTA_E_QUATRO),
        ):
            print(f"\n  contratando {rotulo}")
            print(f"  {'qtd':>4} {'descob.':>8} {'operacional':>13} "
                  f"{'contratação':>13} {'TOTAL':>13}")
            linhas = dimensionar(
                cenario, qualificacao, regime, ate=3,
                segundos_por_rodada=max(15.0, argumentos.segundos / 3),
            )
            for linha in linhas:
                print(f"  {linha.contratacoes:>4} {linha.descobertos:>8} "
                      f"{linha.custo_operacional:>13,.0f} {linha.custo_contratacao:>13,.0f} "
                      f"{linha.total:>13,.0f}")
            melhor = min(linhas, key=lambda d: d.total)
            resultados[f"dimensionamento_{qualificacao.value}"] = [
                asdict(linha) for linha in linhas
            ]
            print(f"  → melhor: {melhor.contratacoes} contratação(ões), "
                  f"total R$ {melhor.total:,.0f}")

    if argumentos.json:
        with open(argumentos.json, "w", encoding="utf-8") as arquivo:
            json.dump(resultados, arquivo, ensure_ascii=False, indent=2)
        print(f"\nnúmeros gravados em {argumentos.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
