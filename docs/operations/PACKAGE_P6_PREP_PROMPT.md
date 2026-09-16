# Phase 6 — preparação, e a única peça que falta e é nossa

Escrito em 2026-09-16, ao fim da quarta sessão da Phase 4. Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

> ## ⛔ ESTA SESSÃO NÃO FAZ O CUTOVER
>
> O cutover é a Phase 6 e ele **não começa** antes da revisão pré-cutover do
> dono, que continua pendente nos quatro itens que restam. Este briefing prepara
> o que pode ser preparado **sem nenhuma autoridade de produção**, e nomeia o
> que é ação do dono em vez de fazê-la.
>
> **A Phase 4 FECHOU** em 2026-09-16: o candidato de 2026 está depositado em
> `araripe-v2-staging` e publicado pela lane, e as cinco cláusulas do exit gate
> P4 estão fechadas. Registro:
> [`../implementation/PHASE_4C_2026-09-16.md`](../implementation/PHASE_4C_2026-09-16.md).

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:docs/implementation/PHASE_4C_2026-09-16.md
    git show origin/main:docs/implementation/PHASE_2B3_2026-09-07.md   # §2
    git config core.hooksPath .githooks     # uma vez por clone

Confirme por conteúdo ou pelo assunto do squash, **nunca por ancestralidade** —
os dois repositórios fazem squash-merge, e `git log origin/main..origin/<branch>`
lista commits cujo conteúdo já está na `main`.

**A `main` do backend andou durante a sessão anterior**: o briefing dela citava
`c04709f…` e a PR `#61` foi mesclada depois, movendo-a. Rode
`git rev-parse origin/main` e use o que sair, não o que um documento diz.

O hook `commit-msg` recusa qualquer SHA de 40 caracteres que não exista *neste*
repositório, **inclusive o SHA legítimo do site**. Use a forma curta para o
site.

**Suítes na base:** backend **1867**, site **203**, worker **44/44**. Os +15 do
backend são o arquivo de teste novo da sessão anterior. Escrever o próximo
briefing soma outros **5**, porque
`tests/test_handoff_prompt_method.py` parametriza 5 checagens por
`docs/operations/PACKAGE_*_PROMPT.md` — a base sobe sem que nenhum teste tenha
sido escrito para ela.

**Use `npm run test:worker`, não `node --test tests/`** — o Node desta máquina
é v25 e a segunda forma morre com `MODULE_NOT_FOUND`. E confira
`pgrep -fl workerd` ao fim.

## 2. O que já foi verificado, para o executor não refazer

**a. As quatro decisões da Phase 4 continuam seladas.** Baseline `2.1.0`,
unidade `physical_datatake` sob `datatake_mosaic-v1`, sobreposição `0.55`,
linhagem ambígua `ambiguous-lineage-as-origin-v1`. Os defaults do azul
continuam `1.0.0`, `0.05` e `raise`, e há teste exigindo que cada par continue
**diferente**. **Não reabra nenhuma.** E **não tente outro valor de
sobreposição** — o parâmetro é autodestrutivo e isso está medido
(`PHASE_4B_2026-09-09.md` §15.3).

**b. A credencial de staging existe e funciona, e o código agora usa o profile.**
`cs.build_client` tem `profile_fallback` (default `False`), e só
`assemble_green_run.py` e `stage_green_run.py` optam. **Não estenda o opt-in
ao `publish_green_release.py`** — ele carrega a identidade de **promoção**, e um
fallback ali deixaria um shell com `AWS_PROFILE=araripe-r2-staging` mover o
ponteiro verde com a chave de candidato. Há teste que varre `scripts/*.py`
**pelo AST** e exige exatamente os dois.

Para rodar qualquer coisa verde local, exporte só valores **não-secretos**:

    export AWS_PROFILE=araripe-r2-staging AWS_REGION=auto
    export R2_STAGING_BUCKET=araripe-v2-staging
    export R2_ENDPOINT_URL=https://9416750169311ee4afc18a8ff3c771d4.r2.cloudflarestorage.com

