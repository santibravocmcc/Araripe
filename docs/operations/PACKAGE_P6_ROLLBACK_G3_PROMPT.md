# Phase 6 — a lane de rollback aceita uma release de cadeia (`rel-g3-`), e a página inicial deixa de mostrar alertas de exemplo

Escrito em 2026-09-29, depois de a página de alertas aprender a ler a release
verde atrás de uma chave (PHASE_6M, site `#28` aberta). **Ampliado em
2026-09-30 a pedido do dono**: a correção da página inicial (PHASE_6M §7) entra
nesta sessão como a segunda tarefa. Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: são duas mudanças pequenas e já nomeadas. A primeira (PHASE_6K §5) é
> numa lane que só alcança o staging, e o cuidado é não afrouxar a validação
> que impede um id malformado de virar chave de objeto — alargar um padrão é
> exatamente onde uma validação vira decoração. A segunda muda o que o público
> vê na primeira tela do site, então termina numa PR que o dono mescla.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git fetch origin
    git rev-parse origin/main
    git show origin/main:docs/implementation/PHASE_6M_2026-09-29.md | grep -n '^## '

E leia o ponteiro verde, só leitura: tem de nomear uma `rel-g3-`, `/2`. Se não
nomear, o estado mudou — **pare e pergunte**.

E o estado das PRs do site, porque ele muda as contagens e o arquivo da
segunda tarefa:

    gh pr view 28 --repo santibravocmcc/observatorio-site --json state,mergedAt
    gh pr view 26 --repo santibravocmcc/observatorio-site --json state,mergedAt

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
- **A página inicial mostra alertas de exemplo como reais** (PHASE_6M §7,
  medido no `dist/`, sem requisição à produção):
  `site/src/js/home.js::cardsReais` busca `/data/alerts/${ultima.file}`, isto
  é `run-<data>.geojson`, o completo. Ele nunca entra no deploy — o
  `.gitignore` do site exclui `public/data/alerts/run-*.geojson` exceto
  `*.strong.geojson`, e `dist/data/alerts` só tem `manifest.json`,
  `all-strong-points.json` e os `.strong`. O `fetch` leva 404, o `catch` mantém
  o markup, e `index.html` (`#home-alert-cards`) mostra três exemplos do design
  — `ALT-0192 · 4,2 ha · sul de Araripina · 22 abr`, `ALT-0191`, `ALT-0190` —
  como se fossem alertas.
- **As PRs `#28` e `#26` do site mesclam juntas sem conflito**, medido em
  2026-09-30 num worktree temporário (`main` + `#28` + `#26`): `npm run
  test:worker` 88, `pytest` 224. A `#26` corrige o `User-Agent` do
  `RouteReader` (a borda da Cloudflare devolvia 403/1010) e não está na `main`
  (`git show origin/main:scripts/site_artifact.py | grep -c USER_AGENT` → 0).
- **`#21` continua não-mesclável**: medido antes, tirar a re-inclusão dá 404
  na data mais recente e o job sai 0 (ver a memória do projeto e
  PACKAGE_P6_PROMPT §4.4). Ela é da virada.
- **A decisão do bucket (PACKAGE_P6_PROMPT §3)**: o dono inclinou-se, em
  2026-09-30, pela opção (a) — o bucket de staging vira o definitivo — e ainda
  não confirmou. A análise que embasou a recomendação está em §5-bis. Não a
  trate como decidida até o dono confirmar.

## 3. A tarefa

Fazer `v2_promotion_lane.yml -f mode=rollback -f release_id=rel-g3-…` aceitar
um alvo de cadeia, com a mesma rigidez de hoje: prefixo `rel-g1-` **ou**
`rel-g3-`, seguido de exatamente 64 hex minúsculos, e nada mais (`rel-g2-`
não existe como release publicável — confira em `green_release.py` antes de
decidir).

**E, em seguida, a página inicial** (repositório do site): fazer
`cardsReais` ler o subconjunto forte que É publicado, e trocar os três
exemplos do markup por um estado neutro que não finja ser alerta.

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
6. **A página inicial**, numa branch do site a partir de `origin/main`
   (depois de conferir o estado da `#28` pelo §1):
   - `cardsReais` busca `ultima.file_strong` (com `ultima.file` só se
     `file_strong` faltar, como `alertas.js` faz). Os três cartões passam a
     ser os três maiores **fortes** da última execução — diga isso na PR,
     porque hoje o critério declarado é "confiança, depois área" sobre todos;
   - o markup de `#home-alert-cards` deixa de ter alertas inventados: um
     estado neutro ("carregando os alertas mais recentes…") que o `catch`
     mantém se o `fetch` falhar;
   - um teste que afirma que o caminho que `home.js` pede para a última
     execução do manifesto **existe** em `public/data/alerts/`, e que o markup
     não tem `ALT-` literal;
   - `npm run test:worker`, `pytest`, `npm run build`, e verificação no
     navegador (servidor de preview do `.claude/launch.json` do site);
   - **PR aberta, não mesclada**: muda a primeira tela do site público.
   - O "Baixar" de cada execução na aba Downloads de `alertas.html` tem o
     mesmo defeito no azul. Se a `#28` já estiver mesclada, corrija junto
     (o link azul vira o `.strong`, rotulado como tal); se não, só registre —
     a `#28` mexe no mesmo arquivo.

