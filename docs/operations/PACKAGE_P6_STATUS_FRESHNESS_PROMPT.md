# Phase 6 — resumo de execução, status e frescor por produto, no verde

Escrito em 2026-10-10, ao fim da sessão que publicou as fontes da release viva
([`PHASE_6X`](../implementation/PHASE_6X_2026-10-10.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: é desenho antes de código. O item 6 da §4.1 de
> [`PACKAGE_P6_PROMPT.md`](PACKAGE_P6_PROMPT.md) nomeia três coisas
> ("resumos de execução, saída de status/saúde, frescor por produto") e o
> verde já tem pedaços de cada uma em lugares diferentes. O erro plausível é
> construir um quarto lugar que repete os outros, ou um frescor que mede o
> carimbo de um objeto em vez da idade do dado que a página mostra.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C site fetch origin && git -C site rev-parse origin/main
    gh pr list -R santibravocmcc/Araripe --state all --limit 4 --json number,state,mergedAt
    gh pr list -R santibravocmcc/observatorio-site --state all --limit 4 --json number,state,mergedAt

- A `Araripe#110` (lane das fontes, `delivery/3`) e a PR de registro da
  PHASE_6X estão na `main` do backend: `git show origin/main:scripts/publish_green_sources.py`
  existe e `docs/implementation/PHASE_6X_2026-10-10.md` também.
- `observatorio-site#46` **não** é pré-requisito; se o dono a tiver mesclado,
  `worker/data_route.js` na `main` do site responde `sources.json`.
- Worktree com os cinco caminhos de dado ligados (memória
  `worktree-novo-nao-tem-o-untracked`). Suíte: conda `araripe`
  (`/opt/anaconda3/envs/araripe/bin/python -m pytest -q`). Base medida em
  2026-10-10 depois da `#110`: **2769**.

## 2. O que já foi verificado, para o executor não refazer

- **Fontes publicadas** (PHASE_6X §3): `sources/current.json` seq. 1 →
  `src-g1-c9dcba55…`, para a release seq. 18 e o contexto `ctx-g1-dd374bac…`.
  A lane `v2_green_sources.yml` e o job `sources` da lane operacional existem.
- **O que já existe e diz "quando" — medido nos arquivos, não suposto:**
  - **azul:** `site/scripts/freshness.py` grava `public/data/freshness/<produto>.json`
    (`updated_utc`, `checked_utc`, `status`, `detail`) para `alertas` e
    `chuva`, e o próprio robô falha quando um produto passa do limite. É o
    único frescor por produto do projeto hoje.
  - **verde, público:** `status/green/heartbeat.json`
    ([`GREEN_HEARTBEAT_CONTRACT_V1.md`](../contracts/phase2b/GREEN_HEARTBEAT_CONTRACT_V1.md)),
    servido em `/data/green/heartbeat.json`; a página mostra "Automação · …"
    a partir dele. Lido em 2026-10-10: `latest` e `last_success` =
    `ci-37688510058`, 2026-10-07T21:19:55Z, `no_acquisition`.
  - **verde, privado:** `runs/<id>/run.json` por rodada; o ponteiro e o
    histórico (`publish_green_release.py status|history`); os ponteiros de
    contexto e de fontes. Nenhum diz a idade do dado que a página mostra.
  - **site verde:** `built-from.json` do índice nomeia a release de que foi
    composto, e a página recusa um índice de outra release.
- **A série verde não anda sozinha.** A lane de depósito é manual até a virada
  (nenhuma lane verde pode ter cron antes dela — `tests/test_workflow_lanes.py`).
  O último dado é de 2026-10-04; a última tentativa, 2026-10-07. Um frescor
  verde medido hoje vai acusar isso, e está certo.
- **O robô azul do site falha desde 02/10** no job `alertas`, recusando
  publicar uma release azul de 31 dias (PHASE_6X §6). É o azul parado desde
  2026-09-03; o conserto é a virada. Não é desta tarefa.

## 3. A tarefa

**Única tarefa: desenhar e entregar o status e o frescor por produto do
caminho verde — o que a página e um operador leem para saber se cada produto
(alertas, contexto de uso do solo, fontes) está em dia — sem criar um lugar
novo quando um que existe serve.**

1. **Medir primeiro.** Para cada produto verde, qual é a idade que importa
   (data do último dado, não do objeto), quem já a guarda, e onde um operador
   a leria hoje. Escrever a tabela no registro antes de qualquer código.
2. **Desenhar** com base na tabela: estender o batimento, um documento novo
   ao lado (como fontes e contexto), ou só a página — e por quê. Se o desenho
   pedir uma chave pública nova, ela é `delivery/4` com vetores.
3. **Entregar o que for aditivo e inerte** (backend em PR, site em PR **não
   mesclada**), com o "resumo de execução" de uma rodada da lane de depósito
   no próprio log do job, se a medição mostrar que ele não existe.

Se o desenho depender de uma decisão do dono (por exemplo, quais limites de
idade contam como "atrasado" no verde), entregue o desenho com a pergunta e
pare antes de codificar o limite.

**Fora de escopo:** a virada (§4.4 de `PACKAGE_P6_PROMPT.md`); ligar cron em
lane verde; o robô azul do site; Fase 5.

## 4. Decisões de escopo já tomadas, com a base

- **Nenhuma lane verde tem cron antes da virada** — Package 2B.0, teste.
- **Publicar não tem revisor** — `config/phase6_publication_authority_v1.json`,
  dono, 2026-10-02.
- **Fontes e contexto são documentos ao lado da release**, não campos dela —
  PHASE_6V §3; um status novo segue o mesmo raciocínio se for por release.
- **Nada é apagado** — `PACKAGE_P6_PROMPT.md` §5.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- **A `main` do site faz deploy de produção.** Não mescle PR do site.
- Reimplantar o Worker verde é do dono (`scripts/green_worker.sh deploy
  GREEN-ONLY`, da máquina dele).
- **Nenhum Environment é criado, renomeado ou reconfigurado por agente**;
  escrever `environment:` com nome inexistente CRIA um. Use só `v2-promotion`
  ou `v2-staging`.
- `detect_gee.yml` e `update_data.yml` nunca são disparados.
- Claude não recebe credencial de control-plane da Cloudflare.

## 6. Armadilhas já pagas — não redescobrir

- **Um run pendente num grupo de concorrência é cancelado** quando outro entra
  na fila — por isso a lane de fontes não usa o grupo da promoção (PHASE_6X §2).
- **Segredo de Environment não chega a um workflow chamado** — `#102`; use job
  com `environment:` próprio.
- **`config.settings` carrega o `.env` de produção no import**; nenhum script
  verde o importa (guarda transitivo).
- **Um teste de módulo carregado por `importlib` com `@dataclass` precisa
  registrar o módulo em `sys.modules` antes de executá-lo** — custou uma
  rodada na PHASE_6X.
- O hook `commit-msg` recusa um SHA de 40 caracteres de OUTRO repositório.
- Uma varredura de mutação apaga `__pycache__`; uma varredura de texto pega
  docstring — use a AST.

## 7. Estado que o package herda

- Ponteiro verde seq. 18 (107 datas até 2026-10-04); contexto e fontes
  publicados para ele.
- `observatorio-site#46` aberta (rota das fontes + créditos verdes); `#42` em
  rascunho; `#21` "não mesclar antes da Phase 6".
- O azul está parado desde 2026-09-03.
- Espelho só-leitura da release viva (~2,1 GB) no scratchpad da sessão de
  2026-10-10, se ainda existir: útil para pré-visualizar a página
  (`scripts/preview_green.mjs`), mas é cópia — releia o ponteiro antes de usar.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da tarefa ficou para trás. A lista de fontes está publicada e conferida, a
rota que a entrega existe, e a página verde já mostra os créditos a partir
dela — mas essa última parte está numa PR do site que espera você.

### O que você precisa fazer

1. **Revisar e mesclar a PR 46 do site** quando puder. Ela só muda a visão de
   teste (com `?dados=verde`); a página que o público vê continua igual. Pode
   esperar.
2. **Depois de mesclar, reimplantar o servidor de teste** da sua máquina (o
   comando está na §5 deste documento), para que a lista de fontes passe a
   ser entregue. Pode esperar junto com o item 1.
3. **Opcional: apagar os segredos da NASA no repositório do site.** A chuva
   já não os usa desde 8 de outubro, então o prazo de 6 de novembro deixou de
   importar.

### Tem algo preocupante?

Não. O robô do site segue falhando na parte dos alertas, mas é a mesma causa
já conhecida — o sistema antigo está parado desde setembro — e ele falha de
propósito para não publicar dado velho; a chuva continua atualizando.

### O que ainda falta no caminho

- **Status e frescor no sistema novo** — a próxima sessão: mostrar, para cada
  produto, se ele está em dia.
- **A virada** — o site passa a mostrar os dados novos para todo mundo, a
  coleta passa a rodar sozinha, e os textos que ainda falam de 2023 saem.
- **Fase 5** — a validação independente.