**Nunca** exporte `R2_STAGING_ACCESS_KEY_ID`/`..._SECRET_ACCESS_KEY`. A receita
antiga em `PHASE_2B_GATE_2026-09-08.md` que faz
`aws configure export-credentials --format env` **está superada** — ela coloca o
segredo no ambiente do processo, que é o que o profile existe para evitar.

**c. O candidato está no bucket E publicado, e conferido contra três fontes.**
`runs/rep-2026-08-30-v3/`, **74 objetos**, **1 785 931 509 bytes**, todos
`created`. Digest por objeto batendo entre a montagem da sessão anterior, o
`execution_record.json` de 16/09 e os bytes em disco. A release é
`rel-g1-fb722b2d…`, publicada pela lane no run `35161611442`, com o ponteiro
verde em **sequence 10**. **Não re-monte para conferir** e **não deposite de
novo**: `put_if_absent` sobre bytes idênticos é no-op, mas o prefixo é imutável
e um run-id novo criaria um segundo candidato.

**d. Custos medidos, para você planejar e não remedir.**

| passo | onde | tempo |
| --- | --- | --- |
| montagem (`plan`) | local | **80 s**, pico de **7,2 GB** de RAM num Mac de 16 GB |
| depósito (`apply`, 1,78 GB) | local | **12 min 35 s** |
| validação read-only | local | **9 min 9 s** |
| job `stage` (a MESMA validação) | runner do GitHub | **2 min 46 s** |
| job `promote` (escreve + relê tudo) | runner do GitHub | **9 min 15 s** |

**O runner é ~3× mais rápido que esta máquina para o mesmo trabalho de I/O** —
a banda GitHub↔Cloudflare. Não orce o tempo de lane pelo número local. Os
timeouts são 20 min para o `stage` e 30 min para o `promote`, ambos folgados.

**e. 72 contra 74 não é discrepância, e já enganou uma leitura.** O `run.json`
declara **72** objetos de produto; `run.json` e `ledger.json` são os outros dois
arquivos do prefixo, que o manifesto não pode listar entre os próprios objetos.

**f. Um objeto de 43 bytes no candidato é CORRETO.**
`alerts/run-2026-02-11.strong.geojson` é a `FeatureCollection` vazia, porque
`is_strong` exige 2 avistamentos e na primeira data nada tem dois. Na tentativa
1 os **dois** objetos fortes tinham 43 bytes e aquilo **era** o defeito; aqui só
a primeira data é vazia. Não "conserte" isto.

**g. Os dois Environments existem, medidos e não supostos.**
`["cloudflare-green-control","v2-promotion","v2-staging"]`. `v2-staging` e
`v2-promotion` têm rules `["branch_policy"]` com política `["branch: main"]` e
**nenhum revisor obrigatório**. **Nunca nomeie um Environment que não existe** —
o GitHub cria o que for nomeado, sem proteção. **O repositório do site não tem
Environment nenhum.**

**h. `ROADMAP.md` está com o bloco datado stale, e isso é pendência real.** O
bloco no topo ainda diz *"Próxima frente: Phase 3"*, e as Fases 3 e 4 fecharam.
O fechamento da Phase 3 também não o atualizou — a convenção estabelecida é
registrar o gate em `docs/implementation/`. Atualizá-lo é trabalho pequeno e
**deliberado**; a sessão anterior não o fez para não mudar o documento canônico
do plano de passagem.

**i. O AZUL ESTÁ PARADO, e é achado de produção — leia antes de planejar.**
`detect_gee.yml` falha em **toda** execução agendada desde o landing do 2A.6:
2026-09-10 e 2026-09-14, as duas com `LegacyPersistenceStateError` e a mesma
lista de 16 colunas faltantes. A última agendada bem-sucedida foi **2026-09-03**.
Mecanismo lido na `main`: `load_persistence_state`
(`src/detection/persistence.py:443`) chama `_validate_state_columns`, que
levanta em `:375`; o landing trouxe esse loader para a `main` e o workflow faz
checkout da `main`, então a produção lê o estado vivo — de geração anterior —
com um loader que o recusa por contrato. A recusa é o desenho; a consequência
operacional não estava registrada em lugar nenhum. Detalhe completo na §11 de
`PHASE_4C_2026-09-16.md`.

