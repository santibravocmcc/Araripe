# Phase 5 — briefing do protocolo de validação, desenhado para NÃO travar

Escrito em 2026-09-08, a pedido do dono, para uma sessão **paralela** ao caminho
crítico do roadmap.

Segue o método em [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md)
versão 2: o corpo é para o agente executor, e a **seção final é para o dono**.

---

## 0. A decisão de sequenciamento, e o que ela custa

O dono decidiu: **a Phase 5 não trava as Fases 6 e 7.** O protocolo é desenhado
agora, a rotulagem roda quando houver pessoas, e o roadmap segue sem esperar o
relatório. Mudanças depois são aceitas.

Isso é viável, e tem **duas consequências exatas** que este package tem de tornar
impossíveis de esquecer:

**1. Nenhuma afirmação de acurácia pode ser publicada antes do relatório.**
O roadmap marca a Phase 5 como *"P0 before validated claims"*. O que a Phase 6
publica é **dado e método** — detecções cruas, tiers de persistência, contexto do
MapBiomas, tudo documentado como procedimento. O que ela **não** pode publicar é
precisão, recall, comissão, omissão, ou qualquer número que soe como
confiabilidade medida. A palavra "confiança" no site já significa *tier
espectral*, não acurácia validada, e a Phase 6 tem um bullet inteiro para
corrigir essa linguagem — ele passa a ter uma segunda razão.

Este package deve entregar **a redação exata do aviso** que o site carrega até o
relatório existir, para a Phase 6 apenas colar.

**2. Uma mudança de default depois obriga a rerodar estágios de 2026.**
*"If a conditional method changes, rerun the affected 2026 stages and repeat
release QA before promotion."* Isso não é um risco: é um custo orçado. Pela
medição de cota em `PHASE_3_INPUTS_2026-09-08.md` §1, um segundo replay cabe
confortavelmente na alocação mensal. O que ele custa é **uma nova promoção**, e o
ponteiro verde já provou mover e reverter.

**Registrar as duas em vez de descobri-las depois é metade do valor deste
package.**

## 1. O ponto de partida existe — NÃO comece do zero

**Já há um protocolo de revisão de mesa, versionado e com checksums**, do
Package 2A.3, em `data/validation/phase2a3-pilot-v1/` (untracked local, gerado
por `scripts/build_validation_pilot.py`):

| Arquivo | O que traz |
| --- | --- |
| `PROTOCOL.md` | elegibilidade do revisor, independência, cegamento, ordem dos casos, sequência por caso, taxonomia de rótulos |
| `manifest.json` | desenho amostral, dupla revisão, parâmetros de geração de evidência, versões de runtime, inventário com sha256 |
| `sources.json` | proveniência das entradas |
| `CHECKSUMS.sha256` | integridade do pacote |

E há um segundo pacote, `data/validation/phase2a5-method-comparison-v2/`.

**O que o 2A.3 já resolveu, e deve ser herdado em vez de reinventado:**

- **Cegamento e independência.** Revisor entra com ID pseudônimo e atesta
  competência; não vê outra revisão, o crosswalk do coordenador, a confiança do
  sistema, a persistência, o rótulo legado de cobertura, nem a chave do método
  antes de submeter a avaliação primária.
- **Ordem fixa dos casos**, para não reordenar por data, lugar ou dificuldade
  aparente.
- **Sequência por caso**, em sete passos, com a regra que importa: *"use the
  polygon as a location cue, not as proof of change"*.
- **Taxonomia de mudança:** `real_change`, `no_change`, `uncertain`,
  `unreviewable` — com a regra de que imagem obrigatória ausente antes **ou**
  depois normalmente exige `unreviewable`, e que **não se substitui o caso** nem
  se usa basemap sem data como prova temporal.
- **Dupla revisão medida:** 12 de 60 casos, fração 0,20, com ordem própria e sem
  dizer ao segundo revisor que julgamento existe.
- **Declaração explícita do que o pacote NÃO afirma:** o `manifest.json` carrega
  `claims` com `precision_estimate: false`, `omission_estimate: false`,
  `qualified_human_labels: …`, `method_promoted_or_activated: false`, e
  `scientific_status: provisional_audit_inputs_only`.

Essa última linha é o modelo para a consequência (1) da §0: **o pacote declara o
que ele não prova, e a declaração é dado, não prosa.**

## 2. O que a Phase 5 exige ALÉM do que o 2A.3 tem

Os bullets do roadmap, com o delta em relação ao pilto:

