# Phase 6 — a virada: construir a release pública corrigida e promovê-la

Escrito em 2026-09-17, depois de a Phase 4 fechar. Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

> ## ⛔ ESTA FASE TEM QUATRO PORTÕES, E TRÊS SÃO DO DONO
>
> A Phase 6 é a primeira fase desde o início do roadmap que **muda o que o
> público vê**. Ela não começa por decisão do agente. Antes de qualquer
> mutação, confirme que os quatro estão abertos — e se algum não estiver,
> **pare e reporte**, fazendo antes tudo o que não depende dele.
>
> 1. **A revisão pré-cutover do dono**, quatro itens, §2a — e dois deles
>    descrevem um presente que deixou de ser o presente.
> 2. **Um hostname alcançável** para `observatorio-chapada-v2-staging`. Hoje
>    não existe, por desenho, e criá-lo é mutação de control-plane **fora** das
>    três operações allowlistadas do broker (§4.2).
> 3. **Um Environment protegido no repositório do site.** Medido em
>    2026-09-17: `gh api .../environments` devolve **`[]`**. O site não tem
>    nenhum (§4.3).
> 4. **A decisão do bucket** (§3) — e ela é nova, apareceu ao responder uma
>    pergunta do dono, e não está resolvida em documento nenhum.
>
> **O que NÃO é portão:** a Phase 5. O dono decidiu que ela não trava as Fases
> 6 e 7. Mas nenhuma afirmação de **acurácia** pode ser publicada antes do
> relatório dela — o que a Phase 6 publica é **dado e método**.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:docs/implementation/PHASE_4C_2026-09-16.md
    git show origin/main:docs/operations/GREEN_RETENTION_AND_MIGRATION.md   # §5, §6
    git show origin/main:docs/operations/GREEN_DELIVERY_BOUNDARY_V1.md
    git show origin/main:docs/operations/PHASE_3_REPLAY_RUNBOOK.md          # §1, §7
    git config core.hooksPath .githooks     # uma vez por clone

Confirme por conteúdo ou pelo assunto do squash, **nunca por ancestralidade**.
A `main` do backend **andou duas vezes** durante a sessão anterior (`#61`, e
depois `#62`/`#63`) — rode `git rev-parse origin/main` e use o que sair, não o
que um documento diz.

Medido em 2026-09-17. Backend `origin/main` em
`a4c321a34b0725498478aba9f51048f7ab24e317`, site `origin/main` em `6f11076`:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **1872** |
| site | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **203** |
| site | `npm run test:worker` | **44 tests, 44 pass** |

**Escrever o próximo briefing soma 5** — `tests/test_handoff_prompt_method.py`
parametriza 5 checagens por `docs/operations/PACKAGE_*_PROMPT.md`.

O hook `commit-msg` recusa qualquer SHA de 40 caracteres que não exista *neste*
repositório, **inclusive o SHA legítimo do site**. Forma curta para o site.
**Use `npm run test:worker`, não `node --test tests/`** — o Node desta máquina é
v25. Confira `pgrep -fl workerd` ao fim.

## 2. O que já foi verificado, para o executor não refazer

### 2a. A revisão pré-cutover do dono — e DOIS itens envelheceram

O bullet do roadmap pede *"an explicit pre-cutover review of the runbook and
resolved targets"*. A lista viva está em
[`PHASE_3_REPLAY_RUNBOOK.md`](PHASE_3_REPLAY_RUNBOOK.md) §7: **2 de 6 fechados,
4 abertos**. Mas a lista foi escrita em 2026-09-08 e o mundo andou:

| item | estado | o que mudou desde que foi escrito |
| --- | --- | --- |
| os alvos resolvidos da §1 estão certos | **aberto** | os alvos continuam válidos; conferidos em 2026-09-17 |
| a regra do corte e a aceitação de que a data resolve na hora | **aberto** | a data **já resolveu**: literal `2026-08-30`. O dono revisa um fato, não mais uma regra hipotética |
| o procedimento da §3, **incluindo que a produção azul continua rodando** | **aberto, e a premissa é FALSA** | a produção azul **não** continua rodando — está parada desde 2026-09-03 (§2b). O dono não pode aceitar esta cláusula como escrita |
| a divergência de unidade de composição é da Phase 4 | **aberto, e já respondido** | a Phase 4 **decidiu**: `physical_datatake`, `datatake_mosaic-v1`, em `config/phase4_composition_unit_decision_v1.json` |

