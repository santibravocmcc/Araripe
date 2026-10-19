# Phase 6 — a folha de execução da virada

Escrita em 2026-10-13, executando
[`PACKAGE_P6_CUTOVER_RUNSHEET_PROMPT.md`](PACKAGE_P6_CUTOVER_RUNSHEET_PROMPT.md).
Registro da sessão: [`PHASE_6Z_2026-10-13.md`](../implementation/PHASE_6Z_2026-10-13.md).

**Nenhum passo desta folha foi executado.** Ela é a lista, na ordem em que se
sustenta, do que muda o que o público vê; cada passo diz quem executa, a
aprovação que exige, o que conferir antes e depois, e como voltar atrás. Ela
substitui, como roteiro, as §4.2–§4.5 de
[`PACKAGE_P6_PROMPT.md`](PACKAGE_P6_PROMPT.md) — que continuam lá como
história; a §1 abaixo diz, item a item, o que delas envelheceu.

Base, lida com `git rev-parse origin/main` no dia:

- backend `fa87e6afd6e44ac2c9d33d5a921b508abfab2b5c`;
- site `afb2810` (SHA curto: o hook `commit-msg` recusa SHA de outro
  repositório).

**Fotografia de partida** — `v2_green_status.yml` disparada da `main`, run
`38406746950`, lida em 2026-10-13T13:39:48Z, só leitura:

| produto | estado | data | idade |
| --- | --- | --- | --- |
| `alerts.shown` | ok | 2026-10-04 | 9 d |
| `alerts.observed` | ok | 2026-10-04 | 9 d |
| `deposits.unpublished` | ok | 2026-10-04 | — (a cabeça cobre o que o ponteiro cobre) |
| `automation.latest` | ok | 2026-10-07T21:19:55Z (`no_acquisition`) | 5 d |
| `automation.last_success` | ok | 2026-10-07T21:19:55Z | 5 d |
| `context` | ok | `ctx-g1-dd374bac…` seq. 2 | — |
| `sources` | ok | `src-g1-c9dcba55…` seq. 1 | — |

O briefing previa a automação `late` a partir de 2026-10-13. Ela ainda era `ok`
com 5 dias: o limite é "mais de 5 dias inteiros", e a última tentativa terminou
às 21:19:55Z de 07/10, então ela vira `late` a partir de 2026-10-13T21:19:55Z.
É o aviso funcionando, não um defeito.

## Como ler um passo

Cada passo tem seis campos, sempre nesta ordem, e
`tests/test_phase6_cutover_runsheet.py` os exige:

- **Quem** — quem executa. "agente" = uma sessão do Claude; "dono" = só o dono.
- **Aprovação** — `nenhuma` (staging, leitura, branch, PR), ou `dono, explícita`
  (tudo que pode mudar o que o público vê, credencial, ou configuração do
  Cloudflare). Uma aprovação vale para **um** passo.
- **Antes** — o que tem de ser verdade para começar, e o comando que prova.
- **Faz** — a ação, uma só.
- **Depois** — a checagem, como comando ou leitura, nunca como frase.
- **Volta** — o caminho de volta, e quanto tempo leva.

Fronteiras que valem para a folha inteira, e não se repetem em cada passo:

- a `main` do site faz deploy de produção: **um merge lá é um deploy**;
- nenhum Environment é criado, renomeado ou reconfigurado por agente;
- `detect_gee.yml` e `update_data.yml` nunca são disparados;
- Claude não recebe credencial de control-plane da Cloudflare; o broker
  (`cloudflare_green_control.yml`) só fecha (`audit`,
  `enforce-worker-isolation`, `disable-site-branch-deploy`) e não ganha
  operação nova nesta virada;
- nada é apagado, em bucket nenhum;
- nenhuma afirmação de acurácia (Phase 5).

## 1. O que envelheceu nas §4.2–§4.5, conferido por conteúdo

| texto antigo | hoje | evidência |
| --- | --- | --- |
| §4.2: portão 2, o hostname do Worker verde, "mudança de broker mais mutação revisada" | **fechado em 2026-09-27, e sem mudança de broker** | o dono abriu o `workers.dev` no painel; 37/37 checagens ao vivo; fechado por `enforce-worker-isolation` (run `36324810625`) e `audit` (run `36324968583`) — `PHASE_6B_2026-09-27.md` |
| §4.2: as checagens ao vivo são contra o Worker verde | **têm de ser repetidas contra o domínio final**, e a rota ainda **não existe lá** | o Worker de produção não serve `/data/green/`: `site/wrangler.jsonc` na `main` não tem `r2_buckets` e `run_worker_first` é só `["/api/*"]`; `site/worker/index.js` não importa `data_route.js`. Já registrado em `PHASE_6M_2026-09-29.md` §7 e `PHASE_6U_2026-10-07.md` §6, e **nenhuma PR o constrói** (lacuna L1) |
| §4.3: portão 3, um Environment protegido no site, com revisor | **não é mais caminho**: o repositório privado no plano grátis não oferece revisor, e o dono tirou o token | `gh api repos/santibravocmcc/observatorio-site/environments/v2-green-deploy/secrets` → `[]` (só a variável `CLOUDFLARE_ACCOUNT_ID` ficou); o Worker verde é implantado só da máquina do dono (`site/scripts/green_worker.sh deploy GREEN-ONLY`) |
| §4.4.2: "`alertas.js` trocado de `pub-…r2.dev` para a rota" | **a troca já está escrita**: a página escolhe a fonte por `FONTE_PADRAO` em `src/js/alertas-fonte.js`, e o verde já lê tudo pela rota; a troca é **mudar uma constante** | `site#28`, `#37`, `#41`, `#46` mescladas; `FONTE_PADRAO = 'azul'` na `main` |
| §4.4: "`grep` por `r2.dev` no bundle construído" | **essa checagem falharia sempre**: com `FONTE_PADRAO` verde, `AZUL.fullBase` continua no bundle para `?dados=azul` | `git grep pub-5eb389 -- ':!docs' ':!*.md' ':!tests'` no site: só `src/js/alertas-fonte.js:46`. A checagem certa é de **rede**: a página padrão não faz requisição a `r2.dev` (passo B5) |
| §4.4, acréscimo de 2026-10-07: "`Araripe#102` mesclada antes" | **cumprido por outro caminho**: a `#102` deu lugar à `#109` (contexto como job da própria lane), e as fontes entraram igual na `#110` | `v2_operational_publish.yml` na `main` tem os jobs `stage,promote,context,sources` |
| §4.4, acréscimo de 2026-10-07: dois deploys, rota e depois `COMPOR = True` | **vale**, mas a `site#42` está **em conflito com a `main`** (`tests/alertas_fonte.test.mjs`) e com a `site#47` | `git merge-tree --write-tree origin/main origin/claude/p6-ordem-do-deploy` → conflito; 6 commits atrás |
| §4.4: `site#21` "depende do passo 2" | vale, e ela também está **em conflito** (`.gitignore`), 36 commits atrás | mesmo comando, branch `claude/phase2b4b-stop-committing-alerts` |
| §4.5: "promover atomicamente o ponteiro" | **feito e rotineiro**: ponteiro seq. 18, `rel-g3-76601bbf…`; o histórico durável existe (D5, `#70`/`#71`) | run `38406746950`; `PHASE_6Y` |
| §4.5: "semear o processo agendado a partir da marca-d'água reconstruída" | **a semente já está no bucket** e a cadeia já anda: a lane de depósito com `chain=head` continua da cabeça | `#76`–`#79`; cabeça `ci-37686447368` cobre até 2026-10-04 |
| §4.5: "processar as 3 datas da fila pós-corte" | **a fila do corte de 08/30 já foi processada** (a série verde vai até 2026-10-04). A fila de hoje começa em **2026-10-05** e cresce um dia por dia | `alerts.observed` = 2026-10-04 |
| §3, condição (2): revisor na promoção | **caiu** (dono, 2026-10-02): nenhuma publicação tem revisor; rollback no `v2-promotion`, só a pedido do dono | `config/phase6_publication_authority_v1.json`; `gh api …/environments`: `v2-promotion` só com `branch_policy` |
| §3, condições (1) e (3): revogar a chave local, reescrever `CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md` | **abertas**, e agora sem impedimento: a lane de depósito existe desde `#72`–`#75` | a nota no topo do documento diz "neither has happened yet" |
| §2b: o azul parado desde 2026-09-03 | vale; o robô do site falha no job `alertas` desde 02/10 | `PHASE_6P`; memória do projeto |

