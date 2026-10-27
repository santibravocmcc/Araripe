# Phase 6 — o registro da virada

Registro de 2026-10-27, executando
[`PACKAGE_P6_CUTOVER_RECORD_PROMPT.md`](../operations/PACKAGE_P6_CUTOVER_RECORD_PROMPT.md)
§3 — o passo C5 da
[folha](../operations/PHASE_6_CUTOVER_RUNSHEET.md). Base: backend
`origin/main` em `c62980b58adb2fe8e4d23d97a2e4d3308650625b` (a `#133`,
registro `PHASE_6ZO`); site `origin/main` em `aa3a859`.

**Escritas do agente:** só esta documentação. Nenhuma lane disparada, nenhum
`wrangler`, nenhuma chamada à API da Cloudflare, nenhuma credencial, nenhum
purge.

**Como cada identificador foi lido.** Os registros `PHASE_6Z` a `PHASE_6ZO`
serviram de índice de onde procurar; cada número abaixo foi relido hoje na
ferramenta que o produz: `gh pr view` (estado, `mergedAt`, `mergeCommit`),
`gh run view` (workflow, evento, conclusão, criação, jobs, log),
`gh api …/commits/<sha>/check-runs` (o build do Workers Builds), `git
rev-parse`/`git show --stat` nos dois repositórios, e `curl` só-GET com o UA
de um Chrome real no domínio final. Os IDs de release foram relidos no log da
run que os escreveu (publicação ou rollback) e no log do status seguinte. O
que só o painel da Cloudflare mostra — a versão do Worker de B0, o clique do
C3 — **não foi relido**: o agente não tem credencial de control-plane, e está
marcado como "lido pelo dono".

## 1. O estado de partida — o §1 do briefing

| conferência | resultado |
| --- | --- |
| `PHASE_6ZO` na `main` | presente em `c62980b` |
| `gh workflow list --all` | `detect_gee.yml` `disabled_manually`; as outras 14 `active` |
| último run de `detect_gee.yml` | ainda `39255074543` (`schedule`, 2026-10-19T12:49:31Z, `failure`) |
| **rodada verde de segunda 2026-10-26** | depósito `40322184487` (`schedule`, criado 12:23:37Z; `detect`, `deposit`, `heartbeat` `success`), janela 2026-10-20..2026-10-25 exclusiva, continua `ci-39769440334`, 20 cenas → 3 datatakes em 2 datas. Publicação `40323697203` (`workflow_run`; `gate`, `stage`, `promote`, `context`, `sources` `success`): ponteiro **seq. 24** `rel-g3-ee52a1f2361f0976f40163a87b6fb7fd59b1fba730db8bacd503ef000c4a35c4` (o log nomeia `sequence 23` → `sequence 24`) |
| status mais recente | `40378162474` (`schedule`, 2026-10-26T18:29:19Z) `success`; **as sete linhas `ok` no log**: `alerts.shown`/`alerts.observed` 2026-10-24 em `rel-g3-ee52a1f2…` (seq. 24); `deposits.unpublished` nada espera (cabeça `ci-40322184487`); `automation.latest`/`last_success` 2026-10-26T12:35:06Z `ci-40322184487`; `context` `ctx-g1-cdbc6719…` seq. 6; `sources` `src-g1-242279d5…` seq. 5 |
| o site seguiu o ponteiro | `green_site_rebuild.yml` `40331259271` (`schedule`, 13:31:03Z) → commit `3085838` `deploy(verde): reconstruir para release=rel-g3-ee52a1f2…`, Workers Builds check run `121603934815` `success` 13:36:52Z. Ao vivo, 2026-10-27T12:40:21Z: `/data/green/current.json` `sequence` 24 com esse `release_id`; `/data/alert-index/built-from.json` com o mesmo `release_id` e `ctx-g1-cdbc6719…` |
| **robô do site de terça 2026-10-27** — o "Depois" do C4 que faltava | `update-data.yml` `40497194139` (`schedule`, criado 11:34:42Z, `headSha` `3085838`) `success`, **um job só**, `chuva`. Commit `aa3a859` `chore: atualizar chuva (2026-10-27)`, 6 arquivos (`freshness/chuva.json`, `chuva-historico.json`, dois PNG de 10-26, `rain/manifest.json`, um `.tif` do MERGE) — **nenhum sob `public/data/alerts/`** (`git show --stat`). O commit automático anterior, `3085838`, também não traz nenhum. `git ls-tree` da `main` do site: os 42 arquivos rastreados de `public/data/alerts/` seguem lá, intocados |
| `r2.dev` de `araripe-cogs` | `site-full/run-2026-01-02.geojson` → `401` (12:40Z); o C3 continua fechado |