**Não peça ao dono para revisar a lista como ela está.** Reescreva-a primeiro
contra o presente, mostre o diff, e então peça. Uma checklist cujas cláusulas
mudaram de verdade não é uma checklist — é uma armadilha de consentimento.

### 2b. A PRODUÇÃO ESTÁ PARADA, e a Phase 6 virou também o conserto dela

`detect_gee.yml` falha em **toda** execução agendada desde o landing do 2A.6.
Medido com `gh run list` e `gh run view --log-failed`, registrado na §11 de
[`../implementation/PHASE_4C_2026-09-16.md`](../implementation/PHASE_4C_2026-09-16.md):

| agendada | resultado |
| --- | --- |
| 2026-09-03 | **success** — a última que funcionou |
| 2026-09-10 | **failure — `LegacyPersistenceStateError`** |
| 2026-09-14 | **failure — `LegacyPersistenceStateError`** |

`load_persistence_state` (`src/detection/persistence.py:443`) chama
`_validate_state_columns`, que levanta em `:375`. O landing trouxe esse loader
para a `main`; o workflow faz checkout da `main`; a produção lê o estado vivo,
de geração anterior, com um loader que o recusa **por contrato**. A recusa é o
desenho. A consequência operacional não estava registrada.

**O rebuild que a exceção pede é o que a Phase 4 depositou**, em staging:
986 744 489 bytes, digest
`5eb17f838b35251b3748dbc26310918a8fa7a00ce99b4f3c501dd5887ac987ce`. Ligá-los é
**este** pacote — o bullet *"seed the scheduled process from the rebuilt
watermark"*.

**Isto muda a urgência da fase, não o seu método.** Não conserte por atalho:
`detect_gee.yml` e `update_data.yml` escrevem em produção e **não são
idempotentes**. Nunca os dispare para testar.

### 2c. O candidato está pronto, depositado e publicado — não o refaça

| | |
| --- | --- |
| prefixo da rodada | `runs/rep-2026-08-30-v3/`, **74 objetos**, **1 785 931 509 bytes** |
| release | `rel-g1-fb722b2d1786075b1a6b4d10b1d49db31bb1b3f4e4be74f9621f21b9358ea8bb` |
| ponteiro verde | **sequence 10**, `promote`, 4 tombstones |
| ledger | 107/107 terminais: 66 + 5 + 36; `failed_processing` em nenhuma linha |
| conteúdo | 36 datas com alertas de 90, **67 068** feições fortes |
| corte | literal `2026-08-30`; fila pós-corte de **3** datas |

**Não re-monte, não re-deposite, não re-publique.** Um run-id novo criaria um
segundo candidato, e os prefixos são imutáveis.

### 2d. A ordem da migração está fixada, e os passos 1-3 estão feitos

`GREEN_RETENTION_AND_MIGRATION.md` §5, e **a rota verde é aditiva**: ela não
compartilha caminho com nada que um consumidor leia hoje.

| passo | estado |
| --- | --- |
| 1. objetos verdes publicados em `araripe-v2-staging` | **feito** |
| 2. fronteira de entrega e política de rota fixadas, com vetores | **feito** |
| 3. rota do Worker implementada contra os vetores | **feito** (2B.4) |
| 4. Worker de staging alcançável, rota verificada ao vivo | **BLOQUEADO** — portão 2 |
| 5. site trocado de `pub-…r2.dev` para a rota same-origin | **Phase 6** |
| 6. caminho público azul desabilitado | **Phase 6, e só depois do 5** |

O consumidor a trocar é **um**: `site/src/js/alertas.js`, linha 20,
`const R2_ALERTS_BASE = 'https://pub-5eb389cffff54421916187be69dd659b.r2.dev/site-full'`.
Conferido em 2026-09-17, ainda lá.

