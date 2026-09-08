# Levar o Package 2A.6 para a `main` — o portão da Phase 3

Escrito em 2026-09-08, ao fechar o **exit gate P2B** e com ele a **Phase 2B**.
Não há mais package na Phase 2B, e o gate está fechado — o registro é
[`../implementation/PHASE_2B_GATE_2026-09-08.md`](../implementation/PHASE_2B_GATE_2026-09-08.md).

O roadmap decide qual é a próxima frente, e não é ambíguo:

> *"Package 2A.6 may run in parallel with Phase 2B, but **must close before
> Phase 3**."*

O Package 2A.6 está **implementado e fechado**, e **não está na `main`**. Ele é
a pré-condição da Phase 3. Esta é a tarefa.

Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

---

## 1. A dependência que precede tudo — e a armadilha que ela esconde

Confirme por conteúdo, nunca por ancestralidade. Os dois repositórios fazem
squash-merge, então `git log origin/main..origin/<branch>` lista commits cujo
conteúdo já está na `main`. Filtre por `%s`:
`git log origin/main --format='%H %s' | grep '(#<número>)'`.

    git fetch origin
    git rev-parse origin/main
    git rev-parse origin/claude/phase2a6d-mapbiomas

Medido em 2026-09-08, com a `main` em
`cd2820a41a0c03325757dbd452df8f363990908e` e a branch em
`64fd781f1551a45914a7db32960b923c05056955`:

| medida | valor |
| --- | --- |
| commits na `main` que a branch não tem | **44** |
| commits na branch que a `main` não tem | 34 |
| merge base | `adf570f05d8240b1a1993630fcb60be280cd2710` |
| arquivos que a branch **acrescenta** | 221 |
| arquivos que a `main` tem e **a branch não** | **93** |

### O que um merge ingênuo apagaria — medido, não temido

Os 93 arquivos ausentes na branch são **a Phase 2B inteira**:

| quantos | o quê |
| --- | --- |
| 13 | `src/publication/` — todos: `atomic_publish`, `conditional_store`, `green_release`, `ledger_gate`, `ledger_binding`, `run_assembler`, `run_inputs`, `site_artifact`, `retention`, `delivery_boundary`, `canonical_json`, `findings`, `__init__` |
| 5 | `.github/workflows/` verdes — inclusive `cloudflare_green_control.yml`, o broker protegido |
| 11 | `docs/contracts/phase2b/` |
| 24 | `tests/` — inclusive `test_workflow_lanes.py` |
| 20 | `docs/operations/` |
| 10 | `scripts/` |
| 7 | `docs/implementation/` |
| 3 | outros |

**Portanto: isto não é um merge.** É reaplicar 2A.6 sobre a `main` atual. Um
`git merge` ou um PR com a branch como está entregaria um diff de
`346 files changed, 183401 insertions(+), 30702 deletions(-)` cujo lado das
deleções é o trabalho de cinco packages. É exatamente a armadilha que o
`AGENTS.md` do workspace nomeia: *"Before building on a branch, check how far
behind `origin/main` it is and what its diff would delete."*

**Confirme os dois números antes de escrever uma linha**, e se o merge base
mudou, refaça a medição em vez de confiar nesta tabela.

Gates medidos na `main` em 2026-09-08, **depois** da `#52`:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **843 passed** |
| site | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **201 passed** |
| site | `npm ci && npm run test:worker` | **44 tests, 44 pass** |

A branch 2A.6 tem **842 testes** *no seu próprio conjunto* — registrado ao
fechar o package, **não medido nesta sessão**. Meça antes de usar como base: os
dois números não são comparáveis, porque as duas árvores têm arquivos de teste
diferentes.

**Use `npm run test:worker`, não `node --test tests/`.** Nesta máquina o Node é
v25, e `node --test tests/` tenta *carregar* `tests/` como módulo e morre com
`MODULE_NOT_FOUND` — um fracasso que parece do repositório e é da invocação.

## 2. O que já foi verificado, para o executor não refazer

