# Phase 6 — construir a lane de depósito verde: provar a identidade de Earth Engine, pôr a baseline no staging, e só então o workflow

Escrito em 2026-09-28, depois de a sessão anterior responder por escrito as
quatro perguntas de desenho e parar por falta de credencial. Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: o desenho está feito e é para ser seguido, não reaberto; o risco
> está em três fronteiras que o código novo atravessa ao mesmo tempo — uma
> credencial nova de Earth Engine, 13 GB escritos para sempre num bucket onde
> nada se apaga, e o primeiro workflow que roda `assemble_green_run`, que
> derruba de propósito o guarda da revogação da chave local.

---

## 1. A dependência que precede tudo — confirme por conteúdo

**Esta sessão só começa se a identidade existir.** O dono cria seguindo
[`GEE_GREEN_IDENTITY_SETUP.md`](GEE_GREEN_IDENTITY_SETUP.md).

    git fetch origin
    git rev-parse origin/main
    git log origin/main --oneline --grep 'deposit-lane-design'
    git show origin/main:docs/implementation/PHASE_6E_2026-09-28.md | head -5
    gh api repos/santibravocmcc/Araripe/environments/v2-staging/secrets --jq '.secrets[].name'
    gh api repos/santibravocmcc/Araripe/environments --jq '.environments[].name'
    git config core.hooksPath .githooks     # uma vez por clone

A lista de segredos de `v2-staging` tem de conter **`GEE_GREEN_SA_KEY`** além
de `R2_STAGING_ACCESS_KEY_ID` e `R2_STAGING_SECRET_ACCESS_KEY`. **Se não
contiver, pare**: não há nada a construir, e nenhuma credencial substitui essa.
Nunca use `GEE_SA_KEY`.

Suíte medida em 2026-09-28 na branch `claude/p6-deposit-lane-design`:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **2124** — 2119 da base + 5 que `tests/test_handoff_prompt_method.py` roda por briefing, e este é um briefing novo |

Rode e use o número que sair.

## 2. O que já foi verificado, para o executor não refazer

Tudo em [`../implementation/PHASE_6E_2026-09-28.md`](../implementation/PHASE_6E_2026-09-28.md).
O essencial:

- **As quatro respostas estão escritas e são o desenho.** Identidade nova
  (§1); runner padrão do GitHub, que cabe (§2.1); **dois jobs** com uma
  autoridade cada (§3); `run_id = ci-<github.run_id>`, sem a tentativa (§4).
- **`GEE_SA_KEY` não foi chamada, de propósito** (§1.2), e a razão de não
  reusá-la não depende dessa chamada (§1.3). Não reabra.
- **A política de IAM de `ee-araripe` não é legível**: as APIs de Resource
  Manager e de IAM estavam desligadas (403, 2026-09-28). Ao criar o papel
  customizado o dono provavelmente ligou a de IAM — isso não autoriza você a
  ligar mais nada.
- **`ee-araripe` não tem nenhum asset** (`listAssets`: *"not found"*). O probe
  de escrita não tem o que estragar, mas uma criação aceita **seria** uma
  mutação de produção; ver §4 item 1.
- **A baseline `2.1.0` só existe nesta máquina**: 72 rasters, 13 GB, em
  `data/baselines_v2/2.1.0`; **0 objetos** em
  `araripe-v2-staging/baselines_v2/2.1.0/`. Por mês: 1 066 a 1 091 MiB.
- **O estado de persistência não está no bucket.** `run.json` guarda só
  `bytes` e `sha256` (986 744 489 bytes). A detecção agendada não tem de onde
  partir — é da §4.5, fora deste pacote; a prova deste pacote parte de estado
  vazio.
- **O montador é determinístico e a detecção não é**: `run_assembler.py` não lê
  relógio; `replay_2026.py` carimba `created_at`/`terminal_at`.
- **`replay_2026.py` chama `ee.Initialize(project=…)` puro** (linhas 305 e
  467), que falha em runner. E `ee_initialize()` do azul lê a variável
  `GEE_SA_KEY` — a lane verde não pode usar esse nome.
- **O docstring de `assemble_green_run.py` foi corrigido**: o produtor do
  ledger está na `main` desde a `#54`.

## 3. A tarefa

Provar a identidade verde de Earth Engine, pôr a baseline `2.1.0` no staging,
construir a lane de depósito de dois jobs e provar um depósito real a partir
da `main` — sem mover ponteiro.

