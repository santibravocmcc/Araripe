# Phase 6 — as três datas na página

Escrito em 2026-10-02, ao fim da sessão que construiu o batimento da automação
verde ([`PHASE_6Q`](../implementation/PHASE_6Q_2026-10-02.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: é trabalho de página, sobre dados que já existem e contratos que já
> estão escritos. O erro plausível é de texto, não de desenho: mostrar a data
> do batimento como se fosse "dado até", ou a última data olhada como se fosse
> a última avaliada. Nenhuma mutação de produção acontece nesta sessão.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe cat-file -e origin/main:docs/contracts/phase2b/GREEN_HEARTBEAT_CONTRACT_V1.md && echo contrato-ok
    git -C site fetch origin
    git -C site grep -n "HEARTBEAT_NAME = 'heartbeat.json'" origin/main -- worker/data_route.js
    gh pr list -R santibravocmcc/observatorio-site --state all --limit 3 --json number,state,baseRefName,mergedAt

- **`observatorio-site#33`** — a porta da rota (PHASE_6Q §4) — tem de estar
  na `main` do site, com base **`main`**. Se o `grep` voltar vazio, ela não entrou:
  **pare**. Até ela entrar, `npm run test:worker` na `main` do site falha em
  `tests/data_route.test.mjs` contra a `main` do backend (os vetores são `/3`
  desde a `Araripe#95`) — esperado, e **não** é para consertar de outro jeito.
- O worker verde de staging **não** é reimplantado pelo merge: ele não tem
  gatilho de branch. A página só lê o batimento pela rota depois que alguém
  com a autoridade certa implantar o worker verde de novo — isso é do portão
  2, não desta sessão. Teste contra o arnês local (§3).

Suítes medidas em 2026-10-02: backend **2604**; site com a PR da rota:
`npm run test:worker` **124**, `pytest` **240** com
`/opt/anaconda3/bin/python3.12`. Use o número que sair.

## 2. O que já foi verificado, para o executor não refazer

- **As três datas e de onde vem cada uma** (PHASE_6P §6, GREEN_HEARTBEAT §3):

  | data | fonte |
  | --- | --- |
  | última observação avaliada com sucesso | último `runs[]` do índice |
  | último alerta não-vazio | último `runs[]` com `count > 0` |
  | última tentativa de automação | `/data/green/heartbeat.json` → `latest.finished_utc` e `latest.outcome` |

- **O batimento não diz o que está no ar.** Não nomeia release, janela nem
  contagem, de propósito (contrato §4). Um `deposited` recente com o índice
  parado é o estado normal entre um depósito e a promoção seguinte.
- **`last_success` existe para separar "quieto" de "quebrado"**:
  `latest` falhou e `last_success` é recente → tropeço; os dois velhos →
  parado. A idade do batimento é o sinal de que a automação nem rodou
  (contrato §6) — com cadência de duas vezes por semana, "velho" é coisa de
  dias.
- **O batimento real está em `araripe-v2-staging`**, escrito pela lane a partir
  da `main` (PHASE_6Q §3), e há uma cópia byte-idêntica em
  `site/tests/fixtures/green-bucket/status/green/heartbeat.json`, que o arnês
  `scripts/verify_green_route.sh` serve sobre HTTP sem credencial.
- **`coverage.last_observed_on` não é nenhuma das três.** É a última data
  *olhada*, inclusive as sem análise.

## 3. A tarefa

**Única tarefa: a página de alertas, na visão verde (`?dados=verde`), mostra
as três datas separadas, com o rótulo certo para cada uma.**

1. Leia `site/src/js/alertas-fonte.js` (a visão verde) e `alertas.html`.
2. Leia o batimento pela rota; **a ausência dele não derruba a página** — sem
   batimento, a terceira data diz que não há registro, e as outras duas
   continuam. Uma falha de leitura também não.
3. Escreva os rótulos em português comum, com a distinção do §2: "a automação
   tentou pela última vez em …, e …" não é "dados até …".
4. Teste com o `node --test` do site, e sobre HTTP com o arnês local.

**Fora de escopo, explicitamente:** a página inicial ler o verde
(`src/js/home-alertas.js`); trocar o "cair no azul"; abrir os portões 2 e 3;
agendar a lane (vem com a virada); qualquer mutação de produção; o limiar de
maio (**Phase 5**).

## 4. Decisões de escopo já tomadas, com a base

- **A página lê o verde só por `?dados=verde` até a virada** — PHASE_6M §3.
- **O batimento não nomeia release** — GREEN_HEARTBEAT_CONTRACT_V1.md §4.
- **Toda data sem análise aparece, só com a regra** — dono, 2026-09-30.
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
- **Um cliente boto3 real num teste cria a sessão padrão do processo**, e um
  teste de profile rodado depois falha com `ProfileNotFound` — passa sozinho,
  falha na suíte (PHASE_6Q §5).
- **Um passo `if: always()` não roda num job pulado**; foi por isso que o
  batimento é um job.
- **O hook `commit-msg` recusa um SHA de 40 caracteres de OUTRO repositório.**

## 7. Estado que o package herda

- **Ponteiro verde:** sequência 17, `rel-g3-264ba36e…`, 103 datas até
  2026-09-27.
- **Batimento:** em `status/green/heartbeat.json` no staging, último
  `ci-37021850688 no_acquisition` (PHASE_6Q §3). A cabeça da cadeia é
  `ci-37020588408`, cobrindo até 2026-09-29; nada foi promovido nesta sessão.
- **A produção azul está parada** desde 2026-09-03; o site público mostra
  alertas até 30/08.
- **O token da NASA expira em 2026-11-06.**

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

O registro de "quando o sistema tentou rodar pela última vez, e como foi" já
existe e já está sendo escrito a cada execução, inclusive quando ela falha.
O que falta é a página mostrar isso — de propósito, é a próxima sessão.

### O que você precisa fazer

1. **Mesclar a PR 33 do site, que ensina o site a entregar esse registro** —
   pode esperar alguns dias, mas a próxima sessão depende dela. Ela não muda
   nada do que o público vê hoje.
2. **Renovar o acesso à NASA antes de 6 de novembro** (até o fim de outubro).
   Sem isso a atualização da chuva para.
3. **Cancelar a chave de acesso que o assistente usa na caixa de testes** —
   só perto da virada, não agora.

### Tem algo preocupante?

Nada novo. Continuam valendo os dois avisos de antes: depois da virada, cada
atualização automática só aparece na página quando o site é reconstruído — e
isso precisa estar resolvido antes da virada —, e o prazo da NASA acima.

### O que ainda falta no caminho

- **As três datas na página** — a próxima sessão.
- **A página inicial lendo os dados novos.**
- **A ordem das atualizações depois da virada** — o site se reconstruir logo
  depois de cada publicação, e a página não cair numa versão desligada.
- **A virada** — o site passa a mostrar os dados novos para todo mundo, a
  caixa de testes vira a definitiva, e o caminho antigo é desligado.
- **Fase 5** — a validação independente, que também revê a data de maio que
  ficou a um fio do mínimo.
