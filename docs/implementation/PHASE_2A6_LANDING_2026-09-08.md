# Landing do Package 2A.6 na `main` — 2026-09-08

**Base verificada:** `origin/main` em `1e97f5768e2665e9370e542eacb587d0749dfd6c`
**Branch científica:** `claude/phase2a6d-mapbiomas` em `64fd781f1551a45914a7db32960b923c05056955`
**Merge base:** `adf570f05d8240b1a1993630fcb60be280cd2710`
**Gate:** 1569 passed (`main` tinha 851; o conjunto da branch, 842 — não eram
comparáveis, porque as duas árvores tinham arquivos de teste diferentes)

O roadmap não era ambíguo: *"Package 2A.6 may run in parallel with Phase 2B, but
**must close before Phase 3**."* Este documento registra o landing e o estado do
exit gate P2A.

---

## 1. A afirmação do briefing anterior que estava errada, e eu a escrevi

O briefing dizia que um merge ingênuo apagaria 93 arquivos, 13 deles o
`src/publication/` inteiro, e concluía **"isto não é um merge"**. O número vinha
de `git diff origin/main <branch>` — um diff de **dois pontos** entre as pontas.
**Não é o que um merge nem uma pull request aplicam**, e a conclusão que ele
sustentava era falsa.

Medido, e é o oposto:

| medida | valor |
| --- | --- |
| arquivos que a `main` tem e a branch não | **97** (eram 93 quando o briefing foi escrito) |
| desses, quantos existiam no **merge base** | **0** |
| quantos sobrevivem ao merge de três vias | **97 de 97** |
| arquivos apagados pelo commit do landing | **0** |
| arquivos sob `src/publication/`, workflows verdes ou `docs/contracts/phase2b/` **modificados** | **0** |

A branch nunca apagou nada. A `main` acrescentou aqueles 97 arquivos **depois**
da divergência, e o merge de três vias os preserva porque a branch não tem
deleção para contribuir. O `git diff` de dois pontos mostra "o que difere entre
duas pontas", que é uma pergunta diferente de "o que este merge faz".

**A lição, e ela é reutilizável:** para saber o que um merge faz, calcule o
merge — `git merge-tree --write-tree`, que não toca a árvore de trabalho. Um
diff entre pontas não responde essa pergunta, e responde algo parecido o
bastante para convencer.

## 2. O risco real era o oposto do temido, e silencioso

Os dois lados acrescentaram, **cada um por sua conta**, uma função
`load_persistence_state` em regiões **diferentes** de
`src/detection/persistence.py`. Medido por `ast`:

| árvore | definições de `load_persistence_state` | classe de erro |
| --- | --- | --- |
| merge base | **0** | nenhuma |
| `main` | 1 (Package 2B.1) | `PersistenceStateError` |
| branch 2A.6 | 1 (Package 2A.1) | `LegacyPersistenceStateError` |
| **merge automático** | **2** | as duas |

Git não reportou conflito, porque as regiões não se sobrepõem. Python usa a
**última** definição, então a da `main` ficou inalcançável — e a da `main` era o
fail-closed escrito **depois de um incidente de produção**, contra um estado
ilegível virar estado vazio em silêncio.

Nenhum marcador de conflito apontou isso. Nenhum teste da `main` que exercitasse
a função **pelo nome** falharia, porque o nome resolve — para a outra função.
O que o revelou foi ler a árvore sintática do arquivo mesclado.

### A resolução, unificando em vez de escolher um lado

```
PersistenceTransitionError(RuntimeError)
└── PersistenceStateError          # existe e não pode ser confiado
    └── LegacyPersistenceStateError  # não pode ser confiado PORQUE é geração anterior
```

A herança é semanticamente honesta — um estado de geração anterior **é** um
estado que existe e não serve — e faz o `except PersistenceTransitionError` de
`run_detection_from_gee.py` cobrir os dois casos sem nomear ambos.

Um `load_persistence_state`, três saídas: `None` para ausente (primeira
execução, contrato do 2B.1), `PersistenceStateError` para ilegível,
`LegacyPersistenceStateError` para geração anterior — com a lista de colunas
faltantes na mensagem, porque quem for reconstruir precisa dela.