**a. O produtor de ledger v3 do 2A.6 funciona e a `main` o aceita — MEDIDO.**
`src/detection/ledger_v3.py` da branch foi **conduzido** em 2026-09-08:
`ProcessingLedgerV3` reconstruído das aquisições do exemplo commitado devolve o
mesmo `ledger_id` e um documento **igual campo a campo**, com o mesmo
`integrity.document_sha256`
(`ca6605a4a7994119f694297001d4de880b57118a4d8c22b8740bb32891f8f573`). Os bytes
diferem só na forma — `to_bytes()` é canônico compacto, o exemplo é `indent=2`
— o que a não-exigência 4 do binding permite. E ledgers que ele emitiu para
datas reais passaram por `check_processing_ledger`, `build_release`,
`check_green_release`, `verify_release` e `promote` da `main` sem adaptar nada.
**A integração de contrato entre 2A.6 e Phase 2B está provada.** Não a refaça;
o que falta é outra coisa — ver §3.

**b. O exemplo e o schema do ledger são byte-idênticos nas duas branches.**
`processing-ledger-v3.example.json` sha256
`fd2db1efd8ac79563f498677bb9c8eccf9f32e8e177958e196a8f1e4353a2e87`; schema
`fde07d7b03b5caf43c01c7a4ee1ab0c0d4f60d2bd71151129ada872cda5f2ad0`. Então essa
parte do merge é um no-op e não precisa de revisão.

**c. VERIFICADO QUE NÃO É O CASO: nenhum produtor na `main` escreve um ledger
v3.** Varrido `scripts/` e `src/` da `main`. `run_detection.py` e
`run_detection_gee.py` **não** chamam o produtor — nem poderiam, porque ele não
está lá. É isto que faz o depósito de rodada verde depender de um ledger
fornecido à mão hoje.

**d. VERIFICADO QUE NÃO É O CASO: nenhum workflow verde roda detecção.**
`v2_candidate_replay.yml` é a sonda de isolamento e `v2_operational_publish.yml`
começa **depois** do depósito. O único produtor dos insumos de
`scripts/assemble_green_run.py` é `detect_gee.yml`, que é **azul e congelado**
nas Fases 2B–5. Ligar o depósito a uma execução automática é Phase 6.

**e. O ponto de entrada de rodada verde existe e está provado.**
`scripts/assemble_green_run.py` (`#52`), lane 2, `plan`/`apply`. Não reescreva,
e não reescreva `src/publication/run_assembler.py`.

**f. MEDIDO: os arquivos de alerta publicados do site NÃO são entrada válida
para o caminho verde.** Eles têm os nomes curtos de `prepare_data.py` (`conf`,
`nat10`, `pcount`) e não têm `confidence_label`, `persistence_count` nem
`lc_natural_frac_10m` — que é o que `is_strong` lê. Alimentar o montador com
eles dá subconjunto forte **vazio, em silêncio**. O dado do produtor está em
`alerts/alerts_<data>.geojson` no mesmo bucket público
(`https://pub-5eb389cffff54421916187be69dd659b.r2.dev/`), e é lá que estão os
nomes longos. **Sem credencial nenhuma** — é leitura HTTP pública.

**g. MEDIDO: o caminho verde reproduz os números da produção.** Compondo o
índice do site a partir de uma release real, **18 de 18 campos estatísticos**
batem com o `manifest.json` de produção em duas datas reais, por um caminho de
código inteiramente diferente. 21 383 feições reais.

**h. MEDIDO: o prefixo de rodada não é à prova de acréscimo.** Uma rodada em
conflito acrescenta chaves antes de colidir no `ledger.json`, e
`plan_retention.py` classifica as órfãs como `retain`, igual às legítimas. A
release não muda (é o `run.json` que declara, e ele vai por último). Insumo
para o package de retenção.

**i. O repositório do site não tem Environment nenhum** (`total_count: 0`).
**Não nomeie um que não existe** — o GitHub cria, sem proteção e sem política de
branch.

**j. O Worker verde de staging continua sem hostname**, então `--from-route`
nunca correu contra HTTP de verdade.

**k. MEDIDO: remover a re-inclusão do `.gitignore` QUEBRA o azul.** Está na
branch `claude/phase2b4b-stop-committing-alerts` e na PR draft `#21` do site.
**Não mescle** antes de a página ler pela rota (Phase 6).

## 3. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: reaplicar 34 commits de ciência sobre uma `main` que ganhou cinco
> packages de publicação, sem apagar nenhum dos dois lados. O risco não é
> escrever código — é **perder trabalho já feito num diff grande demais para a
> revisão pegar**. A medição do §1 é o argumento: um merge ingênuo apaga 93
> arquivos, e 13 deles são o `src/publication/` inteiro.

