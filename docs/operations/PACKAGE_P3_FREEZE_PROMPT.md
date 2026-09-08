# Phase 3 — congelar e ensaiar o replay de 2026

Escrito em 2026-09-08, ao levar o Package 2A.6 para a `main` (PR `#54`, mesclada
com merge commit — os 34 commits científicos estão preservados).

A Phase 2B está fechada e o Package 2A.6 está na `main`. O roadmap não é
ambíguo sobre a ordem: o 2A.6 *"must close before Phase 3"*, e ele fechou.

**A Phase 3 é P0 antes de processamento caro.** Ela existe para que a Phase 4 —
reprocessar 2026 inteiro — não seja rodada duas vezes.

Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

---

## 1. Dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:ROADMAP.md | sed -n '/^### Phase 3 —/,/^### Phase 4 —/p'

Medido na `main` em `ed5f913a562198ad8613927750bfd51a37513905`:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **1586 passed** |
| site | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **201 passed** |
| site | `npm ci && npm run test:worker` | **44 tests, 44 pass** |

**`ROADMAP.md` na `main` É o plano agora** — mudou em 2026-09-08. Não existe
mais "o outro ROADMAP". O rastreador que ocupava aquele nome está em
`docs/implementation/PENDING_CAPABILITIES.md` e **não** é o plano. A branch
`claude/phase2a6d-mapbiomas` fica pela história; **não** leia o `ROADMAP.md`
dela como canônico.

**Use `npm run test:worker`, não `node --test tests/`** — nesta máquina o Node é
v25 e a segunda forma morre com `MODULE_NOT_FOUND`, um fracasso que parece do
repositório e é da invocação.

## 2. O que já foi verificado, para o executor não refazer

**a. Os insumos de cota e data de corte estão medidos.** Leia
[`PHASE_3_INPUTS_2026-09-08.md`](PHASE_3_INPUTS_2026-09-08.md) **integralmente**
antes de tocar nos bullets 1 e 5 do roadmap. Não refaça a análise; ela já
conclui:
- a cota do projeto `ee-araripe` é **3.600.000 EECU-s/mês**, com **0,17%**
  usados. A cota **não limita** a Phase 4;
- o corte recomendado é uma **regra** (a última data que o ledger declara
  terminal no momento da consulta da Phase 4, resolvida e fixada como literal no
  registro daquela execução) mais uma **data provisória para o ensaio:
  `2026-08-30`**, que é o que `data/timeseries/RELEASE.json` declara como
  `latest_observation`;
- a fila pós-corte tem de ser **enfileirada de propósito**. Sem registro
  explícito, "data enfileirada" e "data perdida" não são distinguíveis.

**b. O exit gate P2B está fechado**, provado contra o R2 real com dado de
execução real. Registro em
[`../implementation/PHASE_2B_GATE_2026-09-08.md`](../implementation/PHASE_2B_GATE_2026-09-08.md).
O ponteiro verde de staging está na **sequência 9**, `action: rollback`, e
`araripe-v2-staging` tem **62 objetos**. `plan_retention.py` diz `eligible 0`.

**c. O landing do 2A.6 está registrado**, com duas correções de afirmação e um
achado científico, em
[`../implementation/PHASE_2A6_LANDING_2026-09-08.md`](../implementation/PHASE_2A6_LANDING_2026-09-08.md).
Leia a §3 antes de mexer em persistência: a aquisição fora de ordem passou a ser
**recusada**, e `scripts/r2_state.py` continua tolerando
`first_seen > last_seen` por um motivo **novo** — o produtor promete daqui para
frente, e o estado vivo é anterior à promessa.

**d. MEDIDO — a detecção NÃO emite ledger v3, e a causa é o insumo.**
`ProcessingLedgerV3` e `CompositionRunV3` estão na `main`. Falta o datatake
físico (`platform`, `datatake_id`, `acquisition_timestamp_utc`). Contagem de
`DATATAKE_IDENTIFIER`/`SPACECRAFT_NAME`/`platform`:

| script | ocorrências |
| --- | --- |
| `scripts/build_baseline_v2_gee.py` | **80** |
| `scripts/build_detection_gee.py` | **0** |