| Bullet da Phase 5 | O 2A.3 tem? | Delta |
| --- | --- | --- |
| amostra estratificada da população **candidata final** | não — amostrou alertas legados provisórios, balanceado por local-data | **redesenhar a amostragem sobre o candidato da Phase 4** |
| **amostra independente de mudança conhecida**, para recall/omissão | **não** | **é a maior adição, e a mais difícil** |
| pessoas qualificadas rotulando | sim, com atestação | manter |
| múltiplos revisores num subconjunto | sim, 20% | decidir se 20% basta para o alvo de concordância |
| visitas de campo opcionais e direcionadas | — | escrever a regra |
| estimar precisão, recall, comissão, omissão, estratos, incerteza | não — proibido no piloto | **cálculo e intervalos** |
| validar os defaults aceitos | — | lista fechada, ver §4 |
| versionar amostra, rótulos, cálculos, relatório, protocolo | sim, o padrão existe | herdar |

### A pergunta metodológica central: de onde vem a "mudança conhecida"

O roadmap é explícito sobre por que ela é obrigatória:

> *"Include an independent known-change sample so recall/omission are
> measurable; reviewing only detected polygons can estimate commission but not
> omissions."*

**Amostrar mudança conhecida das próprias detecções é circular** — mede
comissão, nunca omissão. As opções, e este package tem de **escolher e
justificar** uma:

1. **Produto independente de alerta/desmatamento** como quadro de referência
   (por exemplo produtos públicos de alerta para Caatinga/Cerrado). Barato, mas
   herda o viés e a resolução do produto, e pode não cobrir a extensão
   monitorada. Se for esta, o relatório mede **concordância com aquele produto**,
   não verdade de campo — e tem de dizer isso.
2. **Amostra areal sistemática**, estratificada por probabilidade de mudança,
   interpretada às cegas independentemente da detecção. Mede omissão de verdade,
   mas o custo humano cresce com a raridade do evento: desmatamento é raro por
   área, então uma amostra aleatória simples gasta quase todo o esforço em
   não-mudança.
3. **Amostra estratificada por estrato de risco** com pesos declarados, para
   concentrar esforço onde há mudança sem perder a estimativa não-viesada — o
   caminho usual em acurácia de mudança de cobertura, e o que permite intervalo
   de confiança honesto.

**Recomendação a avaliar, não a assumir: (3), com (1) como estrato auxiliar.**
Meça a raridade primeiro — quantos hectares mudaram em 2026 sobre a extensão
monitorada, pelos próprios dados — porque é isso que decide o tamanho amostral.
Não decida por esta frase.

### O tamanho amostral tem de sair de um cálculo, não de um número redondo

O piloto usou 60 casos porque era um piloto. A Phase 5 precisa de um alvo
declarado — por exemplo "recall com meia-largura de intervalo ≤ 10 pontos no
estrato de alta confiança" — e o tamanho sai dele. **Um número escolhido antes
do alvo é um número que não sustenta o intervalo que o relatório vai imprimir.**

## 3. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: esta sessão desenha o instrumento que vai medir a credibilidade
> científica do sistema inteiro. Um desenho amostral enviesado não é corrigível
> depois com mais rótulos — a amostra é a evidência, e refazê-la custa o tempo
> das pessoas, que é o recurso mais escasso do roadmap. E é a única fase cujo
> produto é um número que outras pessoas vão citar.

Entregue **o protocolo e o instrumento da Phase 5**, sem executar a rotulagem.

**Orientação obrigatória antes de qualquer conclusão.** Siga "Establishing the
real state" do `AGENTS.md` do workspace. Leia canônico com
`git show origin/main:<path>`. Confirme o SHA de 40 caracteres da base com
`git rev-parse origin/main` e **cole-o**; o hook `commit-msg` recusa SHA
inexistente — inclusive um SHA legítimo de outro repositório.

**Leia integralmente antes de agir.** `data/validation/phase2a3-pilot-v1/`
inteiro, `data/validation/phase2a5-method-comparison-v2/`,
`scripts/build_validation_pilot.py`, a Phase 5 e a Phase 2A do roadmap na branch
de planejamento, e `PHASE_3_INPUTS_2026-09-08.md`.

**Base.** `claude/phase5-validation-protocol` a partir de `origin/main`.

### Escopo

1. **Medir a raridade do evento** sobre a extensão monitorada, com os dados que
   existem. É o insumo do tamanho amostral e não depende da Phase 4.