E os dois chamadores **deixaram de checar `state_path.exists()`**: o loader é a
única autoridade sobre "ausente". Duas checagens de existência são duas
respostas possíveis para a mesma pergunta.

## 3. Um achado científico, registrado em vez de apagado

`test_last_seen_can_move_backwards` — o teste que a `main` ganhou depois do
incidente de 2026-09-07 — passou a **falhar**, com `OutOfOrderAcquisitionError`.

**Não é regressão.** O estado determinístico do 2A.6 mantém uma marca-d'água e
recusa a aquisição que não é mais nova que ela. O cenário que produzia
`last_seen` para trás — uma rodada posterior casando a track numa data mais
antiga, dentro da janela de 16 dias — deixou de ser aceito. A rodada para, em
vez de reescrever a track. Preenchimento retroativo passa a exigir geração nova.

**A consequência, e é o ponto:** `scripts/r2_state.py` continua tolerando
`first_seen > last_seen` como *oddity* e não como erro — mas o **motivo mudou**.
Não é mais *"o produtor não promete"*; é ***"o produtor promete daqui para
frente, e o estado vivo é anterior à promessa"***. As linhas que o incidente
produziu estão no estado de produção. Reapertar aquela checagem quebraria nelas,
e exige reconstruir o estado primeiro — Phase 4. **Não foi reapertada aqui.**

Reescrito como
`test_uma_aquisicao_fora_de_ordem_e_RECUSADA_pelo_modelo_deterministico`, com o
registro inteiro do incidente na docstring, porque a próxima pessoa a olhar
aquela validação precisa dele.

### Um segundo teste que passava pelo motivo errado

`test_valid_state_round_trips` afirmava `n_sightings == [3, 17]` sobre um estado
montado **à mão** com a forma pré-2A.6. Era exatamente isso que o fazia passar
sobre um esquema que o contrato já não aceita: o teste afirmava o esquema que ele
próprio inventava. Agora `sample_state()` é produzido por `update_tracks` — o
produtor real — e a afirmação é a **propriedade** (ida e volta é identidade), não
números escolhidos. E ganhou o par que faltava:
`test_o_estado_legado_FALHA_FECHADO_em_vez_de_ser_lido`.

## 4. Os dois `ROADMAP.md` eram documentos diferentes — medido

Zero sobreposição de conteúdo:

| | seções |
| --- | --- |
| `main` | BFAST, Sentinel-1 SAR, baselines por sensor, referência de omissão, Package 2B.0, incidente da lane de séries, recontagem de persistência |
| branch | propósito, ledger de decisão, estrutura de dependência, roadmap de execução, portões, cota, diferidos, decisões do dono |

**Nenhuma em comum.** Resolvido preservando os dois:

- `ROADMAP.md` passa a ser **o plano**, com um bloco datado no topo listando o
  que fechou desde a linha de base de 2026-08-11. As linhas
  `Implementation status` **não foram reescritas** — descrevem aquela data, e o
  bloco diz isso em vez de eu reescrever package por package e errar um;
- o conteúdo que estava na `main` foi para
  [`PENDING_CAPABILITIES.md`](PENDING_CAPABILITIES.md), com cabeçalho de
  procedência.

**A armadilha dos dois documentos com um nome deixa de existir.** Ela está
registrada no `AGENTS.md` do workspace por ter causado trabalho duplicado.

## 5. Os outros conflitos, e por que cada um

