# Phase 4, segunda sessão — rodar o replay e montar o candidato

Escrito em 2026-09-09, ao fim da primeira sessão da Phase 4. Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

**As duas decisões que travavam a fase estão tomadas, a cadeia GEE está
exercitada, a contabilidade está construída e testada, e a enumeração do ano
inteiro rodou de verdade.** O que falta é a execução longa e a montagem. O gate
P4 **não fechou** e o estado dele, cláusula por cláusula, está em
[`../implementation/PHASE_4_2026-09-09.md`](../implementation/PHASE_4_2026-09-09.md) §5.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:docs/implementation/PHASE_4_2026-09-09.md
    git show origin/main:config/phase4_composition_unit_decision_v1.json

A PR desta sessão é **`#58`** (`claude/phase4-replay`) e foi aberta **sem
mesclar**. Confirme por conteúdo ou pelo assunto do squash, nunca por
ancestralidade — os dois repositórios fazem squash-merge.

Medido nesta sessão, com a Phase 3 mesclada. `origin/main` do backend em
`6ef2da3455af29f394637bdf9cc193ae6810f3be`, `origin/main` do site em `5304a81`:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **1738** na `main`, **1797** na branch |
| site | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **203** na `main` |
| site | `npm run test:worker` | **44 tests, 44 pass** |

**O site não precisou de mudança nesta fase e provavelmente não precisa na
próxima**: o candidato fica em staging e a página só passa a lê-lo na Phase 6.

**Use `npm run test:worker`, não `node --test tests/`** — o Node desta máquina
é v25 e a segunda forma morre com `MODULE_NOT_FOUND`.

**Ative o hook** com `git config core.hooksPath .githooks`. Ele recusa qualquer
SHA de 40 caracteres que não exista *neste* repositório, inclusive o do site.

## 2. O que já foi verificado, para o executor não refazer

**a. As duas decisões da fase estão tomadas e seladas.**
`config/phase4_composition_unit_decision_v1.json`, lido em tempo de execução
por `src/replay/composition_unit.py`, que falha fechado. **Não redecida.**

- **Unidade de composição: o datatake físico, sob `datatake_mosaic-v1`.** A
  base é que o ledger v3 não tem status terminal para *"os pixels desta
  aquisição entraram no composto de outra"*, então a unidade de composição não
  pode ser mais grossa que a de contabilidade.
- **Grade: não fixar a `crsTransform`.** Medido: as duas grades **já
  coincidem** — 10719/10719 coordenadas x e 4909/4909 y casam exatamente, e
  `reindex_like(tolerance=15)` é seleção de janela, não reamostragem.

**b. A cadeia GEE funciona desta máquina, e a Phase 3 concluiu o contrário por
um motivo específico.** Ela mediu a ausência de credencial de **serviço** e
concluiu que a cadeia era inexercitável. Existe uma credencial OAuth de usuário
em `~/.config/earthengine/credentials`, que é o que `ee.Initialize()` lê — e é
a razão de ele ignorar `GOOGLE_APPLICATION_CREDENTIALS`.
`ee.Initialize(project="ee-araripe")` funciona.

**c. As sete colunas do `reduceColumns` estão PROVADAS**, com contra-prova por
coluna via `aggregate_array`, em duas janelas (24 e 510 cenas). E a checagem
ficou no código: `enumerate_window` a refaz a cada execução.

**d. MEDIDO — a geometria do problema.** 2026-01-01..2026-08-31 exclusivo,
`CLOUDY_PIXEL_PERCENTAGE < 60`: **510 cenas, 107 datatakes, 90 datas**, 17 com
dois datatakes, 0 com três. Duas órbitas relativas apenas: **R095** (~13:02
UTC, 55 datatakes, até 99,6% do extent) e **R138** (~13:13 UTC, 52 datatakes,
teto de **5,8%** — fatia de borda de faixa, não nuvem).

**e. MEDIDO — o que sobra para puxar.** Com o portão de cobertura existente e
não modificado: **107 esperadas, 48 a puxar, 59 rejeitadas na cobertura
medida** (maior rejeitada 7,12%). Nenhuma data muda de lado do portão. 41 das
90 passam de qualquer maneira.

