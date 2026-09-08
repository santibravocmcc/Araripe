# Package 2A.6D — the current prompt

**Written:** 2026-09-06, after Packages 2A.6C and 2A.6C.1 closed.
**Base commit:** `8fb46d7` on `claude/phase2a6c-baseline`.

Paste section 2 verbatim into a fresh session. Section 1 explains what changed
against the older draft of this prompt, so the differences are auditable rather
than silent.

## 1. What the earlier draft got wrong

The prompt drafted before 2A.6C executed is now stale in eight ways. Each of
these would have sent the executor to the wrong state:

| Stale claim | Reality on 2026-09-06 |
|---|---|
| base commit `b398fe3` on `e87097e` | `8fb46d7`; the branch carries 2A.6C and 2A.6C.1 on top |
| `config/baseline_manifest_v2.json` is the live manifest | live manifest is `config/baseline_manifest_v2_1.json`, **baseline 2.1.0**; `..._v2.json` is the immutable 2.0.0 record |
| pre-condition "the GEE half of 2A.6C is complete" | complete, plus a seasonal-regime package (2A.6C.1) the draft never mentions |
| fallback to checkpoint `20260902T013734Z_...` | that checkpoint is closed and superseded; so is `20260905T183630Z_...` |
| test base `739 passed` | **818 passed** |
| read `PHASE_2A6C_2026-09-01.md` | also `PHASE_2A6C1_2026-09-06.md` and `PHASE_2A6C1_SEASONAL_REGIME_MAP.md` |
| Earth Engine capability is simply available | the project is in **noncommercial restricted mode**; quota resets on the 1st |
| (absent) | four Earth Engine behaviours were found the hard way and must not be re-learned |

## 2. The prompt

> Continue o Observatório da Chapada do Araripe com o **Package 2A.6D** — o
> fechamento do Package 2A.6.
>
> **Pré-condição dura.** O baseline rebuilt existe e valida: confirme que
> `config/baseline_manifest_v2_1.json` carrega por `load_manifest_v2` com
> `baseline_version == "2.1.0"`, que `require_baseline_v1_untouched()` passa, e
> que o gate `pytest -q` está em **818 passed**. Se qualquer um falhar, pare e
> reporte em vez de prosseguir.
>
> **Base.** Último commit de `claude/phase2a6c-baseline` (hoje `8fb46d7`). Crie
> `claude/phase2a6d-mapbiomas` a partir dele e confirme o hash de 40 caracteres
> antes de editar. **Não faça merge em `main` e não faça push sem pedir.**
>
> **Leia integralmente antes de agir:** `AGENTS.md` e `CLAUDE.md` do workspace e
> do repositório; `ROADMAP.md` (Package 2A.6 e exit gate P2A);
> `docs/decisions/PHASE_2A_SCIENTIFIC_DECISIONS_2026-08-11.md` (itens 6–10 do
> fechamento); `docs/implementation/PHASE_2A5_2026-08-09.md`,
> `PHASE_2A6C_2026-09-01.md`, `PHASE_2A6C1_2026-09-06.md` e
> `PHASE_2A6C1_SEASONAL_REGIME_MAP.md`; e a skill `araripe-safe-handoff`.
>
> **Capacidade Earth Engine.** Projeto `ee-araripe-baseline-v2`, autenticação
> interativa local do owner, `earthengine-api` 1.7.42 no env
> `/opt/anaconda3/envs/araripe`. Confirme que a credencial é refresh token de
> usuário (sem `private_key`, sem `client_email`) antes de qualquer query. Nunca
> use o service account de produção (`GEE_SA_KEY` / projeto `ee-araripe`) e nunca
> troque de projeto ou principal em silêncio.
> **Atenção à cota:** o projeto entrou em modo restrito não comercial em
> 2026-09-05. Modo restrito reduz throughput, não bloqueia, e a cota reseta no
> dia 1 de cada mês. Meça o tamanho do export da Collection 10.1 antes de
> disparar e, se for pesado, considere esperar o reset. Classifique a capacidade
> via `araripe-safe-handoff` antes de qualquer chamada; se indisponível,
> checkpoint imutável em `docs/handoffs/`.
>
> **Armadilhas do Earth Engine já pagas — não redescubra.** (1) Divisão por zero
> devolve `0`, não valor não-finito: teste denominadores explicitamente. (2)
> `ee.Reducer.frequencyHistogram` é não-determinístico nessa escala. (3) Duas
> reduções independentes do mesmo composto diferem em até 2 px — avalie
> identidades **por pixel** dentro de uma expressão e reduza depois; não use
> tolerância. (4) `system:time_start` é o instante do *granule*, não do datatake.
> Detalhes em `PHASE_2A6C_2026-09-01.md`.
>
> **Escopo exclusivo.** Verificar o fixture checksummado da legenda nacional e
> implementar os mapeamentos v2 exatos por coleção, a política de classes
> 0/27/255, o subset majoritário inclusivo de 50% por centro de pixel e o
> agregador interno de 60% para comparação apenas interna; exportar e
> checksummar o verdadeiro `classification_2024` da Collection 10.1 do asset
> oficial GEE sob o contrato de manifest travado (CRS/transform nativos da banda,
> sem argumento de escala conflitante, vizinho mais próximo, máscara como NoData
> 255); reconstruir o crop regional e regenerar todos os artefatos v2 do 2A.5
> vinculados ao checksum do registro de decisões (`ac61fd1e…`), preservando v1
> como audit-only; invalidar o crop Collection 10 rotulado 10.1 para uso de
> runtime e de revisão qualificada **sem apagar os bytes de auditoria**; travar
> drought desabilitado em todo entrypoint candidato com regressões; e fechar o
> gate de implementação do Package 2A.6 contra o exit gate P2A.
>
> **Nunca** apague detecções brutas nem o arquivo nacional MapBiomas existente.
>
> **Proibido:** escrever em R2; disparar workflows; tocar produção, blue
> schedules, Worker, buckets, domínio, DNS, rotas, site, broker, GitHub
> Environments ou qualquer credencial; modificar a baseline 1.0.0 ou os manifests
> 2.0.0/2.1.0; mudar `BASELINE_VERSION` de runtime; iniciar a Phase 3 ou o replay
> 2026. Preserve `claude/phase2b0-green-isolation` e
> `codex/technical-review-roadmap`. Identidades novas somente v3.
>
> **Ao final:** testes fail-closed e determinísticos, rode os focados e
> `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` (**base 818 passed**),
> um único commit coerente, crie `docs/implementation/PHASE_2A6D_<data>.md`,
> confirme árvore limpa e termine com o estado do exit gate P2A — dizendo
> explicitamente se ele fecha ou o que falta.

## 3. State this package inherits

- **Baseline 2.1.0**, `config/baseline_manifest_v2_1.json`, 72 objects,
  inventory `4a4c1d15…`, plan `9d76e992…`, three seasonal source regimes.
- Runtime `BASELINE_VERSION` is still `1.0.0`; activation belongs to the replay
  packages, not to 2A.6D.
- The v2 baseline is **local only**. Its object keys (`baselines_v2/2.1.0/`) are
  declared in the manifest but nothing has been uploaded; R2 placement belongs
  to Package 2B.3 and activation to the replay packages.
- The wet-season regime carries `mixed_lineage_pending_esa_reprocessing` and a
  retirement condition watched by `scripts/check_esa_reprocessing.py`; that is
  **not** 2A.6D's business.
- Open scientific question, still open and not for this package: whether a
  minimum contribution depth should gate detection. January is the shallowest
  month at 11.58M pixels below three contributions.
