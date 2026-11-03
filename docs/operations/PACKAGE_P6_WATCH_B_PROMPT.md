# Phase 6 — C6B: a vigia que continua, com o site novo

Escrito em 2026-11-03, no fecho encurtado do C6
([`PHASE_6ZP_2026-11-03.md`](../implementation/PHASE_6ZP_2026-11-03.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: é leitura de logs e um registro, sem escrita em nada que roda. O
> risco é concluir pela conclusão de uma run em vez das sete linhas do log
> dela, contar uma rodada que não houve, ou tomar um push de robô novo na
> `main` do site como inofensivo sem olhar a hora.

**Quando abrir:** terça 2026-11-17, depois do status de segunda 2026-11-16
(o cron das 12:00 UTC tem rodado entre 17:00Z e 21:30Z). **Abra antes** se o
dono receber o e-mail de um workflow agendado que falhou, ou se o robô do CAR
abrir um issue: aí a sessão lê a falha e para.

**Por que existe:** o dono fechou o C6 com duas rodadas de quatro, em
2026-11-02, nas palavras dele: *"Eu gostaria de fechar o C6 hoje, em vez de
esperar ate dia 10/11. E montar uma nova etapa de vigilia chamada C6B. Ela
deve considerar o novo estado do site com as mudanças do CAR por exemplo."*
O C6B recupera as rodadas que faltaram e vigia o que entrou no site.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6ZP_2026-11-03.md | head -5
    git -C site fetch origin && git -C site log --oneline --since=2026-11-03 origin/main
    gh workflow list -R santibravocmcc/Araripe --all --json path,state
    gh workflow list -R santibravocmcc/observatorio-site --all --json path,state
    gh run list -R santibravocmcc/Araripe --workflow v2_green_deposit_lane.yml -L 8 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/Araripe --workflow v2_operational_publish.yml -L 8 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/Araripe --workflow v2_green_status.yml -L 20 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/observatorio-site --workflow update-data.yml -L 6 --json databaseId,event,conclusion,createdAt,headSha
    gh run list -R santibravocmcc/observatorio-site --workflow update-clima.yml -L 6 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/observatorio-site --workflow previsao-clima.yml -L 3 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/observatorio-site --workflow update-car.yml -L 3 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/observatorio-site --workflow green_site_rebuild.yml -L 60 --json databaseId,event,conclusion,createdAt

- Esperado: `PHASE_6ZP` na `main` do backend (se não estiver, a PR do C6
  não foi mesclada: pare e diga ao dono); `detect_gee.yml`
  `disabled_manually`, as outras 14 `active`.
- Ponto de partida: ponteiro seq. 26
  `rel-g3-79eef163a64050477d08e6a5152072227c11c98fb1ba9dc100335e2ff5d41a1f`,
  cabeça `ci-41466713190` cobrindo até 2026-10-31, status `41529352600`;
  site em `6a200cd` (`deploy(verde)` da seq. 26).
- `update-car.yml` só existe na `main` do site se a `site#64` entrou. Se o
  `gh run list` dele disser que o workflow não existe, registre "robô do CAR
  não mesclado" e pule o §3.6.

## 2. O que já está provado — não refazer

- A virada A1–C5: `PHASE_6_CUTOVER_2026-10-27.md`.
- As rodadas de 10-29 e 11-02, os status de 10-27 a 11-02 e o robô de chuva
  de 10-30: `PHASE_6ZP` §2–§4. Não contam de novo.
- O build com o Monitor (`#52`/`#53`), o jogo (`#62`) e o verificador
  (`#51`) já foi implantado verde pelo reconciliador (`PHASE_6ZP` §6).
- A chuva do robô de terça aparece na página sem clique desde que o build
  cache foi desligado (registro da virada §7). Vigiar, não consertar.

## 3. A tarefa

**Única tarefa: ler e registrar.** Escreva
`docs/implementation/PHASE_6ZQ_<data>.md`, uma linha por item.

### 3.1 As quatro rodadas de depósito

Qui **2026-11-05**, seg **11-09**, qui **11-12**, seg **11-16** (depósito
`0 6 * * 1,4`). Para cada uma, como no C6:

1. o depósito (`schedule`): jobs `detect`, `deposit`, `heartbeat`; a janela
   e "continues `ci-…`" no log. Uma rodada sem aquisição ou com a aquisição
   recusada pela cobertura **conta** como rodada sem falha, mas diga que não
   trouxe alerta novo (foi o caso de 10-29);
2. a publicação (`workflow_run`): `gate`, `stage`, `promote`, `context`,
   `sources`; o `sequence` antigo → novo e o `rel-g3-…` **copiados do log**;
3. o reconciliador: o commit `deploy(verde): reconstruir para release=…`, o
   check run "Workers Builds" dele, e **a espera entre a linha `pointer :
   promote` do log e o commit**. Em 11-02 foram 4 h 16 min, porque o GitHub
   pulou passadas do cron `41 */3 * * *`.

### 3.2 Todos os status diários

De 2026-11-03 a 2026-11-16: as sete linhas do log
(`grep -E '\b(ok|late|broken)\b'`), não a conclusão. Diga quais faltam, se
o GitHub pulou algum dia.

### 3.3 Os robôs de chuva e de clima (Ter/Sex)

- `update-data.yml` de 11-03, 11-06, 11-10 e 11-13: um job só, `chuva`,
  `success`, commit sem arquivo sob `public/data/alerts/`.
- `update-clima.yml` (`30 7 * * 2,5`) nos mesmos dias: `success`, commit só
  sob `public/data/clima/` e `public/data/freshness/`.
- `previsao-clima.yml` (`0 6 15 * *`): a primeira rodada é dom 2026-11-15.

### 3.4 Jogo (`#62`)

A página `/jogo.html` responde (`307` para `/jogo`, e `/jogo` `200`). Só isso.

### 3.5 Monitor (`#61`) e o redirecionamento de `/alertas.html`

A `site#61` estava em rascunho em `14b9bc5` e devia ser mesclada pelo dono
em 2026-11-03. Confira pelo assunto `(#61)` na `main` do site. Se entrou:

- `/monitor` `200`; "Alertas" fora do menu;
- `/alertas.html` deixa de ser a página e redireciona para o Monitor **no
  navegador** (um redirect do servidor não vê o `#`). Prove com o navegador
  do app, não com `curl`: `/alertas.html#alerta-<id>` tem de abrir
  `/monitor.html?…#alerta-<id>` com a ficha do alerta, e
  `/alertas.html?dados=azul` tem de levar o `?dados=azul`. Use um `id`
  real tirado do índice servido.
- Se não entrou, registre e siga.

### 3.6 Robô do CAR e do Sinaflor (`#63`/`#64`)

`.github/workflows/update-car.yml`, cron `0 12 * * 3`, que só segue na
**1ª quarta do mês**. Na janela do C6B, a única rodada possível é **qua
2026-11-04**, e só se a `#64` entrou antes dela. Se rodou:

- as duas travas de saída: nenhum CPF/CNPJ (os testes de dado pessoal) e o
  `npm run build` passando — leia os passos no log;
- a decisão de publicar e o limiar de queda (`car_diferencas.travas`: mais de
  2% dos imóveis de uma UF sumindo, mais de 1% de mudança que a data não
  explica, mais de 10% das autorizações do Sinaflor sumindo). Travado = branch
  `car/<tag>`, Release pré-release, issue aberto, run vermelho. **Uma trava
  disparada é o robô funcionando, não falha da vigia**: registre e diga ao
  dono que a decisão de publicar é dele;
- o push direto na `main` do site, a Release `car-AAAA-MM-DD`, e o check run
  "Workers Builds" do commit dele.

### 3.7 O risco a vigiar: push na `main` do site entre promoção e reconciliador

Liste todo commit da `main` do site no período com a hora. Para cada
promoção, diga se algum push de outro autor (robô ou merge) caiu entre a
linha `pointer : promote` e o `deploy(verde)`. Um deploy assim implanta o
build com o índice da release anterior até o reconciliador passar — e já
apagou a prova de uma rodada antes. **Registre em especial se algum robô
novo (clima, CAR) cair numa segunda ou quinta**, entre o depósito e o
`deploy(verde)`.

### 3.8 Ao fim, a leitura ao vivo

Só GET, com o UA de um Chrome real: `/data/green/current.json` e
`/data/alert-index/built-from.json` com o mesmo `release_id`;
`/data/territorio/rain/manifest.json` com o `last` do último robô.

### Se tudo passou / se algo falhou

- **Tudo sem `late` nem `broken`:** bloco "Feito em …" num passo C6B novo,
  logo depois do C6 da folha da virada; linha no bloco datado do
  `ROADMAP.md` (sem reescrever as linhas `Implementation status`).
- **Algo falhou:** registre a primeira falha, pare e escreva o briefing de um
  pacote para ela — nunca remendo direto.

Entregue tudo numa PR de docs do backend. **Não mescle.**

**Fora de escopo:** consertar qualquer falha (vira pacote); mesclar PRs do
site; a série verde (D4, pacote seu); a Phase 7; o robô do IBAMA; a sessão
P5.1; apagar os 42 arquivos de `public/data/alerts/`; o broker.

## 4. Decisões de escopo já tomadas, com a base

- C6 encurtado e C6B criado: decisão do dono de 2026-11-02 (§ "Por que
  existe"), registrada em `PHASE_6ZP` §1.
- Limites do status: `automation.latest` `late` com mais de 5 dias inteiros;
  `deposits.unpublished` pendente por mais de 1 dia (D2); dados atrasados com
  21 dias (`site#47`).
- O robô do CAR publica por push direto na `main` do site, porque o
  repositório não deixa o `GITHUB_TOKEN` abrir PR e o dono pediu publicação
  sem passo manual (corpo da `site#64`). O site não tem a regra de "só PR" do
  backend. Não reabrir.

## 5. Fronteiras duras

- Só leitura e documentação. Nenhuma lane disparada, nenhum
  `workflow_dispatch` — nem do reconciliador "para ajudar" uma espera longa,
  nem do robô do CAR.
- Nenhum `wrangler`, token Cloudflare, login, chamada à API da Cloudflare ou
  broker; recusar se oferecido.
- `detect_gee.yml` e `update_data.yml` nunca são disparados nem reativados.
- Nenhum rollback do ponteiro sem o pedido do dono (folha §7).
- A `main` do site faz deploy de produção: o agente não faz push nela, não
  mescla PR dela e não fecha issue do robô do CAR.
- Nenhum purge de cache.

## 6. Armadilhas já pagas — não redescobrir

- `gh workflow list` sem `--all` esconde os desligados.
- Uma rodada sem aquisição, ou com a aquisição recusada pela cobertura,
  termina `success`; o status pode sair `failure` só por `late` — leia o log.
- O cron do GitHub atrasa de 40 min a mais de 9 h (o depósito de 11-02
  começou 14:56Z) e pula passadas do reconciliador; um status lido antes do
  reconciliador pode ver o site uma release atrás. Leia o horário.
- A borda da Cloudflare devolve 403/1010 a cliente sem UA de navegador.
- `/x.html` responde `307` para `/x`; siga o redirect antes de concluir.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório:
  SHAs do site entram na mensagem pela forma curta.
- `<<EOF` não citado executa os backticks: `git commit -F`.
- Decidir merge por conteúdo ou pelo assunto `(#N)`, nunca por
  ancestralidade. A `#52` entrou por merge commit (`d975f00`), não por squash.

## 7. Estado que o package herda

- Phase 6 fechada em 2026-11-03 por decisão do dono (C6 encurtado).
- Ponteiro seq. 26 `rel-g3-79eef163…`, contexto `ctx-g1-4558bd72…` seq. 8,
  fontes `src-g1-1829ba6c…` seq. 7.
- `detect_gee.yml` `disabled_manually` desde 2026-10-19; `r2.dev` de
  `araripe-cogs` fechado desde 2026-10-23; alertas novos fora do git do site
  desde 2026-10-24; build cache do Workers Builds desligado — manter.
- Site na `main`: Clima (`#56`/`#57`), Monitor (`#52`/`#53`), jogo v2
  (`#62`), verificador (`#51`). Em rascunho em 2026-11-03: `#61` (Monitor
  absorve Alertas), `#63` (CAR pelo WFS) e `#64` (robô do CAR), todas para o
  dono mesclar.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada desta etapa ainda: ela começa quando as quatro rodadas de novembro
tiverem acontecido.

### O que você precisa fazer

1. **Abrir a próxima sessão do Claude com este briefing** — a partir de terça
   17/11. Antes disso, só se chegar um e-mail de falha de um robô ou um
   aviso do robô do CAR.
2. **Mesclar as PRs do site quando quiser** — o Monitor novo e o robô do
   CAR. A vigia confere o que tiver entrado; o que não entrou ela só anota.

### Tem algo preocupante?

Não. As rodadas e os avisos diários estão em ordem; o único ponto de atenção
é que o GitHub às vezes atrasa a reconstrução da página em algumas horas, e
esta etapa mede isso.

### O que ainda falta no caminho

- **Esta vigia (C6B)** — quatro rodadas de novembro e as partes novas do site.
- **A série de índices do sistema novo** — a aba "Séries" está parada em
  setembro; o próximo pacote.
- **Avisar o tamanho antes de baixar** — um pacote pequeno do site.
- **Corrigir a frase da automação na página** — um pacote pequeno do site.
- **Fase 5** — a validação independente; a sessão de execução já tem
  briefing.