## 2. Lacunas que o texto antigo não tinha

- **L1 — o Worker de produção não serve `/data/green/*`.** Sem isso não há rota
  no domínio final, e nem `?dados=verde` funciona lá. É código do site
  (`worker/index.js` + `wrangler.jsonc`), e o merge é um deploy de produção.
  Ver a pergunta D0 para a alternativa.
- **L2 — nenhum verificador ao vivo está no repositório.** O de 2026-09-27
  viveu no scratchpad (`PHASE_6B` §6), e `verify_green_route_remote.sh` exige
  token da Cloudflare. A virada precisa de um verificador só-leitura,
  versionado, apontável para o domínio final, que use o `User-Agent` do cliente
  real (o de `site_artifact.py`) — a borda recusou `Python-urllib` com 403/1010.
- **L3 — `site#42`, `site#21` e `site#47` precisam ser rebaseadas** antes de
  qualquer merge da virada (§1).
- **L4 — a série temporal da aba "Séries" não tem produtor verde.** A página lê
  `/data/timeseries/series.json`, gerado pelo job `alertas` do robô do site a
  partir de `data/timeseries/timeseries.db` do backend, que só o
  `detect_gee.yml` (azul) escreve. A última atualização desse banco na `main` é
  `2026-09-07` (`chore: update time-series 2026-09-07 (#30)`). A lane verde
  grava linhas de série só numa base isolada (`PHASE_4B` §9). A ROADMAP §1.1 diz
  que série temporal tem de continuar automática. Pergunta D4.
- **L5 — o binding de R2 não tem modo só-leitura.** A documentação da
  Cloudflare: *"An R2 bucket is able to READ, LIST, WRITE, and DELETE objects"*
  pelo binding. Com L1, o Worker de produção passa a poder apagar no bucket que
  vira canônico; o limite volta a ser o código (`data_route.js` só lê). Não é
  pior que hoje — o token do Workers Builds já é de conta e implanta qualquer
  Worker, inclusive o verde, que tem o mesmo binding (inferido do escopo de
  conta, não medido) —, mas tem de estar escrito e aceito.
- **L6 — a agenda.** Nenhuma lane verde tem cron (Package 2B.0). Na virada:
  depósito, promoção, contexto, fontes, status e o reconciliador do site. Quem
  dispara a promoção é a pergunta D1; a agenda do status, D3; o limite (d),
  D2.
- **L7 — a fila desde 2026-10-05 cresce.** A janela automática da lane de
  depósito vai do dia seguinte à cabeça até `hoje − 1` (exclusivo), com no
  máximo 16 dias; uma fila maior anda em várias rodadas. Depositar e promover
  perto da virada (passo A9) mantém a primeira rodada agendada pequena.
- **L8 — o peso da visão completa** (até 89,1 MiB por data, medido na `rel-g1`
  em 2026-09-27; não remedido na `rel-g3`) é "decisão de produto da virada"
  desde a `PHASE_6M` §7 e ninguém a tomou. Pergunta D5.

## 3. Perguntas ao dono — cada uma com a recomendação

Nenhum passo de produção começa antes de D0–D5 estarem respondidas e
registradas no passo A1.

> **DECIDIDAS pelo dono em 2026-10-13 — todas as recomendações**, nas palavras
> dele: *"Pode anotar todas as suas recomendacoes."* Ficam assim:
> D0 = (a), o Worker de produção serve `/data/green/*`; D1 = 1, promoção
> encadeada por `workflow_run`; D2 = depósito pendente por mais de 1 dia é
> `late`; D3 = lane de status todo dia às 12:00 UTC, falhando em vermelho;
> D4 = 1, virar com a data da série dita na página e a série verde como
> pacote logo depois; D5 = virar como está e medir no passo B4; D6 = quarta
> ou sábado de manhã, dia exato a marcar no passo A11. Passo A1 feito.
>
> **D6 marcado pelo dono em 2026-10-14 (passo A11): o dia é hoje, quarta
> 2026-10-14**, a partir da manhã — nas palavras dele: *"Hoje estamos ainda
> numa quarta-feira de manhã. Nao conseguimos fazer isso hoje? Caso tenha
> algum empecilho, pode marcar para sab 17/10."* Reserva: sábado 2026-10-17,
> com o A9 repetido na sexta 2026-10-16.

**D0 — onde mora a rota no domínio final.**

| | (a) o Worker de produção serve `/data/green/*` (**recomendado**) | (b) uma rota de zona `observatoriodachapadadoararipe.com/data/green/*` → o Worker verde |
| --- | --- | --- |
| o que muda | `wrangler.jsonc` ganha o binding `STAGING_BUCKET` → `araripe-v2-staging` e `run_worker_first` ganha `/data/green/*`; `worker/index.js` encaminha o mount para `handleDataRoute` | uma rota no painel (dono); o Worker de produção não muda. A documentação diz que uma rota no hostname de um Custom Domain roda antes do Worker dele |
| deploy de código da rota | merge na `main` do site (Workers Builds) | só da máquina do dono (`green_worker.sh deploy GREEN-ONLY`) |
| broker | intocado | `audit` exige `route_count == 0` no Worker verde e **passaria a falhar**: precisa de mudança revisada no broker, em tarefa separada |
| autoridade sobre o bucket | quem empurra na `main` do site | na prática a mesma: o token do Workers Builds é de conta (L5) |

