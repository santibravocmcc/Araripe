# Phase 4, terceira sessão — os dois obstáculos que a execução encontrou

Escrito em 2026-09-09, ao fim da segunda sessão da Phase 4. Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

**O replay rodou.** A enumeração se reproduziu byte por byte, o custo foi
medido e é menor do que se projetava, a contabilidade fechou por aquisição, e a
execução encontrou **dois obstáculos que não são tempo de máquina**. Um é uma
recusa fail-closed da ciência congelada; o outro é uma lane que não existe.
Nenhum dos dois é contornável dentro da Phase 4 sem mudar régua ou autoridade,
e por isso nenhum dos dois foi contornado.

O estado do gate P4, cláusula por cláusula, está em
[`../implementation/PHASE_4B_2026-09-09.md`](../implementation/PHASE_4B_2026-09-09.md).

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:docs/implementation/PHASE_4B_2026-09-09.md
    git show origin/main:docs/implementation/OLD_GENERATION_ATTESTATION_2026-09-09.json
    git config core.hooksPath .githooks     # uma vez por clone

A PR desta sessão é **`#59`** (`claude/phase4b-replay-execution`), aberta **sem
mesclar**. Confirme por conteúdo ou pelo assunto do merge/squash, **nunca por
ancestralidade** — os dois repositórios fazem squash-merge e a `#58` veio por
merge commit.

Medido nesta sessão. `origin/main` do backend em
`7269b3e0345886ea0b81936b11afc10106c33ec1`, `origin/main` do site em `5304a81`:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **1802** na `main`, **1830** na branch |
| site | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **203** na `main` |
| site | `npm run test:worker` | **44 tests, 44 pass** |

A conta dos 28 é exata e vale conferir se ela mudar: **23** nos três arquivos
de teste novos (12 + 6 + 5), mais **5** que
`tests/test_handoff_prompt_method.py` acrescenta sozinho, porque ele
parametriza **5 checagens por `docs/operations/PACKAGE_*_PROMPT.md`** e este
briefing é um arquivo novo. Escrever o próximo prompt de handoff soma outros 5,
então a base da próxima sessão sobe sem que nenhum teste tenha sido escrito
para ela.

**O site não precisou de mudança nesta sessão e não precisa na próxima**: o
candidato fica em staging e a página só passa a lê-lo na Phase 6. Isso foi
verificado rodando as duas suítes, não assumido. Não invente uma PR do site.

**Use `npm run test:worker`, não `node --test tests/`** — o Node desta máquina
é v25 e a segunda forma morre com `MODULE_NOT_FOUND`.

O hook `commit-msg` recusa qualquer SHA de 40 caracteres que não exista *neste*
repositório, **inclusive o SHA legítimo do site**. Ele recusou um commit desta
sessão exatamente assim. Use `5304a81` na forma curta.

## 2. O que já foi verificado, para o executor não refazer

**a. As três decisões continuam seladas e foram confirmadas por leitura.**
Baseline `2.1.0` (`project_owner`, 2026-09-09), unidade `physical_datatake` sob
`datatake_mosaic-v1`, grade `do_not_pin_crs_transform`. `BASELINE_VERSION` do
azul continua `1.0.0`. `pytest -q tests/test_replay_freeze.py` → 55 passed,
congelamento `e877e9b1b1150d64c5ac71aeaf7bb23ff7c8b59b29984bd301bfdc3f8611a577`.
**Não redecida nenhuma das três.**

**b. A enumeração é reprodutível — e isso não estava provado antes.** `plan`
rodou num diretório isolado novo e cunhou o **mesmo** `run_manifest_id`
`run-v3-934387671941a94c415ada64f75a81699c4e030f1f09b7a14e8deca8b5c7208f`, com
os mesmos 510 → 107 em 90 datas, 48 a puxar, 59 rejeitadas, maior rejeitada
7,12%. Não re-enumere para conferir; rode `plan` só se precisar do manifest num
diretório novo.

**c. O custo está medido sobre os 48, e não o remeça.** Média **56,0 s** e
**469,9 MB**; mediana 57,5 s e 556,5 MB; mínimo 32 s / 87 MB; máximo 103 s /
737 MB. Download somado **44,8 min**, bytes somados **22,55 GB**, relógio de
parede do replay inteiro **66 min**.

