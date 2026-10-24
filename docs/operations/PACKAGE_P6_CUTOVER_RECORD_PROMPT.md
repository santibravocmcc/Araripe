# Phase 6 — C5: registrar a virada

Escrito em 2026-10-24, logo depois do C4
([`PHASE_6ZO`](../implementation/PHASE_6ZO_2026-10-24.md)): a `site#21`
mesclada pelo dono, rodadas novas de alerta fora do git do site.
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: é só documentação, mas junta quinze registros (`PHASE_6Z` a
> `PHASE_6ZO`) e cada identificador tem de ser recopiado da ferramenta, não
> do registro anterior. O risco é de cópia, não de raciocínio.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6ZO_2026-10-24.md | head -5
    gh workflow list -R santibravocmcc/Araripe --all --json path,state
    gh run list -R santibravocmcc/Araripe --workflow v2_green_status.yml -L 3 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/Araripe --workflow v2_green_deposit_lane.yml -L 3 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/Araripe --workflow v2_promotion_lane.yml -L 3 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/observatorio-site --workflow update-data.yml -L 2 --json databaseId,event,conclusion,createdAt,headSha

- Esperado: `PHASE_6ZO` na `main`; `detect_gee.yml` `disabled_manually`,
  as outras 14 `active`; o status mais recente `success` com as sete linhas
  `ok` (leia o log, não a conclusão).
- **A rodada verde de segunda 2026-10-26** (Mon 06:00 UTC): depósito e
  promoção. Se promoveu, o ponteiro passa da seq. 23; registre o novo
  `rel-g3-…` copiado do status.
- **O robô do site de terça 2026-10-27** (`update-data.yml`): um job só,
  `chuva`, `success`, e o commit dele **não** traz arquivo sob
  `public/data/alerts/` (`git show --stat <commit>`). É o primeiro "Depois"
  do C4 que só o tempo mostra; ver `PHASE_6ZO` §5.
- **Se o status tiver `late` ou `broken`**, ou uma rodada verde tiver
  falhado: pare, registre, e não escreva o registro da virada como fechado.

## 2. O que já está provado — não refazer

- A1–A11, B0–B6 e C1–C4, cada um com o seu bloco "Feito em …" na
  [folha](PHASE_6_CUTOVER_RUNSHEET.md) e o seu registro
  `docs/implementation/PHASE_6Z*.md`. C4: `PHASE_6ZO`.
- A chuva presa em 10-13 é outro assunto, com registro próprio
  (`PHASE_6_CHUVA_PRESA_2026-10-23.md`); entra no registro da virada como
  achado lateral, não como passo.

## 3. A tarefa

**Única tarefa: o passo C5 da folha §6 — registrar a virada.**

1. Escreva `docs/implementation/PHASE_6_CUTOVER_<data>.md`: uma tabela por
   fase (A, B, C), uma linha por passo, com data, PR/merge, run, e a leitura
   que fechou o "Depois". **Cada identificador relido na ferramenta**
   (`gh pr view`, `gh run view`, `git rev-parse`), não copiado de outro
   registro — os registros são o índice de onde procurar, não a fonte.
2. Junte os achados que mudaram a folha no caminho (o "Depois" do C3 que
   passaria pelo motivo errado, `PHASE_6ZN` §3; o teste-alarme da `#21`,
   `PHASE_6ZO` §3), e o que ficou aberto (C6, D4, D5, a `site#51`, a chuva).
3. Atualize `ROADMAP.md` com um bloco datado no topo (não reescreva as
   linhas `Implementation status`, por decisão registrada no próprio
   roadmap) e `docs/implementation/PENDING_CAPABILITIES.md` no que a virada
   fechou.
4. O bloco "Feito em …" no C5 da folha, e o briefing do C6.

Entregue tudo numa PR de docs do backend.

**Fora de escopo:** C6 (a vigia começa depois deste registro); apagar os
42 arquivos rastreados em `public/data/alerts/` ou reescrever a história do
site; a correção da chuva; a `site#51`; D4, D5; o broker.

## 4. Decisões de escopo já tomadas, com a base

- A ordem C1 → C6 e o "Antes" de cada passo são da folha §6.
- O nome do arquivo é o da folha: `PHASE_6_CUTOVER_<data>.md`.
- O roadmap recebe bloco datado, não reescrita (`ROADMAP.md`, o parágrafo
  sobre a baseline de 2026-08-11).

## 5. Fronteiras duras

- Só documentação. Nenhuma escrita em lane, bucket, Worker, DNS ou rota.
- A `main` do site faz deploy de produção a cada push: o agente não faz
  push nela.
- Nenhum `wrangler`, token Cloudflare, login, chamada à API da Cloudflare
  ou broker; recusar se oferecido.
- `detect_gee.yml` e `update_data.yml` nunca são disparados nem reativados.
- Nenhum purge de cache.

## 6. Armadilhas já pagas — não redescobrir

- `gh workflow list` sem `--all` esconde os desligados.
- A borda da Cloudflare devolve 403/1010 a cliente sem UA de navegador.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório:
  SHAs do site entram na mensagem pela forma curta.
- `<<EOF` não citado executa os backticks: `git commit -F`.
- Decidir se algo foi mesclado por conteúdo ou pelo assunto `(#N)`, nunca
  por ancestralidade (os dois repositórios fazem squash).

## 7. Estado que o package herda

- Público no verde desde 2026-10-14; ponteiro seq. 23 `rel-g3-7b69385c…`
  (ou mais nova, depois da segunda 2026-10-26).
- `detect_gee.yml` `disabled_manually` desde 2026-10-19T23:03:30Z.
- Robô do site só com `chuva` desde o merge `e0bd263` (2026-10-22).
- `r2.dev` de `araripe-cogs` fechado desde 2026-10-23 ~16:59Z.
- Rodadas novas de alerta fora do git do site desde o merge `e8dcdc2`
  (2026-10-24T18:33:25Z).
- Site em rascunho: `#51` (verificador).

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada do passo em si: o site parou de guardar alertas novos no código, e a
página seguiu igual. Só o tempo mostra a última prova — o robô de terça
atualizar a chuva sem trazer alerta nenhum.

### O que você precisa fazer

1. **Mesclar a PR de documentação deste passo** — quando puder; não muda
   nada que roda.
2. **Abrir a próxima sessão do Claude com este briefing** — depois de terça
   2026-10-27, para ela já ler o robô de terça.

### Tem algo preocupante?

Não. A página e os dados seguem como antes; o que mudou só impede o
repositório do site de crescer.

### O que ainda falta no caminho

- **Registrar a virada** — este passo: um documento que junta todos os
  passos, sem mudar nada que roda.
- **Duas semanas de vigia** — conferir cada rodada.
- **Consertar a chuva parada na página** — confirmar que o robô de terça
  aparece sozinho.
- **Corrigir a frase da automação na página** — um pacote pequeno do site.
- **Avisar o tamanho antes de baixar** — um pacote pequeno do site.
- **A série de índices do sistema novo** — um pacote logo depois.
- **Fase 5** — a validação independente.
