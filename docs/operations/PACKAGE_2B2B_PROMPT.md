# Package 2B.2B — briefing de execução

Escrito em 2026-09-07, depois de fechar a implementação do Package 2B.2A.
Base de referência do 2B.2A: `origin/main` em
`ff4eea6e6358e2561a4823caa701a41235d91029`.

Este documento vive na `main` pelo mesmo motivo que o do 2B.2A: o executor
trabalha a partir da `main`, e um briefing que só existisse noutra branch
repetiria a falha de leitura entre branches que o `AGENTS.md` proíbe.

---

## 1. Dependência que precede tudo: a PR #33

**O 2B.2B constrói sobre o `src/publication/` que o 2B.2A criou.** Se a PR #33
não estiver mesclada, esse pacote não existe na `main` e não há consumidor de
ledger sobre o qual publicar.

Confirme **por conteúdo, nunca por ancestralidade** (os dois repositórios
fazem squash merge):

    git show origin/main:src/publication/ledger_gate.py | head -5
    git show origin/main:docs/contracts/phase2b/ledger_contract_pin.json | head -5
    git log origin/main --grep '(#33)' --oneline

Se não estiver na `main`: **pare e pergunte.** Não faça branch a partir de
`claude/phase2b2a-ledger-binding` para "adiantar" — o 2B.2A tem uma pendência
de aprovação humana (o `environment.yml`, veja §2) e ramificar dele antes da
decisão duplica trabalho se a revisão pedir mudança.

Gate esperado na `main` depois do #33: **281 passed** (era 212 antes). Confirme
com `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` antes de editar.

## 2. O que já foi verificado, para o executor não refazer

Tudo abaixo foi conferido em 2026-09-07 com a ferramenta que produz o valor.
São achados, não suposições.

**a. Existem DOIS `ROADMAP.md` com o mesmo nome.** O da `main` (~240 linhas)
não é o plano. O plano canônico (~982 linhas) está em
`claude/phase2a6d-mapbiomas`
(`64fd781f1551a45914a7db32960b923c05056955`). Leia com
`git show claude/phase2a6d-mapbiomas:ROADMAP.md`. Package 2B.2, o gate P2B, e
os Topics 29 e 31.

