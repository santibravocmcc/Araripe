# Insumos da Phase 3 — cota de GEE e data de corte

**Escrito:** 2026-09-08, a pedido do dono, antes de a Phase 3 começar
**Status:** insumos medidos e uma recomendação. **A Phase 3 é quem registra a
decisão** — este documento existe para ela não rederivar as medições.

> **Fechado em 2026-09-09 — leia a §3 antes da §1.** O dono abriu a página de
> cotas de `ee-araripe` e o **X** desta estimativa deixou de ser um X. Com o
> número real, o replay custa **~3% de um mês** de alocação, e não os ~6% que a
> §1 estimou nem os ~19% da correção intermediária. A §3 traz a aritmética e a
> razão de cada uma das duas correções. **A §1 fica como estava, de propósito:
> ela é o registro do que se sabia em 08/09.**

A Phase 3 tem sete bullets. Dois deles são perguntas que valem responder antes,
porque a resposta muda o desenho das Fases 4 e 6: *"estimate GEE quotas, batch
sizes, storage, transfer, and runtime"* e *"choose and record the replay cutoff
date"*.

---

## 1. Cota de GEE — e o painel consultado é do projeto ERRADO

O dono enviou a página de cotas de **`ee-araripe-baseline-v2`**. Medido nos
arquivos: **a detecção não roda nesse projeto.**

    .github/workflows/detect_gee.yml:64
      EE_PROJECT: ${{ vars.EE_PROJECT || 'ee-araripe' }}

    scripts/check_esa_reprocessing.py:92
      @click.option("--project", default="ee-araripe-baseline-v2", ...)

Ou seja: `ee-araripe` é o projeto da **detecção** — e portanto o do replay da
Phase 4. `ee-araripe-baseline-v2` é o projeto da **baseline** e da vigilância de
reprocessamento da ESA. **A cota que a Phase 4 vai consumir não é a que foi
consultada.**

### O que a página consultada estabelece, e é útil de qualquer forma

| Item | Valor |
| --- | --- |
| Noncommercial EECU-seconds **por mês** | limite de sistema **3.600.000** |
| EECU-seconds **por dia** | **ilimitado** |
| Uso atual no mês (`ee-araripe-baseline-v2`) | **122.783** = **3,41%** |
| Read requests por minuto | 6.000, uso 0% |
| BigQuery slot-time por dia | 1.260.000, uso 0% |

Três coisas se aprendem daqui:

1. **O teto é mensal e o diário é ilimitado.** Um replay pode ser espalhado ou
   concentrado dentro de um mês sem bater em limite diário — a única pergunta é
   o total do mês.
2. **A alocação noncommercial é de 3,6 M EECU-s/mês**, e é por projeto. O limite
   de `ee-araripe` é, muito provavelmente, o mesmo número; o que não se sabe é o
   **uso atual** dele.
3. **Um trabalho real deste projeto caberia com folga:** a reconstrução da
   baseline v2 custou 122.783 EECU-s — 3,41% de um mês.

### Estimativa para a Phase 4, com as premissas explícitas

