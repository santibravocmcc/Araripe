# Phase 6 — a PR que faz o público ver o verde, escrita e não mesclada

Escrito em 2026-10-13, ao fim da sessão do rebase do site
([`PHASE_6ZC`](../implementation/PHASE_6ZC_2026-10-13.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: é o passo A6 de
> [`PHASE_6_CUTOVER_RUNSHEET.md`](PHASE_6_CUTOVER_RUNSHEET.md) — a PR que o
> B5 mescla, o único passo que muda o que o público vê. A troca em si é uma
> linha; o trabalho é o texto científico estático, que hoje descreve o azul e
> continua sendo lido por `?dados=azul` depois da virada (§2). Nenhum merge na
> `main` do site — ela faz deploy de produção.

---

## 1. O estado de partida — confirme por conteúdo

    git -C site fetch origin && git -C site rev-parse origin/main
    git -C site rev-parse origin/claude/p6-ordem-do-deploy origin/claude/p6-rota-producao
    gh pr list -R santibravocmcc/observatorio-site --state open --json number,isDraft,headRefName
    git -C site grep -n "FONTE_PADRAO = " origin/main -- src/js/alertas-fonte.js

- Ao fim da sessão anterior: `main` do site em `a0c3390`; `#42` em `e2a33f5`,
  `#21` em `ab65a55`, `#48` em `95148a8` — as três rascunho, nenhuma
  conflitando com a `main` nem entre si (`PHASE_6ZC` §1, §4).
- Leia `site/AGENTS.md` inteiro antes de editar o site.
- Worktree próprio com caminho **absoluto**, e um worktree do backend na
  `main` dele ao lado (ou `ARARIPE_DIR`): sem ele o `pytest` do site dá 5
  falhas e 136 testes em vez de 227 (`PHASE_6ZC` §1).
- Conte os testes do site na base antes de mexer.

## 2. O que já foi medido, para o executor não refazer

- **De onde ramificar.** Depois do B5 o público vê a `#42` (recusa sem azul,
  índice composto no build) **mais** esta PR. Ramificada da `main`, os testes
  desta PR exercitariam a página que ainda cai no azul — que o público nunca
  verá. Recomendado: ramificar de `origin/claude/p6-ordem-do-deploy`, abrir a
  PR em rascunho com base nessa branch (diff legível), e dizer no corpo que
  ela é rebaseada sobre a `main` depois do B2. Se preferir outra forma, pare e
  pergunte.
- **A troca.** `FONTE_PADRAO = 'azul'` em `src/js/alertas-fonte.js` (linha 43
  na `#42`). Dois testes a prendem e dizem que a virada os muda junto:
  `tests/alertas_fonte.test.mjs` ("o padrão é o azul até a virada") e
  `tests/home_alertas.test.mjs` ("a virada mudou o padrão; revise as duas
  linhas abaixo" — o link do cartão da página inicial só leva `?dados=` quando
  a fonte não é a padrão).
- **O texto estático descreve o azul, e o azul continua existindo.** Na visão
  verde, `textosDaColecao` (`alertas-fonte.js`) já reescreve na carga as
  opções do seletor "Coleção p/ vegetação natural" e a frase da fração; para o
  azul ele devolve `null` e a página mostra o HTML estático — hoje
  `10 m · Coleção 2 (2023)` e `~300 m · Coleção 10 (2023)` (`alertas.html`
  132–133), que **são** as coleções do azul. Trocar o estático por 2025 sem
  dar ao azul os seus rótulos faria `?dados=azul` (o caminho de volta do B5)
  rotular 2023 como 2025. Decida no código onde mora cada texto, e teste os
  dois caminhos.
- **Onde ainda aparece 2023** (`git grep` na `#42`, 2026-10-13): só
  `alertas.html` 132–133 e `worker/knowledge.js` 107–108 ("calculada com as
  versões ANTERIORES (Coleção 2 beta 10 m e Coleção 10 ~300 m, ambas de
  2023)"). A folha cita também `dados-abertos.html`; ali não há mais 2023 —
  confirme e registre. `index.html` 85 e 134 citam "Coleção 10" como fonte de
  figuras da página inicial: confira de que dado elas são antes de tocar.
- **D4 = 1** (folha §3): virar sem a série atualizada, **com a data dela dita
  na aba "Séries"**. A aba lê `/data/timeseries/series.json`
  (`src/js/alertas.js`, `montaSerie`), que é do azul e está parada; a série
  verde é pacote depois da virada.
- **A `#21` reage a esta troca.** O teste
  `test_a_pagina_ainda_le_a_base_estatica` dela confere
  `FONTE_PADRAO = 'azul'` e falha de propósito quando o padrão muda. Isso é o
  C4, não esta sessão: não rebaseie a `#21` sobre esta branch.

## 3. A tarefa

**Única tarefa: o passo A6 da folha — a PR do site com `FONTE_PADRAO =
'verde'` e os textos estáticos, em rascunho, sem mesclar.**

1. A troca da constante e os dois testes que a prendem.
2. Os textos: o seletor e a frase de `alertas.html`, `worker/knowledge.js`
  (é o que o assistente de `/api/chat` responde), e a data da série na aba
  "Séries"; cada texto certo **nas duas fontes** — verde por padrão, azul por
  `?dados=azul`.
3. `npm run test:worker`, `pytest` e `vite build` verdes; `git grep -n
  "2023"` nos arquivos tocados só onde o texto for histórico de propósito, e
  um teste que prenda isso (linhas executáveis; a mutação que comenta a linha
  tem de derrubá-lo).
4. A PR em rascunho, e o passo A6 da folha atualizado numa PR de docs do
  backend, com o registro da sessão e o próximo briefing (A7).

**Fora de escopo:** mesclar qualquer PR (B1, B2, B5, C4 — com o dono); o
`COMPOR` (B2); o job `alertas` do robô (A7); a série verde (pacote depois da
virada, D4); a agenda (`#118`, B6); a Fase 5.

## 4. Decisões de escopo já tomadas, com a base

- **Nada é apagado** — `PACKAGE_P6_PROMPT.md` §5. O azul continua inteiro
  atrás de `?dados=azul` até o C3.
- D0–D6 decididas pelo dono em 2026-10-13 (folha §3); D4 = 1.
- O verde nunca nomeia 2023 (`site#43`, Araripe `PHASE_6W`).

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- A `main` do site faz deploy de produção: **nenhum merge**, nenhum push nela.
- Nenhum Worker implantado, nenhum `wrangler` com credencial (memória
  `wrangler-login-existe-isolar-home`: `env -i` e `HOME` vazio).
- A `main` do backend é só por PR.
- Nenhum Environment criado ou reconfigurado.

## 6. Armadilhas já pagas — não redescobrir

- `node --test tests/` quebra no Node 25: use `npm run test:worker`.
- Teste de texto lê só as linhas executáveis, e uma mutação que comenta a
  linha tem de derrubar o teste.
- Um teste-alarme envelhece sem mudar de palavra quando o código muda de
  arquivo (`PHASE_6ZC` §3): confira **onde** a coisa mora antes de afirmar que
  ela mudou.
- `git -C <repo> worktree add <caminho relativo>` cria o worktree **dentro**
  do repositório: caminho absoluto.
- O hook `commit-msg` do backend recusa SHA de 40 caracteres de outro
  repositório — no registro, SHA curto do site.
- `<<EOF` não citado executa os backticks do corpo: mensagem em arquivo e
  `git commit -F`.

## 7. Estado que o package herda

- `site#48` (A2+A3, para o B1), `site#42` (para o B2), `site#21` (para o C4):
  rascunho, rebaseadas, limpas.
- `Araripe#118` em rascunho: a agenda verde (A5), para o B6.
- Ponteiro verde seq. 18 (107 datas até 2026-10-04); a fila de depósito desde
  2026-10-05 cresce um dia por dia (A9 a drena na véspera).
- O azul parado desde 2026-09-03; a lane de status acusa a automação atrasada
  desde 2026-10-13 — esperado até a virada.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. As duas mudanças antigas do site estão em dia com a versão atual, todos
os testes passam, e nenhuma foi publicada. Uma delas ganhou testes que
garantem que o aviso "dados atrasados" e a mensagem de erro do sistema novo
não se atropelam.

### O que você precisa fazer

1. **Não mesclar as mudanças do site que estão em rascunho.** Cada uma tem o
   seu momento no roteiro da virada, com você.

Nada mais nesta semana.

### Tem algo preocupante?

Não. Achei um alarme de teste que tinha envelhecido — ele dizia que uma
condição tinha mudado quando só o código tinha mudado de arquivo — e o
consertei; o roteiro da virada tinha a mesma frase envelhecida, também
corrigida.

### O que ainda falta no caminho

- **Escrever a mudança que faz o público ver o sistema novo** — a próxima
  sessão, sem publicar.
- **Desligar o robô antigo do site** — deixar escrita, sem publicar.
- **Revogar a chave local antiga** — com você.
- **Processar os dias acumulados**, na véspera.
- **A virada** — executar o roteiro, com a sua aprovação em cada passo que
  mexe no site público.
- **Fase 5** — a validação independente.
