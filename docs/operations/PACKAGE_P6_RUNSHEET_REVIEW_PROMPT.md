# Phase 6 — a revisão da folha pelo dono e o dia marcado

Escrito em 2026-10-14, ao fim da sessão que drenou a fila de depósito
([`PHASE_6ZG`](../implementation/PHASE_6ZG_2026-10-14.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: é o passo A11 de
> [`PHASE_6_CUTOVER_RUNSHEET.md`](PHASE_6_CUTOVER_RUNSHEET.md), e quem o
> executa é o **dono**. O agente não decide nada: confere que a folha está
> atualizada, apresenta a Fase B em linguagem simples, responde às perguntas
> do dono por conteúdo e registra o "sim" e o dia. Nenhum código, nenhuma
> lane de escrita.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    gh pr list -R santibravocmcc/Araripe --state open --json number,isDraft,headRefName
    gh pr list -R santibravocmcc/observatorio-site --state open --json number,isDraft,headRefName
    git -C Araripe show origin/main:docs/implementation/PHASE_6ZG_2026-10-14.md | head -5
    gh workflow run v2_green_status.yml --ref main -R santibravocmcc/Araripe

- Esperado: site em rascunho `#48`, `#42`, `#49`, `#50`, `#21`; backend
  `#118` em rascunho e a PR de docs do A9 (mesclada ou não — confira por
  conteúdo, como acima).
- Em 2026-10-14 o ponteiro verde foi para a seq. 19,
  `rel-g3-b19132638d911f28ab8c711b68cd848849b57e5f679d373a34191285281e63fa`;
  a cabeça da cadeia é `ci-38561001665`, cobrindo até 2026-10-12; contexto
  `ctx-g1-5b1ac5a0…` seq. 3, fontes `src-g1-e9e0ba1a…` seq. 2. Status
  `38567568460`: as sete linhas `ok`.
- A partir de 2026-10-20 (6 dias desde 12:14:33Z de 10-14), sem agenda verde,
  `automation.latest` volta a `late`. **É esperado** até o B6; não bloqueia.

## 2. O que já foi medido, para o executor não refazer

- A1–A9 têm bloco "Feito" na folha com PR, SHA ou run; A10 é opcional e do
  dono. Conferir é ler os blocos, não refazer os passos.
- Nenhuma PR em rascunho cita a release, o contexto ou as fontes substituídos
  em 2026-10-14 fora de fixtures de teste (`PHASE_6ZG` §5). A troca da seq. 18
  para a 19 não envelheceu nenhuma delas.
- O B5 exige o A9 feito há menos de 3 dias. O A9 de 2026-10-14 **não** vale
  para uma virada depois de 2026-10-16: na véspera repete-se o A9 (o mesmo
  par de comandos; `PHASE_6ZG` §6).
- D6: quarta ou sábado de manhã, ~3 h do dono, fora de segunda/quinta
  (depósito azul) e terça/sexta (robô do site).

## 3. A tarefa

**Única tarefa: o passo A11 da folha — o dono revisa e marca o dia.**

1. Confirme o §1. Se alguma PR de rascunho mudou, ou o status tem `broken`,
   **pare e conte ao dono** antes de seguir.
2. Apresente ao dono a Fase B (B0–B6) e a Fase C (C1–C6) passo a passo, em
   linguagem simples: o que cada passo muda, quem aperta o botão, como se
   volta. Responda às perguntas lendo a folha e as PRs, nunca de memória.
3. Se o dono pedir mudança na folha, faça-a na mesma PR de docs, com a razão.
4. Registre o "sim" do dono **nas palavras dele** e o dia escolhido (D6):
   bloco "Feito" no A11 e no D6 da folha.
5. Registro `PHASE_6ZH_<data>.md` e o próximo briefing: a véspera (A9 de
   novo) seguida do B0 no dia. Tudo numa PR de docs do backend.

**Fora de escopo:** qualquer merge (B1–B6 são do dia); qualquer lane de
escrita (o A9 da véspera é a sessão seguinte, a não ser que o dia marcado
seja amanhã — então diga isso e pergunte); mexer em workflow; o A10.

## 4. Decisões de escopo já tomadas, com a base

- D0–D6 decididas pelo dono em 2026-10-13 (folha §3, passo A1).
- Bucket: opção (a) — dono, 2026-09-30.
- Nenhuma publicação tem revisor; rollback pelo `v2-promotion` — 2026-10-02.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- Nenhum valor de credencial; nenhuma chave nova; nenhum Environment
  alterado. Claude não tem credencial local do bucket desde o A8.
- Nenhum `wrangler`, token Cloudflare ou broker. Se o dono oferecer acesso à
  conta Cloudflare, recuse e diga por quê (`CLAUDE.md`).
- A `main` do backend é só por PR; a do site faz deploy — nenhum merge.
- Um "sim" à folha não aprova nenhum passo de produção: cada passo da Fase B
  pede a aprovação dele, no dia.

## 6. Armadilhas já pagas — não redescobrir

- `late` em `automation.latest` sem agenda é esperado (§1).
- A promoção lê o job `deposit`, não a conclusão da run.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório — no
  registro, SHA curto do site.
- `<<EOF` não citado executa os backticks do corpo: mensagem em arquivo e
  `git commit -F`.

## 7. Estado que o package herda

- Site em rascunho: `#48` (B1), `#42` (B2), `#49` (B5, base `#42`), `#50`
  (C2), `#21` (C4). Backend: `#118` (B6).
- Ponteiro verde na seq. 19; fila vazia até 2026-10-12.
- O azul parado desde 2026-09-03.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. Os dias acumulados desde 5 de outubro foram processados e publicados no
sistema novo; ele está em dia até 12 de outubro, e todas as checagens dele
estão verdes.

### O que você precisa fazer

1. **Revisar e mesclar a PR de documentação desta sessão** — pode esperar;
   não muda nada que roda.
2. **Separar umas duas horas para ler o roteiro da virada com o Claude e
   escolher o dia** — é o próximo passo; quarta ou sábado de manhã.

### Tem algo preocupante?

Não. O aviso de "automação atrasada" vai voltar em uns seis dias, porque o
sistema novo só roda sozinho depois da virada; é esperado.

### O que ainda falta no caminho

- **Você revisar o roteiro e marcar o dia** — a próxima sessão.
- **Processar de novo os dias acumulados** — na véspera da virada.
- **A virada** — executar o roteiro, com a sua aprovação em cada passo que
  mexe no site público.
- **Desligar o sistema antigo** — depois da primeira rodada automática nova.
- **A série de índices do sistema novo** — um pacote logo depois da virada.
- **Fase 5** — a validação independente.