**b. O 2B.2A entregou o consumo, não a publicação.** Já existe na `main`
(via #33): o pin do contrato v3.0.0 em `docs/contracts/phase2b/`, o portão de
completude `src/publication/ledger_gate.py`, a canonicalização
`src/publication/canonical_json.py` (equivalente ao `jcs_dumps` do produtor,
provada contra a saída real dele), e o CLI
`scripts/check_processing_ledger.py`. `jsonschema>=4.23.0` está declarado.
**Consuma isso; não reimplemente.** `check_processing_ledger` devolve um
`LedgerAcceptance` com `ledger_id`, manifesto, `document_sha256`, e por data:
`expected_acquisition_ids`, `observation_ids`, `status_counts` e
`max_terminal_at` — feito para ser a entrada da promoção.

**c. As lanes verdes JÁ estão na `main`.** Isto corrige uma afirmação obsoleta
que o registro do 2B.1 carregava (e que o do 2B.2A repetiu antes de ser
corrigida): `v2_candidate_replay.yml` e `v2_promotion_lane.yml` entraram pelo
squash `8daa1812f8c2f89d6fa13be44c38283242c103bd` — "Package 2B.0: isolated
green broker and inert workflows (#10)". Verifique com
`git ls-tree --name-only origin/main -- .github/workflows/`.

**d. `v2_promotion_lane.yml` é o placeholder que o 2B.2B tem de preencher.**
Hoje: `workflow_dispatch` only, `permissions: contents: read`, grupo
`araripe-green-promotion` com `cancel-in-progress: false`, **nenhum
`environment:` e nenhum secret** — um `sleep` e sai. O próprio comentário do
arquivo diz que "the real promotion logic arrives only with the Package 2B.2
publication contract and will use a different protected identity — never the
green candidate identity and never Claude's local credential".

**e. RESTRIÇÃO DURA MEDIDA: o Environment `v2-staging` só aceita a `main`.**

    gh api repos/santibravocmcc/Araripe/environments/v2-staging
      -> 1 protection rule, type "branch_policy", reviewers []
    gh api repos/santibravocmcc/Araripe/environments/v2-staging/deployment-branch-policies
      -> exatamente uma entrada: {"name":"main","type":"branch"}

Ou seja: **sem revisor** (roda sozinho), mas **um workflow numa branch de
feature não alcança o Environment**. `v2_candidate_replay.yml` declara
`environment: v2-staging` e portanto só roda a partir da `main`. Consequência
prática para o planejamento: **toda a lógica de release/promoção tem de ser
desenvolvida e provada localmente**, com cliente S3 falso e fixtures, e a
prova em objeto real só acontece depois do merge. Alargar a branch policy é
mudança de configuração de repositório que amplia onde uma credencial vale —
**não faça; se achar que é necessário, pare e peça.**
`v2_promotion_lane.yml`, por não declarar Environment nem secret, é
despachável de qualquer ref.

**f. Nenhum workflow roda pytest.** O gate é local
(`/opt/anaconda3/envs/araripe/bin/python -m pytest -q`). Só `detect_gee.yml` e
`update_data.yml` instalam o `environment.yml`. Não invente confiança em CI
que não existe.

**g. `v2_candidate_replay.yml` já traz o padrão de guarda a imitar**: exige
`R2_STAGING_BUCKET == araripe-v2-staging`, exige o endpoint exato da conta,
e prova negação em `araripe-cogs` antes de qualquer operação. Escreva a lane
de promoção com a mesma disciplina: falhar fechado antes de tocar objeto.

**h. R2 SUPORTA escrita condicional, e o caminho no boto3 tem pegadinha.**
Verificado na documentação da Cloudflare, não da memória:

- `PutObject` aceita `If-Match` / `If-None-Match` como extensão R2 da API S3;
  precondição falha com `412 PreconditionFailed`
  (`https://developers.cloudflare.com/r2/api/s3/extensions/`).
- **O boto3 rejeita argumentos extras na validação de parâmetros**, então
  cabeçalhos por requisição exigem registrar dois handlers no event system —
  `before-parameter-build.s3.PutObject` e `before-call.s3.PutObject` — movendo
  o cabeçalho para o contexto antes da validação. Exemplo completo em
  `https://developers.cloudflare.com/r2/examples/aws/custom-header/`.
- O `aws s3 cp` da CLI **não** expõe `If-Match`. Se a promoção precisa de
  escrita condicional, ela é Python/boto3, não CLI.
- As condições de destino no `CopyObject`
  (`cf-copy-destination-if-match` e irmãs) estão **em beta** — não construa o
  núcleo da atomicidade sobre beta sem registrar a escolha.
- **ETag de multipart não é o de um `PUT` único** (é o hash dos MD5
  concatenados das partes, com `-N`). Se um objeto de release grande subir em
  multipart, o `If-Match` tem de comparar com o ETag composto, não com o
  sha256 do conteúdo. Não confunda ETag com checksum científico.

**i. O `RELEASE.json` do 2B.1 é sinal AZUL, e o 2B.2B é verde.** Ver §4.

**j. Estado de produção medido em 2026-09-07** (rodada `34137318406`):
`persistence_state.geojson` com 119.487 tracks, ~126 MB, 128 deles (0,11%) com
`first_seen > last_seen` — artefato conhecido da v1. Vive no bucket de
PRODUÇÃO `araripe-cogs`; Claude não tem e não deve receber credencial dele.

## 3. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: o 2B.2A era amplitude de leitura; o 2B.2B é **corretude de
> concorrência e irreversibilidade**. É a fatia que contém a cláusula
> "cannot expose a partial release" do gate P2B, e a primeira que projeta
> *escrita* — identidade imutável de release, promoção condicional de
> ponteiro, e a regra de manter o último release completo vivo quando uma
> rodada falha no meio. Um protocolo de promoção mal desenhado só se revela
> na corrida, e o custo de descobrir isso depois do Phase 6 é o produto
> público. Some-se que a prova em objeto real só é possível depois do merge
> (§2e), então o desenho tem de estar certo *antes* de ser executável.
>
> O executor roda sozinho dentro das fronteiras de §5 e para quando bater em
> workflow azul, credencial mais ampla, ou mudança de configuração de
> repositório.

Continue o Observatório da Chapada do Araripe com o **Package 2B.2B —
publicação atômica**, segunda fatia da Phase 2B.2.

**Orientação obrigatória antes de qualquer conclusão.** Siga a seção
"Establishing the real state" do `AGENTS.md` do workspace: `git fetch origin`,
`git status --short --branch`, `git log --oneline -5 origin/main` em cada
repositório afetado; leia documento canônico com `git show origin/main:<path>`,
não da árvore de trabalho; **nunca decida se algo foi mesclado por
ancestralidade**. Confirme o SHA de 40 caracteres da base com
`git rev-parse origin/main` e **cole-o** — o hook `commit-msg` rejeita SHA
inexistente, e ele já pegou um SHA completado a partir da forma curta nesta
mesma frente (registro em `docs/implementation/PHASE_2B2A_2026-09-07.md`).
Ative com `git config core.hooksPath .githooks`.

**Base.** Crie `claude/phase2b2b-atomic-publish` a partir de `origin/main`,
**depois** de confirmar §1.

**Leia integralmente antes de agir.** `AGENTS.md` e `CLAUDE.md` do workspace e
do backend; o roadmap completo da branch de planejamento (Package 2B.2, gate
P2B, Topics 29 e 31); `docs/contracts/phase2b/LEDGER_CONTRACT_BINDING_V1.md`
(especialmente §5, os não-requisitos, e §6, a fronteira que este pacote
herda); `docs/implementation/PHASE_2B2A_2026-09-07.md`;
`docs/implementation/PHASE_2B1_2026-09-06.md`;
`docs/operations/GREEN_CONCURRENCY_LANES.md`; os dois workflows v2; e a skill
`araripe-safe-handoff`.

### Escopo do 2B.2B

Os cinco bullets do roadmap que sobraram do Package 2B.2, na ordem em que se
sustentam:

1. **Identidade imutável de release/staging.** Todo artefato publicado sob uma
   identidade que não pode ser reescrita. Derive-a do que o ledger já sela —
   `ledger_id`, `run_manifest_id`, `document_sha256` — em vez de inventar um
   segundo eixo de identidade. Prefixo imutável por release; nada de
   sobrescrever.
2. **Validação antes da promoção do ponteiro verde:** schemas, checksums,
   datas esperadas, watermark do estado e completude do produto. O portão do
   ledger já cobre schema/checksum/completude do ledger — **componha, não
   duplique.** "Datas esperadas" e "watermark do estado" são o que falta, e
   nenhum dos dois está resolvido: decida onde a lista de datas esperadas vem
   e onde o watermark é lido, e registre a decisão.
3. **Escrita condicional** para que uma rodada antiga ou em corrida não
   substitua um release mais novo. Ver §2h para o que R2 realmente oferece e
   para as pegadinhas de boto3/ETag.
4. **Manter o último release completo vivo** quando uma rodada é parcial ou
   falha. É a cláusula do gate P2B; ela e o item 3 são o mesmo problema visto
   de dois lados.
5. **Datas de zero alerta e tombstones de objeto obsoleto, explícitos.** O
   ledger já representa `complete_zero_alerts` como estado terminal de
   primeira classe — a camada de publicação tem de preservar essa distinção,
   não colapsá-la em "sem dados".

**Fora de escopo, explicitamente:** tirar a publicação da lane de PR do git é
**2B.2C**. A separação público/privado do R2 e a rota `/data/...` são
**2B.3**. O artefato e o deploy do site são **2B.4**. Não comece nenhum, nem a
Phase 3, nem o replay 2026.

## 4. Uma decisão de escopo já tomada, com sua base

**O 2B.2B é verde e só do backend. O `data/timeseries/RELEASE.json` não é
substituído nesta fatia, e o repositório do site não é tocado.**

A base, verificada:

- Os cinco bullets restantes do Package 2B.2 falam em "**green** staging-pointer
  promotion" e em release/staging — nenhum deles pede troca do sinal azul.
- A ideia de "absorver" o `RELEASE.json` vem do docstring do
  `scripts/write_release_signal.py` ("Package 2B.2 owns the manifest, the
  ledger and atomic publication, and absorbs this file's role"), que é uma nota
  prospectiva do autor do 2B.1, **não** um bullet do roadmap.
- `site/scripts/check_backend_release.py` valida **só**
  `araripe.timeseries.release/1` e não menciona ledger, manifesto ou contrato
  (verificado por busca em 2026-09-07). Substituí-lo obriga a migrar o
  consumidor do site **na mesma mudança**, com a ordem de merge carregando
  risco — exatamente a armadilha que o 2B.1 documentou.
- O sinal azul serve a lane azul; o release verde serve a lane verde. Os dois
  se encontram no cutover do **Phase 6**, não antes.

Consequência: mantenha o `RELEASE.json` como está e construa o release verde
ao lado dele. **Se aparecer evidência de que isso está errado, pare e
pergunte** em vez de trocar por conta própria.

## 5. Fronteiras duras

- A `main` do backend é **pull-request-only**, com bypass vazio. Nunca faça
  push direto, nunca adicione ator de bypass, nunca mexa em configuração do
  repositório para contornar. Trabalhe em branch, abra PR, **não faça merge**.
- Produção segue congelada nas Fases 2B–5: nada de escrita em `araripe-cogs`,
  nada de tocar o Worker `observatorio-chapada`, o domínio final, DNS, rotas,
  ponteiros canônicos, artefatos publicados atuais, ou os workflows azuis
  (`detect_gee.yml`, `update_data.yml`, e o `update-data.yml` do site).
- **Alteração em workflow azul exige aprovação humana explícita**: prepare,
  explique o impacto, espere. O mesmo vale para qualquer mudança que altere o
  que os workflows azuis instalam (o `environment.yml` é o caso vivo, veja
  §2b) e para qualquer mudança de configuração de repositório, incluindo a
  branch policy do Environment (§2e).
- Claude não recebe credencial de control-plane da Cloudflare. O único caminho
  é uma operação já allowlistada no broker
  `.github/workflows/cloudflare_green_control.yml`; se a operação necessária
  não existir lá, **pare e faça handoff** — nunca substitua por `curl`,
  Wrangler, `gh api` ou credencial mais ampla. Não edite o broker e despache
  na mesma tarefa, e nunca aprove seu próprio Environment.
- Autonomia (política de risco do 2B.0): desenvolvimento local, branches
  locais, operações de objeto em `araripe-v2-staging`, workflows verdes
  manuais que carregam só a identidade de staging, verificações read-only,
  commits, pushes de branch e abrir PR — tudo isso segue sem aprovação
  repetida. Qualquer coisa com autoridade ou efeito em produção espera.
- Preserve `claude/phase2b0-green-isolation`, `codex/technical-review-roadmap`
  e `claude/phase2a6d-mapbiomas`.

## 6. Armadilhas já pagas — não redescubra

- **`detect_gee.yml` não é idempotente**: um re-run reprocessa a janela de 16
  dias e infla `n_sightings`. Nunca dispare só para testar; perder uma rodada
  é recuperável, inflar contador não.
- **Em runner, `ee.Initialize(project=...)` ignora
  `GOOGLE_APPLICATION_CREDENTIALS`**; use `ee_initialize()` de
  `src/acquisition/gee_download.py`.
- Existe um secret `EE_PROJECT`, mas os workflows leem `vars.EE_PROJECT` —
  namespaces diferentes; o secret é peso morto.
- **Nunca afirme invariante que o produtor não promete.** Em 2026-09-07 uma
  validação exigiu `first_seen <= last_seen`, que o `update_tracks` nunca
  garantiu, e derrubou a produção por 0,10% das linhas. O 2B.2A registrou três
  não-requisitos do ledger por esse motivo em
  `LEDGER_CONTRACT_BINDING_V1.md` §5 — em particular, **arquivo de ledger não
  é bytes canônicos**, porque o gerador de exemplos grava
  `json.dumps(indent=2)` enquanto o runtime grava canônico.
- **Não escreva ramo inalcançável.** O 2B.2A apagou checagens que duplicavam o
  schema fixado: como as duas camadas leem o mesmo arquivo, o ramo nunca
  dispararia — parece proteção e não é. Antes de acrescentar uma checagem
  fail-closed, ache o caminho por onde ela pode falhar.
- **Colete todos os achados, não pare no primeiro.** O validador do 2B.1
  morria na primeira feature ruim e o log não distinguia uma linha estranha de
  cem mil. `LedgerRejected` já segue o padrão: código estável, caminho JSON, e
  contagem na primeira linha. Imite.
- **A recontagem de persistência e o limiar `CONFIRMED_MIN = 15` já estão
  mapeados** (Topic 2, Package 2A.1 implementado, limiar é Phase 5). Não abra
  frente nova.

## 7. Ao final

Testes fail-closed e determinísticos para cada item — sem rede, sem relógio
real, sem object store: injete cliente S3 falso e relógio, como
`tests/test_r2_state.py` e `tests/test_release_signal.py` fazem. Rode
`/opt/anaconda3/envs/araripe/bin/python -m pytest -q` (base 281 na `main` com
o #33 mesclado) e reporte falhas pré-existentes em separado. Commits coerentes
com base verificada em SHA de 40 caracteres copiado da ferramenta. Crie
`docs/implementation/PHASE_2B2B_<data>.md`. Confirme árvore limpa — os
untracked `data/baselines_v2/`, `data/landcover/updated/` e `data/validation/`
são artefatos pré-existentes do 2A.6 e ficam **fora** do commit. Abra a PR
**sem mesclar**. Termine com o estado do gate P2B, dizendo explicitamente o
que ainda falta nele.

**Não inicie o 2B.2C, o 2B.3, o 2B.4, a Phase 3 nem o replay 2026.**

## 8. Estado que este package herda

- **Package 2B.2A implementado**, PR #33 aberta em 2026-09-07 com 281 passed
  (base 212). Pendência de aprovação humana: **só** o `environment.yml`
  (`jsonschema>=4.23.0`), que é o único arquivo que muda o que os workflows
  azuis instalam — medido com `conda env create --dry-run`: 282 → 286 pacotes,
  quatro adições puro-Python, **nenhuma versão de pacote existente alterada**.
- **Package 2B.1 fechado e validado em produção** (rodada `34137318406`).
- **Package 2B.0 na `main`**: broker verde isolado, lanes verdes inertes,
  Environments `v2-staging` (sem revisor, só `main`) e
  `cloudflare-green-control` (com revisor humano obrigatório).
- **Package 2A.6 fechado** em `claude/phase2a6d-mapbiomas`
  (`64fd781f1551a45914a7db32960b923c05056955`), **não mesclado** e não precisa
  ser — o contrato consumido já está fixado na `main` pelo 2B.2A.
- **Baseline `2.1.0`** existe localmente e não está publicada; colocação no R2
  é do 2B.3, ativação em runtime é dos packages de replay. `BASELINE_VERSION`
  em runtime segue `1.0.0`.
- **Prova executável das lanes do 2B.0 ainda pendente** (quatro rodadas
  concorrentes, quatro URLs registradas). Agora é despachável — as lanes estão
  na `main` (§2c) — mas é gate do 2B.0, **não** deste package.
- **Pendência viva fora deste package:** `urs.earthdata.nasa.gov` inalcançável
  dos runners desde 01/09; a chuva do site não atualiza desde o raster de
  25/08 e a rodada de sexta 11/09 fica vermelha se não voltar. Saída
  verificada: definir `EARTHDATA_TOKEN`. Decisão do dono, pendente. Não é do
  2B.2.