Levar o **Package 2A.6** para a `main`, preservando a Phase 2B inteira, e
deixar a Phase 3 desbloqueada.

**Orientação obrigatória antes de qualquer conclusão.** Siga "Establishing the
real state" do `AGENTS.md` do workspace nos **dois** repositórios. Leia
canônico com `git show origin/main:<path>`. Cole o SHA de 40 caracteres da base
lido de `git rev-parse origin/main`. Ative o hook com
`git config core.hooksPath .githooks` nos dois — ele recusa qualquer SHA de 40
caracteres que não exista *naquele* repositório, inclusive o SHA legítimo do
outro repositório do workspace. Para citar o SHA do site, use a forma curta.

**Base.** Uma branch nova a partir de `origin/main`, **nunca** a
`claude/phase2a6d-mapbiomas` como está.

### Escopo

1. **Decidir e registrar a estratégia de landing, com a medição na mão.** As
   opções plausíveis são rebase da branch sobre `origin/main`, ou uma série de
   PRs por fatia temática (contratos → identidade/ledger → persistência →
   máscara/composição → MapBiomas → validação). Escolha por evidência —
   quantos conflitos, quantos arquivos por fatia, o que a revisão consegue ler
   — e escreva o porquê. **A `main` é pull-request-only**, então a entrega é
   sempre PR.
2. **Provar que nada da Phase 2B se perde.** A prova tem de ser mecânica, não
   um argumento: os 93 arquivos continuam presentes, `src/publication/` tem os
   13 módulos, os 5 workflows verdes existem, e o conjunto de testes da `main`
   continua passando ao lado do da branch. Um teste que compare inventários é
   melhor que uma inspeção.
3. **Fechar a metade que falta da integração 2A.6 ↔ Phase 2B**: fazer o
   caminho de detecção **emitir** o ledger v3 que o depósito de rodada
   consome. Hoje o ledger é fornecido à mão porque nenhum produtor na `main`
   escreve um (§2c). É isto que transforma "os documentos se encaixam" em "uma
   execução produz o documento".
4. **Registrar** o landing e o estado do exit gate P2A em
   `docs/implementation/`.

**Fora de escopo, explicitamente:** o cutover, o desligamento do bot azul,
ligar a página a `object_base` e qualquer coisa no domínio final são **Phase
6**. O replay de 2026 é a **Phase 3** — este package a desbloqueia e não a
começa. A validação qualificada é **Phase 5**, e ela tem portão de revisão do
dono. O histórico de promoção e qualquer exclusão real são packages próprios.
Reescrever a história do git para recuperar os 247 MiB não é deste package.

**Não inicie a Phase 3, a Phase 4, a Phase 5, a Phase 6 nem a Phase 7.**

## 4. Decisões de escopo já tomadas, com sua base

- **Nenhum segundo produtor de ledger.** O montador da rodada **usa** o ledger
  que a detecção produz. O item 3 do escopo é fazer a detecção produzi-lo, não
  criar um segundo produtor.
- **A política de exposição e a das estatísticas são do backend**; o Worker e o
  compositor do site são adaptadores, e os 31 vetores são a referência.
- **O índice do site é derivado, não selado** — o prefixo da release é função
  do ledger só.
- **A rota verde é aditiva em `/data/green/`**; o `/data/…` estático fica
  intocado, e mantê-lo é o rollback.
- **Nada é apagado.** Nem no R2 nem na história do git.
- **Nenhuma lane verde carrega cron antes da Phase 6.**
- **v1 é audit-only** e não recebe dado v2 serializado.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- A `main` do backend é **pull-request-only**, bypass vazio. Branch, PR, **sem
  merge** sem revisão.
- **A `main` do site faz deploy de produção.** Prove o que muda pelo fecho dos
  imports e pelo conteúdo de `dist/`.
- Produção congelada nas Fases 2B–5.
- **Exclusão de objeto real exige aprovação humana explícita e nomeada.**
- Claude não recebe credencial de control-plane da Cloudflare; o único caminho
  é uma operação já allowlistada no broker protegido
  `.github/workflows/cloudflare_green_control.yml`.
- **Nunca nomeie um Environment que não existe.**
- Preserve `claude/phase2b0-green-isolation`, `codex/technical-review-roadmap`,
  `claude/phase2a6d-mapbiomas`, `ci/promotion-identity-probe`,
  `claude/phase2b3-r2-separation`, as branches do 2B.4A, as **duas** do 2B.4B e
  `claude/phase2b-gate`.

