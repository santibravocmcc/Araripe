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