**f. MEDIDO — o custo por composto, nos dois caminhos.** Sequencial, por
`download_image_tiled`: **525 s / 729 MB**. Paralelo (8 tiles concorrentes),
pelo driver: **75 s / 723 MB**. **7,0x.** Projeção para os 48: cerca de **1
hora** e **~35 GB** com `deflate`. Havia 135 GB livres.
**`download_image_tiled` não foi tocado** — acrescentar concorrência ali
mudaria um caminho azul.

**g. Um lote real rodou fim a fim**, em 2026-08-25 (data dupla): composto R095
puxado, 6136 polígonos detectados com 97,7% de cobertura, MapBiomas 10m e 30m
aplicados, persistência uma vez para a data, R138 filtrado em 5,49%. Duas
linhas terminais: `complete_with_alerts` com 6136 observações e checksum de
artefato, e `rejected_low_coverage` com a fração medida.

**h. A cota continua não sendo o limitante** e **não refaça a análise**:
`ee-araripe` tem 3.600.000 EECU-s/mês com 0,17% usados; uma passagem do replay
é ~3,2% de um mês. Aritmética em
[`PHASE_3_INPUTS_2026-09-08.md`](PHASE_3_INPUTS_2026-09-08.md) §3.

**i. Ferramentas que já existem — leia antes de escrever nova:**
`scripts/replay_2026.py` (`plan` e `run`), `src/replay/enumeration.py`,
`scripts/assemble_green_run.py`, `scripts/stage_green_run.py`,
`scripts/publish_green_release.py`, `scripts/audit_timeseries.py`,
`scripts/check_processing_ledger.py`, `scripts/apply_persistence_filter.py`.

## 3. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: é a execução que a fase existe para fazer uma vez, e o passo de
> montagem toca o contrato de release. Um candidato montado errado é
> plausível, não obviamente quebrado.

Feche o **exit gate P4**. O escopo, na ordem em que se sustenta:

1. **Rodar o replay inteiro**, em lotes cronológicos limitados. O `plan` já
   está escrito no diretório isolado; cada `run` é uma fatia:

       python scripts/replay_2026.py plan --start 2026-01-01 --end 2026-08-31 \
           --out-dir <isolado>
       python scripts/replay_2026.py run --start 2026-01-01 --end 2026-08-31 \
           --batch-start 2026-01-01 --batch-end 2026-03-01 \
           --out-dir <isolado> --state-path <isolado>/persistence_state.geojson

   **O manifest é o da janela inteira e um lote é uma fatia dele.** Os lotes
   acumulam linhas em `terminal_rows.json` e o `run` retoma; só o lote que
   completa as 107 escreve `ledger.json`. Isso é medido, não suposto: o
   primeiro lote levantou `IncompleteDateError` exatamente ali.

2. **Resolver o corte com `resolve_recorded_cutoff`** contra as datas terminais
   **do ledger que o replay produziu** — não do banco azul — e **fixar o
   literal** no registro da execução. Gravar a fila pós-corte com esse corte.
   Isto só pode acontecer **depois** do item 1: a função toma as datas
   terminais, e antes do replay elas não existem.

3. **Preservar a geração antiga como release histórica imutável** — bullet 1 do
   roadmap, ainda não feito. Desde que a Phase 5 virou publicação científica
   isso é **requisito**, não prudência.

4. **Regenerar** tiers de persistência, subconjuntos fortes, estatísticas e as
   linhas limpas de série temporal de 2026 (bullet 8).

5. **Montar e depositar em staging**: `assemble_green_run.py` →
   `stage_green_run.py` → `publish_green_release.py`, sem mover o ponteiro
   final. **Deixar o candidato em staging. NÃO promover.**

6. **Reconciliar** e registrar em `docs/implementation/PHASE_4_<data>.md` com o
   estado do gate e o que continua sem prova.

**Fora de escopo, explicitamente:** promover o candidato; a validação
qualificada (**Phase 5**, com portão de revisão do dono, e ela **não** começa
sem essa revisão); o cutover, o desligamento do bot azul, ligar a página à rota
nova e qualquer coisa no domínio final (**Phase 6**); o histórico durável de
promoção e qualquer exclusão real. **Não inicie as Fases 5, 6 nem 7.**

## 4. Decisões de escopo já tomadas, com a base

- **A unidade de composição é o datatake físico** (§2a). Não reabrir sem
  evidência contrária.
- **A grade não é fixada** (§2a).
- **O portão de qualidade de cena não é modificado.** Reinterpretá-lo contra a
  pegada do datatake aceitaria as fatias R138 e não perderia nada — e é
  **mudança de ciência, da Phase 5**. O arquivo de decisão declara
  `quality_gate_change_permitted: false` e um teste o exige.