**E há uma lição de método aqui que corta para os dois lados.** A projeção da
sessão anterior (~1 h, ~35 GB) vinha de **um** composto de agosto e acertou o
tempo, errando 1,55x no tamanho. A correção que eu publiquei no meio da
execução (~37 min, ~15 GB) vinha de **16** compostos de janeiro a abril e
errou ~1,5x nos **dois** eixos, para baixo. A mediana de janeiro-abril é
260 MB e a do ano é 556,5 MB. **Uma subamostra sazonal engana com qualquer
tamanho de amostra quando o eixo da amostragem correlaciona com o custo.**

**d. A recusa de linhagem é o obstáculo central, está medida, e o MECANISMO
está isolado — leia isto antes de tocar em qualquer coisa.** É o contrato
aceito do Package 2A.1 (`PHASE_2A1_2026-07-28.md`): *"Ambiguous many-to-many
components fail closed for reviewed correction"*, e o mecanismo de reviewed
correction **nunca foi construído**.

As 107 aquisições fecharam em: `rejected_low_coverage` **66**,
`failed_processing` **34**, `rejected_quality` **5**, `complete_with_alerts`
**2**. Os 48 puxados são 2 + 34 + 5 + 7 e os 66 são 59 + 7 — enumeração e
execução reconciliam sem resto.

**Uma data só passa quando o conjunto de tracks elegíveis está VAZIO**, e as
duas que passaram provam a regra:

1. `2026-02-11` passou por ser a primeira aceita, com estado vazio — sem grafo
   não há componente muitos-para-muitos. Deixou 17 704 tracks com `n = 1`.
2. Todas as seguintes falharam contra aquele mesmo conjunto parado.
3. `2026-08-15` passou, e a data **não é coincidência**: elegibilidade é
   `active & (established | recent)`, `recent` é
   `0 <= dias <= grace_days` e `grace_days = 180`. 2026-02-11 + 180 =
   **2026-08-10**, que é a **última** data recusada. Os 17 704 nunca chegaram
   a `confirmed_min = 15`, então nunca ficaram `established`; ao sair da
   janela tornaram-se inelegíveis e o grafo esvaziou.
4. E recomeçou: `2026-08-15` deixou 5 049 tracks e `08-20`, `08-22`, `08-25` e
   `08-30` voltaram a falhar.

**Isto foi previsto a partir de `grace_days` e depois confirmado no log**, o
que é a diferença entre correlação e mecanismo. A consequência: o bloqueio
**não** é "2026 é ambíguo em todo lugar" — é que **um único conjunto de tracks
não confirmado bloqueia toda data dentro da sua janela de graça**, e a primeira
falha se auto-perpetua, porque o estado que causa a ambiguidade é o estado que
nenhuma data seguinte consegue substituir.

**e. Verificado que a chamada não é a variável.** `mode` só é validado em
`update_tracks` e não alcança o guarda; `min_overlap_frac` é `0.05` nos dois
caminhos; `grace_days` é 180 e o maior salto do replay é de 30 dias. A
diferença está na população de polígonos.

**f. Resultado negativo, e ele importa: a persistência do azul FUNCIONA.** O
`manifest.json` do site mostra `candidate` crescendo a partir da segunda data
publicada, com totais de **262 036 candidatos**, **47 246 confirmados** e
`pcount_max` **83**. O guarda não é fatal por si — o replay o atinge sempre e o
azul só às vezes. **Por que não foi medido**, e não pode ser com o que existe
local: a baseline `1.0.0` tem **0 rasters** em `data/baselines`.

**f.1 MEDIDO — o subconjunto forte do candidato é VAZIO, e é o que decide
tudo.** `is_strong` exige `CANDIDATE_MIN_SIGHTINGS = 2` avistamentos, e a
sequência é o que a persistência não amarrou. Nas **duas** datas do candidato
(17 704 e 5 049 feições), `persistence_count` é **1 em todas**, `first_obs` é
o total, `candidate` e `confirmed` são **0**, `pcount_max` é **1** e o
subconjunto forte é **0**. Materializado e não inferido: os dois objetos
`*.strong.geojson` do prefixo montado têm **43 bytes** e **o mesmo digest**,
porque os dois são a mesma `FeatureCollection` vazia. O subconjunto forte é o
que a página carrega por padrão — não é um candidato magro, é um candidato que
não mostra nada, **por construção**.

**E a magnitude, contra o azul:** das 90 datas enumeradas, **2** são aceitas
pelos dois, **42** só pelo azul, **0** só pelo replay, 46 por nenhum.

