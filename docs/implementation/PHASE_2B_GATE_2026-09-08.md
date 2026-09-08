# Exit gate P2B — o montador ligado a uma execução real, e o fechamento da Phase 2B

**Started:** 2026-09-08
**Base:** backend `origin/main` at `cd2820a41a0c03325757dbd452df8f363990908e`;
site `origin/main` at `826fc0dcc36e22f059ff1fbc2da5236419646a1c`
**Branch:** `claude/phase2b-gate` (backend). **Nenhuma mudança no site** — o
repositório do site foi validado sem alteração, e não há PR de site.
**Production impact:** none. Nenhum deploy, nenhuma mudança de DNS, rota,
binding, workflow ou gatilho, nenhuma escrita fora de `araripe-v2-staging`,
nenhuma operação de control-plane, nenhum Environment tocado, nenhum workflow
disparado, nenhum objeto apagado.

Fecha o **exit gate P2B**: *"A deliberately failed or racing green run cannot
corrupt blue or expose a partial release; a staged test release can move and
roll back its green pointer without a manual data PR or any production
effect."*

## 0. Orientação, medida antes de editar

Backend `git rev-parse origin/main` → `cd2820a41a0c03325757dbd452df8f363990908e`
(a `#51` mesclou o briefing atualizado; a versão da branch
`claude/gate-briefing-refresh` e a da `main` são **idênticas**, conferido por
`diff`). Site → `826fc0dcc36e22f059ff1fbc2da5236419646a1c`. Nenhuma PR aberta
no backend; uma no site (`#21`, draft, **não mesclar** — 2B.4B bullet 2).

Dependências do §1 do briefing, conferidas por conteúdo:
`src/publication/site_artifact.py` resolve nos dois repositórios, e os vetores
têm `{'object_cases': 8, 'run_cases': 10, 'index_cases': 4,
'rejection_cases': 9}` — **31 casos**.

Gates medidos **antes**: backend **812 passed**; site **201 passed** e
**44/44** em `npm run test:worker`. Exatamente o que o briefing previa.

O `stash@{0}` de outra sessão foi deixado intocado; os untracked
`data/baselines_v2/`, `data/landcover/updated/` e `data/validation/` ficaram
fora do commit.

## 1. Escopo: quatro itens, e o que cada um passou a ser

O §0 do briefing corrigiu dois dos cinco itens originais: o montador da rodada
**já existia** (`bf2c2cf`, `#49`) e já satisfazia o contrato do artefato do
site. Sobraram quatro, e nenhuma linha de `src/publication/run_assembler.py`
foi tocada.

| item | o que era | estado |
| --- | --- | --- |
| 1 | o ponto de entrada de operador que liga o montador a uma execução real | **feito** — `scripts/assemble_green_run.py` |
| 2 | a prova de execução falhada e concorrente, executada | **feito** — R2 real e 31 testes determinísticos |
| 3 | uma release de teste com dado real, movendo e revertendo o ponteiro | **feito** — sequências 4→5→6, e mais 7→8→9 |
| 4 | registrar o fechamento | este documento |

## 2. O ponto de entrada (item 1)

`scripts/assemble_green_run.py`, dois modos:

    python scripts/assemble_green_run.py plan  --run <id> --ledger <path>
    python scripts/assemble_green_run.py apply --run <id> --ledger <path>

`plan` não toca object store nenhum e não lê credencial; `apply` deposita
`runs/<run-id>/` com `put_if_absent` em todo objeto e o manifesto por último.

**Lane 2, e nada além disso.** `GREEN_CONCURRENCY_LANES.md`: *"Writes:
immutable per-run prefixes only … no deletes, no overwrites, no pointers."*
Lê `R2_STAGING_*`, e `test_o_ponto_de_entrada_nao_nomeia_a_identidade_de_promocao`
e `test_nenhuma_escrita_de_ponteiro_e_expressavel_no_ponto_de_entrada` afirmam
por `ast` que `R2_PROMOTION`, `pointers/green/current.json`, `put_if_match` e
`put_if_pointer_absent` não aparecem como código.

**Não escreve ledger.** `--ledger` é obrigatório e é lido como bytes que o
produtor selou. Ver §3.

