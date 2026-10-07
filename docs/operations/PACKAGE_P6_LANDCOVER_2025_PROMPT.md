# Phase 6 — abandonar o MapBiomas 2023: anotação 2025 numa geração nova, e só então as fontes

Escrito em 2026-10-07, ao fim da sessão que desenhou o documento de fontes
([`PHASE_6V`](../implementation/PHASE_6V_2026-10-07.md)), depois de uma
decisão do dono tomada na mesma sessão.
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: é uma troca de método sobre uma série publicável. O erro plausível
> é reprocessar o histórico com os rótulos de 2025 **sob os mesmos ids** — o
> id de uma observação e de uma release não lê o uso do solo — e bater em
> `ImmutableObjectConflict` no meio do depósito, ou, pior, escrever uma
> geração nova que o encadeamento trata como continuação da antiga.

---

## 0. A decisão que muda o plano

**Decisão do dono, 2026-10-07, no chat da sessão PHASE_6V:** *"reescreva o
briefing para já fazermos todas essas trocas e abandonar ao máximo 2023."*
A base que ele deu: **ninguém usou os dados ainda** — não há citação nem
download a proteger.

Isso substitui duas coisas registradas antes:

- a recomendação da PHASE_6T §4.2 e da memória de 2026-10-04 ("manter 2023 e
  migrar na Phase 5");
- a recusa de 2026-10-06 de "reprocessar o histórico com a versão do uso do
  solo" (`GREEN_CONTEXT_CONTRACT_V1.md` §1, alternativas recusadas): ela valia
  enquanto havia uma série publicada a proteger; o dono diz que não há.

O que **não** muda: nada é apagado (`PACKAGE_P6_PROMPT.md` §5). As releases
`rel-g1-…`/`rel-g3-…` anotadas com 2023 ficam no staging, privadas, e nunca
viram públicas.

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C site fetch origin && git -C site rev-parse origin/main
    gh pr list -R santibravocmcc/Araripe --state all --limit 6 --json number,state,baseRefName,mergedAt
    gh pr list -R santibravocmcc/observatorio-site --state all --limit 4 --json number,state,baseRefName,mergedAt

- **`Araripe#104`** (o documento de fontes, PHASE_6V) é pré-requisito do passo
  6, não dos passos 1-5. Se ainda estiver aberta, ramifique da `main` e deixe
  a parte de fontes para o fim — ou peça ao dono para mesclá-la antes.
- **`observatorio-site#42`** (ordem dos deploys, rascunho) não é pré-requisito.
- O checkout compartilhado do `Araripe` pode estar com outra sessão. Trabalhe
  num worktree com os cinco caminhos de dado ligados (memória
  `worktree-novo-nao-tem-o-untracked`). Suíte: conda `araripe`
  (`/opt/anaconda3/envs/araripe/bin/python -m pytest`); o `python3` do sistema
  não tem `loguru`. Base medida em 2026-10-07: 2665 na `main`, 2717 com a #104.

## 2. O que já foi verificado, para o executor não refazer

- **Onde 2023 está hoje**, lido em 2026-10-07:
  - **detector**: `config/settings.py` `LANDCOVER_RASTERS` →
    `mapbiomas10m_araripe_2023.tif` (Coleção 2 beta) e
    `mapbiomas30m_araripe_2023.tif` (≈ 300 m, linhagem não recuperada),
    aplicados por `annotate_alerts_all_collections` em `scripts/replay_2026.py`;
  - **freeze**: `config/phase3_replay_freeze_v1.json`, grupo `mapbiomas`,
    fotografa os dois por caminho e bytes (sem sha256); `replay_2026.py`
    recusa detectar quando o freeze diverge;
  - **releases**: as colunas `lc_*` dos alertas e o objeto forte de cada data
    (filtro `lc_natural_frac_10m >= 0.5`);
  - **site** (`main`): `alertas.html:123-124`, um seletor "10 m · Coleção 2
    (2023)" / "~300 m · Coleção 10 (2023)"; o crédito em `alertas.html:298` e
    `dados-abertos.html:121` ("A fração de vegetação natural de cada alerta foi
    calculada com as versões anteriores … ambas de 2023"); o recuo da página
    para os rótulos da release quando o contexto não está vivo;
  - **a página pública de produção** ainda lê o azul, anotado com 2023 — isso
    só muda na virada.
- **Os recortes 2025 já existem e estão rastreados**:
  `data/landcover/mapbiomas_col4_10m_2025_araripe.tif` e
  `mapbiomas_col11_30m_2025_araripe.tif`, cada um com `.report.json`
  (registro de fontes, adição de 2026-10-06). As tabelas de classe em
  `src/detection/landcover.py` já têm os códigos de 2026
  (`tests/test_mapbiomas_2025_crops.py`).
- **O efeito medido** (adição de 2026-10-06): no extent, 84,01% dos pixels de
  10 m mantêm o grupo; natural 63,55% → 69,65%. O forte sob 2025 já foi
  calculado para a release viva pela camada de contexto (`ctx-g1-e11ea3f3…`,
  forte 75 796) — é a melhor previsão do que a geração nova dará.
- **Ids não leem o uso do solo**: `observation_id` = f(aquisição, geometria,
  `algorithm_version`, `baseline_version`) (`src/detection/identity_v3.py`);
  `release_identity` = f(ledger). Uma nova geração **precisa** mudar uma
  entrada de identidade — o candidato natural é `algorithm_version`
  (`config/phase3_replay_freeze_v1.json`, `detection_algorithm_version`
  `1.0.0`), que também é membro da "geração" de uma cadeia
  (`chain_release._GENERATION`, PHASE_6H §1: geração nova = raiz nova).
  **Confirme isso medindo antes de escrever**, não por este parágrafo.
- **Custo de GEE** do replay: ~3% da cota de um mês (memória
  `araripe-cota-gee-medida-e-a-licao-do-proxy`) — não é bloqueio.

## 3. A tarefa

**Única tarefa: a geração verde nova anotada só com o MapBiomas 2025, com o
histórico reprocessado, publicada no staging e promovida; o site sem nenhuma
menção a 2023 nos caminhos verdes; e o documento de fontes publicado para
ela, sem registro de 2023.**

1. **Medir** onde a troca entra numa identidade (§2, último item) e escrever
   a decisão: qual campo muda (`algorithm_version` → `1.1.0`, ou outro com
   evidência), e por que a cadeia a trata como raiz nova.
2. **Detector**: `LANDCOVER_RASTERS` apontando para os recortes 2025; freeze
   novo (`phase3_replay_freeze_v2.json`, ou o que `src/replay/freeze.py`
   prescrever) fotografando-os **por sha256**, não só bytes; a regra do forte
   inalterada (0,5 sobre o 10 m) — só a fonte muda. Os arquivos 2023 ficam no
   repositório (o histórico os referencia), mas nenhum código os lê.
3. **Reprocessar o histórico** pela lane de depósito existente, numa raiz
   nova, de 2026-01-02 até a data mais recente; compor a release, publicar no
   staging e promover — a publicação operacional já faz isso. Comparar o forte
   resultante com o 75 796 do contexto e explicar a diferença.
4. **Camada de contexto**: com a anotação já em 2025, o contexto para a
   geração nova seria redundante. Decida com evidência entre não publicar
   contexto para ela (e o site sem contexto vivo usar os rótulos da release,
   que agora são 2025) ou manter a lane para o próximo MapBiomas (2026, em
   2027). Recomendação desta sessão: **manter a lane** — é ela que evita uma
   geração nova a cada coleção anual — e não publicar contexto enquanto a
   receita for idêntica à anotação.
5. **Site** (PR **não mesclada**): o seletor sem as opções 2023, o crédito sem
   a frase "versões anteriores … 2023", as legendas da fração natural nomeando
   2025. A página pública azul não muda até a virada.
6. **Fontes** (depende da `#104`): tirar do `config/green_sources_v1.json` os
   dois registros `release_annotation` de 2023 e pôr os de 2025 nesse papel,
   amarrados ao freeze novo por sha256 — as sete lacunas somem. Uma mudança no
   spec já dá id novo; se `derive` mudar, troque `DERIVATION`. Publicar o
   documento para a release nova pela lane de fontes (lane + `delivery/3` +
   rota do site) — se não couber nesta sessão, deixe para a próxima e diga.

**Fora de escopo:** mudar o limiar do forte ou qualquer afirmação de acurácia
(**Phase 5**); a virada; apagar qualquer objeto; a licença dos produtos.

## 4. Decisões de escopo já tomadas, com a base

- **Abandonar 2023 antes da virada** — dono, 2026-10-07 (§0).
- **Fontes ao lado da release** — PHASE_6V §3 (forma b).
- **Nada é apagado** — `PACKAGE_P6_PROMPT.md` §5.
- **P2 = (a)**, ordem dos deploys desenhada (PHASE_6U).

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- **A `main` do site faz deploy de produção.** Não mescle PR do site.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare — o reprocessamento é pela lane **verde** de
  depósito.
- Claude não recebe credencial de control-plane da Cloudflare; o broker só tem
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Nenhum Environment é criado, renomeado ou reconfigurado por agente**, e
  escrever `environment:` com um nome inexistente CRIA um. Nunca aprove um
  Environment.
- O ponteiro verde se move por promoção normal; um rollback para a `rel-g3-`
  continua possível e não deve ser bloqueado.

## 6. Armadilhas já pagas — não redescobrir

- **Ids que não leem o dado que mudou**: mesma chave, bytes diferentes,
  `ImmutableObjectConflict` (PHASE_6V §2; contexto §1). Meça a identidade antes
  de depositar.
- **`config.settings` carrega o `.env` de produção no import** — nenhum
  script verde pode importá-lo (memória `config-settings-carrega-o-env-de-producao`).
- **O freeze é selado** (`freeze_sha256`); regere-o com
  `scripts/snapshot_replay_freeze.py`, não à mão.
- **Linhagem ambígua bloqueia o replay** — a regra (c) do dono está em vigor
  (memória `araripe-regra-de-linhagem-do-dono`).
- **Um guarda de inventário vai falhar** com módulos ou lanes novos; acrescente
  com o motivo, não afrouxe.
- **Uma varredura de mutação tem de apagar `__pycache__`**; varredura de texto
  pega docstring — use a AST.
- **O hook `commit-msg` recusa um SHA de 40 caracteres de OUTRO repositório.**

## 7. Estado que o package herda

- **Ponteiro verde:** sequência 17, `rel-g3-264ba36e…` (anotada com 2023), 103
  datas até 2026-09-27; contexto `ctx-g1-e11ea3f3…` (2025) vivo para ela.
- **Fontes:** nenhum documento publicado; `Araripe#104` aberta ou mesclada.
- **`observatorio-site#42`** em rascunho.
- **A produção azul está parada** desde 2026-09-03.
- **O token da NASA expira em 2026-11-06.**

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da tarefa. A lista de fontes ficou pronta e guardada. Por sua decisão, ela
só vai ser publicada depois que os dados forem refeitos sem o mapa de 2023.

### O que você precisa fazer

1. **Mesclar a PR 104 do monitoramento**, se concorda com a lista de fontes
   num documento separado. Não muda nada para o público. A próxima sessão
   precisa dela só no final.
2. **Renovar o acesso à NASA antes de 6 de novembro** (até o fim de outubro).
   Sem isso a atualização da chuva para.

### Tem algo preocupante?

Não. Refazer o histórico custa pouco da cota do Google e não toca no site
público; o que muda é que o grupo de alertas "fortes" vai mudar de tamanho, e a
próxima sessão vai medir e explicar quanto.

### O que ainda falta no caminho

- **Refazer os dados só com o mapa de 2025** e tirar 2023 do site — a próxima
  sessão.
- **Publicar e servir a lista de fontes** para os dados refeitos.
- **A virada** — o site passa a mostrar os dados novos para todo mundo, e o
  caminho antigo é desligado.
- **Fase 5** — a validação independente.