## 6. Armadilhas já pagas — não redescobrir

- **Uma branch não é uma entrada de backlog.** Ver §1: 44 commits atrás, 93
  arquivos apagados por um merge ingênuo.
- **Outra sessão pode estar no mesmo clone.** Existe um `stash@{0}` de outra
  sessão no backend. **Nunca `git stash` em árvore alheia**; adicione por nome
  e confira `git status` antes de todo checkout.
- **`config/settings.py` carrega o `.env` de PRODUÇÃO no import** (linhas
  13-18). Nenhum script verde pode importá-lo, e
  `test_nenhum_script_verde_importa_o_carregador_de_dotenv` afirma isso por
  `ast`. Se o item 3 do escopo fizer a detecção emitir o ledger, atenção: o
  caminho de detecção **é** azul e importa `config.settings` — o produtor de
  ledger não pode virar uma ponte que traga essa importação para o lane verde.
- **O hook `commit-msg` recusa SHA estrangeiro.** Ver §3.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca dispare para testar.
- **ETag não é checksum** — multipart é MD5 dos MD5s com sufixo `-N`.
- **Não confie em invariante que o produtor não promete.** Aconteceu de novo em
  2026-09-08: uma checagem que exigia que todo arquivo no diretório de alertas
  fosse da rodada corrente **recusou a rodada real**, porque
  `fetch_alerts_from_r2.py` sem `--latest` baixa o arquivo inteiro para o mesmo
  diretório. Medido, e revertido para "ignorar e reportar".
- **Um teste pode passar pelo motivo errado.** Pergunte sempre **qual mutação o
  teste derruba** — e derrube-a de verdade. Use `ast` para import, e
  `executable_lines()` para shell e YAML: uma varredura textual acusa a
  docstring que explica a proibição.
- **`grep` desta máquina é `ugrep`**: `grep -qv` retorna 1 mesmo com linhas
  selecionadas. Capture a saída e teste se está vazia.
- **`cd` composto no shell das ferramentas pode não pegar.** Use caminho
  absoluto em cada comando.
- **Confira `gh pr list --head <branch>` depois de cada push** — em 2026-09-08
  oito commits ficaram órfãos por não conferir.
- **`ee.Initialize()` ignora `GOOGLE_APPLICATION_CREDENTIALS`.** Não "corrija"
  os scripts locais.

## 7. Ao final

Testes fail-closed e determinísticos: sem rede, sem relógio real, sem object
store, sem credencial. Rode
`/opt/anaconda3/envs/araripe/bin/python -m pytest -q` no backend e
`npm ci && npm run build && npm test && npm run test:worker` no site; reporte
falhas pré-existentes em separado, e confira ao fim que nenhum `workerd`
sobrou (`pgrep -fl workerd`). Commits por repositório, **nunca misturados**,
com base verificada. Crie `docs/implementation/PHASE_2A6_LANDING_<data>.md`.
Confirme árvore limpa — os untracked `data/baselines_v2/`,
`data/landcover/updated/` e `data/validation/` ficam **fora**. Abra as PRs
**sem mesclar**. Termine com o estado do exit gate P2A e com a seção final
obrigatória do método de handoff.

## 8. Estado que este package herda

- **A Phase 2B está fechada.** O exit gate P2B foi provado em 2026-09-08 contra
  o R2 real com dado de execução real: rodadas depositadas, release publicada e
  verificada, ponteiro movido e revertido, rodada falhada e rodada concorrente
  recusadas. Registro em `docs/implementation/PHASE_2B_GATE_2026-09-08.md` §8.
- **PR `#52` aberta e não mesclada** — o ponto de entrada de rodada verde, 31
  testes, e o registro do gate. Nada nela toca produção.
- **O ponteiro verde de staging está na sequência 9**, `action: rollback`,
  apontando para uma release de dado real (cobertura até 2026-08-25). O
  ponteiro guarda **um passo** de história; o estado anterior está registrado
  no documento do gate, §4.3.
- **`araripe-v2-staging` tem 62 objetos**, incluindo quatro rodadas e cinco
  releases. `plan_retention.py` diz `eligible 0` — nada é elegível a exclusão, e
  nenhum caminho de código neste repositório consegue apagar.
