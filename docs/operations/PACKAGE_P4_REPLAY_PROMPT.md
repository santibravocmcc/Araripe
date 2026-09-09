# Phase 4 — reprocessar 2026 inteiro num candidato guardado

Escrito em 2026-09-08, ao fechar a Phase 3. Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é para
o agente executor e a **seção final é para o dono**.

**A Phase 3 fechou o seu gate.** As duas ativações de runtime entraram, as
versões estão congeladas com pin medido, a fotografia está tirada, a fila está
registrada e o ensaio limitado rodou. O que falta antes de processar é **uma
decisão do dono**, e ela é científica.

**Esta é a fase caríssima em tempo de máquina.** A Phase 3 existiu para que ela
rode **uma** vez.

---

## 0. A decisão do dono que precede tudo

**Qual baseline o replay usa.** O runbook
[`PHASE_3_REPLAY_RUNBOOK.md`](PHASE_3_REPLAY_RUNBOOK.md) §2.1 traz a
comparação medida e a recomendação técnica (**2.1.0**) com o custo dela por
inteiro. `config/phase3_replay_freeze_v1.json` registra
`baseline.replay_generation.decided = false`.

**Não processe sem essa decisão registrada.** É contra essa geração que o ano
inteiro é comparado, e um candidato comparado contra a referência errada não
fica obviamente errado — fica plausível.

A revisão do runbook (§7 dele) é a mesma conversa e também está pendente.

## 1. Dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:ROADMAP.md | sed -n '/^### Phase 4 —/,/^### Phase 5 —/p'
    git show origin/main:docs/implementation/PHASE_3_2026-09-08.md

Medido na `main` em `c39c5238d8e939f6a37bc9060ea5c9ec6da8bd3e` **antes** desta
fase; a PR da Phase 3 acrescenta 130 testes ao backend e 2 ao site:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **1593** na base, **1723** com a PR da Phase 3 |
| site | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **201** na base, **203** com a PR do site |
| site | `npm ci && npm run test:worker` | **44 tests, 44 pass** |

**`ROADMAP.md` na `main` É o plano.** O rastreador está em
`docs/implementation/PENDING_CAPABILITIES.md` e **não** é o plano.

**Use `npm run test:worker`, não `node --test tests/`** — nesta máquina o Node é
v25 e a segunda forma morre com `MODULE_NOT_FOUND`, um fracasso que parece do
repositório e é da invocação.

**Ative o hook** com `git config core.hooksPath .githooks`. Ele recusa qualquer
SHA de 40 caracteres que não exista *naquele* repositório — **incluindo o SHA
legítimo do site**, o que aconteceu nesta sessão na primeira tentativa de um
commit. Para citar o site, use a forma curta.

## 2. O que já foi verificado, para o executor não refazer

**a. As duas ativações de runtime estão feitas.**

- **Baseline:** `src/detection/baseline_selection.py` é um registro fechado com
  resolvedor fail-closed. Os três `run_detection*` aceitam
  `--baseline-version` (default `None` → o default azul de
  `config/settings.py`, intocado) e gravam na persistência a versão
  **resolvida**. `run_detection_gee.py` resolve **antes** de tocar o Earth
  Engine. A 2.0.0 é recusada nomeando a 2.1.0 como sucessora.
- **Datatake:** `scripts/build_detection_gee.py` enumera os datatakes físicos e
  escreve `araripe_detection_run_manifest_v3.json`, aditivo — o
  `araripe_detection_acquisitions.json` que `load_composite_acquisition` consome
  ficou intacto em forma. `import ee` e `ee.Initialize` foram para dentro de
  `main()`, então a derivação é importável e testada.

**b. O congelamento é um pin medido, não uma lista em prosa.**
`config/phase3_replay_freeze_v1.json`, `freeze_sha256`
`3554cf715af82cc80be591ddc115e5390a2f2e1bd39894b7e1a6f31b6a481fa3`. Comece
rodando `pytest -q tests/test_replay_freeze.py`: se cair, uma constante
congelada mudou, e descobrir qual vem antes de processar.