O mecanismo do lado da baseline é reutilizável: lê as propriedades da cena,
normaliza com `normalize_platform`, deriva o timestamp de
`datatake_id.split("_")[1]` como `%Y%m%dT%H%M%S`. **Verificado que nenhum
workflow roda `build_detection_gee.py`** — é passo manual de Cloud Shell, então
editá-lo **não é** mudança de runtime azul.

**e. MEDIDO — a detecção NÃO sabe usar a baseline 2.1.0, e isso é decisão desta
fase, por escrito.** `config/settings.py` declara
`BASELINE_VERSION = "1.0.0"` e `BASELINE_MANIFEST_PATH = baseline_manifest_v1.json`.
A baseline **2.1.0** existe (`config/baseline_manifest_v2_1.json`, `build_date`
2026-09-06) com os dados em `data/baselines_v2/2.1.0/`, e é lida **só** pelos
módulos de construção e validação — **nunca** por `src/detection/baseline.py`
nem por `run_detection*.py` (varredura: zero referências).

Isso não é um esquecimento. O registro do 2A.6D diz literalmente:

> *"Compatible baseline: **2.1.0 built and validated**; runtime activation
> deliberately belongs to the replay packages."*

**Ou seja: ativar a 2.1.0 no runtime é trabalho desta fase, por decisão
explícita do package anterior.**

**f. O ensaio tem lane.** `.github/workflows/v2_candidate_replay.yml` é
`workflow_dispatch` **somente**, sem schedule, sem push. É a lane 2 do desenho
de concorrência.

**g. Ferramenta de auditoria que já existe:** `scripts/audit_baselines.py`,
`scripts/audit_timeseries.py`, `scripts/r2_state.py`. **Não escreva um
snapshotter novo antes de ler os três.**

**h. Os 22,5 GB de insumo científico local** (`data/baselines_v2/`,
`data/landcover/updated/`, `data/validation/`) passaram a ser **corretamente
ignorados** pelo `.gitignore` no landing. Eles ficam **fora** de todo commit.

## 3. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: esta fase é o portão que decide se a Phase 4 roda **uma** vez. Duas
> ativações de runtime (§2d e §2e) mudam o que o replay produz, e errar qualquer
> uma significa reprocessar o ano inteiro de novo — ou pior, produzir um
> candidato que parece válido e foi comparado contra a baseline errada.

Feche o **exit gate P3**: *"The small rehearsal is reproducible, completeness
checks pass, rollback works, and the full replay can run without mutating the
live release."*

**Orientação obrigatória antes de qualquer conclusão.** Siga "Establishing the
real state" do `AGENTS.md` do workspace nos **dois** repositórios. Leia canônico
com `git show origin/main:<path>`. Cole o SHA de 40 caracteres da base lido de
`git rev-parse origin/main`. Ative o hook com
`git config core.hooksPath .githooks` — ele recusa qualquer SHA de 40 caracteres
que não exista *naquele* repositório, inclusive o SHA legítimo do outro
repositório do workspace. Para citar o SHA do site, use a forma curta.

**Base.** Uma branch nova a partir de `origin/main`.

### Escopo

1. **As duas ativações de runtime, e são o coração desta fase.**
   - **a baseline 2.1.0** (§2e): fazer `src/detection/baseline.py` e os
     `run_detection*` capazes de carregar a baseline v2, e **decidir e registrar
     qual versão o replay usa**. Se for a 2.1.0, `BASELINE_VERSION` e
     `BASELINE_MANIFEST_PATH` mudam — e essa mudança **afeta o caminho azul**,
     então tem de ser expressável sem alterar o que a produção congelada faz
     hoje. Prove a inércia, não a afirme;
   - **o metadado de datatake no export** (§2d): portar o mecanismo do export de
     baseline para `build_detection_gee.py`, para que o re-export do replay
     carregue os campos físicos e o ledger passe a ser **produzido por
     execução** em vez de declarado. Validável localmente contra propriedades de
     cena gravadas; não há como validar contra o GEE nesta máquina.
