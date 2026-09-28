# Phase 6 — como uma cadeia de rodadas vira a release que o site lê

Escrito em 2026-09-28, depois de a cadeia de estado passar a andar sozinha e
alcançar 2026-09-24. Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: é uma pergunta de contrato, e a resposta errada é cara de desfazer.
> Uma release é imutável e eterna (uma publicação científica cita uma), e o
> ponteiro verde só anda para a frente em cobertura. Promover a coisa errada
> uma vez deixa um registro permanente de uma release que não deveria existir.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:docs/implementation/PHASE_6H_2026-09-28.md | grep -n '^## '
    git show origin/main:scripts/resolve_chain_head.py | head -3
    git config core.hooksPath .githooks     # uma vez por clone

O PHASE_6H tem de ter as seções 7 a 10 (as duas duplas, os achados, o que não
foi feito). Se não tiver, a PR do registro da prova não entrou — decida por
conteúdo, não por ancestralidade.

Suíte medida em 2026-09-28:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **2337** — 2332 da PR `#78` + 5 que `tests/test_handoff_prompt_method.py` roda por este briefing |

Rode e use o número que sair.

## 2. O que já foi verificado, para o executor não refazer

Em [`../implementation/PHASE_6H_2026-09-28.md`](../implementation/PHASE_6H_2026-09-28.md):

- **A cabeça é derivada do bucket** — a única folha que os `predecessor`
  desenham a partir de `rep-2026-08-30-v3` (`state_chain.CHAIN_ROOT`). Não há
  ponteiro de cadeia, e a lane 2 continua *"no pointers"* (§1). Não reabra.
- **A segunda filha é recusada no job que escreve**, e o grupo
  `araripe-green-candidate` **serializa** dois `deposit` — medido na §8: o de D
  ficou `pending` de 18:33:37 a 18:35:39 enquanto C depositava e foi recusado
  depois.
- **Um terceiro membro do grupo cancela o pendente** (§8, item 2): a prova de
  `v2_candidate_replay.yml` foi cancelada quando o `deposit` de D chegou.
- **A janela automática** é `[última data do ledger da cabeça + 1,
  min(hoje − 1, início + 16))` (§3). Base medida em 12 rodadas azuis: 91/94
  datas visíveis, ausentes só com ≤ 21,9 h, zero fora de ordem (§0).
- **Janela vazia deposita nada e sai com sucesso**, provado ao vivo (run
  `36466472616`); janela cheia de 16 dias vazia falha (só em teste).
- **A detecção é determinística**: duas execuções da mesma janela deram o
  mesmo `ledger_id` (§7).
- **O azul nunca rodou com `SEARCH_DAYS_BACK = 5`** em produção: as 12 rodadas
  medidas usaram 16 dias (§0, §4).

## 3. A tarefa

Decidir por escrito **o que é a release pública de uma cadeia** e
implementar o que a decisão exigir — **sem promover**, a menos que a decisão
esteja escrita, testada, e o resultado caiba no que a §5 permite.