**c. A fotografia e a fila estão gravadas**, com a árvore limpa:
`docs/implementation/PHASE_3_SNAPSHOT_2026-08-30.json` e
`PHASE_3_POST_CUTOFF_QUEUE_2026-08-30.json`. Dois assuntos estão **declarados
não medidos com a razão**: o inventário de alertas no R2 (nenhuma credencial) e
`data/persistence_state.geojson` (não existe localmente).

**d. MEDIDO — a unidade de composição diverge, e é decisão desta fase.**
`CompositionRunV3` amarra `composite_method_id` a
`coverage-ranked-first-valid-v1` — escopado por **datatake** —
(`src/detection/composition_run_v3.py:189`), enquanto o export mosaica a **data**
inteira sob `daily_mosaic-v1`. Por isso o export **não** pré-computa
`acquisition_id`: um primeiro rascunho o fez e os valores não batiam.
`tests/test_detection_export_datatakes.py::test_a_divergencia_de_metodo_de_composicao_esta_medida_e_nao_suposta`
fixa a divergência onde ela se romperia. **As duas opções existem no código:**
`CompositionRunV3.compose_all` compõe por datatake a partir de bandas, e o
export por data já produz compostos prontos.

**e. MEDIDO — a grade do export não está prometida.** Ele pede só `crs` e
`scale`, sem `crsTransform`, então a origem é escolha do Earth Engine. A
evidência de que ninguém assumiu alinhamento com a baseline é o
`reindex_like(..., method="nearest", tolerance=15)` em
`scripts/run_detection_from_gee.py`. Fixar a transform removeria aquele reindex
e **mudaria pixels exportados** — decisão desta fase, não de metadado.

**f. MEDIDO — a estimativa de cota tinha um insumo errado, e a conclusão
sobrevive.** `PHASE_3_INPUTS_2026-09-08.md` §1 parte de
`SEARCH_DAYS_BACK = 16`; o valor é **5** (`config/settings.py:53`, e o mesmo em
`ed5f913`). A aritmética corrigida dá ~**5,6 X** em vez de 1,75 X, ou ~**19% de
um mês** de alocação em vez de ~6%. A cota **continua não limitando**; o que não
sobrevive é a margem declarada de 10×. Detalhe em
`docs/implementation/PHASE_3_2026-09-08.md` §3. **Não refaça a análise.**

**g. MEDIDO — a baseline 2.1.0 está íntegra em disco.** Os 72 rasters (13 GB)
estão em `data/baselines_v2/2.1.0/` e os **72 casam byte a byte** com o
manifest. A 1.0.0 **não está local** — a produção a busca do R2 — então a
comparação pixel a pixel entre as duas **não foi feita** e não pode ser feita
aqui sem baixar de produção.

**h. MEDIDO — a cadeia GEE inteira não foi exercitada.** Nenhuma chamada foi
feita: `ee.Initialize()` ignora `GOOGLE_APPLICATION_CREDENTIALS` e esta máquina
não tem credencial de serviço. A enumeração está validada contra propriedades de
cena **gravadas** e a paridade com a biblioteca está provada; o que **não** está
provado é que `reduceColumns(Reducer.toList(7, 1), …)` devolve as sete colunas
nesta ordem para esta coleção. **Comece por uma janela de poucos dias e confira
o manifest antes de enfileirar 242 datas.**

**i. O ensaio já provou a sequência.** `tests/test_replay_rehearsal.py` roda
staging → falha → retentativa → reversão → drenagem contra um store que impõe as
precondições do R2 e **que pode falhar quando mandado**. Ponteiro 1 → 2 → **3
(rollback)** → 4. Não reescreva; estenda se precisar.

**j. Ferramentas que já existem — leia antes de escrever nova:**
`scripts/snapshot_replay_freeze.py`, `scripts/audit_baselines.py`,
`scripts/audit_timeseries.py`, `scripts/r2_state.py`,
`scripts/check_processing_ledger.py`, `scripts/assemble_green_run.py`,
`scripts/stage_green_run.py`, `scripts/publish_green_release.py`.

