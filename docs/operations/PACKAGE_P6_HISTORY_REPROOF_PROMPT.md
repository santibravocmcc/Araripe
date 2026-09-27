# Phase 6 — reprovar o histórico de promoção no R2 real, e só então estender a retenção

Escrito em 2026-09-27, depois de o histórico durável (decisão D5) ser
construído e provado localmente. Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: o desenho, o código e a prova local já estão na `main`; o que falta
> é executar sete disparos que movem o ponteiro verde contra o R2 real e ler o
> resultado com o código de verdade, e depois uma política que só **classifica**.
> O erro caro aqui é de verificação — declarar provado o que não foi lido, ou
> seguir disparando depois de um resultado inesperado —, não de desenho.

---

## 1. A dependência que precede tudo — confirme por conteúdo

Este briefing chega à `main` pela PR `#70`, junto com o código. Antes de
qualquer disparo:

    git fetch origin
    git rev-parse origin/main
    git log origin/main --oneline --grep '#70'
    git cat-file -e origin/main:src/publication/promotion_history.py && echo ok
    git show origin/main:.github/workflows/v2_promotion_lane.yml | grep "publish_green_release.py history"
    git config core.hooksPath .githooks     # uma vez por clone

Se `promotion_history.py` não existir na `main`, a PR não entrou e **a lane
ainda roda o código antigo**: uma promoção agora moveria o ponteiro **sem**
registro. Não dispare nada. **Não decida por ancestralidade** — a `#69` entrou
por merge commit e esta pode entrar por squash.

Medido em 2026-09-27, na branch da PR:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **2003** (1932 na base + 71) |
| site | `ARARIPE_DIR=… python -m pytest -q` na branch da `site#26` | **207** |
| site | `npm run test:worker` | **44/44** |

Rode e use o número que sair, não este.

## 2. O que já foi verificado, para o executor não refazer

### 2.1 O desenho, o código e a prova local

[`../implementation/PHASE_6C_2026-09-27.md`](../implementation/PHASE_6C_2026-09-27.md):
§2 as quatro perguntas respondidas antes do código (ordem, chave, corrida,
passado), §3 o contrato do leitor, §5 a prova — 70 intercalações × 3 estados
iniciais para a corrida, **29 mutações mortas**, um guarda de escritor único,
e o ensaio deste plano contra o store falso
(`test_the_re_proof_plan_rehearsed_against_the_fake_store`).

Em uma linha: toda escrita **aceita** do ponteiro deixa uma cópia byte a byte
em `pointers/green/history/<sequence, 10 dígitos>.json`; a versão substituída é
registrada **antes** do CAS; o único registro que pode faltar é o da versão
viva, e repetir a mesma operação o completa.

### 2.2 O bucket antes da reprova — medido, só leitura

Em 2026-09-27, com `aws s3 … --profile araripe-r2-staging` (identidade de
candidato, só leitura):

- `pointers/` continha **só** `pointers/green/current.json` — **nenhum
  registro de histórico existia**;
- o ponteiro: **3640 bytes**, sha256
  **`5c016cd440a466005a59df99ed97306d39e0c59c06d545b13e2e2671289438ad`**,
  `sequence 10`, `promote`, `rel-g1-fb722b2d…` (o candidato da Phase 4),
  cobertura até 2026-08-30, `supersedes` → `rel-g1-24db9555…` na sequence 9
  (2026-08-25);
- existem os prefixos `runs/gate-p2b-real-c/`, `runs/gate-p2b-real-a/` e
  `runs/rep-2026-08-30-v3/`, que o plano usa.

**Releia antes do passo 1.** Se o ponteiro mudou, o sha256 esperado do registro
10 muda com ele.

### 2.3 A reprova só sai do CI, a partir da `main`

O Environment `v2-promotion` só admite a `main`, e a CLI de promoção **recusa**
a chave local por desenho
(`tests/test_profile_credential_fallback.py::test_every_build_client_call_in_the_promotion_cli_refuses_the_fallback`).
**Não mexa no guarda de opt-in para "facilitar"**: ele é o que impede a chave de
candidato de mover o ponteiro de promoção.

### 2.4 "Nada é apagado" não está no arquivo de decisões

O briefing anterior dizia que a regra estava em
`config/phase6_owner_decisions_v1.json`. Não está (`grep -i "delet\|apag"` no
arquivo: nada). Ela é a fronteira dura de todo briefing desde o 2B.3, feita
requisito quando a Phase 5 virou publicação científica
(`../implementation/PHASE_4C_2026-09-16.md` §10). Vale do mesmo jeito; cite o
lugar certo.

## 3. A tarefa

Reprovar o histórico durável contra o R2 real a partir da `main`, registrar o
resultado, e **só então** estender a política de retenção com ele.

## 4. O escopo, na ordem em que se sustenta

1. **Antes de CADA disparo**, as três checagens da fronteira dura (§6). Se
   qualquer uma mudou, **pare**.