## 4. O escopo, na ordem em que se sustenta

1. **O probe da identidade**, antes de tudo, como
   `v2_promotion_identity_probe.yml` fez para o R2: `workflow_dispatch`,
   `contents: read`, `environment: v2-staging`, referenciando **só**
   `GEE_GREEN_SA_KEY`. Checagens: inicializa por conta de serviço; uma
   `reduceRegion` pequena responde; um `getDownloadURL` pequeno baixa; **criar
   uma pasta de asset em `projects/ee-araripe/assets/` é recusado** — polaridade
   afirmada nos dois sentidos no teste, como em
   `tests/test_promotion_identity_probe.py`. Mede também `df -h` e `free -g`
   do runner. Se a criação for **aceita**, pare: a identidade está ampla
   demais, e a pasta criada fica registrada, não apagada.
2. **A inicialização explícita** em `replay_2026.py`: por uma variável de nome
   próprio (não `GEE_SA_KEY`), sem cair na credencial interativa em silêncio
   quando a variável é nomeada e está vazia. Não "corrija" os scripts locais
   que chamam `ee.Initialize()` puro de propósito
   (`build_detection_gee.py`, `build_baseline_v2_gee.py`, …).
3. **A baseline no staging**: os 72 rasters sob as chaves que
   `config/baseline_manifest_v2_1.json` declara, com `put_if_absent` e sha256
   conferido contra o manifesto, pelo profile local `araripe-r2-staging`. E o
   buscador que a lane usa: só os meses da janela, sha256 conferido, sem
   importar `config.settings`. **Só depois do item 1 passar.**
4. **O workflow**, `workflow_dispatch` apenas, `permissions: contents: read`,
   grupo de concorrência `araripe-green-candidate`, dois jobs: `detect`
   (chave verde de Earth Engine, nenhum segredo de R2) e `deposit`
   (`R2_STAGING_*`, nenhuma chave de Earth Engine), com um artifact entre eles.
5. **Testes que leem o workflow**, como `tests/test_operational_publish_lane.py`:
   autoridade por job; nenhum workflow verde referencia `secrets.GEE_SA_KEY`;
   o job que importa `config.settings` não tem R2; Environment é exatamente
   `v2-staging`. E a varredura de mutação.
6. **O refinamento da fronteira** do `config.settings` (PHASE_6E §2.4),
   escrito no registro e fixado em teste — não ignorado.
7. **O guarda da revogação vai cair** quando o workflow nomear
   `assemble_green_run`. Atualize o teste e
   `config/phase6_owner_decisions_v1.json` (`revocation_ordering`) **na mesma
   PR**, e **avise o dono** no fim da sessão — mas a revogação só vale depois
   do item 8.
8. **Depois do merge:** um depósito real numa janela curta que já tem release
   (por exemplo 2026-08-25 a 2026-08-31), `run_id` novo, **a partir de estado
   vazio** — e o registro diz que a rodada não é comparável com a release.
   Conferido por `stage_green_run.py` (só leitura). **Não promova.**

**Fora de escopo, explicitamente:**

- **o agendamento** (Seg/Qui) e a semeadura pela marca-d'água — Phase 6 §4.5,
  com a virada; e **onde o estado de persistência vive**, que a §4.5 herda
  deste registro;
- **mover o ponteiro verde**;
- **a virada**, o domínio final, o site;
- **revogar a chave local** — é do dono;
- **a validação de acurácia** — Phase 5.

## 5. Decisões de escopo já tomadas, com a base

- **Identidade nova, nunca `GEE_SA_KEY`** — PHASE_6E §1.
- **Dois jobs, uma autoridade cada** — PHASE_6E §3.
- **`run_id = ci-<github.run_id>`**, sem a tentativa — PHASE_6E §4.
- **D1** — `araripe-v2-staging` é o bucket verde canônico.
- **Nenhum segundo produtor de ledger.**
- **Nada é apagado**, em nenhum bucket, nunca.
- **As quatro decisões científicas da Phase 4** não reabrem.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 6. Fronteiras duras

- A `main` dos dois repositórios é **pull-request-only**, e **a `main` do site
  faz deploy de produção**.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare; a lane verde não herda o cron deles.