**k. Os 22,5 GB de insumo científico local** (`data/baselines_v2/`,
`data/landcover/updated/`, `data/validation/`) são ignorados pelo `.gitignore` e
ficam **fora** de todo commit.

## 3. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: é a fase caríssima em tempo de máquina, e a Phase 3 existiu para que
> ela rode **uma** vez. Errar a unidade de composição ou a baseline significa
> reprocessar o ano inteiro de novo — ou pior, produzir um candidato plausível
> comparado contra a referência errada.

Feche o **exit gate P4**: *"One complete, internally consistent, reproducible
2026 candidate exists in staging; every manifest-bound expected acquisition has
one terminal ledger row, every daily summary reconciles those rows, and no
artifact status is unresolved."*

**Orientação obrigatória antes de qualquer conclusão.** Siga "Establishing the
real state" do `AGENTS.md` do workspace nos **dois** repositórios. Leia canônico
com `git show origin/main:<path>`. Cole o SHA de 40 caracteres lido de
`git rev-parse origin/main`.

**Base.** Uma branch nova a partir de `origin/main`. A `main` dos dois
repositórios é pull-request-only.

### Escopo, na ordem em que se sustenta

1. **Registrar a decisão da baseline** (§0) e a revisão do runbook. Sem elas,
   pare.
2. **Decidir a unidade de composição** (§2d) por escrito, com a base. É a
   segunda decisão mais consequente da fase, e a divergência já está medida.
3. **Preservar a geração antiga como release histórica imutável** — bullet 1 do
   roadmap. Nada é apagado, e desde que a Phase 5 virou publicação científica
   isso é **requisito**, não prudência.
4. **Re-exportar** com `build_detection_gee.py`, começando por uma janela de
   poucos dias (§2h) e conferindo o run manifest antes do lote grande.
5. **Resolver o corte** com `resolve_recorded_cutoff` e **fixar o literal** no
   registro da execução. Gravar a fila pós-corte com esse corte.
6. **Processar em lotes cronológicos limitados** com estado isolado
   (`--persistence-mode rebuild --state-path <isolado>`), a partir de estado
   vazio, uma vez por observação aceita, em ordem de timestamp e ID.
7. **Registrar cada aquisição esperada** num dos sete estados terminais, e
   derivar o resumo diário **só** depois de todas as aquisições daquela data
   serem terminais.
8. **Verificar** IDs, cobertura, checksums, reconciliação diária e artefatos
   antes de aceitar cada lote.
9. **Aplicar as anotações versionadas do MapBiomas** e os campos de assinatura
   contextual **sem remover detecção crua**.
10. **Regenerar** tiers de persistência, subconjuntos fortes, estatísticas e as
    linhas limpas de série temporal de 2026.
11. **Reconciliar o candidato e deixá-lo em staging. NÃO promover.**
12. **Registrar** em `docs/implementation/PHASE_4_<data>.md`, com o estado do
    gate P4 e o que continua sem prova.

**Fora de escopo, explicitamente:** promover o candidato; a validação
qualificada (**Phase 5**, com portão de revisão do dono, e ela **não** começa
sem essa revisão); o cutover, o desligamento do bot azul, ligar a página à rota
nova e qualquer coisa no domínio final (**Phase 6**); o histórico durável de
promoção e qualquer exclusão real (packages próprios). **Não inicie as Fases 5,
6 nem 7.**

## 4. Decisões de escopo já tomadas, com a base

- **Nenhum segundo produtor de ledger.** A detecção produz; o montador consome.
- **Nada é apagado.** Nem no R2 nem na história do git, e agora é requisito.
- **Nenhuma lane verde carrega cron antes da Phase 6.**
- **A rota verde é aditiva em `/data/green/`**; o `/data/…` estático é o
  rollback.
- **v1 é audit-only** e não recebe dado v2 serializado.
- **A produção azul continua rodando.** O roadmap é explícito: *"do not pause
  current automation for the long rebuild"*. Um freeze curto de escrita azul só
  é permitido na janela de cutover da Phase 6.
- **O corte é inclusivo do lado do lote**, porque a Phase 4 consulta *"from
  January 1 through the recorded cutoff"*.