Recomendo (a): é o caminho que a `PHASE_6M` e a `PHASE_6U` já assumem, não
mexe no broker, e (b) não reduz de verdade quem alcança o bucket.

**D1 — quem dispara a promoção depois do depósito.**

1. **encadeada (recomendado)**: `v2_operational_publish.yml` ganha
   `workflow_run` sobre a conclusão da lane de depósito, roda só quando a
   rodada depositou, e promove `source=chain`. Nenhuma credencial nova: o job
   liga o `v2-promotion` ele mesmo, que só aceita a `main` — e `workflow_run`
   roda na branch padrão. Espera entre depósito e promoção: minutos.
2. agendada separada (ex.: Seg/Qui 09:00 UTC): o atraso medido do cron do
   GitHub (40 min a 12 h 10 min, `PHASE_6U` §2) não ordena nada; uma promoção
   que roda antes do depósito terminar espera até a rodada seguinte (~3,5 dias).
3. manual: contradiz a ROADMAP §1.1 (publicação de rotina sem aprovação
   humana).

**D2 — o limite (d) de 2026-10-10: quanto tempo um depósito pode esperar a
promoção.** Com D1.1, qualquer espera além da mesma rodada é falha.
Recomendo: **`deposits.unpublished` pendente por mais de 1 dia = `late`**.
Exige código (hoje esse produto não tem idade; `green_status.py`), no mesmo PR
da agenda (A5). Com D1.2, o limite teria de ser 4 dias.

**D3 — a agenda da lane de status, e o que ela faz quando um limite estoura.**
Recomendo: **todo dia às 12:00 UTC**, longe das 06:00 do depósito; ao
estourar, o run fica vermelho e o GitHub manda o e-mail de workflow agendado
que falhou (para quem editou o cron por último — a conta do dono). Nada se
conserta sozinho; o aviso público é só o "dados atrasados" da página, que
depende da data olhada (`site#47`).

**D4 — a aba "Séries" (L4).**

1. **virar sem ela atualizada, com a data dela dita na página (recomendado)**,
   e a série verde como pacote logo depois da virada;
2. construir a série verde antes da virada (atrasa a virada; a fila e o azul
   parado continuam correndo).

**D5 — a visão completa pesada (L8).** Recomendo virar como está e medir na
`rel-g3` no passo B4; se passar de 25 MiB numa data comum, avisar o tamanho
antes de baixar (pacote do site, depois).

**D6 — o dia.** Uma manhã de dia útil em que o dono esteja disponível por ~3 h
para os merges e o painel, **fora** de segunda e quinta (o depósito das 06:00
UTC estaria rodando) e fora de terça e sexta (o robô do site). Quarta ou sábado.

## 4. Fase A — preparação, sem mudar o que o público vê

### A1. Registrar as decisões D0–D6

- **Quem:** dono decide; agente registra.
- **Aprovação:** nenhuma (é registro).
- **Antes:** esta folha mesclada na `main` do backend: `git show origin/main:docs/operations/PHASE_6_CUTOVER_RUNSHEET.md`.
- **Faz:** PR no backend acrescentando à §3 desta folha a resposta datada de cada pergunta, com as palavras do dono.
- **Depois:** `git show origin/main:docs/operations/PHASE_6_CUTOVER_RUNSHEET.md | grep -n "DECIDIDA"` mostra D0–D6.
- **Volta:** nova PR com a decisão revista; nada executado depende só do texto.

### A2. A rota no Worker de produção (L1, se D0 = a)

> **Feito em 2026-10-13, não mesclado:** `observatorio-site#48` (rascunho,
> branch `claude/p6-rota-producao`, commit `95148a8`), junto com A3. É a PR
> que o passo B1 mescla. Medido localmente contra `wrangler dev` da
> configuração de produção, com `env -i` e `HOME` vazio: antes/depois
> idênticos em `/`, `/data/alerts/manifest.json` e `/api/chat` — só
> `/data/green/current.json` muda; mutação 12/12; `npm run test:worker`
> 216 → 225, `pytest` 227 → 247. **Não medido:** se o token do Workers Builds
> aceita o binding de R2 no deploy — o check de branch da PR passou, mas o
> comando de deploy de branch é `exit 0`, então ele não exercita o binding.

- **Quem:** agente.
- **Aprovação:** nenhuma para a PR; o merge é o passo B1.
- **Antes:** `git -C site show origin/main:wrangler.jsonc` sem `r2_buckets`; `tests/test_green_worker_config.py` passando.
- **Faz:** PR no site: `worker/index.js` encaminha `MOUNT` para `handleDataRoute(request, env.STAGING_BUCKET)`; `wrangler.jsonc` ganha `r2_buckets: [{ binding: "STAGING_BUCKET", bucket_name: "araripe-v2-staging" }]` e `run_worker_first: ["/api/*", "/data/green/*"]`; os testes de configuração passam a afirmar a nova forma (e que `/api/chat` e os assets não mudam).
- **Depois:** `CLOUDFLARE_LOAD_DEV_VARS_FROM_DOT_ENV=false` + `wrangler dev -c wrangler.jsonc` local (R2 simulado, sem credencial) com a fixture `tests/fixtures/green-bucket/`: `/data/green/current.json` 200 com `Cache-Control: no-store`, `/api/chat` igual, `/` e `/data/alerts/manifest.json` iguais; `npm run test:worker` e `pytest` verdes.
- **Volta:** fechar a PR.

### A3. O verificador ao vivo versionado (L2)

> **Feito em 2026-10-13, não mesclado:** na mesma `observatorio-site#48`.
> `scripts/verifica_rota_ao_vivo.py` só manda GET e HEAD — as recusas por
> método não são pedidas ao domínio público; estão nos vetores e no arnês
> verde. `scripts/verifica_rota_producao_local.sh` o prova contra a
> configuração de produção: 53/53 PASS, e três adulterações (sha256 do
> manifesto no ponteiro, um byte de um produto com mesmo tamanho, sha256 das
> fontes) derrubam cada uma exatamente a checagem que a nomeia. Nos passos B1,
> B3 e B5: `python3 scripts/verifica_rota_ao_vivo.py --base https://observatoriodachapadadoararipe.com/data/green/`.

