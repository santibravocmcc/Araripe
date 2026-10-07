# Phase 6 — publicar as fontes da release 2025, e servi-las

Escrito em 2026-10-07, ao fim da sessão que refez a série verde só com o
MapBiomas 2025 ([`PHASE_6W`](../implementation/PHASE_6W_2026-10-07.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: são três peças que mudam a fronteira do que é público — uma lane
> que escreve no staging com a identidade de promoção, o `delivery/3` e uma
> rota do site — e o erro plausível é servir um documento de fontes que não
> descreve a release viva (o contexto ou a release trocaram e o ponteiro de
> fontes ficou para trás).

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C site fetch origin && git -C site rev-parse origin/main
    gh pr list -R santibravocmcc/Araripe --state all --limit 6 --json number,state,mergedAt
    gh pr list -R santibravocmcc/observatorio-site --state all --limit 4 --json number,state,mergedAt

- A PR de registro da PHASE_6W (os registros de fontes sem 2023) tem de estar
  na `main` do backend: `config/green_sources_v1.json` sem nenhum `_2023` e
  com `basis.freeze_path` = `config/phase3_replay_freeze_v2.json`.
- `observatorio-site#43` (o caminho verde sem 2023) e `#42` (ordem dos
  deploys) **não** são pré-requisito.
- Trabalhe num worktree com os cinco caminhos de dado ligados (memória
  `worktree-novo-nao-tem-o-untracked`). Suíte: conda `araripe`. Base medida
  em 2026-10-07 depois da PHASE_6W: **2739**.

## 2. O que já foi verificado, para o executor não refazer

- **Ponteiro verde:** sequência 18,
  `rel-g3-76601bbf1637b777c954f0e5496e6af4b245ae3fdfb9c2114a2a99694a154d00`,
  geração `1.1.0`, 107 datas até 2026-10-04, 19 membros (`ci-37660908253` …
  `ci-37686447368`). Contexto vivo:
  `ctx-g1-dd374bace05f4248d30f99023b7c0d35d713b9ec29d8472939ec4b9cd949d2ad`.
- **O documento de fontes já foi construído localmente** com os 19 ledgers e
  esse contexto: `src-g1-c9dcba5530ae9f83cb1a9d2c82c773a724e2afb3652dd701938279df505d9d9d`,
  10 644 bytes, aceito por `check_sources`, zero lacunas. A lane tem de chegar
  ao **mesmo id** — se não chegar, pare: algo mudou entre as duas leituras.
- **O que o contrato já fixou** (`GREEN_SOURCES_CONTRACT_V1.md` §6):
  `sources/` é privado na fronteira de entrega e "review, never eligible" na
  retenção; servir é `delivery/3` (`/data/green/sources.json`, servido só
  enquanto o ponteiro nomeia a release viva **e** o contexto vivo) e uma rota
  do site. O escritor único de `sources/current.json` existe
  (`src/publication/sources_pointer.py`) e nada o chama.
- **A atribuição repete as citações MapBiomas** quando há contexto (uma linha
  `release`, uma `context`, mesmo texto): a página deve mostrar cada texto uma
  vez. A regra de derivação não muda por isso.
- **O job `context` da `#102` falha** (run 37688757241: os segredos de
  Environment chegaram vazios ao workflow chamado). Até o dono decidir o
  conserto, cada promoção pede `v2_green_context.yml` disparado à mão. A lane
  de fontes **não** deve copiar esse desenho: um job com `environment:`
  próprio, não `workflow_call`.

## 3. A tarefa

**Única tarefa: o documento de fontes da release viva publicado no staging e
servido pela rota verde — lane, `delivery/3` e rota do site, nesta ordem.**

1. **Lane** (backend): `plan` + `apply` em `scripts/plan_green_sources.py` (ou
   um script irmão) que lê a release viva, os ledgers dos membros e o contexto
   vivo do bucket, constrói, escreve `sources/<id>/sources.json` com
   `put_if_absent` e move `sources/current.json` com `sources_pointer.move`.
   Workflow novo, `environment: v2-promotion` (é ato de publicação, como o
   contexto), só da `main`, serializado com a promoção. Os inventários de lane
   nos testes vão falhar — acrescente com o motivo.
2. **`delivery/3`**: a fronteira passa a servir `sources.json` sob a regra do
   §6 do contrato; vetores novos; o Worker verde lê.
3. **Rota do site** (PR **não mesclada**): `/data/green/sources.json` pela
   rota, e os créditos da página verde lidos dele, cada texto uma vez.

Se a peça 3 não couber, entregue 1 e 2 e diga.

**Fora de escopo:** o conserto do job `context` (decisão do dono, §8);
licença dos produtos próprios; a virada.

## 4. Decisões de escopo já tomadas, com a base

- **Fontes ao lado da release**, forma (b) — PHASE_6V §3, mesclada (`#104`).
- **Abandonar 2023 antes da virada** — dono, 2026-10-07; feito (PHASE_6W).
- **Publicar contexto para a geração nova** — PHASE_6W §8: é o único canal
  que nomeia a coleção na página.
- **Nada é apagado** — `PACKAGE_P6_PROMPT.md` §5.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- **A `main` do site faz deploy de produção.** Não mescle PR do site.
- Reimplantar o Worker verde é do dono (`scripts/green_worker.sh deploy
  GREEN-ONLY`, da máquina dele).
- **Nenhum Environment é criado, renomeado ou reconfigurado por agente**;
  escrever `environment:` com nome inexistente CRIA um. Use só
  `v2-promotion` ou `v2-staging`, que existem.
- `detect_gee.yml` e `update_data.yml` nunca são disparados.
- Claude não recebe credencial de control-plane da Cloudflare.

## 6. Armadilhas já pagas — não redescobrir

- **Segredo de Environment não chega a um workflow chamado** sem que o
  chamador os passe — medido na `#102`.
- **`update_tracks` compara a geração**, mas só numa data com alertas —
  PHASE_6W §4; não reafirme o contrário.
- **Uma janela inteira de recusas não gravava estado** — corrigido na `#106`.
- `config.settings` carrega o `.env` de produção no import; nenhum script
  verde o importa (guarda transitivo).
- Uma varredura de mutação apaga `__pycache__`; uma varredura de texto pega
  docstring — use a AST.
- O hook `commit-msg` recusa um SHA de 40 caracteres de OUTRO repositório.

## 7. Estado que o package herda

- Ponteiro verde: seq. 18, release 2025 (§2). A release anotada com 2023
  (`rel-g3-264ba36e…`) fica no staging, privada; rollback para ela é possível.
- `observatorio-site#43` aberta; `#42` em rascunho.
- A produção azul está parada desde 2026-09-03.
- **O token da NASA expira em 2026-11-06.**
- Uma diferença de persistência entre as gerações (uma trilha, 2 fortes em
  407 093 feições) ficou sem causa — PHASE_6W §7. Não é desta tarefa.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Duas coisas. A lista de fontes está pronta e conferida, mas ainda não foi
publicada nem aparece no site — falta construir o caminho que a publica. E a
correção do site que tira 2023 da visão nova está esperando você.

### O que você precisa fazer

1. **Revisar e mesclar a PR 43 do site** quando puder. Ela só muda a visão de
   teste (com `?dados=verde`); a página que o público vê continua igual. Pode
   esperar.
2. **Decidir como consertar a publicação automática do mapa de uso do solo.**
   Depois de cada nova versão dos dados, esse passo precisa ser disparado à
   mão. O conserto mais simples entrega ao passo também as chaves do sistema
   antigo, que ele não usa; a alternativa é separar em dois disparos. Não é
   urgente; enquanto isso, o agente dispara à mão.
3. **Renovar o acesso à NASA antes de 6 de novembro** (até o fim de outubro).
   Sem isso a atualização da chuva para.

### Tem algo preocupante?

Não. A série nova saiu igual à antiga em todas as manchas detectadas; só o
grupo "forte" mudou em duas manchas de um mesmo ponto, de um total de mais de
400 mil, e a causa ficou registrada como não explicada.

### O que ainda falta no caminho

- **Publicar e servir a lista de fontes** — a próxima sessão.
- **Consertar a publicação automática do mapa de uso do solo**, depois da sua
  decisão.
- **A virada** — o site passa a mostrar os dados novos para todo mundo, e os
  textos que ainda falam de 2023 saem junto.
- **Fase 5** — a validação independente.