2. **Os sete disparos, um por vez** — a tabela de
   `../implementation/PHASE_6C_2026-09-27.md` §6. Leia o log de cada um e
   confira contra a tabela **antes** do seguinte:

   | # | disparo | esperado |
   | --- | --- | --- |
   | 1 | `v2_operational_publish.yml`, `run_id=gate-p2b-real-c` | `promote` → `rel-g1-2ddb10c7…`, seq 11; registros 10 (**criado**) e 11 |
   | 2 | `v2_promotion_lane.yml`, `mode=rollback`, `release_id=` o id completo de `rel-g1-24db9555…` | `rollback`, seq 12; registro 12 |
   | 3 | `v2_operational_publish.yml`, `run_id=gate-p2b-real-c` | `promote`, seq 13; registro 13 |
   | 4 | o mesmo de novo | `unchanged`, seq 13; **nenhum** registro novo |
   | 5 | `v2_operational_publish.yml`, `run_id=gate-p2b-real-a` | **recusa** `coverage_regression`; ponteiro intocado; nenhum registro |
   | 6 | `v2_operational_publish.yml`, `run_id=rep-2026-08-30-v3` | `promote` → `rel-g1-fb722b2d…` de volta, seq 14; registro 14 |
   | 7 | `v2_promotion_lane.yml`, `mode=history` | `verdict: consistent`, entradas 10–14 |

   Copie cada id de release completo **da ferramenta** (`gh run view --log`,
   `aws s3 ls`), nunca do `…` deste documento. O passo 5 é **esperado
   vermelho** — é a recusa. **Qualquer outro resultado diferente da tabela:
   pare**, não "conserte para frente".
3. **Conferir o histórico**: pelo modo `history` da lane (o código de verdade),
   as entradas 10–14 nomeiam `fb722b2d → 2ddb10c7 → 24db9555 → 2ddb10c7 →
   fb722b2d`; e o registro 10 tem **exatamente** o sha256 da §2.2. Como
   complemento, **não** como prova: `aws s3 ls
   s3://araripe-v2-staging/pointers/green/history/ --profile araripe-r2-staging`
   e o sha256 de cada objeto.
4. **Registrar** num documento de implementação novo, com os run ids copiados
   de `gh run view`, os resultados negativos (4 e 5 não escreveram nada) e o
   sha256 dos cinco registros.
5. **Estender a política de retenção**, pelo desenho de
   `PHASE_6C_2026-09-27.md` §7: o histórico lido pelo planejador; a
   reconstrução das sequences 1–9 como arquivo versionado (declara-se
   reconstruída, cita documento e seção por entrada, conferida no
   `supersedes` do registro 10); um teste que lê cada documento citado; e a
   varredura de mutação. O teste
   `test_until_the_policy_is_extended_a_history_record_is_kept_unclassified`
   **tem de mudar** — é ele que marca a extensão. **Classificar não é apagar**,
   e nenhuma release fica `eligible`, nunca.
6. Atualizar o bloco datado do `ROADMAP.md` e
   `GREEN_RETENTION_AND_MIGRATION.md` §3 com o fechamento da D5.

**Fora de escopo, explicitamente:**

- **a lane de depósito em CI** (`assemble_green_run.py apply` com a identidade
  `v2-staging`) — é o pacote seguinte, e é ela que libera a revogação da chave
  local; o guarda
  `test_a_revogacao_da_credencial_e_o_ultimo_passo_e_nao_o_primeiro` cai sozinho
  no dia em que um workflow rodar o depósito — avise o dono nesse dia;
- **o processo agendado verde** — Phase 6 §4.5;
- **os itens 3 a 6 da §4.1** do [`PACKAGE_P6_PROMPT.md`](PACKAGE_P6_PROMPT.md);
- **tornar o histórico público** — é privado por nome na fronteira de entrega;
  mudar isso é decisão da virada;
- **a validação de acurácia** — Phase 5.

## 5. Decisões de escopo já tomadas, com a base

- **D1** e **D5** — `config/phase6_owner_decisions_v1.json`;
- **o protocolo** — ponteiro primeiro, com a versão substituída registrada
  antes do CAS (`PHASE_6C_2026-09-27.md` §2.1). A outra ordem deixa registro de
  promoção que não aconteceu e trava a chave; não reabrir sem evidência;
- **sem backfill no store** — as sequences 1–9 vivem numa reconstrução
  versionada no repositório, nunca como objeto (§2.4 do mesmo registro);
- **nada é apagado**, em nenhum bucket, nunca — §2.4 deste briefing.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 6. Fronteiras duras

- **A reprova move o ponteiro verde, e isso só é permitido antes da virada.**
  Imediatamente antes de **cada** disparo:
  1. `site/src/js/alertas.js` na `main` do site ainda aponta para `pub-…r2.dev`
     (`git show origin/main:src/js/alertas.js | grep R2_ALERTS_BASE`);
  2. o domínio final não serve `/data/green/`: um `GET` sem credencial em
     `https://observatoriodachapadadoararipe.com/data/green/current.json` não
     devolve um ponteiro verde;
  3. o `workers.dev` do Worker verde segue fechado (404, `error code: 1042`).

  Se qualquer uma mudou, **pare**: a partir da virada, promover é ação de
  produção e espera aprovação explícita do dono.