- **O filtro de cobertura só pode rejeitar.** `assess_scene_quality` continua
  sendo a única coisa que aceita. A condição de correção está escrita e testada
  (`test_a_condicao_de_correcao_do_filtro_vale_na_faixa_toda`).
- **Nenhum segundo produtor de ledger.** A detecção produz; o montador consome.
- **Nada é apagado.**
- **A produção azul continua rodando** durante o replay.
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
  escreve **só** em `araripe-v2-staging`, e
  `src/replay/rehearsal.staging_bucket_only` recusa outro store.
- Claude não recebe credencial de control-plane da Cloudflare; o único caminho
  é uma operação já allowlistada no broker protegido, cuja lista é exatamente
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Nunca nomeie um Environment que não existe** — o repositório do site não
  tem nenhum.
- **Exclusão de objeto real exige aprovação humana explícita e nomeada.**

## 6. Armadilhas já pagas — não redescobrir

- **`to_dict()` do ledger falha fechado num lote parcial.** É o desenho, não um
  bug: o ledger amarra um manifest e só serializa quando as 107 estão
  terminais. Por isso os lotes acumulam em `terminal_rows.json`.
- **Um teste pode passar pelo motivo errado — duas vezes nesta sessão.**
  `test_a_divergencia_de_metodo_de_composicao...` dizia no docstring que cairia
  "se o export passar a compor por datatake"; o export passou e ele **não
  caiu**. E o leitor da decisão tinha duas mensagens de erro que eram **código
  morto** atrás de uma checagem genérica. Pergunte sempre qual mutação o teste
  derruba, e derrube-a.
- **Varredura de string pega docstring.** Um teste desta sessão procurou
  `--persistence-mode` no arquivo inteiro e casou com o docstring que explica
  que a flag não existe. Use o AST.
- **`config/settings.py` carrega o `.env` de PRODUÇÃO no import**, e o guarda
  dos scripts verdes é **transitivo**. O driver do replay importa `config`
  dentro de `command_run`, não no topo, para o `plan` não carregar o `.env`.
- **Duas canonicalizações não são a mesma** (`1.0` vs `1`, `1e-07` vs `1e-7`);
  os documentos selados recusam float.
- **`cd` composto no shell das ferramentas pega, e PERSISTE.** Aconteceu de
  novo nesta sessão. Caminho absoluto.
- **`grep` desta máquina é `ugrep`**: `grep -qv` retorna 1 mesmo com linhas
  selecionadas.
- **Outra sessão pode estar no mesmo clone.** Havia um `stash@{0}` de outra
  sessão; ele **não** foi aplicado nem descartado. Commite por caminho
  explícito e confira `git status` antes de todo checkout.
- **Confira `gh pr list --head <branch>` depois de cada push** e
  `pgrep -fl workerd` ao fim.

## 7. Estado que esta sessão herda

- **Phase 3 fechada**, backend `#56`/`#57` e site `#25` mescladas.
- **A baseline do replay é a `2.1.0`**, decisão do dono de 2026-09-09.
  `BASELINE_VERSION` do azul continua `1.0.0` e um teste exige que sejam
  diferentes.
- **O congelamento** é `e877e9b1b1150d64c5ac71aeaf7bb23ff7c8b59b29984bd301bfdc3f8611a577`;
  comece rodando `pytest -q tests/test_replay_freeze.py`.
- **Manifest do ano**: `run-v3-934387671941a94c415ada64f75a81699c4e030f1f09b7a14e8deca8b5c7208f`.
- **A revisão pré-cutover do dono** continua pendente nos quatro itens que
  restam; é portão da **Phase 6** e não bloqueia a Phase 4.
- **Dois pré-requisitos da Phase 6, e NÃO são ação do dono hoje:** o endereço
  temporário do Worker de staging e o Environment protegido no site. São a
  mesma autoridade de conta e nenhum bullet das Fases 3, 4 e 5 depende deles.
- **A PR draft `#21` do site** não deve ser mesclada antes da Phase 6.
- **O token da NASA expira em 2026-11-06**, e a falha aparece vermelha.
- **A chuva do site está pulando por rede**; primeiro dia vermelho 22/09/2026.
- **A `2.1.0` admite produtos pré-Collection-1 nos meses 1-4**, que a ESA está
  reprocessando: janeiro-abril pode ter de ser refeito. Vigilância em
  `scripts/check_esa_reprocessing.py`. O registro da execução deve dizer contra
  qual regime sazonal cada mês foi composto.