| arquivo | resolução | base |
| --- | --- | --- |
| `AGENTS.md`, `CLAUDE.md`, skill de handoff | fica a da `main` | medido por linha substantiva normalizada: a branch tem **zero** seção e **zero** linha que a `main` não cubra. As 3 que a varredura acusou eram o mesmo parágrafo com quebra diferente |
| `environment.yml` | **união** | a `main` pedia `pyyaml` e `jsonschema`, a branch `pillow`. O comentário da `main` já antecipava esta convergência por escrito |
| `PHASE_2B0_2026-08-11.md` | fica a da `main` | é o registro do que aconteceu **na** `main` (PR #10) |
| imports de `run_detection*.py` | união + as guardas de `persistence_mode` da branch | nada removido de nenhum lado |

## 6. A prova mecânica, porque o briefing pediu prova e não argumento

`tests/test_landing_preserves_both_sides.py`, 14 testes:

- os **13** módulos de `src/publication/` pelo nome, **e a contagem** — um
  `glob` que só contasse passaria se alguém trocasse um módulo por outro;
- os 3 workflows verdes, inclusive o broker protegido;
- os 7 scripts operacionais da Phase 2B;
- os vetores de conformidade;
- e o que teria pegado a colisão: **nenhum módulo de `src/` ou `scripts/` define
  o mesmo nome de topo duas vezes**, lido por `ast` e não por texto — uma
  varredura textual acusaria a própria docstring que explica a proibição.

### Mutação, três vezes

| mutação | resultado |
| --- | --- |
| reintroduzir a definição duplicada | falha **só** `test_nenhum_modulo_define_o_mesmo_nome_de_topo_duas_vezes` |
| apagar `src/publication/retention.py` | falham **só** os dois testes de módulo |
| apagar `cloudflare_green_control.yml` | falha **só** o teste daquele workflow |

## 7. O item 3 do escopo NÃO foi entregue, e a medição explica por quê

O escopo pedia **fazer o caminho de detecção emitir o ledger v3** que o depósito
de rodada consome. Não foi feito, e a razão não é falta de tempo — é
sequenciamento, e a medição mudou o meu entendimento do problema.

**O que existe:** `src/detection/ledger_v3.py` (`ProcessingLedgerV3`) e
`src/detection/composition_run_v3.py` (`CompositionRunV3`), que já registra as
linhas terminais e aceita as linhas de detecção do chamador. A máquina está
pronta.

**O que falta é o insumo.** `ProcessingLedgerV3` exige, por aquisição, o
**datatake físico**: `platform`, `datatake_id`, `acquisition_timestamp_utc`.
Medido, contando ocorrências de `DATATAKE_IDENTIFIER`/`SPACECRAFT_NAME`/
`platform` nos scripts de export:

| script | ocorrências |
| --- | --- |
| `scripts/build_baseline_v2_gee.py` (2A.6C) | **80** |
| `scripts/build_detection_gee.py` | **0** |

O export de **baseline** já coleta esses campos, e o mecanismo é proven: lê
`DATATAKE_IDENTIFIER` e `SPACECRAFT_NAME` das propriedades da cena, normaliza
com `normalize_platform`, e deriva o timestamp de
`datatake_id.split("_")[1]` como `%Y%m%dT%H%M%S`. O export de **detecção** emite
só identidades `acquisition-v1` (`acquisition_id`, `identity_inputs_sha256`) e
**nenhum campo físico**.

Foi por isso que o gate P2B declarou os metadados à mão, e por isso o registro
dele diz *"provada no documento, não na passagem"*.

### O achado de sequenciamento

`scripts/build_detection_gee.py` é **passo manual de Cloud Shell** — nenhum
workflow o roda, verificado. Então **editá-lo não é mudança de runtime azul**, e
eu poderia fazê-lo. Mas:

> **A mudança só afeta exports futuros. Ela não pode consertar retroativamente
> um composto já exportado, e é de composto exportado que a detecção vive.**

Portar os ~20 linhas hoje produziria um produtor de ledger sem insumo válido:
todo composto de 2026 em disco foi exportado sem os campos físicos. O momento em
que a mudança se paga é o **re-export da Phase 3/4**, que reprocessa o ano
inteiro de todo modo — e ali ela é obrigatória, não opcional.

**Recomendação registrada:** o porte entra como **pré-requisito do export da
Phase 3**, não como conserto local agora. Um produtor que só pode ser exercido
contra insumo que ainda não existe seria código não verificado no único caminho
que precisa estar certo na hora do replay. E não tenho como validá-lo contra o
GEE nesta sessão.

## 8. Estado do exit gate P2A

O exit gate P2A — *"o portão de política de geração de candidatos está
fechado"* — foi declarado fechado ao fim do Package 2A.6 na branch científica. O
que este landing muda é **onde** ele está: o código, os contratos, os testes e
os registros das Fases 0, 1 e 2A.1–2A.6D estão na `main`.

**A pré-condição da Phase 3 está satisfeita**, com uma ressalva nomeada: o item
7 acima. O replay da Phase 3 tem de carregar o metadado de datatake no export,
senão a Phase 4 produz um candidato sem ledger produzido por execução.
