# Phase 6 — onde o estado de persistência vive, a semente no bucket, e a primeira rodada encadeada

Escrito em 2026-09-28, depois de a lane de depósito verde depositar a primeira
rodada real a partir da `main`. Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: é uma pergunta de contrato antes do código. O estado de persistência
> é o que liga uma rodada à seguinte, pesa quase 1 GB, e onde ele for escrito
> fica para sempre. Errar a chave ou a amarração com o `run.json` é pior do que
> não ter lane agendada.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:docs/implementation/PHASE_6F_2026-09-28.md | sed -n '194,256p'
    git show origin/main:.github/workflows/v2_green_deposit_lane.yml | head -5
    git config core.hooksPath .githooks     # uma vez por clone

O PHASE_6F tem de ter as seções 6 (o depósito real) e 7 (a semente). Se não
tiver, a PR deste registro não entrou — decida por conteúdo, não por
ancestralidade.

Suíte medida em 2026-09-28 na branch `claude/p6-deposit-lane-proof`:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **2208** — 2203 + 5 que `tests/test_handoff_prompt_method.py` roda por briefing |

Rode e use o número que sair.

## 2. O que já foi verificado, para o executor não refazer

Em [`../implementation/PHASE_6F_2026-09-28.md`](../implementation/PHASE_6F_2026-09-28.md):

- **A lane existe e funciona.** `v2_green_deposit_lane.yml`, run
  `36432616599`: detecção como `araripe-green-detect`, 4/4 terminais,
  `runs/ci-36432616599/` com 6 objetos, `stage_green_run.py` aceitou, ponteiro
  intocado na sequência 14. Não reprove.
- **A identidade verde é só de computação** (run `36429668172`, 9/9: criar
  asset e exportar são recusados por permissão). Não reabra.
- **A baseline `2.1.0` está no staging**: 72 objetos, 13 626 201 392 bytes,
  igual ao manifesto; a lane baixa só os meses da janela.
- **A lane parte de estado VAZIO** e o passo exige isso
  (`test ! -e …/persistence_state.geojson`). É por isso que o subconjunto
  forte da rodada difere da release (0 contra 1 565 em 25/08): *forte* exige
  dois avistamentos.
- **O estado não está em bucket nenhum.** O `run.json` de cada rodada declara
  só `persistence_state.bytes` e `.sha256`; o objeto não é depositado.
- **A semente existe numa cópia só**: o estado final do replay, 986 744 489
  bytes, sha256 `5eb17f838b35251b3748dbc26310918a8fa7a00ce99b4f3c501dd5887ac987ce`
  — o que `runs/rep-2026-08-30-v3/run.json` declara —, no diretório isolado do
  replay na máquina do dono (fora dos dois repositórios; o caminho não vai
  para documento). Conferido por `shasum -a 256` em 2026-09-28.
- **O ledger é determinístico mesmo com a detecção carimbando horários**:
  `ledger_v3.py` exclui `created_at` da identidade; o ensaio local e o runner
  deram o mesmo `pl-v3-a5439927…`. Os bytes dos alertas diferem.
- **O replay encadeia estado entre lotes em modo `rebuild`**
  (`scripts/replay_2026.py`, `update_tracks(…, mode="rebuild")`); o 2026
  inteiro rodou assim. Se uma rodada encadeada deve usar `rebuild` ou `live`
  **não** foi medido — é pergunta desta sessão.

## 3. A tarefa

Decidir por escrito onde o estado de persistência de uma rodada vive e como
uma rodada nomeia a sua antecessora; pôr a semente no bucket; ensinar a lane a
partir do estado de uma rodada anterior e a depositar o seu; e provar uma
rodada encadeada a partir de `rep-2026-08-30-v3` — sem promover.

## 4. O escopo, na ordem em que se sustenta

1. **As respostas por escrito, antes do código**, num registro novo:
   - a chave do estado: dentro do prefixo da rodada (e então o `run.json`
     passa a listá-lo — mudança de contrato do manifesto da rodada) ou num
     prefixo próprio, imutável e endereçado pela rodada;
   - a amarração: a rodada seguinte recebe `from_run`, lê o `run.json` da
     antecessora e **recusa** um estado cujo sha256 não seja o declarado — a
     amarração já existe no `run.json`, só falta o objeto;
   - `rebuild` ou `live` para uma rodada encadeada, com o código de
     `update_tracks` como fonte, não a prosa;
   - como uma janela encadeada se relaciona com a marca d'água da antecessora
     (sobreposição, lacuna, recusa).
2. **A semente no bucket**: subida única, local, com o profile, conferida
   contra `runs/rep-2026-08-30-v3/run.json` antes de escrever, com
   `put_if_absent`. Só depois do item 1.
3. **A lane**: entrada opcional `from_run`; sem ela, o comportamento de hoje
   (estado vazio). Com ela, o passo que baixa o estado segura só
   `R2_STAGING_*` e não importa `config`. O depósito passa a escrever o estado
   da rodada. Testes por passo, como `tests/test_green_deposit_lane.py`, e a
   varredura de mutação.
