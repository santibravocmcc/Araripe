# Runbook do replay de 2026 — e os alvos resolvidos

**Escrito:** 2026-09-08, na Phase 3
**Base verificada:** `origin/main` em
`c39c5238d8e939f6a37bc9060ea5c9ec6da8bd3e`
**Baseline do replay:** **DECIDIDA em 2026-09-09 — `2.1.0`**, registrada em
[`../../config/phase3_replay_baseline_decision_v1.json`](../../config/phase3_replay_baseline_decision_v1.json).
Ver §2.1.
**Revisão pré-cutover do dono:** **FEITA em 2026-09-18** — ver §7 e
[`../implementation/PHASE_3_REVIEW_2026-09-18.md`](../implementation/PHASE_3_REVIEW_2026-09-18.md).
Nenhum item PENDENTE aqui; os portões 2 e 3 da Phase 6 seguem fechados e são
capacidades, não revisões.
O bullet do roadmap pede a revisão *antes do cutover*, então ela **não** bloqueia
a Phase 4; bloqueia a Phase 6.

Este documento é o procedimento da Phase 4 (o reprocessamento) e da drenagem da
fila na Phase 6, com os alvos resolvidos por nome. Ele não autoriza nada: as
Fases 4, 5 e 6 têm os seus próprios portões.

---

## 1. Os alvos resolvidos

Lidos do código, não de memória. `tests/test_replay_freeze.py` falha se um
destes nomes mudar no código e não aqui.

| o quê | valor | onde vive |
| --- | --- | --- |
| bucket de staging (verde) | `araripe-v2-staging` | `src/publication/conditional_store.py` |
| bucket de produção (azul, **congelado**) | `araripe-cogs` | idem |
| ponteiro verde | `pointers/green/current.json` | `src/publication/green_release.py` |
| projeto GEE da detecção | `ee-araripe` | `.github/workflows/detect_gee.yml` |
| projeto GEE da baseline | `ee-araripe-baseline-v2` | `scripts/build_baseline_v2_gee.py` |
| lane do ensaio | `v2_candidate_replay.yml` (`workflow_dispatch` só) | `.github/workflows/` |
| Environment de staging | `v2-staging` (sem revisor, política `main`) | backend |
| Environment de promoção | `v2-promotion` (sem revisor) | backend |
| Environment de control-plane | `cloudflare-green-control` (**com revisor humano**) | backend |
| congelamento das versões | `config/phase3_replay_freeze_v1.json` | backend |
| fotografia | `docs/implementation/PHASE_3_SNAPSHOT_2026-08-30.json` | backend |
| fila pós-corte | `docs/implementation/PHASE_3_POST_CUTOFF_QUEUE_2026-08-30.json` | backend |

**O repositório do site não tem Environment nenhum.** Não nomeie um: o GitHub
cria o que for nomeado, sem proteção e sem política de branch.

## 2. As duas decisões que precedem a Phase 4

### 2.1 Qual baseline o replay usa — DECIDIDA: `2.1.0`

**Decidida pelo dono em 2026-09-09.** Perguntado *"qual referência o recálculo
usa — a antiga ou a nova"*, respondeu **"a nova"**, seguindo a recomendação
técnica desta seção com o custo dela declarado.

A decisão está registrada em
`config/phase3_replay_baseline_decision_v1.json`, com autorização datada, e o
congelamento a **lê** dali em vez de a repetir — `build_freeze` valida que a
versão nomeada é uma geração **registrada** e que a autorização existe, então
um erro de digitação ou a `2.0.0` superada falham fechado.

**Decidir o replay não moveu o default do azul.** `BASELINE_VERSION` em
`config/settings.py` continua `1.0.0`, o arquivo de decisão declara
`blue_default_change_permitted: false`, e
`tests/test_replay_freeze.py::test_decidir_o_replay_nao_move_o_default_do_azul`
exige que os dois valores continuem diferentes e ambos gravados. A produção
congelada resolve `1.0.0` sem argumento; o replay nomeia `2.1.0`.

