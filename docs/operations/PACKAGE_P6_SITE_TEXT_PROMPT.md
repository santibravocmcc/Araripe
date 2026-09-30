# Phase 6 — o texto científico do site passa a descrever o que o sistema verde faz, e as datas recusadas aparecem com o motivo

Escrito em 2026-09-30, depois de a lane de rollback aceitar uma release de
cadeia e de a página inicial deixar de mostrar alertas de exemplo (PHASE_6N).
**Ampliado em 2026-09-30 com duas decisões do dono** (§5): as 4 datas
recusadas aparecem na página com o motivo — a segunda tarefa desta sessão — e
o bucket de staging vira o definitivo na virada.
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: é texto, não código novo, mas é o texto que o público lê como
> afirmação científica. O cuidado é cada frase ter uma fonte medida no backend
> (constante, documento ou contagem) — não a lembrança de como o sistema
> funcionava. A segunda tarefa pode tocar o contrato do artefato do site
> (backend e site juntos); se tocar, é ela que decide o effort — pare e fatie
> antes de passar de uma sessão. Termina em PRs do site que o dono mescla.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6N_2026-09-30.md | grep -n '^## '
    gh pr view 29 --repo santibravocmcc/observatorio-site --json state,mergedAt

A `observatorio-site#29` (página inicial) foi **mesclada pelo dono em
2026-09-30**; parta de `origin/main` do site.

Suítes medidas em 2026-09-30: backend **2489**; site `npm run test:worker`
**93** e `pytest` **224** (na branch da `#29`, que é o conteúdo mesclado).
Rode e use o número que sair.

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
- **As 4 datas recusadas** (PHASE_6L §4): 2026-01-02, 01-04 e 01-22 por
  `scene-alert-fraction-anomalous` (57,33%, 57,70% e 39,01% da área válida
  virou alerta — assinatura de artefato da cena) e 2026-05-22 por
  `scene-valid-coverage-below-minimum` (19,87%, mínimo 20,00%). O motivo está
  no ledger (`runs/rep-2026-08-30-v3/ledger.json`, e no `ledger.json` de cada
  release membro).
- **Onde elas se perdem hoje**, lido no código em 2026-09-30, a confirmar:
  `green_release.classify_date` dá `alert_state = "no_valid_coverage"` a uma
  data sem aquisição utilizável, e o compositor do site
  (`site/scripts/site_artifact.py`, laço de `manifest["dates"]`) faz
  `continue` nessa data — "uma data sem cobertura não foi uma execução". Então
  a data provavelmente está no manifesto da release e **o índice do site a
  descarta**. Confirme sobre a release viva antes de desenhar.
