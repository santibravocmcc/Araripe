# Phase 6 — o histórico durável de promoção (a decisão D5)

Escrito em 2026-09-27, depois de o portão 2 fechar. Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: max**
>
> Por quê: este pacote muda `atomic_publish.promote` e `rollback`, o caminho
> que foi provado cinco vezes contra o R2 real em 2026-09-07 e que, depois da
> virada, decide o que o site público mostra. O erro aqui não é barulhento: uma
> ordem de escrita errada entre o histórico e o ponteiro deixa um registro que
> afirma uma promoção que não aconteceu, ou uma promoção sem registro — e as
> duas coisas parecem sucesso.

---

## 1. A dependência que precede tudo — confirme por conteúdo

Este briefing chega à `main` pela PR `#69`. Antes de qualquer linha de código:

    git fetch origin
    git rev-parse origin/main
    git log origin/main --oneline --grep '#69'
    git show origin/main:config/phase6_owner_decisions_v1.json | grep '"corrected_on"'
    git cat-file -e origin/main:docs/implementation/PHASE_6B_2026-09-27.md && echo ok
    git config core.hooksPath .githooks     # uma vez por clone

O `corrected_on` da condição de revogação tem de dizer **`2026-09-27`**. Se
disser `2026-09-18`, a `#69` não está na `main` e você está lendo o raciocínio
errado que ela corrige (§2.3). **Não decida por ancestralidade**: a `#67` entrou
por merge commit e a `#69` pode entrar por squash.

Medido em 2026-09-27, na branch da `#69` (a `main` em `e0d1c2a` mais a `#69`):

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **1932** (1927 + as 5 checagens deste briefing) |
| site | `ARARIPE_DIR=… python -m pytest -q` na branch da `site#26` | **207** (203 na `main` do site) |
| site | `npm run test:worker` | **44/44** |

Rode e use o número que sair, não este.

## 2. O que já foi verificado, para o executor não refazer

### 2.1 A especificação existe e é curta

[`../implementation/PHASE_2B3_2026-09-07.md`](../implementation/PHASE_2B3_2026-09-07.md),
seção *"The prerequisite, specified and deliberately not built"*:

> A durable write-once promotion history — one immutable object per pointer
> write — is what would make release retention decidable. [...] it would add a
> write to `atomic_publish.promote` and `rollback`, and that path was proven end
> to end against real R2 five times on 2026-09-07. [...] Build it, re-prove it,
> then extend the policy — that is a package of its own.

### 2.2 Onde o código vive, lido em `origin/main`

| o quê | onde |
| --- | --- |
| escrita do ponteiro (CAS) | `src/publication/atomic_publish.py` — `_write_pointer`, que chama `put_if_pointer_absent` ou `put_if_match` |
| `promote` / `rollback` | mesmo arquivo; `_supersedes` e `tombstones` montam o contexto de um passo |
| a chave do ponteiro | `src/publication/green_release.py`, `POINTER_KEY = "pointers/green/current.json"` |
| as primitivas | `ConditionalStore`: `get`, `require`, `put_if_absent`, `put_if_match`, `put_if_pointer_absent` — **nenhum delete, nenhum put incondicional** |
| o gancho da política | `src/publication/retention.py`, razão `REVIEW` `promotion_history_not_recorded` |

**Verificado e negativo:** nenhum prefixo `history` existe hoje —
`git grep "history/\|pointers/green/history\|promotion_history" origin/main -- src/ scripts/`
só acha o motivo de `REVIEW` e os testes dele. Não há colisão de chave.

### 2.3 A chave local NÃO roda promoção — e isso decide como reprovar

Medido em 2026-09-27, e corrigiu um erro meu registrado em 2026-09-18. A
credencial local (`AWS_PROFILE=araripe-r2-staging`) é **opt-in por ponto de
entrada**, e só dois scripts optam: `assemble_green_run.py` e
`stage_green_run.py`
(`tests/test_profile_credential_fallback.py::test_only_the_two_lane_two_entry_points_opt_in`).
A CLI de promoção, `publish_green_release.py`, **recusa** a chave local
(`test_every_build_client_call_in_the_promotion_cli_refuses_the_fallback`).