- **O ponteiro verde não tem história durável**, e a Phase 5 tornou isso
  requisito: um artigo cita **uma** release, e ela passa a ter de existir para
  sempre.
- **Package 2B.4B entregue**; a PR draft `#21` do site (parar de commitar os
  alertas) **não deve ser mesclada** antes da Phase 6.
- **Environments do backend:** `cloudflare-green-control` (com revisor),
  `v2-staging` e `v2-promotion` (sem revisor, política `main`). **O
  repositório do site não tem Environment nenhum.**
- **A chuva do site está pulando por rede** — não é o token e não é o nosso
  código. Três tentativas automáticas antes do primeiro dia vermelho, que é
  **22 de setembro de 2026**; qualquer rodada bem-sucedida zera o contador.
  **Sexta 2026-09-11 não fica vermelha** — quem afirmar isso está lendo uma
  nota velha.
- **Pendência com data: o token da NASA expira em 2026-11-06**, e essa falha
  aparece vermelha no download, não como congelamento silencioso.
- **Mesmo padrão suspeito no fallback do backend**, sem prazo: o passo "Run
  detection pipeline" do `update_data.yml` passa usuário e senha do Earthdata e
  não foi verificado se `run_detection.py` chega a fazer login. Pode ser que a
  correção certa seja **remover** as duas linhas.

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

**Nada — a etapa foi entregue inteira, e a fase inteira fechou com ela.**

O que faltava era ligar a peça que monta uma publicação a uma execução de
verdade, em vez de a um exemplo montado à mão. Isso está feito, e foi provado
com dado real: três execuções reais de monitoramento (mais de vinte mil alertas
de agosto), o arquivo de memória do sistema com cento e dezenove mil trilhas, e
a publicação de teste feita, verificada, promovida e depois revertida — no
armazenamento de verdade, sem tocar em nada de produção.

Duas coisas que valem saber, e nenhuma é pendência desta etapa:

A prova mais convincente foi comparar. O caminho novo calculou os números que a
página de alertas mostra e eles bateram **exatamente** com os que o site já
publica — dezoito números conferidos, dois dias, zero diferenças — por um
caminho de cálculo completamente diferente. Quando dois caminhos independentes
chegam ao mesmo número em dado real, é a melhor evidência que existe de que a
regra está certa.

E encontrei um defeito meu, no meio do caminho. Eu tinha escrito uma checagem
que exigia que todo arquivo de alerta na pasta pertencesse à execução atual.
Parecia prudente. Só que a pasta funciona como **arquivo histórico** quando se
roda localmente, então a checagem recusou a execução real na primeira tentativa.
Era o mesmo tipo de erro que derrubou a produção em setembro: exigir uma
garantia que ninguém prometeu. Troquei por "ignorar e avisar quantas foram
ignoradas", que é honesto e não quebra nada.

### O que você precisa fazer

1. **Não mesclar ainda a proposta que tira os arquivos grandes** (a `#21` do
   site). Aplicá-la hoje quebra a aba de alertas. Ela entra na etapa da troca
   final.
2. **Anotar 6 de novembro:** a chave da NASA expira e o mapa de chuva para de
   novo. Essa falha é vermelha, não silenciosa.

**É isso — a lista tem dois itens, e nenhum dos dois é urgente.** A `#52` já
está mesclada (`53eb411`).

#### Dois itens saíram desta lista, e não devem voltar

O endereço temporário do servidor de teste e o Environment protegido no
repositório do site apareceram como "ação do dono" em **quatro** briefings
seguidos (2B.4, 2B.4B, o gate P2B e a primeira versão deste), e em nenhum deles
eram ação a tomar. **São pré-requisitos da Phase 6**, registrados na §0-bis
abaixo com a medição que sustenta isso. Não os re-liste aqui.

Sobre a chuva: continua pulando por problema de rede entre o robô do GitHub e o
servidor da NASA, e o sistema está fazendo o que foi desenhado para fazer. Há
três tentativas automáticas antes do primeiro dia vermelho, que é **22 de
setembro**. Não é preciso fazer nada.

### Tem algo preocupante?

**Não.** Nada quebrou, produção não foi tocada, o site publicado continua
exatamente igual, e nada foi apagado em lugar nenhum.