- **Termine com o candidato vivo.** O passo 6 devolve `rel-g1-fb722b2d…` ao
  ponteiro; não encerre a sessão com o ponteiro numa release de prova.
- a `main` dos dois repositórios é **pull-request-only**, e **a `main` do site
  faz deploy de produção**;
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare;
- nunca aprove a sua própria requisição de Environment; nunca nomeie um
  Environment que não existe;
- Claude não recebe credencial de control-plane da Cloudflare. A allowlist do
  broker é exatamente `audit`, `enforce-worker-isolation`,
  `disable-site-branch-deploy`;
- **não ligue** `green_site_publish.yml` ao Environment `v2-green-deploy`.

## 7. Armadilhas já pagas — não redescobrir

- **Mensagem de commit por script, não por heredoc** — escreva o arquivo em
  Python e use `git commit -F`.
- **Depois de cada push, `gh pr list --head <branch> --state all`**: uma PR
  **MERGED** é o sinal de que o próximo commit fica órfão.
- **Um verificador que difere do cliente real prova a coisa errada.** A prova é
  o modo `history` da lane; o `aws s3` é complemento.
- **`HistoryNotRecorded` quer dizer que o ponteiro SE MOVEU.** Não reverta por
  causa dele: repita a mesma operação, que completa o registro.
- **O modo `history` sai 1 num histórico inconsistente** — um run vermelho ali
  é um achado, não instabilidade. Leia os achados antes de qualquer coisa.
- **Uma mutação que deixa o estado final idêntico só morre com um teste que
  observa o instante** — foi o caso de registrar a versão substituída depois
  do CAS.
- **Limpe `__pycache__` e use `PYTHONDONTWRITEBYTECODE=1` antes de cada
  mutação.**
- **No zsh desta máquina, `echo =====` falha** (`= not found`): a palavra que
  começa com `=` é expansão de comando. Use aspas.
- `grep` desta máquina é `ugrep`: `grep -c` com zero casamentos sai 1 e quebra
  uma cadeia `&&`.
- `botocore` 1.35.x tem `IfNoneMatch` mas **não** `IfMatch`; as lanes verdes
  instalam `boto3>=1.36.0` por isso.

## 8. Estado que o pacote herda

- **PR `#70`** — o histórico durável; esta sessão depende dela.
- **Worker verde implantado**, versão `ee433c7a-dbf7-43ae-95c6-98b57ee64327`,
  sem endereço público desde a execução `36324810625`.
- **PRs abertas:** `observatorio-site#26` (o `RouteReader` recusado pela
  borda), sem mesclar.
- **A produção azul está parada**: seis execuções agendadas de `detect_gee.yml`
  falharam desde a última agendada bem-sucedida (2026-09-03, run
  `33747456220`) — a mais recente em 2026-09-24 (run `35993515768`), medido em
  2026-09-27. A última escrita em produção foi a manual de 2026-09-07 (run
  `34137318406`). O conserto é a virada.
- **Achados esperando a sua vez:** o site atribui "Landsat 8/9" e o sistema só
  usa Sentinel-2; a visão completa pesa até 89,1 MiB por data; o índice não tem
  campo para a última tentativa de automação.
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

A prova ao vivo do registro de versões. O registro está construído e testado
aqui, mas ele só pode ser provado no depósito de verdade depois de entrar na
versão principal — e isso depende da sua aprovação. A regra de limpeza que usa
o registro vem depois dessa prova, de propósito.

### O que você precisa fazer

1. **Aprovar e mesclar a mudança número 70 do backend** — é o que libera
   a prova. Não é urgente para nada quebrar: enquanto ela não entra, tudo
   continua como está.
2. **Abrir a próxima sessão com este documento**, no modelo e esforço do topo,
   depois do passo 1.
3. **Aprovar e mesclar a mudança número 26 do site** — pode esperar; lembre que
   mesclar no site publica o site.
4. **Manter a chave de testes ativa** — não apague até eu avisar que o depósito
   automático existe.

### Tem algo preocupante?

Sim, o mesmo de antes: a detecção automática falhou seis vezes seguidas e o
site mostra dados de 30 de agosto. A próxima tentativa agendada deve falhar
também. O conserto é a virada; este trabalho é um dos passos que faltam até
ela.

### O que ainda falta no caminho

- **Prova ao vivo do registro de versões** — a próxima sessão; move o ponteiro
  de teste algumas vezes e confere que cada movimento ficou registrado.
- **Regra de limpeza informada pelo registro** — passa a dizer com certeza
  quais versões já estiveram no ar. Continua sem apagar nada.
- **Depósito automático** — hoje só eu, da minha máquina, coloco dados novos no
  depósito; é o que libera apagar a minha chave.
- **Detecção agendada da versão nova** — religar a detecção duas vezes por
  semana sobre o estado reconstruído; é o que tira o sistema da cegueira.
- **As páginas do site** — linguagem, fonte (tirar o Landsat), as três datas
  separadas, e as datas muito pesadas.
- **A virada** — o site passa a ler os dados novos no próprio domínio, e só
  depois o caminho antigo é desligado.
- **Fase 5** — a validação independente; até ela, nada é publicado como
  "precisão do sistema".