### 2.1 Três traduções entre o disco do produtor e o contrato

O montador deixa aberta uma pergunta de propósito — *de onde vêm as feições* —
e é só isso que este arquivo decide. Cada resposta é uma medição:

1. **Uma data que o ledger reconcilia como `alerts` e não tem arquivo fica
   ausente**, e a biblioteca a recusa (`date_without_detection_output`).
   Fornecer `[]` transformaria uma detecção que não escreveu numa afirmação
   publicada de que o dia foi quieto.
2. **Uma data `zero_alerts` sem arquivo vira `[]`.** Medido do produtor:
   `scripts/run_detection.py:508` só põe a data em `alerts_by_date` dentro do
   galho que achou alertas, e loga *"Scene {}: no alerts"* no outro — logo uma
   data observada e quieta **não escreve arquivo nenhum**. O contrato exige
   duas coleções vazias, como *observação positiva de ausência*, e o ledger é
   a autoridade que diz que alguém olhou.
3. **Uma data `zero_alerts` cujo arquivo tem feições é recusada.** A
   biblioteca **não** pega este caso — ela checa o espelho
   (`features_for_an_unobserved_date`). O ledger diz que toda aquisição
   reportou nada e a detecção diz o contrário; publicar qualquer das duas
   versões faria a release contradizer o ledger que ela embarca.
   `test_a_biblioteca_sozinha_publicaria_essa_contradicao` escreve por extenso
   a mutação que isso derruba, para ninguém "simplificar" removendo a checagem.

### 2.2 O defeito que eu mesmo introduzi, e o que ele ensina

A primeira versão de `collect_features` **recusava** um arquivo de uma data que
o ledger não reconcilia, passando-o adiante para a biblioteca o nomear. Parece
uma boa checagem cruzada. Medido quem enche o diretório:

* no CI, `detect_gee.yml` busca **só** o estado de persistência antes da
  detecção (o comentário no topo do arquivo ainda fala de buscar alertas
  recentes, e o passo que faz isso não existe mais), então `data/alerts/`
  contém exatamente as datas daquela rodada — e a checagem passaria;
* localmente e no build do site, `fetch_alerts_from_r2.py` **sem** `--latest`
  baixa o arquivo inteiro para o mesmo diretório (`--out` cai em `ALERTS_DIR`)
  — e a checagem **recusaria toda rodada real**, porque há 40 datas
  históricas em disco e um ledger reconcilia três.

Executado contra o dado real, foi exatamente isso: `RunAssemblyRejected
[features_for_an_unreconciled_date]` para 2026-08-30 numa rodada de duas datas.

*"Todo arquivo no diretório de alertas é desta rodada"* é propriedade de **um
dos dois usos documentados**, não promessa do produtor, e o ponto de entrada
não consegue saber qual deles enchura o diretório. Encodá-la seria o incidente
de 2026-09-07 (`first_seen <= last_seen`) num lugar novo. As datas a mais
passaram a ser **ignoradas e reportadas** (`ignored : N date(s)`), e
`test_o_ledger_decide_as_datas_e_um_arquivo_a_mais_e_ignorado` derruba a volta
da versão antiga.

### 2.3 Por que não importa `config.settings` — e um pin novo

`config/settings.py`:13-18 chama `load_dotenv(ROOT_DIR / ".env")` **no import**,
e o `.env` do repositório guarda as credenciais de **produção**. Importá-lo
para alcançar `ALERTS_DIR` colocaria esses valores no ambiente de um lane cujo
princípio inteiro é não alcançar produção — o mesmo defeito medido no site, onde
`wrangler dev` injetou cinco bindings de credencial do `.env`.

Nenhum dos cinco scripts verdes o importava, e nada afirmava isso.
`test_nenhum_script_verde_importa_o_carregador_de_dotenv` passou a afirmar, por
`ast` e não por texto — a docstring deste próprio arquivo cita
`config.settings`, e uma varredura textual acusaria o comentário em vez do
import. É a armadilha do 2B.4B no sentido correto, e a mutação M5 (§6) confirma
as duas polaridades.