**Fora de escopo:** a virada (trocar `FONTE_PADRAO` no site, rota de produção,
índice no build); a decisão do bucket; a linguagem científica do site
(PHASE_6L §6) — cada um é o seu próprio pacote.

## 5. Decisões de escopo já tomadas, com a base

- **Opção H**: estado comprimido e publicação por referência — PHASE_6J.
- **A página lê o verde só por `?dados=verde` até a virada**, padrão em código —
  PHASE_6M §3.
- **`built-from.json` ao lado do índice**, não campo do índice — PHASE_6M §3.
- **`promote` recusa perder uma data publicada** — PHASE_6I §3.
- **Nada é apagado**, nunca.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5-bis. A recomendação do bucket, para quando o dono confirmar

Recomendado ao dono em 2026-09-30: **(a), o bucket de staging vira o
definitivo**, com três condições. Por quê:

- **A opção H mora num bucket só.** A `/3` é um índice que referencia as `/1`
  de cada rodada nos seus prefixos (PHASE_6J). Com um bucket final separado
  (b), cada promoção teria de copiar os membros entre buckets — perde a
  economia que motivou a H (a mesma promoção pela `/2` copiaria ~1,86 GB,
  PHASE_6K §4) e acrescenta um caminho de cópia a construir e provar.
- **(b) não tira o DELETE do bucket público.** No R2 escrever inclui apagar e o
  escopo é por bucket (medido em 2026-09-07). A identidade que promove teria
  de escrever no bucket final, então teria DELETE lá do mesmo jeito. O limite
  continua sendo o código (`ConditionalStore` sem delete).
- **O lixo de sandbox não é exposto.** A rota só serve o que a release viva
  declara; prefixos de probe e fixture são inalcançáveis por construção.

As condições, todas antes da virada:

1. **Revogar a chave local `claude-araripe-v2-staging-rw`** — a lane de
   depósito já existe, então nada depende dela; o documento
   `CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md` manda revogá-la antes de mudar o
   papel do bucket.
2. **Revisor obrigatório no Environment `v2-promotion`**: a base de não ter
   revisor era "é um sandbox" (PACKAGE_P6_PROMPT §2f). O repositório do
   backend é público, então revisor de Environment está disponível aqui (ao
   contrário do site).
3. **Reescrever `CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md`**, que hoje diz que o
   bucket *não* é canônico, e registrar a decisão em PACKAGE_P6_PROMPT §3.

Nada disso é desta sessão: é o que a decisão implica quando for tomada.

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
  Sentinel-2; `#26` aberta — o `User-Agent` do compositor; as duas mesclam
  juntas (§2). `#21` em rascunho, não mesclar. O merge das três é do dono.
- **Bucket de staging:** 22,029 GB; nada escrito nesta sessão.
- **A produção azul está parada** desde 2026-09-03; o site público mostra dados
  até 30/08.
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da tarefa em si. A página de alertas já sabe mostrar os dados novos,
incluindo setembro, mas só quando alguém pede isso no endereço; para o público
ela continua mostrando a publicação atual. A correção da página inicial entrou
na próxima sessão, como você pediu.

### O que você precisa fazer

1. **Mesclar a mudança da página de alertas e depois a correção do
   compositor** (pode esperar, mas ajuda a próxima sessão). As duas foram
   testadas juntas e passam. Ao mesclar, o público só nota que a página e o chat
   deixam de citar Landsat.
2. **Não mesclar a mudança marcada "não mescle ainda"**: ela é da virada, e
   hoje faria sumir o arquivo da data mais recente.
3. **Confirmar a escolha do bucket** (pode esperar, trava a virada). A
   recomendação é usar a caixa de testes atual como definitiva, com três
   cuidados antes da virada: cancelar a chave de acesso que o assistente usa
   hoje, exigir sua aprovação em cada publicação, e reescrever o documento que
   hoje chama a caixa de descartável.
4. **Renovar o acesso à NASA antes de 6 de novembro** (até o fim de outubro).
   Sem isso a atualização da chuva para.

### Tem algo preocupante?

Sim, uma coisa: a página inicial mostra três alertas de exemplo como se fossem
reais. Não é novo, e a próxima sessão já prepara a correção; ela só entra no ar
quando você mesclar. E o prazo da NASA acima.

### O que ainda falta no caminho

- **Poder voltar para uma publicação nova, se preciso** — a próxima sessão.
- **A página inicial sem alertas de exemplo** — a próxima sessão, com a sua
  aprovação no fim.
- **O texto científico da página** — explicar confiança e persistência com a
  contagem nova, e decidir o que mostrar nas quatro datas recusadas.
- **A virada** — o site passa a mostrar os dados novos para todo mundo, e o
  caminho antigo é desligado.
- **Detecção e publicação automáticas** — ligam na virada.
- **Fase 5** — a validação independente.
