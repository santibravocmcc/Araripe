# Phase 6 — rebasear as duas PRs antigas do site, sem mesclar nenhuma

Escrito em 2026-10-13, ao fim da sessão da agenda verde
([`PHASE_6ZB`](../implementation/PHASE_6ZB_2026-10-13.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: é o passo A4 de
> [`PHASE_6_CUTOVER_RUNSHEET.md`](PHASE_6_CUTOVER_RUNSHEET.md). Resolver
> conflito em `src/js/alertas.js` entre a recusa do `?dados=verde` da `#42` e o
> aviso "dados atrasados" da `#47` é onde um merge limpo esconde uma colisão
> (memória `merge-limpo-pode-esconder-colisao`): as duas mexem no mesmo
> caminho da página verde. Nenhum merge na `main` do site — ela faz deploy de
> produção.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C site fetch origin && git -C site rev-parse origin/main
    gh pr view 47 -R santibravocmcc/observatorio-site --json state,mergedAt
    git -C site merge-tree --write-tree --name-only origin/main origin/claude/p6-ordem-do-deploy
    git -C site merge-tree --write-tree --name-only origin/main origin/claude/phase2b4b-stop-committing-alerts

- `site#47` **mesclada** pelo dono em 2026-10-13 17:11 UTC; a `main` do site
  estava em `a0c3390` (SHA curto de outro repositório) ao fim desta sessão.
- Leia `site/AGENTS.md` inteiro antes de editar o site.
- Worktree próprio para cada branch, com caminho **absoluto**; a árvore
  principal do site pode ter trabalho de outra sessão.
- Conte os testes do site na base (`npm run test:worker` e `pytest`) antes de
  mexer — e os do backend não mudam nesta sessão.

## 2. O que já foi verificado, para o executor não refazer

Medido em 2026-10-13 com `git merge-tree --write-tree` e
`git rev-list --left-right --count origin/main...origin/<branch>`:

| PR | branch | atrás / à frente da `main` | conflito |
| --- | --- | --- | --- |
| `site#42` (rascunho) | `claude/p6-ordem-do-deploy` | 7 / 5 | `src/js/alertas.js`, `src/styles/alertas.css`, `tests/alertas_fonte.test.mjs` (`src/js/alertas-fonte.js` mescla sozinho) |
| `site#21` (rascunho) | `claude/phase2b4b-stop-committing-alerts` | 37 / 1 | `.gitignore` |
| `site#48` (rascunho) | `claude/p6-rota-producao` | 1 / 1 | **nenhum** — não precisa de rebase agora |

- A `#42` é a ordem dos deploys: `COMPOR = False` em
  `scripts/indice_no_build.py`, o reconciliador `green_site_rebuild.yml`
  (cron `41 */3`, inerte enquanto `COMPOR` for falso), e `abreFonte` com
  `?dados=verde` recusado devolvendo `{fonte: 'verde', recusa}` em vez de cair
  no azul (`PHASE_6U`). A `#47` acrescentou o aviso "dados atrasados" quando a
  última data **olhada** passa de 21 dias, também só com `?dados=verde`
  (`PHASE_6Y` §9). O rebase tem de manter os **dois** comportamentos: uma
  recusa continua recusa (sem aviso de atraso por cima de dado que não
  abriu), e uma abertura com data velha continua avisando.
- A `#21` para de commitar os arquivos de alerta. Ela **só pode ser mesclada
  no passo C4**, depois de a página ler as rodadas pela rota — senão a data
  mais recente dá 404 (memória `site-pr21-nao-mesclar-antes-da-phase6`). O
  rebase não muda isso.
- A agenda verde (`Araripe#118`, A5) está escrita e em rascunho; nada desta
  sessão depende dela.

## 3. A tarefa

**Única tarefa: o passo A4 da folha — rebasear a `#42` e a `#21` sobre a
`main` do site, sem mesclar nenhuma.**

1. `#42`: rebase sobre `origin/main`, resolvendo os três conflitos com os dois
   comportamentos preservados; um teste que prenda a interação (recusa sem
   aviso de atraso; abertura com data olhada > 21 dias com aviso).
2. `#21`: rebase sobre `origin/main`, resolvendo o `.gitignore`.
3. Em cada branch: `git merge-tree` limpo contra a `main`,
   `npm run test:worker` e `pytest` verdes, `vite build` verde.
4. `git push --force-with-lease` de cada branch, com o SHA anterior no corpo
   do commit de rebase (é a volta do passo).
5. Atualizar o passo A4 da folha com os SHAs novos, numa PR de docs do
   backend.

**Fora de escopo:** mesclar qualquer PR do site (B1, B2, C4 — com o dono); a
`#48` (sem conflito); ligar `COMPOR` (B2); `FONTE_PADRAO` e os textos (A6,
sessão própria); o job `alertas` do robô (A7); a agenda (`#118`, B6); Fase 5.

## 4. Decisões de escopo já tomadas, com a base

- **Nada é apagado** — `PACKAGE_P6_PROMPT.md` §5.
- **`FONTE_PADRAO` continua `'azul'`** até o B5.
- D0–D6 decididas pelo dono em 2026-10-13 (folha §3).

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- A `main` do site faz deploy de produção: **nenhum merge**, nenhum push nela.
- Nenhum Worker implantado, nenhum `wrangler` com credencial (memória
  `wrangler-login-existe-isolar-home`: `env -i` e `HOME` vazio).
- A `main` do backend é só por PR.
- Nenhum Environment criado ou reconfigurado.

## 6. Armadilhas já pagas — não redescobrir

- `node --test tests/` quebra no Node 25: use `npm run test:worker`.
- Teste de texto lê só as linhas executáveis (`executable_lines()`), e uma
  mutação que comenta a linha tem de derrubar o teste.
- `git -C <repo> worktree add <caminho relativo>` cria o worktree **dentro**
  do repositório: caminho absoluto.
- O hook `commit-msg` do backend recusa SHA de 40 caracteres de outro
  repositório — no registro, SHA curto do site.
- `<<EOF` não citado executa os backticks do corpo: mensagem em arquivo e
  `git commit -F`.

## 7. Estado que o package herda

- `Araripe#118` em rascunho: a agenda verde (A5), para o B6.
- `site#48` em rascunho e limpa: a rota de produção e o verificador (A2+A3),
  para o B1.
- Ponteiro verde seq. 18 (107 datas até 2026-10-04); a fila de depósito desde
  2026-10-05 cresce um dia por dia (A9 a drena na véspera).
- O azul parado desde 2026-09-03. A lane de status acusa a automação atrasada
  desde 2026-10-13 — esperado até a virada.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. A agenda automática do sistema novo está escrita e testada: depósito
duas vezes por semana, publicação logo depois — só quando houve dado novo — e
uma conferência diária que fica vermelha e manda e-mail se algo atrasar. Ela
não está ligada.

### O que você precisa fazer

1. **Não mesclar a mudança da agenda agora.** Ela está em rascunho de
   propósito: mesclar faz o sistema novo começar a rodar sozinho, e isso é um
   passo do dia da virada, com você.

Nada mais nesta semana.

### Tem algo preocupante?

Não. A única coisa que só o dia real mostra é a primeira rodada automática, e
o roteiro da virada já manda conferir cada parte dela; se falhar, nada é
publicado e o aviso chega.

### O que ainda falta no caminho

- **Arrumar as mudanças antigas do site** — a próxima sessão, agora que você
  mesclou o aviso.
- **Preparar a troca do site para o sistema novo e desligar o robô antigo** —
  deixar escritas, sem publicar, as duas mudanças do site.
- **Revogar a chave local antiga** — com você.
- **Processar os dias acumulados**, na véspera.
- **A virada** — executar o roteiro, com a sua aprovação em cada passo que
  mexe no site público.
- **Fase 5** — a validação independente.