- **A release viva do azul é fotografia e não pin.** A deriva é esperada e
  reportada por ferramenta, nunca por teste.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- A `main` do backend é **pull-request-only**, bypass vazio. Branch, PR.
- **A `main` do site faz deploy de produção.**
- Produção congelada nas Fases 2B-5: Worker `observatorio-chapada`,
  `araripe-cogs`, domínio final, DNS, rotas, workflows azuis, ponteiros
  canônicos, artefatos publicados.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. **Nunca dispare para testar.**
- O ensaio e o replay escrevem **só** em `araripe-v2-staging`;
  `src/replay/rehearsal.staging_bucket_only` recusa qualquer outro store.
- Claude não recebe credencial de control-plane da Cloudflare; o único caminho é
  uma operação já allowlistada no broker protegido, cuja lista é exatamente
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Nunca nomeie um Environment que não existe** — o GitHub o cria, sem
  proteção. **O repositório do site não tem Environment nenhum.**
- **Exclusão de objeto real exige aprovação humana explícita e nomeada.**

## 6. Armadilhas já pagas — não redescobrir

- **`config/settings.py` carrega o `.env` de PRODUÇÃO no import.** O guarda que
  proibia isso nos cinco scripts verdes olhava só o AST do **próprio** script, e
  isso não bastava: medido, com
  `from src.detection.baseline_selection import resolve_baseline` acrescentado a
  `scripts/plan_retention.py`, o guarda antigo **passa**. O novo
  (`test_nenhum_script_verde_alcanca_o_carregador_de_dotenv_transitivamente`)
  falha e nomeia a cadeia. **Não faça um script verde alcançar `config`, nem por
  dois saltos.**
- **Duas canonicalizações não são a mesma.** Medido:
  `json.dumps(sort_keys=True, separators=(",",":"))` e a forma RFC 8785 da
  biblioteca discordam em float de valor integral (`1.0` vs `1`) e em expoente
  (`1e-07` vs `1e-7`). Por isso o manifest do export e o congelamento **recusam
  float** e gravam decimal em texto.
- **`FakeS3.__init__` copia o dict de objetos.** Construir um segundo store com
  `objects=fake.objects` lhe dá um retrato de **antes**, e a falha aparece como
  "release.json is absent" — que parece do `atomic_publish` e é do arnês.
- **Um teste pode passar pelo motivo errado.** Além do guarda acima, o site
  tinha `assert len(runs) == 40` no manifesto publicado: medido, a próxima
  publicação **bem-sucedida** o derrubaria. Pergunte sempre **qual mutação o
  teste derruba**, e derrube-a.
- **`git diff A B` não diz o que um merge faz.** Calcule com
  `git merge-tree --write-tree`.
- **Não confie em invariante que o produtor não promete.**
  `first_seen <= last_seen` derrubou produção em 2026-09-07.
- **Outra sessão pode estar no mesmo clone.** Havia um `stash@{0}` de outra
  sessão no backend nesta sessão; ele **não** foi aplicado nem descartado.
  **Nunca `git stash` em árvore alheia**; adicione por nome e confira
  `git status` antes de todo checkout.
- **`cd` composto no shell das ferramentas pega, e PERSISTE.** Um
  `cd ../site && …` mudou o diretório da sessão e a chamada seguinte rodou o
  arquivo errado. Caminho absoluto.
- **Caminho absoluto num documento commitado.** A primeira fotografia gravava
  `/Users/sbravo/...`; além de o `AGENTS.md` proibir, faria duas fotografias da
  mesma árvore diferirem por quem as tirou.
- **`grep` desta máquina é `ugrep`**: `grep -qv` retorna 1 mesmo com linhas
  selecionadas. Capture a saída e teste se está vazia.
- **Confira `gh pr list --head <branch>` depois de cada push** — em 2026-09-08
  oito commits ficaram órfãos por não conferir.
- **`ee.Initialize()` ignora `GOOGLE_APPLICATION_CREDENTIALS`.** Não "corrija"
  os scripts locais.