- **Quem:** agente.
- **Aprovação:** nenhuma.
- **Antes:** a tabela de checagens de `PHASE_6B_2026-09-27.md` §2 e a lista de `GREEN_RETENTION_AND_MIGRATION.md` §5.
- **Faz:** `site/scripts/verifica_rota_ao_vivo.py --base <url>`: só GET/HEAD, com o `User-Agent` de `site_artifact.py`; confere `Content-Length` e `sha256` contra o manifesto, `no-store` no ponteiro, nenhum `Access-Control-Allow-Origin`, `?download=1` com nome do caminho declarado, `/data/green/sources.json` e `heartbeat.json`; sai 1 em qualquer falha.
- **Depois:** contra `wrangler dev` local: todas PASS; com o ponteiro da fixture adulterado: FAIL na checagem certa.
- **Volta:** fechar a PR.

### A4. Rebasear `site#47`, `site#42` e `site#21` (L3)

> **Feito em 2026-10-13, nada mesclado:** a `#47` mesclada pelo dono às
> 17:11 UTC; sobre a `main` do site em `a0c3390`, a `#42` foi de `f3c9c85`
> para `e2a33f5` e a `#21` de `d8c02c0` para `ab65a55` (`--force-with-lease`;
> o SHA anterior inteiro e o comando de volta estão no corpo do último commit
> de cada uma). As duas continuam rascunho, 0 atrás da `main`, e
> `git merge-tree` limpo. Registro:
> [`PHASE_6ZC_2026-10-13.md`](../implementation/PHASE_6ZC_2026-10-13.md).
> A `#42` ganhou três testes que prendem a recusa **sem** aviso de atraso e a
> abertura com data olhada velha **com** aviso. A `#21` teve o seu alarme
> reapontado: a base azul mudou de `alertas.js` para `alertas-fonte.js`, e o
> teste agora confere `FONTE_PADRAO = 'azul'` — ele **falha de propósito**
> depois do B5 (ver C4). As três branches juntas sobre a `main` (`#48`, `#42`,
> `#21`, nessa ordem): `npm run test:worker` 240/240, `pytest` 297, build ok.

- **Quem:** agente; o merge da `#47` é do dono.
- **Aprovação:** dono, explícita, só para mesclar a `#47` (inerte para o público: atrás de `?dados=verde`).
- **Antes:** `gh pr view 47 -R santibravocmcc/observatorio-site --json state` aberta; `git merge-tree --write-tree origin/main origin/<branch>` mostra o conflito.
- **Faz:** dono mescla a `#47`; agente rebaseia a `#42` sobre a `main` nova (resolvendo `alertas_fonte.test.mjs`, `alertas-fonte.js`, `alertas.js`) e a `#21` (`.gitignore`), sem mesclar nenhuma das duas.
- **Depois:** `git merge-tree` limpo para as duas; `npm run test:worker` e `pytest` verdes em cada branch.
- **Volta:** `git push --force-with-lease` da branch anterior (o SHA fica no corpo do commit do rebase).

### A5. A agenda verde, em PR que só é mesclada no passo B6

> **Feito em 2026-10-13, não mesclado:** `Araripe#118` (rascunho, branch
> `claude/p6-agenda-verde`), registro
> [`PHASE_6ZB_2026-10-13.md`](../implementation/PHASE_6ZB_2026-10-13.md). A
> promoção encadeada **não** lê a conclusão do run de depósito — medido: uma
> rodada sem aquisição termina `success` com o job `deposit` `skipped` —, e
> sim o job `deposit` da tentativa que disparou, só para rodada agendada. Um
> depósito despachado à mão continua promovido à mão (A9). D2 conta do
> `terminal_at` da rodada pendente mais antiga: com o status das 12:00, uma
> promoção que não veio fica vermelha entre 48 e 72 h depois da detecção.
> `pytest` 2840 → 2909; 25 mutações derrubadas. **Só a primeira rodada
> agendada depois do B6 prova** o `workflow_run`, o `actions: read` e o
> `v2-promotion` aceitando esse evento.

- **Quem:** agente.
- **Aprovação:** nenhuma para a PR.
- **Antes:** D1, D2, D3 registradas (A1).
- **Faz:** PR no backend: `v2_green_deposit_lane.yml` ganha `schedule: '0 6 * * 1,4'` (o horário do `detect_gee.yml`, preservando a folga de 24 h para o robô do site às 06:00 de Ter/Sex) e o guarda `github.event_name == 'workflow_dispatch'` dos jobs passa a aceitar `schedule` com `chain=head`; a promoção encadeada por D1; `v2_green_status.yml` ganha o cron de D3; `green_status.py` ganha o limite (d) de D2; o teste do 2B.0 ("nenhuma lane verde tem cron") vira a lista exata das que têm.
- **Depois:** `pytest` verde; `executable_lines()` nos workflows mostra os crons esperados e nenhum outro.
- **Volta:** fechar a PR.

### A6. `FONTE_PADRAO` verde e os textos estáticos, em PR mesclada no passo B5

> **Feito em 2026-10-13, não mesclado:** `observatorio-site#49` (rascunho,
> branch `claude/p6-fonte-padrao-verde`, ramificada da `#42` e com a PR
> apontando para ela; rebasear sobre a `main` do site depois do B2). Registro:
> [`PHASE_6ZD_2026-10-13.md`](../implementation/PHASE_6ZD_2026-10-13.md).
> O texto estático das duas páginas virou o **neutro** (é o que a recusa
> mostra) e o azul leva os rótulos de 2023 do código; a aba "Séries" diz a
> data lida do próprio `series.json`. A mais do que este passo pedia:
> `dados-abertos.html` lia `/data/alerts/manifest.json` sem chave e agora
> abre pela mesma porta da página de alertas. `main` + `#48` + `#42` + `#49`:
> `npm run test:worker` 251/251, `pytest` 290, build ok. Sobre elas a `#21`
> falha de propósito em `test_a_pagina_ainda_le_a_base_estatica` (C4).

- **Quem:** agente.
- **Aprovação:** nenhuma para a PR.
- **Antes:** `git -C site grep -n "FONTE_PADRAO = 'azul'" origin/main` acha a linha.
- **Faz:** PR no site: `FONTE_PADRAO = 'verde'`; e, no mesmo diff (acréscimo de 2026-10-07 à noite), o seletor de coleção e a frase "versões anteriores … 2023" em `alertas.html`, a mesma frase em `dados-abertos.html` e a explicação em `worker/knowledge.js`; se D4 = 1, a data da série dita na aba "Séries".
- **Depois:** `npm run test:worker`, `pytest`, `vite build` verdes; `git grep -n "2023"` nos três arquivos só onde o texto for histórico de propósito.
- **Volta:** fechar a PR.