Nenhum `late`, nenhum `broken`, nenhuma rodada verde falhada: o registro pode
fechar.

## 2. Fase A — preparação

| passo | data | PR / merge | run | a leitura que fechou o "Depois" |
| --- | --- | --- | --- | --- |
| A1 decisões D0–D6 | 2026-10-13 | `Araripe#116`, merge `e2d6ebcbcef26a521abea6531c388e80df3bbafd` (16:31:16Z) | — | a folha §3 com o bloco "DECIDIDAS": D0 = (a), D1 = 1, D2 = 1 dia, D3 = 12:00 UTC, D4 = 1, D5 = virar e medir, D6 a marcar no A11 |
| A2 rota no Worker de produção | 2026-10-13 | `site#48` (rascunho; mesclada no B1); registro `Araripe#117` | — | `wrangler dev` local da configuração de produção, `env -i` e `HOME` vazio: só `/data/green/current.json` muda; mutação 12/12 (`PHASE_6ZA`) |
| A3 verificador versionado | 2026-10-13 | na mesma `site#48` | — | contra a configuração de produção local, 53/53 PASS; três adulterações derrubam cada uma a sua checagem (`PHASE_6ZA`) |
| A4 rebase do site | 2026-10-13 | `site#47` mesclada pelo dono, `a0c3390` (17:11:40Z); `#42` → `e2a33f5`, `#21` → `ab65a55`; registro `Araripe#120` | — | `git merge-tree` limpo nas duas; `test:worker` 240/240 com as três empilhadas (`PHASE_6ZC`) |
| A5 agenda verde | 2026-10-13 | `Araripe#118` (rascunho; mesclada no B6); registro `Araripe#119` | — | `pytest` 2840 → 2909; 25 mutações derrubadas (`PHASE_6ZB`) |
| A6 `FONTE_PADRAO` verde | 2026-10-13 | `site#49` (rascunho; mesclada no B5); registro `Araripe#121` | — | `test:worker` 251/251, build ok sobre `#48`+`#42` (`PHASE_6ZD`) |
| A7 robô sem `alertas` | 2026-10-14 | `site#50` `ad710d8` (rascunho; mesclada no C2); registro `Araripe#122` | — | o YAML só com `chuva`, seis mutações derrubam (`PHASE_6ZE`) |
| A8 chave local revogada | 2026-10-14 | registro `Araripe#123` | status `38559580150` (`workflow_dispatch`, `failure` só por `automation.latest late`) | o profile local `Unauthorized` às 11:51:46Z; a chave do Environment leu tudo (`PHASE_6ZF`) |
| A9 fila drenada | 2026-10-14 | registro `Araripe#124` | status `38560897858` (`failure`, só `late`); depósito `38561001665`; publicação `38562453035` → seq. 19 `rel-g3-b19132638d911f28ab8c711b68cd848849b57e5f679d373a34191285281e63fa`; status `38567568460` `success` | as sete linhas `ok`, `alerts.observed` 2026-10-12 (`PHASE_6ZG`) |
| A10 ensaio na borda (opcional) | — | **não executado** | — | com D0 = (a), o B1 foi essa checagem |
| A11 revisão pelo dono | 2026-10-14 | registro `Araripe#125` | status `38568924312` `success` | *"1. Sim"*; o dia marcado: 2026-10-14 (`PHASE_6ZH`) |

