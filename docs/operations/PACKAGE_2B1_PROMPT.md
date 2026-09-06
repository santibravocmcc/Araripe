# Package 2B.1 — the prompt for the next session

**Written:** 2026-09-06, after Package 2A.6 closed.
**Base:** `origin/main` at `58f5bb8` — **not** the science branch.

Paste section 3 verbatim into a fresh session. Sections 1–2 explain the two
things that make this package different from the last one, so the executor
does not have to rediscover them.

## 1. Why the base is `main`, and what that means

Phase 2A and Phase 2B are parallel tracks. All the Package 2A.6 work lives on
`claude/phase2a6d-mapbiomas` and is **not merged to `main`**. Package 2B.1 is
publication and workflow-safety work, and it belongs to the `main` lineage,
where Package 2B.0 already installed the green lanes and the broker.

Practical consequence: on `main` the full gate is **131 passed**, not the 842
of the science branch. The v2 baseline, the seasonal regimes and the Phase
2A.5 v2 artifacts do not exist there and are not this package's business.

## 2. Four things already measured, so the executor need not

Read these as findings, not assumptions — each was verified on 2026-09-06.

**a. The R2 state helper fails OPEN, not closed.** `scripts/r2_state.py`
wraps its download in a bare `except Exception` that prints "primeira
execução?" and continues. An authentication failure, a network error, a
truncated download or a corrupt object is therefore indistinguishable from a
genuine first run — and the pipeline proceeds with an empty state, which
silently resets `n_sightings`, `first_seen` and `last_seen` for **every**
track. That is the exact scientific corruption the first roadmap bullet
targets. The `put` path is quieter still: a missing local file prints a
warning and exits 0.

**b. `detect_gee.yml` has no `concurrency:` block at all.** The green lanes
installed by 2B.0 (`araripe-green-candidate`,
`araripe-green-promotion`, `araripe-cloudflare-green-control`) all declare
`cancel-in-progress: false`; the blue detection lane declares nothing, so two
overlapping runs can interleave their R2 state read-modify-write.

**c. The documented cadence does not match reality.** The workspace
`AGENTS.md` states "backend detection runs Mon/Thu 06:00 UTC and the site
refresh Tue/Fri 06:00 UTC — a deliberate 24 h gap". The actual crons are
backend `0 6 * * 1,4` and site `30 7 * * 1,4` — the same days, **90 minutes
apart**, not 24 hours. Whichever is intended, the fixed offset is the thing
the third roadmap bullet replaces with a validated release signal, and the
drift between the instruction file and the workflows must be resolved
explicitly rather than silently.

**d. Rainfall is chained to alerts, not independent.** In the site repository
the `chuva` job declares `needs: alertas`, so any alert-side failure skips
the rainfall refresh entirely, and neither job carries a freshness state.
That is the fourth bullet.

## 3. The prompt

**NEXT SESSION MODEL: Opus 5**
**EFFORT: high**

