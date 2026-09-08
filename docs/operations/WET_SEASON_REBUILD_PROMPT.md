# Retiring the wet-season regime: the complete rebuild prompt

**Purpose.** Baseline `2.0.0` admits pre-Collection-1 products for calendar
months 1–4 under the provenance state
`mixed_lineage_pending_esa_reprocessing`. That admission was always temporary.
When ESA finishes reprocessing those months onto the Collection-1 lineage, the
wet season should be rebuilt on that lineage alone and the regime retired.

**When to use this.** When
`.github/workflows/esa_reprocessing_watch.yml` opens the issue, or when
`scripts/check_esa_reprocessing.py` exits with status 9. Progress today
(2026-09-06) is 25–34% per wet month; the threshold is 90%.

**How to use this.** Paste section 3 verbatim as the prompt for a fresh
session. It is self-contained.

---

## 1. What the executor must know before it starts

The rebuild machinery already exists and is closed, tested and byte-stable.
This task **consumes** it. Nothing in `src/processing/scl_mask_v2.py`,
`composition_v2.py`, `gee_composition_v2.py` or `src/detection/identity_v3.py`
should change: `reviewed_baselines` is already a parameter of every one of
them, which is why seasonal regimes were implementable without touching the
accepted science.

Read `docs/implementation/PHASE_2A6C1_2026-09-06.md` and
`docs/implementation/PHASE_2A6C1_SEASONAL_REGIME_MAP.md` first. They record the
contract, the measurements behind every choice, and the Earth Engine
behaviours that must not be re-learned the hard way.

## 2. The four Earth Engine traps, already paid for

1. **Division by zero returns `0`, not a non-finite value.** The accepted
   policy makes a non-finite index *missing*, so every index denominator is
   tested explicitly and a zero denominator masked. Without this a degenerate
   pixel enters the median and the dispersion as a real observation of `0`.
2. **`ee.Reducer.frequencyHistogram` is non-deterministic at this region
   size** — repeated evaluation of one composite returned different totals.
   Contributor accounting uses exact integer indicator sums instead.
3. **Reduction totals are not pixel identities.** Two independently reduced
   sums over the same 54-megapixel composite differ by up to two pixels at tile
   boundaries. Evaluate every integrity identity *per pixel* inside one
   expression and reduce afterwards; then it is exact and needs no tolerance.
   Do not "fix" this with a tolerance — that path was tried and rejected.
4. **`system:time_start` is the per-granule instant**, spreading 0–26 s within
   one datatake. The acquisition timestamp is the datatake instant, recoverable
   without mismatch from `PRODUCT_ID` field 2 or `system:index` field 0.

Also verified: `ee.Reducer.stdDev()` is the population form the science
requires, and the median is exact at rebuild scale.

## 3. The prompt