O que segue é a comparação que sustentou a recomendação. As duas gerações estão
carregáveis pelo runtime desde a Phase 3; o replay escolhe por
`--baseline-version 2.1.0`.

Medido, e é o insumo da decisão:

| | 1.0.0 | 2.1.0 |
| --- | --- | --- |
| grade, extent, 72 nomes | **idênticos** | **idênticos** |
| rasters em comum (SHA-256) | **0 de 72** | **0 de 72** |
| `valid_fraction` | menor nos 72 | **maior nos 72** (+0,51 a +0,82 pp) |
| procedência | `partial` — IDs de cena, task IDs e os 12 checksums de export **não** retidos | `complete` — 10 classes de procedência retidas |
| contrato de composição | ausente | `coverage-ranked-first-valid-v1`, escopado por datatake |
| dispersão | "standard deviation" | **população**, computada em float64 |
| plataformas observadas | não registradas | S2A, S2B, S2C, com política fail-closed |
| profundidade de contribuição | não registrada | por índice e mês |
| status | `accepted_audit_generation` | `rebuilt_candidate_generation` |

**Recomendação técnica: 2.1.0.** Ela é a única que satisfaz o que a Phase 4
exige de si mesma — *"verify acquisition/scene IDs, coverage, checksums, daily
reconciliation, and artifacts before accepting each batch"* — porque a 1.0.0
não retém IDs de cena nem os checksums de export, e o gate P4 pede exatamente
esses. A troca também não é um reprojeto: mesma grade, mesmo extent, mesmos 72
nomes.

**O que a recomendação custa, dito por inteiro.** A 2.1.0 admite produtos
pré-Collection-1 nos meses 1-4 (regime `wet-season-mixed-lineage-v1`), que a
ESA ainda está reprocessando; quando esse reprocessamento chegar, o regime é
para ser retirado e a estação chuvosa reconstruída. Ou seja: **um replay contra
a 2.1.0 pode ter de ser refeito para janeiro-abril.** A vigilância existe
(`scripts/check_esa_reprocessing.py`). A Phase 5 já podia forçar um segundo
replay de qualquer forma, e a cota não é o limitante.

**A decisão foi do dono porque é científica**, e porque é contra a geração
escolhida que o ano inteiro será comparado. Um candidato comparado contra a
referência errada não fica obviamente errado — fica plausível.

**O custo foi aceito com a decisão**, e está no próprio arquivo dela
(`accepted_cost`): pode ser preciso refazer janeiro-abril quando o
reprocessamento da ESA alcançar a estação chuvosa. A razão de aceitar: a Phase 5
podia forçar um segundo replay de todo modo, e a cota **não** é o limitante —
uma passagem custa ~3% de um mês de alocação, medido em
[`PHASE_3_INPUTS_2026-09-08.md`](PHASE_3_INPUTS_2026-09-08.md) §3.

### 2.2 A data de corte — regra, resolvida na hora

Registrada em `src/replay/cutoff.py`:

> O corte é a última data UTC que o ledger declara plenamente terminal no
> momento em que a consulta da Phase 4 é emitida, **resolvida e fixada como
> data literal no registro daquela execução**.

Chame `resolve_recorded_cutoff(terminal_dates=…, asked_at_utc=…)` e grave o
literal. Ele falha fechado com conjunto terminal vazio.

**Data provisória da Phase 3: `2026-08-30`**, lida de
`data/timeseries/RELEASE.json` (`latest_observation`). É a que o sistema
declara avaliada. Ela serve ao ensaio e à fotografia — **não** é o corte da
Phase 4.

O corte é **inclusivo do lado do lote**: a própria data do corte é replayada, e
só datas estritamente posteriores vão para a fila.

## 3. O procedimento da Phase 4