4. **Depois do merge:** uma rodada encadeada de `rep-2026-08-30-v3` sobre a
   janela seguinte ao corte (a fila pós-corte medida na Phase 4: 2026-09-02,
   09-04 e 09-07), validada por `stage_green_run.py`. **Não promova.**
5. **Atualize** `revocation_ordering.before_revoking_also` em
   `config/phase6_owner_decisions_v1.json` quando a semente estiver no bucket,
   e **avise o dono** de que a chave local pode ser revogada.

**Fora de escopo, explicitamente:**

- **o agendamento** (Seg/Qui) — vem com a virada;
- **promover** qualquer rodada, ou mover o ponteiro;
- **a virada**, o domínio final, o site;
- **revogar a chave local** — é do dono, depois do aviso;
- **a validação de acurácia** — Phase 5.

## 5. Decisões de escopo já tomadas, com a base

- **Identidade verde de Earth Engine, nunca `GEE_SA_KEY`** — PHASE_6E §1.
- **Dois jobs; no `detect`, só o passo de download segura R2** — PHASE_6F §3.
- **`run_id = ci-<github.run_id>`**, sem a tentativa — PHASE_6E §4.
- **D1** — `araripe-v2-staging` é o bucket verde canônico.
- **Nada é apagado**, em nenhum bucket, nunca.
- **As quatro decisões científicas da Phase 4** não reabrem.

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

## 7. Armadilhas já pagas — não redescobrir

- **Resolva as dependências para Linux antes do runner**:
  `pip install --dry-run --platform manylinux2014_x86_64 --python-version 3.11
  --only-binary=:all: -r requirements-green-detect.txt`. O ambiente conda local
  tem um par `boto3`/`botocore` descasado que o pip recusa (run
  `36432410617`).
- **O contexto `runner` não existe no `env:` de nível de job** do Actions; use
  `$RUNNER_TEMP` no passo.
- **`araripe-green-candidate` já é o grupo de nível de workflow de
  `v2_candidate_replay.yml`**; a lane o segura no job.
- **Mensagem de commit por arquivo**, `git commit -F`; depois de cada push,
  `gh pr list --head <branch> --state all`.
- **Um teste que depende de exceção pode passar pelo motivo errado**: o probe
  captura exceções e as registra como falha. Afirme o efeito, não a exceção.
- **Varredura de código por AST, não por texto**: docstrings nomeiam o que o
  código proíbe.
- **Limpe `__pycache__` e use `PYTHONDONTWRITEBYTECODE=1`** antes de cada
  mutação.

## 8. Estado que o pacote herda

- **PRs `#72`, `#73`, `#74`** mescladas; a deste registro, também.
- **Ponteiro verde:** sequência 14, `rel-g1-fb722b2d…`. Nenhuma release nova.
- **`runs/ci-36432616599/`** no bucket — rodada de estado vazio, não
  comparável com a release.
- **A produção azul está parada** desde 2026-09-03; o conserto é a virada.
- **Achados esperando a sua vez:** o site atribui "Landsat 8/9"; a visão
  completa pesa até 89,1 MiB por data; o índice não tem campo para a última
  tentativa de automação.
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

O depósito automático está pronto e já funcionou de verdade: o sistema novo
rodou a detecção sozinho no GitHub, com a conta nova do Earth Engine, e guardou
o resultado sem mexer na versão que está no ar. Ficou pendente uma coisa que
descobri no fim: o arquivo que liga uma rodada à seguinte — a memória dos
avistamentos de 2026 — existe numa cópia só, no seu computador. A próxima
sessão decide onde ele fica guardado e o coloca lá.

### O que você precisa fazer

1. **Não apagar a pasta `araripe_replay_2026`** da sua pasta pessoal no
   computador. É a única cópia da memória de 2026 até a próxima sessão
   guardá-la. Vale até eu avisar.
2. **Ainda não revogar a chave de testes.** O depósito automático existe, mas
   a próxima sessão ainda precisa dela uma vez, para guardar esse arquivo. Eu
   aviso quando puder.
3. **Abrir a próxima sessão com este documento**, no modelo e esforço do topo.
   Não é urgente.

### Tem algo preocupante?

Sim, dois. O primeiro é o de antes: a detecção automática antiga está parada
desde 3 de setembro, e o site mostra dados de 30 de agosto. O segundo é novo:
a memória de 2026 existe numa cópia só. Se o computador se perder antes da
próxima sessão, dá para refazer — rodando o ano inteiro de novo, cerca de uma
hora —, mas o resultado não seria idêntico ao que a versão publicada declara.

### O que ainda falta no caminho

- **Guardar a memória de 2026 e encadear as rodadas** — a próxima sessão:
  decidir onde fica, guardá-la, e fazer uma rodada continuar de onde a outra
  parou. É o que libera apagar a minha chave.
- **Detecção agendada da versão nova** — duas vezes por semana, a partir
  dessa memória; vem junto com a virada.
- **As páginas do site** — linguagem, fonte (tirar o Landsat), as três datas
  separadas, e as datas muito pesadas.
- **A virada** — o site passa a ler os dados novos no próprio domínio, e só
  depois o caminho antigo é desligado.
- **Fase 5** — a validação independente; até ela, nada é publicado como
  "precisão do sistema".
