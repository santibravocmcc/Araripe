# Phase 6 — a rota no Worker de produção e o verificador ao vivo

Escrito em 2026-10-13, ao fim da sessão da folha da virada
([`PHASE_6Z`](../implementation/PHASE_6Z_2026-10-13.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: são os passos A2 e A3 de
> [`PHASE_6_CUTOVER_RUNSHEET.md`](PHASE_6_CUTOVER_RUNSHEET.md) — código do
> site cujo merge, mais tarde, é um deploy de produção, e um verificador que só
> lê. O desenho já está decidido nos registros; o erro plausível é um teste de
> configuração que afirma a forma velha e passa, ou um verificador que difere
> do cliente real e prova o errado. **Esta sessão não mescla nada no site.**

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C site fetch origin && git -C site rev-parse origin/main
    git -C Araripe show origin/main:docs/operations/PHASE_6_CUTOVER_RUNSHEET.md | grep -n "DECIDIDA"

- **D0 respondida pelo dono e registrada na folha** (passo A1). Se D0 = (b)
  (rota de zona para o Worker verde), **pare**: este briefing é para (a), e (b)
  exige mudança revisada no broker em tarefa separada. Se D0 não foi
  respondida, pare e pergunte — não presuma (a) porque é a recomendação.
- `PHASE_6Z` na `main` do backend, e `tests/test_phase6_cutover_runsheet.py`.
- `observatorio-site#47`: aberta ou mesclada (`gh pr view 47 -R
  santibravocmcc/observatorio-site --json state`). Se mesclada, parta da `main`
  nova; se aberta, parta da `main` e **não** a empilhe.
- Worktree com os cinco caminhos de dado ligados (memória
  `worktree-novo-nao-tem-o-untracked`). Suíte do backend com o conda
  `araripe`. Base: ver o corpo do commit da PR da PHASE_6Z.

## 2. O que já foi verificado, para o executor não refazer

- **O Worker de produção não serve `/data/green/*`**: `site/wrangler.jsonc`
  sem `r2_buckets`, `run_worker_first: ["/api/*"]`, `worker/index.js` sem
  import de `data_route.js` (PHASE_6Z §3, PHASE_6M §7).
- **O Worker verde é o modelo**: `worker/green.js` encaminha `MOUNT` para
  `handleDataRoute(request, env.STAGING_BUCKET)`; `wrangler.green.jsonc` liga
  `STAGING_BUCKET` → `araripe-v2-staging`.
- `tests/test_green_worker_config.py` (site) afirma hoje que `worker/index.js`
  **não** importa nada de `green.js` e que o Worker de produção não tem R2. A
  mudança inverte uma parte disso de propósito; o teste tem de dizer qual parte
  e por quê, e continuar afirmando o resto (o verde intacto, `/api/chat` e os
  assets iguais).
- **O binding de R2 é CRUD** (documentação da Cloudflare). O código da rota só
  lê; um teste tem de afirmar que `worker/index.js` não chama `put`, `delete`
  nem `createMultipartUpload` no binding — pela AST ou por um parser, não por
  `grep` em comentário.
- **`wrangler dev` verifica sem credencial** (R2 simulado), mas **injeta o
  `.env` do site**: rode com `CLOUDFLARE_LOAD_DEV_VARS_FROM_DOT_ENV=false`.
- **A borda recusou `Python-urllib`** com 403/1010 (memória
  `verificador-que-difere-do-cliente-prova-o-errado`): o verificador usa o
  `User-Agent` de `site_artifact.py`, o cliente real.
- As checagens ao vivo e os valores esperados de 2026-09-27 estão na tabela de
  `PHASE_6B_2026-09-27.md` §2; a lista curta em
  `GREEN_RETENTION_AND_MIGRATION.md` §5.

## 3. A tarefa

**Única tarefa: os passos A2 e A3 da folha, em uma PR do site, não mesclada.**

1. **A2** — `worker/index.js` encaminha `/data/green/*` para `handleDataRoute`
   com `env.STAGING_BUCKET`; `wrangler.jsonc` ganha o binding e
   `run_worker_first: ["/api/*", "/data/green/*"]`. Verificado com `wrangler
   dev` local sobre `tests/fixtures/green-bucket/`.
2. **A3** — `site/scripts/verifica_rota_ao_vivo.py --base <url>`: só GET/HEAD,
   o `User-Agent` do cliente real, sai 1 em qualquer falha. Provado contra o
   `wrangler dev` local: tudo PASS, e uma adulteração da fixture dá FAIL na
   checagem certa.
3. Atualizar o passo A2/A3 da folha com o número da PR (PR do backend, só
   documento).

**Fora de escopo:** mesclar qualquer PR do site; implantar qualquer Worker;
tocar o painel, o broker ou um Environment; os passos A4–A11; Fase 5.

## 4. Decisões de escopo já tomadas, com a base

- **Nada é apagado** — `PACKAGE_P6_PROMPT.md` §5.
- **Nenhuma lane verde tem cron antes da virada** — Package 2B.0, teste.
- **`FONTE_PADRAO` continua `'azul'`** — a troca é o passo B5, em outra PR.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- **A `main` do site faz deploy de produção.** Não mescle.
- Nenhum Environment criado, renomeado ou reconfigurado por agente.
- `detect_gee.yml` e `update_data.yml` nunca são disparados.
- Claude não recebe credencial de control-plane da Cloudflare.

## 6. Armadilhas já pagas — não redescobrir

- `main` no wrangler é relativo ao arquivo de config.
- `node --test tests/` quebra no Node 25: use `npm run test:worker`.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório.
- Varredura de texto pega comentário: use a AST ou `executable_lines()`.
- Uma varredura de mutação: um backup por mutação, restaurado antes da
  seguinte — numa sessão, um caminho de backup errado empilhou as mutações.

## 7. Estado que o package herda

- Ponteiro verde seq. 18 (`rel-g3-76601bbf…`, 107 datas até 2026-10-04).
- `site#47` aberta; `site#42` e `site#21` em rascunho e **em conflito** com a
  `main`.
- O azul parado desde 2026-09-03.
- A lane de status passa a acusar a automação atrasada desde
  2026-10-13T21:19:55Z — esperado até a virada.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. A folha da virada está escrita, e o aviso "dados atrasados" está pronto
para você mesclar quando quiser.

### O que você precisa fazer

1. **Responder às perguntas D0 a D6 da folha da virada** — antes da próxima
   sessão, pelo menos a D0 (de onde o site vai ler os dados novos). Cada uma
   tem a minha recomendação; "sim às recomendações" é uma resposta completa.
   Urgente: a próxima sessão para sem a D0.
2. **Mesclar a mudança do aviso "dados atrasados" no site**, quando quiser.
   Ela só aparece para quem abre a página com a chave de teste; pode esperar.

### Tem algo preocupante?

Sim, uma coisa nova. A página de "Séries" lê um arquivo que só o sistema
antigo produz, e ele está parado desde setembro. Depois da virada essa aba
continua mostrando dado antigo, porque o sistema novo ainda não gera essa
série. Não impede a virada, mas é decisão sua (pergunta D4): virar dizendo a
data da série na página, ou construir a série nova antes.

### O que ainda falta no caminho

- **A ligação dos dados novos no site de produção** — a próxima sessão:
  escrever, sem publicar, a mudança que faz o site do domínio final servir os
  dados novos, e um verificador.
- **A preparação restante da folha** — juntar as mudanças antigas do site com
  a de hoje, preparar a agenda automática, trocar a chave de teste.
- **A virada** — executar a folha, com a sua aprovação em cada passo que mexe
  no site público.
- **Fase 5** — a validação independente.