Os nomes de arquivo e diretório vêm do produtor e são lidos dele:
`test_o_nome_do_arquivo_de_alerta_e_o_do_produtor` extrai por `ast` a f-string
que `save_alerts` atribui a `filename`.

## 3. A condição bloqueante do roadmap: integração com o produtor 2A.6

O roadmap, Package 2B.2: *"Consume the exact version and checksum of the v2
ledger contract/schema and backend producer owned by Package 2A.6. … Development
may run in parallel, but **the P2B gate cannot close before integration with the
2A.6 producer passes**."*

O produtor é `src/detection/ledger_v3.py`, e ele está em
`claude/phase2a6d-mapbiomas`, **não** na `main`. Nenhum produtor na `main`
escreve um ledger v3 — medido varrendo `scripts/` e `src/`.

Medido, e é o que fecha a condição:

* o exemplo e o schema do produtor são **byte-idênticos** nas duas branches —
  `processing-ledger-v3.example.json` sha256
  `fd2db1efd8ac79563f498677bb9c8eccf9f32e8e177958e196a8f1e4353a2e87`, schema
  `fde07d7b03b5caf43c01c7a4ee1ab0c0d4f60d2bd71151129ada872cda5f2ad0`;
* **o produtor real reproduz o próprio exemplo.** `ProcessingLedgerV3`
  reconstruído das aquisições do exemplo devolve o mesmo `ledger_id`
  (`pl-v3-49e3e14e…`) e um documento **igual campo a campo**, com
  `integrity.document_sha256` idêntico
  (`ca6605a4a7994119f694297001d4de880b57118a4d8c22b8740bb32891f8f573`). Os
  bytes diferem só na forma de serialização — `to_bytes()` é a forma canônica
  compacta, o exemplo commitado é `indent=2` — o que a não-exigência 4 do
  binding permite explicitamente;
* **ledgers emitidos pelo produtor real para as datas reais foram aceitos ponta
  a ponta pela `main`**: `check_processing_ledger`, `build_release`,
  `check_green_release`, `verify_release` e `promote`. Nenhum deles foi
  adaptado.

O que **continua sem prova** é o resto do caminho: os metadados de aquisição
(datatake, cena, timestamp) foram **declarados**, não recuperados, porque nenhuma
execução de detecção real jamais emitiu um ledger v3 — o produtor não está na
`main` e `detect_gee.yml` não o chama. As **identidades** derivam do produtor
(`create_acquisition_v3` → `identity_sha256`); os insumos físicos não vêm de
uma passagem real. Ver §7.

## 4. O dado real (item 3)

Baixado por HTTPS público, **sem credencial nenhuma**, do bucket que a produção
já publica (`https://pub-5eb389cffff54421916187be69dd659b.r2.dev/`):

| objeto | feições | bytes | sha256 |
| --- | --- | --- | --- |
| `alerts/alerts_2026-08-22.geojson` | 5 497 | 20 723 442 | `06d58d90a56cfa81…` |
| `alerts/alerts_2026-08-25.geojson` | 6 762 | 25 637 125 | `04a10f982d16139d…` |
| `alerts/alerts_2026-08-30.geojson` | 7 807 | 29 410 862 | `10ff79914e81b51d…` |
| `persistence_state.geojson` | 119 487 tracks | 126 505 520 | `dbf04c8de308740f7846dcac3565f3eb321c56fb0a32fc7a56881597a3a0cca1` |

**Medido, e é a primeira armadilha de quem for buscar "dado real": os arquivos
publicados do site NÃO são entrada válida.** `site/public/data/alerts/run-*.geojson`
carrega os nomes curtos que `prepare_data.py` escreve (`conf`, `nat10`,
`pcount`) e **não** tem `confidence_label`, `persistence_count` nem
`lc_natural_frac_10m`. `is_strong` lê os nomes longos, então alimentar o
montador com eles daria subconjunto forte **vazio** — em silêncio, e com o
objeto cheio parecendo correto. O dado do produtor está em `alerts/` no mesmo
bucket, e é ele que tem os nomes longos.

### 4.1 A checagem cruzada mais forte deste gate