2. **Congelar as versões** — extensão, algoritmo, baseline, máscara/mosaico,
   seca, MapBiomas, rótulos, schema, ambiente e release. O bullet do roadmap
   pede isso e **nenhuma delas depende do corte**. Um congelamento que não é
   verificável por teste não é congelamento: prefira um pin medido a uma lista
   em prosa.
3. **A fotografia com checksum** dos alertas no R2, objetos de baseline, estado
   de persistência, banco SQLite, manifest do site, produtos públicos e os
   commits dos **dois** repositórios. Leia §2g antes de escrever ferramenta
   nova.
4. **O ensaio limitado**: um intervalo de datas pequeno, com recuperação de
   falha, reversão de ponteiro e recuperação de data enfileirada. A lane é a
   §2f. **Sem mutar a release viva.**
5. **O registro da fila pós-corte** (§2a), explícito e consumível pelo cutover.
6. **O runbook e a revisão do dono** antes do cutover — o bullet pede revisão
   explícita.
7. **Registrar** em `docs/implementation/PHASE_3_<data>.md`, com o estado do
   exit gate P3 e o que continua sem prova.

**Fora de escopo, explicitamente:** rodar a Phase 4 (o reprocessamento inteiro);
o cutover, o desligamento do bot azul, ligar a página à rota nova e qualquer
coisa no domínio final (**Phase 6**); a validação qualificada (**Phase 5**, com
portão de revisão do dono); o histórico durável de promoção e qualquer exclusão
real (packages próprios). **Não inicie as Fases 4, 5, 6 nem 7.**

## 4. Decisões de escopo já tomadas, com sua base

- **Nenhum segundo produtor de ledger.** A detecção produz; o montador consome.
- **Nada é apagado.** Nem no R2 nem na história do git. E agora é **requisito**,
  não prudência: a Phase 5 vira publicação científica, e um artigo cita **uma**
  release, que passa a ter de existir para sempre.
- **Nenhuma lane verde carrega cron antes da Phase 6.**
- **A rota verde é aditiva em `/data/green/`**; o `/data/…` estático é o
  rollback.
- **v1 é audit-only** e não recebe dado v2 serializado.
- **A produção azul continua rodando.** O roadmap é explícito: *"do not pause
  current automation for the long rebuild"*. Um freeze curto de escrita azul só
  é permitido na janela de cutover da Phase 6.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- A `main` do backend é **pull-request-only**, bypass vazio. Branch, PR.
- **A `main` do site faz deploy de produção.**
- Produção congelada nas Fases 2B–5: Worker `observatorio-chapada`,
  `araripe-cogs`, domínio final, DNS, rotas, workflows azuis, ponteiros
  canônicos, artefatos publicados.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. **Nunca dispare para testar.**
- Claude não recebe credencial de control-plane da Cloudflare; o único caminho é
  uma operação já allowlistada no broker protegido, cuja lista é exatamente
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Nunca nomeie um Environment que não existe** — o GitHub o cria, sem proteção.
- **Exclusão de objeto real exige aprovação humana explícita e nomeada.**

## 6. Armadilhas já pagas — não redescobrir

- **`git diff A B` não diz o que um merge faz.** É diff de dois pontos entre as
  pontas. Em 2026-09-08 isso me fez escrever que um merge apagaria 93 arquivos;
  zero deles existia no merge base. Calcule o merge:
  `git merge-tree --write-tree`, que não toca a árvore.
- **Merge limpo pode esconder colisão.** Os dois lados adicionaram a **mesma**
  função em regiões diferentes de um arquivo; git não viu conflito e Python usou
  a última, deixando a outra inalcançável.
  `tests/test_landing_preserves_both_sides.py` fixa isso por `ast`.
- **Um teste pode passar pelo motivo errado, inclusive um teste escrito para
  pegar isso.** `tests/test_instruction_crossrefs.py` nasceu checando se a seção
  `§N` existia — e `§6` existe em dois documentos com assuntos diferentes, então
  a mutação passou. Pergunte sempre **qual mutação o teste derruba**, e derrube-a.
- **Não confie em invariante que o produtor não promete.** Duas vezes já:
  `first_seen <= last_seen` (derrubou produção em 2026-09-07) e uma checagem que
  exigia que todo arquivo no diretório de alertas fosse da rodada corrente
  (recusou a rodada real).
