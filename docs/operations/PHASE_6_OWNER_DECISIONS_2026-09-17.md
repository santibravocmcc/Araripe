# Dossiê de decisão da Phase 6 — para o dono

**Escrito:** 2026-09-17
**Base verificada:** backend `origin/main` em
`9e1279e64edf5019c2a45f995820bb4e06d8ccca`, site `origin/main` em `6f11076`
**Origem:** os seis pontos da §9 de
[`PACKAGE_P6_PROMPT.md`](PACKAGE_P6_PROMPT.md), com a decisão do bucket da §3
desenvolvida como D1.

Cada decisão traz: **o que está em jogo** em uma frase, as **opções**, o
**custo medido** de cada uma, a **recomendação com o porquê**, e **o que
acontece se esperar**. Onde faltava medição eu medi antes de recomendar; onde
não dá para medir, está dito que não dá.

**Nenhuma mutação foi executada para escrever isto.** As leituras do R2 foram
`s3 ls` e um `s3 cp` do ponteiro para a saída padrão. Nenhum workflow foi
disparado.

---

> ## ✅ RESPONDIDO em 2026-09-18 — as seis, e todas seguindo a recomendação
>
> Registrado em
> [`../../config/phase6_owner_decisions_v1.json`](../../config/phase6_owner_decisions_v1.json).
>
> | | decisão | resposta |
> | --- | --- | --- |
> | D1 | onde a versão nova mora | **(a) promover `araripe-v2-staging`** |
> | D2 | a revisão pré-virada | **(i) revisar agora** |
> | D3 | endereço de teste | **(i) subdomínio `workers.dev` temporário** |
> | D4 | Environment do site | **(i) criar com revisor obrigatório** |
> | D5 | registro de versões | **(i) construir antes da virada** |
> | D6 | corrigir o plano | **(i) autorizar** |
>
> **Duas ressalvas que o leitor precisa levar daqui:**
>
> 1. **A D2 escolheu o cronograma, não o resultado.** *"Revisar agora"* não é
>    *"revisei e aceito"*. A revisão continua **pendente** e é sobre os **três**
>    itens que restaram na §7 do runbook — a D1 e a D5 fecharam dois.
> 2. **A condição de ordem da D1 estava CEDO DEMAIS e foi corrigida.** Eu
>    escrevi *"revogar depois de os produtos do site estarem gerados"*. Medido
>    em 2026-09-18, isso é a restrição errada duas vezes: os produtos do site
>    **nunca** precisaram desta credencial — `site_artifact.py` lê a release por
>    `RouteReader`, um GET sem credencial, e `green_site_publish.yml` não
>    referencia segredo de R2 nenhum. Quem precisa dela é a **D5**: reprovar a
>    mudança de `promote`/`rollback` exige escrever no R2, a mudança vive numa
>    branch até mesclar, e os **três** Environments do backend têm política de
>    branch `main` **só** (conferido por `gh api`). **Revogar é o último passo,
>    depois da D5 reprovada** — antes disso, a reprova só seria possível
>    mesclando código não provado na `main`, o que inverte a ordem de segurança
>    que o pacote existe para proteger.

---

## Sumário — o que eu recomendo, em uma linha cada

| | decisão | recomendação | urgência |
| --- | --- | --- | --- |
| **D1** | onde a versão nova mora de vez | **(a) promover `araripe-v2-staging`**, revogando a chave **depois** dos produtos gerados | **alta — primeiro passo da virada** |
| **D2** | a revisão pré-virada | **revisar agora**; a lista foi reescrita hoje contra os fatos | alta |
| **D3** | endereço de teste do servidor novo | **subdomínio `workers.dev` temporário**, fechado depois | alta |
| **D4** | lugar protegido de credencial no site | **criar com revisor obrigatório** | alta |
| **D5** | registro permanente de versões antes ou depois | **antes — e ele não espera portão nenhum** | média |
| **D6** | corrigir o documento do plano | **autorizar**; vai junto na próxima PR de documento | baixa |

---

## D1 — Onde os dados da versão nova vão morar de vez

**Em jogo:** o depósito de que o site público passará a depender é hoje
governado por um documento que o chama de descartável e proíbe explicitamente
que ele seja alvo de promoção.