2. **Desenhar o quadro amostral**: estratos, pesos, e o estrato de mudança
   conhecida independente (§2). Registrar a escolha **com a razão e a
   alternativa recusada**.
3. **Calcular o tamanho amostral** a partir de um alvo de precisão declarado,
   por estrato, e dizer quantos casos-revisor isso significa.
4. **Atualizar o `PROTOCOL.md`** do piloto para um protocolo de acurácia:
   herdar cegamento, ordem, sequência e taxonomia; acrescentar o estrato de
   mudança conhecida e a regra de visita de campo.
5. **Escrever o cálculo** — precisão, recall, comissão, omissão, por estrato,
   com estimador ponderado e intervalo. Como código testado, não como fórmula
   em prosa.
6. **A declaração de não-afirmação**: o `claims` do manifesto, e **a redação do
   aviso do site** que a Phase 6 vai colar (§0, consequência 1).
7. **O pacote de rotulagem**: o que um revisor recebe, e o que ele não recebe.
   Herde o gerador do 2A.3 em vez de escrever outro.

**Fora de escopo, explicitamente:** rodar a amostragem sobre o candidato (ele
não existe até a Phase 4); recrutar ou instruir revisores; qualquer visita de
campo; e **mudar qualquer default** — a Phase 5 os valida, e mudá-los exige
evidência qualificada registrada. Não comece as Fases 3, 4, 6 ou 7.

## 4. Decisões de escopo já tomadas, com sua base

- **A Phase 5 não trava as Fases 6 e 7** — decisão do dono, 2026-09-08, com as
  duas consequências da §0.
- **Os defaults aceitos ficam como estão** até haver evidência qualificada:
  seca desabilitada, máscara SCL v2 e composição por datatake geram o candidato,
  o subconjunto de maioria 50% do MapBiomas é contextual, e rótulos espectrais
  públicos ficam desligados.
- **O piloto do 2A.3 não é um estudo de acurácia** e seus rótulos não podem ser
  reportados como tal — está escrito no próprio protocolo dele.
- **Nenhum rótulo do piloto ativa método nenhum** (`method_decision_status:
  none`).

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- A `main` é **pull-request-only**. Branch, PR, **sem merge**.
- Produção congelada nas Fases 2B–5. Nada de escrita em `araripe-cogs`, no
  Worker de produção, no domínio final, DNS, rotas, ponteiros canônicos ou
  workflows azuis.
- **Os pacotes de validação existentes são imutáveis.** `phase2a3-pilot-v1/` tem
  `CHECKSUMS.sha256` e um `artifact_inventory_rule`. Um pacote novo é um
  diretório novo com id próprio; **não** edite o antigo.
- **Nenhum dado pessoal de revisor no repositório.** O piloto usa ID pseudônimo,
  e isso é a regra, não um detalhe.
- Autonomia: desenvolvimento local, branches, verificações read-only, commits,
  pushes e abrir PR seguem sem aprovação. Qualquer coisa com efeito em produção
  espera.

## 6. Armadilhas já pagas — não redescobrir

- **Rotular só o que foi detectado mede comissão, nunca omissão.** É o motivo
  de o roadmap exigir a amostra independente, e é o erro mais comum em
  validação de alerta.
- **Um teste pode passar pelo motivo errado.** Pergunte qual mutação ele
  derruba; se nenhuma, conserte o código. Já aconteceu duas vezes neste projeto.
- **Varredura de texto tem de ignorar comentário** — use um helper de linhas
  executáveis; aconteceu três vezes numa sessão.
- **Nunca afirme invariante que o produtor não promete**, e não confie numa
  também.
- **Copie todo identificador da ferramenta que o produz.** Um SHA completado da
  forma curta já foi recusado pelo hook nesta semana.
- **`grep` desta máquina é `ugrep`**: `grep -qv` retorna 1 mesmo com linhas
  selecionadas.
- **`cut` não está disponível** no shell das ferramentas; use Python.

## 7. Ao final

Testes determinísticos para o cálculo — sem rede, sem relógio, sem dado real:
um estimador ponderado é exatamente o tipo de código que passa a parecer certo
com números plausíveis. Rode
`/opt/anaconda3/envs/araripe/bin/python -m pytest -q` e reporte falhas
pré-existentes em separado. Crie `docs/implementation/PHASE_5_<data>.md`. Abra a
PR **sem mesclar**. Termine com a seção final obrigatória do método de handoff.

