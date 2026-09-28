# Phase 6 — qual rodada é a cabeça da cadeia, a fila até hoje, e a lane pronta para agendar

Escrito em 2026-09-28, depois de a primeira rodada encadeada continuar o estado
do replay de 2026 a partir do bucket. Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: de novo uma pergunta de contrato antes do código. Hoje um humano
> escolhe a antecessora a cada disparo; um agendamento não pode. Escolher a
> cabeça errado — ou deixar a cadeia bifurcar — faz duas rodadas reivindicarem
> as mesmas datas, e isso só aparece depois, numa release.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:docs/implementation/PHASE_6G_2026-09-28.md | grep -n '^## '
    git show origin/main:src/publication/state_chain.py | head -5
    git config core.hooksPath .githooks     # uma vez por clone

O PHASE_6G tem de ter as seções 6 a 10 (o código, a semente, a rodada
encadeada, os achados). Se não tiver, a PR do registro da prova não entrou —
decida por conteúdo, não por ancestralidade.

Suíte medida em 2026-09-28 na branch `claude/p6-state-chain-proof`:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **2270** — 2265 + 5 que `tests/test_handoff_prompt_method.py` roda por briefing |

Rode e use o número que sair.

## 2. O que já foi verificado, para o executor não refazer

Em [`../implementation/PHASE_6G_2026-09-28.md`](../implementation/PHASE_6G_2026-09-28.md):

- **Onde o estado vive está decidido e em uso**: `runs/<run_id>/persistence_state.geojson`,
  nome fixo, amarrado pelo `persistence_state` do `run.json`; fora de `objects`.
  Não reabra (§1).
- **A janela encadeada é "dia seguinte à última data do ledger da
  antecessora"** — sobreposição e lacuna recusadas antes de baixar o estado
  (§4). Provado com caso real: a rodada `ci-36456671793` tem marca d'água
  interna 2026-08-30 e ledger até 2026-09-07; a próxima aceita **só**
  2026-09-08.
- **`rebuild` e `live` são o mesmo comportamento** — `mode` é validado e nunca
  lido em `update_tracks`; um teste exige estados byte-idênticos (§3).
- **A semente está no bucket**, conferida pelo caminho do consumidor (§7).
- **A cadeia funciona na lane**: run `36456671793`, `from_run=rep-2026-08-30-v3`,
  depositou `runs/ci-36456671793/` com `predecessor` no `run.json` e o próprio
  estado (§8). A fila pós-corte (09-02, 09-04, 09-07) deu **três
  `rejected_low_coverage`** — nenhuma data observável.
- **Carregar e regravar o estado é byte-idêntico**, em macOS e no runner
  Linux; pico de 4,4 GB de memória, runner com 15 GB (§6, §8).
- **O passo que lê a semente não aceita a chave local** (`fetch_green_state.py`
  sem `profile_fallback`); a D1 diz que nada mais espera a revogação.

## 3. A tarefa

Decidir por escrito como uma rodada **sem humano** encontra a sua antecessora e
recusa uma segunda filha; implementar; alcançar o presente com rodadas
encadeadas a partir de `ci-36456671793`; e deixar a lane pronta para um
agendamento **sem ligá-lo** — sem promover.

## 4. O escopo, na ordem em que se sustenta

1. **As respostas por escrito, antes do código**, num registro novo:
   - **a cabeça**: um objeto mutável (um ponteiro de cadeia, escrita
     condicional) ou derivada do bucket (seguir os `predecessor` a partir de
     `rep-2026-08-30-v3` e exigir exatamente uma folha). A lane 2 hoje é
     *"no pointers"* (`GREEN_CONCURRENCY_LANES.md`), então a primeira opção
     muda a definição da lane e tem de dizer qual identidade escreve o
     ponteiro;
   - **a bifurcação** (PHASE_6G §9): duas execuções com o mesmo `from_run`
     hoje passam as duas. O depósito roda no grupo `araripe-green-candidate`,
     serializado — então "recusar se outra rodada já nomeia esta antecessora"
     cabe no job que escreve, antes do primeiro byte. Meça se o grupo de fato
     serializa os dois `deposit`, não suponha;
   - **o fim da janela automática**: hoje é entrada; agendada, é "hoje" — e o
     limite de 16 dias da lane precisa de resposta para uma fila maior que
     isso;
   - **a relação com a janela de 5 dias do azul** (`SEARCH_DAYS_BACK = 5`):
     o PHASE_6G §9 argumenta que a regra da cadeia a substitui; confirme ou
     refute pelo código de `detect_gee.yml`/`run_detection_from_gee.py`.
2. **O código**, com testes por passo e a varredura de mutação.
3. **Alcançar o presente**, depois do merge: rodadas encadeadas a partir de
   `ci-36456671793`, começando em **2026-09-08**, janelas de até 16 dias, cada
   uma validada por `stage_green_run.py`. **Não promova.**
4. **O modo agendável**, se o item 1 o permitir: a lane aceita rodar sem
   `from_run` explícito e escolhe a cabeça sozinha — **sem** `schedule:` no
   workflow.

**Fora de escopo, explicitamente:**

- **ligar o agendamento** (Seg/Qui) — vem com a virada;
- **promover** qualquer rodada, ou mover o ponteiro verde;
- **a virada**, o domínio final, as páginas do site;
- **a retenção dos estados** de rodadas que já têm sucessora (PHASE_6G §9) —
  registrar, não resolver;
- **a validação de acurácia** — Phase 5.