O montador aplica `site_artifact.strong_features` às feições cruas; a produção
calcula os mesmos números por um caminho completamente diferente
(`prepare_data.py`, no repositório do site). Os dois concordam:

| data | `count` verde / azul | `strong` verde / azul |
| --- | --- | --- |
| 2026-08-22 | 5 497 / 5 497 | 2 347 / 2 347 |
| 2026-08-25 | 6 762 / 6 762 | 2 547 / 2 547 |
| 2026-08-30 | 7 807 / 7 807 | 3 017 / 3 017 |

E depois, compondo o índice do site **a partir da release real viva** com
`site/scripts/site_artifact.py compose --from-dir`: **18 de 18 campos
estatísticos batem** com o `manifest.json` de produção, nas duas datas —
`count`, `area_ha`, `high`, `medium`, `low`, `first_obs`, `candidate`,
`confirmed`, `strong`. Totais: `count` 12 259, `strong` 4 894, `area_ha`
73 180,4, `pcount_max` 82, `object_base` `/data/green/`, e o validador de
schema aceita o índice escrito.

Isto é o que "rodar os vetores como gate no caminho novo, com dado de execução
real" quer dizer: 21 383 feições reais, e o caminho novo reproduz o número que
o público já vê.

### 4.2 As rodadas depositadas e a release publicada

| run id | datas reais | objetos | release |
| --- | --- | --- | --- |
| `gate-p2b-real-a` | 2026-08-22 | 4 | `rel-g1-1fb345489260784289532351887aef039345964518c981556b4a02048d16e14d` |
| `gate-p2b-real-b` | 2026-08-22, 2026-08-25 | 6 | `rel-g1-24db9555c8b2c3569418d953194622e02ebff2eae51b97d294014b3f777a6e36` |
| `gate-p2b-real-c` | 2026-08-30 | 4 | `rel-g1-2ddb10c795deb75f0b2f61a4ae349fda192baf31a2cbd310723b0c362a6670d3` |
| `gate-p2b-real-fail` | 2026-08-22 (**meia**) | 2 | nenhuma — ver §5 |

**Reenviar `gate-p2b-real-a` foi um no-op idempotente contra o R2 real**: os
quatro objetos voltaram `unchanged`, então `put_if_absent` comparou bytes e a
determinismo do montador vale contra o store de verdade, não só contra o falso.

### 4.3 O ponteiro: movido e revertido, com dado real

O ponteiro verde guarda **um passo** de história, então o estado anterior fica
registrado aqui antes de ter sido sobrescrito:

    sequence 3, action rollback, release rel-g1-ae3f6e1db152ac608f5e63d2fe2d6f4357f0f311ad5582070dfabf9e91828827
    coverage 2026-04-07 … 2026-04-10, promoted_utc 2026-09-07T22:32:54Z
    sha256 b70b27fcc44762e84f693be0b7c8a4eb9047093fb455bd70a4799add7636d219

Os movimentos, todos contra `araripe-v2-staging`:

| seq | ação | release | cobertura até |
| --- | --- | --- | --- |
| 4 | promote | A | 2026-08-22 |
| 5 | promote (supersede A) | B | 2026-08-25 |
| 6 | **rollback → A** | A | 2026-08-22 |
| 7 | promote (corrida) | B | 2026-08-25 |
| 8 | promote (corrida, supersede B) | C | 2026-08-30 |
| 9 | **rollback → B** | B | 2026-08-25 |

Cada `publish` fez publicar → verificar → mover, com `verified : every declared
object re-read and matched`. **Nenhum PR de dado, nenhum git no caminho.**
Estado final vivo: `rel-g1-24db9555…`, sequência 9, `action: rollback` — a
própria cláusula do gate.

Nota honesta: rodando localmente, `promoted_by` fica `{actor: null, run_id:
null, run_url: null, workflow: null}`. Só um run de Actions preenche isso.

## 5. Rodada falhada e rodada concorrente (item 2), executadas

### 5.1 Falhada — contra o R2 real

Uma rodada montada do dado real foi cortada por uma exceção **depois** de dois
objetos e **antes** do `ledger.json` e do `run.json` (o manifesto vai por
último, por construção). O que ficou provado, com os leitores do próprio
repositório:

