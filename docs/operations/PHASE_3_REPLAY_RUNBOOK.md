# Runbook do replay de 2026 — e os alvos resolvidos

**Escrito:** 2026-09-08, na Phase 3
**Base verificada:** `origin/main` em
`c39c5238d8e939f6a37bc9060ea5c9ec6da8bd3e`
**Estado da revisão do dono:** **PENDENTE** — ver §7. O bullet do roadmap pede
uma revisão explícita antes do cutover, e ela é ação do dono, não do agente.

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

### 2.1 Qual baseline o replay usa — decisão do dono, científica

O congelamento registra as duas gerações e **não escolhe**
(`baseline.replay_generation.decided = false`). As duas estão carregáveis pelo
runtime desde a Phase 3; o replay escolhe por `--baseline-version`.

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

**A decisão é do dono porque é científica**, e porque é contra a geração
escolhida que o ano inteiro será comparado. Um candidato comparado contra a
referência errada não fica obviamente errado — fica plausível.

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
2. **Escolher a baseline** (§2.1) e registrar a escolha e o porquê.
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
   --baseline-version <escolhida> --persistence-mode rebuild
   --state-path <caminho isolado> --out-dir <caminho isolado>`.
   **`--persistence-mode rebuild` exige `--state-path` explícito e isolado** —
   o modo `live` recusa datas mais antigas, que é exatamente o que um replay
   faz.
6. **Montar e publicar em staging**, sem promover o ponteiro final:
   `assemble_green_run.py` → `stage_green_run.py` → `publish_green_release.py`.
7. **Reconciliar** e deixar o candidato em staging. **Não promover.**

**A produção azul continua rodando durante tudo isso.** O roadmap é explícito:
*"do not pause current automation for the long rebuild"*. Um freeze curto de
escrita azul só é permitido na janela de cutover da Phase 6.

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

**Atenção ao ler o lado do lote da fila.** Ele diz
`is_authoritative_for_phase_4: false` de propósito: a fonte de observação sem
credencial é o banco de série temporal, que é o produto **azul** e só conhece as
datas que o azul processou. A Phase 4 enumera do GEE e verá mais.

## 7. A revisão do dono — pendente

O bullet do roadmap pede *"an explicit pre-cutover review of the runbook and
resolved targets"*. Isto é o que precisa da sua assinatura, e **nada abaixo
disto está decidido**:

- [ ] os alvos resolvidos da §1 estão certos;
- [ ] **qual baseline o replay usa** (§2.1) — a recomendação técnica é 2.1.0, e
      o custo dela está dito por inteiro;
- [ ] a regra do corte da §2.2, e a aceitação de que a data resolve na hora;
- [ ] o procedimento da §3, incluindo que a produção azul continua rodando;
- [ ] a divergência de unidade de composição da §8 é da Phase 4 e não bloqueia
      a Phase 3.

Registre a revisão como um bloco datado neste arquivo, ou num
`docs/implementation/PHASE_3_REVIEW_<data>.md`. Sem ela o cutover não começa.

## 8. Uma divergência medida, e ela é da Phase 4

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