Não rode nada disto na Phase 3.

1. **Confirmar o congelamento.** `pytest -q tests/test_replay_freeze.py`. Se
   cair, uma constante congelada mudou: descubra qual antes de processar.
2. **A baseline já está escolhida e registrada** (§2.1): `2.1.0`. Confirme que
   o congelamento a lê — `baseline.replay_generation.version` — e não a
   redecida.
3. **Re-exportar os compositos** com o datatake físico:
   `python3 build_detection_gee.py --project ee-araripe --start 2026-01-01
   --end <corte+1 dia>` em Cloud Shell. Ele escreve dois documentos: o
   `araripe_detection_acquisitions.json` de sempre e o
   `araripe_detection_run_manifest_v3.json` novo, com uma entrada por datatake
   físico e o `run_manifest_id` derivado.
4. **Resolver o corte** (§2.2) contra o ledger dessa execução e fixar o
   literal.
5. **Processar em lotes cronológicos limitados**, com estado isolado:
   `python scripts/run_detection_from_gee.py --in-dir <dir>
   --baseline-version 2.1.0 --persistence-mode rebuild
   --state-path <caminho isolado> --out-dir <caminho isolado>`.
   **`--persistence-mode rebuild` exige `--state-path` explícito e isolado** —
   o modo `live` recusa datas mais antigas, que é exatamente o que um replay
   faz.
6. **Montar e publicar em staging**, sem promover o ponteiro final:
   `assemble_green_run.py` → `stage_green_run.py` → `publish_green_release.py`.
7. **Reconciliar** e deixar o candidato em staging. **Não promover.**

**A instrução do roadmap é não pausar a automação azul pelo rebuild** — *"do
not pause current automation for the long rebuild"* — e ela foi cumprida: nada
deste procedimento pausou o azul, e um freeze curto de escrita azul só é
permitido na janela de cutover da Phase 6.

> **Correção de 2026-09-17: a produção azul NÃO está rodando, e não foi este
> procedimento que a parou.** Este parágrafo abria com uma afirmação no
> presente sobre a automação azul estar ativa — citada na íntegra na tabela do
> diff da §7, que é o único lugar deste documento onde ela pode aparecer — e
> ela deixou de ser verdade. `detect_gee.yml`
> falha em **quatro** execuções agendadas consecutivas — 2026-09-10, 2026-09-14
> e 2026-09-17, com `LegacyPersistenceStateError`, mais 2026-09-07 por outra
> causa. A última escrita em produção foi a execução **manual** de 2026-09-07
> 15:15 UTC. A causa é o landing do Package 2A.6 (`#54`): a `main` passou a
> trazer um loader que recusa por contrato o estado vivo, que é de geração
> anterior. Medido e explicado em
> [`PHASE_4C_2026-09-16.md`](../implementation/PHASE_4C_2026-09-16.md) §11.
> **O conserto é o cutover, não um patch** — o estado de geração nova que a
> exceção exige é o que a Phase 4 depositou em staging.

## 4. Recuperação de falha

Ensaiado e provado em `tests/test_replay_rehearsal.py`; o comportamento é do
`src/publication/atomic_publish.py`.

- Uma publicação que morre no meio **deixa a release anterior viva e completa**.
  O manifest sai por último, então um prefixo sem manifest é visivelmente
  inacabado, e o ponteiro só se move no fim.
- **Republicar é seguro e converge.** A identidade da release é derivada do
  ledger, então a retentativa reencontra byte a byte o que já saiu (`unchanged`)
  e cria só o que faltava. Nada é sobrescrito: cada objeto sai com
  `If-None-Match: *`.
- Uma falha de precondição **não se retenta**: a decisão por trás daquela
  escrita foi tomada sobre uma versão que já não está viva.

## 5. Reversão de ponteiro

    python -c "from src.publication.atomic_publish import rollback"  # via a lane