**Não dispare `detect_gee.yml` nem `update_data.yml` para investigar** — os dois
escrevem em produção e não são idempotentes. E **não tente consertar**: o
rebuild que a exceção pede é o estado de geração nova que a Phase 4 já
depositou em staging, e ligá-lo à produção é o cutover, que é Phase 6 e exige a
revisão do dono.

## 3. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: o passo acrescenta uma escrita ao caminho de promoção, e esse
> caminho foi provado ponta a ponta contra R2 real cinco vezes em 2026-09-07.
> Mudá-lo invalida aquelas provas para o código que passa a rodar, então a
> re-prova faz parte do trabalho e não é opcional. É também o passo que decide
> se uma release pode um dia ser apagada — e a resposta de hoje é *não*.

**O histórico durável de promoção — um objeto imutável por escrita de ponteiro.**
Está **especificado e deliberadamente não construído** em
`docs/implementation/PHASE_2B3_2026-09-07.md` §2, que o chama de *"a package of
its own"*. A sessão da Phase 4 produziu a evidência ao vivo de por que ele é
necessário, e ela está na §6.1 e na §10 do registro daquela sessão.

Na ordem em que se sustenta:

1. **O dano já está medido — comece dele, não o remeça.** A sessão anterior
   leu o ponteiro antes e depois do movimento e mediu o que se perde:

   | | releases que o store consegue nomear |
   | --- | --- |
   | `sequence 9` | `rel-g1-24db9555…`, `rel-g1-2ddb10c7…` |
   | `sequence 10` | `rel-g1-24db9555…`, `rel-g1-fb722b2d…` |

   `rel-g1-2ddb10c7…` **esteve no ar** como sequence 8, todos os seus objetos
   continuam no bucket, e nada no store a distingue mais de uma release que
   nunca foi promovida. Ela só sobrevive como nome porque a §6.1 do registro a
   copiou à mão. E `rel-g1-24db9555…` sobreviveu **por acaso**: quatro
   tombstones a nomeiam. Sem mudança de conteúdo não haveria tombstone e ela
   teria saído junto — então não trate tombstone como histórico.
2. **Projete a escrita durável** — um objeto por movimento, write-once, sob um
   prefixo imutável, nunca sobrescrito. Ele tem de bastar para responder "esta
   release já esteve no ar?" sem depender do ponteiro.
3. **Acrescente a escrita a `atomic_publish.promote` e ao `rollback`,** e
   **re-prove o caminho inteiro contra R2 real**. Sem a re-prova, a mudança
   troca cinco provas válidas por nenhuma.
4. **Só então estenda a política de retenção.** Hoje
   `test_no_release_is_ever_eligible_at_any_age` prova que nenhuma release é
   jamais elegível a remoção, e isso está **certo** enquanto não houver
   histórico. Não afrouxe esse teste antes do passo 3.
5. **Nada é apagado nesta sessão**, nem depois. A exigência de publicação
   científica torna a imutabilidade um requisito e não uma prudência: um artigo
   cita **uma** release, para sempre.

**Fora de escopo, explicitamente:** o cutover, desligar o bot azul, ligar a
página à rota nova, qualquer coisa no domínio final, DNS, rotas ou no Worker
`observatorio-chapada` (**Phase 6**); a validação qualificada (**Phase 5**, com
portão de revisão do dono, e ela **não** começa sem essa revisão); qualquer
exclusão real de objeto; e o CI da suíte Python (**Phase 7**). **Não inicie as
Fases 5, 6 nem 7.**

## 4. Decisões de escopo já tomadas, com a base

