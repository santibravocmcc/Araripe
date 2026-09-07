# Provas executadas em 2026-09-07: identidade de promoção e lanes verdes

Três provas pendentes desde o Package 2B.0 e o 2B.2B foram executadas contra os
sistemas reais. **Duas passaram. Uma falhou, e a falha é um defeito de
configuração que precisa de ação do dono.**

Nenhuma operação de produção foi executada. Ver §4 para um defeito no
*procedimento* documentado da prova das lanes, que pedia justamente isso.

---

## 1. O R2 realmente aplica as duas precondições — primeira medição

O Package 2B.2B construiu a publicação sobre `If-None-Match` e `If-Match` e
provou o próprio comportamento contra um armazenamento em memória, porque a
política de branch do Environment `v2-staging` só admite `main`. A documentação
da Cloudflare dizia que o R2 as aplica; **ninguém havia medido.** Se o R2 as
ignorasse, a imutabilidade dos releases e o compare-and-swap do ponteiro
estariam desligados em produção sem sinal algum.

Medido agora, com o código real de `src/publication/conditional_store.py`
(run [34164992026](https://github.com/santibravocmcc/Araripe/actions/runs/34164992026)):

| Checagem | Resultado |
| --- | --- |
| guarda de alvo e suporte a escrita condicional | **PASS** |
| listar `araripe-v2-staging` | **PASS** |
| `araripe-cogs` é recusado para esta identidade | **FAIL** — ver §2 |
| criar objeto novo com `If-None-Match: *` | **PASS** (`created`) |
| os mesmos bytes de novo são no-op idempotente | **PASS** (`unchanged`) |
| bytes diferentes na mesma chave são recusados | **PASS** — o R2 devolveu falha de precondição |
| ler o objeto de volta byte a byte | **PASS** |
| compare-and-swap com o ETag atual | **PASS** |
| compare-and-swap com ETag velho **perde** | **PASS** — o R2 devolveu falha de precondição |

**Oito de nove.** As duas linhas que importavam mais — bytes diferentes
recusados e ETag velho perdendo — confirmam que o R2 aplica ambas as
precondições de verdade. O desenho do 2B.2B está validado contra o sistema
real, e não só contra o próprio teste.

### O piso do botocore, medido na imagem do runner

O primeiro run
([34164434461](https://github.com/santibravocmcc/Araripe/actions/runs/34164434461))
falhou em `require_conditional_write_support` antes de tocar objeto:

> this botocore does not accept IfMatch, IfNoneMatch on PutObject … Refusing to
> publish: an unconditional PutObject would overwrite silently.

Causa medida no run seguinte, que agora imprime a versão antes e depois:

    botocore before: 1.34.46
    botocore after:  1.43.89 / boto3 1.43.89

A imagem do runner traz **1.34.46**, anterior à escrita condicional, e um
`pip install boto3` sem piso é satisfeito por ela. A guarda recusou em vez de
emitir `PutObject` sem precondição contra um bucket real — sem ela, o run teria
passado com a imutabilidade e o CAS desligados. Vale registrar porque no
Package 2B.2B essa guarda foi descrita como alcançável mas com dúvida sobre
valer a pena; valeu.

Consequência para outro arquivo, **não alterada aqui**: `environment.yml` pina
`botocore>=1.35.0,<1.36.0`, faixa em que `IfNoneMatch` existe e `IfMatch`
**não** (tabela medida em `PHASE_2B2C_2026-09-07.md`). Write-once funcionaria e
o CAS do ponteiro seria inexpressável — falha assimétrica. As lanes verdes
instalam o próprio cliente exatamente para não depender disso; mexer no
`environment.yml` altera o que os workflows **azuis** instalam e precisa de
aprovação humana.

## 2. A identidade de promoção está com escopo amplo demais — AÇÃO NECESSÁRIA

A única checagem que falhou:

> **FAIL** `araripe-cogs` is refused for this identity — THE LIST SUCCEEDED —
> the token is over-scoped and isolation is broken.

**A chave de promoção consegue ler o bucket de PRODUÇÃO.** Ela deveria alcançar
só `araripe-v2-staging`.

Isto não é uma falha do código: `conditional_store.assert_staging_target`
recusa `araripe-cogs` pelo nome antes de ler credencial, e nenhum caminho da
publicação o endereça. É a **segunda camada** que está ausente — a razão de
existir uma chave restrita a um bucket é que, mesmo se o código estivesse
errado, a credencial não alcançaria produção. Hoje essa camada não existe.

**O que não foi testado, e deliberadamente:** se a chave também **escreve** em
`araripe-cogs`. Testar isso seria mutação de produção, proibida nas Fases
2B–5. Como o R2 oferece `Object Read & Write` como um nível único, o prudente é
assumir que sim.

### Como corrigir

1. No Cloudflare, **revogue** o token `araripe-green-promotion-rw`.
2. Crie outro, `Object Read & Write`, e em **Apply to specific buckets only**
   marque **exatamente** `araripe-v2-staging` — é este passo que faltou.
3. Atualize `R2_PROMOTION_ACCESS_KEY_ID` e `R2_PROMOTION_SECRET_ACCESS_KEY` no
   Environment `v2-promotion`.
4. Redisparate o probe. Ele deve ficar **9 de 9**.

**Até lá, não dispare `v2_operational_publish.yml` no modo `promote`.** A lane
funcionaria, mas com uma credencial que alcança produção — e a defesa em
profundidade do Package 2B.0 é justamente o que essa lane pressupõe.

## 3. A prova das lanes do Package 2B.0 — três das quatro execuções

Pendente desde 2026-08-11. Executada agora, com os horários como evidência:

| Run | Lane | Criado | Fim | Resultado |
| --- | --- | --- | --- | --- |
| [34165026961](https://github.com/santibravocmcc/Araripe/actions/runs/34165026961) | 2, `araripe-green-candidate` | 21:58:33 | 21:58:49 | success |
| [34165030692](https://github.com/santibravocmcc/Araripe/actions/runs/34165030692) | 3, `araripe-green-promotion` (A) | 21:58:37 | 21:59:45 | success |
| [34165036367](https://github.com/santibravocmcc/Araripe/actions/runs/34165036367) | 3, `araripe-green-promotion` (B) | 21:58:45 | 22:00:52 | success |

O que os horários provam, sem depender de nenhuma afirmação:

- **A lane 3 serializa.** B foi criada às 21:58:45, enquanto A ainda corria (até
  21:59:45), e foi observada com status `pending`. Só terminou às 22:00:52 —
  cerca de 68 s de espera, que é o `hold_seconds=60` de A mais o overhead. Duas
  promoções não se atropelam.
- **A lane 2 não é afetada.** O run do candidato correu de 21:58:33 a 21:58:49,
  **inteiramente dentro** da janela em que A detinha o lock, e concluiu com
  sucesso. Nenhuma fila entre as lanes.

## 4. Defeito no procedimento documentado — a quarta execução não foi feita

`GREEN_CONCURRENCY_LANES.md` descrevia a prova como quatro execuções, incluindo
*"a legacy manual run executes"*. **Essa quarta execução não foi disparada, e
não deve ser.**

O membro manual da lane 1 é `update_data.yml`, que busca as baselines e o
estado de persistência do R2 de **produção**, roda a detecção, e sobe alertas e
estado de volta para `araripe-cogs`. Disparar isso é mutação de produção,
proibida nas Fases 2B–5 — e a detecção não é idempotente, então um run extra
infla `n_sightings`. O procedimento foi escrito em 2026-08-11, **antes** do
congelamento, e envelheceu sem que ninguém notasse.

A metade azul da propriedade não precisa de execução: grupos de concorrência
são strings, os workflows azuis declaram `araripe-legacy-state`, os verdes
declaram nomes distintos, e o GitHub não enfileira entre grupos diferentes.
`tests/test_workflow_lanes.py` afirma exatamente isso a partir dos arquivos.
O procedimento no documento foi corrigido para dizer isso em vez de pedir uma
execução proibida.

## 5. O que estas provas fecham, e o que não

**Fechado:** o R2 aplica as duas precondições (§1); a lane 3 serializa e a lane
2 não é afetada (§3); o piso de botocore está medido e pinado (§1).

**Aberto:** o escopo da credencial (§2) — depende do dono; a publicação
end-to-end no modo `promote`, que não deve ser disparada antes de §2; e a
integração com um ledger de rodada real do 2A.6, que o gate P2B exige.

---

## 6. Publicação operacional de ponta a ponta, contra o R2 real

Depois de o dono recriar a chave restrita ao bucket, o probe voltou **9 de 9**
(run [34166180531](https://github.com/santibravocmcc/Araripe/actions/runs/34166180531)),
com `araripe-cogs is refused for this identity — code AccessDenied`. Com a
credencial provada, a cadeia 2B.2A → 2B.2B → 2B.2C foi exercitada inteira
contra o R2, **sem nenhum pull request no caminho do dado**.

A rodada de teste foi montada à mão e enviada para `runs/<run-id>/` com a
identidade **local** de staging — a peça que o Package 2B.2C deixou para uma
pessoa ("o sistema sabe publicar uma rodada; quem a monta ainda é uma pessoa").
O script que a montou vive fora do repositório, no scratchpad da sessão: ele é
andaime de prova, não produto.

| # | Rodada | Cobertura | Esperado | Resultado |
| --- | --- | --- | --- | --- |
| 1 | `proof-a-2026-09-07` | 04-07 … 04-10 | publica e promove | **4 created**, ponteiro em **sequence 1** |
| 2 | a mesma, de novo | idem | no-op idempotente | **0 created, 4 already identical**, ponteiro **unchanged**, sequence **continua 1** |
| 3 | `proof-b-older` | 04-01 | **recusa** | `PromotionRefused … [coverage_regression]` |
| 4 | `proof-c-newer` | 04-07 … 04-13 | promove com tombstone | **sequence 2**, supersede de A, **1 tombstone** |

### O que cada linha estabelece, e que não era estabelecível antes

**Linha 1 — a identidade derivada é reprodutível entre máquinas.** O
`release_id` que o runner calculou,
`rel-g1-ae3f6e1db152ac608f5e63d2fe2d6f4357f0f311ad5582070dfabf9e91828827`, é
**byte a byte o mesmo** que o `plan` local havia impresso horas antes para o
mesmo ledger, noutra máquina e noutro sistema operacional. A propriedade
"mesmo ledger → mesmo prefixo" deixou de ser um teste e passou a ser um fato
observado.

**Linha 2 — republicar é grátis.** `0 created, 4 already identical` prova que o
caminho do `412` seguido de comparação de bytes funciona no R2 de verdade, e
que a sequência do ponteiro **não** avança num no-op.

**Linha 3 — a regra que mais importa.** A recusa veio com a mensagem inteira:

> the candidate covers through 2026-04-01 while the live release … covers
> through 2026-04-10. An older run may not replace a newer release; use
> rollback to move the pointer backwards deliberately.

E o detalhe que mostra o desenho funcionando: os objetos da rodada antiga
**foram publicados** (`3 created`) sob o prefixo imutável dela, e o ponteiro
**não se moveu** — verificado depois, ainda em `sequence 1`. Publicar é seguro
e idempotente; promover é o passo com portão. Uma rodada antiga não corrompe
nada: ela só não é servida.

**Linha 4 — supersede e tombstone reais.** O ponteiro foi para `sequence 2`,
registrou `supersedes` com a cobertura de A, e produziu **um** tombstone:
`absent_from_successor` para `2026-04-10` — o artefato do dia de zero alertas
que a rodada C não republica. Nada foi apagado.

### O que continua NÃO provado executavelmente

**Reverter.** O gate P2B pede *"move **and roll back** its green pointer"*, e o
movimento está provado. A reversão não: `v2_operational_publish.yml` não tem
modo de reversão, e o modo `rollback` de `v2_promotion_lane.yml` ainda **para**
com uma mensagem que dizia faltar a identidade protegida — **mensagem agora
obsoleta**, porque o Environment `v2-promotion` existe e está provado. A
reversão só é exercitável do CI, porque a credencial de promoção vive apenas no
Environment e não deve existir localmente. Ligar aquele modo é o passo que
fecha a cláusula.

---

## 7. A reversão, provada — a cláusula do gate fecha

`v2_promotion_lane.yml` ganhou o modo `rollback` num job separado, o único do
arquivo a declarar `environment: v2-promotion` (PR #42). Dispatch
[34167023754](https://github.com/santibravocmcc/Araripe/actions/runs/34167023754),
revertendo do release C para o release A:

    pointer  : rollback -> rel-g1-ae3f6e1db152ac608f5e63d2fe2d6f4357f0f311ad5582070dfabf9e91828827
               at sequence 3, 1 tombstone(s)

Lido de volta do bucket:

| campo | valor |
| --- | --- |
| `action` | `rollback` |
| `sequence` | **3** |
| `release_id` | A, cobrindo até **2026-04-10** |
| `rolled_back_from` | C (`rel-g1-5ffad23a…`), sequence 2 |
| `supersedes` | C, `last_observed_on` **2026-04-13** |
| `tombstones` | 1, `absent_from_successor` |

### Os dois eixos, visíveis numa única sequência de três escritas

    sequence :  1        →  2        →  3
    cobre até:  04-10    →  04-13    →  04-10

**A sequência só cresce; a cobertura foi e voltou.** É a propriedade central do
contrato (`GREEN_RELEASE_CONTRACT_V1.md` §6) observada em execução, não
afirmada num teste: "qual escrita é mais recente" e "qual dado é mais novo" são
perguntas diferentes, e é por isso que `promote` compara cobertura enquanto
`rollback` é uma operação nomeada à parte. Um teste de recência por sequência
teria deixado a reversão passar por "avanço".

E a reversão não é um atalho: ela releu o release A **do próprio bucket**,
revalidou-o inteiro incluindo o ledger, e verificou que todos os objetos
declarados seguiam presentes, antes de tocar o ponteiro. O ponteiro só pode
nomear um release que ainda esteja completo.

**Com isto a cláusula do gate P2B está fechada em execução:** *"a staged test
release can move and roll back its green pointer without a manual data PR or
any production effect."* Nenhum pull request participou de nenhum dos cinco
movimentos, e nenhuma operação tocou produção.

## 8. O que ficou no bucket, e por que isso é do Package 2B.3

Nada foi apagado — `ConditionalStore` não tem operação de delete. O que
`araripe-v2-staging` contém depois destas provas:

    pointers/green/current.json                  o ponteiro (1 objeto mutável)
    releases/rel-g1-<A|B|C>/…                    3 releases imutáveis, 11 objetos
    runs/proof-{a,b,c}…/…                        3 prefixos de rodada, 11 objetos
    promotion-identity-probe/run-…/…             2 rodadas do probe, 4 objetos
    green-isolation-proof/run-…/…                2 rodadas do 2B.0, 2 objetos

São artefatos de prova, não produto, e ficam como evidência auditável até que
exista política de retenção. **Definir essa política é do Package 2B.3** — que é
a primeira etapa do roadmap em que este projeto poderá apagar qualquer coisa.
Estes objetos são o primeiro caso de teste dela: um release **que já esteve
live** (`rel-g1-5ffad23a…`, revertido) não é o mesmo caso que um release que
nunca foi promovido (`rel-g1-9f1ed344…`, o da cobertura antiga recusada), e a
política tem de distinguir os dois.