**g. O azul engole o mesmo erro.** `run_detection_from_gee.py:295-297` captura
qualquer exceção que não seja `PersistenceTransitionError`, loga e segue. É por
isso que a produção nunca parou nisto, e explica os degraus **90 datas
observadas → 45 linhas em `alert_stats` → 40 rodadas publicadas**.

**h. Não existe lane que deposite o candidato.** `grep -rn assemble_green_run
.github/` é **vazio**. `v2_operational_publish.yml` **exige** que
`runs/<run-id>/` já contenha `run.json`, `ledger.json` e os corpos;
`v2_candidate_replay.yml` é a sonda inerte do 2B.0. O Environment `v2-staging`
tem política de branch **`main`**. As duas metades seguintes — validar e
publicar — têm lane e funcionam.

**i. A fila pós-corte não é vazia, e a Phase 3 registrou 0.** Medido por uma
segunda enumeração: **2026-09-02** (5,22%), **2026-09-04** (13,30%),
**2026-09-07** (4,22%). A Phase 3 usou o banco azul, cuja última data É a data
provisória do corte, então a fila saía vazia por construção.

**j. O achado científico está medido e o seu confundimento também.** Cinco
datas que o azul aceitou e o replay rejeitou, com fração de alerta de 39% a
61% contra o portão congelado de 30%; as cinco têm **um único datatake**, então
a unidade de composição não é a variável. Mas as 11 aquisições de processing
baseline `05.11` são **todas** de janeiro mais 2026-02-01, então **lineage e
estação não são separáveis** com estes dados. `scripts/compare_replay_to_blue.py`
imprime o confundimento junto com a tabela.

**k. Ferramentas que já existem — leia antes de escrever nova:**
`scripts/replay_2026.py` (`plan`, `run`), `scripts/finalize_replay_candidate.py`
(corte, bullet 8, fila, montagem), `scripts/attest_old_generation.py`,
`scripts/compare_replay_to_blue.py`, `src/replay/seasonal_regime.py`,
`src/replay/enumeration.py`, e a corrente verde
`assemble_green_run.py` → `stage_green_run.py` → `publish_green_release.py`.

## 3. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: os dois obstáculos são de contrato, não de código. Um exige ler o
> que a persistência promete e o que a Phase 5 possui; o outro exige desenhar
> uma travessia de autoridade sem afrouxar nenhuma. Um candidato depositado
> errado é plausível, não obviamente quebrado.

**A Phase 4 não fecha antes da decisão do dono sobre a linhagem** (§8). O que a
próxima sessão pode fazer sem ela, na ordem em que se sustenta:

1. **Desenhar a travessia do depósito, e não só acrescentar um passo.** A
   pergunta real não é "falta um step" — é **como os corpos da rodada chegam ao
   bucket de staging**. As três saídas, e nenhuma é óbvia:
   - rodar o replay **dentro** da lane: precisa de credencial de **serviço** do
     GEE, e esta máquina só tem OAuth de usuário (a Phase 3 mediu a ausência);
   - subir os corpos como artifact de workflow: precisa medir o limite contra
     o tamanho real da rodada;
   - um operador com a credencial de staging rodar `assemble_green_run.py
     apply` localmente: é a via que a arquitetura já suporta, e é ação do dono.
   Meça antes de escolher. Registre a escolha com a base.

2. **Fechar as cláusulas do gate que fecham sem o depósito.** A contabilidade
   por aquisição, a reconciliação diária e a ausência de status irresolvido não
   dependem do bucket. Diga quais fecham e quais não.

3. **Não deposite o candidato atual sem a decisão da linhagem.** Ele é
   internamente consistente e reprodutível, e o seu **subconjunto forte é
   vazio** (§2f.1) — a única data com observações amarradas é a primeira,
   porque o estado estava vazio, e nada pode ter dois avistamentos quando nada
   encadeia. Depositar isso criaria uma release **imutável** de um candidato
   que a Phase 5 vai rejeitar, e **nada pode ser apagado**. A falta da lane
   (§2h) deixou de ser o obstáculo mais forte: mesmo com ela, o depósito
   estaria errado.

**Fora de escopo, explicitamente:** promover o candidato; a validação
qualificada (**Phase 5**, com portão de revisão do dono, e ela **não** começa
sem essa revisão); o cutover, o desligamento do bot azul, ligar a página à rota
nova e qualquer coisa no domínio final (**Phase 6**); o histórico durável de
promoção e qualquer exclusão real. **Não inicie as Fases 5, 6 nem 7.**

