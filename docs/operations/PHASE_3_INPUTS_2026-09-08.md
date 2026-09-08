# Insumos da Phase 3 — cota de GEE e data de corte

**Escrito:** 2026-09-08, a pedido do dono, antes de a Phase 3 começar
**Status:** insumos medidos e uma recomendação. **A Phase 3 é quem registra a
decisão** — este documento existe para ela não rederivar as medições.

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
