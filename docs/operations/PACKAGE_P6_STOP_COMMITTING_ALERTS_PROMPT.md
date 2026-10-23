# Phase 6 — C4: parar de commitar alertas no git do site

Escrito em 2026-10-23, logo depois do C3
([`PHASE_6ZN`](../implementation/PHASE_6ZN_2026-10-23.md)): o acesso público
`r2.dev` de `araripe-cogs` desligado pelo dono, nenhum objeto apagado.
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: a mudança da `site#21` é de uma linha e está pronta desde o
> 2B.4B; a sessão a rebaseia, reescreve o teste-alarme que a própria
> virada disparou, roda as suítes, o dono mescla, e a sessão lê o build.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6ZN_2026-10-23.md | head -5
    gh workflow list -R santibravocmcc/Araripe --all --json path,state
    gh run list -R santibravocmcc/Araripe --workflow v2_green_status.yml -L 2 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/observatorio-site --workflow update-data.yml -L 2 --json databaseId,event,conclusion,createdAt
    gh pr view 21 -R santibravocmcc/observatorio-site --json state,isDraft,headRefOid,mergeable

- Esperado: `PHASE_6ZN` na `main`; `detect_gee.yml` `disabled_manually`, as
  outras 14 `active`; o status mais recente `success` com as sete linhas
  `ok` (leia o log, não a conclusão).
- **O "Depois" do C3 que faltou:** o status verde de **sábado
  2026-10-24** (cron diário 12:00 UTC, costuma rodar ~16:45Z) com as sete
  linhas `ok`. Registre o id.
- Releia o fechamento do C3, com o UA de um navegador real:
  `curl -sI -A "<UA>" https://pub-5eb389cffff54421916187be69dd659b.r2.dev/site-full/run-2026-01-02.geojson`
  → `401`. Se voltou `200`, alguém reabilitou: pare e pergunte.
- `update-data.yml` de terça 2026-10-27, se já houver: um job só,
  `chuva`, `success`.
- A `#21`: aberta, rascunho, `ab65a55` em 2026-10-23, **11 commits atrás**
  da `main` do site e 2 à frente (`git rev-list --left-right --count`).
- **Se o status tiver `late` ou `broken`**, ou uma rodada verde tiver
  falhado: pare, registre, e não peça o merge.

## 2. O que já está provado — não refazer

- C1, C2 e C3 feitos (`PHASE_6ZL`, `PHASE_6ZM`, `PHASE_6ZN`). Nada azul
  agendado escreve; o robô do site só roda `chuva`; `r2.dev` fechado.
- B5 (2026-10-14): `FONTE_PADRAO = 'verde'` em `src/js/alertas-fonte.js`
  na `main` do site (linha 45 em 2026-10-23). A página padrão lê as
  rodadas pela rota `/data/green/…`, não de `/data/alerts/`
  (`PHASE_6ZN` §5: a visão completa padrão pediu
  `/data/green/alerts/run-2026-10-19.geojson` `200`).
- O que a `#21` faz (lido em `ab65a55`): **só** `.gitignore` (a linha
  `!public/data/alerts/run-*.strong.geojson` sai, e o comentário muda) e o
  teste novo `tests/test_alert_files_are_not_committed.py`. Os 42 arquivos
  já rastreados em `public/data/alerts/` **continuam rastreados** — são o
  caminho de `?dados=azul` e de volta; o que para é o crescimento.

## 3. A tarefa

**Única tarefa: o passo C4 da [folha](PHASE_6_CUTOVER_RUNSHEET.md) §6 —
preparar a `site#21` para o merge, e o dono mescla.**

1. Rebaseie a `#21` sobre a `main` do site (num worktree; o
   `.gitignore` é o único arquivo que pode conflitar).
2. Reescreva `test_a_pagina_ainda_le_a_base_estatica`: ele afirma
   `FONTE_PADRAO = 'azul'` e **falha de propósito** desde o B5. Ele deve
   passar a registrar a condição **cumprida** (o padrão é o verde, a
   página padrão não lê `/data/alerts/`) e falhar se o padrão voltar ao
   azul. Pergunte qual mutação derruba o teste novo, e faça a mutação.
3. Releia a docstring do teste e o comentário do `.gitignore` contra o
   presente e corrija o que envelheceu, no mínimo:
   - *"os full … são servidos do R2"* — desde o C3, não são mais servidos
     ao público;
   - o risco de 404 *"na próxima rodada do bot azul"* — desde o C2 não há
     bot que commite alertas; o risco só volta com um revert do C2. O
     teste `test_toda_rodada_do_indice_tem_o_seu_arquivo_forte` continua
     valendo como guarda desse caso.
4. Rode, no tree rebaseado: `python3 -m pytest -q` e
   `npm run test:worker`; compare com a `main` do site sozinha no mesmo
   ambiente.