## 4. Decisões de escopo já tomadas, com a base

- **As três decisões da §2a.** Não reabrir sem evidência contrária.
- **O portão de qualidade de cena não é modificado.** O arquivo de decisão
  declara `quality_gate_change_permitted: false` e um teste o exige. As cinco
  rejeições da estação chuvosa são o portão congelado funcionando.
- **`failed_processing` é o status honesto para a linhagem recusada.** É um dos
  sete terminais e o bullet 4 o nomeia. `complete_*` afirmaria observações que
  a persistência se recusou a amarrar; `rejected_quality` culparia o portão de
  cena, que aceitou a aquisição.
- **O filtro de cobertura só pode rejeitar.** `assess_scene_quality` continua
  sendo a única coisa que aceita.
- **Nenhum segundo produtor de ledger.** A detecção produz; o montador consome.
- **Nada é apagado.**
- **A produção azul continua rodando.**
- **O corte é inclusivo do lado do lote.**

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- A `main` do backend é **pull-request-only**, bypass vazio. Branch, PR.
- **A `main` do site faz deploy de produção.**
- Produção congelada nas Fases 2B-5: Worker `observatorio-chapada`,
  `araripe-cogs`, domínio final, DNS, rotas, workflows azuis, ponteiros
  canônicos, artefatos publicados.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. **Nunca dispare para testar.**
- O replay escreve **só** no `--out-dir` e no `--state-path`; a lane verde
  escreve **só** em `araripe-v2-staging`.
- Claude não recebe credencial de control-plane da Cloudflare; o único caminho
  é uma operação já allowlistada no broker protegido, cuja lista é exatamente
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Nunca nomeie um Environment que não existe** — o repositório do site não
  tem nenhum. O GitHub cria o que for nomeado, sem proteção.
- **Nunca aprove a sua própria requisição de Environment.**
- **Exclusão de objeto real exige aprovação humana explícita e nomeada.**

## 6. Armadilhas já pagas — não redescobrir

- **`to_dict()` do ledger falha fechado num lote parcial.** É o desenho. Por
  isso os lotes acumulam em `terminal_rows.json`, e agora `flush_rows()` roda
  no topo de cada iteração dos dois laços — o primeiro lote que morreu na
  linhagem **descartou o trabalho terminado de 17 aquisições** porque as linhas
  só eram escritas no fim.
- **O hook recusa o SHA do site.** Aconteceu nesta sessão. Forma curta.
- **`config/settings.py` carrega o `.env` de PRODUÇÃO no import**, e o guarda
  dos scripts verdes é **transitivo**. O driver importa `config` dentro de
  `command_run`, não no topo, para o `plan` não carregar o `.env`. Mantenha
  assim; há teste.
- **Mutação em arquivo enquanto o replay roda contamina o lote seguinte.** As
  nove mutações do módulo de regime foram aplicadas **em memória**, registrando
  o módulo mutado em `sys.modules` antes do `exec` — e o `@dataclass` resolve o
  seu módulo por `sys.modules`, então registre **antes** do `exec` ou ele
  levanta `AttributeError: 'NoneType'`.
- **Varredura de string pega docstring e comentário.** Use o AST. O docstring
  de `finalize_replay_candidate.py` **nomeia** o banco azul de propósito, e o
  teste prova que a varredura o pegaria se fosse executável.
- **Um teste pode passar pelo motivo errado.** Pergunte qual mutação ele
  derruba e derrube-a. As nove do módulo de regime foram mortas, cada uma pelo
  teste cujo docstring a nomeia.
- **Duas canonicalizações não são a mesma** (`1.0` vs `1`, `1e-07` vs `1e-7`);
  os documentos selados recusam float.
- **`cd` composto no shell das ferramentas pega, e PERSISTE.** Aconteceu três
  vezes nesta sessão. Caminho absoluto sempre.
- **`grep` desta máquina é `ugrep`**: `grep -qv` retorna 1 mesmo com linhas
  selecionadas; e `--include=*.py` sem aspas não casa nada no zsh.
- **Outra sessão pode estar no mesmo clone.** O `stash@{0}` de outra sessão
  continua intocado — não aplicado, não descartado. Confira `git status` antes
  de todo checkout e **nunca rode `git stash` ali**.
- **Confira `gh pr list --head <branch>` depois de cada push** e
  `pgrep -fl workerd` ao fim.

