# Phase 6 — a folha de execução da virada, contra o presente

Escrito em 2026-10-10, ao fim da sessão do status e frescor por produto
([`PHASE_6Y`](../implementation/PHASE_6Y_2026-10-10.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: max**
>
> Por quê: com o item 6, a §4.1 de [`PACKAGE_P6_PROMPT.md`](PACKAGE_P6_PROMPT.md)
> acabou, e o que resta é a virada — a primeira coisa que muda o que o público
> vê. O texto das §4.2–§4.5 é de 2026-09-17 com seis acréscimos datados, e
> metade das premissas dele mudou (bucket decidido, autoridade decidida,
> contexto e fontes publicados, status pronto). O erro plausível é executar um
> passo na ordem do texto antigo; o outro é uma folha que parece completa e
> esquece um passo que só o dono pode dar. **Esta sessão não muta produção.**

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C site fetch origin && git -C site rev-parse origin/main
    gh pr list -R santibravocmcc/Araripe --state all --limit 4 --json number,state,mergedAt
    gh pr list -R santibravocmcc/observatorio-site --state all --limit 6 --json number,state,mergedAt

- `Araripe#112` (status e resumo da rodada) e a PR de registro da PHASE_6Y na
  `main` do backend: `git show origin/main:scripts/green_status.py` existe, e
  `docs/implementation/PHASE_6Y_2026-10-10.md` tem o §7.
- `observatorio-site#46` mesclada (2026-10-10); `#42` em rascunho; `#21`
  "não mesclar antes da Phase 6".
- Worktree com os cinco caminhos de dado ligados (memória
  `worktree-novo-nao-tem-o-untracked`). Suíte: conda `araripe`. Base medida
  depois da PR de registro da PHASE_6Y: **2818** (2813 da `#112` + 5
  parametrizados sobre este briefing).
- **Primeiro passo de verdade:** dispare `v2_green_status.yml` da `main` e
  leia o resumo. É só leitura e é a fotografia de onde a virada parte.

## 2. O que já foi verificado, para o executor não refazer

- **Status lido ao vivo em 2026-10-10** (run 38060470700): os sete produtos
  `ok` — alertas até 2026-10-04, nada depositado esperando, última tentativa
  `no_acquisition` em 2026-10-07, contexto seq. 2 e fontes seq. 1 servidos.
  O batimento ficou byte-idêntico depois da leitura.
- **Decidido, com a base:**
  - bucket: opção (a), o staging vira o definitivo na virada — dono,
    2026-09-30, `PACKAGE_P6_PROMPT.md` §3;
  - publicação sem revisor, rollback no `v2-promotion` —
    `config/phase6_publication_authority_v1.json`, dono, 2026-10-02;
  - contexto e fontes depois de cada promoção, na mesma lane
    (`v2_operational_publish.yml`, jobs `context` e `sources`) — `#109`, `#110`;
  - ordem dos deploys do site (`site#42`: compor no build atrás de
    `COMPOR = False`, reconciliador, recusa sem azul) — PHASE_6U.
- **Limites de idade decididos pelo dono em 2026-10-10** (PHASE_6Y §9): última
  tentativa > 5 dias, última data olhada > 21 dias, data mostrada sem limite,
  espera entre lanes decidida na virada. **Já codificados no backend** — a lane
  de status falha com `late`, e vai acusar a automação atrasada a partir de
  2026-10-13 porque o depósito é manual até a virada. Falta o aviso na página
  (§3.1).
- **O azul está parado desde 2026-09-03** (`LegacyPersistenceStateError`); o
  robô do site falha no job `alertas` desde 02/10 recusando uma release de 31
  dias. O conserto é a virada, não um patch.

## 3. A tarefa

**Única tarefa: escrever a folha de execução da virada —
`docs/operations/PHASE_6_CUTOVER_RUNSHEET.md` — como uma lista ordenada de
passos verificáveis contra o presente, cada um com quem executa, a aprovação
que exige, a checagem antes e depois, e o caminho de volta. Nenhum passo de
produção é executado nesta sessão.**

1. **Reler as §4.2–§4.5 e cada acréscimo datado** e marcar, passo a passo, o
   que envelheceu (com a evidência por conteúdo, não por título de PR).
2. **Fechar as lacunas que o texto antigo não tinha**, cada uma como passo ou
   como pergunta ao dono:
   - quem dispara a promoção depois do depósito quando a lane de depósito
     ganhar agenda (§4.5) — encadeada, agendada separada, ou manual — e o que
     isso faz com o item (d) dos limites;
   - a agenda da lane de status, e o que ela faz quando um limite estoura;
   - a revogação da chave local de staging e a reescrita de
     `CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md` (condições da opção (a));
   - a implantação do servidor verde: só da máquina do dono
     (`site/scripts/green_worker.sh deploy GREEN-ONLY`), porque o lugar protegido
     do repositório do site não tem revisor (memória `site-main-nao-tem-environment`);
   - `FONTE_PADRAO` para o verde junto com os textos estáticos que ainda
     descrevem o azul anotado com 2023 (§4.4, acréscimo de 2026-10-07 à noite);
   - `site#21` depois do passo 2 da §4.4; a semente da agenda a partir da
     marca-d'água e a fila desde 2026-10-05.
3. **Para cada passo, a checagem é um comando ou uma leitura**, não uma frase
   — de preferência `v2_green_status.yml` (backend) e
   `site/scripts/verify_green_route.sh` / `verify_green_route_remote.sh`,
   que já existem.

### 3.1 Antes da folha: o aviso "dados atrasados" na página

O dono decidiu que a página diz "dados atrasados" **só** quando a última data
olhada (`coverage.last_observed_on` do índice verde, não o último `runs[]`)
passa de 21 dias. Site, atrás de `?dados=verde`, PR **não mesclada**. Nenhum
outro aviso: a automação parada já tem o texto da 3ª data e não muda.

**Fora de escopo:** executar qualquer passo de produção; criar, renomear ou
reconfigurar Environment; ligar cron em lane verde; Fase 5.

## 4. Decisões de escopo já tomadas, com a base

- **Nenhuma lane verde tem cron antes da virada** — Package 2B.0, teste.
- **Nada é apagado** — `PACKAGE_P6_PROMPT.md` §5; desabilitar o acesso
  público de `araripe-cogs` é configuração reversível, e o hostname exato tem
  de estar anotado antes.
- **Status não é documento gravado** — PHASE_6Y §2.1.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- **A `main` do site faz deploy de produção.** Não mescle PR do site.
- Produção é só leitura até o dono aprovar, passo a passo, cada mutação.
- **Nenhum Environment é criado, renomeado ou reconfigurado por agente**;
  escrever `environment:` com nome inexistente CRIA um.
- `detect_gee.yml` e `update_data.yml` nunca são disparados.
- Claude não recebe credencial de control-plane da Cloudflare; o broker só
  fecha.

## 6. Armadilhas já pagas — não redescobrir

- **Cada promoção some da página até o site reconstruir** — o índice é de
  build; por isso o reconciliador da `site#42`.
- **Um run pendente num grupo de concorrência é cancelado** quando outro entra
  na fila (PHASE_6X §2).
- **Segredo de Environment não chega a um workflow chamado** — `#102`/`#109`.
- **Um deploy com `workers_dev: false` desliga a rota**: implantar antes de
  abrir (memória `araripe-portao2-nao-precisa-do-broker`).
- **A data mostrada fica 30 dias parada na chuva** — um limite sobre ela
  alarma todo verão (PHASE_6Y §1).
- Uma varredura de texto pega comentário e docstring — use a AST, ou
  `executable_lines()` nos workflows.

## 7. Estado que o package herda

- Ponteiro verde seq. 18 (107 datas até 2026-10-04); contexto e fontes
  publicados para ele; nada depositado esperando.
- Lane de status manual e só leitura; resumo de rodada na lane de depósito.
- `observatorio-site#42` em rascunho; `#21` em rascunho.
- O azul parado desde 2026-09-03.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. Os limites que você escolheu já estão valendo na verificação do GitHub;
falta só o aviso "dados atrasados" na página, que a próxima sessão faz.

### O que você precisa fazer

1. **Nada agora.** Saiba só que, a partir de segunda (13/10), a verificação
   do GitHub vai acusar a coleta como parada — porque até a virada ela só roda
   quando alguém aperta o botão. É o aviso funcionando, não um problema novo.

### Tem algo preocupante?

Não. O sistema antigo segue parado desde setembro e o robô do site segue
recusando publicar dado velho, que é o comportamento certo até a virada. O
aviso de coleta parada que vai aparecer na segunda é esperado.

### O que ainda falta no caminho

- **A folha da virada** — a próxima sessão: cada passo da troca, na ordem, com
  quem faz, quem aprova e como volta atrás. Nada muda para o público nela.
- **A virada** — executar a folha, com a sua aprovação em cada passo que mexe
  no site público.
- **Fase 5** — a validação independente.