O fato que obriga a pergunta (PHASE_6H §9, primeiro item): a identidade e o
conteúdo de uma release são função do ledger **de uma rodada**
(`GREEN_RELEASE_CONTRACT_V1.md` §2), e o site lê **uma** release viva
(`src/publication/site_artifact.py`: *"the index spans every date in the
release"*). A release que a cabeça de hoje cunharia cobre **só 2026-09-24**; o
ponteiro aponta para a do replay, que cobre 2026-01-02 … 2026-08-30. Promover
a cabeça como está trocaria oito meses por um dia — e o
`coverage_regression` do contrato **não** pega isso, porque compara só a
última data coberta, que avança (`src/publication/atomic_publish.py`:654-656).

## 4. O escopo, na ordem em que se sustenta

1. **Procure antes de propor.** O roadmap (Phase 6, primeiro bullet: *"from
   the staged release manifest"*), `GREEN_RELEASE_CONTRACT_V1.md`,
   `SITE_ARTIFACT_CONTRACT_V1.md`, `promotion_history.py` (D5) e
   `docs/implementation/` podem já responder. Se responderem, a tarefa é
   implementar, não decidir.
2. **As respostas por escrito, antes do código**, num registro novo. As
   opções que a sessão anterior viu, **sem** ter escolhido:
   - **(a) release acumulada pelo caminho**: a release de uma cabeça é
     construída dos ledgers de toda a cadeia, da raiz até ela. Pergunta: o
     `release_identity` e o schema aceitam mais de um ledger? O
     `replay_2026.py` diz *"the ledger binds one manifest"*;
   - **(b) o ledger encadeado já acumulado**: a rodada carrega adiante as
     linhas da antecessora e o seu ledger cobre tudo. Pergunta: o que isso faz
     à regra da janela (PHASE_6G §4, que lê a *última* data do ledger) e ao
     tamanho do ledger;
   - **(c) o site acumula**: cada release continua sendo uma janela, e o
     índice do site é derivado de várias. Pergunta: o que vira "a release
     viva", o rollback, e a citação de uma publicação;
   - e a guarda, qualquer que seja a escolha: **uma promoção que reduz o
     conjunto de datas publicadas tem de ser recusada**, não só uma que reduz
     a última data.
3. **O código**, com testes por passo e a varredura de mutação.
4. **Só então**, se a decisão permitir e a release resultante cobrir
   2026-01-02 … 2026-09-24 inteiro, avaliar promovê-la **em staging**. Se
   houver qualquer dúvida sobre isso, pare antes e deixe escrito.

**Fora de escopo, explicitamente:**

- **o agendamento** Seg/Qui — vem com a virada, e o `queue: max` (PHASE_6H §9)
  é decisão dela;
- **as páginas do site** e o texto sobre Landsat — outro pacote, no outro
  repositório;
- **a virada**, o domínio final;
- **a retenção dos estados** (~1 GB por rodada);
- **a validação de acurácia** — Phase 5.

## 5. Decisões de escopo já tomadas, com a base

- **Estado no prefixo da rodada, nome fixo** — PHASE_6G §1.
- **`run.json` `/2` com `predecessor` obrigatório** — PHASE_6G §2.
- **Janela = dia seguinte à última data do ledger** — PHASE_6G §4.
- **Cabeça derivada, raiz `rep-2026-08-30-v3`** — PHASE_6H §1.
- **Segunda filha recusada no `deposit`** — PHASE_6H §2, medido na §8.
- **Janela automática termina em hoje − 1** — PHASE_6H §3.
- **Identidade verde de Earth Engine, nunca `GEE_SA_KEY`** — PHASE_6E §1.
- **D1** — `araripe-v2-staging` é o bucket verde canônico.
- **Nada é apagado**, em nenhum bucket, nunca. Uma release publicada é eterna.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 6. Fronteiras duras

- A `main` dos dois repositórios é **pull-request-only**, e **a `main` do site
  faz deploy de produção**.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare.
- Nunca nomeie um Environment que não exista; nunca aprove a sua própria
  requisição.
- Nunca ligue API nem mude permissão no Google.
- Claude não recebe credencial de control-plane da Cloudflare; a allowlist do
  broker é exatamente `audit`, `enforce-worker-isolation`,
  `disable-site-branch-deploy`.
- **Não ligue** `green_site_publish.yml` ao Environment `v2-green-deploy`.
- **`v2_operational_publish.yml` não tem modo "só validar"**: o job `promote`
  segue o `stage`. Dispará-lo é promover.
- **Se o dono já revogou a chave local**, não há leitura local do bucket:
  verifique pelas lanes. Não peça a chave de volta.

## 7. Armadilhas já pagas — não redescobrir

- **Um worktree novo não tem os arquivos não versionados**: a suíte num
  worktree de `origin/main` deu 2250 + 6 falhas + 14 erros = 2270, e as falhas
  são isso, não regressão.
- **`gh run view --log` só funciona com o job terminado**; para acompanhar,
  leia `--json jobs` e os `steps`.
- **O ponteiro verde é `pointers/green/current.json`**, não
  `pointers/green.json`.
- **O Python embutido num passo de workflow se testa executando-o**: extraia
  o texto entre `<<'PY'` e `PY` e rode com um `GITHUB_OUTPUT` temporário —
  `tests/test_green_deposit_lane.py::run_inline`.
- **Mensagem de commit por arquivo**, `git commit -F`; depois de cada push,
  `gh pr list --head <branch> --state all`.
- **Limpe `__pycache__` e use `PYTHONDONTWRITEBYTECODE=1`** antes de cada
  mutação.
- **Um teste que depende de exceção pode passar pelo motivo errado** — afirme
  o efeito (nada escrito, estado não lido).

## 8. Estado que o pacote herda

- **PR `#78`** mesclada (`dc335a9`); a do registro da prova, também.
- **Cadeia:** `rep-2026-08-30-v3 -> ci-36456671793 -> ci-36462882711 ->
  ci-36465147834`, cobre até **2026-09-24**. A próxima data do extent,
  2026-09-27, entra numa rodada `head` a partir de 2026-09-29.
- **Ponteiro verde:** sequência 14, `rel-g1-fb722b2d…` (o replay, até
  2026-08-30). Nenhuma release nova.
- **Setembro tem alertas reais**: seis datas com detecção (09-09, 09-11, 09-14,
  09-19, 09-21, 09-24), nenhuma publicada.
- **A produção azul está parada** desde 2026-09-03; o conserto é a virada.
- **Achados esperando a sua vez:** o site atribui "Landsat 8/9"; a visão
  completa pesa até 89,1 MiB por data; o índice não tem campo para a última
  tentativa de automação; cada rodada guarda ~1 GB de estado para sempre; o
  cancelamento do pendente no grupo (PHASE_6H §9).
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada ficou pela metade. O sistema novo agora escolhe sozinho de onde
continuar, recusa continuar a mesma coisa duas vezes — isso foi testado de
verdade, com duas rodadas disputando o mesmo lugar — e alcançou o dia 24 de
setembro. A imagem do dia 27 fica para amanhã de propósito: o sistema espera
um dia a mais para ter certeza de que o satélite já entregou tudo.

### O que você precisa fazer

1. **Nada é urgente.** A chave de testes continua podendo ser revogada quando
   você quiser; esta sessão a usou só para ler e conferir.
2. **Abrir a próxima sessão com este documento**, no modelo e esforço do topo.

### Tem algo preocupante?

Um, o mesmo de antes, agora mais concreto: o site ainda mostra dados até 30
de agosto, e agora sabemos que setembro tem alertas de verdade em seis datas.
Eles estão guardados e conferidos, mas ainda não podem ir para o site: do
jeito que as coisas estão, publicar a rodada nova apagaria da tela os oito
meses anteriores. Resolver isso é exatamente a próxima sessão.

### O que ainda falta no caminho

- **A cadeia virar a publicação** — a próxima sessão: decidir como as rodadas
  somadas viram o que o site mostra, sem perder o histórico.
- **Detecção agendada da versão nova** — duas vezes por semana; já está
  pronta para ser ligada, e liga junto com a virada.
- **As páginas do site** — linguagem, fonte (tirar o Landsat), as três datas
  separadas, e as datas muito pesadas.
- **A virada** — o site passa a ler os dados novos no próprio domínio, e só
  depois o caminho antigo é desligado.
- **Fase 5** — a validação independente; até ela, nada é publicado como
  "precisão do sistema".