## 7. Estado que esta sessão herda

- **A execução longa rodou.** Diretório isolado durável, fora do repositório, e
  o caminho absoluto **não** está em documento nenhum (o `AGENTS.md` proíbe). Os
  compostos ficam em disco, então retomar é barato: o driver salta o download
  quando o arquivo existe.
- **O registro do regime sazonal existe** e diz que retirar
  `wet-season-mixed-lineage-v1` refaz **os meses 1-4 e só eles**.
- **A geração antiga está selada** como inventário imutável: 44 objetos,
  258 881 911 bytes, digest
  `3c279436f3815f628aa98cf3fa1eec867f8402061cbc1430dfd19e0b4af9d20e`, com a
  reivindicação do próprio produtor conferida contra o blob rastreado. O bullet
  1 fica **parcial**: a forma "release no store" continua aberta porque a
  identidade de release deriva de um ledger v3 e nenhum produtor azul escreve
  um.
- **A revisão pré-cutover do dono** continua pendente nos quatro itens que
  restam; é portão da **Phase 6** e não bloqueia a Phase 4.
- **Dois pré-requisitos da Phase 6, e NÃO são ação do dono hoje:** o endereço
  temporário do Worker de staging e o Environment protegido no site.
- **A PR draft `#21` do site** não deve ser mesclada antes da Phase 6.
- **O token da NASA expira em 2026-11-06**, e a falha aparece vermelha.
- **A `2.1.0` admite produtos pré-Collection-1 nos meses 1-4**; vigilância em
  `scripts/check_esa_reprocessing.py`.
- **Nenhum workflow deste repositório roda a suite Python** — CI é Phase 7.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

**O recálculo rodou, e ele encontrou dois problemas que eu não posso resolver
sozinho.** O primeiro é seu para decidir; o segundo é uma peça que falta ser
construída.

**Primeiro problema — e é o importante.** O sistema tem uma regra que diz: "se
eu não consigo saber com certeza se duas manchas de desmatamento são a mesma
mancha crescendo ou duas manchas diferentes que se encostaram, eu paro e peço
revisão humana". Essa regra foi aceita há tempo, de propósito, e está certa em
princípio.

O problema é que **a revisão humana nunca foi construída**, e no recálculo essa
situação acontece em **praticamente todas as datas**. Resultado: o recálculo
consegue acompanhar as manchas ao longo do tempo em **uma única data** — a
primeira, porque antes dela não havia nada com que confundir.

**E isso esvazia o resultado, não só o encurta.** O mapa que a página mostra por
padrão só inclui manchas vistas **pelo menos duas vezes** — é assim que o site
separa sinal de ruído. Se nada é acompanhado ao longo do tempo, nada chega a
duas vezes: das 22 753 manchas que o recálculo encontrou nas duas datas que
funcionaram, **zero** entrariam no mapa padrão. Então o recálculo, como está
hoje, **não produz nada publicável** — e é por isso que eu não o guardei no
depósito mesmo tendo como montá-lo.

**A magnitude, para comparar:** o satélite observou 90 datas. O sistema no ar
publica 44 delas. O recálculo produziu **2**.

**E eu descobri exatamente por que**, o que é a melhor notícia desta parte. Não
é que os dados de 2026 sejam confusos em todo lugar. É que **um único dia
bloqueia todos os seguintes durante seis meses**, assim:

1. O primeiro dia que funciona não tem com o que se confundir, então passa — e
   deixa 17 704 manchas registradas.
2. Todos os dias seguintes são comparados contra aquelas mesmas 17 704 manchas
   e travam nelas. E como travam, não conseguem substituí-las: o problema se
   auto-alimenta.
3. O sistema esquece uma mancha que não foi reconfirmada depois de **180
   dias**. Seis meses depois do primeiro dia, aquelas 17 704 foram esquecidas —
   e o dia seguinte passou, do zero, outra vez.
4. E aí recomeçou: esse dia deixou 5 049 manchas novas, e os dias depois dele
   voltaram a travar.

Eu **previ** que o dia 15 de agosto passaria, contando 180 dias a partir de 11
de fevereiro, antes de ver o resultado — e foi o que aconteceu. Isso significa
que a causa está entendida, não apenas observada, e é isso que torna a sua
decisão do item 1 possível de tomar com informação.

Duas coisas que o senhor precisa saber sobre isso:

