# Phase 6 — promover a release da cadeia no staging, e provar a volta

Escrito em 2026-09-28, depois de decidir e construir a release pública de uma
cadeia (`araripe.green.release/2`). Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: a forma já está decidida, testada e composta do bucket real só
> leitura (PHASE_6I §8). O que resta é executar um caminho provado e medir com
> cuidado. Não é pergunta de contrato; é prova ao vivo. Se a prova contradisser
> a decisão, **pare e pergunte** — não redesenhe.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:src/publication/chain_release.py | head -3
    git show origin/main:docs/implementation/PHASE_6I_2026-09-28.md | grep -n '^## '
    git log origin/main --grep 'release de cadeia' --oneline
    git config core.hooksPath .githooks     # uma vez por clone

O `chain_release.py` tem de existir na `main`, e o PHASE_6I tem de ter as
seções 0 a 10. **Se não existir, a PR não foi mesclada pelo dono: pare.** Não
mescle você mesmo — a PR não é a mínima e inerte que a política deixa o agente
mesclar (PHASE_6I §10), e a promoção só roda da `main`.

Suíte medida em 2026-09-28:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **2405** na branch da PR (2337 na base) |

Rode e use o número que sair.

## 2. O que já foi verificado, para o executor não refazer

Em [`../implementation/PHASE_6I_2026-09-28.md`](../implementation/PHASE_6I_2026-09-28.md):

- **Por que (a)** e não (b) nem (c), e por que copiar e não referenciar (§2).
  Não reabra.
- **As constantes `/1` não mudam** — o freeze da Phase 3 as fixa e o
  `replay_2026.py` recusa detectar se mudarem (§0, §4). O teste
  `test_the_version_one_contract_and_its_constants_are_untouched` roda o
  `freeze.load_freeze()`.
- **A release que a cadeia compõe hoje, só leitura, do bucket real** (§8):
  `rel-g2-a24441c9ee5a84179af16578400ef7db15333943c30ee03a670b28d708c45ee4`,
  102 datas, 2026-01-02 … 2026-09-24, 84 objetos (1 804 054 886 bytes),
  `ledger.json` de 60 533 651 bytes; contra o ponteiro vivo: nenhuma data
  perdida, zero tombstones, 72/72 objetos carregados byte a byte. Composição
  local em 265 s.
- **O site não precisa mudar** (§8): compositor e rota da `origin/main` do site
  compõem e servem uma `/2` de fixture.
- **A guarda nova** recusa promover a release da cabeça sozinha
  (`coverage_dates_dropped`) — o caso que motivou o pacote, em teste.
- **Mutação**: 33, 32 mortas, M15 equivalente e explicada (§9).

## 3. A tarefa

Promover a release da cadeia no staging a partir da `main`, **provar ao vivo**
o que a §8 do PHASE_6I previu, e provar a volta: rollback para a release do
replay e promoção da cadeia de novo — as duas direções com o ponteiro `/2`.

## 4. O escopo, na ordem em que se sustenta

1. **Ler antes de escrever.** O ponteiro vivo (sequência, versão, release), a
   cabeça da cadeia (`resolve_chain_head.py` ou a leitura só leitura da §8) e o
   histórico (`publish_green_release.py history` não roda local sem a
   identidade de promoção — leia os registros com o profile, só leitura). Se a
   cadeia andou desde 2026-09-28, a release é outra: anote qual.
2. **Promover**:

       gh workflow run v2_operational_publish.yml --repo santibravocmcc/Araripe -f source=chain

   Acompanhe com `gh run view <id> --json jobs` (o `--log` só com o job
   terminado). Meça o tempo de cada job e o pico: é o primeiro dado real do
   custo de uma promoção de cadeia.
3. **Conferir ao vivo, só leitura**: ponteiro na sequência seguinte, `/2`,
   com um `ledgers` por membro e a cobertura inteira; o prefixo
   `releases/rel-g2-…/` com `release.json`, `ledger.json` e os objetos;
   `verify_release` sobre ele; os registros de histórico do `/1` substituído
   (byte a byte) e do `/2` novo; zero tombstones.
4. **A volta**: `rollback --to` a release do replay e, em seguida, promover a
   cadeia de novo (a lane com `source=chain` de novo). Três escritas, três
   registros, o histórico consistente. Hoje isso só está provado no store
   falso (`test_rollback_from_a_chain_release_to_the_root_names_both`).
5. **O registro**: um `PHASE_6J` com as medições, e a linha do roadmap
   atualizada.

**Fora de escopo, explicitamente:**

- **a cadência de promoção** e o agendamento Seg/Qui — da virada; mas registre
  o custo medido, que é o insumo dela (PHASE_6I §5);
- **uma `/3` com referências em vez de cópias** — só quando a rota puder mudar;
- **as páginas do site**, a fonte (Landsat), as três datas — outro pacote;
- **a retenção** das cópias e dos estados;
- **a validação de acurácia** — Phase 5.

## 5. Decisões de escopo já tomadas, com a base

- **A release de cadeia é (a), `/2`, autocontida por cópia** — PHASE_6I §2.
- **`promote` recusa perder uma data publicada**; ir para trás é `rollback`
  — PHASE_6I §3.
