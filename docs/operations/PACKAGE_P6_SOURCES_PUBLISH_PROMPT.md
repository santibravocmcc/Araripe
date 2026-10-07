# Phase 6 — publicar as fontes ao lado da release, e servi-las

Escrito em 2026-10-07, ao fim da sessão que desenhou o documento de fontes
([`PHASE_6V`](../implementation/PHASE_6V_2026-10-07.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: toca a fronteira de entrega (o que fica público) e uma lane que
> escreve no staging com a identidade de promoção. O erro plausível é servir o
> documento de fontes quando ele descreve outro contexto ou outra release —
> a página mostraria créditos que não batem com o dado servido.

---

## 0. Pré-condição — a decisão do dono

**Só comece se a PR da PHASE_6V estiver mesclada** (procure por
`git log origin/main --grep 'PHASE_6V'` e confira por conteúdo:
`git show origin/main:src/publication/green_sources.py`). Ela é a forma (b)
— um documento ao lado da release. Se o dono escolheu outra forma, ou ainda
não decidiu, **pare e pergunte**; não reabra a comparação sozinho.

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C site fetch origin && git -C site rev-parse origin/main
    gh pr list -R santibravocmcc/Araripe --state all --limit 6 --json number,state,baseRefName,mergedAt
    gh pr list -R santibravocmcc/observatorio-site --state all --limit 4 --json number,state,baseRefName,mergedAt

- `observatorio-site#42` (ordem dos deploys, rascunho) **não** é pré-requisito.
  Se ainda estiver aberta, ramifique o site da `main` e não empilhe; se tiver
  sido mesclada, o reconciliador dela compara o que está vivo com o que o
  índice foi construído — decida se as fontes entram nessa comparação.
- O checkout compartilhado do `Araripe` pode estar em outra branch com outra
  sessão. Trabalhe num worktree com os cinco caminhos de dado ligados (memória
  `worktree-novo-nao-tem-o-untracked`). A suíte usa o ambiente conda
  `araripe` (`/opt/anaconda3/envs/araripe/bin/python -m pytest`); o `python3`
  do sistema não tem `loguru`.

## 2. O que já foi verificado, para o executor não refazer

- **Onde as fontes moram e por quê**: `GREEN_SOURCES_CONTRACT_V1.md` §1, com
  os testes que medem a recusa do store e dos schemas. Não reabra.
- **O documento contra a release viva** (PHASE_6V §4): o spec e o amarramento
  ao contexto vivo `ctx-g1-e11ea3f3…` passam; o aviso sai "2017–2026"; o id
  previsto é `src-g1-e00e23a4…` com o contexto. **Falta a conferência contra
  os ledgers dos 5 membros** — só a lane os lê.
- `sources/` hoje é **privado** na fronteira e `review` na retenção, por não
  ser classificado (asserido em `tests/test_green_sources.py`).
- O padrão a copiar é o do contexto: `scripts/publish_green_context.py`
  (`fetch` / `plan` / `apply`), `.github/workflows/v2_green_context.yml`
  (Environment `v2-promotion`, só da `main`, concorrência própria,
  `workflow_call` lendo `inputs.mode`), e `_resolve_context` em
  `delivery_boundary.py` com o espelho em `site/worker/data_route.js`.

## 3. A tarefa

**Única tarefa: publicar e servir o documento de fontes — uma lane que o
escreve no staging depois do contexto, a fronteira `delivery/3` que o serve
em `/data/green/sources.json`, e a rota do site que a espelha — e publicar o
primeiro documento, para a release viva, só com o aceite do dono.**

1. **Lane** (`.github/workflows/v2_green_sources.yml`, modos `plan` |
   `publish`, Environment **`v2-promotion`, que já existe** — nunca escreva
   outro nome): `fetch` lê a release viva, o contexto vivo e os ledgers dos
   membros; `plan` roda `plan_green_sources.py` e mostra o documento; `apply`
   faz `put_if_absent` e `sources_pointer.move`. Recusa se o ponteiro verde ou
   o do contexto mudou entre o `fetch` e o `apply`.
2. **Encadear** em `v2_operational_publish.yml`, num job que `needs: context`
   — a ordem vira promover → contexto → fontes → site.
3. **Fronteira `delivery/3`**: `/data/green/sources.json` servido só quando o
   ponteiro de fontes nomeia a release viva **e** o contexto vivo (ou nenhum,
   quando não há contexto vivo); recusas no mesmo formato do contexto
   (`sources_absent`, `sources_not_live`, …); `classify_key` torna público só
   o documento vivo; um cabeçalho `Link: </data/green/sources.json>;
   rel="describedby"` em toda resposta servida. Vetores de conformidade
   atualizados, porque o site os lê.
4. **Rota do site** espelhando a fronteira, numa PR **não mesclada** (a `main`
   do site faz deploy de produção).
5. **Publicar o primeiro documento** — `plan` primeiro, mostrar ao dono o
   texto de atribuição e as lacunas, e só então `publish`, com o aceite dele
   registrado no chat.

**Fora de escopo:** a página ler os créditos do documento (§6.1 do registro:
"UI labels must be derived from that manifest") — é o pacote seguinte, porque
a página só pode ler o que já é servido; trocar os recortes de 2023 (Phase 5);
a licença dos produtos (decisão do dono); a virada.

## 4. Decisões de escopo já tomadas, com a base

- **Forma (b)** — PHASE_6V §3, condicionada ao merge (§0 acima).
- **Nada é apagado e nenhuma release é reescrita** — `PACKAGE_P6_PROMPT.md` §5.
- **Publicação sem revisor** — a P1 foi retirada pelo dono em 2026-10-02
  (`config/phase6_publication_authority_v1.json`); a lane usa a identidade de
  promoção como a do contexto.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- **A `main` do site faz deploy de produção.** Não mescle PR do site.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare.
- Claude não recebe credencial de control-plane da Cloudflare; o broker só tem
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Nenhum Environment é criado, renomeado ou reconfigurado por agente**, e
  escrever `environment:` com um nome inexistente CRIA um. Nunca aprove um
  Environment.
- Escrever no staging só pela lane, só no modo `publish`, e só depois do
  aceite do dono para o primeiro documento.

## 6. Armadilhas já pagas — não redescobrir

- **Um guarda de inventário vai falhar** quando a lane e o módulo novo
  entrarem: `test_landing_preserves_both_sides` (módulos, workflows e scripts
  de publicação) e o H2 de `test_promotion_history` (escritores de ponteiro).
  É o guarda funcionando: acrescente com o motivo, não afrouxe.
- **Chamada por `workflow_call`, o contexto `github` é do chamador**: leia o
  modo de `inputs.mode`, como `v2_green_context.yml` faz.
- **O documento só é função do id enquanto a regra de derivação não muda**:
  qualquer mudança em `green_sources.derive` exige trocar `DERIVATION` e
  regenerar os vetores — nunca só o digest.
- **Uma varredura de mutação tem de apagar `__pycache__` antes de cada
  execução**; e varredura de texto pega docstring — use a AST.
- **O hook `commit-msg` recusa um SHA de 40 caracteres de OUTRO repositório.**

## 7. Estado que o package herda

- **Ponteiro verde:** sequência 17, `rel-g3-264ba36e…`, 103 datas até
  2026-09-27; contexto `ctx-g1-e11ea3f3…` vivo para ela.
- **Fontes:** nenhum documento publicado; `sources/` vazio no staging.
- **`observatorio-site#42`** em rascunho.
- **A produção azul está parada** desde 2026-09-03.
- **O token da NASA expira em 2026-11-06.**

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da tarefa. Ficou pronto, mas guardado, o jeito de cada publicação levar
junto a lista de onde vêm os dados e os créditos que as licenças pedem. Nenhuma
publicação foi mudada e nada novo foi publicado.

### O que você precisa fazer

1. **Decidir se aprova a forma proposta** — a lista de fontes num documento
   separado, ao lado de cada publicação, em vez de dentro dela. Aprovar é
   mesclar a PR desta sessão. Não muda nada para o público. Pode esperar, mas
   a próxima sessão depende disso.
2. **Opcional: dizer de onde e quando baixou o mapa MapBiomas de 2023** (o de
   10 metros, Coleção 2 beta), se lembrar. Três das sete lacunas registradas
   fecham com essa informação.
3. **Renovar o acesso à NASA antes de 6 de novembro** (até o fim de outubro).
   Sem isso a atualização da chuva para.

### Tem algo preocupante?

Não. A publicação de hoje continua sem a lista de fontes até a próxima
sessão, mas os créditos já aparecem no site onde o dado aparece.

### O que ainda falta no caminho

- **Publicar e servir a lista de fontes** — a próxima sessão, depois do seu
  aceite.
- **A página ler os créditos dessa lista**, em vez de tê-los escritos à mão.
- **A virada** — o site passa a mostrar os dados novos para todo mundo, a caixa
  de testes vira a definitiva, a reconstrução automática é ligada, e o caminho
  antigo é desligado.
- **Fase 5** — a validação independente, que também decide se o mapa de uso do
  solo de 2023 dá lugar a um mais novo.