* `scripts/stage_green_run.py --run gate-p2b-real-fail` → `RunRejected
  [run_manifest_absent]`, exit 1;
* `scripts/publish_green_release.py publish --run gate-p2b-real-fail` → o
  mesmo achado, exit 1. A lane maior recusa pelo mesmo motivo que a menor;
* o ponteiro vivo ficou **byte-idêntico** —
  `bdebe6d95c1d357156787a226b1375f6fee743ae041a8f5f506a1466a3ac969d` antes e
  depois;
* **nenhuma release nova**: 5 prefixos em `releases/` antes e depois;
* o azul segue inalcançável com esta identidade: `aws s3 ls s3://araripe-cogs/`
  → `AccessDenied`.

### 5.2 Concorrente — o compare-and-swap, contra o R2 real

Um job concorrente é um cuja visão do ponteiro envelheceu. Executado:

* `put_if_match` com um ETag que nunca existiu → **`PreconditionFailed`**, e a
  mensagem do próprio repositório: *"another writer won the race. Re-read and
  re-evaluate: this write is not retried, because the decision behind it was
  made about a version that is no longer live."* O ponteiro ficou idêntico
  (`bdebe6d9…`, ETag `"2a6838b20498dbe64be29c52c2116081"`);
* e com o ETag **corrente** a escrita foi aceita — então a recusa acima é a
  precondição, não uma negação genérica. As duas polaridades medidas.

### 5.3 Concorrente — política de cobertura, contra o R2 real

`publish --run proof-b-older` (cobertura até 2026-04-01) com a release real A
viva (até 2026-08-22) → **`PromotionRefused [coverage_regression]`**, exit 1, e
o ponteiro intocado. Detalhe que vale registrar: os objetos da rodada perdedora
**foram republicados** (`0 created, 3 already identical`) e verificados antes da
recusa do ponteiro. Uma rodada que perde tem release publicada e **não** fica
viva — que é exatamente o contrato, e é o oposto de expor parcial.

### 5.4 Duas rodadas, um id — e uma nuance medida

Montada uma rodada **diferente** (2026-08-30) sob o id `gate-p2b-real-a`, que
já existia com 2026-08-22 → **`ImmutableObjectConflict`**.

A recusa caiu no **`ledger.json`**, não nos objetos, porque `put_if_absent` é
por chave e as datas da segunda rodada são outras. Consequência medida: a
rodada em conflito **acrescentou 41 MiB** (dois objetos de 2026-08-30) ao
prefixo antes de colidir. E ainda assim `stage_green_run.py --run
gate-p2b-real-a` continua lendo **a mesma release**,
`rel-g1-1fb345489260784289532351887aef039345964518c981556b4a02048d16e14d`, com
o mesmo ledger, a mesma cobertura e os mesmos dois objetos declarados — porque
`run.json` é quem declara, e ele vai por último.

Ou seja: **o prefixo é imutável no que decide a release, e não é à prova de
acréscimo.** Os objetos órfãos são inertes para correção. Para higiene, não
são: `scripts/plan_retention.py` os classifica `[retain]
within_run_horizon`, igual aos legítimos — ele decide por idade de prefixo, não
por "o manifesto declara esta chave". É insumo para o package de retenção e
histórico de promoção, não bloqueio deste gate.
`test_duas_rodadas_diferentes_com_um_id_falham_fechado_e_a_release_nao_muda`
fixa a nuance, para que mudá-la seja uma decisão.

### 5.5 Uma corrida de verdade, e o que ela mostrou

Dois `publish --run` reais disparados no mesmo instante (B, até 2026-08-25, e
C, até 2026-08-30) com A viva: **os dois passaram**, serializados pelo store nas
sequências 7 e 8, e o ponteiro terminou coerente em C com `supersedes` nomeando
B na sequência 7. **Nenhum `PreconditionFailed` foi observado nesta corrida
natural** — a janela entre ler e escrever o ponteiro não se sobrepôs nesta
escala. Registrado como medido, e não como "a corrida foi ganha": o mecanismo
está provado em §5.2, com uma corrida determinística.