## 3. Fase B — a virada, em 2026-10-14

Registro do dia: `PHASE_6ZI`, `Araripe#126`
(`4f9097b2e87120925f6f48e205b1117d0c485dd3`).

| passo | PR / merge | run / check run | a leitura que fechou o "Depois" |
| --- | --- | --- | --- |
| B0 fotografia | — | status `38573085048` `success`, seq. 19 `rel-g3-b1913263…` | **lido pelo dono no painel, não relido:** versão em produção do Worker `observatorio-chapada` `3d910ec8`; o hostname público de `araripe-cogs` `pub-5eb389cffff54421916187be69dd659b.r2.dev` |
| B1 rota no domínio final | `site#48` (head `b518bb0`), merge `11d1b65` (14:35:16Z) | Workers Builds `115914515813` `success` 14:37:16Z | o token do Workers Builds aceitou o binding de R2 (o não medido do A2); `/data/green/current.json` `200` `no-store`; verificador 54 PASS + 1 FAIL **do próprio verificador** (§5) |
| B2 índice composto e reconciliador | `site#42` (head `ec92808`, `COMPOR = True`), merge `198be57` (14:57:28Z) | Workers Builds `115929141305` `success` 15:05:51Z; `green_site_rebuild.yml` `38586402108` `success` | `built-from.json` = `rel-g3-b1913263…` + `ctx-g1-5b1ac5a0…`, o do ponteiro; `em_dia` |
| B3 ensaio de rollback | — | histórico `38586517253`; rollback `38593878442` (log: seq. 19 → 20, `rel-g3-76601bbf1637b777c954f0e5496e6af4b245ae3fdfb9c2114a2a99694a154d00`); reconciliador `38594820364` → `91bffea`, build `115961353848` 16:09:04Z; volta `38595685474` (seq. 20 → 21, `rel-g3-b1913263…`); reconciliador `38596477365` → `a5bdad5`, build `115968563063` 16:23:40Z; status `38597782742` seq. 21 | a página mostrou o quadro de atualização e reconstruiu a cada movimento; ~6 min por movimento com disparo manual |
| B4 o que só o navegador responde | — | — | visão completa típica: mediana 26 MiB, 25 de 47 acima de 25 MiB; a maior (26/06) 27,9 MiB transferidos em ~26 s; `?download=1` nomeia pelo caminho; nenhum `Access-Control-*`; 375 px sem rolagem lateral |
| B5 **o público vê o verde** | `site#49` (head `008a27d`), merge `1978b15` (16:28:45Z) | Workers Builds `115974799054` `success` 16:36:27Z | sem parâmetro, as três páginas no verde, nenhum pedido a `r2.dev` nem a `/data/alerts/`; `?dados=azul` no azul de 30/08 |
| B6 agenda verde | `Araripe#118`, merge `17cae38d3d9f1e4fd82508f2f1ee9fba2b827511` (16:50:52Z) | ver §4 | **quatro runs lidos, não presumidos**, só na segunda 2026-10-19 (`PHASE_6ZK`, `Araripe#128`): a primeira rodada (10-15) não tinha imagem (`PHASE_6ZJ`, `Araripe#127`) |

## 4. As rodadas agendadas desde o B6

| rodada | depósito (`schedule`) | publicação (`workflow_run`) | ponteiro | status seguinte |
| --- | --- | --- | --- | --- |
| qui 2026-10-15 | `38724054754`, `deposit` `skipped` (janela de um dia, sem datatake) | `38724206864`, o `gate` não promoveu | seq. 21 (igual) | `38770513231`, sete `ok` |
| seg 2026-10-19 | `39251503748` | `39253009226`, `stage`/`promote`/`context`/`sources` `success` | seq. 22 `rel-g3-0a788e76c5bde9398bafecb0884a1ac72fd7e7e9a9a81b18e3c4205496574ff9` | `39303347681`, sete `ok` |
| qui 2026-10-22 | `39769440334` | `39770767242`, os cinco jobs `success` | seq. 23 `rel-g3-7b69385c7da8bd75390be0e97b7cacec7b10d2b50c534eeeba6bf800c3d74ef0` | `39989359677` (10-23), sete `ok` |
| seg 2026-10-26 | `40322184487` | `40323697203`, os cinco jobs `success` | seq. 24 `rel-g3-ee52a1f2361f0976f40163a87b6fb7fd59b1fba730db8bacd503ef000c4a35c4` | `40378162474`, sete `ok` |