- **O índice do site é contrato** (`SITE_ARTIFACT_CONTRACT_V1`, schema
  `araripe.site.alert_index/1`, vetores
  `docs/contracts/phase2b/site_artifact_conformance_vectors.json`, porta Python
  no backend e no site, porta JS em `alertas-fonte.js`). Uma data recusada no
  índice muda o contrato nos três lugares — e, lembrete, o índice é
  **derivado**, nunca objeto de release (memória "o índice do site é
  derivado").
- **O revisor de promoção e a publicação automática se contradizem.** A
  condição (2) da decisão do bucket pedia revisor humano no Environment
  `v2-promotion`; mas esse Environment serve toda a lane de promoção, e o
  roadmap exige publicação operacional automática, sem aprovação manual
  (`ROADMAP.md`, "Keep operational data publication automatic"). Um revisor
  ali faria cada publicação da virada esperar um clique. **Não é desta
  sessão**, e não peça ao dono para ligar o revisor: é desenho da virada
  (por exemplo, promoção automática e rollback manual em Environments
  distintos). Registre-o no briefing da virada.
- **Fonte só Sentinel-2** já está corrigida nos quatro lugares pela `#28`.
- **`fixture.source` dos vetores do backend ainda diz `LANDSAT 8/9`**
  (PHASE_6M §7): é texto livre de fixture, não chega ao público.

## 3. A tarefa

**Primeira:** reescrever o texto de persistência e de nuvem do site —
`alertas.html` e `worker/knowledge.js` (o que o chat responde) — para que cada
afirmação corresponda a uma constante ou documento do backend, com os trechos
contraditórios reduzidos a uma definição só.

**Segunda (decisão do dono, 2026-09-30):** na visão verde (`?dados=verde`),
uma data que o portão de qualidade recusou **aparece** na página, marcada como
recusada, com o motivo em português comum — em vez de sumir. No azul nada
muda: lá essas datas têm os alertas que o azul publicou.

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
6. **As datas recusadas** — nesta ordem:
   - confirme sobre a release viva onde a data e o motivo estão (manifesto,
     `ledger.json`), só leitura;
   - desenhe a mudança **mínima e aditiva** do índice (uma data com um estado
     e um código de motivo, sem feições e sem somar em nenhum total), e
     escreva a decisão antes do código, como PHASE_6M §3;
   - backend primeiro: contrato, vetores novos, as duas portas Python; depois
     o site: compositor, `alertas-fonte.js`, a página;
   - o texto de cada motivo é do site, curto, sem afirmar mais do que o ledger
     diz (a de 22/05 está a 0,13 ponto do mínimo — diga isso, não "sem
     imagem");
   - se o contrato crescer além de um campo aditivo, **pare**: registre o
     desenho e deixe a implementação para a sessão seguinte.

**Fora de escopo:** reabrir o limiar que recusou 22/05 (PHASE_6L §6.2) —
é da Phase 5; a virada (trocar `FONTE_PADRAO`, rota de produção, índice no build); a decisão
do bucket; a visão completa verde pesada (PHASE_6M §7).

## 5. Decisões de escopo já tomadas, com a base

- **A página lê o verde só por `?dados=verde` até a virada** — PHASE_6M §3.
- **Os cartões da página inicial são os fortes da última execução** — PHASE_6N.
- **O download azul de cada execução é o `.strong`, rotulado** — PHASE_6N.
- **As datas recusadas aparecem com o motivo** — dono, 2026-09-30.
- **O bucket de staging vira o definitivo na virada** — dono, 2026-09-30,
  opção (a) de `PACKAGE_P6_PROMPT.md` §3, com três condições antes da virada.
  Até lá ele continua regido como sandbox; nada nesta sessão muda o papel dele.
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
- **Site:** `#28`, `#26` e `#29` mescladas em 2026-09-30; `#21` em rascunho,
  não mesclar.
- **A produção azul está parada** desde 2026-09-03; o site público mostra dados
  até 30/08.
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. As suas duas decisões ficaram registradas: as quatro datas recusadas vão
aparecer na página com o motivo, e a caixa de testes vira a definitiva na
virada.

### O que você precisa fazer

1. **Renovar o acesso à NASA antes de 6 de novembro** (até o fim de outubro).
   Sem isso a atualização da chuva para.
2. **Cancelar a chave de acesso que o assistente usa hoje na caixa de testes**
   — só perto da virada, não agora (pode esperar). Até lá ela ainda serve para
   as leituras de conferência; a próxima sessão pode precisar dela.

### Tem algo preocupante?

Uma coisa, sem pressa: exigir a sua aprovação em cada publicação, como eu
tinha recomendado para a caixa definitiva, impediria a publicação automática
que o plano exige. Isso precisa ser desenhado na virada, e por isso não está
na sua lista. E o prazo da NASA acima.

### O que ainda falta no caminho

- **O texto científico da página e as datas recusadas** — a próxima sessão:
  uma definição só de "confirmado", o limite de nuvem certo, e as quatro datas
  aparecendo com o motivo em vez de sumir.
- **A virada** — o site passa a mostrar os dados novos para todo mundo, a
  caixa de testes vira a definitiva, e o caminho antigo é desligado.
- **Detecção e publicação automáticas** — ligam na virada.
- **Fase 5** — a validação independente.