O texto que cria o conflito, em
[`CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md`](CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md):
*"This bucket is an object-level development sandbox. It is **not** a canonical
release bucket, public bucket, or promotion target"*, e na seção Revocation:
revogar a chave *"before repurposing the bucket"*.

### As opções

**(a) Promover `araripe-v2-staging`** a depósito canônico verde.
**(b) Criar um depósito final** e copiar a release para lá.

### Custo medido de (a)

| item | medição |
| --- | --- |
| dados a mover | **zero** |
| código a mudar | **zero** — `assert_staging_target` já aponta para este bucket |
| config do Worker verde | **zero** — `wrangler.green.jsonc` já liga `STAGING_BUCKET → araripe-v2-staging` |
| documento a reescrever | 1 — o que o governa |
| ação de control-plane sua | 1 — revogar `claude-araripe-v2-staging-rw` no painel |

**A consequência de ordem, e ela é a única armadilha de (a):** essa chave é a
que eu uso para **ler** a release. O item 2 da §4.1 da fase — gerar os produtos
do site a partir do manifesto — precisa dela. Revogar antes disso bloqueia o
único trabalho substancial que hoje não depende de portão nenhum.
**Revogue depois, não antes.**

### Custo medido de (b)

O volume é o menor dos custos, e é este:

| o que se copiaria | objetos | bytes |
| --- | --- | --- |
| a release atual `rel-g1-fb722b2d…` | **74** | **1 778 202 736** |
| todas as releases | 99 | 1 913 078 973 |
| o bucket inteiro | 210 | 3 904 281 427 |

O custo que decide é outro, e é tudo medido hoje:

- **eu não consigo executar a cópia.** A credencial de staging é negada em
  qualquer outro bucket: testada contra `araripe-cogs` e contra um nome novo,
  `AccessDenied` nas duas;
- **não existe ferramenta de cópia.** `grep` por
  `copy_object|CopySource|copy_from` em `src/` e `scripts/` devolve nada;
- **(b) exige editar o guarda de isolação.** `assert_staging_target()` recusa
  fail-closed qualquer bucket que não seja `araripe-v2-staging` e qualquer
  endpoint que não seja o aprovado. É a primeira linha de defesa que mantém a
  publicação verde longe da produção, afirmada em cinco lugares entre testes e
  scripts. Afrouxá-la no mesmo pacote em que a lane verde vira pública é
  exatamente o tipo de mudança que não se quer fazer sob pressa;
- **e exige control-plane seu duas vezes**: criar o bucket e criar uma
  credencial nova — nenhuma das duas está na allowlist do broker.

### Recomendação: **(a)**, com a ordem invertida na revogação

O argumento que o briefing levanta a favor de (b) é real e merece resposta
direta: *depois da virada, uma credencial com DELETE alcança o depósito de que
o site público depende*. Eu medi as duas metades disso:

1. **a credencial realmente apaga.** No R2 a permissão de DELETE vem junto com
   a de WRITE, com escopo por bucket e sem prefixo. O limite hoje é o
   **código**: `ConditionalStore` expõe `get`, `require`, `put_if_absent`,
   `put_if_match` e `put_if_pointer_absent` — nenhum delete, nenhum put
   incondicional. Isso é suficiente para um sandbox e é uma afirmação mais
   fraca do que se quer para produção;
2. **mas a credencial em questão é a minha, e (a) já manda revogá-la.** Depois
   da revogação, o alcance de DELETE ao depósito público é o mesmo nos dois
   caminhos: nenhum agente o tem. O argumento não separa (a) de (b) — ele
   separa "antes de revogar" de "depois de revogar".

E um segundo argumento a favor de (b) que eu **cheguei a escrever e retirei
depois de medir**: "um depósito público exporia os prefixos `runs/` de 1,99 GB
e o resíduo das sondagens". **É falso.** A rota verde nunca monta a chave a
partir da requisição: o caminho pedido é procurado numa allowlist construída do
manifesto da **release viva**, e a chave é `release_prefix` mais aquele caminho
declarado (`site/worker/data_route.js`). Então `runs/`, os prefixos de sondagem
e qualquer release que não seja a viva são inalcançáveis **por construção**, e
não por filtragem. O ganho de arrumação que (b) prometia não existe.

Sobra, a favor de (b), manter o sandbox descartável — o que é real, mas custa
um bucket novo, uma credencial nova, código novo e uma edição no guarda de
isolação, para comprar uma propriedade que (a) obtém revogando uma chave.