> Retome o Package 2A.6 do Observatório da Chapada do Araripe (backend
> `Araripe/`) para **aposentar o regime sazonal da estação chuvosa** do baseline
> 2.0.0. Trabalhe na branch `claude/phase2a6c-baseline` (ou uma branch nova a
> partir dela). Não faça merge em `main` e não faça push sem pedir.
>
> **Contexto.** O baseline `2.0.0` está construído e validado
> (`config/baseline_manifest_v2.json`). Ele usa dois regimes de fonte: a estação
> seca (meses 5–12, só linhagem Collection-1, nuvem <40) e a chuvosa (meses 1–4,
> nuvem <60, admitindo também `02.11 02.14 03.00 03.01 04.00` porque a ESA ainda
> não havia reprocessado esses meses). O regime chuvoso carrega o estado
> `mixed_lineage_pending_esa_reprocessing` e uma condição de aposentadoria. O
> monitor `scripts/check_esa_reprocessing.py` indicou que essa condição foi
> atingida.
>
> **Leia integralmente antes de agir:** `AGENTS.md` e `CLAUDE.md` do workspace e
> do repositório; `docs/BASELINE_V2_EXECUTION.md`;
> `docs/implementation/PHASE_2A6C1_2026-09-06.md`;
> `docs/implementation/PHASE_2A6C1_SEASONAL_REGIME_MAP.md`;
> `docs/operations/WET_SEASON_REBUILD_PROMPT.md` (este documento, seções 1 e 2);
> `config/phase2a6c1_seasonal_source_regime_amendment_v1.json`; e a skill
> `araripe-safe-handoff`.
>
> **Capacidade Earth Engine.** Projeto `ee-araripe-baseline-v2`, autenticação
> interativa local do owner, `earthengine-api` no env
> `/opt/anaconda3/envs/araripe`. Confirme que a credencial é refresh token de
> usuário (sem `private_key`, sem `client_email`) antes de qualquer query. Nunca
> use o service account de produção (`GEE_SA_KEY` / projeto `ee-araripe`) e nunca
> troque de projeto ou principal em silêncio. **Verifique a cota antes de
> começar**: uma reconstrução consome bastante EECU e o projeto já entrou em modo
> restrito uma vez.
>
> **O que fazer.**
> 1. Rode `scripts/check_esa_reprocessing.py` e confirme a prontidão com números
>    reais, não com a suposição de que o gatilho estava certo.
> 2. Meça, **antes de decidir**, a cobertura e a profundidade que a estação
>    chuvosa teria só com Collection-1, no filtro de nuvem candidato. Espelhe o
>    pipeline real (mosaico por datatake, depois `count` entre datatakes); nunca
>    use `unmask(0)` numa máscara para isso — reprojetar 10 m para 20 m transforma
>    a máscara em fração e infla a cobertura. Compare contra o piso aceito de
>    `0.99` e contra a profundidade atual registrada no manifest.
> 3. Se a medição sustentar a aposentadoria: escreva uma nova emenda de regime
>    (o padrão está em `config/phase2a6c1_seasonal_source_regime_amendment_v1.json`)
>    em que a estação chuvosa passa a `collection1_lineage_stable`, com o filtro
>    de nuvem que a medição justificar, e uma revisão registrada nova se algum
>    valor novo precisar de admissão. **Não baixe o piso de cobertura** e não
>    imponha limiar de profundidade mínima — isso é decisão do owner e da Phase 5.
> 4. Reexporte **apenas** os meses cujo conjunto-fonte admitido mudou. Verifique
>    isso comparando os conjuntos por datatake e por cena, como o 2A.6C.1 fez: se
>    a estação seca ficar idêntica, os rasters dela não são refeitos.
> 5. Refaça a evidência e escreva um manifest novo. `write_manifest_v2` recusa
>    sobrescrever, então **mova** `config/baseline_manifest_v2.json` para um nome
>    de auditoria antes, ou escreva em caminho novo — o manifest anterior é
>    material de auditoria e não pode ser destruído.
> 6. Rode os testes focados e `pytest -q`, atualize o registro de implementação,
>    o ROADMAP e a memória, e faça commits coerentes.
>
> **Proibido:** escrever em R2; disparar workflows; tocar produção, blue
> schedules, Worker, buckets, domínio, DNS, rotas, site, broker, GitHub
> Environments ou qualquer credencial; modificar a baseline 1.0.0
> (`require_baseline_v1_untouched()` deve passar antes e depois); mudar
> `BASELINE_VERSION` para 2.0.0; iniciar o Package 2A.6D dentro desta tarefa.
> Drought permanece desabilitado.
>
> **Ao final**, reporte a distribuição de profundidade por índice e mês, e diga
> explicitamente se a aposentadoria melhorou ou piorou a profundidade em relação
> ao baseline atual — se piorou, pare e apresente a evidência em vez de
> prosseguir.

## 4. If the measurement says "not yet"

Retiring the regime is only worth it if the Collection-1-only wet season
clears `0.99` coverage **and** does not lose contribution depth against the
current mixed baseline. If it clears coverage but is shallower, that is a real
trade — surface it to the owner rather than deciding it. The current wet-season
depth to beat, from `config/baseline_manifest_v2.json`:

| Month | Coverage | Depth median | Pixels < 3 |
|---|---|---|---|
| 01 | 0.9991 | 4 | 11,582,430 |
| 02 | 1.0000 | 6 | 890,582 |
| 03 | 1.0000 | 6 | 553,965 |
| 04 | 1.0000 | 7 | 210,800 |

## 5. Running the watch without GitHub Actions

The workflow only runs once merged to `main`, because GitHub schedules
workflows from the default branch. To watch locally instead, run monthly from
the repository root:

```bash
/opt/anaconda3/envs/araripe/bin/python scripts/check_esa_reprocessing.py --json-out /tmp/esa_progress.json
```

Exit status `9` means ready. A `launchd` agent on macOS can run it on the first
of each month and post a notification; the script writes its full report to the
`--json-out` path either way.