A corrida natural tem duas saídas seguras e nenhuma terceira: quem escreve
depois vê o ponteiro do outro e o supersede, ou é recusado por
`coverage_regression`. O ponteiro nunca fica incoerente.

## 6. Os testes determinísticos, e a mutação que cada um derruba

`tests/test_assemble_green_run.py`, **31 testes**: sem rede, sem relógio real,
sem object store, sem credencial. Reusa `tests/green_release_fixtures.py`,
`tests/fake_object_store.py` e as feições de `tests/test_run_assembler.py`.

A corrida determinística usa `StalePointerView`, que devolve ao chamador o
ponteiro que ele *leu* e delega todo o resto ao store real — a única forma de
fixar aquele entrelaçamento sem thread nem relógio. A primeira versão desse
teste errou de um jeito instrutivo, e o erro ficou fixado: um corredor que
re-promove a release que a sua visão velha já diz viva sai pelo galho
`unchanged` de `promote` e **não escreve nada** — seguro, mas não é o
compare-and-swap. A montagem que importa é a que o teste tem hoje: o corredor
promove B, a comparação de cobertura de `promote` **diz sim** (porque compara
com o que ele leu), e o ponteiro real já está em C — de modo que a escrita, se
passasse, substituiria uma release de 04-16 por uma de 04-13. A política não
pode ver isso; o `If-Match` pode.

Cada afirmação foi checada por mutação (`§6` do briefing: *pergunte sempre qual
mutação o teste derruba*):

| mutação | teste | resultado exigido |
| --- | --- | --- |
| M1 tirar a checagem de contradição `zero_alerts` | contradição | **falhou** |
| M2 devolver a varredura por glob | ledger decide as datas | **falhou** |
| M3 `zero_alerts` sem arquivo passa a ser omitida | duas coleções vazias | **falhou** |
| M4 `import config.settings` | nenhum script verde importa dotenv | **falhou** |
| M5 um **comentário** citando `config.settings` | o mesmo teste | **passou** |
| M6 tornar `put_if_match` expressável | nenhuma escrita de ponteiro | **falhou** |
| M7 afirmar o digest do estado em vez de calculá-lo | digest calculado | **falhou** |
| M8 renomear `ALERT_FILENAME` | nome é o do produtor | **falhou** |

M5 é a que importa por si: a varredura é por `ast`, então o comentário que
explica a proibição não é acusado por ela.

## 7. O que continua sem prova

* **O ponto de entrada não tem chamador automático, e não pode ter antes da
  Phase 6.** Ele consome os arquivos que uma detecção deixa em disco, e
  **nenhum workflow verde roda detecção**: `v2_candidate_replay.yml` é a sonda
  de isolamento e `v2_operational_publish.yml` começa depois do depósito. O
  único produtor dos seus insumos é `detect_gee.yml`, que é azul e congelado
  nas Fases 2B–5. Ligar o depósito a uma execução automática é requisito da
  Phase 6, não deste gate: o que o Package 2B.2C removeu do caminho de dado
  foi o pull request e o merge, não a decisão do operador de rodar.
* **A integração com o produtor 2A.6 está provada no documento, não na
  passagem.** O produtor emite bytes que a `main` aceita ponta a ponta (§3),
  mas os metadados físicos de aquisição foram declarados. Fechar isso é o
  Package 2A.6 entrar na `main` e `run_detection*` chamar o produtor — Phase 3
  em diante.
* **`--from-route` nunca correu contra HTTP de verdade.** O Worker verde de
  staging continua sem hostname; a composição do §4.1 foi por
  `--from-dir` sobre a release real baixada. Capacidade nomeada em
  `GREEN_RETENTION_AND_MIGRATION.md` §5, e este gate não depende dela.
* **O prefixo de rodada não é à prova de acréscimo** e a retenção não distingue
  chave órfã de chave declarada (§5.4).
* **O ponteiro verde não tem história durável** — um passo. Nenhuma release
  pode ser apagada até existir, e a Phase 5 tornou isso requisito e não
  prudência: um artigo cita **uma** release.
* **`promoted_by` fica nulo fora do Actions** (§4.3).
* **A corrida natural não produziu recusa** (§5.5).