- **`config/settings.py` carrega o `.env` de PRODUÇÃO no import.** Nenhum script
  verde pode importá-lo, e um teste afirma isso por `ast`. **Atenção nesta
  fase:** o caminho de detecção **é** azul e importa `config.settings` — a
  ativação da baseline não pode virar uma ponte que traga essa importação para o
  lane verde.
- **Outra sessão pode estar no mesmo clone.** Existe um `stash@{0}` de outra
  sessão no backend. **Nunca `git stash` em árvore alheia**; adicione por nome e
  confira `git status` antes de todo checkout.
- **O hook `commit-msg` recusa SHA estrangeiro.** Ver §3.
- **`grep` desta máquina é `ugrep`**: `grep -qv` retorna 1 mesmo com linhas
  selecionadas. Capture a saída e teste se está vazia.
- **`cd` composto no shell das ferramentas pode não pegar.** Caminho absoluto.
- **Confira `gh pr list --head <branch>` depois de cada push** — em 2026-09-08
  oito commits ficaram órfãos por não conferir.
- **O arnês de rota verde vazava `workerd`.** Corrigido, mas confira
  `pgrep -fl workerd` ao fim de cada execução.
- **`ee.Initialize()` ignora `GOOGLE_APPLICATION_CREDENTIALS`.** Não "corrija"
  os scripts locais.

## 7. Ao final

Testes fail-closed e determinísticos: sem rede, sem relógio real, sem object
store, sem credencial. Rode
`/opt/anaconda3/envs/araripe/bin/python -m pytest -q` no backend e
`npm ci && npm run build && npm test && npm run test:worker` no site; reporte
falhas pré-existentes em separado. Confira `pgrep -fl workerd` e árvore limpa —
os `data/` grandes ficam **fora**. Commits por repositório, **nunca misturados**,
com base verificada. Crie `docs/implementation/PHASE_3_<data>.md`. Abra as PRs
**sem mesclar**. Termine com o estado do exit gate P3 e com a seção final
obrigatória do método de handoff.

**Não inicie a Phase 4.**

## 8. Estado que esta fase herda

- **Phase 2B fechada**, exit gate P2B provado contra o R2 real (§2b).
- **Package 2A.6 na `main`** (`#54`, merge commit — 34 commits preservados).
- **`ROADMAP.md` na `main` é o plano** desde 2026-09-08; o rastreador antigo
  está em `docs/implementation/PENDING_CAPABILITIES.md`.
- **Duas ativações de runtime pendentes e nomeadas:** baseline 2.1.0 (§2e) e
  metadado de datatake no export (§2d). **As duas são desta fase.**
- **Environments do backend:** `cloudflare-green-control` (com revisor),
  `v2-staging` e `v2-promotion` (sem revisor, política `main`). **O repositório
  do site não tem Environment nenhum.**
- **Dois pré-requisitos da Phase 6, e NÃO são ação do dono hoje:** o endereço
  temporário do Worker de staging e o Environment protegido no site. São a
  **mesma autoridade** (`Workers Scripts: Edit` de conta, que alcança o Worker
  de produção), e **nenhum bullet das Fases 3, 4 e 5 depende deles** — varredura
  feita. `tests/test_handoff_prompt_method.py` falha se voltarem para a lista do
  dono.
- **A PR draft `#21` do site** (parar de commitar os alertas) **não deve ser
  mesclada** antes da Phase 6.
- **A chuva do site está pulando por rede** — não é o token e não é o nosso
  código. Primeiro dia vermelho: **22 de setembro de 2026**; qualquer rodada
  bem-sucedida zera o contador. **Sexta 2026-09-11 não fica vermelha.**
- **Pendência com data: o token da NASA expira em 2026-11-06**, e essa falha
  aparece vermelha no download.
- **Mesmo padrão suspeito no fallback do backend**, sem prazo: o passo "Run
  detection pipeline" do `update_data.yml` passa usuário e senha do Earthdata e
  não foi verificado se `run_detection.py` chega a fazer login. Pode ser que a
  correção certa seja **remover** as duas linhas.

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