5. Force-push da branch (é branch de agente), tire do rascunho, e peça o
   merge ao dono em uma frase. Sem o "mesclei" dele nesta sessão, pare e
   entregue o registro.
6. Depois do merge: check run *"Workers Builds: observatorio-chapada"*
   `success` no commit do merge; `alertas.html`, `/` e `dados-abertos.html`
   sem parâmetro abrem a data mais recente (não 404), sem pedido a
   `r2.dev`, pela rede do navegador.

Entregue: o bloco "Feito em …" no C4 da folha, um registro
`docs/implementation/PHASE_6ZO_<data>.md` com ids copiados das ferramentas,
e o briefing do C5. Tudo numa PR de docs do backend.

**Fora de escopo:** apagar os 42 arquivos rastreados (`git rm`) ou
reescrever a história do site; o cache velho da chuva (`PHASE_6ZN` §2 —
pacote próprio); a `site#51`; C5 em diante; D4, D5; o broker.

## 4. Decisões de escopo já tomadas, com a base

- A ordem C1 → C6 e o "Antes" de cada passo são da folha §6.
- A condição de merge da `#21` é o padrão verde (B5) — escrita no próprio
  teste desde o A4 (`PHASE_6ZC` §3), e cumprida em 2026-10-14.
- Os arquivos rastreados ficam: são o rollback (folha §7, C4: revert da
  PR).

## 5. Fronteiras duras

- O merge é do dono. Nenhuma escrita em lane, bucket, Worker, DNS ou rota.
- A `main` do site faz deploy de produção a cada push: o agente não faz
  push nela.
- Nenhum `wrangler`, token Cloudflare, login, chamada à API da Cloudflare
  ou broker; recusar se oferecido.
- `detect_gee.yml` e `update_data.yml` nunca são disparados nem reativados.
- Nenhum purge de cache, nem para a chuva.

## 6. Armadilhas já pagas — não redescobrir

- A borda da Cloudflare devolve 403/1010 a cliente sem UA de navegador; use
  o UA real.
- Um caminho de prefixo (`…/site-full/`) é `404` com o acesso aberto ou
  fechado: confira um **objeto** (`PHASE_6ZN` §3).
- Os JSON de nome fixo sob `/data/` podem estar velhos na borda mesmo com
  build `success` (`PHASE_6ZN` §2): compare o conteúdo servido com a `main`,
  não só o status do build.
- Testar o site num worktree fora de `site/` precisa de `../Araripe` em
  `origin/main` e de `node_modules`; sem eles, 7 testes Python e
  `producao_rota.test.mjs` falham por ambiente (`PHASE_6ZM` §3).
- `gh workflow list` sem `--all` esconde os desligados.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório.
- `<<EOF` não citado executa os backticks: `git commit -F`.

## 7. Estado que o package herda

- Público no verde desde 2026-10-14; ponteiro seq. 23 `rel-g3-7b69385c…`
  (ou mais nova, depois da segunda 2026-10-26).
- `detect_gee.yml` `disabled_manually` desde 2026-10-19T23:03:30Z.
- Robô do site só com `chuva` desde o merge `e0bd263` (2026-10-22).
- `r2.dev` de `araripe-cogs` fechado desde 2026-10-23 ~16:59Z.
- Site em rascunho: `#21` (C4), `#51` (verificador).

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

O acesso público antigo está fechado e a página seguiu igual. Falta só
ver o relatório de saúde de sábado, que a próxima sessão lê primeiro.

### O que você precisa fazer

1. **Mesclar a PR de documentação deste passo** — quando puder; não muda
   nada que roda.
2. **Abrir a próxima sessão do Claude com este briefing** — quando quiser
   dar o próximo passo. Ela prepara a mudança e depois pede que você
   mescle uma PR do site.

### Tem algo preocupante?

Sim, um, fora deste passo: a página de chuva mostra os dados de 13 de
outubro há dez dias, embora o robô atualize direitinho. É um cache da
Cloudflare segurando os arquivos velhos. Os alertas não são afetados.
Vale um pacote próprio para achar a causa antes de mexer.

### O que ainda falta no caminho

- **Parar de guardar alertas no código do site** — este passo, com o seu
  "sim" no merge.
- **Registrar a virada** — um documento que junta todos os passos.
- **Duas semanas de vigia** — conferir cada rodada.
- **Consertar a chuva parada na página** — achar a causa do cache, depois
  corrigir.
- **Corrigir a frase da automação na página** — um pacote pequeno do site.
- **Avisar o tamanho antes de baixar** — um pacote pequeno do site.
- **A série de índices do sistema novo** — um pacote logo depois.
- **Fase 5** — a validação independente.
