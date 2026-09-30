# Phase 6 — o texto científico do site passa a descrever o que o sistema verde faz

Escrito em 2026-09-30, depois de a lane de rollback aceitar uma release de
cadeia e de a página inicial deixar de mostrar alertas de exemplo (PHASE_6N).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: é texto, não código novo, mas é o texto que o público lê como
> afirmação científica. O cuidado é cada frase ter uma fonte medida no backend
> (constante, documento ou contagem) — não a lembrança de como o sistema
> funcionava. Termina numa PR do site que o dono mescla.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6N_2026-09-30.md | grep -n '^## '
    gh pr view 29 --repo santibravocmcc/observatorio-site --json state,mergedAt

A `observatorio-site#29` (página inicial) pode estar aberta ou mesclada; ela
mexe em `index.html`, `src/js/alertas.js` e `src/js/alertas-fonte.js`. Se
estiver aberta, parta de `origin/main` do site e evite esses trechos, ou
parta da branch dela dizendo isso na PR.

Suítes medidas em 2026-09-30: backend **2484**; site `npm run test:worker`
**93** e `pytest` **224** na branch da `#29` (na `main` do site, 88 e 224
enquanto a `#29` não for mesclada). Rode e use o número que sair.

## 2. O que já foi verificado, para o executor não refazer

- **Os dois trechos de persistência de `alertas.html` se contradizem**
  (PHASE_6L §6.3), medido por `git grep` na `main` do site em 2026-09-30:
  - linha ~114: "Confirmado: 15+×", e a contagem "não recomeça por até ~6
    meses";
  - linha ~249: "conta em quantas observações o mesmo lugar reaparece";
  - linha ~280: "um alerta é **confirmado** quando a mesma área reaparece na
    observação seguinte" — isso é falso para os dois sistemas: confirmado é
    15 ou mais observações.
- **As constantes vêm do backend, não do site.** `POLITICA` em
  `site/src/js/alertas-fonte.js` (`confirmed_min_sightings: 15`,
  `candidate_min_sightings: 2`) é porta de `Araripe/src/publication/site_artifact.py`;
  a janela de reconexão é `GRACE_DAYS = 180`, citada em
  `site/worker/knowledge.js:93`. Confira cada número no backend antes de
  escrevê-lo.
- **`worker/knowledge.js:31` diz "cenas com nuvem acima de ~20% são
  descartadas"**; o ledger do replay enumerou cenas com nuvem < 60%
  (PHASE_6L §5). Ache a constante que decide isso no backend e escreva o que
  ela diz.
- **O azul recontava observações; o verde conta cada uma uma vez**
  (PHASE_6L §3, memória "diferença de fortes azul × verde"). O texto novo
  tem de valer para o verde, que é o que o público vai ver depois da virada, e
  não pode ficar falso para o azul enquanto a virada não chega — escreva o que
  vale para os dois ou diga qual.
- **Fonte só Sentinel-2** já está corrigida nos quatro lugares pela `#28`.
- **`fixture.source` dos vetores do backend ainda diz `LANDSAT 8/9`**
  (PHASE_6M §7): é texto livre de fixture, não chega ao público.

## 3. A tarefa

Reescrever o texto de persistência e de nuvem do site — `alertas.html` e
`worker/knowledge.js` (o que o chat responde) — para que cada afirmação
corresponda a uma constante ou documento do backend, com os trechos
contraditórios reduzidos a uma definição só.

## 4. O escopo, na ordem em que se sustenta

1. **Inventário**: todo trecho do site que afirma um número ou regra do método
   (persistência, confiança, nuvem, janela, vegetação natural). Uma tabela:
   trecho, o que afirma, a fonte no backend, se confere.
2. **Um teste que prende os números** que tiverem constante no backend (o
   padrão já existe: `tests/alertas_fonte.test.mjs` lê os vetores do backend e
   falha, nunca pula, se eles faltarem).
3. **O texto**, curto e em português comum.
4. `npm run test:worker`, `pytest`, `npm run build`, navegador.
5. **PR aberta, não mesclada.**

**Fora de escopo:** mostrar o motivo da recusa das 4 datas só-azul e a data de
22/05 (PHASE_6L §6.1-2) — são decisões do dono, e o texto não as antecipa; a
virada (trocar `FONTE_PADRAO`, rota de produção, índice no build); a decisão
do bucket; a visão completa verde pesada (PHASE_6M §7).

## 5. Decisões de escopo já tomadas, com a base

- **A página lê o verde só por `?dados=verde` até a virada** — PHASE_6M §3.
- **Os cartões da página inicial são os fortes da última execução** — PHASE_6N.
- **O download azul de cada execução é o `.strong`, rotulado** — PHASE_6N.
- **Nada é apagado**, nunca.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 6. Fronteiras duras

- **A `main` do site faz deploy de produção.** Não mescle a PR: é do dono.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare.
- Claude não recebe credencial de control-plane da Cloudflare; o broker só tem
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Não ligue** `green_site_publish.yml` ao Environment `v2-green-deploy`.
- **Não mescle** `observatorio-site#21`.

## 7. Armadilhas já pagas — não redescobrir

- **Guarda por string é derrotada por paráfrase**: um teste de texto que
  procura "15" passa com "15 dias". Prenda o número à frase pela estrutura.
- **Um teste pode passar pelo motivo errado**: pergunte qual mutação cada teste
  derruba.
- **Navegar só trocando o `#hash` não recarrega a página.**
- **Premissa medida no estado que a torna verdadeira**: não descreva o método
  pelo que o azul fazia.
- **Copie todo identificador da ferramenta que o produz.**

## 8. Estado que o pacote herda

- **Ponteiro verde:** sequência 17, `/2`, `rel-g3-264ba36e…`, 103 datas até
  2026-09-27; a lane de rollback aceita `rel-g3-` desde a `#88`.
- **Site:** `#28` e `#26` mescladas em 2026-09-30; `#29` (página inicial)
  aberta; `#21` em rascunho, não mesclar.
- **A produção azul está parada** desde 2026-09-03; o site público mostra dados
  até 30/08.
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. O sistema novo agora consegue voltar para uma publicação da cadeia, e
isso foi provado no ambiente de testes sem mudar nada. A correção da página
inicial está pronta e testada, esperando você.

### O que você precisa fazer

1. **Mesclar a correção da página inicial** (pode esperar, mas é a que o
   público vê primeiro). Ela troca os três alertas de exemplo pelos três
   maiores alertas fortes da última execução, e o botão "Baixar" de cada
   execução passa a funcionar, baixando só os alertas fortes, com esse nome.
2. **Decidir se as quatro datas recusadas aparecem na página com o motivo**
   (pode esperar; a próxima sessão não depende disso).
3. **Confirmar a escolha do bucket** (pode esperar, trava a virada). A
   recomendação continua a de usar a caixa de testes atual como definitiva,
   com os três cuidados antes da virada.
4. **Renovar o acesso à NASA antes de 6 de novembro** (até o fim de outubro).
   Sem isso a atualização da chuva para.

### Tem algo preocupante?

Só o prazo da NASA acima. O resto pode esperar.

### O que ainda falta no caminho

- **O texto científico da página** — a próxima sessão: explicar confiança e
  persistência com a contagem nova, sem as duas definições que hoje se
  contradizem.
- **A virada** — o site passa a mostrar os dados novos para todo mundo, e o
  caminho antigo é desligado.
- **Detecção e publicação automáticas** — ligam na virada.
- **Fase 5** — a validação independente.
