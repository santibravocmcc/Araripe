# Phase 4 — reprocessar 2026 inteiro num candidato guardado

Escrito em 2026-09-08, ao fechar a Phase 3. Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é para
o agente executor e a **seção final é para o dono**.

**A Phase 3 fechou o seu gate, e a decisão do dono está tomada.** As duas
ativações de runtime entraram, as versões estão congeladas com pin medido, a
fotografia está tirada, a fila está registrada, o ensaio limitado rodou, **a
baseline do replay está decidida** e **a cota está medida**. Nada bloqueia esta
fase.

**Esta é a fase caríssima em tempo de máquina.** A Phase 3 existiu para que ela
rode **uma** vez.

---

## 0. A decisão que precedia tudo — TOMADA

**A baseline do replay é a `2.1.0`.** Decidida pelo dono em **2026-09-09**:
perguntado *"qual referência o recálculo usa — a antiga ou a nova"*, respondeu
**"a nova"**, seguindo a recomendação com o custo declarado.

Registrada em `config/phase3_replay_baseline_decision_v1.json` com autorização
datada. O congelamento **lê** a decisão dali — `build_freeze` valida que a
versão nomeada é uma geração **registrada** e que a autorização existe, então
um erro de digitação ou a `2.0.0` superada falham fechado. Confirme com:

    /opt/anaconda3/envs/araripe/bin/python -c "from src.replay import freeze; \
      print(freeze.load_freeze()['baseline']['replay_generation'])"

**Não redecida.** E não mova o default do azul: `BASELINE_VERSION` em
`config/settings.py` continua `1.0.0`, o arquivo de decisão declara
`blue_default_change_permitted: false`, e
`test_decidir_o_replay_nao_move_o_default_do_azul` exige que os dois valores
continuem diferentes e ambos gravados. O replay nomeia
`--baseline-version 2.1.0`.

**O custo que veio com a decisão, e que a Phase 4 herda:** a `2.1.0` admite
produtos pré-Collection-1 nos meses 1-4, que a ESA está reprocessando. **Um
replay contra ela pode ter de ser refeito para janeiro-abril.** Vigilância em
`scripts/check_esa_reprocessing.py`. Não é motivo para hesitar — é motivo para
que o registro da execução diga contra qual regime sazonal cada mês foi
composto, para que refazer quatro meses seja possível sem refazer doze.

**A revisão do runbook (§7 dele) é PRÉ-CUTOVER**, ou seja portão da Phase 6.
Dois itens fecharam (a baseline e a cota) e quatro continuam abertos. **Ela não
bloqueia esta fase.**

## 1. Dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:ROADMAP.md | sed -n '/^### Phase 4 —/,/^### Phase 5 —/p'
    git show origin/main:docs/implementation/PHASE_3_2026-09-08.md

Medido com a Phase 3 já mesclada. `origin/main` do backend em
`baea4f7326caca198f61a2a640909010b0070111`, `origin/main` do site em `5304a81`:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **1723** na `main`, **1738** com a PR da decisão |
| site | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **203** na `main` |
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

**f. MEDIDO — a cota está fechada, e o X não é mais um X.** O dono abriu as duas
páginas em 2026-09-09. `ee-araripe` (o projeto da detecção e do replay): limite
**3.600.000** EECU-s/mês, uso **6.242** = **0,17%**. Diário ilimitado.

Medido de `gh run list`: esses 6.242 vêm de **duas** execuções completas
(2026-09-03 e o dispatch de 2026-09-07); a execução agendada que falhou em
07/09 parou em *"Fetch persistence state from R2"*, **antes** do passo de GEE,
e gastou zero. Logo **3.121 EECU-s por execução**, e com 8 execuções/mês
**X = 24.968 EECU-s/mês = 0,69%** da alocação.

A janela é de **seis** dias e a cadência seg/qui, então cada data cai em **1,71**
janelas em média; o replay processa cada data uma vez, logo custa **1/1,71** do
que a operação gastou no mesmo intervalo:

| | EECU-s | % de um mês |
| --- | --- | --- |
| uma passagem (242 dias) | ~115.800 | **3,2%** |
| duas passagens | ~231.600 | 6,4% |
| uma passagem com erro de 10× | ~1.157.900 | 32% — **ainda cabe** |

Confirmação independente: é **0,94×** o custo da reconstrução da baseline v2
(122.783 EECU-s), um trabalho real já pago de escala comparável.