- `rollback` carrega a release alvo **do store**, revalida o ledger inteiro e
  verifica cada objeto declarado **antes** de mover o ponteiro.
- A `sequence` do ponteiro conta **escritas** e só cresce, inclusive na
  reversão. Qual dado é mais novo é outra pergunta, respondida por
  `coverage.last_observed_on`. Conflatar as duas é a armadilha: um replay de uma
  janela antiga é uma escrita mais nova de dado mais velho.
- `promote` recusa mover para cobertura estritamente mais antiga; **`rollback` é
  a única maneira de ir para trás, e é deliberada.**
- Nada é apagado. Um objeto superado fica como tombstone no ponteiro.

## 6. Drenagem da fila pós-corte (Phase 6)

1. Ler `docs/implementation/PHASE_3_POST_CUTOFF_QUEUE_<data>.json` — e o
   documento equivalente que a Phase 4 gravar com o corte resolvido.
2. Semear o processo agendado a partir do watermark reconstruído.
3. Drenar as datas enfileiradas pelo contrato incremental de cinco dias
   (`SEARCH_DAYS_BACK = 5`, cadência seg/qui).
4. Cada data drenada entra numa release posterior. **A release anterior não é
   tocada** — provado no ensaio.

**A fila registrada na Phase 3 tem 0 datas**, porque a última data do banco de
série temporal É a data provisória do corte. Ela cresce enquanto as Fases 4 e 5
correm, a ~2 datas observadas por semana.

> **Atualização de 2026-09-17.** A Phase 4 re-enumerou do GEE e a fila **não é
> vazia**: **3** datas — `2026-09-02`, `2026-09-04`, `2026-09-07`
> ([`PHASE_4B_2026-09-09.md`](../implementation/PHASE_4B_2026-09-09.md) §9). O
> 0 da Phase 3 não estava errado, estava medido na fonte errada: o banco azul só
> conhece as datas que o azul processou. **E o 3 também já envelheceu** — foi
> enumerado sobre `2026-08-31..2026-09-10`, e essa janela fechou. Re-enumere no
> passo 1 em vez de reusar o número.

**Atenção ao ler o lado do lote da fila.** Ele diz
`is_authoritative_for_phase_4: false` de propósito: a fonte de observação sem
credencial é o banco de série temporal, que é o produto **azul** e só conhece as
datas que o azul processou. A Phase 4 enumera do GEE e verá mais.

## 7. A revisão do dono — reescrita contra o presente em 2026-09-17

O bullet do roadmap pede *"an explicit **pre-cutover** review of the runbook and
resolved targets"*. Pré-cutover: a revisão é portão da **Phase 6**.

> ### Por que esta lista foi reescrita antes de ser submetida
>
> Ela foi escrita em **2026-09-08**, e o mundo andou. Das quatro cláusulas que
> estavam abertas, **três deixaram de descrever o presente**: uma afirma um fato
> que hoje é **falso**, outra pergunta algo que a Phase 4 **já respondeu**, e uma
> terceira pede aceitação de uma **regra hipotética** que já virou **fato
> literal**. Pedir concordância com as frases antigas seria colher consentimento
> sobre um mundo que não existe — e uma checklist cujas cláusulas mudaram de
> verdade não é uma checklist, é uma armadilha de consentimento.
>
> O que mudou em cada uma, e a medição, está na tabela depois da lista.

### Fechados

- [x] **qual baseline o replay usa** (§2.1) — **`2.1.0`, decidida em
      2026-09-09**, com o custo aceito e registrado;
- [x] **a cota de `ee-araripe` está medida** — 3.600.000 EECU-s/mês, 0,17%
      usados; o replay é ~3% de um mês
      ([`PHASE_3_INPUTS_2026-09-08.md`](PHASE_3_INPUTS_2026-09-08.md) §3);