## 5. Decisões de escopo já tomadas, com a base

- **O estado vive no prefixo da rodada, nome fixo** — PHASE_6G §1.
- **`run.json` `/2` com `predecessor` obrigatório** — PHASE_6G §2.
- **Janela = dia seguinte à última data do ledger** — PHASE_6G §4.
- **`rebuild`** para rodadas encadeadas — PHASE_6G §3.
- **Identidade verde de Earth Engine, nunca `GEE_SA_KEY`** — PHASE_6E §1.
- **`run_id = ci-<github.run_id>`**, sem a tentativa — PHASE_6E §4.
- **D1** — `araripe-v2-staging` é o bucket verde canônico.
- **Nada é apagado**, em nenhum bucket, nunca.

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
- **Se o dono já revogou a chave local**, não há leitura local do bucket:
  verifique pelas lanes (os logs de `fetch_green_state.py` e
  `stage_green_run.py` imprimem o que foi lido). Não peça a chave de volta.

## 7. Armadilhas já pagas — não redescobrir

- **O estado ~1 GB passa entre os jobs como artifact**; o `plan` e o `apply`
  leem-no inteiro na memória. Cabe hoje; confira o pico se a cadeia crescer.
- **Um PUT único no R2 aceita até 5 GiB − 5 MiB**; o depósito recusa acima
  disso com a mensagem certa (`state_exceeds_single_put`). Não é para já.
- **Expansão de array vazio sob `set -u`**: use `${ARR[@]+"${ARR[@]}"}`;
  funciona até no bash 3.2 do macOS.
- **Resolva as dependências para Linux antes do runner**:
  `pip install --dry-run --platform manylinux2014_x86_64 --python-version 3.11
  --only-binary=:all: -r requirements-green-detect.txt`.
- **O contexto `runner` não existe no `env:` de nível de job**; use
  `$RUNNER_TEMP` no passo.
- **Mensagem de commit por arquivo**, `git commit -F`; depois de cada push,
  `gh pr list --head <branch> --state all`.
- **Um teste que depende de exceção pode passar pelo motivo errado** — afirme
  o efeito (nada escrito, estado não lido). Na #76, M16 sobreviveu porque o
  teste mudava duas coisas de uma vez.
- **Limpe `__pycache__` e use `PYTHONDONTWRITEBYTECODE=1`** antes de cada
  mutação.

## 8. Estado que o pacote herda

- **PR `#76`** mesclada (`f9ac8a6`); a do registro da prova, também.
- **Cabeça atual da cadeia:** `ci-36456671793`, cobre até 2026-09-07; a
  próxima começa em 2026-09-08.
- **Ponteiro verde:** sequência 14, `rel-g1-fb722b2d…`. Nenhuma release nova.
- **`runs/ci-36432616599/`** no bucket — rodada de estado vazio, sem estado
  depositado; não serve de antecessora (recusada por `predecessor_state_absent`).
- **A produção azul está parada** desde 2026-09-03; o conserto é a virada.
- **Achados esperando a sua vez:** o site atribui "Landsat 8/9"; a visão
  completa pesa até 89,1 MiB por data; o índice não tem campo para a última
  tentativa de automação; cada rodada guarda ~1 GB de estado para sempre.
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da tarefa ficou pela metade. A memória dos avistamentos de 2026 agora
está guardada no armazenamento do sistema novo, conferida byte a byte, e o
sistema novo já fez uma rodada de verdade continuando dessa memória. As três
datas de setembro que estavam na fila foram olhadas: nas três, as nuvens ou a
borda da passagem do satélite cobriam quase toda a Chapada, e não havia nada
para detectar.

### O que você precisa fazer

1. **Revogar a chave de testes, quando quiser.** Não há mais nada esperando
   por ela: o sistema novo guarda e lê tudo com a credencial própria dele. Um
   efeito para saber antes: depois de revogar, eu deixo de conseguir conferir
   o armazenamento de testes a partir do seu computador e passo a conferir só
   pelos registros das rodadas automáticas. Se preferir que eu continue
   conferindo daqui, crie antes uma chave **só de leitura** para esse
   armazenamento; é opcional.
2. **A pasta `araripe_replay_2026` pode ficar ou sair.** A memória de 2026 já
   tem cópia no armazenamento; a pasta deixou de ser a única.
3. **Abrir a próxima sessão com este documento**, no modelo e esforço do topo.
   Não é urgente.

### Tem algo preocupante?

Um, o de antes, e um pouco menor do que parecia: a detecção automática antiga
está parada desde 3 de setembro e o site mostra dados de 30 de agosto. O que
mudou é que agora sabemos que as três datas logo depois do corte não tinham
nada observável — então o site não perdeu nada até 7 de setembro. De 8 de
setembro em diante ainda não sabemos; é a próxima sessão que olha.

### O que ainda falta no caminho

- **A cadeia andar sozinha** — a próxima sessão: o sistema novo escolher
  sozinho de qual rodada continuar, recusar continuar a mesma duas vezes, e
  alcançar hoje.
- **Detecção agendada da versão nova** — duas vezes por semana; vem junto com
  a virada.
- **As páginas do site** — linguagem, fonte (tirar o Landsat), as três datas
  separadas, e as datas muito pesadas.
- **A virada** — o site passa a ler os dados novos no próprio domínio, e só
  depois o caminho antigo é desligado.
- **Fase 5** — a validação independente; até ela, nada é publicado como
  "precisão do sistema".
