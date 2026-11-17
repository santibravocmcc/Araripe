# Estado das frentes — o que está aberto, o que fechou e como retomar

**Retrato de 2026-11-17, por volta de 14:45 UTC.** Este arquivo **não é o
plano**: o plano é o `ROADMAP.md` da `main` (registro de decisões, tópicos,
fases e portões). Aqui fica só o mapa do trabalho em curso, para que uma sessão
nova, inclusive de outra conta do Claude, sem a memória nem o histórico das
sessões anteriores, saiba o que está aberto, de quem é a vez e por onde
continuar.

Ele envelhece. **Antes de agir sobre qualquer linha, rode o comando de conferência
dela.** Se o resultado discordar, vale o que a ferramenta mostrar, e esta linha
deve ser corrigida.

Base verificada nesta escrita:

| repositório | `origin/main` |
| --- | --- |
| Araripe (este, público) | `b13cd0959bae659395b7762e4dfae49d1323cc9d` (#139) |
| observatorio-site (privado, pasta `../site`) | `f105787384bf2487631baf9bdb4367efd14bef87` (site#68) |

Nos dois repositórios não havia PR aberta nem issue aberta.

Marcas usadas na coluna "conferido":

- **17/11**: relido na ferramenta (git, `gh`) nesta escrita.
- **herdado**: tirado de um registro anterior e não medido de novo. A data é a
  do registro.

---

## 1. Como retomar numa sessão nova

1. Leia `../AGENTS.md` (workspace), este `AGENTS.md` e o `AGENTS.md` do site.
2. Em cada repositório:
   `git fetch origin && git status --short --branch && git log --oneline -5 origin/main`.
   Os checkouts locais costumam estar em branches de trabalho antigas, não na
   `main` (ver §8).
3. Leia este arquivo **da `main`**: `git show origin/main:docs/operations/ESTADO_DAS_FRENTES.md`.
4. Escolha uma linha da §2 com a vez do agente. Abra o briefing indicado, que
   também se lê da `main`. Ele traz o modelo, o esforço, o estado de partida e
   o ponto de parada.
5. Uma tarefa por sessão. A sessão termina escrevendo o briefing seguinte
   (`HANDOFF_PROMPT_METHOD.md`, versão 2) e atualizando este arquivo na mesma PR.

Limites que valem para tudo abaixo:

- A `main` do Araripe só aceita PR.
- A `main` do site faz deploy de produção a cada merge, e quem mescla é o dono.
- Nenhum agente usa credencial direta da Cloudflare.

---

## 2. Em aberto: a vez é de um agente

| frente | estado | próximo passo | briefing / prompt | conferido | conferir com |
| --- | --- | --- | --- | --- | --- |
| **C6B: a vigia que continua** (Phase 6, já fechada) | Pode abrir desde **2026-11-17**. As rodadas que ele lê existem. Depósitos: 11-05 `42042128336`, 11-09 `42644557490`, 11-12 `43240398004`, 11-16 `43891838856`. Publicações: `42043840040`, `42645922591`, `43242230079`, `43893562035`. Há um `deploy(verde)` no site para cada uma (`3394db3`, `e670290`, `71951ad`, `26e9d95`). | Abrir a sessão e ler cada rodada pelas **sete linhas do log**. Que a run diga "success" **não basta** para contar uma rodada limpa. | `docs/operations/PACKAGE_P6_WATCH_B_PROMPT.md` (Opus 5.5, medium) | 17/11, só a conclusão das runs | `gh run list -R santibravocmcc/Araripe --workflow v2_green_deposit_lane.yml -L 8` |
| **D4B: a série verde ligada às lanes e ao site** | A sessão 1 está mesclada (#138, `3a545d1`). A aba "Séries" segue parada em 2026-09-07. **As duas decisões do dono da §7 de `PHASE_D4_2026-11-03.md` foram tomadas em 2026-11-05:** (1) a série é refeita **desde janeiro**; (2) o gráfico mostra **só as imagens aceitas**, o que tira 01-02, 01-04, 01-12, 01-22 e 02-01 de 2026. Até aqui elas estavam registradas só fora do git (`../proximas-sessoes/2026-11-05/D4B_SERIE_VERDE.md`). | Primeiro medir, com **uma** data, se o Earth Engine devolve hoje o mesmo arquivo de outubro. Se não devolver, parar e levar ao dono. Não mesclar mudança no job `deposit` enquanto o C6B estiver aberto. | `docs/operations/PACKAGE_D4B_GREEN_TIMESERIES_LANE_PROMPT.md` (Opus 5.5, high), com as decisões acima | 17/11 | `git show origin/main:src/timeseries/green_rows.py \| head -3` |
| **P5.1: quadro amostral e pacote de rotulagem** (Phase 5) | O briefing está na `main` (#136, `e8d955a`). A sessão **não foi aberta**. Não depende do C6/C6B. | Reproduzir em código a conta de alocação **antes** de gravar qualquer `n`. Parar antes de qualquer revisor receber material. | `docs/operations/PACKAGE_P5_EXECUTION_PROMPT.md` (Opus 5.5, max) | 17/11 | `git show origin/main:docs/operations/PACKAGE_P5_EXECUTION_PROMPT.md \| head -20` |
| **Robô semanal do IBAMA/ICMBio** (site) | Mesclado em 06/11 (site#65, `db8b1a4`). **Nunca publicou.** As rodadas de 11-08 (`42506272912`) e 11-15 (`43747473644`) falharam na coleta do pytest: `import yaml` sem `pyyaml` instalado. O conserto foi mesclado hoje (site#68, `f105787`, Workers Builds verde) e **ainda não foi provado por uma rodada**. | Na rodada de **dom 2026-11-22, 12:00 UTC** (o GitHub costuma atrasar uma hora ou mais), conferir três coisas: o run verde; um commit `chore(ibama): embargos e fiscalização de 2026-11-22` na `main`; um deploy depois dele. Uma branch `ibama/*` com issue indica que a trava barrou a publicação, não que a falha antiga voltou. Só leitura. | o PR site#68 e `docs/integracao/PLANO_INTEGRACAO.md` do site | 17/11 | `gh run list -R santibravocmcc/observatorio-site --workflow update-ibama.yml -L 3` |

---

## 3. Em aberto: a vez é do dono

| assunto | o que falta | onde está registrado | conferido |
| --- | --- | --- | --- |
| Abrir as sessões da §2 | C6B a partir de 17/11; D4B de preferência depois do C6B; P5.1 quando quiser | os briefings | 17/11 |
| Phase 5, antes dos revisores começarem | Exigência de aprovação ética; onde fica a lista que liga revisor e código (fora do git); consentimento para crédito | `PACKAGE_P5_EXECUTION_PROMPT.md`, seção final | herdado (2026-10-31) |
| Phase 5, antes do artigo e do relatório | Vínculo dos revisores e autor correspondente; destino citável da release (Zenodo ou equivalente) | idem | herdado (2026-10-31) |
| Pontos de embargo no Monitor | O robô mantém como ponto os termos do IBAMA que só têm ponto. Mudar para "só polígono" exige uma PR nova. | descrição da site#65 | herdado (2026-11-03) |
| Tokens amplos no painel da Cloudflare | Tokens "Admin Read & Write" em todos os buckets e um MCP da Cloudflare conectado, nunca avaliados. Só o dono pode revogar ou desconectar. | `PHASE_6ZF`, §3 | herdado (2026-10-31) |
| Decisões pequenas do `ROADMAP.md` | Destino das notificações, limites de frescor, número e duração dos rollbacks | `ROADMAP.md`, seção "Small owner decisions" | herdado (2026-10-31) |
| Environment de rollback com revisor (P1 de `PHASE_6P`) | Não se achou nos docs registro de que foi criado. Confirmar com o dono. | `docs/implementation/PHASE_6P_2026-10-02.md` | herdado (2026-10-31) |
| Jogo v2 | Está no ar (site#62). Faltam: jogar uma partida inteira em cada cenário; revisão dos textos e dos números da estufa por especialista; decidir se o selo "PROTÓTIPO" fica | `../jogo/PLANO.md` (fora do git) | herdado (2026-10-31) |

---

## 4. Calendário: o que vai acontecer e o que conferir

| quando (UTC) | o quê | conferir |
| --- | --- | --- |
| seg e qui, 06:00 (costuma rodar entre 11h e 15h) | depósito e publicação verdes | o C6B; depois, `v2_green_status` diário (sete linhas `ok`) |
| ter e sex, 06:00 | robô do site (chuva e clima). Em **17/11 às 14:41 ainda não tinha rodado**; nas últimas semanas saiu entre 13h e 16h | `gh run list -R santibravocmcc/observatorio-site -L 10` |
| a cada 3 h, no minuto 41 | reconstrução do site verde (`deploy(verde)`). Mesclar no site **perto** desse minuto, logo depois de uma promoção, pode sumir com o commit que a vigia procura | o C6B lê |
| **dom 2026-11-22, 12:00** | **1ª rodada real do robô do IBAMA** | §2 |
| **qua 2026-12-02, 12:00** | rodada mensal do CAR (só a 1ª quarta do mês publica; as outras saem cedo, como em 11-11). Ao terminar, ela dispara o robô do IBAMA (`update-car.yml`, `gh workflow run update-ibama.yml`) | `gh run list -R santibravocmcc/observatorio-site --workflow update-car.yml -L 3` |
| mensal | `esa_reprocessing_watch.yml` (regime úmido do baseline). Última: 2026-11-01, `41314951306`, success | §6 |

---

## 5. Feito recentemente (desde 2026-10-26)

Cada linha foi confirmada pelo assunto do squash na `main`.

| data | repositório | o quê | squash |
| --- | --- | --- | --- |
| 2026-11-17 | site | conserto do robô do IBAMA: `pyyaml` (#68) | `f105787` |
| 2026-11-13 | ambos | arquivos de instrução depois da virada (#139 e site#67) | `b13cd09` · `5488468` |
| 2026-11-06 | site | razão social, CNPJ e página institucional (#66) | `ca766b1` |
| 2026-11-06 | site | robô semanal de embargos e fiscalização (#65) | `db8b1a4` |
| 2026-11-04 | site | 1º instantâneo publicado pelo robô do CAR | `e39264b` |
| 2026-11-03 | site | CAR pelo WFS do SICAR (#63) e robô mensal do CAR e do Sinaflor (#64) | `6b2126c` · `bf44a21` |
| 2026-11-03 | site | o Monitor absorve Alertas, M5 (#61) | `212bc1f` |
| 2026-11-03 | Araripe | D4 sessão 1: produtor da série verde, inerte (#138) | `3a545d1` |
| 2026-11-03 | Araripe | C6 encurtado: **Phase 6 fechada**, registro `PHASE_6ZP` (#137) | `390a7ad` |
| 2026-10-31 | Araripe | Phase 5: decisões (a)(b)(c), meta de precisão, briefing P5.1 (#136) | `e8d955a` |
| 2026-10-31 | site | jogo v2 (P1–P5) na `main` (#62) | `32dc712` |
| 2026-10-31 | site | verificador ao vivo pede o header de contexto ao objeto (#51) | `6626f9e` |
| 2026-10-28 | site | monitor no ar, M1–M3 (#52, #53) | `d975f00` · `fafb0b5` |
| 2026-10-27 | Araripe | aba Clima no `ROADMAP` (Phase 8, #135); registro da virada, C5 (#134) | `2949dba` · `30a0a88` |
| 2026-10-27 | site | aba Clima e robôs (#56, #57) | `cca2b14` · `fcaa081` |

O histórico anterior da Phase 6 está nos blocos datados do topo do `ROADMAP.md`
e em `docs/implementation/PHASE_6*`.

---

## 6. Backlog aprovado, sem sessão aberta

| item | estado | conferido |
| --- | --- | --- |
| Phase 7.1: CI e proteção de branches | Nenhum workflow tem gatilho `pull_request` (0 de 13 no Araripe, 0 de 7 no site). As Actions do Araripe estão **parcialmente** pinadas por SHA: `checkout` e `setup-python` na maioria, mas ainda há `checkout@v4`, `setup-python@v5` e `setup-miniconda@v3`. A proteção de branches precisa do dono. | 17/11 |
| Tópico 21A: Worker de IA | O site ainda aceita `?debug=1` público (`worker/index.js:298`), que devolve `tried: errors`. A remoção está adiada pelo `ROADMAP` até a IA virar recurso promovido; a decisão é do dono. | 17/11 |
| Tópico 21B: CSP e cabeçalhos | Nenhum `Content-Security-Policy` no site; adiado | 17/11 |
| Pacotes pequenos do site, da `PHASE_6_CUTOVER_2026-10-27.md` | Aviso de tamanho antes da visão completa (mediana de 26 MiB); a frase da automação na página; PNGs de chuva iguais com `max_mm` 13,8; 404 de `figures/rain-2026-04-24.png` | herdado (2026-10-31) |
| Regime úmido do baseline 2.0.0 | `mixed_lineage_pending_esa_reprocessing`; espera o reprocessamento da ESA chegar a 90%. Em 2026-09-06 estava em 25–34%; o valor atual não foi medido | herdado; roteiro em `docs/operations/WET_SEASON_REBUILD_PROMPT.md` |
| `STAGING_LIMITER` | Declarado e não aplicado; esperar a forma real do tráfego | herdado (`PHASE_2B4A`) |
| Alertas antigos no git do site | 42 arquivos, 247 MiB em `public/data/alerts`, servidos em `?dados=azul`. Não apagar nem reescrever a história (`ROADMAP.md`, seção 7.6) | herdado (2026-10-31) |
| Diferidos sem gatilho | Extent formal (tópico 3), BFAST, Sentinel-1, baselines Landsat/HLS, referência de omissão | `docs/implementation/PENDING_CAPABILITIES.md` |

---

## 7. Fora do git (pastas do workspace)

Estas frentes vivem na pasta comum do workspace, que não é repositório. Leia o
`README` de cada uma.

- `../proximas-sessoes/`: prompts prontos para colar, por data. O de
  `2026-11-05/D4B_SERIE_VERDE.md` é o que leva as decisões da D4B (§2).
- `../painel/`: painel local de acompanhamento da Associação, com as fases 1–3
  feitas. O próximo passo depende do uso numa reunião real. Ver `painel/README.md`.
- `../institucional/`, `../projetos/`, `../oportunidades/`: captação, governada
  por `institucional/README.md`.
- Limpeza de disco: o `.git` do Araripe caiu de 18 GB para 1,6 GB em
  2026-11-06. Ainda esperam o dono:
  - `data/baselines_v2/2.1.0` (13 GB): só apagar depois de conferir os 72
    objetos no bucket pela CI.
  - `data/landcover/updated` (7,1 GB): as URLs de origem deram 403.
  - Três objetos LFS que não estão no remoto.
  - Os caches `site/.cache/alerts*`.
  - A pasta pessoal do replay 2026 (26 GB). Recomendação: manter até a D4B
    terminar e depois apagar.

---

## 8. Resíduos: não construir em cima deles

- Os dois repositórios mesclam por squash. Branches como
  `claude/reanotacao-2025` (o checkout local do Araripe, já entrou como #101),
  `jogo/v2-*` (checkout local do site, entrou como #62), `claude/car-*`,
  `claude/monitor-*` e `claude/ibama-*` aparecem "à frente" da `main`, mas o
  conteúdo delas já entrou. Decida por conteúdo ou pelo assunto do squash
  (`git log origin/main --grep '(#N)'`), nunca por ancestralidade.
- O Araripe tem um `stash@{0}` antigo ("WIP on main: e3a1ffc"). Não foi
  avaliado; não o descarte sem olhar.
- Há worktrees de sessões antigas em `/private/tmp/claude-502/...` (por
  exemplo, o do conserto do IBAMA). Rode `git worktree list` e `git status` em
  cada um antes de remover.

---

## 9. Como manter este arquivo

- Atualize na mesma PR que fecha ou abre uma frente: mude a linha, a coluna
  "conferido" e a data do topo, e mova o que fechou para a §5.
- Copie identificadores da ferramenta (`git rev-parse`, `gh run view`). Não os
  complete de memória.
- Não repita decisões do `ROADMAP.md`; aponte para elas. Uma decisão do dono que
  ainda não tem lugar no repositório entra aqui até ganhar um, com a data e
  onde estava antes.
- Este repositório é público: nada de dado pessoal, nome de pessoa ou assunto
  de fora do projeto.