### A7. Tirar o job `alertas` do robô do site, em PR mesclada no passo C2

> **Feito em 2026-10-14, não mesclado:** `observatorio-site#50` (rascunho,
> branch `claude/p6-robo-sem-alertas`, commit `ad710d8`, ramificada da `main`
> do site em `a0c3390`). Registro:
> [`PHASE_6ZE_2026-10-14.md`](../implementation/PHASE_6ZE_2026-10-14.md).
> Sai o job inteiro; `chuva`, cron, `workflow_dispatch`, `concurrency` e
> `permissions` iguais pelo YAML carregado (na `chuva`, só um comentário de
> shell). Os testes prendem que nenhum passo chama `check_backend_release.py`,
> `freshness.py … alertas` nem `prepare_data.py alerts`/`timeseries`, nem
> recebe `R2_*`; seis mutações derrubam. Ficam sem chamador, **não
> apagados**: `check_backend_release.py`, os dois modos de `prepare_data.py` e
> `public/data/freshness/alertas.json`. `npm run test:worker` 223/223,
> `pytest` 227 → 225, build ok. Não toca nenhum arquivo das `#48`, `#42`,
> `#49`, `#21`.

- **Quem:** agente.
- **Aprovação:** nenhuma para a PR.
- **Antes:** `update-data.yml` tem os jobs `alertas,chuva`.
- **Faz:** PR que remove o job `alertas` (e, por D4, a geração de `series.json` que vive nele) e deixa o job `chuva` e o cron `0 6 * * 2,5` intactos.
- **Depois:** o YAML tem só `chuva`; `pytest` do site verde.
- **Volta:** fechar a PR.

### A8. Revogar a chave local de staging e reescrever o documento dela

> **Feito em 2026-10-14:** o dono apagou (delete, não roll) o token
> `claude-araripe-v2-staging-rw` no painel; o profile `araripe-r2-staging`
> passou a receber `Unauthorized` às 11:51:46 UTC. A chave do Environment
> `v2-staging` é `github-araripe-v2-staging-rw` (nomes e datas no painel,
> `PHASE_2B0_2026-08-11.md`) e **não** foi revogada: `v2_green_status.yml`
> da `main` (run `38559580150`) leu todos os produtos com ela. A run
> terminou `failure` só por `automation.latest late` (6 dias desde
> 2026-10-07, limite 5 — nenhuma agenda verde antes do B6), não por
> credencial. O dono também apagou os dois profiles locais; esta máquina não
> tem mais credencial do bucket. `CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md`
> reescrito. Registro:
> [`PHASE_6ZF_2026-10-14.md`](../implementation/PHASE_6ZF_2026-10-14.md).

- **Quem:** dono revoga; agente prova e reescreve.
- **Aprovação:** dono, explícita (credencial).
- **Antes:** o dono confere no painel da Cloudflare (R2 → API tokens) que `claude-araripe-v2-staging-rw` **não** é a chave guardada no Environment `v2-staging` (nomes e datas de criação diferentes) — senão a revogação para a lane de depósito; agente confirma que nenhum passo desta folha depende de depósito local (todos usam as lanes).
- **Faz:** dono revoga `claude-araripe-v2-staging-rw`; agente reescreve `CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md` para o papel canônico (opção (a)), registrando a revogação como fato medido.
- **Depois:** uma chamada só-leitura com o profile local é **recusada** (escopo de credencial só se prova com chamada real recusada); `v2_green_status.yml` disparada da `main` continua `ok` (a chave do Environment vive).
- **Volta:** o dono cria uma chave nova com o mesmo escopo; nada de produção depende da antiga.

### A9. Drenar a fila desde 2026-10-05, na véspera

> **Feito em 2026-10-14 (antes do dia marcado — repetir na véspera):**
> status `38560897858` sem `broken` (só `automation.latest late`, 6 d).
> Lane de depósito `38561001665`, `chain=head`: continuou
> `ci-37686447368`, janela 2026-10-05..2026-10-13 exclusiva (8 dias, até
> `hoje − 2`, uma rodada bastou) e depositou `ci-38561001665` — 10-09 e
> 10-11 com alertas, 10-07 e 10-12 sem cobertura válida. Publicação
> `38562453035`, `source=chain`: `stage`, `promote`, `context` e `sources`
> com sucesso; ponteiro na seq. 19 →
> `rel-g3-b19132638d911f28ab8c711b68cd848849b57e5f679d373a34191285281e63fa`
> (20 membros), contexto `ctx-g1-5b1ac5a0…` seq. 3, fontes
> `src-g1-e9e0ba1a…` seq. 2. Status `38567568460`: tudo `ok` —
> `alerts.observed` 2026-10-12 (2 d), `deposits.unpublished` nada espera,
> `automation.latest` 0 d. A fila volta a crescer um dia por dia: o B5 pede
> o A9 feito há menos de 3 dias, então **na véspera** roda-se de novo o
> mesmo comando. Registro:
> [`PHASE_6ZG_2026-10-14.md`](../implementation/PHASE_6ZG_2026-10-14.md).

- **Quem:** agente.
- **Aprovação:** nenhuma (staging; promoção sem revisor por decisão de 2026-10-02; nenhum consumidor público segue o ponteiro ainda).
- **Antes:** `v2_green_status.yml` sem `broken`.
- **Faz:** dispara `v2_green_deposit_lane.yml` com `chain=head` (repete enquanto a janela de 16 dias não cobrir até `hoje − 2`); se depositou, `v2_operational_publish.yml` com `source=chain`.
- **Depois:** `v2_green_status.yml`: `deposits.unpublished` ok e `alerts.observed` com no máximo 2 dias, ou o motivo (`no_acquisition`) no resumo da rodada.
- **Volta:** um rollback do ponteiro pelo `v2-promotion` (`v2_promotion_lane.yml`, `mode: rollback`), só a pedido do dono.

### A10 (opcional). Ensaio do Worker verde na borda

- **Quem:** dono.
- **Aprovação:** dono, explícita.
- **Antes:** só se o dono quiser ver o código novo da rota (delivery/3) na borda antes do domínio final; com D0 = a, o passo B1 já é essa checagem.
- **Faz:** `site/scripts/green_worker.sh deploy GREEN-ONLY` da máquina do dono, **antes** de abrir o `workers.dev` no painel (um deploy com `workers_dev: false` desliga o endereço).
- **Depois:** A3 contra o endereço `workers.dev`; depois o broker fecha (`enforce-worker-isolation`, então `audit`) e o endereço responde 404 `1042`.
- **Volta:** `wrangler rollback` para a versão anterior, na máquina do dono.

### A11. A revisão desta folha pelo dono