- Nunca nomeie um Environment que não exista. `v2-staging` existe.
- Nunca aprove a sua própria requisição de Environment.
- Nunca ligue API nem mude IAM no Google — é do dono.
- Claude não recebe credencial de control-plane da Cloudflare; a allowlist do
  broker é exatamente `audit`, `enforce-worker-isolation`,
  `disable-site-branch-deploy`.
- **Não ligue** `green_site_publish.yml` ao Environment `v2-green-deploy`.

## 7. Armadilhas já pagas — não redescobrir

- **Mensagem de commit por arquivo**, escrita em Python, `git commit -F`.
  Heredoc sem aspas come backticks e `\\`.
- **Depois de cada push, `gh pr list --head <branch> --state all`**.
- **`ee.Initialize()` ignora `GOOGLE_APPLICATION_CREDENTIALS`**; a credencial
  de serviço é passada por `ee.ServiceAccountCredentials(email="", key_data=…)`.
- **Escopo de credencial só se prova com chamada recusada**, e com o cliente
  real.
- **Um segredo de Environment só entra no job que o referencia** — e o teste
  tem de ler isso **por job**, não pelo arquivo.
- **Limpe `__pycache__` e use `PYTHONDONTWRITEBYTECODE=1`** antes de cada
  mutação; reordenar preserva o tamanho e o `.pyc` antigo vale.
- **Varredura de workflow ignora comentário**: use `executable_lines()`.
- **No zsh desta máquina, `echo =====` falha**; `grep` é `ugrep`, e `grep -c`
  com zero casamentos sai 1.
- `botocore` 1.35.x tem `IfNoneMatch` mas não `IfMatch`; as lanes verdes
  instalam `boto3>=1.36.0`.

## 8. Estado que o pacote herda

- **PR desta sessão** — `claude/p6-deposit-lane-design`: registro PHASE_6E,
  roteiro da identidade, este briefing, o checkpoint em `docs/handoffs/`, e o
  docstring corrigido.
- **Ponteiro verde:** `sequence 14`, `rel-g1-fb722b2d…`. Sete releases, nenhuma
  apagada.
- **Worker verde implantado**, sem endereço público.
- **PRs abertas:** `observatorio-site#26`, sem mesclar.
- **A produção azul está parada** desde 2026-09-03; o conserto é a virada.
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

O depósito automático não foi construído. A sessão respondeu por escrito como
ele tem de ser feito e parou porque falta uma chave: a versão nova precisa de
uma conta própria no Earth Engine, e a única que existe é a do sistema antigo,
que pode apagar coisas e que qualquer rascunho de código consegue ler. Também
descobri que a referência de comparação da versão nova só existe no seu
computador, e que o estado que liga uma rodada à seguinte não está guardado em
lugar nenhum. O primeiro se resolve na próxima sessão; o segundo é da virada.

### O que você precisa fazer

1. **Criar a conta nova do Earth Engine**, seguindo o roteiro
   `GEE_GREEN_IDENTITY_SETUP.md`: um papel que só calcula, uma conta com esse
   papel, uma chave, e a chave guardada no lugar protegido v2-staging do
   GitHub com o nome `GEE_GREEN_SA_KEY`. Não é urgente, mas sem ela a próxima
   sessão não começa. Nunca cole a chave no chat.
2. **Aprovar e mesclar a mudança desta sessão** — só documentos e um
   comentário de código; não muda nada no que roda. Pode esperar.
3. **Manter a chave de testes ativa.** Não apague até eu avisar que o
   depósito automático fez o primeiro depósito de verdade.

### Tem algo preocupante?

Sim, o mesmo de antes: a detecção automática está parada desde 3 de setembro
e o site mostra dados de 30 de agosto. O conserto é a virada, e o depósito
automático é um dos passos que faltam até ela.

### O que ainda falta no caminho

- **Depósito automático** — a próxima sessão, depois da conta nova: provar que
  ela só calcula, subir a referência de comparação, construir e provar o
  depósito. É o que libera apagar a minha chave.
- **Detecção agendada da versão nova** — duas vezes por semana, e antes
  decidir onde fica guardado o estado entre uma rodada e outra.
- **As páginas do site** — linguagem, fonte (tirar o Landsat), as três datas
  separadas, e as datas muito pesadas.
- **A virada** — o site passa a ler os dados novos no próprio domínio, e só
  depois o caminho antigo é desligado.
- **Fase 5** — a validação independente; até ela, nada é publicado como
  "precisão do sistema".