- **As quatro decisões da Phase 4.** Não reabrir sem evidência contrária.
- **Nenhuma release pode ser apagada** até o histórico durável existir, e
  depois dele a exclusão continua exigindo aprovação humana explícita e
  nomeada.
- **Nenhum segundo produtor de ledger.** A detecção produz; o montador consome.
- **A identidade de promoção não vem para a máquina local.** Depositar é local,
  publicar é pela lane.
- **O portão de qualidade de cena não é modificado** — o arquivo de decisão
  declara `quality_gate_change_permitted: false` e há teste.
- **A produção azul continua rodando** e congelada.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- A `main` dos dois repositórios é **pull-request-only**, bypass vazio.
  Branch, PR. **A `main` do site faz deploy de produção.**
- Produção congelada nas Fases 2B-5: Worker `observatorio-chapada`,
  `araripe-cogs`, domínio final, DNS, rotas, workflows azuis, ponteiros
  canônicos, artefatos publicados.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. **Nunca dispare para testar.**
- Claude não recebe credencial de control-plane da Cloudflare; o único caminho
  é uma operação já allowlistada no broker protegido, cuja lista é exatamente
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Nunca nomeie um Environment que não existe.**
- **Nunca aprove a sua própria requisição de Environment.**
- A credencial de staging **permite delete**; o limite é o código
  (`ConditionalStore` não tem delete nem escrita incondicional), não a
  credencial. Mantenha assim.

## 6. Armadilhas já pagas — não redescobrir

- **Uma varredura de mutação tem de apagar `__pycache__` antes de CADA
  execução.** Uma mutação de **reordenação** preserva o tamanho do arquivo; com
  a reescrita caindo no mesmo segundo de `mtime`, a invalidação de bytecode do
  CPython — que compara **(mtime, size)** — não dispara, o pytest importa o
  `.pyc` antigo e a mutação aparece como "sobreviveu". Enganou **duas vezes**
  na sessão anterior. `-p no:cacheprovider` **não** resolve: o cache que engana
  é o do *import*.
- **Um teste pode passar pelo motivo errado — pergunte qual mutação ele derruba
  e derrube-a.** O teste de ordem do guarda de bucket afirmava só que um bucket
  errado levanta erro, e sobreviveu à mutação que move o guarda para o fim.
  Arme **duas** falhas de uma vez e exija qual delas fala.
- **Varredura de string pega docstring e comentário.** Use o AST. Os docstrings
  de `assemble_green_run.py` e `stage_green_run.py` **nomeiam**
  `profile_fallback=True`, então um grep passaria com a chamada fazendo o
  contrário.
- **`config/settings.py` carrega o `.env` de PRODUÇÃO no import**, e o guarda
  dos scripts verdes é **transitivo**. Nenhum script verde pode importá-lo.
- **`cd` composto no shell das ferramentas PEGA e PERSISTE.** Caminho absoluto
  sempre. Aconteceu de novo na sessão anterior.
- **`grep` desta máquina é `ugrep`**, e `grep -c` com zero casamentos **sai 1**,
  o que quebra uma cadeia `&&` inteira. Não encadeie em `grep` sem `|| true`.
- **Antes de declarar ausência de algo, pergunte onde a convenção do projeto
  diz que ele mora.** A credencial de staging foi declarada ausente porque foi
  procurada no `.env`, e o documento que a governa diz explicitamente para não
  usar `.env`.
- **Uma medição tomada num estado não representativo já enganou quatro vezes
  nesta frente** — a projeção de custo por subamostra sazonal, a premissa de
  disjunção dos tracks, a fração de linhagem medida no estado congelado, e o
  cache de bytecode.
- **`ProfileNotFound` do boto3 vem do CONSTRUTOR de `Session`, não de
  `get_credentials()`.** E um profile que existe sem chave constrói `Session`
  sem erro nenhum.
- **Outra sessão pode estar no mesmo clone.** O `stash@{0}` continua intocado.
  Confira `git status` antes de todo checkout e **nunca rode `git stash` ali**.