> **Feito em 2026-10-14:** a folha apresentada ao dono passo a passo (Fases B
> e C, com quem age e como se volta); resposta dele, nas palavras dele:
> *"1. Sim"*, e o dia: hoje, quarta 2026-10-14 (ver D6 na §3). Conferido antes,
> às 13:05Z: status `38568924312` com as sete linhas `ok` (ponteiro seq. 19,
> `alerts.observed` 2026-10-12); site em rascunho `#48` `95148a8`, `#42`
> `e2a33f5`, `#49` `6fc7491` (base `#42`), `#50` `ad710d8`, `#21` `ab65a55`;
> backend `#118` em rascunho. A `#48` está **1 commit atrás** da `main` do
> site (`a0c3390`, a `#47`) com `git merge-tree` limpo — o "Antes" do B1 pede
> rebaseá-la. O A9 de 2026-10-14 (12:54Z) vale para um B5 hoje; não é preciso
> véspera. Registro:
> [`PHASE_6ZH_2026-10-14.md`](../implementation/PHASE_6ZH_2026-10-14.md).

- **Quem:** dono.
- **Aprovação:** dono, explícita.
- **Antes:** A1–A9 feitos; esta folha atualizada com os SHAs e runs de cada um.
- **Faz:** o dono lê a Fase B inteira e marca o dia (D6).
- **Depois:** o "sim" do dono registrado na PR do registro da virada.
- **Volta:** nada a desfazer.

## 5. Fase B — a virada, no dia

Cada passo desta fase **para e pergunta** antes de agir.

### B0. Fotografia e alvos de volta

> **Feito em 2026-10-14:** status `38573085048` (13:36Z), as sete linhas
> `ok`, ponteiro seq. 19; versão do Worker `observatorio-chapada` em produção
> `3d910ec8` (lida pelo dono em Deployments, 100% do tráfego) — o alvo de
> volta de B1/B2/B5; hostname público de `araripe-cogs` lido pelo dono nas
> configurações do bucket: `pub-5eb389cffff54421916187be69dd659b.r2.dev`,
> igual ao esperado; `detect_gee.yml` ativo. Linha de base às 14:33Z: o
> `manifest.json` azul com sha256 `158f005f…cbd5505`, `/data/green/current.json`
> 404. Registro: [`PHASE_6ZI_2026-10-14.md`](../implementation/PHASE_6ZI_2026-10-14.md).

- **Quem:** agente lê; dono anota o que só o painel mostra.
- **Aprovação:** nenhuma (leitura).
- **Antes:** A11 feito.
- **Faz:** registra no documento da virada, só lendo: `v2_green_status.yml` (run e as sete linhas); a versão em produção do Worker `observatorio-chapada` (o dono lê em Deployments) como alvo de volta de B1/B2/B5; o hostname público de `araripe-cogs` **como o dono o lê nas configurações do bucket**, que tem de ser exatamente `pub-5eb389cffff54421916187be69dd659b.r2.dev`; `gh workflow list -R santibravocmcc/Araripe` com `detect_gee.yml` ativo.
- **Depois:** os quatro valores escritos, copiados da ferramenta que os produz.
- **Volta:** nada a desfazer.

### B1. A rota no domínio final (merge da PR de A2)

> **Feito em 2026-10-14:** a `site#48` rebaseada (`95148a8` → `b518bb0`) e
> mesclada pelo dono às 14:35Z (`11d1b65`), nas palavras dele: *"Sim, mesclei
> a #48"*. Check run do Workers Builds `success` às 14:37:16Z — **o token
> aceitou o binding de R2** (era o não medido). `/data/green/current.json`
> 200 `no-store`; o azul com o mesmo sha256; `/api/chat/models` 200; a página
> sem parâmetro pediu `manifest.json` e `run-2026-08-30`. O verificador deu
> 54 PASS e **1 FAIL que era dele**: pedia `X-Araripe-Context-Id` ao
> documento `context/context.json`, que o vetor de conformidade e
> `_resolve_context` servem sem esse header (ele vai nos objetos); o arnês
> local roda `--sem-contexto` e não pegava. Corrigido em `site#51`
> (rascunho, `ddf2599`): 61 PASS, 0 FAIL. Sem "Volta".

- **Quem:** dono mescla.
- **Aprovação:** dono, explícita (deploy de produção).
- **Antes:** A2 verde e rebaseada sobre a `main`; B0 registrado.
- **Faz:** merge da PR de A2.
- **Depois:** check run do Workers Builds no commit do merge = `success` (`gh api repos/santibravocmcc/observatorio-site/commits/<sha>/check-runs`); A3 contra `https://observatoriodachapadadoararipe.com/data/green/` — todas PASS; a página sem parâmetro continua azul (mesmo `manifest.json`); `/api/chat` responde. Se o build falhar porque o token do Workers Builds não liga R2 (não medido), a versão anterior fica no ar: é falha fechada.
- **Volta:** revert da PR (outro deploy, ~70 s) ou rollback para a versão de B0 no painel (dono).

### B2. O índice composto no build e o reconciliador (merge da `site#42` com `COMPOR = True`)

> **Feito em 2026-10-14:** a `#42` rebaseada sobre a `#48` (`e2a33f5` →
> `ec92808`, com `COMPOR = True` e o teste que o fixa); antes do merge, o
> build local contra o domínio real compôs o índice da release viva. Mesclada
> pelo dono às 14:57Z (`198be57`): *"Sim, mesclei a #42"*. Build `success` às
> 15:05:51Z; `built-from.json` = `rel-g3-b1913263…` + `ctx-g1-5b1ac5a0…`, o
> mesmo do ponteiro; verificador 61 PASS; `alertas?dados=verde` com as três
> datas e `/?dados=verde` com os alertas de 11/10, nenhum pedido a `r2.dev`;
> `green_site_rebuild.yml` à mão (run `38586402108`): `em_dia`.

- **Quem:** agente prepara o diff de uma linha na `#42`; dono mescla.
- **Aprovação:** dono, explícita.
- **Antes:** B1 verificado; a `#42` rebaseada (A4).
- **Faz:** merge da `#42` com `COMPOR = True` em `site/scripts/indice_no_build.py`, que liga junto o cron `41 */3` de `green_site_rebuild.yml`.
- **Depois:** check run `success`; `curl -s https://observatoriodachapadadoararipe.com/data/alert-index/built-from.json` nomeia o mesmo `release_id` de `/data/green/current.json`; `alertas.html?dados=verde` e `/?dados=verde` mostram o verde com as três datas, sem pedido a `r2.dev` (rede do navegador); `green_site_rebuild.yml` disparado à mão diz `em_dia`.
- **Volta:** PR com `COMPOR = False` (desliga composição e reconciliador; a página volta a recusar `?dados=verde` e o padrão segue azul).