### Se esperar

É o primeiro passo da virada: nada do §4.4 pode acontecer sem saber qual
depósito o site vai ler. Enquanto esperar, a produção segue cega (ver "o que
preocupa", no fim).

---

## D2 — A revisão pré-virada

**Em jogo:** o roadmap exige a sua revisão explícita antes da virada, e a lista
que existia pedia que o senhor concordasse com frases que deixaram de ser
verdade.

### O que eu fiz antes de trazer a lista

Reescrevi a §7 de [`PHASE_3_REPLAY_RUNBOOK.md`](PHASE_3_REPLAY_RUNBOOK.md)
contra os fatos de hoje, com a tabela do diff dentro do próprio documento, para
o senhor ver o que mudou e não só o resultado. Das quatro cláusulas abertas:

| cláusula | o que aconteceu |
| --- | --- |
| os alvos resolvidos da §1 | **mantida** — reconferida hoje, `pytest tests/test_replay_freeze.py` → 55/55 |
| a regra do corte | **reescrita** — deixou de ser regra e virou o literal `2026-08-30` |
| o procedimento, *"incluindo que a produção azul continua rodando"* | **reescrita — a premissa é falsa** |
| a divergência de unidade de composição | **fechada** — a Phase 4 respondeu as duas metades |
| — | **acrescentada** — o ponteiro vira público sem revisor e sem histórico |
| — | **acrescentada** — a própria D1 |

### As opções

(i) revisar agora a lista reescrita; (ii) revisar depois.

### Custo

(i) custa o seu tempo de leitura de seis itens, todos com evidência apontada.
(ii) custa a virada inteira: sem a revisão, ela não começa.

### Recomendação: **(i)**

Não porque a lista seja urgente em si, mas porque ela é o portão mais barato
dos quatro — é o único que não depende de painel, credencial ou código.

### Se esperar

Bloqueia tudo o que vem depois do §4.1.

---

## D3 — Um endereço de teste para o servidor novo

**Em jogo:** o Worker verde não tem endereço nenhum — de propósito — e sem
endereço a rota nova não pode ser verificada contra dado real num navegador.

O bloqueio é a isolação funcionando: `public_subdomain_enabled` é `false`,
`custom_domain_count` é `0`, `route_count` é `0`, e `cloudflare_green_control.py::audit`
afirma os três fail-closed.

### As opções

**(i)** um subdomínio `workers.dev` temporário;
**(ii)** uma rota de zona num hostname **não-final**;
**(iii)** não abrir nada, e aceitar a verificação que já existe sem rede.

### Custo medido

**(iii) primeiro, porque ele define o que as outras duas compram.** `wrangler dev`
já verifica a rota verde **sem credencial nenhuma** — o R2 é simulado
localmente, e 29/29 checagens de conformidade passaram sobre HTTP. Então (iii)
não é "não verificar". O que ele **não** consegue provar, e que só uma rede
responde:

- que o `Content-Length` e o `sha256` de um produto servido batem com o
  manifesto da release **real** (o simulador serve bytes locais);
- que o `Cache-Control` do ponteiro chega como `no-store` pela borda real, e
  que um rollback aparece numa página recarregada dentro da janela;
- que **nenhum** `Access-Control-Allow-Origin` sai em resposta nenhuma;
- que o modo de alertas completos, que hoje puxa ~13,8 MiB, renderiza pela rota
  verde num navegador de verdade;
- que `?download=1` produz um arquivo nomeado pelo caminho declarado.

**(i) e (ii)** custam a mesma coisa em processo: uma mudança no broker
protegido (uma PR) **mais** um disparo revisado, e pelas regras as duas não
podem ser feitas na mesma tarefa. Mais a sua aprovação no Environment
`cloudflare-green-control`, que tem revisor humano obrigatório — e isso não
muda, porque o token dele edita em nível de conta.

A diferença entre (i) e (ii): o subdomínio `workers.dev` não toca zona, DNS nem
rota do domínio final, e já existe uma operação allowlistada para fechá-lo
depois (`enforce-worker-isolation`). Uma rota de zona toca a configuração da
zona do domínio — mais superfície, para a mesma verificação.

**Uma alternativa que já foi medida e descartada:** binding remoto no
`wrangler dev`. O campo é `remote` (`experimental_remote` só avisa e lê local),
e ele **cria um Worker de proxy na conta**, o que exige permissão Workers-Edit —
exatamente a credencial que eu não posso receber.

### Recomendação: **(i) subdomínio `workers.dev`, aberto só pela duração da verificação**

Menor superfície, fechamento já scriptado, e não encosta no domínio final. Com
uma condição de ordem: **as afirmações da auditoria têm de ser atualizadas
enquanto ele estiver aberto**, senão o deploy verde derruba a própria auditoria
que prova a isolação.

### Se esperar

Travam os passos 4, 5 e 6 da migração — ou seja, a virada inteira. É o portão
mais caro em processo dos quatro, então ele é o que mais vale começar cedo.

---

## D4 — Um lugar protegido para credenciais no repositório do site

**Em jogo:** implantar o servidor novo exige guardar uma identidade de deploy, e
o repositório do site não tem onde.

**Medido hoje:** `gh api repos/santibravocmcc/observatorio-site/environments`
devolve **`[]`**. O backend tem três (`cloudflare-green-control` **com** revisor,
`v2-promotion` e `v2-staging` **sem**); o site, nenhum.

**A razão de o revisor não ser opcional, e ela é concreta:** no Cloudflare a
permissão de Workers é de **conta**, não de Worker. Quem implanta o Worker verde
implanta o de produção.

### As opções

**(i)** criar o Environment com revisor obrigatório;
**(ii)** o senhor implantar o Worker verde à mão, do seu computador, sem
Environment.

### Custo medido

**(i):** configuração de repositório, poucos minutos. A lane que o consome
**já existe e já o nomeia**: `site/.github/workflows/green_site_publish.yml`
tem um job `publish` que recusa e imprime exatamente as duas capacidades que
faltam — este Environment e o hostname da D3. Ela está completa e inerte de
propósito, e é `workflow_dispatch` só.

**(ii):** zero configuração, mas sem trilha de auditoria e sem revisor no
caminho que pode implantar produção. E repetido a cada deploy.

**Uma nota de escopo que vale dizer:** este portão bloqueia **automatizar** o
deploy verde. A troca do consumidor (`alertas.js`) passa pelo caminho de deploy
de produção que já existe e não precisa dele. Mas não se troca para uma rota que
não foi implantada — então ele bloqueia a virada de qualquer jeito, por
transitividade.

### Recomendação: **(i)**

E uma armadilha, porque ela já custou caro em outros lugares: **nunca nomeie um
Environment que não existe.** O GitHub cria o que for nomeado, sem proteção e
sem política de branch — e aí o senhor tem um lugar de credencial sem revisor
com nome de lugar protegido.

### Se esperar

Mesma consequência da D3: a rota verde não vai ao ar.

---

## D5 — O registro permanente de versões vem antes ou depois da virada

**Em jogo:** hoje o sistema consegue nomear **uma** versão para trás, e depois
da virada é o público que segue esse ponteiro.

### O que eu medi no depósito, hoje

| | |
| --- | --- |
| releases que existem | **7** |
| releases que o ponteiro consegue nomear | **2** — a atual `rel-g1-fb722b2d…` e `supersedes` → `rel-g1-24db9555…` (sequence 9) |
| releases órfãs do ponteiro | **5** |

Uma delas, `rel-g1-2ddb10c7…`, **esteve no ar** como sequence 8 e só sobrevive
porque foi copiada à mão para um registro.

E o `v2-promotion` **não tem revisor obrigatório** (confirmado hoje pela API),
com a base registrada em
[`PROMOTION_IDENTITY_SETUP.md`](PROMOTION_IDENTITY_SETUP.md) sendo literalmente
"é um sandbox" — mais a frase que manda revisitar: *"no cutover o ponteiro verde
passa a ser o que o site público segue, e aí a conta de um erro deixa de ser um
sandbox."*

### As opções

**(i)** construir o registro antes da virada;
**(ii)** aceitar o risco por escrito e construir logo depois.

### Custo medido

**(i):** está especificado — *"um objeto imutável e write-once por escrita de
ponteiro"* — e a razão de não ter sido construído está registrada: ele
acrescenta uma escrita a `atomic_publish.promote` e `rollback`, e esse caminho
foi provado ponta a ponta contra o R2 real cinco vezes em 2026-09-07. Mudá-lo
faz aquelas provas não cobrirem mais o código que roda. *"Construir, reprovar,
depois estender a política — isso é um pacote por si."*

**E aqui está o que muda a conta, e eu só vi ao medir:** construir **e reprovar**
esse pacote **não depende de portão nenhum**. Ele escreve em
`araripe-v2-staging`, com a credencial que eu já tenho, e não toca produção,
Worker, DNS nem domínio. É o único trabalho substancial da fase que não espera
o senhor.

**(ii):** entre a virada e o registro, uma promoção errada só volta um passo, e
quem segue o ponteiro é o público. O `rollback` em si é seguro — ele recarrega a
release alvo do store, revalida o ledger inteiro e confere cada objeto declarado
**antes** de mover o ponteiro. O que é curto não é a segurança da volta, é o
**alcance**: um passo.

**O que eu considerei e retirei:** exigir revisor no `v2-promotion` como
mitigação barata. Não serve — o objetivo declarado do Package 2B.2C é
*"keep operational data publication automatic without PRs or manual merges"*, e
um revisor obrigatório em cada publicação agendada anula o próprio pacote. A
mitigação certa é o registro, não o revisor.

### Recomendação: **(i), construir antes — e começar já, em paralelo com D1–D4**

Não porque o risco de (ii) seja intolerável, mas porque **a virada está parada
esperando três ações suas de qualquer forma**, e este é o único pacote que anda
sem elas. Fazê-lo agora não atrasa a virada em um dia sequer: ele ocupa o tempo
que já vai passar.

Se o senhor preferir (ii) mesmo assim, ela é defensável — mas então a aceitação
precisa estar escrita e datada, porque é um risco que o público passa a correr.

### Se esperar

Nada trava. É a única das seis que não bloqueia nada.

---

## D6 — Autorizar a correção do documento do plano

**Em jogo:** o `ROADMAP.md` ainda diz que a próxima frente é a Phase 3, e as
Fases 3 e 4 fecharam.

**Medido:** o bloco datado do topo termina em *"**Próxima frente: Phase 3.**"*,
e o fechamento da Phase 3 não o atualizou; o da Phase 4 também não.

### As opções

(i) autorizar a correção agora; (ii) deixar para o fim da fase.

### Custo

(i) meia hora, nenhum risco, entra numa PR de documento junto com outra coisa.
(ii) zero esforço agora.

### Recomendação: **(i)**

Pelo precedente: este projeto já perdeu trabalho por planejar contra o documento
errado — foi o incidente dos dois `ROADMAP.md`. Uma linha de "próxima frente"
desatualizada é a mesma classe de erro, mais barata de consertar do que de
descobrir.

### Se esperar

Uma sessão futura pode planejar contra uma frente que fechou. Baixo risco,
custo baixo de eliminar.

---

## O que não é decisão sua, e por que está aqui

**A Phase 5 não é portão desta fase** — o senhor já decidiu isso. Mas a
consequência vale repetir: até o relatório dela sair, **nada pode ser publicado
como "precisão do sistema"**. O que a virada publica é **dado e método**.

---

## O relógio — e ele é a razão de tudo acima ter urgência

**O sistema no ar não detecta desmatamento novo desde 3 de setembro**, e o dado
mais recente do site é de **30 de agosto**.

Medido hoje com `gh run list`, e é pior do que o último registro dizia:
`detect_gee.yml` falhou em **quatro** execuções agendadas —
**2026-09-10**, **2026-09-14** e **2026-09-17 (hoje)** com
`LegacyPersistenceStateError`, mais 2026-09-07 por outra causa. A última escrita
em produção foi a execução **manual** de 2026-09-07 15:15 UTC.

O que conserta é **esta fase**: o arquivo de estado de geração nova que a
detecção exige é o que a Phase 4 depositou em staging — 986 744 489 bytes,
digest `5eb17f838b35251b3748dbc26310918a8fa7a00ce99b4f3c501dd5887ac987ce` — e
ligá-lo à produção é um item da virada, não um remendo à parte.

**Quanto mais a virada demorar, mais tempo o sistema fica cego.** Não é
emergência de horas; é o peso que deve entrar nas decisões D1 a D4.

Duas coisas que **não** são alarme, e que eu confirmei: a página não mente sobre
o frescor do dado — o arquivo interno que diz "atualizado" não é lido por página
nenhuma; e o token da NASA expira em **6 de novembro**, ainda com tempo.