Consequência: **a D5 não se reprova localmente.** Ela se reprova em CI, a partir
da `main`, pelas lanes de promoção (`v2_operational_publish.yml`,
`v2_promotion_lane.yml`, Environment `v2-promotion`, sem revisor, política de
branch `main`) — exatamente como as cinco provas de
[`GREEN_PROOFS_2026-09-07.md`](GREEN_PROOFS_2026-09-07.md). **Não mexa no guarda
de opt-in para "facilitar" a reprova**: ele existe para que a chave de
candidato nunca mova o ponteiro de promoção.

### 2.4 O buraco, medido no bucket

Em 2026-09-17, com `s3 ls` e o ponteiro lido: **7** releases existem, o ponteiro
nomeia **2** — a viva `rel-g1-fb722b2d…` (sequence **10**) e `supersedes` →
`rel-g1-24db9555…` (sequence 9). As outras **5** não são alcançáveis pelo store.
`rel-g1-2ddb10c7…` **esteve no ar** como sequence 8 e só sobrevive porque foi
copiada à mão para um registro
([`../implementation/PHASE_4C_2026-09-16.md`](../implementation/PHASE_4C_2026-09-16.md) §6.1).
O ponteiro continuava em sequence 10 em 2026-09-27.

### 2.5 A rota verde está verificada ao vivo, e segue o ponteiro

[`../implementation/PHASE_6B_2026-09-27.md`](../implementation/PHASE_6B_2026-09-27.md):
37/37 checagens contra o Worker real, e o índice do site composto **pela rota**
byte-idêntico ao composto do bucket. O Worker lê o ponteiro **a cada
requisição** e ele sai `Cache-Control: no-store`, sem cache na borda. Então
**qualquer escrita de ponteiro aparece imediatamente para quem segue a rota** —
que é a razão do §6.

## 3. A tarefa

Construir o histórico durável de promoção, reprová-lo contra o R2 real a
partir da `main`, e só então estender a política de retenção.

## 4. O escopo, na ordem em que se sustenta

1. **Responder por escrito, antes do código, as perguntas de desenho** — e
   registrar as respostas num documento de implementação:
   - **a ordem das duas escritas.** Histórico antes do ponteiro deixa, se o CAS
     do ponteiro falhar, um registro de uma promoção que não aconteceu. Ponteiro
     antes do histórico deixa, se o histórico falhar, exatamente a promoção sem
     registro que este pacote existe para eliminar. Escolha, e diga o que o
     leitor do histórico tem de fazer com o resíduo do caminho escolhido;
   - **a chave.** A `sequence` do ponteiro conta escritas e só cresce, inclusive
     na reversão (`PHASE_3_REPLAY_RUNBOOK.md` §5), o que a torna candidata
     natural — mas confira no código que ela é única por escrita **aceita**;
   - **dois promotores em corrida.** O CAS do ponteiro serializa; diga o que
     acontece com o objeto de histórico do perdedor;
   - **o passado.** As sequences 1-10 não podem ser reconstruídas do store. Se
     houver backfill, ele tem de se declarar **reconstruído** e citar a fonte —
     nunca se apresentar como a escrita original.
2. **Implementar** com escrita `put_if_absent` (write-once), sem delete, sem put
   incondicional. Testes com mutação verificada — o ensaio de falha no meio de
   `tests/test_replay_rehearsal.py` é o modelo.
3. **Reprovar em CI a partir da `main`**, depois de a PR mesclar: promover,
   reverter, promover de novo, repetir uma promoção (no-op idempotente) e ter
   uma promoção recusada — a mesma forma das cinco provas de 2026-09-07. Cada
   escrita tem de deixar o seu objeto de histórico, e o histórico tem de nomear
   toda release que esteve viva, na ordem.
4. **Estender a política de retenção**: com o histórico, o motivo `REVIEW`
   `promotion_history_not_recorded` deixa de ser a resposta. **Classificar não é
   apagar** — ver §5.

**Fora de escopo, explicitamente:**