### 2e. O que cada Worker é hoje, medido nos arquivos de config

| | `observatorio-chapada` (produção) | `observatorio-chapada-v2-staging` (verde) |
| --- | --- | --- |
| config | `wrangler.jsonc` | `wrangler.green.jsonc` |
| binding de R2 | **nenhum** | `STAGING_BUCKET` → `araripe-v2-staging` |
| assets | `./dist` | nenhum |
| `workers_dev` | — | `false`, e `preview_urls: false` |
| rotas / domínio | o domínio final | `route_count == 0`, `custom_domain_count == 0` |

**O Worker de produção não tem binding de R2 nenhum.** É por isso que o site
lê alertas pela URL pública `pub-…r2.dev` — cross-origin — e é exatamente isso
que a rota same-origin substitui.

### 2f. O ponteiro verde ainda não tem histórico durável, e no cutover isso muda de peso

Medido na sessão anterior, não previsto: ao mover o ponteiro de `sequence 9`
para `10`, a release `rel-g1-2ddb10c7…` — que **esteve no ar** como sequence 8
— deixou de ser nomeável pelo store. Ela só sobrevive porque a §6.1 do registro
a copiou à mão.

Hoje isso é tolerável porque **nenhum consumidor público segue esse ponteiro**.
**No cutover deixa de ser**, e `PROMOTION_IDENTITY_SETUP.md` diz isso com todas
as letras: *"Revisar esta decisão quando o Phase 6 se aproximar. No cutover o
ponteiro verde passa a ser o que o site público segue, e aí a conta de um erro
deixa de ser um sandbox."*

Duas consequências que esta fase **tem** de resolver ou registrar como aceitas:

- o Environment `v2-promotion` **não tem revisor obrigatório**, e a base dessa
  decisão era literalmente "é um sandbox";
- o histórico durável de promoção continua **não construído**
  (`PHASE_2B3_2026-09-07.md` §2, *"a package of its own"*).

## 3. A DECISÃO DO BUCKET — nova, e não resolvida em lugar nenhum

Apareceu ao responder uma pergunta do dono em 2026-09-17, e a varredura não
achou nenhum documento que a resolva.

**Os produtos da versão nova vivem em `araripe-v2-staging`.** É o bucket que o
Worker verde liga como `STAGING_BUCKET`, e onde estão `runs/`, `releases/` e
`pointers/green/current.json`.

**Mas `araripe-v2-staging` é governado por um documento que diz o contrário do
que a Phase 6 faria com ele.** `CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md`:

> *"This bucket is an object-level development sandbox. It is **not a canonical
> release bucket, public bucket, or promotion target**."*

e manda revogar a credencial do Claude *"before repurposing the bucket"*.

Então uma destas coisas tem de acontecer, e é decisão do dono:

- **(a) promover o bucket**: `araripe-v2-staging` deixa de ser sandbox e passa
  a ser o bucket canônico verde. Exige reescrever aquele documento, **revogar
  `claude-araripe-v2-staging-rw`** — uma chave que hoje pode **apagar** objetos
  dentro dele — e revisar quem mais o alcança;
- **(b) criar um bucket final** e copiar a release para lá. Custa uma cópia de
  1,78 GB e um passo de migração a mais, e mantém o sandbox descartável.

**Meça antes de recomendar.** E note que (a) tem uma consequência que (b) não
tem: depois do cutover, uma credencial com DELETE alcança o bucket de que o
site público depende. O limite hoje é o **código** (`ConditionalStore` não tem
delete nem escrita incondicional), não a credencial — o que está medido e é
suficiente para um sandbox, e é uma afirmação mais forte do que se quer para
produção.

**E `araripe-cogs` não muda de conteúdo em nenhum dos dois caminhos.** O que
muda nele é **uma configuração**: desabilitar o acesso público gerenciado do
R2, que mata a URL `pub-5eb389…r2.dev`. Reversível reabilitando — o hostname
deriva do bucket, então a mesma URL volta e `alertas.js` não precisa mudar para
o rollback. **Capture o hostname exato do dashboard antes de desabilitar.**
As baselines continuam em `araripe-cogs`: elas são **insumo** da detecção, não
produto do site, e nenhuma lane verde escreve baseline.

