# escala-clt

Gera escala de postos de trabalho com as regras da CLT como restrição dura — e prova que a escala que gerou é a mais barata possível.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![OR-Tools](https://img.shields.io/badge/OR--Tools-CP--SAT-4285F4?style=flat-square&logo=google&logoColor=white)
![Licença MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-green?style=flat-square)

---

## O problema

Escala de segurança patrimonial é montada em planilha, por um supervisor, sob pressão. Ele precisa cobrir posto 24 horas em regime 12x36 e posto administrativo em jornada de 44 horas, com gente de férias, gente em atestado e um efetivo dimensionado no limite — porque folguista parado é custo que aparece no orçamento e hora extra é custo que aparece só na folha do mês seguinte.

Quando falta alguém às seis da manhã, ele tem duas saídas, e as duas custam caro:

**Cobrir o buraco com quem estiver disponível.** É o que o cliente exige e é o que gera passivo. A pessoa que está de folga hoje é justamente a que trabalhou ontem, e escalá-la quebra as 36 horas de descanso do art. 59-A.

**Deixar o posto descoberto.** É o que a lei permite e é o que o contrato pune. A fatura vem com desconto.

Este projeto mostra que essa escolha é falsa — e mede em reais o quanto ela custa.

---

## O número

Cenário de referência: **23 postos** (18 de 24 horas, 5 administrativos), **83 colaboradores**, **30 dias**, **1.190 turnos** a cobrir, **10,1% de dias de ausência**. Sintético, e explicado abaixo por quê.

| Método | Cobertura | Descobertos | Infrações | Horas extras | Folha | Multa | **Total** |
|---|---|---|---|---|---|---|---|
| Supervisor apressado | 99,1% | 11 | **1.110** | 5.496 h | R$ 311.409 | R$ 9.900 | **R$ 321.309** |
| Supervisor que confere | 91,3% | 103 | 0 | 0 h | R$ 218.844 | R$ 92.700 | **R$ 311.544** |
| **Programação por restrições** | **98,4%** | **19** | **0** | **0 h** | R$ 232.774 | R$ 17.100 | **R$ 249.874** |

**R$ 61.670 por mês** — 19,8% — abaixo da escala conforme, com as mesmas zero infrações.  
**R$ 71.435 por mês** — 22,2% — abaixo da escala apressada, e 1.110 infrações a menos.

Tempo para resolver: **7,8 segundos**, com status `OPTIMAL`. Reproduza com `python comparar.py`.

### Por que duas linhas de base, e não uma

Comparar um otimizador contra um método propositalmente burro é propaganda, não medição. As duas linhas de base existem porque as duas são reais, e porque juntas elas mostram a escolha que a operação enfrenta hoje: **passivo trabalhista ou desconto na fatura**. O valor do método não é ganhar de uma delas — é não precisar escolher.

O `supervisor que confere` recusa toda alocação ilegal e deixa o posto vazio quando não acha ninguém. Ele é a linha de base difícil, e é contra ela que os 19,8% valem.

### O que `OPTIMAL` significa aqui

Não é "a melhor que o programa achou no tempo disponível". É prova matemática de que **não existe escala mais barata** que respeite todas as restrições. O solver termina com o limite inferior igual ao valor encontrado.

Isso muda a natureza da entrega. O supervisor pode dizer que fez o melhor que deu; o solver demonstra que fez.

### Estabilidade

Um número que só vale numa semente não é número. Cinco cenários independentes:

| Semente | Escala conforme | Otimizada | Economia | % | Infrações | Status | Tempo |
|---|---|---|---|---|---|---|---|
| 1 | R$ 320.037 | R$ 261.474 | R$ 58.562 | 18,3% | 0 | OPTIMAL | 4,4 s |
| 7 | R$ 326.384 | R$ 265.251 | R$ 61.133 | 18,7% | 0 | OPTIMAL | 2,9 s |
| 13 | R$ 350.259 | R$ 263.995 | R$ 86.263 | 24,6% | 0 | OPTIMAL | 4,3 s |
| 42 | R$ 311.544 | R$ 249.874 | R$ 61.670 | 19,8% | 0 | OPTIMAL | 8,0 s |
| 99 | R$ 344.483 | R$ 261.340 | R$ 83.143 | 24,1% | 0 | OPTIMAL | 6,9 s |

Economia entre **18,3% e 24,6%**. Zero infrações em todos. Ótimo provado em todos, em menos de 8 segundos.

---

## O achado que não estava no roteiro

O solver deixou 19 turnos descobertos — e provou que não dá para cobri-los sem quebrar a lei. Essa informação sozinha vale pouco. O que muda a conversa de orçamento é a informação seguinte:

```
11 turnos administrativos de porteiro
 8 turnos noturnos de vigilante armado
```

O instinto de quem gerencia é contratar mais vigilante, que é a qualificação que cobre tudo. O projeto mostra o que acontece:

| Contratações | Descobertos | Operacional | Contratação | **Total** |
|---|---|---|---|---|
| **Vigilante armado 12x36** | | | | |
| 0 | 19 | R$ 249.874 | R$ 0 | **R$ 249.874** |
| 1 | 14 | R$ 246.632 | R$ 3.330 | R$ 249.962 |
| 2 | 11 | R$ 244.687 | R$ 6.660 | R$ 251.347 |
| 3 | 11 | R$ 244.687 | R$ 9.990 | R$ 254.677 |
| **Porteiro 44h** | | | | |
| 0 | 19 | R$ 249.874 | R$ 0 | R$ 249.874 |
| 1 | 12 | R$ 244.363 | R$ 2.478 | R$ 246.841 |
| 2 | 8 | R$ 241.213 | R$ 4.956 | **R$ 246.169** |
| 3 | 8 | R$ 241.213 | R$ 7.434 | R$ 248.647 |

Contratar vigilante armado **aumenta** o custo total em qualquer quantidade, e a partir da segunda contratação não cobre mais nenhum turno — porque quem falta está no regime 44h, e vigilante de 12x36 não cobre turno administrativo.

Contratar **dois porteiros no regime 44h** economiza R$ 3.705 por mês.

É a mesma ideia que eu repito em desenho de processo, aqui com número: **contratar sem diagnóstico só aumenta a folha.**

---

## As regras da lei, no código

O módulo `escala/clt.py` audita **qualquer** escala — a que veio da planilha, a que saiu do sistema legado, a que este projeto gerou. Isso é de propósito: validador que só confere a própria saída não serve para diagnóstico, e diagnóstico é o que vem antes de trocar de método.

| Regra | Dispositivo | O que ela impede |
|---|---|---|
| 36 horas de descanso | **art. 59-A** | Trabalhar em dias seguidos no regime 12x36 |
| Intervalo entre jornadas | **art. 66** | Jogar quem é de 44h num turno de 12 horas |
| Repouso semanal | **art. 67** | Sequência acima de seis dias sem folga |
| Limite de horas suplementares | **art. 59** | Extra além de 2 horas por dia útil |
| Trabalho durante ausência | **art. 134** | Escalar quem está de férias |
| Adicional e hora noturna | **art. 73, §§ 1º e 2º** | Pagar a noite pelo relógio, e não pela hora reduzida |
| Habilitação do posto | **Lei 7.102/1983** | Porteiro em posto armado |

Cada infração sai com o artigo, a pessoa, o dia e a explicação em linguagem de gente:

```
[art. 59-A] C042 dia 12: trabalhou em 12 e voltou em 13, sem as 36h de descanso
```

### O detalhe que some em toda planilha

Art. 73, § 1º: a hora noturna é computada como **52 minutos e 30 segundos**. O turno das 19h às 7h cobre sete horas de relógio dentro da janela legal das 22h às 5h — e essas sete horas são pagas como oito.

É uma diferença de 14% sobre a parcela noturna. Multiplicar hora por valor sem olhar o relógio erra para menos todo mês, e a diferença aparece no passivo.

Existe teste para isso.

---

## Por que dado sintético

Nenhum dado de cliente entra aqui, e isso não é limitação — é requisito. O que precisa ser reproduzido é a **estrutura** que faz a escala travar, e ela é pública:

- posto armado não aceita cobertura de porteiro, mas o contrário acontece;
- férias vêm em bloco de quinze dias, não em dias soltos pelo mês;
- o efetivo é dimensionado com folga pequena, porque folguista parado é custo visível.

É a terceira linha que cria o problema. **Operação com folga de efetivo não precisa de otimizador nenhum** — e um cenário generoso produziria um número inflado.

No cenário de referência, a capacidade legal máxima é de 1.099 turnos para uma demanda de 1.080: folga de **1,7%**. É esse aperto que faz o método importar.

---

## Como executar

```bash
git clone https://github.com/thiagolopes-ai/escala-clt.git
cd escala-clt
pip install -r requirements.txt

python comparar.py                    # reproduz a tabela principal
python comparar.py --dimensionar      # e a análise de contratação
python comparar.py --semente 7        # outro cenário
python -m pytest testes/ -q           # 22 testes
```

### Usando como biblioteca

```python
from escala.cenario import gerar
from escala.solver import resolver, onde_falta
from escala.clt import auditar

cenario = gerar(semente=42)
resultado = resolver(cenario, segundos=60)

auditoria = auditar(resultado.escala, cenario)
print(auditoria.conforme, auditoria.custo.total)

for (turno, qualificacao), quantos in onde_falta(resultado.escala, cenario).items():
    print(f"faltam {quantos} turnos {turno.value} de {qualificacao.value}")
```

Para auditar uma escala que já existe, sem gerar nada:

```python
auditoria = auditar(minha_escala_vinda_da_planilha, cenario)
for infracao in auditoria.infracoes:
    print(infracao)
```

---

## Decisões técnicas

| Decisão | Alternativa considerada | Por quê |
|---|---|---|
| Programação por restrições (CP-SAT) | Heurística sem retrocesso com correção | Ela decide um turno por vez e nunca desfaz. Com folga de 1,7%, desfazer é o que fecha a escala |
| CP-SAT | Programação linear inteira pura | As regras são combinatórias, não lineares: "não trabalha em dias seguidos" é natural em CP e desajeitado em PLI |
| Condição de Hall para substituição | Variável por (pessoa, dia, turno, classe) | As classes são encaixadas, então basta exigir gente suficiente em cada prefixo. Triplicaria o modelo para responder o mesmo |
| Auditor separado do gerador | Validação dentro do solver | Auditor que só confere a própria saída não audita planilha de terceiro — e é isso que a operação precisa primeiro |
| Multa contratual no custo | Comparar só a folha | Sem ela, o método que simplesmente não escala ninguém ganha de todos |
| Custo em centavos inteiros | Ponto flutuante | CP-SAT trabalha com inteiros; centavo é exato e evita objetivo com arredondamento |
| Duas linhas de base | Uma só | Uma linha fraca transforma medição em propaganda |

---

## Limitações

- **Cenário sintético.** A estrutura é real, os números são gerados. Em operação de verdade, recalibre o valor-hora, a multa contratual e a taxa de ausência antes de acreditar no percentual.
- **Ausência é conhecida de antemão.** Férias sim; atestado não. Uma versão útil em produção precisa de replanejamento diário, não de um plano mensal fechado.
- **Sem preferência de pessoa.** Ninguém escolhe turno, ninguém tem restrição de transporte, ninguém mora longe. Numa operação real isso existe e muda a solução — é a extensão mais óbvia.
- **Feriado não é tratado.** No 12x36 o trabalho em feriado é compensado pelo próprio regime, mas o adicional de domingo e a jornada de véspera merecem modelagem própria.
- **Um único mês.** A escala não conversa com o mês seguinte, e o ciclo par/ímpar do 12x36 atravessa a virada.
- **Não substitui advogado nem contador.** É ferramenta de diagnóstico e planejamento. A conferência final da folha continua sendo de quem responde por ela.

---

## Próximos passos

- [ ] Replanejamento diário com falta imprevista
- [ ] Preferência e restrição individual como custo, não como impedimento
- [ ] Horizonte de dois meses, com continuidade do ciclo 12x36
- [ ] Exportação da escala em planilha, no formato que o supervisor já usa
- [ ] Feriado e adicional de domingo

---

## Stack

Python 3.11 · OR-Tools (CP-SAT) · pytest

## Licença

MIT — veja [LICENSE](LICENSE).