- **Confira `gh pr list --head <branch>` depois de cada push**, e **não
  acrescente commits a uma branch cuja PR já foi aberta** — o dono mescla
  rápido e isso já deixou commits órfãos duas vezes.

## 7. Estado que esta sessão herda

- **A Phase 4 fechou.** Candidato depositado e publicado dentro do bucket de
  staging; as cinco cláusulas do gate P4 fechadas.
- **O bullet 1 da Phase 4 fica PARCIAL** e não é desta sessão: preservar a
  geração antiga como release **no store** exige uma identidade de release, que
  deriva de um ledger v3, e **nenhum produtor azul escreve um**. O inventário
  está selado e citável.
- **As três tentativas do replay continuam lado a lado** num diretório isolado
  durável fora do repositório, com os compostos em disco. O caminho absoluto
  não está em documento nenhum, de propósito.
- **A revisão pré-cutover do dono** continua pendente nos quatro itens que
  restam; é portão da Phase 6.
- **Dois pré-requisitos da Phase 6, e NÃO são ação do dono hoje:** o endereço
  temporário do Worker de staging e o Environment protegido no site. Os dois
  exigem `Workers Scripts: Edit` em nível de conta, que alcança o Worker de
  produção, e nenhum bullet das Fases 3, 4 e 5 depende deles.
- **A PR draft `#21` do site** não deve ser mesclada antes da Phase 6: medido,
  tirar a re-inclusão dá 404 na data mais recente.
- **O token da NASA expira em 2026-11-06**, e a falha aparece vermelha.
- **A `2.1.0` admite produtos pré-Collection-1 nos meses 1-4**; vigilância em
  `scripts/check_esa_reprocessing.py`.
- **Nenhum workflow deste repositório roda a suíte Python** — CI é Phase 7.
- **Cadência agendada:** detecção do backend Seg/Qui 06:00 UTC e refresh do
  site Ter/Sex 06:00 UTC, com folga deliberada de 24 h. Preserve a folga.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

**Nada da tarefa desta sessão.** O recálculo de 2026 foi depositado no depósito
de testes e publicado lá dentro, e a última exigência da Fase 4 fechou. A Fase
4 acabou.

O que **não** era desta tarefa e continua aberto é uma coisa só, e ela é a
próxima: **o sistema não guarda um registro permanente de qual versão dos dados
esteve no ar em cada momento.** Existe um ponteiro que diz "a versão atual é
esta", e ele guarda **um** passo para trás e mais nada. Toda vez que ele se
move, a lembrança da versão anterior à anterior desaparece.

Isso não é um erro novo: já estava medido e registrado, de propósito, como um
trabalho à parte. O que esta sessão acrescentou foi a prova ao vivo — para
mover o ponteiro, eu tive de **copiar o valor antigo à mão para dentro de um
documento**, porque senão ele se perderia. Enquanto isso não for consertado,
nenhuma versão dos dados pode ser apagada, nunca. E isso está certo assim.

### O que você precisa fazer

1. **Mesclar as duas pull requests desta sessão** (backend). Uma é a correção
   de credencial com os testes, a outra é o registro do fechamento da Fase 4.
   Não é urgente, mas a próxima sessão trabalha a partir delas.
2. **Decidir o que fazer com a detecção parada** (veja a seção seguinte). São
   duas saídas, e as duas são suas: antecipar a virada para a Fase 6, que é o
   conserto de verdade e exige a sua revisão pré-virada; ou aceitar
   explicitamente que o sistema no ar fica parado até lá, e registrar isso.
   **Qualquer conserto passa por mexer na produção, então eu não mexo sem você.**
   É a coisa mais urgente desta lista.