## 4. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: é a primeira fase que muda o que o público vê, e ela mistura três
> coisas que erram de formas diferentes — uma mutação de control-plane sob
> aprovação, uma troca de consumidor que quebra a página se o fallback estiver
> errado, e um desligamento que só é reversível se o hostname tiver sido
> anotado antes. Um cutover feito pela metade é plausível, não obviamente
> quebrado.

Na ordem em que se sustenta. **Cada passo que muta produção para e pergunta.**

### 4.1 O que dá para fazer sem nenhum portão aberto — comece por aqui

1. **Reescrever a checklist da §7 do runbook contra o presente** (§2a), com o
   diff visível, para que a revisão do dono seja sobre fatos atuais.
2. **Gerar os produtos do site a partir do manifesto da release**, não
   varrendo prefixos vivos — é o primeiro bullet da fase. A release existe e é
   legível com a credencial de staging.
3. **Corrigir a linguagem** de confiança, persistência, evento/observação,
   área, MapBiomas, assinatura espectral, fonte, baseline, completude e
   frescor. **Nenhuma afirmação de acurácia** — isso é Phase 5.
4. **Separar as três datas na página**: a última observação avaliada com
   sucesso, a última tentativa de automação, e o último alerta não-vazio. O
   bullet existe desde sempre e a §2b mostra por que ele importa: hoje elas se
   confundem, e um sistema parado há duas semanas não é visível.
5. **Completar o registro de fontes e atribuição**, CC-BY do MapBiomas,
   limites de licença, arquivos de citação, README/deploy/método.
6. **Preparar** os resumos de execução, a saída de status/saúde e o
   monitoramento de frescor por produto.

### 4.2 Portão 2 — o hostname do Worker verde

O passo 4 da migração está bloqueado e **o bloqueio é a isolação funcionando**:
`public_subdomain_enabled` é `false`, `custom_domain_count` é `0`,
`route_count` é `0`, e `cloudflare_green_control.py::audit` afirma os três
fail-closed.

**Capacidade nomeada:** um hostname alcançável para
`observatorio-chapada-v2-staging` — um subdomínio `workers.dev` ou uma rota de
zona num hostname **não-final** — aberto só pela duração da verificação, com as
afirmações da auditoria atualizadas enquanto estiver aberto, e
`enforce-worker-isolation` rodado para fechá-lo depois.

**Isso é mudança de broker mais mutação revisada, e pelas regras não pode ser
autorada e dispatchada na mesma tarefa.** Não substitua por `curl`, Wrangler,
`gh api`, outro workflow ou credencial mais ampla. Se o portão não estiver
aberto, **pare e reporte**, tendo feito a §4.1 antes.

Com hostname, as checagens ao vivo são os vetores de conformidade mais estas,
que só um navegador e uma rede respondem:

* `Content-Length` e `sha256` de um produto servido batem com o manifesto;
* `Cache-Control` do ponteiro é `no-store`, e um rollback aparece numa página
  recarregada em até um minuto;
* **nenhum** `Access-Control-Allow-Origin` em resposta nenhuma — same-origin
  não precisa de preflight;
* o modo de alertas completos renderiza pela rota verde, com os filtros que
  hoje puxam ~13,8 MiB cross-origin;
* `?download=1` produz um arquivo nomeado pelo caminho declarado.

### 4.3 Portão 3 — o Environment protegido do site

Medido em 2026-09-17: `gh api repos/santibravocmcc/observatorio-site/environments`
devolve **`[]`**. **Nunca nomeie um Environment que não existe** — o GitHub
cria o que for nomeado, **sem proteção e sem política de branch**, e isso é uma
mudança de configuração de repositório, a errada.

E há uma razão específica para ele precisar de **revisor**, medida no Package
2B.4A: permissão de Workers no Cloudflare é de **conta**, não de Worker. Quem
implanta o Worker verde implanta o de produção.

### 4.4 A troca do consumidor, e o desligamento — nesta ordem, nunca invertida