- **a lane de depósito em CI** (`assemble_green_run.py apply` rodando com a
  identidade `v2-staging`) — é o pacote seguinte, e é ela, não este, que libera a
  revogação da chave local (§5);
- **o processo agendado verde** (semear a partir da marca-d'água reconstruída) —
  Phase 6 §4.5;
- **os itens 3 a 6 da §4.1** do [`PACKAGE_P6_PROMPT.md`](PACKAGE_P6_PROMPT.md) —
  linguagem, as três datas, fontes (inclui o achado do Landsat), status;
- **como o site público passa a ler `/data/green/` no próprio domínio**, e o
  peso da visão completa (até 89,1 MiB por data) — decisões da virada;
- **a validação de acurácia** — Phase 5.

## 5. Decisões de escopo já tomadas, com a base

Todas em [`../../config/phase6_owner_decisions_v1.json`](../../config/phase6_owner_decisions_v1.json):

- **D1** — `araripe-v2-staging` é promovido a bucket canônico verde. A revogação
  de `claude-araripe-v2-staging-rw` é o **último** passo, e espera **uma lane de
  depósito em CI**. A condição foi escrita errada duas vezes antes; o guarda
  `test_a_revogacao_da_credencial_e_o_ultimo_passo_e_nao_o_primeiro` lê o código
  e **cai sozinho** no dia em que um workflow rodar o depósito — avise o dono
  nesse dia;
- **D5** — construir o histórico **antes** da virada. Duas razões: não bloqueia
  nada e nada o bloqueia; e a reprova só sai de graça **enquanto nenhum
  consumidor público segue o ponteiro**;
- **nada é apagado**, em nenhum bucket, nunca. Um artigo cita **uma** release.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 6. Fronteiras duras

- **A reprova move o ponteiro verde, e isso só é permitido antes da virada.**
  Imediatamente antes de cada disparo, confirme que nenhum consumidor público
  segue o ponteiro: `site/src/js/alertas.js` tem de continuar apontando para
  `pub-…r2.dev`, e nada no domínio final pode servir `/data/green/`. Se isso
  tiver mudado, **pare**: a partir da virada, promover é ação de produção e
  espera aprovação explícita do dono;
- a `main` dos dois repositórios é **pull-request-only**, e **a `main` do site
  faz deploy de produção**;
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare;
- nunca aprove a sua própria requisição de Environment; nunca nomeie um
  Environment que não existe;
- Claude não recebe credencial de control-plane da Cloudflare. A allowlist do
  broker é exatamente `audit`, `enforce-worker-isolation`,
  `disable-site-branch-deploy`;
- **não ligue** `green_site_publish.yml` ao Environment `v2-green-deploy`: ele
  existe no site, **sem revisor** (repo privado em plano grátis) e **sem
  segredo** — o dono tirou o token de lá em 2026-09-27.

## 7. Armadilhas já pagas — não redescobrir

- **Mensagem de commit por script, não por heredoc.** `<<EOF` sem citar
  **executa** os acentos graves do corpo; em 2026-09-18 isso apagou `main` de
  duas linhas de uma mensagem, e o commit entrou assim. Escreva o arquivo em
  Python e use `git commit -F`.
- **Depois de cada push, `gh pr list --head <branch> --state all`.** Com
  `--state all`: uma PR **MERGED** é o sinal de que o próximo commit fica órfão.
  Aconteceu de novo em 2026-09-18.
- **Um verificador que difere do cliente real prova a coisa errada.** Em
  2026-09-27 um verificador próprio passou 37/37 porque mandava `User-Agent`, e
  o cliente do site levou 403 da borda (`error code: 1010`). Na reprova, rode o
  código de verdade.
- **Limpe `__pycache__` antes de cada execução de mutação** — reordenar
  preserva o tamanho do arquivo e o `.pyc` antigo vale.
- **Guarda por frase literal é derrotado por quebra de linha**, em silêncio.
  Normalize com `" ".join(text.split())` e corte pela estrutura.
- **Prosa sobre o comportamento de outro componente não quebra quando ele
  muda.** A condição de revogação foi escrita errada duas vezes por isso; o
  guarda atual lê o código.
- `grep` desta máquina é `ugrep`: `grep -c` com zero casamentos sai 1 e quebra
  uma cadeia `&&`. `cd` composto no shell das ferramentas persiste.
- `botocore` 1.35.16/1.35.36 têm `IfNoneMatch` mas **não** `IfMatch`; as lanes
  verdes instalam `boto3>=1.36.0` no Python do runner por isso.

## 8. Estado que o pacote herda

- **Portões da Phase 6:** 1 (revisão pré-cutover) **fechado** em 2026-09-18; 2
  (endereço de teste do servidor verde) **fechado** em 2026-09-27; 3 resolvido
  por decisão — o token de deploy fica fora do GitHub e o Worker verde é
  implantado da máquina do dono; 4 (bucket) **decidido**.
- **Worker verde implantado:** versão `ee433c7a-dbf7-43ae-95c6-98b57ee64327`; o
  placeholder anterior, `7c1b4812-91dd-486b-b9bd-556101a7f0e0`, é o alvo de
  rollback. Sem endereço público desde a execução `36324810625`.
- **PRs abertas:** `observatorio-site#26` (o `RouteReader` recusado pela borda),
  sem mesclar.
- **A produção azul está parada**: seis execuções agendadas de `detect_gee.yml`
  falharam desde a última agendada bem-sucedida (2026-09-03) — cinco com
  `LegacyPersistenceStateError` (a última em 2026-09-24, run `35993515768`) e a
  de 2026-09-07 por outra causa. A última escrita em produção foi a manual de
  2026-09-07. O conserto é a virada.
- **Achados esperando a sua vez:** o site atribui "Landsat 8/9" e o sistema só
  usa Sentinel-2, inclusive no compositor verde; a visão completa pesa até
  89,1 MiB por data; o índice não tem campo para a última tentativa de
  automação.
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da tarefa desta sessão. O servidor novo foi instalado, testado ao vivo e
fechado de novo, e o teste achou um defeito no site que já está consertado numa
proposta de mudança.

Ao escrever este documento eu achei um erro meu: em 18/09 eu disse que a chave
de testes só podia ser apagada depois do registro de versões. O motivo real é
outro — ela é a única forma de colocar dados novos no depósito. A conclusão
prática não muda: ainda não apague a chave.

### O que você precisa fazer

1. **Aprovar e mesclar a mudança número 69 do backend** — urgente antes da
   próxima sessão, porque este documento só vale depois de entrar na versão
   principal.
2. **Abrir a próxima sessão com este documento**, no modelo e esforço que estão
   no topo — quando puder.
3. **Aprovar e mesclar a mudança número 26 do site** — pode esperar. Ela não muda
   nenhuma página; mas lembre que mesclar no site publica o site.
4. **Manter a chave de testes ativa** — não apague até eu avisar que o depósito
   automático existe.

### Tem algo preocupante?

Sim, o mesmo de antes, mais pesado: a detecção automática falhou seis vezes
seguidas e o site mostra dados de 30 de agosto. O conserto é a virada, e cada
pacote até lá encurta a espera — mas ela ainda não é de dias.

### O que ainda falta no caminho

- **Registro de versões** — o próximo pacote; faz o sistema lembrar toda versão
  que já esteve no ar, e não só a anterior.
- **Depósito automático** — hoje só eu, da minha máquina, consigo colocar dados
  novos no depósito; é preciso que isso rode sozinho na nuvem. É o que libera
  apagar a minha chave.
- **Detecção agendada da versão nova** — religar a detecção duas vezes por
  semana, agora sobre o estado reconstruído. É o que tira o sistema da cegueira.
- **As páginas do site** — corrigir a linguagem e a fonte (tirar o Landsat),
  mostrar as três datas separadas, e decidir o que fazer com as datas muito
  pesadas.
- **A virada** — o site passa a ler os dados novos no próprio domínio, e só
  depois o caminho antigo é desligado, guardando tudo para poder voltar atrás.
- **Fase 5** — a validação independente; até ela, nada é publicado como
  "precisão do sistema".
