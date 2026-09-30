# Phase 6 — a lane de rollback aceita uma release de cadeia (`rel-g3-`)

Escrito em 2026-09-29, depois de a página de alertas aprender a ler a release
verde atrás de uma chave (PHASE_6M, site `#28` aberta). Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: é uma mudança pequena, aditiva e já nomeada (PHASE_6K §5), numa lane
> que só alcança o staging. O cuidado é não afrouxar a validação que impede um
> id malformado de virar chave de objeto — alargar um padrão é exatamente onde
> uma validação vira decoração.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:docs/implementation/PHASE_6M_2026-09-29.md | grep -n '^## '

E leia o ponteiro verde, só leitura: tem de nomear uma `rel-g3-`, `/2`. Se não
nomear, o estado mudou — **pare e pergunte**.

Suítes medidas em 2026-09-29: backend **2459** (com este briefing na `main`); site `npm run test:worker`
**88** e `pytest` **220** na branch da `#28` (na `main` do site, 56 e 203
enquanto a `#28` não for mesclada). Rode e use o número que sair.

## 2. O que já foi verificado, para o executor não refazer

- **O gate é só da lane.** `.github/workflows/v2_promotion_lane.yml`, passo
  "Accept only a well-formed release id": `case rel-g1-*`, depois 64 hex
  minúsculos. A função `atomic_publish.rollback` é genérica: carrega o alvo do
  store com `load_published_release` e revalida com `verify_release`, que já
  aceitam a `/3` — é o que a promoção da sequência 15 e 17 usou (PHASE_6K §2).
- **Voltar PARA uma `/3` nunca foi exercitado.** A sequência 16 voltou para uma
  `rel-g1-`; a 17 avançou por promoção de cadeia, não por rollback
  (PHASE_6K §5).
- **Outros padrões `rel-g1-` existem e NÃO são o mesmo gate** — decida cada um
  pelo que ele valida, não pela string:
  - `src/publication/delivery_boundary.py::MEMBER_RELEASE_ID` e
    `site/worker/data_route.js::MEMBER_RELEASE_ID`: um **membro** de uma `/3` é
    sempre `/1` (PHASE_6J §2.4). Correto como está.
  - `src/publication/retention.py::_RELEASE_ID`: valida a reconstrução
    congelada das versões que o store perdeu
    (`config/green_promotion_history_reconstruction_v1.json`). Confira se
    alguma entrada dela poderia ser `/3`; provavelmente não, porque é anterior
    à `/3`.
- **`tests/test_promotion_lane.py::test_a_malformed_release_id_never_reaches_an_object_key`**
  lê o script do passo por string (`"rel-g1-" in script`). Ele vai falhar ao
  alargar — ajuste-o para afirmar o comportamento (ids aceitos e recusados),
  não o texto.

## 3. A tarefa

Fazer `v2_promotion_lane.yml -f mode=rollback -f release_id=rel-g3-…` aceitar
um alvo de cadeia, com a mesma rigidez de hoje: prefixo `rel-g1-` **ou**
`rel-g3-`, seguido de exatamente 64 hex minúsculos, e nada mais (`rel-g2-`
não existe como release publicável — confira em `green_release.py` antes de
decidir).

## 4. O escopo, na ordem em que se sustenta

1. **Procure antes de propor**: o passo da lane, o CLI
   `scripts/publish_green_release.py rollback`, e se o CLI tem validação própria
   de id.
2. **O teste primeiro**: ids aceitos (`rel-g1-` e `rel-g3-` com 64 hex) e
   recusados (`rel-g2-`, 63 e 65 hex, maiúsculas, `rel-g3-../`, vazio), rodando
   o script do passo de verdade (bash) em vez de procurar texto.
3. **A mudança** na lane, e no CLI se ele tiver o mesmo gate.
4. **Prova no staging, se couber no escopo autônomo**: a lane só tem a
   identidade de staging. Um rollback real para a própria `rel-g3-` viva é
   `unchanged` e não escreve nada — é a prova barata de que o gate aceita.
   Um rollback para outra `/3` exigiria haver outra `/3`; não crie uma para
   isto.