- [x] **a divergência de unidade de composição da §8** — **respondida pela
      Phase 4 em 2026-09-09**, não mais uma pergunta em aberto:
      `physical_datatake` / `datatake_mosaic-v1`, registrado em
      [`../../config/phase4_composition_unit_decision_v1.json`](../../config/phase4_composition_unit_decision_v1.json)
      sob delegação explícita (`PACKAGE_P4_REPLAY_PROMPT.md` §9). A segunda
      metade da §8 — se a transform da grade devia ser fixada — foi **medida em
      vez de suposta**: as grades **já alinham** (deslocamento de exatamente 42 e
      39 pixels de 20 m, todas as 10 719 × 4 909 coordenadas com correspondência
      exata), então a decisão é `do_not_pin_crs_transform`. Fixá-la é que mudaria
      pixels.

### Duas decisões do dono, tomadas em 2026-09-18, fecham dois destes

Registradas em
[`../../config/phase6_owner_decisions_v1.json`](../../config/phase6_owner_decisions_v1.json).
As seis do dossiê foram respondidas; **D1** e **D5** são as que tocam esta
lista, e as outras quatro abrem portões sem mudar cláusula nenhuma daqui.

> **A revisão em si continua PENDENTE, e isto não é formalidade.** O dono
> escolheu **quando** revisar — *"revisar agora"* — e isso não é uma afirmação
> de que as cláusulas abertas estão aceitas. Registrar uma resposta de
> **cronograma** como se fosse a revisão seria a imagem espelhada da armadilha
> que esta reescrita existe para evitar: fabricar consentimento a partir de um
> "sim" sobre outra pergunta. A revisão entra aqui quando o dono declarar a
> aceitação dos três itens abaixo.

### Confirmados pelo dono em 2026-09-18 — o portão 1 está FECHADO

Registro em
[`../implementation/PHASE_3_REVIEW_2026-09-18.md`](../implementation/PHASE_3_REVIEW_2026-09-18.md),
com a resposta literal *"3 itens confirmados"* sobre a lista **reescrita**.

- [x] **os alvos resolvidos da §1 continuam certos.** Reconferidos no código em
      2026-09-17, não herdados: `tests/test_replay_freeze.py` passa **55/55**, e
      é ele que cai se um nome mudar no código e não aqui. Os Environments foram
      relidos do GitHub na mesma data — backend tem três
      (`cloudflare-green-control` **com revisor**, `v2-promotion` e `v2-staging`
      **sem**), e o repositório do site continua com **`[]`**, nenhum.
- [x] **o corte é o literal `2026-08-30`, e o senhor revisa um fato, não uma
      regra.** Quando esta linha foi escrita, a §2.2 descrevia uma regra e a data
      era *provisória*. A Phase 4 **exerceu** a regra: `resolve_recorded_cutoff`
      tomou as datas terminais do ledger
      `pl-v3-af8d6c78fb2ad7fa15e40a47e631fd9596ece4b519c22b5fd6e6dccf731b4442` e
      fixou `2026-08-30` com `date_is_provisional: false`
      ([`PHASE_4B_2026-09-09.md`](../implementation/PHASE_4B_2026-09-09.md) §9).
      Resolveu para o mesmo valor que a Phase 3 tinha como provisório, e isso é
      coincidência de valor e não de método.
      **Ressalva medida em 2026-09-17:** a fila pós-corte de **3** datas foi
      enumerada sobre a janela `2026-08-31..2026-09-10`. Essa janela fechou há
      uma semana; a fila real de hoje é maior e **não está medida**. Ela é
      re-enumerada na drenagem (§6), não agora.
