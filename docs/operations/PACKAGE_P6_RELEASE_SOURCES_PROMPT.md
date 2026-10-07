# Phase 6 — a publicação diz de onde vêm os dados

Escrito em 2026-10-07, ao fim da sessão que desenhou a ordem dos deploys
([`PHASE_6U`](../implementation/PHASE_6U_2026-10-07.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: é mudança de contrato sobre um objeto **imutável e citável**. O
> erro plausível é acrescentar um campo ao `release.json` que parece inócuo e
> quebra a identidade da release — mesmo id, bytes diferentes, e o store
> recusa ou, pior, duas releases passam a afirmar coisas diferentes com o
> mesmo nome. Pede leitura do código de identidade antes de escrever.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C site fetch origin && git -C site rev-parse origin/main
    gh pr list -R santibravocmcc/Araripe --state all --limit 6 --json number,state,baseRefName,mergedAt
    gh pr list -R santibravocmcc/observatorio-site --state all --limit 4 --json number,state,baseRefName,mergedAt

- **`Araripe#102`** (contexto depois da promoção) e **`observatorio-site#42`**
  (ordem dos deploys, rascunho) **não são** pré-requisito desta tarefa. Se
  estiverem abertas, ramifique da `main` e não empilhe. Se a `#102` tiver sido
  mesclada, `v2_operational_publish.yml` tem um terceiro job, `context`.
- Suítes medidas em 2026-10-07: backend `pytest` **2655** na `main` (2660 com a
  `#102`), num worktree com os 5 caminhos de dado ligados — sem eles, 6 falhas e
  14 erros de ambiente (memória `worktree-novo-nao-tem-o-untracked`). Site:
  `npm run test:worker` **184** e `pytest` com `/opt/anaconda3/bin/python3.12`
  **245** na `main` (189 / 288 com a `#42`).

## 2. O que já foi verificado, para o executor não refazer

- **O pedido existe e está escrito**: o
  [registro de fontes](../contracts/phase1/DATA_SOURCE_AND_ATTRIBUTION_REGISTER_2026-07-24.md)
  §3.3 diz que *"the release manifest and every public UI/download that uses
  these sources must carry"* a atribuição, e §6.1 repete; a adição A4 de
  2026-10-04 registra que `release.json` não carrega nenhuma.
- **O que o verde usa de fato**, lido do código em 2026-10-04 (PHASE_6T §2):
  Sentinel-2 L2A (`COPERNICUS/S2_SR_HARMONIZED`) e os recortes MapBiomas de
  2023 na anotação da release; e, desde 2026-10-06, a camada de contexto com o
  MapBiomas 2025 (Coleção 4 de 10 m, Coleção 11 de 30 m), ao lado da release
  (`GREEN_CONTEXT_CONTRACT_V1.md`). CHIRPS **não** é usado
  (`drought.operationally_applied: false`).
- **A armadilha central, já medida em outra forma**: `release_identity`
  (`src/publication/green_release.py`) depende **só** do ledger — id do ledger,
  do manifesto de rodada, e os dois digests. Reanotar a release dava as mesmas
  chaves com bytes diferentes, e foi por isso que o contexto virou camada
  separada (memória `araripe-indice-do-site-e-derivado`; contrato do contexto
  §1). Um campo `sources` no mesmo `release.json` cai exatamente nisso.
- O schema vivo da release por referência é `araripe.green.release/3`
  (`REFERENCE_RELEASE_SCHEMA`, `src/publication/chain_release.py`); os schemas
  estão em `docs/contracts/phase2b/schemas/green-release-v{1,2,3}.schema.json`.
- O site já mostra os créditos onde o dado aparece (`site#38`, mesclada); o que
  falta é a **publicação** carregá-los, para que um download fora do site leve
  a atribuição junto.

## 3. A tarefa

**Única tarefa: desenhar e implementar, numa branch, como uma publicação verde
passa a carregar as suas fontes e atribuições — sem mudar a identidade de
nenhuma release existente — e propor ao dono, com recomendação.**

1. **Meça antes de escolher**: o que exatamente entra em `release_identity` e
   em cada `*_identity` da cadeia; se o store recusaria um `release.json`
   diferente sob a mesma chave (`ImmutableObjectConflict`); e quais
   consumidores leem `release.json` (rota do site, compositor, `status`,
   `history`, rollback).
2. **Compare pelo menos estas duas formas**, com recomendação:
   (a) uma versão nova do schema (`release/4`) cuja identidade inclua as
   fontes, para releases **futuras**; (b) um documento de fontes **ao lado** da
   release, por conteúdo e com ponteiro próprio, como o contexto. Diga o que
   cada uma faz com a `rel-g3-…` que está viva hoje e com uma citação científica
   que nomeie uma release.
3. **Implemente a recomendada numa branch**, com os vetores e o schema, e
   **pare antes de publicar** qualquer objeto: publicar é decisão do dono.

**Fora de escopo, explicitamente:** trocar a coleção MapBiomas da anotação
(**Phase 5**); a virada; qualquer afirmação de acurácia (**Phase 5**); a licença
dos produtos do projeto (decisão do dono, PHASE_6T §4.5); mexer nas PRs `#102`
e `site#42`.

## 4. Decisões de escopo já tomadas, com a base

- **Nada é apagado e nenhuma release é reescrita** — `PACKAGE_P6_PROMPT.md` §5;
  um artigo cita uma release.
- **Contexto MapBiomas 2025 é camada ao lado da release**, não reanotação —
  decisão do dono de 2026-10-06 (`GREEN_CONTEXT_CONTRACT_V1.md`).
- **P2 = (a)**, e a ordem dos deploys está desenhada (PHASE_6U): cada
  publicação nova chega à página pelo reconciliador do site.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- **A `main` do site faz deploy de produção.** Não mescle PR do site.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare.
- Nenhuma escrita no bucket de staging nesta tarefa — desenho e branch.
- Claude não recebe credencial de control-plane da Cloudflare; o broker só tem
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Nenhum Environment é criado, renomeado ou reconfigurado por agente**, e
  escrever `environment:` com um nome inexistente CRIA um. Nunca aprove um
  Environment.

## 6. Armadilhas já pagas — não redescobrir

- **Duas canonicalizações não são a mesma**: `json.dumps` e a RFC 8785
  discordam em `1.0`/`1`; documento assinado não leva float.
- **O índice do site é derivado, não selado**: nada de regra mutável vira
  objeto de release.
- **O Python da imagem do Workers Builds não tem `_sqlite3`** (PHASE_6U §2): se
  esta tarefa tocar o compositor do site, ele não pode importar nada que o
  arraste.
- **Uma varredura de mutação tem de apagar `__pycache__` antes de cada
  execução**; e varredura de texto pega docstring — use a AST.
- **O hook `commit-msg` recusa um SHA de 40 caracteres de OUTRO repositório.**

## 7. Estado que o package herda

- **Ponteiro verde:** sequência 17, `rel-g3-264ba36e…`, 103 datas até
  2026-09-27; contexto `ctx-g1-e11ea3f3…` vivo para ela (forte 75 796).
- **`Araripe#102`** aberta: contexto publicado logo depois de cada promoção.
- **`observatorio-site#42`** em rascunho: o build compõe o índice atrás de
  `COMPOR = False`, o reconciliador, a recusa sem azul.
- **A produção azul está parada** desde 2026-09-03.
- **O token da NASA expira em 2026-11-06.**

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da tarefa. Ficou desenhado e pronto, em duas propostas, o caminho para
que cada publicação nova apareça no site sozinha: o site confere a cada três
horas se o que está publicado mudou e, se mudou, se reconstrói. E, quando a
página não puder mostrar os alertas, ela diz por quê em vez de mostrar a versão
antiga. Nada disso está ligado: as duas propostas esperam você.

### O que você precisa fazer

1. **Mesclar a PR 102 do monitoramento** — faz o mapa de uso do solo de 2025
   ser publicado logo depois de cada publicação, em vez de depender de alguém
   lembrar. Pode esperar, mas tem de entrar antes da virada.
2. **Decidir quando mesclar a PR 42 do site**, que está em rascunho. Mesclar
   agora não muda nada para o público; custa só uns 240 minutos por mês da cota
   de automação do GitHub, à toa até a virada. Recomendo mesclar junto com o
   passo da virada que liga a reconstrução automática.
3. **Renovar o acesso à NASA antes de 6 de novembro** (até o fim de outubro).
   Sem isso a atualização da chuva para.
4. **Cancelar a chave de acesso que o assistente usa na caixa de testes** — só
   perto da virada, não agora.

### Tem algo preocupante?

Sim, um, e já resolvido na proposta: o computador da Cloudflare que monta o
site não tem uma peça que o programa dos alertas usava, e a primeira montagem
depois da virada teria falhado. Só apareceu porque testei lá dentro. A correção
está na PR 42 do site; se a virada acontecer sem ela, o site não se atualiza.

### O que ainda falta no caminho

- **Os dados dizerem de onde vêm** — cada publicação levar junto a lista de
  fontes e créditos, sem mudar as publicações que já existem. É a próxima
  sessão.
- **A virada** — o site passa a mostrar os dados novos para todo mundo, a caixa
  de testes vira a definitiva, a reconstrução automática é ligada, e o caminho
  antigo é desligado.
- **Fase 5** — a validação independente, que também revê a data de maio que
  ficou a um fio do mínimo.