A Phase 4 processa cada data **uma vez** (*"process stateless spectral detection
in bounded chronological batches"*). A operação de hoje processa cada data
**várias** vezes: `SEARCH_DAYS_BACK = 16` e cadência seg/qui, então cada data cai
em ~4–5 janelas antes de sair do alcance.

Chamando de **X** o consumo mensal de detecção em `ee-araripe`:

- por mês há ~8,6 execuções × 16 dias de janela ≈ **138 processamentos-de-data**;
- custo por processamento-de-data ≈ **X / 138**;
- o replay de 2026-01-01 até um corte em ~30/08 são **~242 datas**, uma passagem
  cada ≈ **242 × X/138 ≈ 1,75 X**.

**Conclusão: o replay inteiro custa cerca de 1,75 mês da operação normal de
detecção, gasto uma vez, sem teto diário.** Se a detecção consome algo próximo
dos 3,4% que a baseline mostrou, o replay fica em torno de **6% de um mês** de
alocação. Mesmo com uma margem de erro de 10× continua caber num mês.

**A cota não deve ser o fator limitante da Phase 4.** O fator limitante é tempo
de máquina e de fila, não a alocação.

### O que ainda precisa ser medido, e é ação do dono

**Abrir a página de cotas de `ee-araripe`** e registrar duas linhas: o limite
mensal e o uso atual. É a única medição que falta para a estimativa acima deixar
de ter um X.

### Ressalvas que a Phase 3 deve carregar

- **O custo por data não é constante.** Mais cenas por data — nuvem, sobreposição
  de datatakes — custa mais compute. A estimativa usa uma média implícita.
- **A Phase 4 faz mais que detecção**: aplica anotações versionadas do MapBiomas
  e regenera tiers de persistência, subconjuntos fortes, estatísticas e série
  temporal. Parte disso é local, não GEE.
- **A Phase 5 pode forçar um segundo replay.** *"If a conditional method changes,
  rerun the affected 2026 stages"*. Orçar o replay como podendo acontecer duas
  vezes — o que, pelos números acima, continua confortável.
- **A baseline já foi paga** e não entra nesta conta.

## 2. Data de corte do replay — mecânica, trade, e recomendação

### O que o corte é, mecanicamente

Três bullets do roadmap definem o papel dele:

- Phase 3: *"choose and record the replay cutoff date. Queue acquisitions after
  that cutoff for later incremental processing"*;
- Phase 4: *"query every available 2026 physical acquisition/datatake from
  January 1 **through the recorded cutoff**"*;
- Phase 6: *"seed the scheduled process from the rebuilt watermark, then process
  **queued post-cutoff dates** through the five-day incremental contract"*.

Então o corte parte 2026 em dois: **antes** entra no replay em lote; **depois**
vira fila, drenada pelo caminho incremental normal **depois** do cutover.

### A restrição dura: o corte tem de estar terminal

O exit gate P4 exige que *"every manifest-bound expected acquisition has one
terminal ledger row, every daily summary reconciles those rows"*. Uma data cujas
aquisições esperadas ainda não são terminais **não pode** fechar o gate.

Medido na `main` agora, em `data/timeseries/RELEASE.json`:

    latest_observation : 2026-08-30
    published_utc      : 2026-09-07T15:52:37Z
    run_id             : 34137318406

Ou seja: **o próprio sistema declara 2026-08-30 como a última data plenamente
avaliada**, publicada em 07/09 — uma defasagem de ~8 dias, que é o revisita do
Sentinel-2 mais a exigência de terminalidade. Isso não é estimativa: é o que o
produtor afirma.

### O trade, e ele aponta numa direção só

| | replay | fila até o cutover |
| --- | --- | --- |
| corte **mais cedo** | menor | **maior** |
| corte **mais tarde** | maior | **menor** |

E o replay é **barato** (§1), enquanto a fila é a parte incômoda: ela é drenada
no cutover, pelo caminho incremental, e **cresce enquanto as Fases 4 e 5
correm** — a Fase 5 depende de pessoas rotulando, então o intervalo
corte→cutover é medido em semanas ou meses.

Concretamente: ~2 datas observadas por semana. Dois meses de Fase 5 são ~17
execuções, ~60 datas de fila. Pelo contrato incremental de cinco dias, isso é
~12 execuções de recuperação depois do cutover.

**Logo: quanto mais tarde o corte, melhor** — limitado pela terminalidade.

### Recomendação

**Duas partes, e as duas ficam registradas.**

1. **A regra**, que é o que de fato importa:

   > O corte é a última data UTC que o ledger declara plenamente terminal no
   > momento em que a consulta da Phase 4 é emitida, **resolvida e fixada como
   > data literal no registro daquela execução**.

   Fixar a data hoje e só rodar a Phase 4 em três semanas acrescentaria três
   semanas de fila sem nenhum ganho.

2. **A data provisória para a Phase 3 congelar e ensaiar: `2026-08-30`.**
   É a que o sistema declara avaliada, não um palpite com margem. Serve para o
   ensaio limitado da Phase 3 e para a fotografia dos artefatos.

**O que a Phase 3 congela não é a data — são as versões**: extensão, algoritmo,
baseline, máscara de nuvem/mosaico, seca, MapBiomas, rótulos, schema, ambiente e
release. Essas têm de congelar agora, e nenhuma delas depende do corte. É por
isso que a regra pode resolver depois sem enfraquecer o congelamento.

**Se preferir aderência literal ao bullet** — uma data escolhida e registrada
agora, ponto — então `2026-08-30`, e aceite a fila proporcional ao tempo até o
cutover. É defensável; só é mais caro no cutover.

### Um detalhe a não perder

A fila pós-corte tem de ser **enfileirada de propósito**, não esquecida. A Phase
3 diz *"queue acquisitions after that cutoff for later incremental
processing"* — ou seja, existe um registro explícito das datas que ficaram de
fora, e o cutover o consome. Sem esse registro, a diferença entre "data
enfileirada" e "data perdida" não é observável.

---

## 3. Adendo de 2026-09-09 — a cota está medida, e as duas correções

**Escrito:** 2026-09-09, depois de o dono abrir as duas páginas de cota.
**Nada da §1 ou da §2 foi reescrito.** Elas registram o que se sabia em 08/09; o
que segue é o que mudou com a medição.

### 3.1 O que o dono mediu

| projeto | limite mensal | uso no mês | % |
| --- | --- | --- | --- |
| **`ee-araripe`** (detecção — e o do replay) | 3.600.000 EECU-s | **6.242** | **0,17%** |
| `ee-araripe-baseline-v2` (baseline) | 3.600.000 EECU-s | 122.783 | 3,41% |

E o resto continua folgado nos dois: EECU-s por **dia** ilimitado, 6.000
leituras/minuto com 0% de uso, BigQuery slot-time 0%.

### 3.2 Quantas execuções gastaram esses 6.242

Medido com `gh run list --workflow detect_gee.yml`, setembro de 2026:

| data | gatilho | resultado |
| --- | --- | --- |
| 2026-09-03 | `schedule` | sucesso |
| 2026-09-07 | `schedule` | **falha** |
| 2026-09-07 | `workflow_dispatch` | sucesso (é a `run_id` do `RELEASE.json`) |

A falha **não gastou compute**: `gh run view 34120627779` mostra que ela parou em
*"Fetch persistence state from R2"*, e o passo *"Run GEE detection"* saiu como
`skipped`. Então os 6.242 EECU-s vêm de **duas** execuções completas:

    6.242 / 2 = 3.121 EECU-s por execução de detecção

Setembro de 2026 tem 4 segundas e 4 quintas, ou seja **8** execuções agendadas:

    X = 8 x 3.121 = 24.968 EECU-s/mês  =  0,69% da alocação

### 3.3 O custo do replay, com o X medido

A operação processa cada data **mais de uma vez** e o replay a processa **uma**.
A janela é de seis dias (`start = hoje - 5`, `end = hoje + 1`, e `filterDate` é
semiaberto), e as execuções são segunda e quinta. Contando, para cada dia da
semana, quantos dias-de-execução caem em `[D, D+5]`:

| D | seg | ter | qua | qui | sex | sáb | dom | média |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| execuções que a alcançam | 2 | 1 | 2 | 2 | 1 | 2 | 2 | **12/7 = 1,71** |

Logo o replay de um intervalo custa **1/1,71 = 0,585** do que a operação gastou
naquele mesmo intervalo — e essa razão não precisa saber quantas datas existem,
o que é justamente a sua vantagem: as duas passam pelo mesmo conjunto de datas
disponíveis.

    2026-01-01 .. 2026-08-30           = 242 dias = 7,95 meses
    operação naquele intervalo          = 7,95 x 24.968  ~ 198.500 EECU-s
    REPLAY, uma passagem                = 198.500 / 1,71 ~ 115.800 EECU-s
                                        = 3,2% de um mês de alocação

| cenário | EECU-s | % de um mês |
| --- | --- | --- |
| uma passagem do replay | ~115.800 | **3,2%** |
| duas passagens | ~231.600 | 6,4% |
| uma passagem com erro de **10x** | ~1.157.900 | **32%** — ainda cabe |

**Confirmação independente:** a reconstrução da baseline v2 custou 122.783
EECU-s, e o replay estimado é **0,94x** disso. Um trabalho real, já pago, de
escala comparável.

### 3.4 As duas correções, e por que a segunda também estava errada

| estimativa | insumo | resultado |
| --- | --- | --- |
| §1, 08/09 | `SEARCH_DAYS_BACK = 16`, X não medido | 1,75 X, ~6% de um mês |
| `PHASE_3_2026-09-08.md` §3 | janela **5** (correto), X ≈ o uso da baseline | 5,6 X, ~19% de um mês |
| **aqui**, 09/09 | janela 6 dias medida, **X medido** | **3,2% de um mês** |

A primeira correção estava certa no que corrigiu: a janela é 5 dias
(`config/settings.py:53`), não 16. **Mas a magnitude que ela publicou estava
errada por outro motivo:** ela usou os 3,41% do projeto `ee-araripe-baseline-v2`
como proxy do consumo da detecção. Medido agora, a detecção consome **0,69%**, ou
seja o proxy era **4,9x alto** — a baseline é um trabalho muito mais pesado por
mês do que a detecção.

**E a frase que a §1 diz e que a primeira correção declarou morta volta a
valer:** *"mesmo com uma margem de erro de 10x continua caber num mês"*. Com
32%, cabe.

### 3.5 As ressalvas que continuam de pé

- **O mecanismo do replay não é o da operação.** A operação puxa com
  `getDownloadURL` em tiles; o replay exporta com `Export.image.toDrive`. O
  compute do composto domina e é o mesmo, mas os dois não foram medidos lado a
  lado.
- **O custo por data não é constante.** Mais cenas por data — nuvem,
  sobreposição de datatakes — custa mais. A razão de 0,585 usa uma média
  implícita, e o intervalo do replay inclui a estação chuvosa.
- **A Phase 4 faz mais que detecção**: anotações versionadas do MapBiomas, tiers
  de persistência, subconjuntos fortes, estatísticas e série temporal. Parte
  disso é local, não GEE.
- **A Phase 5 pode forçar um segundo replay**, e pelos números acima isso
  continua confortável.
- **A baseline já foi paga** e não entra nesta conta.

### 3.6 Nada mais é ação do dono nesta conta

A linha *"o que ainda precisa ser medido, e é ação do dono"* da §1 está
**fechada**. Não há mais X.
