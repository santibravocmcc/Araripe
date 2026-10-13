# Phase 6 — a agenda verde, em PR que só é mesclada no passo B6

Escrito em 2026-10-13, ao fim da sessão da rota de produção
([`PHASE_6ZA`](../implementation/PHASE_6ZA_2026-10-13.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: é o passo A5 de
> [`PHASE_6_CUTOVER_RUNSHEET.md`](PHASE_6_CUTOVER_RUNSHEET.md) — workflows que,
> depois do merge, rodam sem clique de ninguém. O erro plausível é uma
> promoção encadeada que roda quando a rodada **não** depositou, ou um teste de
> "nenhuma lane verde tem cron" trocado por um que aceita qualquer cron.
> **Esta sessão abre a PR e não a mescla**: o merge é o passo B6, com o dono.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/operations/PHASE_6_CUTOVER_RUNSHEET.md | grep -n "DECIDIDA"
    git -C Araripe show origin/main:docs/implementation/PHASE_6ZA_2026-10-13.md | head -5

- D1, D2 e D3 decididas (bloco "DECIDIDAS pelo dono em 2026-10-13" na §3 da
  folha): **D1 = promoção encadeada por `workflow_run`**; **D2 =
  `deposits.unpublished` pendente por mais de 1 dia é `late`**; **D3 = lane de
  status todo dia às 12:00 UTC, falhando em vermelho**. Se o texto não estiver
  lá, pare e pergunte.
- Worktree com os cinco caminhos de dado ligados (memória
  `worktree-novo-nao-tem-o-untracked`). Suíte do backend com o conda
  `araripe`. Conte os testes na base antes de mudar qualquer coisa.

## 2. O que já foi verificado, para o executor não refazer

- **Nenhuma lane verde tem `schedule:` hoje**, e três testes o afirmam:
  `tests/test_workflow_lanes.py::test_green_lanes_cannot_inherit_a_schedule`,
  `tests/test_operational_publish_lane.py::test_no_green_lane_can_inherit_a_schedule`,
  `tests/test_green_deposit_lane.py::test_manual_only_read_only_and_unscheduled`
  e `tests/test_green_status.py::test_the_lane_is_manual_unscheduled_read_only_and_joins_no_queue`.
  O A5 os troca pela **lista exata** das lanes que passam a ter cron, com o
  cron exato — nunca por "qualquer cron é aceito".
- `v2_green_deposit_lane.yml` já diz, no comentário do topo, que `chain=head`
  é "o que um schedule usará" e que o guarda
  `github.event_name == 'workflow_dispatch'` dos jobs muda junto. Um evento
  agendado não carrega `inputs`: o caminho agendado tem de resolver `chain` como
  `head` sem ler input nenhum.
- `tests/test_workflow_lanes.py::test_blue_detection_schedule_is_unchanged`
  prende o cron azul; o `detect_gee.yml` não muda. **O cron verde de depósito
  é o mesmo dele (`0 6 * * 1,4`)**, e os dois rodam juntos até o passo C1. O
  azul falha cedo, por contrato, com `LegacyPersistenceStateError` desde
  2026-09-03; meça se os dois disputam algo (fila de concorrência, cota do
  GEE) antes de afirmar que não.
- **Uma rodada de depósito pode terminar `success` sem depositar nada**: o
  resumo de cada rodada (`PHASE_6Y`) e o batimento registram
  `no_acquisition`. A promoção encadeada de D1 tem de saber se **esta** rodada
  depositou — e `workflow_run` só entrega a conclusão do run, não o resultado.
  Desenhe o sinal (artefato, saída lida pela API, ou a própria lane de
  promoção recusando com `unchanged` quando a cabeça já é a promovida) e prove
  com uma rodada sem aquisição.
- `workflow_run` roda na branch padrão, e o Environment `v2-promotion` só
  aceita a `main` (memória `araripe-lanes-verdes-e-v2-staging`). **Segredo de
  Environment não chega a um workflow chamado** sem os `secrets` do chamador, e
  `secrets: inherit` levaria as chaves azuis (memória
  `segredo-de-environment-em-workflow-chamado`): o job da promoção liga o
  `v2-promotion` ele mesmo.
- `scripts/green_status.py` não dá idade a `deposits.unpublished` hoje; D2 é
  código novo, com o limite de 1 dia ao lado dos de 5 e 21 dias
  (`PHASE_6Y` §9; `#114`).
- **Nunca nomeie um Environment que não existe** — o GitHub cria um sem
  proteção (memória `araripe-nunca-nomear-environment-inexistente`). Meça com
  `gh api repos/santibravocmcc/Araripe/environments` antes de escrever
  `environment:`.

## 3. A tarefa

**Única tarefa: o passo A5 da folha, em uma PR do backend, não mesclada.**

1. `v2_green_deposit_lane.yml`: `schedule: - cron: '0 6 * * 1,4'`; o guarda
   dos jobs aceita `schedule` (e só ele, além de `workflow_dispatch`); o evento
   agendado roda como `chain=head`.
2. A promoção encadeada (D1): `v2_operational_publish.yml` ganha
   `workflow_run` sobre a conclusão da lane de depósito, roda **só** quando a
   rodada depositou, e promove `source=chain` — com os jobs
   `stage,promote,context,sources` que já existem.
3. `v2_green_status.yml`: `schedule: - cron: '0 12 * * *'` (D3), falhando em
   vermelho quando um limite estoura.
4. `green_status.py`: o limite (d) de D2.
5. Os testes de "nenhuma lane verde tem cron" viram a lista exata, lida por
   `executable_lines()` nos workflows — nenhum cron além dos esperados.
6. Atualizar o passo A5 da folha com o número da PR.

**Fora de escopo:** mesclar a PR (é o B6); disparar qualquer lane com efeito
(depósito, promoção); A4 (rebase das PRs do site — sessão própria, depois que o
dono mesclar a `site#47`); o reconciliador do site (`green_site_rebuild.yml`,
na `site#42`, passo B2); Fase 5.

## 4. Decisões de escopo já tomadas, com a base

- **Nada é apagado** — `PACKAGE_P6_PROMPT.md` §5.
- **Nenhuma publicação tem revisor** — `config/phase6_publication_authority_v1.json`
  (dono, 2026-10-02).
- **`FONTE_PADRAO` continua `'azul'`** até o B5.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- A `main` do backend é só por PR; nunca push direto, nunca ator de bypass.
- `detect_gee.yml` e `update_data.yml` nunca são disparados nem editados.
- Nenhum Environment criado, renomeado ou reconfigurado por agente.
- Claude não recebe credencial de control-plane da Cloudflare.
- O merge desta PR liga execução sem clique: **só o dono, no B6**.

## 6. Armadilhas já pagas — não redescobrir

- Varredura de texto pega comentário: use a AST ou `executable_lines()`; e um
  comando com continuação `\` é uma linha só para o shell.
- Uma varredura de mutação: um backup por mutação, restaurado e conferido por
  sha256 antes da seguinte; limpe `__pycache__` (memória
  `varredura-de-mutacao-e-o-cache-de-bytecode`).
- `git -C <repo> worktree add <caminho relativo>` resolve o caminho **dentro**
  do repositório: use caminho absoluto.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório.
- `<<EOF` não citado executa os backticks do corpo: escreva a mensagem num
  arquivo e use `git commit -F`.

## 7. Estado que o package herda

- `observatorio-site#48` em rascunho: a rota no Worker de produção e o
  verificador ao vivo (A2+A3), para o B1. Sem conflito com a `site#47`.
- `site#47` aberta; `site#42` e `site#21` em rascunho e em conflito com a
  `main` (A4).
- Ponteiro verde seq. 18 (`rel-g3-76601bbf…`, 107 datas até 2026-10-04); a
  fila de depósito desde 2026-10-05 cresce um dia por dia (A9 a drena na
  véspera).
- O azul parado desde 2026-09-03. A lane de status acusa a automação atrasada
  desde 2026-10-13T21:19:55Z — esperado até a virada.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. A mudança que faz o site do domínio final servir os dados novos está
escrita e testada, e o verificador que vai conferir isso no dia da virada
também. Nenhuma das duas foi publicada.

### O que você precisa fazer

1. **Mesclar o aviso "dados atrasados" no site**, quando quiser — ele só
   aparece com a chave de teste. Pode esperar, mas destrava a próxima
   arrumação das mudanças antigas do site.
2. **Não mesclar a mudança da rota de produção agora.** Ela está em rascunho
   de propósito: mesclar é publicar no site real, e isso é um passo do dia da
   virada, com você.

### Tem algo preocupante?

Uma coisa pequena, que só o dia da virada responde: não dá para saber antes se
o sistema de publicação da Cloudflare aceita ligar o armazenamento de dados ao
site. Se não aceitar, a publicação falha e o site atual continua no ar, sem
dano — mas a virada para nesse passo até resolver.

### O que ainda falta no caminho

- **A agenda automática** — a próxima sessão: deixar escrito, sem ligar, o
  que faz o sistema novo rodar sozinho duas vezes por semana e avisar quando
  atrasar.
- **Arrumar as mudanças antigas do site** — depois que você mesclar o aviso.
- **Preparar a véspera** — trocar a chave de teste, revogar a chave local
  antiga, processar os dias acumulados.
- **A virada** — executar a folha, com a sua aprovação em cada passo que mexe
  no site público.
- **Fase 5** — a validação independente.