Vale registrar uma coisa para a etapa seguinte, e ela é um cuidado, não um
alarme: **a próxima etapa mexe com uma pasta de trabalho que ficou parada por
um mês enquanto o resto avançava.** Medi o que aconteceria se alguém a juntasse
sem cuidado: apagaria noventa e três arquivos, e treze deles são o coração de
todo o trabalho de publicação das últimas semanas. Ninguém vai fazer isso por
acidente agora que está medido e escrito — é justamente por isso que medi. Mas
é a razão pela qual a próxima etapa pede atenção e não pressa.

#### §0-bis — os dois itens da Phase 6, e por que não são decisão de hoje

Medido em 2026-09-08, para o caso de a pergunta voltar.

**São a mesma autoridade, não dois assuntos.** Os dois exigem
`Workers Scripts: Edit` **em nível de conta**, e quem tem essa permissão
implanta o Worker de produção `observatorio-chapada`. O endereço precisa dela
para ligar o subdomínio; o Environment do site existe justamente para guardar
um token que a tenha. Decidir um é decidir o outro.

**Nada entre hoje e a Phase 6 depende de nenhum dos dois.** Varredura dos
bullets das Phases 3, 4 e 5 no roadmap canônico
(`git show claude/phase2a6d-mapbiomas:ROADMAP.md`): nenhuma menção a Worker,
rota, hostname, deploy, domínio ou Environment. A única ocorrência de
"environment" naquele trecho é *"schema, environment, and release versions"*,
que é versão de ambiente de software. Os dois aparecem na Phase 6, no bullet
*"Verify the main domain, same-origin data route, CORS, full/strong modes"*.

**O endereço desfaz, à mão, o que o broker existe para impor.** A auditoria
afirma fail-closed `subdomain == {"enabled": false, "previews_enabled": false}`,
e a lista de operações do broker é exatamente
`audit`, `enforce-worker-isolation`, `disable-site-branch-deploy` — **não existe
operação para ligar subdomínio**, e uma delas existe para desligá-lo. Dar
endereço ao Worker de staging exigiria uma operação nova revisada ou um token
direto, e deixaria a auditoria de isolação vermelha enquanto durasse.

**O que o endereço fecharia está nomeado e é pequeno:** `--from-route` nunca
correu contra HTTP de verdade (`PHASE_2B_GATE_2026-09-08.md` §7). A checagem
cruzada de 18 campos do §4.1 foi feita por `--from-dir` sobre a release real, e
o degrau 1 do
[`GREEN_ROUTE_VERIFICATION_LADDER.md`](GREEN_ROUTE_VERIFICATION_LADDER.md)
verifica o comportamento do Worker inteiro em 29 checagens HTTP, com `wrangler
dev` local e **zero credencial**. O que falta é só afirmar que a borda da
Cloudflare não mexe nos headers — e isso só importa quando o site público
apontar para a rota, que é o cutover.

**A recomendação registrada, e ela não mudou:** degrau 2 **pular**, degrau 3
**Phase 6** (tabela no fim daquele documento). Se um token de deploy verde
existir algum dia — e a Phase 6 precisa de um —, os dois degraus saem de graça
junto. Até lá, pagar autoridade de conta compra uma afirmação que ninguém
precisa ainda.

### O que ainda falta no caminho

- **Trazer o trabalho científico para o tronco principal** — é a próxima etapa,
  e é o portão da seguinte. O que ela também resolve: hoje o sistema sabe
  publicar uma execução, mas o documento de auditoria que acompanha cada
  publicação ainda é preparado à mão, porque a parte que o gera está naquela
  pasta parada.
- **A verificação no navegador** — na Phase 6, junto com o cutover, não antes.
  Ver a §0-bis: não é uma decisão pendente do dono.
- **Uma etapa própria para a memória de publicações**, que é o que permitirá um
  dia apagar versões antigas com segurança — e que a publicação científica
  transformou de prudência em requisito.
- **Congelar e ensaiar o reprocessamento de 2026** — a etapa depois da próxima.
- **Reprocessar o ano inteiro** e depois **validar o resultado**, que é onde
  entra a revisão científica que você pediu para segurar.
- **A troca final:** o novo substitui o antigo, a página passa a ler pelo
  caminho novo, o robô antigo é desligado, o endereço público antigo é fechado,
  e a publicação passa a acontecer sozinha num horário. É nessa etapa que a
  proposta guardada dos arquivos grandes entra.