- **O arnês de rota verde vazava `workerd`.** Corrigido, mas confira
  `pgrep -fl workerd` ao fim de cada execução.

## 7. Ao final

Testes fail-closed e determinísticos: sem rede, sem relógio real, sem object
store, sem credencial — exceto o que a re-exportação exigir do Earth Engine, que
é execução e não teste. Rode
`/opt/anaconda3/envs/araripe/bin/python -m pytest -q` no backend e
`npm ci && npm run build && npm test && npm run test:worker` no site; reporte
falhas pré-existentes em separado. Confira `pgrep -fl workerd` e árvore limpa —
os `data/` grandes ficam **fora**. Commits por repositório, **nunca misturados**,
com base verificada. Crie `docs/implementation/PHASE_4_<data>.md`. Abra as PRs
**sem mesclar**. Termine com o estado do exit gate P4 e com a seção final
obrigatória do método de handoff.

**Não promova o candidato. Não inicie a Phase 5.**

## 8. Estado que esta fase herda

- **Phase 2B fechada**; **Package 2A.6 na `main`** (`#54`); **Phase 3 fechada**
  com uma decisão do dono pendente.
- **`ROADMAP.md` na `main` é o plano** desde 2026-09-08.
- **Duas PRs abertas e não mescladas** ao fim da Phase 3: a do backend e a do
  site. As duas são texto, teste e documento; nenhuma muda o que está publicado.
- **A fila pós-corte registrada tem 0 datas**, porque a última data do banco de
  série temporal É a data provisória do corte. Ela cresce a ~2 datas observadas
  por semana enquanto as Fases 4 e 5 correm.
- **Environments do backend:** `cloudflare-green-control` (com revisor),
  `v2-staging` e `v2-promotion` (sem revisor, política `main`). **O repositório
  do site não tem Environment nenhum.**
- **Dois pré-requisitos da Phase 6, e NÃO são ação do dono hoje:** o endereço
  temporário do Worker de staging e o Environment protegido no site. São a
  **mesma autoridade** (`Workers Scripts: Edit` de conta, que alcança o Worker
  de produção), e **nenhum bullet das Fases 3, 4 e 5 depende deles**.
  `tests/test_handoff_prompt_method.py` falha se voltarem para a lista do dono.
- **A PR draft `#21` do site** (parar de commitar os alertas) **não deve ser
  mesclada** antes da Phase 6.
- **A chuva do site está pulando por rede** — não é o token e não é o nosso
  código. Primeiro dia vermelho: **22 de setembro de 2026**; qualquer rodada
  bem-sucedida zera o contador.
- **Pendência com data: o token da NASA expira em 2026-11-06**, e essa falha
  aparece vermelha no download.
- **Mesmo padrão suspeito no fallback do backend**, sem prazo: o passo "Run
  detection pipeline" do `update_data.yml` passa usuário e senha do Earthdata e
  não foi verificado se `run_detection.py` chega a fazer login. Pode ser que a
  correção certa seja **remover** as duas linhas.
- **Nenhum workflow deste repositório roda a suite Python** — CI completo é
  Phase 7. As suites rodam localmente, e é por isso que um teste que cai pelo
  motivo errado passa desapercebido até a próxima sessão.

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

**Uma coisa, e ela é sua: escolher contra qual referência o ano de 2026 vai ser
recalculado.** Tudo o mais que essa etapa prometia está entregue.

Existem duas referências possíveis. A antiga é a que o sistema usa hoje. A nova
foi construída no trabalho científico das etapas anteriores e é melhor por um
motivo concreto: ela guarda de onde veio cada imagem que a formou, e a etapa
seguinte exige exatamente isso para poder conferir o próprio trabalho. A antiga
não guarda.

As duas cobrem a mesma área, na mesma resolução, com os mesmos arquivos — a
troca não é uma reforma, é uma troca. Mas elas não têm **nenhuma** imagem em
comum, então o resultado muda.

**O que a nova custa, e é honesto dizer:** de janeiro a abril ela usa imagens
que a agência espacial europeia ainda está reprocessando. Quando esse
reprocessamento chegar a esses meses, esses quatro meses provavelmente terão de
ser recalculados de novo. A recomendação técnica continua sendo a nova, porque a
etapa seguinte também podia forçar um recálculo de qualquer forma e porque o
custo de máquina não é o gargalo.

