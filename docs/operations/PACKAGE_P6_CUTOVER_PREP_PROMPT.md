# Phase 6 — preparar a virada: o que falta sem portão aberto, e quem pode publicar sem clique

Escrito em 2026-09-30, ao fim da sessão do texto do método e das datas sem
análise ([`PHASE_6O`](../implementation/PHASE_6O_2026-09-30.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: a parte central é decidir **quem tem autoridade para publicar em
> produção sem clique humano**, e o erro ali é plausível, não obviamente
> quebrado — um Environment com revisor trava a publicação automática; um sem
> revisor entrega a produção a qualquer run da `main`. Nenhuma mutação de
> produção acontece nesta sessão: ela termina em documento de decisão para o
> dono e, se sobrar tempo, numa PR do site.

---

## 1. A dependência que precede tudo — confirme por conteúdo

Três PRs desta sessão, que o dono mescla **nesta ordem**:
`Araripe#91` (índice com datas sem análise) → `observatorio-site#30` (texto
do método) → `observatorio-site#31` (datas sem análise na página; empilhada
sobre a #30, a base troca para `main` depois dela).

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:src/publication/site_artifact.py | grep -n 'def unanalyzed_date'
    git -C site fetch origin
    git -C site show origin/main:worker/metodo.js | head -3
    git -C site show origin/main:src/js/alertas-fonte.js | grep -n 'export function datasSemAnalise'

Se só a #91 estiver mesclada, `site` `pytest` e `vectors --check` na `main` do
site **divergem dos vetores** — esperado, é a janela entre os merges, e só a
lane manual `green_site_publish.yml` a veria. Não "conserte" isso no site: é a
#31 que fecha.

Suítes medidas em 2026-09-30 com as três aplicadas: backend **2514**; site
`npm run test:worker` **107** e `pytest` **240**. Rode e use o número que sair.

## 2. O que já foi verificado, para o executor não refazer

- **O texto do método agora está preso ao backend.** `site/worker/metodo.js`
  guarda os números; `site/tests/texto_do_metodo.test.mjs` lê cada um na fonte
  (`persistence.py`, `settings.py`, `replay_2026.py`, `run_detection_gee.py`,
  a decisão de sobreposição). **Mudar uma dessas constantes no backend derruba
  um teste do site** — de propósito. O inventário completo está na descrição
  da `observatorio-site#30`.
- **O filtro de nuvem real é 60, não 20** (PHASE_6O §1): `MAX_CLOUD_COVER = 20`
  só é lido pelo caminho STAC, que nada agendado roda. Verificado que nenhuma
  das duas lanes passa `--max-cloud` nem `--min-clear`.
- **O ajuste por seca está desligado** (`change_detect.py`,
  `drought-disabled-v1`); o chat dizia o contrário. A linha de base guarda a
  **mediana** nas duas gerações.
- **61 das 103 datas da release viva não têm aquisição utilizável** — 56
  cobertura baixa, 5 anomalia, 0 falhas; as portas do backend e do site dão a
  mesma lista sobre as 103 entradas reais (PHASE_6O §2). O dono decidiu
  mostrar todas, só com a regra.
- **A §4.1.4 do `PACKAGE_P6_PROMPT.md` não está feita.** `git grep -niE
  'tentativa|frescor'` nos `.html` e `src/js/*.js` da `main` do site em
  2026-09-30 não achou nada: a página não separa a última observação avaliada,
  a última tentativa de automação e o último alerta não-vazio.
- **O site não roda CI em pull request**; `green_site_publish.yml` só tem
  `workflow_dispatch`. Um teste do site só roda quando alguém o roda.
- **O revisor de promoção contradiz a publicação automática** (herdado do
  briefing anterior, não resolvido): a condição (2) da decisão do bucket pedia
  revisor humano no Environment `v2-promotion`, mas ele serve **toda** a lane
  de promoção, e o `ROADMAP.md` exige publicação operacional automática ("Keep
  operational data publication automatic"). Um revisor ali faria cada
  publicação esperar um clique.

## 3. A tarefa

**Primeira — o desenho de autoridade de publicação.** Um documento de decisão
(no formato de `config/phase6_owner_decisions_v1.json` e de um
`docs/implementation/PHASE_6P_…md`) que responda: **qual operação publica
sem clique, qual exige revisor, e em que Environment cada uma roda.** A
hipótese a testar, não a conclusão: promoção de uma release nova que passou
nos portões — automática; rollback, tombstone e qualquer coisa que aponte o
ponteiro para trás — manual, com revisor, num Environment separado.

- **Meça antes de desenhar**: `gh api repos/santibravocmcc/Araripe/environments`
  (nomes, revisores, política de branch) e quais jobs de
  `.github/workflows/v2_*.yml` nomeiam cada Environment. **Nunca nomeie um
  Environment que não existe** — o GitHub o cria sem proteção.
- **Não crie nem altere Environment nenhum.** É configuração de repositório; a
  decisão é do dono, e a mudança é da sessão seguinte.
- Diga o que o desenho **não** protege: o token do Environment de promoção
  continua escrevendo no bucket inteiro (DELETE vem junto com WRITE no R2).

**Segunda — a checklist da virada contra o presente.** Reescreva a §4.1 do
`PACKAGE_P6_PROMPT.md` com o diff visível: o que as sessões desde então
fecharam (produtos do site a partir da release — `site#28`/`#29`; linguagem
do método — `site#30`; datas sem análise — `site#31`) e o que resta (§4.1.4,
§4.1.5, §4.1.6). Cada "feito" com a PR que o fez, lida por conteúdo.

**Terceira, se sobrar sessão — a §4.1.4 no site.** As três datas separadas na
página, a partir do que a release e o ponteiro já dizem (`promoted_utc`,
`coverage.last_observed_on`, o último `runs[]` com alerta). Se precisar de um
campo novo no índice, **pare**: é contrato, e fica para a sessão seguinte.

**Fora de escopo, explicitamente:** abrir os portões 2 e 3 e qualquer
mutação de produção (a virada propriamente dita); o limiar que recusou 22/05
(**Phase 5**); o percentual exato de cada data recusada (o dono recusou em
2026-09-30); a visão completa verde pesada (PHASE_6M §7).

## 4. Decisões de escopo já tomadas, com a base

- **A página lê o verde só por `?dados=verde` até a virada** — PHASE_6M §3.
- **Toda data sem análise aparece, só com a regra** — dono, 2026-09-30,
  PHASE_6O §3.
- **O bucket de staging vira o definitivo na virada** — dono, 2026-09-30,
  opção (a), com três condições antes da virada.
- **Nada é apagado**, nunca.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- **A `main` do site faz deploy de produção.** Não mescle PR do site.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare.
- Claude não recebe credencial de control-plane da Cloudflare; o broker só tem
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Não ligue** `green_site_publish.yml` ao Environment `v2-green-deploy`.
- **Não mescle** `observatorio-site#21`.
- Nenhum Environment é criado, renomeado ou reconfigurado nesta sessão.

## 6. Armadilhas já pagas — não redescobrir

- **O hook `commit-msg` recusa um SHA de 40 caracteres de OUTRO repositório.**
  Cite o do outro repo pela forma curta (7-12), como o hook instrui.
- **Os vetores JSON são serializados com chaves ordenadas**: não provam que
  uma porta ordena. Monte o dict fora de ordem num teste próprio.
- **Variável com vários argumentos não se divide no zsh** (`aws … $A` falha
  como "Unknown options"). Escreva as opções por extenso.
- **`find /` não termina em 2 minutos nesta máquina.** Procure no caminho
  documentado (o espelho da release está descrito na PHASE_6M §6).
- **Um teste de texto por string é derrotado por paráfrase**; o do site prende
  cada número pela estrutura (`data-metodo`), e a varredura de mutação achou
  um caso que sobrevivia (a definição do forte) antes de o teste certo existir.
- **Premissa medida no estado que a torna verdadeira**: "4 datas" era a
  interseção com o azul, não o conjunto. Meça o conjunto.

## 7. Estado que o package herda

- **Ponteiro verde:** sequência 17, `rel-g3-264ba36e…`, 103 datas até
  2026-09-27, das quais 42 com análise e 61 sem.
- **Site:** `#30` e `#31` abertas (dono mescla); `#21` em rascunho, não
  mesclar.
- **A produção azul está parada** desde 2026-09-03; o site público mostra dados
  até 30/08, e o chat público ainda diz as afirmações falsas até a `#30`.
- **O token da NASA expira em 2026-11-06.**

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da tarefa ficou por fazer, mas ela só vale depois dos seus merges. O
texto da página e do chat foi corrigido, e as datas sem imagem utilizável
agora aparecem com o motivo — só na visão nova, que o público ainda não vê.

### O que você precisa fazer

1. **Mesclar três PRs, nesta ordem**: a do backend (datas sem análise), depois
   a do texto do método, depois a das datas sem análise na página — nesta
   última, troque a base para a principal antes. Pode esperar alguns dias, mas
   as três andam juntas.
2. **Renovar o acesso à NASA antes de 6 de novembro** (até o fim de outubro).
   Sem isso a atualização da chuva para.
3. **Cancelar a chave de acesso que o assistente usa hoje na caixa de testes**
   — só perto da virada, não agora. Até lá ela ainda serve para as leituras de
   conferência.

### Tem algo preocupante?

Duas coisas, nenhuma urgente. O chat do site público está dizendo coisas
falsas sobre o método (um ajuste de seca que não existe, um limite de nuvem
errado) até a PR do texto entrar. E o prazo da NASA acima.

### O que ainda falta no caminho

- **Preparar a virada** — a próxima sessão: decidir quais publicações saem
  sozinhas e quais esperam o seu clique, e mostrar na página as três datas
  (última imagem analisada, última tentativa, último alerta).
- **A virada** — o site passa a mostrar os dados novos para todo mundo, a
  caixa de testes vira a definitiva, e o caminho antigo é desligado.
- **Detecção e publicação automáticas** — ligam na virada.
- **Fase 5** — a validação independente, que também revê a data de maio que
  ficou a um fio do mínimo.