- [x] **o procedimento da §3 — e a premissa de que "a produção azul continua
      rodando" é FALSA.** Esta é a cláusula que mais mudou, e ela não pode ser
      aceita como estava escrita. Medido com `gh run list` em 2026-09-17:
      `detect_gee.yml` falha em **quatro** execuções agendadas consecutivas —
      2026-09-10, 2026-09-14 e **2026-09-17 (hoje)** com
      `LegacyPersistenceStateError`, além de 2026-09-07 por outra causa. A
      última escrita em produção foi a execução **manual** de 2026-09-07 15:15
      UTC (run `34137318406`), que publicou `latest_observation: 2026-08-30`.
      O procedimento da §3 em si continua correto — ele foi executado e fechou.
      O que caiu foi a sua última frase. Ver §3 e
      [`PHASE_4C_2026-09-16.md`](../implementation/PHASE_4C_2026-09-16.md) §11.
- [x] **(acrescentado em 2026-09-17, FECHADO em 2026-09-18 pela D5) o ponteiro
      verde vira público sem revisor e sem histórico durável.** Não estava na
      lista porque, quando ela foi escrita, isto era problema de sandbox. O
      cutover o transforma: o ponteiro passa a ser o que o site público segue.
      **Decidido: construir o histórico durável ANTES da virada** — o dono
      escolheu (i), e não a aceitação do risco por escrito.
      [`PROMOTION_IDENTITY_SETUP.md`](PROMOTION_IDENTITY_SETUP.md) já mandava
      revisitar — *"no cutover … a conta de um erro deixa de ser um sandbox"*.
      Medido no bucket em 2026-09-17: existem **7** releases e o ponteiro nomeia
      **2** (a atual `rel-g1-fb722b2d…` e `supersedes` → `rel-g1-24db9555…`,
      sequence 9). As outras **5** não são alcançáveis pelo store. Aceitar o
      risco por escrito ou construir o histórico antes é decisão sua.
- [x] **(acrescentado em 2026-09-17, FECHADO em 2026-09-18 pela D1) onde os
      dados da versão nova vivem depois do cutover.** **Decidido: promover
      `araripe-v2-staging`** a depósito canônico verde — zero bytes copiados,
      zero mudança de código — com a revogação de `claude-araripe-v2-staging-rw`
      como **último** passo, depois de a D5 estar construída e reprovada (a
      condição foi corrigida em 2026-09-18; ver o arquivo de decisão). Não estava na lista porque a pergunta não existia: a §1 já
      nomeia `araripe-v2-staging` como o bucket verde, mas
      [`CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md`](CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md)
      o governa como *"an object-level development sandbox … **not** a canonical
      release bucket, public bucket, or promotion target"* e manda revogar a
      credencial *"before repurposing the bucket"*. O cutover faria dele
      exatamente um bucket público. As opções e o custo medido de cada uma estão
      no dossiê de decisão desta fase.

### O diff desta reescrita, para o senhor ver o que mudou

| cláusula de 2026-09-08 | o que aconteceu com ela | evidência |
| --- | --- | --- |
| os alvos resolvidos da §1 estão certos | **mantida, e reconferida** | `pytest tests/test_replay_freeze.py` → 55/55, 2026-09-17; `gh api …/environments` nos dois repositórios |
| a regra do corte da §2.2, e a aceitação de que a data resolve na hora | **reescrita**: a regra virou fato literal `2026-08-30` | `PHASE_4B_2026-09-09.md` §9; ressalva nova sobre a fila de 3 estar medida numa janela vencida |
| o procedimento da §3, **incluindo que a produção azul continua rodando** | **reescrita — a premissa é falsa** | 4 falhas agendadas medidas com `gh run list`, a última hoje; `PHASE_4C_2026-09-16.md` §11 |
| a divergência de unidade de composição da §8 é da Phase 4 e não bloqueia a Phase 3 | **fechada** — a Phase 4 respondeu as duas metades | `config/phase4_composition_unit_decision_v1.json` |
| — | **acrescentada**: ponteiro público sem revisor nem histórico | 7 releases no bucket, 2 nomeáveis; `PROMOTION_IDENTITY_SETUP.md` §"quando isso deve ser revisto" |
| — | **acrescentada**: onde a versão nova mora de vez | `CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md` §Boundary e §Revocation |