Também ficou preparado — e não decidido — um segundo ponto técnico sobre como
agrupar as imagens de cada dia. Ele não precisa de você; a próxima sessão decide
com o que está medido.

### O que você precisa fazer

1. **Decidir qual referência o recálculo usa** — a antiga ou a nova. É a única
   coisa que trava o próximo passo. Se preferir, responda só "a nova": é a
   recomendação, e o custo dela está descrito acima.
2. **Ler e aprovar o roteiro do recálculo**, quando tiver um momento. Ele está
   no repositório do monitoramento como um documento com uma lista de itens para
   marcar, e o primeiro item é a decisão acima. Sem essa aprovação a troca final
   não começa — mas o recálculo pode começar só com a decisão da referência.
3. **Mesclar duas propostas, quando quiser** — uma no repositório do
   monitoramento e uma no do site. As duas são texto, teste e documento; não
   mudam nada do que está publicado.
4. **Não mesclar ainda** a proposta que tira os arquivos grandes do site. Ela
   entra na troca final.
5. **Abrir a página de cota do Google Earth Engine** do projeto que roda a
   detecção e anotar duas linhas: o limite do mês e quanto já foi usado. Pode
   esperar — o recálculo cabe com folga pelas contas que temos.
6. **Anotar 6 de novembro:** a chave da NASA expira e o mapa de chuva para de
   novo. Essa falha é vermelha, não silenciosa.

### Tem algo preocupante?

**Nada quebrado.** Produção não foi tocada, o site publicado continua igual,
nada foi apagado, e nenhuma senha ou chave foi usada em lugar nenhum.

Três coisas que vale saber, e nenhuma é alarme:

**A primeira é a decisão da referência**, e é por isso que ela está no topo. Se
a referência errada for congelada, o resultado não fica obviamente errado —
fica plausível, e comparado contra a coisa errada. Foi para dar tempo a essa
decisão que a etapa que acabou existiu.

**A segunda é uma conta que eu corrigi.** O documento de insumos que o senhor
pediu antes desta etapa estimou o custo de máquina partindo de um número que
mudou meses atrás. Refazendo a conta com o número certo, o recálculo custa cerca
de três vezes mais do que aquele documento dizia. **A conclusão não muda: cabe
com folga.** O que não vale mais é a frase de que caberia mesmo se a conta
estivesse dez vezes errada. Está registrado, e o número certo agora é lido do
próprio sistema por um teste, para a próxima conta não repetir o erro.

**A terceira é um teste do site que ia quebrar sozinho.** Ele afirmava que o
site tem exatamente 40 dias de alerta publicados. Na próxima publicação
bem-sucedida ele passaria a ter 41 e o teste falharia — um teste que acusa
problema quando nada está errado deixa de ser lido. Está consertado na proposta
do site, sem afrouxar nenhuma verificação de verdade.

### O que ainda falta no caminho

- **Reprocessar 2026 inteiro** num candidato guardado, sem publicar. É a próxima
  etapa, e a caríssima em tempo de máquina. Ela começa com a decisão da
  referência.
- **A validação científica** — a etapa que o senhor pediu para não travar nada, e
  que agora tem portão: ela não começa sem a sua revisão, porque o objetivo
  passou a ser uma publicação.
- **Uma etapa própria para a memória de publicações**, que é o que permitirá um
  dia apagar versões antigas com segurança — e que a publicação transformou de
  prudência em requisito.
- **A troca final:** o novo substitui o antigo, a página passa a ler pelo
  caminho novo, o robô antigo é desligado, o endereço público antigo é fechado, e
  a publicação passa a acontecer sozinha num horário. É aqui que os dois
  pré-requisitos guardados se pagam.
- **O endurecimento:** ligar as verificações automáticas nos dois repositórios
  (hoje elas só rodam na minha máquina), proteção de branch, acessibilidade e as
  ferramentas reusáveis.