1. rota verde servindo e verificada ao vivo (§4.2);
2. `alertas.js` trocado de `pub-…r2.dev` para a rota same-origin, **e o site
   verificado**;
3. **só então** desabilitar o acesso público gerenciado em `araripe-cogs`;
4. verificar o site de novo — a visão completa tem de continuar funcionando,
   agora same-origin.

Antes do passo 3, cada uma destas tem de ser verdade e todas são checáveis:

* nenhuma requisição ao caminho público azul parte do site — `grep` por
  `r2.dev` no bundle **construído**, não no fonte;
* a rota verde serve todo arquivo que o manifesto lista como `file`;
* o hostname exato do `pub-<id>.r2.dev` está **anotado no documento de
  cutover**, porque o rollback é reabilitar.

`site#21` é draft e diz *"NÃO MESCLE AINDA"*. Ela para de commitar os arquivos
de alerta no git, e **medido**: tirar a re-inclusão dá 404 na data mais recente
e o job sai 0. Ela é desta fase, e depende do passo 2 estar feito.

### 4.5 Promover, drenar a fila, e só então desligar o azul

- promover atomicamente o ponteiro pequeno da release;
- **só depois** de as checagens de saúde verdes passarem, desabilitar os
  schedules azuis, os bots escritores e o caminho público do bucket interno —
  **retendo dados e configuração** para rollback;
- semear o processo agendado a partir da **marca-d'água reconstruída** (é o que
  conserta a §2b) e processar as **3** datas da fila pós-cutoff pelo contrato
  incremental de cinco dias.

**Fora de escopo, explicitamente:** a validação qualificada e qualquer
afirmação de acurácia (**Phase 5**); o CI da suíte Python, a acessibilidade
não-quebrante e as skills reutilizáveis (**Phase 7**); qualquer exclusão real
de objeto, em qualquer bucket, em qualquer fase.

## 5. Decisões de escopo já tomadas, com a base

- **As quatro decisões da Phase 4**: baseline `2.1.0`, unidade
  `physical_datatake`/`datatake_mosaic-v1`, sobreposição `0.55`, linhagem
  `ambiguous-lineage-as-origin-v1`. Não reabrir. **Não tente outro valor de
  sobreposição** — o parâmetro é autodestrutivo e está medido.
- **Nada é apagado**, em nenhum bucket, nunca — e a publicação científica
  transforma isso de prudência em requisito: um artigo cita **uma** release.
- **"Não apagar durante a migração inicial"** é o desenho: o caminho antigo não
  é modificado, então o rollback é não fazer nada.
- **A identidade de promoção não vem para a máquina local.**
- **Nenhum segundo produtor de ledger.**
- **O portão de qualidade de cena não é modificado.**
- **A folga de 24 h entre a cadência do backend (Seg/Qui) e a do site
  (Ter/Sex)** é deliberada. Preserve-a ao mexer em qualquer schedule.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 6. Fronteiras duras

- A `main` dos dois repositórios é **pull-request-only**, bypass vazio.
  **A `main` do site faz deploy de produção** — um merge lá é um deploy.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. **Nunca dispare para testar**, nem para "ver se voltou".
