# Phase 6 — C2: parar o robô azul do site

Escrito em 2026-10-19, logo depois do C1
([`PHASE_6ZL`](../implementation/PHASE_6ZL_2026-10-19.md)): `detect_gee.yml`
`disabled_manually`, as outras 14 lanes `active`.
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: o código está pronto desde o A7; a sessão confere se a PR ainda
> vale contra a `main` do site, o dono mescla, e a sessão lê a terça ou
> sexta seguinte.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6ZL_2026-10-19.md | head -5
    gh workflow list -R santibravocmcc/Araripe --all --json path,state
    gh run list -R santibravocmcc/Araripe --workflow detect_gee.yml -L 2 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/Araripe --workflow v2_green_status.yml -L 1 --json databaseId,event,conclusion,createdAt
    gh pr view 50 -R santibravocmcc/observatorio-site --json state,isDraft,headRefOid,mergeable,mergeStateStatus

- Esperado: `PHASE_6ZL` na `main`; `detect_gee.yml` `disabled_manually` e as
  outras 14 `active`; **nenhum run de `detect_gee.yml` depois de
  `39255074543`** (2026-10-19) — se a sessão abrir depois da quinta
  2026-10-22, esta é a leitura que fecha o "Depois" do C1, registre-a; o
  status mais recente `success`; a `#50` aberta, rascunho, `ad710d8`.
- **Se aparecer um run novo de `detect_gee.yml`**, o C1 foi desfeito por
  alguém: pare e pergunte ao dono, não reative nem desative nada.
- **Se o status mais recente tiver `late` ou `broken`**, ou se uma rodada
  verde tiver falhado: pare, registre, e não peça o merge — o C2 tira a
  última peça azul que ainda escreve alertas.

## 2. O que já está provado — não refazer

- A `#50` (A7, [`PHASE_6ZE`](../implementation/PHASE_6ZE_2026-10-14.md)):
  sai o job `alertas` inteiro; `chuva`, cron `0 6 * * 2,5`,
  `workflow_dispatch`, `concurrency` e `permissions` iguais pelo YAML
  carregado; seis mutações derrubam os testes novos; ficam sem chamador, não
  apagados, `check_backend_release.py`, os dois modos de `prepare_data.py` e
  `public/data/freshness/alertas.json`.
- Conferido em 2026-10-19 (`PHASE_6ZL` §7): a `#50` está 7 commits atrás da
  `main` do site (`8723e41`), `mergeable` `CLEAN`, e **nenhum** daqueles 7
  toca os quatro arquivos dela (`.github/workflows/update-data.yml`,
  `DEPLOY.md`, `tests/test_green_site_publish_lane.py`,
  `tests/test_update_data_workflow.py`).
- O público lê o verde desde o B5 (2026-10-14); o job `alertas` do robô não
  alimenta mais a página padrão.

## 3. A tarefa

**Única tarefa: o passo C2 da [folha](PHASE_6_CUTOVER_RUNSHEET.md) §6 — o
merge da `observatorio-site#50`, feito pelo dono.**

1. Refaça a conferência de deriva do §2 contra a `main` do site de hoje
   (`git log ad710d8..origin/main -- <os quatro arquivos>` vazio). Se algum
   commit novo tocar um deles, rebaseie a `#50` só com o seu commit, rode
   `pytest` e `npm run test:worker` do site, e empurre a branch — sem tirar
   o rascunho.
2. Rode no tree que vai ser mesclado: `pytest` do site e
   `npm run test:worker`. Registre os números.
3. Peça ao dono, em uma frase, que tire o rascunho e mescle a `#50`. **Você
   não mescla.** Sem o "mesclei" dele nesta sessão, pare aqui e entregue o
   registro do que conferiu.
4. Depois do merge: o SHA do merge na `main` do site; o build do site
   `success` (o check run *"Workers Builds: observatorio-chapada"*); a
   página padrão igual (release da seq. vigente em `built-from.json`).
