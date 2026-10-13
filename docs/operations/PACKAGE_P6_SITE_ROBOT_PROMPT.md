# Phase 6 — tirar o job `alertas` do robô do site, escrito e não mesclado

Escrito em 2026-10-13, ao fim da sessão da PR que faz o público ver o verde
([`PHASE_6ZD`](../implementation/PHASE_6ZD_2026-10-13.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: é o passo A7 de
> [`PHASE_6_CUTOVER_RUNSHEET.md`](PHASE_6_CUTOVER_RUNSHEET.md) — uma PR no
> site que tira um job de um workflow e ajusta os testes que o prendem. Pouco
> código; o cuidado é não levar junto o job `chuva` nem o cron, e dizer na PR
> o que fica órfão. Nenhum merge na `main` do site — ela faz deploy de
> produção.

---

## 1. O estado de partida — confirme por conteúdo

    git -C site fetch origin && git -C site rev-parse origin/main
    gh pr list -R santibravocmcc/observatorio-site --state open --json number,isDraft,headRefName,baseRefName
    git -C site show origin/main:.github/workflows/update-data.yml | grep -n "^  [a-z]*:$\|cron"

- Ao fim da sessão anterior: `main` do site em `a0c3390`; abertas em
  rascunho `#48` (`95148a8`), `#42` (`e2a33f5`), `#21` (`ab65a55`) e `#49`
  (`6fc7491`, com base na `#42`). Nenhuma delas toca `update-data.yml`,
  `scripts/prepare_data.py`, `scripts/freshness.py`,
  `scripts/check_backend_release.py` nem `tests/test_update_data_workflow.py`
  (`git diff --stat origin/main...origin/claude/<branch>`, 2026-10-13): a `#42`
  e a `#49` só **acrescentam** `.github/workflows/green_site_rebuild.yml`.
  Então ramifique da `main` do site e abra a PR contra ela.
- Leia `site/AGENTS.md` inteiro antes de editar o site.
- Worktree próprio com caminho **absoluto**, e um worktree do backend na
  `main` dele ao lado (ou `ARARIPE_DIR`).
- Conte os testes do site na base antes de mexer: na `main` do site,
  `npm run test:worker` 223 e `pytest` 227 (`PHASE_6ZC` §1), com `python3`
  3.12 (§6).

## 2. O que já foi medido, para o executor não refazer

- **O workflow.** `update-data.yml` tem dois jobs, `alertas` e `chuva`, e o
  cron `0 6 * * 2,5`. O `alertas` roda `scripts/check_backend_release.py`,
  depois `python scripts/prepare_data.py alerts timeseries` — é **ele** que
  gera `public/data/timeseries/series.json` (D4) —, grava e confere
  `freshness` de `alertas`, e commita com laço de retry.
- **Ele já está vermelho, e é o portão funcionando.** Run `38405724207`
  (2026-10-13): `chuva` `success`; `alertas` `failure` em "Validar a release
  do backend antes de publicar" ("a última release do backend tem 35 dias
  (limite 10 …)") e em "Conferir frescor dos alertas" ("… há 28 dias …"). As
  quatro rodadas agendadas desde 2026-10-02 falharam igual. Não é defeito a
  consertar: o azul está parado desde 2026-09-03 e o portão recusa publicar
  por cima dele. Tirar o job é o que deixa o robô verde de novo.
- **Os testes que o prendem** (`tests/test_update_data_workflow.py` na
  `main` do site): `test_both_products_are_present`,
  `test_alerts_record_and_check_their_own_freshness`, os parametrizados de
  orçamento de frescor e de "último passo", e os dois do portão
  (`test_the_backend_release_is_validated_before_data_is_prepared`,
  `test_the_release_gate_reads_the_cloned_backend`). Mudam junto, e o
  `test_the_schedule_keeps_the_24h_gap_after_the_backend` continua.
- **O que fica órfão** quando o job sai: `scripts/check_backend_release.py`
  e o modo `alerts`/`timeseries` de `prepare_data.py` (só esse job os chama no
  `.github`); `public/data/freshness/alertas.json` (nenhuma página o lê —
  `git grep freshness -- src worker '*.html'` vazio). Recomendado: **não
  apagar** nada disso nesta PR — dizer na PR que ficou sem chamador, e deixar
  a limpeza para depois do C3, quando o azul sai do deploy.
- **A série congela** em `public/data/timeseries/series.json` (última data
  2026-08-30). A `#49` já faz a aba "Séries" dizer isso com a data lida do
  próprio arquivo; nada a fazer na página.

## 3. A tarefa

**Única tarefa: o passo A7 da folha — a PR do site que tira o job
`alertas` de `update-data.yml`, em rascunho, sem mesclar.**

1. Tirar o job `alertas` inteiro; o job `chuva`, o cron `0 6 * * 2,5`, o
  `workflow_dispatch` e a `concurrency` ficam intactos.
2. Os testes de `test_update_data_workflow.py` passam a prender o novo
  estado: o workflow tem **só** `chuva`; nenhum passo chama
  `prepare_data.py alerts`/`timeseries`, `check_backend_release.py` nem
  `freshness.py … alertas`. Leia o YAML pela estrutura (o teste já carrega o
  YAML), não por string; e a mutação que devolve o job tem de derrubar o
  teste.
3. `npm run test:worker`, `pytest` e `npm run build` verdes.
4. A PR em rascunho dizendo o que ficou órfão (§2), e o passo A7 da folha
  atualizado numa PR de docs do backend, com o registro da sessão e o próximo
  briefing (A8, ou o primeiro passo da folha que ainda não tiver bloco
  "Feito" — confira a folha na `main`).

**Fora de escopo:** mesclar qualquer PR (B1, B2, B5, C2, C4 — com o dono); a
série verde (pacote depois da virada, D4); apagar scripts ou dados do azul
(depois do C3); a `#21` (C4); a agenda (`#118`, B6).

## 4. Decisões de escopo já tomadas, com a base

- **Nada é apagado** — `PACKAGE_P6_PROMPT.md` §5. O azul continua no deploy
  até o C3.
- D0–D6 decididas pelo dono em 2026-10-13 (folha §3); D4 = 1: virar sem a
  série atualizada, com a data dita na página.
- A folga de 24 h entre o backend (Seg/Qui 06:00 UTC) e o robô do site
  (Ter/Sex 06:00 UTC) fica — `AGENTS.md` do workspace.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- A `main` do site faz deploy de produção: **nenhum merge**, nenhum push nela.
- Nenhum Worker implantado, nenhum `wrangler` com credencial (memória
  `wrangler-login-existe-isolar-home`: `env -i` e `HOME` vazio).
- Não dispare o `update-data.yml` à mão: ele commita na `main` do site.
- A `main` do backend é só por PR. Nenhum Environment criado ou
  reconfigurado.

## 6. Armadilhas já pagas — não redescobrir

- `node --test tests/` quebra no Node 25: use `npm run test:worker`.
- `pytest` do site: use `python3` 3.12 (`/opt/anaconda3/bin`). Com o 3.11 do
  env `araripe`, `test_o_centroide_usa_a_soma_compensada_do_python` falha
  também na base (`PHASE_6ZD` §1).
- Teste de workflow lê o YAML carregado (ou só linhas executáveis), nunca uma
  string que um comentário satisfaz.
- `git -C <repo> worktree add <caminho relativo>` cria o worktree **dentro**
  do repositório: caminho absoluto.
- O hook `commit-msg` do backend recusa SHA de 40 caracteres de outro
  repositório — no registro, SHA curto do site.
- `<<EOF` não citado executa os backticks do corpo: mensagem em arquivo e
  `git commit -F`.

## 7. Estado que o package herda

- `site#48` (A2+A3, para o B1), `site#42` (para o B2), `site#49` (A6, para
  o B5, com base na `#42`), `site#21` (para o C4): rascunho.
- `Araripe#118` em rascunho: a agenda verde (A5), para o B6.
- Ponteiro verde seq. 18 (107 datas até 2026-10-04); a fila de depósito
  desde 2026-10-05 cresce um dia por dia (A9 a drena na véspera).
- O azul parado desde 2026-09-03; o job `alertas` do robô do site vermelho
  desde pelo menos 2026-10-02 pelo portão de release — esperado até o C2.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. A mudança que faz o público ver o sistema novo está escrita, testada e
guardada sem publicar. A única coisa que não deu para ver na tela foi o
sistema novo com dados de verdade — as cópias locais tinham sido apagadas; os
testes cobrem, e o próprio dia da virada confere de novo.

### O que você precisa fazer

1. **Não mesclar as mudanças do site que estão em rascunho.** Cada uma tem o
   seu momento no roteiro da virada, com você.

Nada mais nesta semana.

### Tem algo preocupante?

Não. Achei uma página que continuaria mostrando o sistema antigo depois da
virada — a de dados abertos — e ela já foi incluída na mesma mudança.

### O que ainda falta no caminho

- **Desligar o robô antigo do site** — a próxima sessão, deixar escrito, sem
  publicar.
- **Revogar a chave local antiga** — com você.
- **Processar os dias acumulados**, na véspera.
- **A virada** — executar o roteiro, com a sua aprovação em cada passo que
  mexe no site público.
- **A série de índices do sistema novo** — um pacote logo depois da virada.
- **Fase 5** — a validação independente.