- **Nenhum workflow deste repositório roda a suite Python** — CI é Phase 7.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

**O recálculo em si — e ele não começou por falta de tempo de máquina, não por
obstáculo.** Esta sessão fez tudo o que precisava vir antes: decidiu as duas
perguntas que estavam abertas, mediu o que ninguém tinha medido, montou a
contabilidade que registra o destino de cada imagem, e rodou um dia inteiro de
ponta a ponta para provar que a corrente funciona.

O que sobrou é a parte longa: são **48 imagens** para baixar e processar, cerca
de **uma hora** de download mais o processamento. A próxima sessão roda isso.

Duas coisas que vale saber que mudaram de figura:

1. **Descobri que o computador consegue falar com o Google Earth Engine.** A
   etapa anterior tinha concluído que não conseguia, e a conclusão estava
   errada por um detalhe técnico. Isso destravou toda a medição desta sessão.
2. **O recálculo ficou muito mais barato do que parecia.** Baixando as partes
   de cada imagem em paralelo, cada uma leva 75 segundos em vez de quase 9
   minutos.

### O que você precisa fazer

1. **Nada urgente.** Quando quiser, abra a próxima sessão para rodar o
   recálculo. O texto acima já diz ao assistente tudo o que ele precisa.
2. **Mesclar a proposta desta sessão quando lhe convier** — ela é a número 58,
   e está aberta sem mesclar, como o senhor pediu. Ela não muda nada do que
   está no ar; acrescenta a decisão, a ferramenta e a documentação. Pode
   esperar.
3. **Anotar 6 de novembro:** a chave da NASA expira e o mapa de chuva para de
   novo. Essa falha é vermelha, não silenciosa, e é a única data no calendário.

### Tem algo preocupante?

**Não.** Produção não foi tocada, o site publicado continua igual, nada foi
apagado, nenhuma senha ou chave foi usada, e nenhum arquivo do sistema no ar
foi modificado.

Há **uma coisa que o senhor deve saber**, porque é uma escolha minha com
consequência científica, ainda que pequena, e prefiro que ela chegue ao senhor
por escrito e não escondida numa tabela.

O satélite passa sobre a Chapada por dois caminhos diferentes. Um deles cobre
quase toda a área; o outro só raspa uma faixa fina da borda — no máximo 5,8%.
Hoje, em 17 dias do ano, o sistema junta as duas passagens numa imagem só, sem
registrar de qual delas veio cada pedaço. Isso torna impossível dizer, depois,
qual passagem enxergou o quê — e a etapa de publicação científica precisa
exatamente disso.

Decidi separá-las: cada passagem passa a ser contada por si. A consequência é
que a faixa fina, por ser pequena demais, passa a ser **registrada como
descartada** em vez de entrar em silêncio. Medi o que se perde com isso: em no
máximo **0,85% da área**, em 13 dias do ano, um pedaço que hoje é observado por
essa passagem estreita deixará de ser. É pequeno, e agora fica escrito quanto
foi, em vez de desaparecer sem registro.

Existe uma alternativa que não perderia nada: mudar a régua de "quanto da área
precisa estar visível" para medir cada passagem contra o seu próprio tamanho em
vez de contra a área toda. **Não fiz isso de propósito** — mudar régua é
decisão científica, e essas ficam para a etapa de validação, que tem a sua
revisão. Deixei a medição pronta para o senhor decidir lá.

### O que ainda falta no caminho

- **Rodar o recálculo do ano inteiro** e guardar o resultado sem publicar — a
  próxima etapa, agora sem nada travando.
- **A validação científica** — a etapa que não começa sem a sua revisão, porque
  o objetivo passou a ser uma publicação. É lá que entra a decisão sobre a
  régua que mencionei acima.
- **Uma etapa própria para a memória de publicações**, que é o que permitirá um
  dia apagar versões antigas com segurança.
- **A troca final:** o novo substitui o antigo, a página passa a ler pelo
  caminho novo, o robô antigo é desligado e a publicação passa a acontecer
  sozinha num horário. **É aqui que a sua revisão do roteiro é obrigatória.**
- **O endurecimento:** ligar as verificações automáticas nos dois repositórios
  (hoje elas só rodam na minha máquina), proteção de branch e acessibilidade.