## 8. Estado do gate P2B

A cláusula, parte por parte:

| parte da cláusula | estado | onde |
| --- | --- | --- |
| *a deliberately failed … green run cannot corrupt blue* | **provado** | §5.1 — ponteiro byte-idêntico, nenhuma release nova, `araripe-cogs` `AccessDenied` |
| *… or expose a partial release* | **provado** | §5.1 — as duas lanes recusam `run_manifest_absent`; o manifesto vai por último |
| *or racing green run …* | **provado** | §5.2 CAS real, §5.3 `coverage_regression` real, §5.4 identidade imutável, §6 corrida determinística |
| *a staged test release can move … its green pointer* | **provado, com dado real** | §4.3, sequências 4, 5, 7, 8 |
| *… and roll back* | **provado, com dado real** | §4.3, sequências 6 e 9 |
| *without a manual data PR* | **provado** | `publish --run` lê `runs/<id>/` do R2; `permissions: contents: read` na lane; nada de git |
| *or any production effect* | **provado** | nenhuma escrita fora de `araripe-v2-staging`; nenhum deploy, DNS, rota, binding, workflow, Environment ou objeto apagado |

**O exit gate P2B está fechado, e com ele a Phase 2B.** O Package 2B.4 era o
último package da fase; não há 2B.5 no roadmap.

O que a fase entrega, ponta a ponta e com dado de execução real: uma rodada é
montada dos arquivos que a detecção escreve, depositada num prefixo imutável,
lida de volta por uma identidade que não pode escrever, publicada e verificada
por outra que pode, e o ponteiro se move por compare-and-swap — com reversão
deliberada, sem git, sem PR e sem tocar produção.

Fora de escopo e **não iniciado**: o cutover, o desligamento do bot azul,
ligar a página a `object_base`, qualquer coisa no domínio final (Phase 6), o
replay 2026 (Phase 3), a Phase 5, a Phase 7, o histórico de promoção e
qualquer exclusão real.

## 9. Gates depois da mudança

| repositório | comando | antes | depois |
| --- | --- | --- | --- |
| backend | `python -m pytest -q` | 812 passed | **843 passed** |
| site | `python -m pytest -q` | 201 passed | **201 passed** (sem alteração) |
| site | `npm run test:worker` | 44/44 | **44/44** (sem alteração) |

`pgrep -fl workerd` → nada sobrou. Árvore limpa nos dois repositórios, com os
três untracked de dado fora do commit.

## 10. Como reproduzir

O dado real é público e não precisa de credencial:

    for d in 2026-08-22 2026-08-25 2026-08-30; do
      curl -sSo "data/alerts/alerts_$d.geojson" \
        "https://pub-5eb389cffff54421916187be69dd659b.r2.dev/alerts/alerts_$d.geojson"
    done
    curl -sSo data/persistence_state.geojson \
      https://pub-5eb389cffff54421916187be69dd659b.r2.dev/persistence_state.geojson

O ledger vem do produtor 2A.6, que não está na `main` — extraia-o sem misturar
branch:

    git archive origin/claude/phase2a6d-mapbiomas src/detection docs/contracts \
      | tar -x -C /tmp/p2a6

e conduza `ProcessingLedgerV3` com as datas reais (§3). Depois, sem credencial:

    python scripts/assemble_green_run.py plan --run <id> --ledger <ledger.json>

Para o depósito e a publicação, a identidade é o perfil AWS nomeado de
`CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md` — o segredo nunca é impresso:

    eval "$(aws configure export-credentials --profile araripe-r2-staging --format env)"
    export R2_STAGING_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
           R2_STAGING_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
           R2_STAGING_BUCKET=araripe-v2-staging AWS_REGION=auto \
           R2_ENDPOINT_URL=https://9416750169311ee4afc18a8ff3c771d4.r2.cloudflarestorage.com
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_PROFILE

    python scripts/assemble_green_run.py apply --run <id> --ledger <ledger.json>
    python scripts/stage_green_run.py --run <id>
    R2_PROMOTION_ACCESS_KEY_ID=… python scripts/publish_green_release.py publish --run <id>