**Nada da etapa anterior** — o trabalho científico entrou no tronco principal e
a fase fechou. Este documento **é** o insumo da próxima.

Duas coisas que valem saber, e as duas são consequência do que entrou:

1. **O trabalho científico trouxe uma baseline nova (a 2.1.0) que o sistema de
   detecção ainda não sabe usar.** Não é esquecimento: o pacote anterior
   registrou por escrito que "ligar isso no funcionamento real pertence às
   etapas do reprocessamento". É a próxima etapa que liga — e é a decisão mais
   consequente dela, porque é contra essa baseline que o ano inteiro vai ser
   comparado.
2. **O documento de auditoria de cada publicação ainda é preparado à mão**, e a
   razão está medida: o arquivo que exporta as imagens de detecção não anota de
   qual passagem do satélite cada imagem veio. O export da baseline já anota, e
   o mecanismo se copia. Só faz sentido fazer isso junto com o re-export do
   reprocessamento, porque a anotação não conserta imagem já exportada.

### O que você precisa fazer

1. **Colar o prompt da próxima sessão**, que vai junto com esta entrega.
2. **Mesclar duas propostas, quando quiser** — uma no repositório do
   monitoramento e uma no do site. As duas são só texto e um teste; não mudam
   nada do que está publicado.
3. **Não mesclar ainda** a proposta que tira os arquivos grandes (a `#21` do
   site). Ela entra na troca final.
4. **Ler uma pergunta da próxima etapa quando ela chegar:** qual baseline o
   reprocessamento usa. Não precisa decidir agora — a sessão vai medir as duas e
   trazer a recomendação. Mas é decisão sua, porque é científica.
5. **Anotar 6 de novembro:** a chave da NASA expira e o mapa de chuva para de
   novo — e essa falha é vermelha, não silenciosa.

Sobre a chuva: continua pulando por problema de rede entre o robô do GitHub e o
servidor da NASA. O primeiro dia vermelho é **22 de setembro**, e qualquer
rodada bem-sucedida zera o contador. Não é preciso fazer nada.

### Tem algo preocupante?

**Nada quebrado.** Produção não foi tocada, o site publicado continua igual, e
nada foi apagado em lugar nenhum.

Vale registrar um cuidado, e não é alarme: **a próxima etapa é a última barata.**
Ela existe justamente para que o reprocessamento do ano inteiro — que é a etapa
seguinte, e a caríssima em tempo de máquina — rode **uma** vez. Se a baseline
errada for congelada ali, o resultado não fica obviamente errado: fica
plausível, e comparado contra a referência errada. É por isso que a próxima
etapa pede atenção e não pressa, e é por isso que a pergunta da baseline volta
para você.

Duas coisas que eu mesmo errei ao preparar esta entrega, e as duas ficaram
consertadas com teste: li um diff de git como se fosse um merge e escrevi um
alarme falso em cima disso; e escrevi um teste para pegar referência quebrada
que **não pegava** a referência quebrada, porque conferia o número da seção e
não o assunto. A segunda é a mais instrutiva — um teste verde não é evidência
até você derrubá-lo de propósito.

### O que ainda falta no caminho

- **Congelar e ensaiar** — a próxima etapa, e o portão da seguinte. Inclui as
  duas ligações descritas acima.
- **Reprocessar 2026 inteiro** num candidato guardado, sem publicar. É tempo de
  máquina, e a cota não limita: 0,17% usados.
- **A validação científica** — a etapa que você pediu para não travar nada, e
  que agora tem portão: ela não começa sem a sua revisão, porque o objetivo
  passou a ser uma publicação.
- **Uma etapa própria para a memória de publicações**, que é o que permitirá um
  dia apagar versões antigas com segurança — e que a publicação transformou de
  prudência em requisito.
- **A troca final:** o novo substitui o antigo, a página passa a ler pelo
  caminho novo, o robô antigo é desligado, o endereço público antigo é fechado,
  e a publicação passa a acontecer sozinha num horário. É aqui que os dois
  pré-requisitos guardados se pagam.
- **O endurecimento:** CI completo, proteção de branch, acessibilidade e as
  skills reusáveis.