**Duas correções, e a segunda foi minha:** a §1 dos insumos usou janela 16 (era
5); a correção de 08/09 acertou a janela mas usou o consumo do projeto da
**baseline** como proxy do da detecção, e o proxy era **4,9× alto**. A frase
*"mesmo com erro de 10× continua caber num mês"* que aquela correção declarou
morta **volta a valer**. Aritmética inteira em
`docs/operations/PHASE_3_INPUTS_2026-09-08.md` §3. **Não refaça a análise.**

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

1. **Confirmar a decisão da baseline** (§0) lendo o congelamento — não
   redecidir. E confirmar que `pytest -q tests/test_replay_freeze.py` passa
   antes de gastar compute.
2. **Decidir a unidade de composição** (§2d) por escrito, com a base. É agora a
   decisão mais consequente da fase, e a divergência já está medida.
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
  (`#56`, merge commit — os 5 commits preservados) e a decisão da baseline
  **tomada** em 2026-09-09.
- **`ROADMAP.md` na `main` é o plano** desde 2026-09-08.
- **As duas PRs da Phase 3 foram mescladas** em 2026-09-09: backend `#56`
  (merge commit) e site `#25` (squash). Confirmado por conteúdo, não por
  ancestralidade.
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

**Nada.** A etapa de congelar e ensaiar fechou, o senhor escolheu a referência
nova, mediu a cota, e as duas propostas foram mescladas. O recálculo do ano
inteiro pode começar quando o senhor quiser abrir a próxima sessão.

Duas coisas ficaram **preparadas e não decididas**, e nenhuma precisa do senhor:

1. **Como agrupar as imagens de cada dia.** O satélite pode passar duas vezes
   sobre a área no mesmo dia, e as duas metades do sistema hoje contam isso de
   maneiras diferentes. Está medido e escrito; a próxima sessão decide.
2. **Se o recálculo deve alinhar a grade das imagens à da referência.** Hoje ele
   não alinha e compensa depois. Alinhar seria melhor, mas muda os pixels
   exportados, então é decisão da etapa que exporta.

### O que você precisa fazer

1. **Nada urgente.** Quando quiser, abra a próxima sessão para o recálculo — o
   texto acima já diz ao assistente tudo o que ele precisa.
2. **Anotar 6 de novembro:** a chave da NASA expira e o mapa de chuva para de
   novo. Essa falha é vermelha, não silenciosa, e é a única data no calendário.
3. **Guardar uma expectativa sobre o recálculo:** de janeiro a abril ele usa
   imagens que a agência espacial europeia ainda está reprocessando, então esses
   quatro meses provavelmente serão refeitos uma segunda vez mais adiante. Isso
   já estava no preço quando o senhor escolheu a referência nova, e o custo de
   máquina não é o gargalo — uma passagem inteira usa cerca de 3% da cota de um
   mês.

### Tem algo preocupante?

**Não.** Produção não foi tocada, o site publicado continua igual, nada foi
apagado, e nenhuma senha ou chave foi usada.

Uma correção que vale registrar, porque é de um número que eu mesmo publiquei
errado: na entrega anterior eu disse que o recálculo custaria cerca de 19% da
cota de um mês. Com a medição que o senhor trouxe, o número real é **cerca de
3%**. O erro foi meu e tinha uma causa concreta — eu não tinha o consumo do
projeto da detecção, então usei o consumo do projeto da referência como
substituto, e ele é quase cinco vezes maior. Agora o número vem da medição, e
há uma conferência independente: o recálculo custa aproximadamente o mesmo que a
construção da referência nova, que já foi paga e correu sem problema.

### O que ainda falta no caminho

- **Reprocessar 2026 inteiro** num candidato guardado, sem publicar — a próxima
  etapa, e a caríssima em tempo de máquina. Está desbloqueada.
- **A validação científica** — a etapa que o senhor pediu para não travar nada, e
  que agora tem portão: ela não começa sem a sua revisão, porque o objetivo
  passou a ser uma publicação.
- **Uma etapa própria para a memória de publicações**, que é o que permitirá um
  dia apagar versões antigas com segurança — e que a publicação transformou de
  prudência em requisito.
- **A troca final:** o novo substitui o antigo, a página passa a ler pelo
  caminho novo, o robô antigo é desligado, o endereço público antigo é fechado, e
  a publicação passa a acontecer sozinha num horário. **É aqui que a sua revisão
  do roteiro é obrigatória** — ela é portão desta etapa, não do recálculo.
- **O endurecimento:** ligar as verificações automáticas nos dois repositórios
  (hoje elas só rodam na minha máquina), proteção de branch, acessibilidade e as
  ferramentas reusáveis.