*Why this pairing.* Three of the four scope items are judgment-heavy on a
small code surface, which is the shape that rewards a strong model rather
than a long search. Distinguishing a genuine first run from an
authentication, network, or corruption failure is a subtle correctness
problem whose wrong answers are both silent and production-affecting; the
concurrency work is interaction reasoning across blue and green lanes; and
the cadence discrepancy is a design decision with a live schedule attached.
Only the fourth item (splitting the site's alert and rainfall jobs) is
mechanical. High effort rather than max: the file surface is tiny —
`scripts/r2_state.py` is about fifty lines and the rest is YAML — so the
gain is care per decision, not breadth of search. The package is also
production-adjacent (`detect_gee.yml` runs on a real schedule against real
R2 state and is **not** idempotent), which is the usual reason to keep the
stronger model rather than economise.

*Session shape.* One session is enough: the roadmap sizes this at 25k–40k
and there is no hours-long external wait like the Earth Engine exports. Be
reachable near the end — item 3 needs an owner call on whether the
instruction file or the crons are wrong, and item 2's blue-lane change needs
approval before merge.

> Continue o Observatório da Chapada do Araripe com o **Package 2B.1 — State
> safety and workflow coordination**, a próxima fatia da Phase 2B.
>
> **Base.** Comece de `origin/main` (hoje `58f5bb8`), **não** da branch
> científica: todo o Package 2A.6 vive em `claude/phase2a6d-mapbiomas` e não
> está mesclado. Crie `claude/phase2b1-state-safety` a partir de
> `origin/main` e confirme o hash de 40 caracteres antes de editar. Na `main`
> o gate completo é **131 passed** — essa é a sua base, não 842.
>
> **Leia integralmente antes de agir:** `AGENTS.md` e `CLAUDE.md` do
> workspace e dos **dois** repositórios (`Araripe/` e `site/`);
> `ROADMAP.md` (Package 2B.1, Package 2B.0, e o gate P2B);
> `docs/implementation/PHASE_2B0_2026-08-11.md`;
> `docs/operations/GREEN_CONCURRENCY_LANES.md`;
> `docs/operations/RESTRICTED_CLOUDFLARE_BROKER.md`; e a skill
> `araripe-safe-handoff`.
>
> **Escopo — os quatro itens do roadmap:**
> 1. **Falhar fechado no estado do R2.** Hoje `scripts/r2_state.py` falha
>    *aberto*: um `except Exception` nu trata falha de autenticação, erro de
>    rede, download truncado e objeto corrompido como "primeira execução",
>    e o pipeline segue com estado vazio — o que zera `n_sightings`,
>    `first_seen` e `last_seen` de **todas** as tracks em silêncio. Distinga
>    ausência genuína (primeira execução) de falha, valide o objeto baixado
>    (parse, schema, contagem) e falhe fechado no resto. O `put` também
>    precisa deixar de sair 0 quando o arquivo local não existe.
> 2. **Coordenação de concorrência.** `detect_gee.yml` não declara
>    `concurrency:` alguma. Dê à lane azul um grupo próprio com
>    `cancel-in-progress: false`, mantendo as lanes verdes do 2B.0
>    (`araripe-green-candidate`, `araripe-green-promotion`,
>    `araripe-cloudflare-green-control`) separadas e o lock serializado único
>    para a promoção condicional do ponteiro verde. Um replay verde longo não
>    pode bloquear os schedules azuis inalterados. Atualize
>    `docs/operations/GREEN_CONCURRENCY_LANES.md`.
> 3. **Trocar o offset fixo de relógio por um sinal de release validado.**
>    Atenção: o `AGENTS.md` do workspace diz "Mon/Thu 06:00 UTC" no backend e
>    "Tue/Fri 06:00 UTC" no site, com folga deliberada de 24 h, mas os crons
>    reais são `0 6 * * 1,4` e `30 7 * * 1,4` — mesmos dias, 90 minutos de
>    diferença. **Resolva essa divergência explicitamente** (corrigindo o
>    documento, os crons, ou ambos, com justificativa registrada) e substitua
>    a dependência temporal por um sinal que o site *valide* antes de
>    publicar, em vez de presumir que o backend já terminou.
> 4. **Alertas e chuva independentes.** No repositório `site/` o job `chuva`
>    declara `needs: alertas`, então qualquer falha do lado dos alertas pula a
>    chuva inteira, e nenhum dos dois carrega estado de frescor. Dê a cada um
>    execução, retry e estado de frescor próprios, sem corrida de push.
>
> **Fronteiras duras.** A `main` do backend é **pull-request-only** (ruleset
> com bypass vazio): nunca faça push direto, nunca adicione ator de bypass,
> nunca mexa em configuração do repositório para contornar. Trabalhe em
> branch e **abra PR — não faça merge**. Alterações em workflow azul
> (`detect_gee.yml`), no Worker `observatorio-chapada`, no bucket
> `araripe-cogs`, no domínio, DNS, rotas, ponteiros canônicos ou em qualquer
> credencial exigem **aprovação humana explícita**: prepare, explique o
> impacto e espere. Produção segue congelada nas Fases 2B–5. Nada de escrita
> em R2 de produção, nada de dispatch de workflow, nada de tocar o broker ou
> os GitHub Environments. Preserve `claude/phase2b0-green-isolation` e
> `codex/technical-review-roadmap`.
>
> **Armadilhas já pagas — não redescubra.**
> (a) `detect_gee.yml` **não é idempotente**: um re-run manual infla
> `n_sightings` no `persistence_state` do R2. Nunca dispare só para testar.
> (b) Em runner, `ee.Initialize(project=...)` **ignora**
> `GOOGLE_APPLICATION_CREDENTIALS`; use `ee_initialize()` de
> `src/acquisition/gee_download.py`, que já tem a precedência canônica. Esse
> bug passou por dois PRs porque a credencial interativa local mascara a
> falha.
> (c) Existe um **secret** `EE_PROJECT`, mas os workflows leem
> `vars.EE_PROJECT` — namespaces diferentes. O secret é peso morto e um
> override por ele passaria sem efeito.
>
> **Trabalho entre repositórios.** Valide o backend primeiro, depois o site.
> Mantenha commits, validação e histórico separados por repositório; nunca
> inicialize Git no diretório-pai comum. Reporte falhas pré-existentes em
> separado.
>
> **Ao final:** testes fail-closed e determinísticos para cada item (em
> especial a distinção ausência-genuína × falha no estado do R2), rode
> `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` (**base 131 passed**
> na `main`), commits coerentes por repositório, crie
> `docs/implementation/PHASE_2B1_<data>.md`, confirme árvore limpa, abra o(s)
> PR(s) sem mesclar, e termine com o estado do gate **P2B** — dizendo
> explicitamente o que ainda falta nele.
>
> **Não inicie** o Package 2B.2, a Phase 3 nem o replay 2026.

## 4. State this package inherits

- Package 2A.6 is closed on `claude/phase2a6d-mapbiomas` (commit `5237da0`);
  the P2A implementation gate is closed. None of it is on `main`, and 2B.1
  does not need it.
- Baseline `2.1.0` exists locally and is **not** published: its R2 placement
  belongs to Package 2B.3 and its runtime activation to the replay packages.
  Runtime `BASELINE_VERSION` stays `1.0.0`.
- The monthly ESA reprocessing watch is live on `main`
  (`.github/workflows/esa_reprocessing_watch.yml`) and is unrelated to this
  package.
- Package 2B.2 owns the manifest, ledger and atomic publication; its gate
  cannot close until the Package 2A.6 producer/consumer integration passes.