Três promoções seguidas sem clique, cada uma seguida pelo reconciliador do
site. Estas rodadas **não** contam para o C6: a vigia começa depois deste
registro (briefing §3).

## 5. Fase C — desligar o azul

| passo | data | PR / merge | run / check run | a leitura que fechou o "Depois" |
| --- | --- | --- | --- | --- |
| C1 agendamento azul parado | 2026-10-19 | registro `Araripe#129` | último run azul `39255074543` (`failure`) | `gh workflow disable` às 23:03:30Z; `disabled_manually`, as outras 14 `active`; **relido hoje:** nenhum run de `detect_gee.yml` depois de `39255074543` (`PHASE_6ZL`, `PHASE_6ZM` §1) |
| C2 robô azul do site parado | 2026-10-22 | `site#50` (head `ad710d8`), merge `e0bd263` (18:04:09Z); registro `Araripe#130` | Workers Builds `120000739557` `success` 18:12:07Z; `update-data.yml` `39942866107` (10-23) | o robô de sexta com um job só, `chuva`, `success`, nenhum `R2_` no log (`PHASE_6ZN` §2). A página de chuva **não** atualizou — achado à parte (§7) |
| C3 `r2.dev` de `araripe-cogs` fechado | 2026-10-23 | — (clique do dono no painel); registro `Araripe#131` | status `40107863057` (10-24), sete `ok` | um objeto conhecido `200` → `401` (16:52:19Z → 16:59:33Z); **relido hoje:** `401` (`PHASE_6ZN`) |
| C4 alertas fora do git do site | 2026-10-24 | `site#21` (head `50de81a`), merge `e8dcdc2` (18:33:25Z); registro `Araripe#133` | Workers Builds `120954776891` `success` 18:40:41Z; `update-data.yml` `40497194139` (10-27) | a página padrão abre a data mais recente; **lido hoje:** o primeiro commit do robô depois do C4, `aa3a859`, não traz arquivo sob `public/data/alerts/` (§1) |
| C5 este registro | 2026-10-27 | a PR deste documento | — | `git show origin/main:docs/implementation/PHASE_6_CUTOVER_2026-10-27.md`, depois do merge |

## 6. Achados que mudaram a folha no caminho

Cada um está no bloco "Feito em …" do passo; juntos aqui porque o padrão se
repete — **uma checagem escrita antes do dia que passaria pelo motivo
errado, ou que envelheceu sem mudar de palavra**:

- **A5 — a promoção não lê a conclusão do depósito.** Uma rodada sem
  aquisição termina `success` com o job `deposit` `skipped`; o `gate` lê o
  job da tentativa que disparou (`PHASE_6ZB`). Provado ao vivo em 10-15.
- **A8 — o status falhou por outro motivo.** A run `38559580150` foi
  `failure` só por `automation.latest late` (nenhuma agenda antes do B6),
  não por credencial; ler o log, não a conclusão (`PHASE_6ZF`).
- **B1 — o FAIL era do verificador.** Ele pedia `X-Araripe-Context-Id` ao
  documento `context/context.json`, que o vetor serve sem esse header; o
  arnês local rodava `--sem-contexto` e não pegava. Corrigido na `site#51`
  (rascunho, `ddf2599`, **ainda aberta**) — `PHASE_6ZI` §3.
