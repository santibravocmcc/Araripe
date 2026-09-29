# Phase 6 — promover a release da cadeia por referência no staging, e provar a volta

Reescrito em 2026-09-29, depois da opção H (PHASE_6J): o estado comprimido
está em produção verde, e a release da cadeia passou a ser uma **`/3` por
referência** — um índice das releases `/1` de cada rodada, sem cópia. Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: a forma está decidida pelo dono, construída, testada nos dois
> repositórios e composta do bucket real só leitura (PHASE_6J §3.3). O que
> resta é executar um caminho provado e medir. Se a prova contradisser a
> decisão, **pare e pergunte** — não redesenhe.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:src/publication/chain_release.py | grep -n 'REFERENCE_RELEASE_SCHEMA ='
    git show origin/main:docs/implementation/PHASE_6J_2026-09-29.md | grep -n '^## '
    git config core.hooksPath .githooks     # uma vez por clone

E no site:

    git -C ../site fetch origin
    git -C ../site show origin/main:worker/data_route.js | grep -n 'object_release_unusable'

As duas coisas têm de estar na `main`, e **o Worker verde tem de ter sido
reimplantado pelo dono depois do merge do site** — da máquina dele, no clone
do site atualizado, com o mesmo comando de 2026-09-27
(`scripts/green_worker.sh deploy GREEN-ONLY`, PHASE_6B §1). Esse terceiro fato não se
confere por git: pergunte ao dono, ou leia a data da última implantação que
ele informar. **Sem o Worker novo, não promova**: o Worker antigo, diante de
uma `/3`, procuraria os objetos no prefixo do índice e responderia 503.

Suíte medida em 2026-09-29:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **2449** |
| site | `npm run test:worker` (com `../Araripe` na mesma `main`) | **56** |

Rode e use o número que sair.

## 2. O que já foi verificado, para o executor não refazer

Em [`../implementation/PHASE_6J_2026-09-29.md`](../implementation/PHASE_6J_2026-09-29.md):

- **O estado comprimido está provado ao vivo** (§1.4): `ci-36587297892`
  depositou `run.json /3` e o estado em 259 063 959 bytes para 1 021 260 480;
  a cabeça o lê e o `fetch_state` o infla e confere em 19 s.
- **A `/3` composta do bucket real, só leitura** (§3.3):
  `rel-g3-264ba36ee44bc799fd4fe7f22748d84488469087ec1924e2130ac5b28ba53a02`,
  103 datas até 2026-09-27, zero tombstones contra o ponteiro vivo, grava ~100
  KB e referencia 1,8 GB em 5 membros. Quatro membros ainda não têm a sua
  `/1` publicada; o `publish-chain` publica cada uma antes do índice.
- **A rota do site e a do backend concordam** nos 28 vetores `/2`, e as
  mutações da regra do membro morrem nos dois lados (§3.2).
- **A `/2` fica definida e nunca é produzida** (`GREEN_RELEASE_CONTRACT_V1.md`
  §13). Não a promova.

## 3. A tarefa

Promover a `/3` no staging a partir da `main`, **provar ao vivo** o que a
§3.3 previu, e provar a volta: rollback para a release do replay e promoção
da `/3` de novo.

## 4. O escopo, na ordem em que se sustenta

1. **Ler antes de escrever**: o ponteiro vivo, a cabeça da cadeia e o
   histórico, só leitura. Se a cadeia andou desde 2026-09-29, a `/3` é outra:
   anote qual.
2. **Promover**:

       gh workflow run v2_operational_publish.yml --repo santibravocmcc/Araripe -f source=chain

   Acompanhe com `gh run view <id> --json jobs`. Meça o tempo de cada job: é o
   primeiro dado real do custo de uma promoção por referência.
3. **Conferir ao vivo, só leitura**: ponteiro na sequência seguinte, `/2`,
   nomeando `rel-g3-…`, um `ledgers` por membro; `releases/rel-g3-…/` com
   **só** `release.json` e `ledger.json`; as `/1` dos quatro membros novos
   publicadas; `verify_release` sobre a `/3`; registros de histórico 14 (os
   bytes `/1`) e 15; zero tombstones.
4. **Pelo Worker verde**, se o dono o tiver deixado acessível: `release.json`,
   `ledger.json` e um objeto de setembro respondem 200, e o objeto sai do
   prefixo do membro. Use o verificador do site
   (`scripts/verify_green_route_remote.sh`) só se a janela estiver aberta — a
   abertura é do dono ou do broker, nunca sua por outro caminho.
5. **A volta**: `rollback --to` a release do replay e promover a `/3` de novo.
   Três escritas, três registros, o histórico consistente, e os tombstones do
   rollback nomeando chaves que existem (prefixos `rel-g1-`).
6. **O registro**: um `PHASE_6K` com as medições, e a linha do roadmap.

