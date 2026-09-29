# Phase 6 — os produtos do site a partir da release verde viva

Escrito em 2026-09-29, depois de a release da cadeia por referência ser
promovida no staging e a volta provada (PHASE_6K). Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: é a primeira mudança que o público vai **ver**. O dado está pronto e
> verificado; o risco agora é o site dizer algo que o dado não sustenta — uma
> fonte errada, uma data confundida com outra, um número de "confirmados" que
> não é o que a política conta. E a `main` do site faz deploy de produção.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:docs/implementation/PHASE_6K_2026-09-29.md | grep -n '^## '

E leia o ponteiro verde, só leitura: tem de nomear uma `rel-g3-`, `/2`, com a
cobertura até 2026-09-27 ou além. Se não nomear, a promoção foi desfeita —
**pare e pergunte**.

Suíte medida em 2026-09-29: backend **2449**; site `npm run test:worker`
**56**, `pytest` **203**. Rode e use o número que sair.

## 2. O que já foi verificado, para o executor não refazer

- **A release viva** (PHASE_6K): `rel-g3-264ba36e…`, 103 datas de
  2026-01-02 a 2026-09-27, cinco membros, 84 objetos; setembro tem alertas em
  09-09, 09-11, 09-14, 09-19, 09-21 e 09-24.
- **O compositor do site já compõe uma `/3` sem mudança** (PHASE_6I §8, e a
  rota da `/3` provada em PHASE_6J §3.2): `scripts/site_artifact.py` lê
  `dates[]`/`objects[]` e busca os objetos pela rota.
- **A rota verde `/data/green/…`** está no Worker verde (versão
  `cf1915ab-…`), sem hostname; a verificação por HTTP exige o dono abrir a
  janela `workers.dev`.
- **O site hoje declara "SENTINEL-2 L2A · LANDSAT 8/9"** e o sistema não usa
  Landsat: 4 lugares no site, e o 3º é o compositor verde
  (`site/scripts/site_artifact.py::_source_line`).

## 3. A tarefa

O primeiro bullet da Phase 6 no roadmap — *"Generate site full, strong,
point-index, chart, and download products from the staged release manifest"*
— para a página de alertas, **atrás de uma chave**: a página continua lendo o
caminho azul por padrão, e passa a poder ler a release verde pela rota de
mesma origem quando a chave estiver ligada. Mais as correções de fonte.

## 4. O escopo, na ordem em que se sustenta

1. **Procure antes de propor**: `SITE_ARTIFACT_CONTRACT_V1.md` §6c (ligar a
   página a `object_base` foi deixado explicitamente para a Phase 6),
   `green_site_publish.yml` e o seu teste, e o topic table do roadmap.
2. **Escreva a decisão antes do código**: como a página escolhe azul ou verde
   sem que um deploy de produção mude o que o público vê até a virada; o que
   acontece quando a rota verde falha.
3. **Corrija a fonte** — Sentinel-2 apenas — nos quatro lugares, com teste.
4. **O código e os testes**, com a varredura de mutação; `npm run build`.
5. **A PR do site fica aberta** para o dono: o merge publica no domínio
   final. Mesclar é decisão dele, nesta etapa, mesmo com a autorização de
   2026-09-29 — aquela era para mudanças que o público não via.

**Fora de escopo:** o agendamento e a virada; a linguagem científica completa
(confiança, persistência, MapBiomas) além da fonte; a validação de acurácia
(Phase 5); alargar a lane de rollback para alvo `rel-g3-` (PHASE_6K §5 — um
pacote pequeno próprio).

## 5. Decisões de escopo já tomadas, com a base

- **Opção H**: estado comprimido e publicação por referência — PHASE_6J.
- **A release pública é uma só, e o site a lê pela rota de mesma origem** —
  PHASE_6I §1, `SITE_ARTIFACT_CONTRACT_V1.md` §6c.
- **`promote` recusa perder uma data publicada** — PHASE_6I §3.
- **Nada é apagado**, nunca.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 6. Fronteiras duras

- **A `main` do site faz deploy de produção.** Nesta etapa o merge é do dono.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare.
- Claude não recebe credencial de control-plane da Cloudflare; o broker só tem
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Não ligue** `green_site_publish.yml` ao Environment `v2-green-deploy`.
- **Não mescle** `observatorio-site#21` antes da Phase 6 estar pronta para
  isso: medido, tirar a re-inclusão dá 404 na data mais recente.

## 7. Armadilhas já pagas — não redescobrir

- **O clone local do site pode estar noutra branch**: rode o compositor da
  `main` com `git archive origin/main scripts worker | tar -x` fora do clone.
- **`node --test tests/` quebra no Node 25**: use `npm run test:worker`.
- **`wrangler dev` injeta o `.env` do repo**, com chaves de produção: desligue
  com `CLOUDFLARE_LOAD_DEV_VARS_FROM_DOT_ENV=false`.
- **Um verificador com User-Agent próprio prova o errado**: a borda da
  Cloudflare respondeu 403/1010 ao cliente real.
- **Copie todo identificador da ferramenta que o produz.**

## 8. Estado que o pacote herda

- **Ponteiro verde:** sequência 17, `/2`, `rel-g3-264ba36e…`.
- **Cadeia:** cinco rodadas, até 2026-09-27; estado comprimido desde
  `ci-36587297892`. Nenhum `schedule:`.
- **Bucket de staging:** 22,029 GB.
- **A produção azul está parada** desde 2026-09-03; o site público mostra dados
  até 30/08.
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. Os dados de setembro estão publicados na caixa de testes: a publicação
nova junta os oito meses antigos e setembro, sem copiar nada, e foi conferida
arquivo por arquivo. Também testamos voltar para a versão anterior e avançar
de novo, e as duas coisas funcionaram.

### O que você precisa fazer

1. **Nada agora.** Quando quiser seguir, abra a próxima sessão com este
   documento. Ela vai preparar o site para ler os dados novos e tirar a menção
   ao Landsat, e vai deixar a mudança esperando você aprovar, porque essa é a
   primeira que o público vai ver.

### Tem algo preocupante?

Não. O site público continua como estava; tudo o que mudou hoje está na caixa
de testes.

### O que ainda falta no caminho

- **O site ler os dados novos** — a próxima sessão, com a sua aprovação no fim.
- **Detecção e publicação agendadas** — ligam na virada.
- **A virada** — o site passa a ler os dados novos no próprio domínio, e o
  caminho antigo é desligado.
- **Fase 5** — a validação independente.