- **C3 — o "Depois" passaria pelo motivo errado.** `curl -sI …/site-full/`
  já era `404` antes do clique (é um prefixo, não um objeto); a prova certa é
  um objeto conhecido, `200` antes e `401` depois (`PHASE_6ZN` §3).
- **C4 — o "Antes" envelheceu sem mudar de palavra**, de `alertas.js` para
  `alertas-fonte.js` (`PHASE_6ZC` §3); e **o teste-alarme da `#21`**, que
  falhava de propósito desde o B5, virou `test_a_pagina_padrao_le_o_verde`,
  derrubado por três mutações (`PHASE_6ZO` §3).
- **B6 — a primeira rodada não provou a promoção.** Sem imagem na janela de
  um dia, o C1 esperou a segunda 2026-10-19 (`PHASE_6ZJ` §2).

## 7. Achado lateral: a chuva presa em 10-13 — lida hoje

Não é passo da virada (briefing §2). Diagnóstico em
[`PHASE_6_CHUVA_PRESA_2026-10-23.md`](PHASE_6_CHUVA_PRESA_2026-10-23.md)
(`Araripe#132`): o *build output cache* do Workers Builds restaurava a cópia
de 10-13 por cima do checkout (§5a, log lido pelo dono); o dono desligou o
build cache em 2026-10-24.

**A prova que o `PHASE_6ZO` §6 pedia, lida hoje:** o robô de terça
`40497194139` commitou `aa3a859`; Workers Builds `122182905579` `success`
12:15:35Z; às 12:40Z o domínio serve `/data/territorio/rain/manifest.json`
com `last` = `2026-10-26` e `/data/freshness/chuva.json` com `run_id`
`40497194139` — **apareceu sem clique**, com `cf-cache-status: HIT` (o cache
da borda não atrapalhou). Antes dele, o rebuild de `3085838` (10-26) também
não regrediu. O build cache deve continuar desligado.

## 8. O que ficou aberto

| item | estado | dono do item |
| --- | --- | --- |
| **C6** duas semanas de vigia | começa agora; briefing [`PACKAGE_P6_WATCH_PROMPT.md`](../operations/PACKAGE_P6_WATCH_PROMPT.md) | próxima sessão |
| **D4** a aba "Séries" | a série na `main` parou em 2026-09-07 (`5574b1f`, `#30`); com `detect_gee.yml` desligado, nada a atualiza. A página diz a data. Série verde = pacote logo depois | pacote próprio |
| **D5** visão completa pesada | medida no B4 (mediana 26 MiB); o aviso de tamanho antes de baixar é pacote do site | pacote do site |
| `site#51` | rascunho aberto (`ddf2599`): o verificador ao vivo corrigido | dono mescla quando quiser; não muda o que roda |
| a frase da automação | *"ela aparece aqui quando for publicada"* envelhece depois da promoção (`PHASE_6ZK` §5) | pacote pequeno do site |
| a chuva | a correção vale (§7); fica a observação dos PNG iguais com `max_mm` 13,8 (`PHASE_6_CHUVA_PRESA` §6) e o `404` de `figures/rain-2026-04-24.png` na página inicial, anterior à virada | quem mexer na chuva |
| os 42 arquivos de `public/data/alerts/` | rastreados e implantados, servem `?dados=azul`; **não apagar**, e nenhuma história reescrita | fora da Phase 6 |
| `STAGING_LIMITER` | declarado e não aplicado (folha §8) | quando a forma do tráfego for conhecida |
| Phase 5 | nenhuma afirmação de acurácia até o relatório | Phase 5 |

## 9. Volta

Nada a desfazer: só documentação. A tabela de volta da virada é a folha §7;
depois de C3, voltar ao azul é B5 ao contrário **e** C3 ao contrário, e o azul
continua congelado em 2026-08-30.

## 10. Próximo

C6: duas semanas de vigia. Briefing:
[`PACKAGE_P6_WATCH_PROMPT.md`](../operations/PACKAGE_P6_WATCH_PROMPT.md).
