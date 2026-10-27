# Phase 6 — C6: duas semanas de vigia

Escrito em 2026-10-27, logo depois do C5
([`PHASE_6_CUTOVER_2026-10-27.md`](../implementation/PHASE_6_CUTOVER_2026-10-27.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: é leitura de logs e um registro, sem escrita em nada que roda. O
> risco é concluir pela conclusão de uma run em vez das sete linhas do log
> dela, ou contar uma rodada que não houve.

**Quando abrir:** a partir de terça 2026-11-10, depois do status de segunda
2026-11-09 (o cron das 12:00 UTC tem rodado por volta das 16:30–18:30Z). As
quatro rodadas são as de **qui 2026-10-29, seg 11-02, qui 11-05 e seg 11-09**
(depósito `0 6 * * 1,4`). As runs ficam no GitHub; uma sessão só no fim lê
todas. **Abra antes** se o dono receber o e-mail de um workflow agendado que
falhou: aí a sessão lê a falha e para.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6_CUTOVER_2026-10-27.md | head -5
    gh workflow list -R santibravocmcc/Araripe --all --json path,state
    gh run list -R santibravocmcc/Araripe --workflow v2_green_deposit_lane.yml -L 8 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/Araripe --workflow v2_operational_publish.yml -L 8 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/Araripe --workflow v2_green_status.yml -L 20 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/observatorio-site --workflow update-data.yml -L 6 --json databaseId,event,conclusion,createdAt,headSha
    gh run list -R santibravocmcc/observatorio-site --workflow green_site_rebuild.yml -L 40 --json databaseId,event,conclusion,createdAt

- Esperado: `PHASE_6_CUTOVER_2026-10-27` na `main` (se não estiver, a PR
  do C5 não foi mesclada: pare e diga ao dono); `detect_gee.yml`
  `disabled_manually`, as outras 14 `active`.
- Ponto de partida: ponteiro seq. 24
  `rel-g3-ee52a1f2361f0976f40163a87b6fb7fd59b1fba730db8bacd503ef000c4a35c4`,
  cabeça `ci-40322184487` cobrindo até 2026-10-24, status `40378162474`.

## 2. O que já está provado — não refazer

- A virada inteira, A1–C5, com cada identificador:
  `PHASE_6_CUTOVER_2026-10-27.md` §2–§5.
- A promoção pela agenda já correu três vezes sem clique (10-19, 10-22,
  10-26; registro §4). Essas rodadas **não contam** para a vigia.
- A chuva do robô de terça aparece na página sem clique desde que o dono
  desligou o build cache (registro §7). Vigiar, não consertar.

## 3. A tarefa

**Única tarefa: o passo C6 da folha §6.** Para cada uma das quatro rodadas:

1. O depósito (`schedule`): jobs `detect`, `deposit`, `heartbeat`; a janela
   e "continues `ci-…`" no log. Uma rodada `no_acquisition` (`deposit`
   `skipped`) **conta** como rodada sem falha, mas diga que não promoveu.
2. A publicação (`workflow_run`) dela: `gate` e, se depositou, `stage`,
   `promote`, `context`, `sources`; o `sequence` antigo → novo e o
   `rel-g3-…` **copiados do log**.
3. O reconciliador do site: o commit `deploy(verde): reconstruir para
   release=…` e o check run *"Workers Builds"* dele.
4. **Todo** status diário desde o de 2026-10-27 até o último lido: as sete linhas
   do log (`grep -E '\b(ok|late|broken)\b'`), não a conclusão.
5. Os robôs do site de Ter/Sex (10-30, 11-03, 11-06, 11-10): um job só,
   `chuva`, `success`, commit sem arquivo sob `public/data/alerts/`.

Ao fim: o domínio, só GET com o UA de um Chrome real —
`/data/green/current.json` e `/data/alert-index/built-from.json` com o
mesmo `release_id`, e `/data/territorio/rain/manifest.json` com o `last`
do último robô.

Escreva `docs/implementation/PHASE_6ZP_<data>.md` com uma linha por rodada e
uma por status. **Se as quatro rodadas e todos os status estiverem sem
`late` nem `broken`:** o C6 fecha — bloco "Feito em …" no C6 da folha, linha
"Phase 6 fechada" no bloco datado do `ROADMAP.md` (sem reescrever as linhas
`Implementation status`), e o briefing seguinte: a série temporal verde
(D4). **Se uma falhou:** registre a primeira falha, pare, e escreva o
briefing de um pacote para ela — nunca remendo direto.

Entregue tudo numa PR de docs do backend.

**Fora de escopo:** consertar qualquer falha (vira pacote); a série verde
(D4); o aviso de tamanho (D5); a frase da automação; a `site#51`; apagar os
42 arquivos de `public/data/alerts/`; o broker.

## 4. Decisões de escopo já tomadas, com a base

- Quatro rodadas seguidas sem `late` nem `broken`; a primeira que falhar
  vira pacote: folha §6, C6.
- A vigia começa depois do registro do C5: briefing do C5, §3.
- Limites do status: `automation.latest` `late` com mais de 5 dias inteiros;
  `deposits.unpublished` pendente por mais de 1 dia (D2); dados atrasados com
  21 dias (`site#47`).

## 5. Fronteiras duras

- Só leitura e documentação. Nenhuma lane disparada — nem a de depósito "para
  ajudar" uma rodada sem imagem.
- Nenhum `wrangler`, token Cloudflare, login, chamada à API da Cloudflare ou
  broker; recusar se oferecido.
- `detect_gee.yml` e `update_data.yml` nunca são disparados nem reativados.
- Nenhum rollback do ponteiro sem o pedido do dono (folha §7).
- A `main` do site faz deploy de produção: o agente não faz push nela.
- Nenhum purge de cache.

## 6. Armadilhas já pagas — não redescobrir

- `gh workflow list` sem `--all` esconde os desligados.
- Uma rodada sem aquisição termina `success` com `deposit` `skipped`; o
  status pode sair `failure` só por `late` — leia o log (`PHASE_6ZF`).
- O cron do GitHub atrasa de 40 min a mais de 6 h; um status lido antes do
  reconciliador pode ver o site uma release atrás. Leia o horário.
- A borda da Cloudflare devolve 403/1010 a cliente sem UA de navegador.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório:
  SHAs do site entram na mensagem pela forma curta.
- `<<EOF` não citado executa os backticks: `git commit -F`.
- Decidir merge por conteúdo ou pelo assunto `(#N)`, nunca por ancestralidade.

## 7. Estado que o package herda

- Público no verde desde 2026-10-14; ponteiro seq. 24 `rel-g3-ee52a1f2…`,
  contexto `ctx-g1-cdbc6719…` seq. 6, fontes `src-g1-242279d5…` seq. 5.
- `detect_gee.yml` `disabled_manually` desde 2026-10-19; robô do site só com
  `chuva` desde 2026-10-22; `r2.dev` de `araripe-cogs` fechado desde
  2026-10-23; alertas novos fora do git do site desde 2026-10-24.
- Build cache do Workers Builds desligado pelo dono em 2026-10-24 — manter.
- Site em rascunho: `#51` (verificador); `#52` e `#53`, cujo título diz
  "NÃO MESCLE ANTES DO C6".

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. O registro da virada está escrito, e a última prova que faltava
apareceu hoje: o robô de terça atualizou a chuva sem trazer alerta nenhum, e
a chuva nova apareceu na página sozinha.

### O que você precisa fazer

1. **Mesclar a PR de documentação do registro da virada** — quando puder; não
   muda nada que roda.
2. **Abrir a próxima sessão do Claude com este briefing** — a partir de terça
   2026-11-10. Antes disso, só se chegar um e-mail de falha de um robô.

### Tem algo preocupante?

Não. As três últimas rodadas publicaram sozinhas e a página está em dia.

### O que ainda falta no caminho

- **Duas semanas de vigia** — este passo: conferir quatro rodadas seguidas.
- **A série de índices do sistema novo** — a aba "Séries" está parada em
  setembro; um pacote logo depois da vigia.
- **Avisar o tamanho antes de baixar** — um pacote pequeno do site.
- **Corrigir a frase da automação na página** — um pacote pequeno do site.
- **Mesclar o conserto do verificador** — a PR pequena do site que já está
  pronta.
- **Fase 5** — a validação independente.