**Fora de escopo, explicitamente:**

- **a cadência** de detecção e promoção, e o `queue: max` — da virada;
- **as páginas do site**, a fonte (Landsat), as três datas — outro pacote;
- **a retenção** das rodadas cujos membros foram publicados;
- **a validação de acurácia** — Phase 5.

## 5. Decisões de escopo já tomadas, com a base

- **Opção H**: estado comprimido e publicação por referência — decisão do dono
  em 2026-09-29, PHASE_6J.
- **A unidade pública é a release `/1` de cada rodada**; `runs/` continua
  privada — PHASE_6J §2.1.
- **`promote` recusa perder uma data publicada** — PHASE_6I §3.
- **`RELEASE_SCHEMA` e `POINTER_SCHEMA` continuam `/1`** — o freeze da Phase 3.
- **D1**: `araripe-v2-staging` é o bucket verde canônico.
- **Nada é apagado**, em nenhum bucket, nunca.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 6. Fronteiras duras

- A `main` dos dois repositórios é **pull-request-only**, e **a `main` do site
  faz deploy de produção**.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare.
- Nunca nomeie um Environment que não exista; nunca aprove a sua própria
  requisição.
- Claude não recebe credencial de control-plane da Cloudflare; a allowlist do
  broker é exatamente `audit`, `enforce-worker-isolation`,
  `disable-site-branch-deploy`. **Reimplantar o Worker verde não está nela.**
- **Não ligue** `green_site_publish.yml` ao Environment `v2-green-deploy`.
- **`v2_operational_publish.yml` não tem modo "só validar"**: dispará-lo é
  promover.
- **O profile local só lê.**

## 7. Armadilhas já pagas — não redescobrir

- **O `stage` está no grupo `araripe-green-candidate`**, o mesmo do `deposit`:
  um `deposit` pendente é cancelado se o `stage` chegar depois.
- **`publish-chain --expect`** recusa (`chain_moved_since_staging`) se uma
  rodada entrar entre o stage e o promote. Dispare de novo.
- **O `promote` lê os objetos mais de uma vez** — na verificação de cada
  membro, na do índice e dentro do `promote` —, ~1,8 GB cada. Timeout 60 min.
- **Um SHA escrito de memória passa na revisão.** Em 2026-09-29 um SHA de base
  inventado chegou a ser escrito no PHASE_6J e só não entrou porque foi
  relido do `git rev-parse` antes do commit. Copie sempre da ferramenta.
- **O compositor do site da branch local não é o da `main`**: use `git archive
  origin/main scripts worker | tar -x` fora do clone.
- **`gh run view --log` só funciona com o job terminado.**

## 8. Estado que o pacote herda

- **Ponteiro verde:** sequência 14, `/1`, `rel-g1-fb722b2d…` (o replay).
- **Cadeia:** `rep-2026-08-30-v3 -> ci-36456671793 -> ci-36462882711 ->
  ci-36465147834 -> ci-36587297892`, até 2026-09-27. Nenhum `schedule:`.
- **O bucket de staging:** ~22 GB; `baselines_v2` 13,6 GB.
- **Setembro tem alertas reais** em seis datas, nenhuma publicada.
- **A produção azul está parada** desde 2026-09-03; o conserto é a virada.
- **Achados esperando a sua vez:** o site atribui "Landsat 8/9"; o índice não
  tem campo para a última tentativa de automação; as rodadas antigas guardam
  o estado descomprimido (~1 GB cada) e não são reescritas.
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Só publicar. O estado comprimido já está funcionando de verdade, e a
publicação por referência está pronta nos dois lados — o sistema e o site. Ela
não foi feita ainda porque o servidor de testes do site precisa ser
reimplantado com a versão nova antes, e isso só você pode fazer.

### O que você precisa fazer

1. **Reimplantar o servidor de testes do site** (o Worker verde) a partir da
   versão nova do site, do mesmo jeito que você fez em 27/09 — o comando está
   no começo deste documento. Não é urgente,
   mas a publicação espera por isso.
2. **Abrir a próxima sessão com este documento** depois da reimplantação, no
   modelo e esforço do topo, dizendo que ela foi feita.

### Tem algo preocupante?

Não. O custo que preocupava caiu: cada rodada nova guarda um quarto do que
guardava, e publicar passa a gravar só um índice pequeno em vez de copiar
quase 2 GB.

### O que ainda falta no caminho

- **Publicar a cadeia na vitrine de testes** — a próxima sessão, depois da
  reimplantação.
- **Detecção e publicação agendadas** — ligam na virada, com a frequência.
- **As páginas do site** — linguagem, fonte (tirar o Landsat), as três datas.
- **A virada** — o site passa a ler os dados novos no próprio domínio.
- **Fase 5** — a validação independente.