5. Na terça ou sexta seguinte ao merge: `update-data.yml` roda só o job
   `chuva`, `success`; nenhum passo com `R2_*`; a página de chuva com a data
   nova. Se a sessão fechar antes, isso vai para o §1 do briefing do C3.

Entregue: o bloco "Feito em …" no C2 da folha, um registro
`docs/implementation/PHASE_6ZM_<data>.md` (as conferências do §1 e do §3,
com ids copiados das ferramentas), e o briefing do C3. Tudo numa PR de docs
do backend.

**Fora de escopo:** C3 em diante (cada um tem a sua aprovação); apagar os
scripts que ficaram sem chamador; a frase da automação que envelhece depois
da promoção (`PHASE_6ZK` §5); mesclar a `site#51`; D4, D5; o broker.

## 4. Decisões de escopo já tomadas, com a base

- D0–D6 na folha §3; a ordem C1 → C2 → C3 → C4 → C5 → C6 é da folha §6.
- O C2 é um merge, não uma edição: o conteúdo é o da `#50` revisado no A7.
- Os scripts que perdem o chamador ficam (`PHASE_6ZE`); apagar é outro
  pacote, depois da vigia.

## 5. Fronteiras duras

- Nenhuma escrita em lane, bucket ou Worker. O único push permitido é o
  rebase da branch da `#50`, se o §3.1 pedir.
- **Todo merge é do dono.** Nenhum `gh pr merge`, nenhum `gh pr ready`.
- Nenhum `wrangler`, token Cloudflare, login ou broker; recusar se oferecido.
- `detect_gee.yml` e `update_data.yml` nunca são disparados nem reativados;
  nada é apagado.
- Nenhum rollback de ponteiro sem pedido do dono.

## 6. Armadilhas já pagas — não redescobrir

- O e-mail de falha do robô azul do site (`update-data.yml`, job `alertas`)
  chega em toda terça e sexta **até o merge**; depois dele, nenhum. Um
  e-mail desses antes do merge não é sinal de problema novo.
- A `main` do site faz deploy de produção a cada push: o merge da `#50` gera
  um build, mesmo sem mudar a página.
- `gh workflow list` sem `--all` esconde os desligados.
- Uma rodada sem imagem termina `success` com `deposit` `skipped`; leia os
  jobs, não a conclusão.
- `node --test tests/` quebra no Node 25: use `npm run test:worker`.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório.
- `<<EOF` não citado executa os backticks: `git commit -F`.

## 7. Estado que o package herda

- Público no verde desde 2026-10-14; ponteiro seq. 22 `rel-g3-0a788e76…`
  (ou mais nova, se a quinta 2026-10-22 achou imagem).
- `detect_gee.yml` `disabled_manually` desde 2026-10-19T23:03:30Z.
- Site em rascunho: `#50` (C2), `#21` (C4), `#51` (verificador).

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. O sistema antigo de detecção está desligado desde a noite de
2026-10-19; o arquivo dele ficou intacto e religar é um comando. Falta só
ver, na quinta, que ele não rodou mais.

### O que você precisa fazer

1. **Mesclar a PR de documentação do desligamento** — quando puder; não
   muda nada que roda.
2. **Abrir a próxima sessão do Claude com este briefing** — quando quiser
   parar o robô antigo do site. Ela confere tudo e depois pede que você
   mescle a PR #50 do site.

### Tem algo preocupante?

Não. Os e-mails de falha do sistema antigo de detecção param a partir de
agora; o do robô antigo do site ainda chega às terças e sextas até o
próximo passo, e é esperado.

### O que ainda falta no caminho

- **Desligar o sistema antigo** — três passos, cada um com o seu "sim":
  parar o robô antigo do site, fechar o acesso público antigo, parar de
  guardar alertas no código do site.
- **Duas semanas de vigia** — conferir cada rodada.
- **Corrigir a frase da automação na página** — um pacote pequeno do site.
- **Avisar o tamanho antes de baixar** — um pacote pequeno do site.
- **A série de índices do sistema novo** — um pacote logo depois.
- **Fase 5** — a validação independente.