## 8. Estado que este package herda

- **Phase 2B**: os packages 2B.0 a 2B.4 estão na `main`; falta o **exit gate**,
  cujo único item aberto é o montador da rodada.
- **Package 2A.6 fechado** em `claude/phase2a6d-mapbiomas`, **não mesclado**.
  `src/detection/ledger_v3.py` existe só lá.
- **Os pacotes de validação do 2A.3 e do 2A.5** existem localmente como
  untracked e são a base desta fase.
- **Cota de GEE não deve limitar a Phase 4** — ver `PHASE_3_INPUTS_2026-09-08.md`
  §1. Falta o dono abrir a página de cotas de `ee-araripe`.
- **Corte do replay recomendado: `2026-08-30`**, com a regra de re-resolução —
  mesma referência, §2.
- **Pendências do dono, nenhuma bloqueando esta fase:** o Environment protegido
  no repo do site, e um hostname para o Worker verde de staging.

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada — este documento **é** o insumo que você pediu. Ele existe para uma sessão
nova começar a Fase 5 sem depender das outras.

O que ele deixa registrado, e que vale você saber antes de aprovar: **a Fase 5
não trava nada, mas ela cobra duas coisas em troca.** A primeira é que o site
**não pode publicar número de acurácia** — nem precisão, nem "X% de acerto" —
antes do relatório existir. Ele publica os dados e o método, com um aviso dizendo
que a medição de acurácia ainda não foi feita. A segunda é que, se a validação
depois disser que algum critério deve mudar, o reprocessamento de 2026 tem de
ser refeito na parte afetada — o que é caro em tempo de máquina, mas cabe na cota
e o sistema já sabe voltar atrás numa publicação.

### O que você precisa fazer

1. **Ler a §2 e opinar sobre uma coisa só:** de onde vem a amostra de "mudança
   conhecida". É a decisão científica que decide se o relatório pode falar de
   *omissão* (o que o sistema deixou passar) ou só de *comissão* (o que ele
   apontou errado). Sem ela, metade do relatório não existe. Não precisa
   escolher agora — precisa saber que existe.
2. **Pensar em quem rotula.** Não é trabalho de agente: precisa de gente com
   competência em interpretação de sensoriamento remoto, e de pelo menos duas
   pessoas num subconjunto, para medir se elas concordam entre si. É o item de
   prazo mais longo de todo o roadmap, e é o único que começar agora encurta.
3. **Abrir a página de cotas do projeto `ee-araripe`** e me mandar duas linhas:
   o limite mensal e o uso atual. A página que você mandou é de outro projeto —
   o da baseline, não o da detecção.
4. **Anotar 6 de novembro:** a chave da NASA expira e a chuva do site para.

### Tem algo preocupante?

**Não.** Nada aqui é urgente e nada quebrou.

Vale registrar uma coisa que é boa notícia e uma que é honesta.

A boa: **já existe um protocolo de revisão** feito na Fase 2A.3, com cegamento,
ordem fixa dos casos, taxonomia de rótulos e dupla revisão em 20% — e com uma
declaração explícita, dentro do próprio pacote, de que ele **não** é um estudo de
acurácia. A Fase 5 herda isso em vez de começar do zero.

A honesta: **a peça que falta é a mais difícil de todas**, e é a amostra de
mudança conhecida. Olhar só para o que o sistema apontou nunca revela o que ele
deixou passar — e "o que deixou passar" é exatamente o que um observatório de
desmatamento precisa saber sobre si mesmo.

### O que ainda falta no caminho

- **O fechamento da Fase 2B:** o montador da rodada, que é a próxima etapa e não
  depende de nada seu.
- **Fase 3 — congelar e ensaiar:** decidir a data de corte (recomendação:
  30/08/2026) e fotografar tudo antes de começar.
- **Fase 4 — reprocessar 2026 inteiro** num candidato guardado, sem publicar.
  É tempo de máquina, e a cota não deve limitar.
- **Fase 5 — esta:** o protocolo agora, a rotulagem quando houver pessoas, o
  relatório quando ela terminar. **Em paralelo, sem travar.**
- **Fase 6 — a troca final:** o novo substitui o antigo, a página passa a ler
  pela rota nova, o robô antigo é desligado, e a publicação passa a acontecer
  sozinha num horário. É aqui que entra a proposta guardada dos arquivos grandes.
- **Fase 7 — endurecimento:** CI completo, proteção de branch, acessibilidade e
  as skills reusáveis.
