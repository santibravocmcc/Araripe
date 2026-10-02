# Phase 6 — o batimento da automação verde, e as respostas do dono sobre autoridade

Escrito em 2026-10-02, ao fim da sessão que desenhou quem publica sem clique
([`PHASE_6P`](../implementation/PHASE_6P_2026-10-02.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: a parte central é um **contrato novo** — um objeto que a automação
> escreve a cada execução, com sucesso ou não, fora da release imutável — e o
> erro plausível é fazer dele uma segunda resposta a "o que está no ar", que
> o contrato do site já recusou uma vez (`SITE_ARTIFACT_CONTRACT_V1.md` §8.4).
> Nenhuma mutação de produção acontece nesta sessão.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe cat-file -e origin/main:config/phase6_publication_authority_v1.json && echo autoridade-ok
    git -C site fetch origin
    git -C site grep -n 'export function datasSemAnalise' origin/main -- src/js/alertas-fonte.js
    gh pr list -R santibravocmcc/observatorio-site --state all --limit 3 --json number,state,baseRefName,mergedAt

- A PR do backend desta sessão (`PHASE_6P`, a proposta de autoridade) tem de
  estar na `main`. Se não estiver, leia a branch `claude/p6-autoridade-publicacao`
  só para contexto e **não construa sobre ela**.
- **`observatorio-site#32`** é a `#31` recuperada. Se o `grep` acima voltar
  vazio, a `main` do site continua com **11 falhas** de vetor no `pytest` — é
  esperado até o merge, e **não** é para consertar de outro jeito.
- Confira, na saída do `gh pr list`, que a `#32` entrou com base **`main`**.
  Foi exatamente a base errada que deixou a `#31` fora.

Suítes medidas em 2026-10-02: backend **2530** na branch da PHASE_6P; site
com a `#32`:
`npm run test:worker` **107**, `pytest` **240**. **Rode o `pytest` do site com
`/opt/anaconda3/bin/python3.12`** — com o 3.11 do env `araripe` um teste de
soma compensada falha (PHASE_6P §1). Use o número que sair.

## 2. As respostas do dono — leia antes de qualquer código

`config/phase6_publication_authority_v1.json` tem duas propostas, P1 e P2,
com `decided: null`. **Só o dono preenche.** Se ele respondeu no chat, registre
as palavras dele e a data em `authorization` (`authorized_by: project_owner`)
e em cada `decided`, num commit próprio — `tests/test_publication_authority.py`
exige as duas coisas juntas.

- **P1 sim** → **antes** de tocar em workflow, meça:
  `gh api repos/santibravocmcc/Araripe/environments`. Se `v2-rollback` **não**
  aparecer, pare: o dono ainda não criou, e **nomear um Environment
  inexistente o cria sem proteção**. Se aparecer, com `required_reviewers` e
  política `main`: registre a medição em `measured`, e então divida o job
  `pointer` de `v2_promotion_lane.yml` em um de leitura (`status`, `history`,
  em `v2-promotion`) e um de `rollback` (em `v2-rollback`). Teste por job, como
  `tests/test_promotion_lane.py` já faz. **Não dispare o rollback** para
  provar: a prova é um `status` lido no job novo, e a de rollback espera um
  pedido do dono, porque um revisor vai ser chamado.
- **P1 não, ou sem resposta** → nada muda no workflow. A condição (2) do bucket
  continua como o dono a escreveu, e o conflito com a publicação automática
  fica registrado, não resolvido.
- **P2** não tem código nesta sessão; a resposta só muda o que a §3 escreve
  sobre o lado do site.

## 3. O que já foi verificado, para o executor não refazer

- **Só o `rollback` move o ponteiro para trás.** `promote()` recusa
  `coverage_regression` e `coverage_dates_dropped` sem override; "tombstone"
  não é operação, é relação gravada no ponteiro; nada apaga (PHASE_6P §2).
- **Das três datas da §4.1.4, duas já existem no índice**: a última avaliada
  (último `runs[]`) e o último alerta não-vazio (último `runs[]` com
  `count > 0`). **A terceira não existe em lugar nenhum.** `promoted_utc` só
  anda quando o ponteiro anda, e um rollback o renova com dado mais velho;
  `coverage.last_observed_on` (2026-09-27) é a última data *olhada*, já três
  dias depois da última avaliada (2026-09-24) (PHASE_6P §6).
- **Cada promoção pede um deploy do site para ficar visível**: o índice é
  artefato de build, e a página recusa o verde quando `built-from.json` nomeia
  outra release. Ao recusar, **cai no azul** — que a §4.4 do
  `PACKAGE_P6_PROMPT.md` vai desligar (PHASE_6P §5).
- **A chave do `v2-staging` escreve e apaga no bucket inteiro**, e depois da
  virada esse bucket é o público. Um objeto de batimento escrito por ela fica
  protegido só pelo código.
- **O frescor por produto já existe no azul** (`site/scripts/freshness.py`,
  `public/data/freshness/<produto>.json`): `status`, `updated_utc`,
  `checked_utc`, `run_id`, `run_url`, `detail`. É o precedente a ler antes de
  inventar formato. Em 2026-10-02 a chuva está `skipped` desde 2026-09-29: o
  servidor de login da NASA inalcançável a partir do runner — problema já
  conhecido, não deste package.

## 4. A tarefa

**Desenhar e construir o batimento da automação verde** — o objeto que
responde "quando a automação tentou pela última vez, e o que aconteceu", que é
a data que falta na §4.1.4 e a "saída de status/saúde" da §4.1.6.

1. **Procure antes de propor**: `site/scripts/freshness.py` (o precedente),
   `src/publication/conditional_store.py` (o que se escreve e como),
   `v2_green_deposit_lane.yml` (quem escreveria), `site/worker/data_route.js`
   (o que a rota serve — hoje **só** o que a release viva declara).
2. **Escreva a decisão antes do código**, num `docs/contracts/phase2b/`
   novo ou numa seção do contrato da release, respondendo: onde o objeto vive
   (fora de `releases/` e de `runs/`), quem o escreve (a lane de depósito, com
   `compare-and-swap`), o que ele **não** diz (não nomeia release, para não ser
   uma segunda resposta a "o que está no ar"), e como a rota o serve **sem**
   abrir o bucket a caminhos arbitrários.
3. **Construa no backend**: schema, escritor, testes; a lane de depósito
   escreve o batimento no fim — inclusive quando falha, num passo
   `if: always()`. Varredura de mutação.
4. **Prove no staging**: um despacho da lane de depósito a partir da `main`
   escreve o batimento. É trabalho de objeto em `araripe-v2-staging`, autônomo
   pela política — mas **só depois** de a PR estar mesclada, porque a política
   de branch do `v2-staging` só aceita `main`. Se a PR não puder ser mesclada
   nesta sessão (não é "inerte mínima"), pare na PR.
5. **A rota do site servir o batimento é mudança no Worker** — `site/worker/` é
   produção ao ser mesclado. Desenhe e teste numa PR do site, **não mescle**.

**Fora de escopo, explicitamente:** a página mostrar as três datas (vem depois
de o batimento existir — sessão seguinte); a página inicial ler o verde
(`site/src/js/home-alertas.js` é só azul); trocar o "cair no azul" da página;
abrir os portões 2 e 3; qualquer mutação de produção; o limiar de maio
(**Phase 5**).

## 5. Decisões de escopo já tomadas, com a base

- **A página lê o verde só por `?dados=verde` até a virada** — PHASE_6M §3.
- **Toda data sem análise aparece, só com a regra** — dono, 2026-09-30.
- **O bucket de staging vira o definitivo na virada** — dono, 2026-09-30.
- **O índice não é objeto da release** — `SITE_ARTIFACT_CONTRACT_V1.md` §1. O
  batimento não reabre isso: ele não carrega estatística de alerta.
- **Nada é apagado**, nunca.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 6. Fronteiras duras

- **A `main` do site faz deploy de produção.** Não mescle PR do site.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare.
- Claude não recebe credencial de control-plane da Cloudflare; o broker só tem
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Nenhum Environment é criado, renomeado ou reconfigurado por agente.** E
  nenhum é citado num workflow antes de aparecer numa medição.
- **Não ligue** `green_site_publish.yml` ao `v2-green-deploy`; **não mescle**
  `observatorio-site#21`.
- O agente age com a conta do dono no GitHub: **nunca aprove um Environment**,
  mesmo que a API permita.

## 7. Armadilhas já pagas — não redescobrir

- **Uma PR empilhada mesclada sem trocar a base não chega à `main`**, e o
  `MERGED` aparece igual. Confira `baseRefName` no `gh pr list --state all`
  (PHASE_6P §1).
- **O hook `commit-msg` recusa um SHA de 40 caracteres de OUTRO repositório.**
  Cite o do outro repo pela forma curta.
- **O `pytest` do site com Python 3.11** falha num teste de soma; use o 3.12.
- **Os vetores JSON são serializados com chaves ordenadas**: não provam que
  uma porta ordena.
- **Um teste de texto por string é derrotado por paráfrase e por quebra de
  linha**; normalize com `" ".join(texto.split())`.
- **Reordenar código preserva o tamanho do arquivo** e o `.pyc` antigo vale:
  limpe `__pycache__` antes de uma varredura de mutação.

## 8. Estado que o package herda

- **Ponteiro verde:** sequência 17, `rel-g3-264ba36e…`, 103 datas até
  2026-09-27, 42 com análise e 61 sem.
- **Backend:** a proposta de autoridade (P1, P2) aguardando o dono.
- **Site:** `#32` aberta (a `#31` recuperada); `#21` em rascunho, não mesclar.
- **A produção azul está parada** desde 2026-09-03; o site público mostra
  alertas até 30/08.
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

A terceira parte — mostrar na página as três datas — não foi feita, e foi de
propósito. Duas delas já dá para mostrar. A terceira, "quando o sistema tentou
rodar pela última vez", não existe em lugar nenhum hoje, e criá-la é mudar o
formato dos dados; o combinado era parar aí. A próxima sessão cria esse dado.

Também apareceu uma pendência que não era da tarefa: a mudança das datas sem
análise na página, que você mesclou em 30/09, **não entrou no site** — ela foi
mesclada em cima da outra PR, depois que a outra já tinha entrado. Abri uma PR
nova com o mesmo conteúdo.

### O que você precisa fazer

1. **Mesclar a PR nova do site com as datas sem análise** (a que substitui a
   que não entrou). Urgente no sentido de que, até ela entrar, os testes do
   site falham; para o público não muda nada.
2. **Mesclar a PR do backend desta sessão** — só documentos e um teste, não
   muda nada que roda.
3. **Responder à proposta P1**: hoje a sua condição para o bucket diz "toda
   publicação passa por um revisor". Isso faria cada atualização automática
   esperar o seu clique. A proposta: publicar para a frente sai sozinho (o
   sistema já se recusa a voltar para dados mais velhos), e **só voltar atrás**
   pede o seu clique. Se disser sim, você cria um novo lugar protegido no
   backend, chamado `v2-rollback`, com você como revisor e as mesmas duas
   chaves do de promoção — o passo a passo está no documento da sessão.
4. **Responder à proposta P2**: aceitar que a atualização de rotina do site
   continue sendo feita pela própria Cloudflare a cada mudança na branch
   principal do site, como já é hoje — porque o outro caminho exigiria seu
   clique a cada atualização, e o seu plano do GitHub nem oferece isso para
   repositório privado.
5. **Renovar o acesso à NASA antes de 6 de novembro** (até o fim de outubro).
6. **Cancelar a chave de acesso que o assistente usa na caixa de testes** —
   só perto da virada, não agora.

### Tem algo preocupante?

Sim, uma coisa de desenho, não de urgência: depois da virada, **cada
atualização automática some da página até o site ser reconstruído**, e hoje a
página, quando isso acontece, volta para a versão antiga — que a virada vai
desligar. Precisa ser resolvido antes da virada; está registrado e tem
caminho. E o prazo da NASA acima.

### O que ainda falta no caminho

- **O batimento da automação** — a próxima sessão: um registro de "quando
  rodou pela última vez e como foi", que é a data que falta na página.
- **As três datas na página**, e a página inicial lendo os dados novos.
- **A ordem das atualizações depois da virada** — o site se reconstruir logo
  depois de cada publicação, e a página não cair numa versão desligada.
- **A virada** — o site passa a mostrar os dados novos para todo mundo, a
  caixa de testes vira a definitiva, e o caminho antigo é desligado.
- **Fase 5** — a validação independente, que também revê a data de maio que
  ficou a um fio do mínimo.