1. **No sistema que está no ar hoje, isso funciona.** O acompanhamento das
   manchas ao longo do tempo está lá, com dezenas de milhares de manchas
   confirmadas. Então a regra não é impossível de satisfazer — é o recálculo
   que a esbarra sempre, e o sistema atual só às vezes.
2. **Descobri por que o sistema atual nunca parou nisso: ele descarta a data
   em silêncio.** Quando essa situação acontece, o programa anota um erro num
   arquivo de log que ninguém lê e segue para a próxima data. Isso explica um
   desencontro de números que estava sem explicação: o satélite observou **90
   datas** em 2026, o banco de dados tem **45**, e o site publica **40**. As
   que faltam não foram "não observadas" — algumas foram processadas e
   perdidas sem registro.

   No recálculo eu **não** deixei descartar em silêncio. Cada data que esbarra
   na regra fica registrada, com o motivo, para que a revisão saiba exatamente
   quais são.

**Segundo problema.** Para guardar o resultado no lugar certo falta uma peça:
existe o programa que valida o resultado e o programa que o publica, mas **não
existe nada que leve o resultado do meu computador até o depósito**. E a senha
desse depósito, por desenho, só existe dentro do GitHub. Não é uma peça que eu
possa improvisar sem afrouxar uma regra de segurança, então não improvisei.

**E uma coisa boa:** o recálculo é mais barato do que se pensava. Cada imagem
leva **47 segundos** em vez de 75, e ocupa **15 GB** em vez de 35.

### O que você precisa fazer

1. **Decidir a questão do acompanhamento das manchas** — é a única coisa que
   trava tudo, e é sua porque é uma decisão científica. Em linguagem simples: o
   que o sistema deve fazer quando não consegue distinguir uma mancha que
   cresceu de duas que se encostaram? As opções são (a) afrouxar a regra que
   decide quando duas manchas "se tocam", (b) construir a revisão humana que a
   regra pressupõe, ou (c) aceitar que essas datas fiquem sem acompanhamento
   temporal e sejam contadas como observações isoladas. **Não é urgente hoje**,
   mas nada avança sem ela. Eu não escolhi por você, e não vou.

2. **Mesclar a proposta desta sessão quando lhe convier** — é a número 59, e
   está aberta sem mesclar. Ela não muda nada do que está no ar: acrescenta o
   registro, as ferramentas e a documentação. Pode esperar.

3. **Anotar 6 de novembro:** a chave da NASA expira e o mapa de chuva para de
   novo. Essa falha é vermelha, não silenciosa, e é a única data no calendário.

### Tem algo preocupante?

**Sim, uma coisa — e não é sobre o recálculo.**

**O sistema que está no ar perde datas sem avisar.** Das 90 datas que o
satélite observou este ano, o banco tem 45 e o site publica 40. Parte dessa
diferença é legítima — nuvem, cobertura insuficiente, passagens que só raspam a
borda da área. Mas **parte é dado processado e descartado por causa de um erro
que virou linha de log**, e hoje não há como saber quanto é cada coisa, porque
o descarte não deixa registro.

Isso não quebra nada agora e não é urgente. Mas é exatamente o tipo de coisa
que não pode existir num sistema que vai sustentar uma publicação científica, e
o senhor deve saber que existe antes de a etapa de validação começar. O
recálculo já não faz isso — ele registra tudo o que descarta.

Fora disso: produção não foi tocada, o site publicado continua igual, nada foi
apagado, nenhuma senha ou chave foi usada, e nenhum arquivo do sistema no ar
foi modificado.

### O que ainda falta no caminho

- **Fechar o recálculo**, que depende da sua decisão do item 1 e da peça que
  falta para o depósito.
- **A validação científica** — a etapa que não começa sem a sua revisão,
  porque o objetivo passou a ser uma publicação. É lá que entram as duas
  medições que deixei prontas: a régua da cobertura das passagens estreitas e a
  comparação entre a referência antiga e a nova.
- **Uma etapa própria para a memória de publicações**, que é o que permitirá um
  dia apagar versões antigas com segurança.
- **A troca final:** o novo substitui o antigo, a página passa a ler pelo
  caminho novo, o robô antigo é desligado e a publicação passa a acontecer
  sozinha num horário. **É aqui que a sua revisão do roteiro é obrigatória.**
- **O endurecimento:** ligar as verificações automáticas nos dois repositórios
  (hoje elas só rodam na minha máquina), proteção de branch e acessibilidade.