### B3 (recomendado). Ensaio de rollback com a página no ar

> **Feito em 2026-10-14**, com o "sim" do dono: *"Sim, pode fazer o B3"*.
> Histórico `38586517253`: `consistent`, seq. 10–19. Rollback `38593878442`
> → seq. 20 `rel-g3-76601bbf…`: `?dados=verde` mostrou "Os alertas estão
> sendo atualizados" (`indice_de_outra_release`); reconciliador `38594820364`
> → commit vazio `91bffea` → build `success` 16:09:04Z → a página com a
> release de 04/10 (contexto e fontes ausentes, como o contrato manda para
> uma release que não é a deles). Volta `38595685474` → seq. 21
> `rel-g3-b1913263…`; reconciliador `38596477365` → `a5bdad5` → build
> 16:23:40Z. Ao fim: verificador 61 PASS; status `38597782742` sete `ok`,
> ponteiro seq. 21; o azul com o mesmo sha256.

- **Quem:** agente dispara, a pedido do dono.
- **Aprovação:** dono, explícita (move o ponteiro que `?dados=verde` segue).
- **Antes:** B2 verificado; `publish_green_release.py history` (lane `v2_promotion_lane.yml`, `mode: history`) mostra a release anterior retida.
- **Faz:** `v2_promotion_lane.yml` `mode: rollback` para a release anterior; depois `mode: rollback` de volta para a de B0.
- **Depois:** a cada movimento, `?dados=verde` recarregada mostra o quadro "Os alertas estão sendo atualizados" em até 1 min, e o reconciliador reconstrói (≤ 3 h + atraso do cron, ou disparo manual); ao fim, A3 e o status iguais aos de B0.
- **Volta:** é o próprio passo.

### B4. As checagens que só um navegador responde

> **Feito em 2026-10-14:** visão completa de 11/10: 2,0 MiB transferidos
> (7,0 MiB de corpo); a maior, 26/06: **27,9 MiB transferidos (89,1 MiB de
> corpo), ~26 s**, renderizada (5.053 alertas). **D5:** a mediana das 47
> visões completas é 26 MiB e 25 passam de 25 MiB — o aviso de tamanho antes
> de baixar vira pacote do site, depois. `?download=1` →
> `filename="run-2026-10-09.geojson"`; nenhum `Access-Control-*`, nenhum
> preflight; `.creditos-dados` presente; 375 px sem rolagem lateral
> (`scrollWidth` 375).

- **Quem:** agente (navegador, só leitura).
- **Aprovação:** nenhuma.
- **Antes:** B2 verificado.
- **Faz:** em `alertas.html?dados=verde`: a visão completa de uma data comum e da maior; "Baixar" de uma execução; os créditos das fontes (`.creditos-dados`); 375 px sem rolagem lateral.
- **Depois:** tamanho transferido da maior visão completa anotado (D5); `?download=1` nomeia o arquivo pelo caminho declarado; nenhum `Access-Control-Allow-Origin` e nenhum preflight na aba de rede.
- **Volta:** nada a desfazer.

### B5. O público passa a ver o verde (merge da PR de A6)

> **Feito em 2026-10-14:** a `#49` rebaseada só com o seu commit
> (`6fc7491` → `008a27d`, mesmo patch) e com a base trocada para `main`;
> mesclada pelo dono às 16:28Z (`1978b15`): *"Sim, mesclei a #49"*. Build
> `success` 16:36:27Z. Sem parâmetro: `alertas` verde com as três datas e os
> créditos, `/` com os alertas de 11/10, `dados-abertos` baixando
> `/data/green/alerts/run-2026-10-11.geojson?download=1`; nas três, nenhum
> pedido a `r2.dev` nem a `/data/alerts/`. Verificador 61 PASS;
> `?dados=azul` mostra o azul de 30/08 (3.017 fortes).

- **Quem:** dono mescla.
- **Aprovação:** dono, explícita — **é o passo que muda o que o público vê**.
- **Antes:** B1–B4 verificados; A9 feito há menos de 3 dias.
- **Faz:** merge da PR de A6 (`FONTE_PADRAO = 'verde'` e os textos estáticos).
- **Depois:** sem parâmetro, `alertas.html` e `/` mostram o verde, as três datas, os créditos das fontes; a aba de rede da carga padrão não tem pedido a `pub-5eb389cffff54421916187be69dd659b.r2.dev` nem a `/data/alerts/manifest.json`; `dados-abertos.html` sem parâmetro oferece a última execução verde (`?download=1`) e também não pede `/data/alerts/` (acréscimo de 2026-10-13, `PHASE_6ZD` §3); A3 de novo; `?dados=azul` ainda mostra o azul congelado em 2026-08-30.
- **Volta:** revert da PR (~70 s): a página volta ao azul, que ainda está inteiro no deploy e no `r2.dev`.

### B6. A agenda verde (merge da PR de A5)

> **Feito em 2026-10-14:** a `#118` (`8e9c6e3`, 7 atrás da `main`, só
> docs) testada rebaseada localmente: suíte 2924 passed, 6 failed e 14
> errors — todos os de 2a5/2a6d que dependem de dados não rastreados num
> worktree novo. Mesclada pelo dono às 16:50Z (`17cae38`): *"Sim, mesclei a
> #118"*; o tree mesclado é o testado. Na `main`: `0 6 * * 1,4` no depósito,
> `0 12 * * *` no status, `workflow_run` na publicação; os três `active`.
> **A rodada agendada ainda não rodou:** a primeira é quinta 2026-10-15
> 06:00 UTC (próxima sessão).
>
> **Primeira rodada lida em 2026-10-16** ([`PHASE_6ZJ`](../implementation/PHASE_6ZJ_2026-10-16.md)):
> depósito `38724054754` (`schedule`) sem imagem na janela de um dia
> (`deposit` `skipped`); publicação `38724206864` disparada por
> `workflow_run`, o `gate` leu o job e não promoveu; status `38770513231`
> (`schedule`) sete `ok`. A promoção vinda da agenda segue não exercitada:
> o "Antes" do C1 espera a rodada de segunda 2026-10-19.
>
> **Rodada de segunda lida em 2026-10-19** ([`PHASE_6ZK`](../implementation/PHASE_6ZK_2026-10-19.md)):
> depósito `39251503748` (`schedule`) com 3 aquisições na janela
> 10-13..10-18; publicação `39253009226` por `workflow_run`, `stage`,
> `promote`, `context`, `sources` `success`, ponteiro seq. 22
> `rel-g3-0a788e76…`; o reconciliador reconstruiu o site e o domínio serve a
> release nova; status `39303347681` sete `ok`. **O "Antes" do C1 está
> cumprido.**