3. **Decidir qual é a próxima frente.** São três caminhos e a escolha é sua:
   - **o registro permanente de versões** — é a recomendação, porque não
     depende de nenhuma revisão sua e porque ela destrava a limpeza do
     depósito mais tarde;
   - **a Fase 5**, a validação independente, que está parada esperando a sua
     revisão de três decisões de método (o desenho da amostra, o papel do
     drone, e autoria/anonimato dos revisores);
   - **a Fase 6**, a virada para o público, que espera a sua revisão
     pré-virada nos quatro pontos que restam.
4. **Quando puder, olhar o número que vai para a publicação.** Cerca de **3,5%**
   das detecções de 2026 tiveram origem impossível de determinar e foram
   registradas como eventos novos, seguindo a sua regra de 16/09. É um número
   honesto e defensável, mas é seu para conhecer antes de alguém perguntar.
5. **Autorizar, ou não, uma correção pequena no documento do plano.** O bloco
   no topo dele ainda diz que a próxima frente é a Fase 3, e as Fases 3 e 4 já
   fecharam. É meia hora de trabalho e nenhum risco, mas é o documento que
   governa tudo o mais, então eu não o mudo de passagem. Pode esperar.

### Tem algo preocupante?

**Sim, uma coisa — e ela não é desta tarefa. O sistema que está no ar parou de
detectar desmatamento novo.**

A última vez que a detecção automática rodou com sucesso no horário dela foi
**3 de setembro**. Depois disso, as duas execuções agendadas (10 e 14 de
setembro) falharam, as duas pelo mesmo motivo. O dado mais recente que o site
mostra é de **30 de agosto**.

O motivo, em uma frase: em 8 de setembro a ciência nova entrou no ramo
principal, e ela **se recusa a trabalhar com o arquivo de memória antigo** do
sistema — de propósito, porque aquele arquivo não tem as informações que a
ciência nova precisa e usá-lo produziria números em que não se pode confiar.
Ela para em vez de fingir.

**A recusa está certa. O que ninguém escreveu é que isso pararia a detecção.**
Estava registrado que o arquivo antigo teria de ser reconstruído, e que
reconstruí-lo era trabalho da Fase 4 — mas não que, enquanto isso não
acontecesse, o sistema no ar ficaria parado. Já são duas semanas sem registro
de incidente.

**E a notícia boa é que a peça que falta é justamente o que esta sessão
acabou de construir.** O recálculo de 2026 produziu exatamente o arquivo de
memória novo que a detecção pede, e ele está guardado no depósito de testes,
conferido. Ligar os dois é a virada, a Fase 6 — que espera a sua revisão. Eu
**não** fiz isso, e não devo fazer sem ela.

Duas coisas que **não** são alarme, para você não se preocupar com elas:

- o site **não** está mentindo sobre o frescor do dado. Existe um arquivo
  interno que diz "atualizado em 15 de setembro", mas ele é de monitoramento e
  nenhuma página o lê — conferido. O site mostra dado cuja observação mais
  recente é 30 de agosto;
- o **token da NASA expira em 6 de novembro de 2026**. Quando expirar, a
  atualização de chuva falha e aparece vermelha. Ainda há tempo, e é uma troca
  simples.

### O que ainda falta no caminho

- **Fase 4 — pronta.** O ano de 2026 inteiro foi recalculado com a ciência
  nova e o resultado está guardado no depósito de testes, conferido.
- **Registro permanente de versões** — a peça que falta para o depósito poder
  ser limpo um dia sem risco. É trabalho meu, e não toca a produção.
- **Fase 5 — validação independente.** Parada esperando a sua revisão. Ela
  **não** trava as fases seguintes; foi decisão sua.
- **Fase 6 — a virada.** Ligar o site ao caminho novo, desligar o robô antigo,
  mover o endereço público. Espera a sua revisão pré-virada, e é a fase em que
  algo pode de fato quebrar para quem visita o site. **Passou a ser também o
  conserto da detecção parada**, o que muda a urgência dela.
- **Fase 7 — acabamento.** Rodar os testes automaticamente a cada mudança,
  acessibilidade, e transformar o que aprendemos em ferramentas reutilizáveis.