- Claude não recebe credencial de control-plane da Cloudflare. O único caminho
  é uma operação já allowlistada no broker, e a lista é exatamente `audit`,
  `enforce-worker-isolation`, `disable-site-branch-deploy`. Desabilitar o
  acesso público de `araripe-cogs` **não** está nela, **não deve ser
  adicionado** (o desenho declarado do broker é *"production operations do not
  exist in this file"*), e é ação do dono sob aprovação explícita.
- **Nunca aprove a sua própria requisição de Environment.**
- **Nunca nomeie um Environment que não existe.**
- Um broker não pode ser **editado e dispatchado na mesma tarefa**.
- A credencial de staging **permite delete**; o limite é o código. Mantenha.

## 7. Armadilhas já pagas — não redescobrir

- **Uma varredura de mutação tem de apagar `__pycache__` antes de CADA
  execução.** Uma mutação de **reordenação** preserva o tamanho do arquivo, e
  a invalidação de bytecode do CPython compara **(mtime, size)** — o pytest
  importa o `.pyc` antigo e a mutação lê como "sobreviveu". Enganou duas vezes.
  `-p no:cacheprovider` **não** resolve: o cache que engana é o do *import*.
- **Um teste pode passar pelo motivo errado.** Pergunte qual mutação ele
  derruba e derrube-a. Um teste de ordem que só afirma "levanta erro"
  sobrevive à mutação que move o guarda para o fim — arme **duas** falhas e
  exija qual delas fala.
- **Varredura de string pega docstring e comentário.** Use o AST.
- **`config/settings.py` carrega o `.env` de PRODUÇÃO no import**, e o guarda
  dos scripts verdes é **transitivo**.
- **`wrangler dev` injeta o `.env` do repositório do site** — cinco bindings de
  credencial, incluindo chaves de **produção**. Desligue com
  `CLOUDFLARE_LOAD_DEV_VARS_FROM_DOT_ENV=false`. E `wrangler dev` verifica a
  rota **sem credencial nenhuma**: o R2 é simulado localmente, e 29/29
  checagens da rota verde passaram sobre HTTP sem token.
- **O campo de binding remoto é `remote`**; `experimental_remote` só AVISA e lê
  local. E binding remoto **cria um Worker de proxy na conta** — exige
  Workers-Edit, por isso aquele degrau foi descartado.
- **`main` no wrangler é relativo ao arquivo de config.**
- **`cd` composto no shell das ferramentas PEGA e PERSISTE.** Caminho absoluto.
- **`grep` desta máquina é `ugrep`**, e `grep -c` com zero casamentos **sai 1**,
  o que quebra uma cadeia `&&` inteira. Não encadeie em `grep` sem `|| true`.
- **Antes de declarar ausência de algo, pergunte onde a convenção do projeto
  diz que ele mora.** A credencial de staging foi declarada ausente porque foi
  procurada no `.env`, e o documento que a governa proíbe o `.env`.
- **Uma medição tomada num estado não representativo já enganou quatro vezes**
  nesta frente. Pergunte de qual estado a sua amostra veio.
- **Outra sessão pode estar no mesmo clone.** O `stash@{0}` continua intocado.
  Confira `git status` antes de todo checkout e **nunca rode `git stash` ali**.
- **Confira `gh pr list --head <branch>` depois de cada push**, e **não
  acrescente commits a uma branch cuja PR já foi aberta** sem conferir antes
  que ela ainda está aberta.

## 8. Estado que esta fase herda

- **A Phase 4 fechou**, com as cinco cláusulas do gate P4 fechadas.
- **O bullet 1 da Phase 4 fica PARCIAL**: preservar a geração antiga como
  release **no store** exige identidade de release, que deriva de um ledger v3,
  e nenhum produtor azul escreve um. O inventário está selado e citável.
- **O histórico durável de promoção continua não construído** (§2f).
- **`ROADMAP.md` está com o bloco datado stale** — ele ainda diz *"Próxima
  frente: Phase 3"*, e as Fases 3 e 4 fecharam. O fechamento da Phase 3 também
  não o atualizou.
- **As três tentativas do replay** continuam lado a lado num diretório isolado
  durável fora do repositório; o caminho absoluto não está em documento nenhum.
- **O token da NASA expira em 2026-11-06**, e a falha aparece vermelha.
- **A `2.1.0` admite produtos pré-Collection-1 nos meses 1-4**; vigilância em
  `scripts/check_esa_reprocessing.py`.
- **Nenhum workflow deste repositório roda a suíte Python** — CI é Phase 7.

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

**Nada.** A tarefa desta sessão era escrever este briefing, e ele está escrito.

Duas coisas que eu **não** fiz de propósito, e que você deve saber: não comecei
o registro permanente de versões — você escolheu a virada como próxima tarefa,
e eu não começo um pacote sozinho; e não mexi em nada de produção.

Ao preparar isto eu descobri **uma decisão que ninguém tinha tomado ainda**, e
ela é sua. Está explicada na próxima seção.

### O que você precisa fazer

1. **Decidir onde os dados da versão nova vão morar de vez.** Hoje eles estão
   num depósito que a própria documentação chama de *descartável* e *"não é
   depósito público"* — e a virada faria dele exatamente o depósito de que o
   site público depende. Ou você promove esse depósito a definitivo (e aí a
   minha chave de escrita nele, que também apaga, precisa ser revogada), ou
   criamos um depósito final e copiamos. **Isto é urgente: é o primeiro passo
   da virada.**
2. **Revisar a lista pré-virada — mas só depois de eu reescrevê-la.** Dos
   quatro pontos que restavam, um afirma que *"a produção azul continua
   rodando"*, e isso deixou de ser verdade; outro pergunta algo que a Fase 4 já
   respondeu. Eu reescrevo a lista contra os fatos de hoje, te mostro o que
   mudou, e aí você revisa. Pedir a sua revisão na lista antiga seria pedir que
   você concordasse com frases que não valem mais.
3. **Abrir um endereço de teste para o servidor novo**, temporariamente. Hoje
   ele não tem endereço nenhum — de propósito, é a trava de isolamento
   funcionando — e sem endereço não dá para testar a rota nova num navegador
   de verdade. Abrir e fechar depois exige uma permissão que só você tem, e
   pelas regras eu não posso escrever a mudança e executá-la na mesma tarefa.
4. **Criar um lugar protegido para credenciais no repositório do site.** Medido
   hoje: o repositório do site não tem nenhum. Ele precisa ter revisor
   obrigatório, e a razão é concreta — no Cloudflare, quem pode publicar o
   servidor novo pode publicar o de produção; a permissão é da conta inteira,
   não de um servidor só.
5. **Decidir se a virada espera pelo registro permanente de versões.** Hoje o
   sistema lembra **uma** versão para trás. Enquanto é um ambiente de teste,
   tudo bem. Depois da virada, é o que o público segue — e um erro deixa de ser
   um erro de sandbox. Ou construímos o registro antes, ou você aceita o risco
   por escrito e construímos logo depois.
6. **Quando puder, autorizar a correção do documento do plano.** Ele ainda diz
   que a próxima frente é a Fase 3. Meia hora, nenhum risco, pode esperar.

### Tem algo preocupante?

**Sim, e é o mesmo de ontem: o sistema no ar continua sem detectar desmatamento
novo desde 3 de setembro.** O dado mais recente do site é de 30 de agosto.

A diferença de hoje é que agora sabemos exatamente o que conserta: **é esta
fase**. O arquivo de memória novo que a detecção pede é o que a Fase 4
construiu, e um dos passos da virada é justamente ligar os dois e religar o
processo automático. Não é um remendo à parte — é um item da lista.

O que isso significa na prática: **quanto mais a virada demorar, mais tempo o
sistema fica cego.** Não é uma emergência de horas, mas é o relógio que deve
pesar quando você decidir os pontos 1 a 5 acima.

Duas coisas que **não** são alarme: o site não mente sobre o frescor do dado
(conferido — o arquivo interno que diz "atualizado" não é lido por nenhuma
página); e o token da NASA expira em **6 de novembro**, ainda com tempo.

### O que ainda falta no caminho

- **Fase 4 — pronta.** 2026 inteiro recalculado, depositado e publicado no
  depósito de testes.
- **Fase 5 — validação independente.** Espera três decisões de método suas.
  Não trava as outras, mas até ela sair **nada pode ser publicado como
  "precisão do sistema"** — o que a virada publica é dado e método.
- **Fase 6 — a virada, a próxima.** Construir as páginas a partir da release
  nova, corrigir a linguagem, ligar o site ao caminho novo, promover, religar o
  processo automático e só então desligar o antigo — guardando tudo para poder
  voltar atrás. É a primeira fase que muda o que o público vê.
- **Registro permanente de versões** — trabalho meu, não toca produção; a
  decisão é se ele vem antes ou depois da virada (ponto 5).
- **Fase 7 — acabamento.** Testes automáticos a cada mudança, acessibilidade,
  e transformar o aprendizado em ferramentas reutilizáveis.