5. **Varredura de mutação** no gate novo.

**Fora de escopo:** a virada (trocar `FONTE_PADRAO` no site, rota de produção,
índice no build); a decisão do bucket; a linguagem científica do site
(PHASE_6L §6); a página inicial com alertas de exemplo (PHASE_6M §7) — cada um é
o seu próprio pacote.

## 5. Decisões de escopo já tomadas, com a base

- **Opção H**: estado comprimido e publicação por referência — PHASE_6J.
- **A página lê o verde só por `?dados=verde` até a virada**, padrão em código —
  PHASE_6M §3.
- **`built-from.json` ao lado do índice**, não campo do índice — PHASE_6M §3.
- **`promote` recusa perder uma data publicada** — PHASE_6I §3.
- **Nada é apagado**, nunca.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 6. Fronteiras duras

- **A `main` do site faz deploy de produção.** Não mescle a `#28`: é do dono.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare.
- Claude não recebe credencial de control-plane da Cloudflare; o broker só tem
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Não ligue** `green_site_publish.yml` ao Environment `v2-green-deploy`.
- **Não mescle** `observatorio-site#21`.

## 7. Armadilhas já pagas — não redescobrir

- **Guarda por string é derrotada por paráfrase**: o teste atual da lane lê
  texto; troque por execução do script.
- **Varredura de script ignora comentário**: um `rel-g1-` num comentário do
  YAML não é o gate.
- **Um teste pode passar pelo motivo errado**: pergunte qual mutação cada teste
  derruba.
- **Navegar só trocando o `#hash` não recarrega a página** — medido nesta
  sessão, ao reverificar o site: o navegador mostrou o estado do teste anterior.
- **Copie todo identificador da ferramenta que o produz.**

## 8. Estado que o pacote herda

- **Ponteiro verde:** sequência 17, `/2`, `rel-g3-264ba36e…`, 103 datas até
  2026-09-27.
- **Site:** `#28` aberta — a página lê o verde atrás de `?dados=verde`, fonte só
  Sentinel-2. Não mesclada.
- **Bucket de staging:** 22,029 GB; nada escrito nesta sessão.
- **A produção azul está parada** desde 2026-09-03; o site público mostra dados
  até 30/08.
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da tarefa em si. A página de alertas já sabe mostrar os dados novos,
incluindo setembro, mas só quando alguém pede isso no endereço; para o público
ela continua mostrando a publicação atual. A mudança está esperando a sua
decisão para entrar no ar.

### O que você precisa fazer

1. **Decidir se mescla a mudança do site** (pode esperar). Ao mesclar, o
   público só vê duas coisas diferentes: a página de alertas deixa de dizer que
   usa Landsat, e o assistente de chat também. Os números e o mapa continuam os
   de hoje.
2. **Decidir onde os dados novos vão morar quando forem públicos** (pode
   esperar, mas trava a virada): usar a caixa de testes atual como definitiva,
   ou criar uma nova e copiar para lá. É a mesma pergunta de antes, ainda
   aberta.

### Tem algo preocupante?

Sim, uma coisa: a página inicial do site mostra três alertas **de exemplo** do
desenho original como se fossem reais, porque o arquivo que ela procura não vai
para o ar. Não é novo e não tem relação com esta mudança, mas é informação
falsa na primeira tela. Corrigir é pequeno, e pede a sua aprovação porque muda
o que o público vê. E lembrete: o acesso à NASA para a chuva vence em 6 de
novembro.

### O que ainda falta no caminho

- **Voltar para uma publicação nova, se preciso** — a próxima sessão: hoje só
  dá para voltar para uma publicação antiga do formato anterior.
- **O texto científico da página** — explicar confiança e persistência com a
  contagem nova, e decidir o que mostrar nas quatro datas recusadas.
- **A virada** — o site passa a ler os dados novos por padrão, no próprio
  domínio, e o caminho antigo é desligado.
- **Detecção e publicação agendadas** — ligam na virada.
- **Fase 5** — a validação independente.
