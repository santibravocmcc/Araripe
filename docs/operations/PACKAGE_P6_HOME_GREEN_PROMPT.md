# Phase 6 — a página inicial lendo a release verde

Escrito em 2026-10-02, ao fim da sessão que pôs as três datas na página de
alertas ([`PHASE_6R`](../implementation/PHASE_6R_2026-10-02.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: é a mesma porta que a página de alertas já fez, para um módulo de
> 42 linhas, com testes e vetores prontos. O erro plausível é de desenho
> pequeno, não de ciência: a página inicial abrir uma segunda chave ou um
> segundo caminho de leitura verde em vez de reutilizar o que
> `alertas-fonte.js` já confere.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C site fetch origin
    git -C site grep -n "export async function leBatimento" origin/main -- src/js/alertas-fonte.js
    gh pr list -R santibravocmcc/observatorio-site --state all --limit 3 --json number,state,baseRefName,mergedAt

- **`observatorio-site#34`** (as três datas) **não é** pré-requisito desta
  tarefa: a página inicial não mostra o batimento. Se ela ainda estiver
  aberta, ramifique da `main` do site e **não** a empilhe — uma PR empilhada
  mesclada sem trocar a base não chega à `main`.
- Se ela já estiver na `main` (o `grep` acima acha a linha), as suítes são as
  da linha seguinte.

Suítes medidas em 2026-10-02 na branch da `site#34`: `npm run test:worker`
**134**, `pytest` **240** com `/opt/anaconda3/bin/python3.12`; na `main` do site
sem ela, **124** e 240. Backend **2604**. Use o número que sair.

## 2. O que já foi verificado, para o executor não refazer

- **O estado de hoje.** `site/src/js/home-alertas.js` lê só o azul
  (`AZUL.indice` e o `.strong` da última execução) e diz isso no comentário:
  *"a página inicial não tem a chave `?dados=verde`"*. `src/js/home.js:72`
  chama `alertasDaHome(fetch)` e, em falha, mostra uma frase — nunca alerta de
  exemplo (`site#29`).
- **O verde já tem toda a E/S conferida** em `src/js/alertas-fonte.js`:
  `abreFonte(fetch, location.search)` decide a fonte uma vez, confere
  ponteiro × índice × `built-from.json` e a release de cada objeto, e devolve
  `ultima` e `primeira` (as feições fortes traduzidas da execução mais
  recente). É exatamente o que os cartões da página inicial precisam.
- **As propriedades batem.** `normalizaVerde` produz `id`, `conf`, `area_ha`,
  `near`, `date` — as cinco que `home.js` desenha.
- **O link do cartão** vai para `/alertas.html#alerta-<id>`. Na visão verde,
  sem `?dados=verde` no link, a página de alertas abriria o **azul** e o
  deep link não acharia o id verde (os ids verdes vêm do `observation_id`,
  `idDoAlerta`). O link tem de carregar a mesma fonte.
- **A §4.1 de `PACKAGE_P6_PROMPT.md`, item 2,** registra este pedaço como o
  que falta: *"não para a página inicial"*.

## 3. A tarefa

**Única tarefa: com `?dados=verde`, os cartões de alerta da página inicial
vêm da release verde, pela mesma porta conferida da página de alertas; sem
ele, nada muda.**

1. Leia `src/js/home-alertas.js`, `src/js/home.js` (os cartões) e
   `tests/home_alertas.test.mjs`.
2. Reutilize `abreFonte` — não escreva outra leitura do ponteiro ou do
   índice. Se o verde for recusado, a página inicial cai no azul como a de
   alertas cai, e o console diz por quê.
3. O link de cada cartão leva a fonte junto (`?dados=verde`) quando ela é
   verde.
4. Teste com `npm run test:worker`, e sobre HTTP com
   `scripts/preview_green.mjs` (o PHASE_6R §4 tem o espelho em scratch que
   funcionou: `tests/fixtures/green-release` copiada para
   `releases/<id>/`, e o ponteiro com `release_path` acrescentado).

**Fora de escopo, explicitamente:** trocar o padrão para verde (é a virada);
o "cair no azul" (a §4.4 decide); a rolagem horizontal de `nav.site-nav` em
375 px (achado do PHASE_6R, de outra tarefa); abrir os portões 2 e 3; agendar
a lane; qualquer mutação de produção; o limiar de maio (**Phase 5**).

## 4. Decisões de escopo já tomadas, com a base

- **O verde só por `?dados=verde` até a virada** — PHASE_6M §3; e a virada é
  um diff de uma linha em `FONTE_PADRAO`, que a página inicial tem de seguir
  sozinha, sem uma segunda chave.
- **Nunca alerta de exemplo no lugar de um real** — `site#29`.
- **Nada é apagado**, nunca.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- **A `main` do site faz deploy de produção.** Não mescle PR do site.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare.
- Claude não recebe credencial de control-plane da Cloudflare; o broker só tem
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Nenhum Environment é criado, renomeado ou reconfigurado por agente.**
- O agente age com a conta do dono no GitHub: **nunca aprove um Environment**.

## 6. Armadilhas já pagas — não redescobrir

- **Uma PR empilhada mesclada sem trocar a base não chega à `main`**; confira
  `baseRefName`.
- **O `pytest` do site com Python 3.11** falha num teste de soma; use o 3.12.
- **`node --test tests/` quebra no Node 25**; use `npm run test:worker`.
- **O guarda de `alertas.js` ignora comentários de linha inteira**; se você
  escrever um guarda parecido para `home.js`, faça o mesmo — uma menção num
  comentário não é uma requisição.
- **O hook `commit-msg` recusa um SHA de 40 caracteres de OUTRO repositório.**

## 7. Estado que o package herda

- **Ponteiro verde:** sequência 17, `rel-g3-264ba36e…`, 103 datas até
  2026-09-27.
- **Batimento:** em `status/green/heartbeat.json` no staging, último
  `ci-37021850688 no_acquisition`. Nada foi promovido nem depositado nesta
  sessão.
- **O worker verde de staging** não foi reimplantado depois da `site#33`; ele
  não serve o batimento até alguém com a autoridade do portão 2 reimplantá-lo.
- **A produção azul está parada** desde 2026-09-03; o site público mostra
  alertas até 30/08.
- **O token da NASA expira em 2026-11-06.**

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da tarefa. A página de alertas, no modo de teste dos dados novos, agora
mostra separadas a última imagem analisada, a última data com alertas e a
última vez que a automação tentou rodar. Está numa PR do site, esperando você.

### O que você precisa fazer

1. **Mesclar a PR 34 do site, que põe as três datas na página** — pode
   esperar; o público não vê diferença, porque a mudança só aparece no modo de
   teste.
2. **Renovar o acesso à NASA antes de 6 de novembro** (até o fim de outubro).
   Sem isso a atualização da chuva para.
3. **Cancelar a chave de acesso que o assistente usa na caixa de testes** —
   só perto da virada, não agora.

### Tem algo preocupante?

Nada novo. Continuam valendo os dois avisos de antes: depois da virada, cada
atualização automática só aparece na página quando o site é reconstruído — e
isso precisa estar resolvido antes da virada —, e o prazo da NASA acima.

### O que ainda falta no caminho

- **A página inicial lendo os dados novos** — a próxima sessão.
- **A ordem das atualizações depois da virada** — o site se reconstruir logo
  depois de cada publicação, e a página não cair numa versão desligada.
- **Fontes e atribuição** — conferir que cada dado de terceiros aparece com o
  crédito e a licença certos.
- **A virada** — o site passa a mostrar os dados novos para todo mundo, a
  caixa de testes vira a definitiva, e o caminho antigo é desligado.
- **Fase 5** — a validação independente, que também revê a data de maio que
  ficou a um fio do mínimo.