- **Ponteiro escrito como `/2`; leitores aceitam `/1` e `/2`** — PHASE_6I §4.
- **`RELEASE_SCHEMA` e `POINTER_SCHEMA` continuam `/1`** — o freeze.
- **Cabeça derivada, raiz `rep-2026-08-30-v3`** — PHASE_6H §1.
- **D1**: `araripe-v2-staging` é o bucket verde canônico.
- **Nada é apagado**, em nenhum bucket, nunca.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 6. Fronteiras duras

- A `main` dos dois repositórios é **pull-request-only**, e **a `main` do site
  faz deploy de produção**. Nada no site muda neste pacote.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare.
- Nunca nomeie um Environment que não exista; nunca aprove a sua própria
  requisição.
- Claude não recebe credencial de control-plane da Cloudflare; a allowlist do
  broker é exatamente `audit`, `enforce-worker-isolation`,
  `disable-site-branch-deploy`.
- **Não ligue** `green_site_publish.yml` ao Environment `v2-green-deploy`.
- **`v2_operational_publish.yml` não tem modo "só validar"**: o job `promote`
  segue o `stage`. Dispará-lo é promover.
- **O profile local só lê.** A promoção roda na lane, com a identidade de
  promoção. Se o dono já revogou a chave local, verifique pelas lanes e não a
  peça de volta.

## 7. Armadilhas já pagas — não redescobrir

- **O `stage` está no grupo `araripe-green-candidate`**, o mesmo do `deposit`:
  um `deposit` pendente é cancelado se o `stage` chegar depois (PHASE_6H §9).
  Não dispare os dois juntos.
- **`publish-chain --expect`** recusa (`chain_moved_since_staging`) se uma
  rodada entrar entre o stage e o promote. É a recusa certa; dispare de novo.
- **O `promote` lê o corpo inteiro duas vezes** (`verify_release` no
  `_publish_verify_promote` e de novo dentro do `promote`) — ~1,8 GB cada.
  O timeout do job é 60 min por isso.
- **O ponteiro verde é `pointers/green/current.json`**; o histórico,
  `pointers/green/history/<10 dígitos>.json`.
- **`gh run view --log` só funciona com o job terminado.**
- **Mensagem de commit por arquivo**, `git commit -F`; depois de cada push,
  `gh pr list --head <branch> --state all`.
- **Limpe `__pycache__` e use `PYTHONDONTWRITEBYTECODE=1`** antes de cada
  mutação.
- **O compositor do site da branch local não é o da `main`**: o clone do site
  estava em `claude/route-reader-user-agent`. Para rodar o da `main`, `git
  archive origin/main scripts worker | tar -x` fora do clone.

## 8. Estado que o pacote herda

- **PR desta sessão** aberta, **não mesclada** — a promoção depende dela.
- **Ponteiro verde:** sequência 14, `/1`, `rel-g1-fb722b2d…` (o replay).
- **Cadeia:** `rep-2026-08-30-v3 -> ci-36456671793 -> ci-36462882711 ->
  ci-36465147834`, até 2026-09-24. Nenhum `schedule:`; a cadeia só anda por
  despacho.
- **Setembro tem alertas reais** em seis datas, nenhuma publicada.
- **A produção azul está parada** desde 2026-09-03; o conserto é a virada.
- **Achados esperando a sua vez:** cada release de cadeia copia o histórico
  inteiro (PHASE_6I §5); o site atribui "Landsat 8/9"; o índice não tem campo
  para a última tentativa de automação; cada rodada guarda ~1 GB de estado; a
  retenção não sabe que uma release de cadeia contém os objetos das rodadas.
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Uma coisa, de propósito: colocar os dados novos na vitrine de testes. Está
tudo pronto e conferido — o sistema agora junta todas as rodadas numa
publicação só, com os oito meses antigos e setembro juntos, e se recusa a
publicar algo que apague datas já publicadas. Mas publicar é para sempre, e a
forma nova foi decidida nesta sessão; eu preferi que você a visse antes.

### O que você precisa fazer

1. **Ler e mesclar a PR desta sessão.** Não é urgente, mas os alertas de
   setembro só chegam à vitrine de testes depois disso. O documento de
   decisão explica em poucas páginas o que foi escolhido e por quê.
2. **Abrir a próxima sessão com este documento**, depois do merge, no modelo e
   esforço do topo. Ela faz a publicação e a prova.

### Tem algo preocupante?

Um custo, não um risco: do jeito escolhido, cada publicação guarda uma cópia
completa do histórico, hoje perto de 2 GB. Se publicarmos duas vezes por
semana, isso soma algo como 300 GB no primeiro ano, e nada é apagado. Não é
urgente — a frequência das publicações é decidida na virada, e publicar uma
vez por semana, ou só quando há alerta novo, reduz muito. Mas vale decidir
com esse número na mão.

### O que ainda falta no caminho

- **Publicar a cadeia na vitrine de testes** — a próxima sessão, depois do
  merge.
- **Detecção agendada da versão nova** — duas vezes por semana; pronta, liga
  junto com a virada, e junto com ela a frequência das publicações.
- **As páginas do site** — linguagem, fonte (tirar o Landsat), as três datas
  separadas, e as datas muito pesadas.
- **A virada** — o site passa a ler os dados novos no próprio domínio, e só
  depois o caminho antigo é desligado.
- **Fase 5** — a validação independente; até ela, nada é publicado como
  "precisão do sistema".