**Atualização de 2026-09-18:** as duas cláusulas *acrescentadas* já fecharam,
pelas decisões D1 e D5 do dono. Restam **três**, e são as três originais que
foram mantidas ou reescritas.

A revisão está registrada em
[`../implementation/PHASE_3_REVIEW_2026-09-18.md`](../implementation/PHASE_3_REVIEW_2026-09-18.md).
**Sem ela o cutover não começa** — e ela está feita, o que fecha **um** dos
quatro portões. Os portões 2 (hostname do Worker verde) e 3 (Environment
protegido no site) continuam **fechados**, e a revisão não os abre. Ela nunca bloqueou o reprocessamento: *"a Phase 4 pode começar"* foi o
registro de 2026-09-08, e a Phase 4 começou e fechou em 2026-09-16.

## 8. Uma divergência medida — DECIDIDA pela Phase 4 em 2026-09-09

> **Esta seção descreve uma pergunta que já foi respondida.** Ela é mantida
> porque é o enunciado do problema, e a decisão se lê contra ele. As duas
> metades foram decididas em
> [`../../config/phase4_composition_unit_decision_v1.json`](../../config/phase4_composition_unit_decision_v1.json):
> a unidade de composição do replay é o **datatake físico**
> (`datatake_mosaic-v1`), porque o ledger v3 não tem linha honesta para a
> segunda aquisição de uma data; e a transform da grade **não** é fixada, porque
> as grades foram medidas e **já alinham**. Nada disso muda o runtime azul.

`CompositionRunV3` amarra `composite_method_id` a
`coverage-ranked-first-valid-v1` — composição escopada por **datatake**
(`src/detection/composition_run_v3.py:189`). O export de detecção mosaica a
**data** inteira sob `daily_mosaic-v1`.

Consequência prática: a identidade `acq-v3-…` que o ledger espera é a da
composição por datatake, e não a de um composto por data. Por isso o export
**não** pré-computa `acquisition_id` — ele enumera os datatakes físicos e deixa
a identidade ser cunhada por quem compõe. Um ID plausível que não casa é pior
que nenhum ID.

A Phase 4 tem de decidir qual unidade compõe. As duas opções existem no
código: `CompositionRunV3.compose_all` compõe por datatake a partir de bandas,
e o export por data já produz compostos prontos.

Relacionado, e da mesma natureza: o export pede só `crs` e `scale`, sem
`crsTransform`, então a sua origem é escolha do Earth Engine e **não** está
prometido que ela case com a grade da baseline. A evidência de que ninguém
assumiu alinhamento é o `reindex_like(..., method="nearest", tolerance=15)` em
`scripts/run_detection_from_gee.py`. Fixar a transform removeria aquele reindex
e mudaria pixels exportados — decisão da Phase 4.

## 9. O que NÃO fazer

- **Nunca disparar `detect_gee.yml` nem `update_data.yml` para testar.** Eles
  não são idempotentes e escrevem em produção.
- **Nunca escrever em `araripe-cogs`.** Congelado nas Fases 2B-5.
- **Nunca adicionar ator de bypass** ao ruleset "Protect main — pull requests
  only", nem mexer em configuração do repositório para restaurar push direto.
- **Nunca nomear um Environment que não existe.**
- **Nunca aceitar token direto de control-plane da Cloudflare.** O único
  caminho é uma operação já allowlistada no broker protegido, e a lista é
  exatamente `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Nunca apagar objeto real** sem aprovação humana explícita e nomeada. E
  desde que a Phase 5 virou publicação científica, isto deixou de ser prudência
  e virou requisito: um artigo cita **uma** release, que passa a ter de existir
  para sempre.
- **Não mesclar a PR draft `#21` do site** (parar de commitar os alertas) antes
  da Phase 6.