- **Quem:** dono mescla.
- **Aprovação:** dono, explícita (muda o que roda sem clique; a `main` do backend é só por PR).
- **Antes:** B5 verificado.
- **Faz:** merge da PR de A5.
- **Depois:** `gh workflow view v2_green_deposit_lane.yml -R santibravocmcc/Araripe` mostra o agendamento; a próxima segunda ou quinta: o depósito agendado roda como `head`, a promoção vem por D1, o contexto e as fontes na mesma lane, o reconciliador reconstrói o site, e o status de D3 sai `ok` — quatro runs lidos, não presumidos.
- **Volta:** PR que tira os crons; as lanes manuais continuam.

## 6. Fase C — desligar o azul, só depois da primeira rodada verde agendada

### C1. Parar o agendamento azul

> **Feito em 2026-10-19**, com o "sim" do dono: *"Sim, pode desligar o
> agendamento azul (detect_gee.yml) agora."* `gh workflow disable
> detect_gee.yml` às 23:03:30Z, saída 0; `gh workflow list --all`:
> `detect_gee.yml` `disabled_manually`, as outras 14 lanes `active` como
> antes; o arquivo não mudou. Último run azul `39255074543` (10-19,
> `failure`). Registro:
> [`PHASE_6ZL_2026-10-19.md`](../implementation/PHASE_6ZL_2026-10-19.md).
> Falta ler a quinta 2026-10-22: nenhum run novo de `detect_gee.yml`.

- **Quem:** dono (ou agente com o "sim" do dono para este passo).
- **Aprovação:** dono, explícita (lane azul de produção).
- **Antes:** a primeira rodada agendada de B6 lida e `ok`.
- **Faz:** `gh workflow disable detect_gee.yml -R santibravocmcc/Araripe` — o arquivo fica byte-idêntico, como a Phase 6 promete.
- **Depois:** `gh workflow list -R santibravocmcc/Araripe` com `detect_gee.yml` `disabled_manually`; nenhum run novo na segunda/quinta seguinte.
- **Volta:** `gh workflow enable detect_gee.yml` (imediato; ele volta a falhar, porque é o `LegacyPersistenceStateError`).

### C2. Parar o robô azul do site (merge da PR de A7)

- **Quem:** dono mescla.
- **Aprovação:** dono, explícita.
- **Antes:** C1 feito.
- **Faz:** merge da PR de A7.
- **Depois:** a terça/sexta seguinte: `update-data.yml` roda só `chuva`, verde; a página de chuva atualizada.
- **Volta:** revert da PR.

### C3. Desligar o acesso público de `araripe-cogs`

- **Quem:** dono, no painel (R2 → `araripe-cogs` → Settings → Public access → `r2.dev` Disable).
- **Aprovação:** dono, explícita. **Não** vai para o broker.
- **Antes:** B5 verificado com a aba de rede sem `r2.dev`; o hostname de B0 conferido letra por letra.
- **Faz:** desabilita o acesso público gerenciado. **Nenhum objeto é apagado.**
- **Depois:** `curl -sI https://pub-5eb389cffff54421916187be69dd659b.r2.dev/site-full/` não responde mais com objeto; a visão completa padrão continua funcionando (é pela rota); `?dados=azul` perde a visão completa — aceito.
- **Volta:** reabilitar no mesmo lugar; o hostname deriva do bucket e volta igual.

### C4. Parar de commitar alertas no git do site (merge da `site#21`)

- **Quem:** dono mescla.
- **Aprovação:** dono, explícita.
- **Antes:** B5 e C2 feitos; a `#21` rebaseada de novo sobre a `main` do site depois do B5, e o teste `test_a_pagina_ainda_le_a_base_estatica` dela — que confere `FONTE_PADRAO = 'azul'` em `src/js/alertas-fonte.js` e falha de propósito quando o padrão vira verde — reescrito para registrar a condição cumprida. (Até 2026-10-13 este campo dizia "`src/js/alertas.js` resolve `object_base`": envelheceu sem mudar de palavra, porque a resolução mora em `alertas-fonte.js` desde a leitura verde, e só vale para `?dados=verde` até o B5 — `PHASE_6ZC` §3.)
- **Faz:** merge da `#21`.
- **Depois:** build `success`; a página padrão abre a data mais recente (não 404).
- **Volta:** revert da PR.

### C5. Registrar a virada

- **Quem:** agente.
- **Aprovação:** nenhuma.
- **Antes:** C1–C4 feitos.
- **Faz:** registro `docs/implementation/PHASE_6_CUTOVER_<data>.md` com cada passo, SHA, run e leitura; `ROADMAP.md` (bloco datado) e `PENDING_CAPABILITIES.md` atualizados.
- **Depois:** `git show origin/main:docs/implementation/PHASE_6_CUTOVER_<data>.md` existe.
- **Volta:** nada a desfazer.

### C6. Duas semanas de vigia

- **Quem:** agente lê; dono recebe os e-mails de falha.
- **Aprovação:** nenhuma.
- **Antes:** C5.
- **Faz:** lê a lane de status (D3) e os runs de depósito e promoção a cada rodada.
- **Depois:** quatro rodadas seguidas sem `late` nem `broken`; a primeira que falhar vira pacote, nunca remendo direto.
- **Volta:** a tabela de volta da §7.

## 7. Os caminhos de volta, numa tabela

| depois de | para voltar | quem | tempo |
| --- | --- | --- | --- |
| B1 | revert da PR, ou rollback de versão no painel | dono | ~70 s |
| B2 | PR com `COMPOR = False` | dono mescla | ~70 s |
| B5 | revert da PR (`FONTE_PADRAO` azul) | dono mescla | ~70 s |
| B6 | PR tirando os crons | dono mescla | minutos |
| C1 | `gh workflow enable detect_gee.yml` | dono | imediato |
| C3 | reabilitar `r2.dev` em `araripe-cogs` | dono | imediato |
| uma promoção errada | `v2_promotion_lane.yml` `mode: rollback`, a pedido do dono | agente | minutos + rebuild do site |

**Depois de C3, voltar para o azul é B5 ao contrário E C3 ao contrário** — o
azul está congelado em 2026-08-30 e não volta a andar, porque o
`detect_gee.yml` falha por contrato desde 2026-09-03.

## 8. O que esta folha não cobre

- a validação qualificada e qualquer afirmação de acurácia (Phase 5);
- o CI da suíte, acessibilidade e skills (Phase 7);
- a série temporal verde (D4), um pacote seu;
- limitar a taxa da rota (`STAGING_LIMITER` declarado e não aplicado,
  `worker/green.js`): pergunta para quando a forma do tráfego for conhecida;
- apagar qualquer objeto, em qualquer bucket, em qualquer fase.
