# Package 2B.2A — briefing de execução

Escrito em 2026-09-07, depois de fechar o Package 2B.1 e validá-lo em produção.
Base de referência: `origin/main` em `5574b1fe353f3d88900f7ffb27c5b896b9f1c1bb`.

Este documento vive na `main` de propósito: o executor do 2B.2A trabalha a
partir da `main`, e um briefing que só existisse noutra branch repetiria
exatamente a falha de leitura entre branches que o `AGENTS.md` passou a proibir
em 2026-09-07.

---

## 1. Por que a base é a `main`, e por que 2B.2 precisa ser fatiado

Package 2B.2 é linhagem `main`, como o 2B.1. Na `main` o gate completo é
**212 passed** — não os 842 da branch científica.

O roadmap estima o 2B.2 em **50k–80k, "Very High"**, quase o dobro do 2B.1. Não
cabe numa sessão, e a cadência do projeto é de uma tarefa por sessão. **Fatie**,
como o 2A.6 foi fatiado em A/B/C/D. Divisão sugerida:

- **2B.2A — vínculo de contrato e consumo do ledger** (esta sessão): resolver a
  decisão v2/v3, fixar versão e checksum exatos do contrato, implementar a
  exigência de uma linha terminal por aquisição esperada e o resumo diário que
  reconcilia as linhas do mesmo dia. Sem tocar em publicação.
- **2B.2B — publicação atômica**: identidade imutável de release, validação
  antes da promoção do ponteiro verde, escrita condicional, manter o último
  release completo vivo em falha parcial, datas de zero alerta e tombstones.
- **2B.2C — automação sem PR**: tirar a publicação operacional da lane de PR do
  git.

As seções abaixo são o briefing do **2B.2A**.

## 2. O que já foi verificado, para o executor não refazer

Tudo abaixo foi conferido em 2026-09-07. São achados, não suposições.

**a. Existem DOIS `ROADMAP.md` com o mesmo nome.** O da `main` (~240 linhas) é
uma lista de itens não implementados e **não é o plano**. O plano canônico
(~980 linhas) está na branch de planejamento, hoje
`claude/phase2a6d-mapbiomas` (HEAD `64fd781f1551a45914a7db32960b923c05056955`).
Leia com `git show claude/phase2a6d-mapbiomas:ROADMAP.md`. Planejar contra a
cópia da `main` já duplicou trabalho uma vez.

**b. O produtor do 2A.6 existe, mas NÃO está na `main`.** Contratos, schemas e
módulos vivem só na branch científica:
`docs/contracts/phase2a/` (incluindo `schemas/processing-ledger-v2.schema.json`
e `-v3`), `src/detection/contracts_v2.py`, `contracts_v3.py`,
`persistence_v2.py`, `persistence_v3.py`. O roadmap diz que o 2B.2 **consome**
esse contrato e **não define um segundo ledger**.

**c. A família de contrato é a v3 — decisão do dono, tomada em 2026-09-07.**
O bullet do roadmap diz "the exact version and checksum of the **v2** ledger
contract/schema", mas essa redação é anterior à emenda do Sentinel-2C. **Vale a
v3.0.0.** A base da decisão, verificada:

- a v3 existe porque **20 das 70 cenas retidas do piloto da Phase 2A.4 são
  Sentinel-2C** (`GS2C_*`), dado válido da constelação que o enum `platform` da
  v2 (`S2A`/`S2B`) **não consegue representar**;
- foi autorizada pelo dono em 2026-09-01 em
  `config/phase2a_sentinel2c_contract_amendment_v3.json`, e sob a política de
  compatibilidade da Phase 1 (§9) mudança de enum é **major**, então a família
  v2 (`2.0.0`) não foi editada e **não existe relabel `S2C -> S2A` em lugar
  nenhum**;
- vincular o 2B.2 à v2 deixaria a camada de publicação estruturalmente incapaz
  de representar 20/70 das cenas do piloto, ou forçaria exatamente o relabel que
  o contrato proíbe;
- o custo de escolher v3 é zero agora: **nenhuma das duas famílias está ligada
  ao runtime** (`ledger_v2.py`/`ledger_v3.py`, `persistence_v2.py`/`_v3.py` e
  `contracts_v2.py`/`_v3.py` existem em paralelo, nenhum importado pelos
  `run_detection*.py`), e há testes de separação de major e de equivalência
  estrutural entre as duas.

O executor **não reabre esta decisão**; registra o vínculo e segue.

**d. `jsonschema` não está declarado na `main`.** O `environment.yml` da branch
científica traz `jsonschema>=4.23.0` (e `pillow`); o da `main`, não — a única
diferença entre os dois arquivos, fora o `pyyaml` que o 2B.1 declarou. Validar
contra os schemas do 2A.6 a partir da `main` exige adicioná-lo.

**e. O 2B.1 deixou um sinal de release mínimo que o 2B.2 absorve.**
`data/timeseries/RELEASE.json`, schema `araripe.timeseries.release/1`, escrito
por `scripts/write_release_signal.py` em toda rodada bem-sucedida e validado por
`site/scripts/check_backend_release.py`. Foi mantido deliberadamente mínimo para
não virar uma segunda definição de ledger. Se o 2B.2 o substituir, **o
consumidor no repositório do site tem de migrar na mesma mudança**, senão o
site quebra na rodada seguinte.

**f. A lane de publicação tem uma guarda de caminho.** O passo de publicação do
`detect_gee.yml` recusa qualquer coisa fora de `data/timeseries/` — o 2B.1 usou
isso a favor, fazendo o `RELEASE.json` viajar dentro daquele diretório e ficar
atômico com o banco de graça. Se o 2B.2 publicar manifesto ou ledger em outro
caminho do git, essa guarda muda, e ela é workflow AZUL (exige aprovação
humana). O roadmap manda "keep operational data publication automatic without
PRs or manual merges" — provavelmente a resposta é publicar no R2, não no git.

**g. A lane azul agora é serializada.** `detect_gee.yml` e `update_data.yml`
compartilham o grupo `araripe-legacy-state` com `cancel-in-progress: false`. As
lanes verdes do 2B.0 mantêm grupos próprios. Não colida com nenhuma delas;
`tests/test_workflow_lanes.py` trava a distinção.

**h. Estado de produção medido em 2026-09-07** (rodada `34137318406`): o
`persistence_state.geojson` tem 119.487 tracks e ~126 MB, e 128 deles (0,11%)
têm `first_seen > last_seen` — artefato conhecido da v1, registrado como
checagem no `ROADMAP.md` §7 da `main`. O objeto vive no bucket de PRODUÇÃO
`araripe-cogs`; Claude não tem e não deve receber credencial dele.

---

## 3. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: diferente do 2B.1, aqui o custo não é cuidado por decisão num
> arquivo pequeno, é **amplitude**. O executor precisa reconciliar duas famílias
> de contrato completas (v2 e v3, com schemas, exemplos e módulos), o produtor
> que vive noutra branch, o consumidor que vive noutro repositório, e a lane de
> publicação — sem redefinir nada do que o 2A.6 já definiu. Errar o vínculo de
> contrato contamina os packages 2B.3 e 2B.4 inteiros, e o gate P2B não fecha
> sem essa integração. É o package mais caro do roadmap (50k–80k) e o que menos
> perdoa economia de modelo.
>
> A decisão de contrato (v2 × v3) já foi tomada — v3. O executor roda sozinho e
> só interrompe se encontrar evidência contra essa escolha ou se precisar tocar
> workflow azul, que exige aprovação humana.

Continue o Observatório da Chapada do Araripe com o **Package 2B.2A — vínculo
de contrato e consumo do ledger**, primeira fatia da Phase 2B.2.

**Orientação obrigatória antes de qualquer conclusão.** O `AGENTS.md` do
workspace ganhou em 2026-09-07 uma seção "Establishing the real state" porque a
sessão anterior errou duas vezes lendo arquivo da branch errada. Siga-a:
`git fetch origin`, `git status --short --branch`, `git log --oneline -5
origin/main` em cada repositório afetado; leia documento canônico com
`git show origin/main:<path>`, não da árvore de trabalho; **nunca decida se algo
foi mesclado por ancestralidade** — os dois repositórios usam squash merge, e
`git log main..branch` mente. Confirme o SHA de 40 caracteres da base com
`git rev-parse origin/main` e cole-o; não o complete a partir da forma curta (um
hook `commit-msg` rejeita SHA inexistente; ative com
`git config core.hooksPath .githooks`).

**Base.** Crie `claude/phase2b2a-ledger-binding` a partir de `origin/main`.
Quando este prompt foi escrito a `main` estava em
`5574b1fe353f3d88900f7ffb27c5b896b9f1c1bb`, mas outras PRs podem ter entrado —
confirme o SHA atual antes de editar. Gate na `main`: 212 passed.

**Leia integralmente antes de agir.** `AGENTS.md` e `CLAUDE.md` do workspace e
dos dois repositórios; o **roadmap completo da branch de planejamento**
(`git show claude/phase2a6d-mapbiomas:ROADMAP.md`) — Package 2B.2, o gate P2B, e
a tabela de tópicos, especialmente os Topics 29 e 31; os contratos do 2A.6 em
`docs/contracts/phase2a/` daquela branch, com os schemas de ledger v2 e v3;
`docs/implementation/PHASE_2B1_2026-09-06.md`;
`docs/operations/GREEN_CONCURRENCY_LANES.md`; e a skill `araripe-safe-handoff`.

**Escopo do 2B.2A:**

1. **Vincular à família v3.0.0** (decidido; ver o achado (c) acima). Registre a
   decisão e sua base num documento de contrato sob `docs/contracts/`, não só na
   mensagem de commit, incluindo por que o bullet do roadmap diz "v2" e por que
   essa redação é anterior à emenda do Sentinel-2C de 2026-09-01. Se durante a
   execução aparecer evidência de que a v3 é a escolha errada, **pare e
   pergunte** em vez de trocar por conta própria.
2. **Fixar o vínculo exato.** Versão e checksum do contrato/schema escolhido,
   verificados e registrados de forma que uma mudança silenciosa no produtor
   falhe fechado. O 2B.2 consome o contrato do 2A.6; **não defina um segundo
   ledger**.
3. **Exigir uma linha terminal de ledger por aquisição esperada e vinculada ao
   manifesto**, mais um resumo diário derivado que reconcilie todas as linhas do
   mesmo dia. Testes determinísticos para: linha faltando, linha não terminal,
   linha duplicada, resumo que não reconcilia, e aquisição fora do manifesto.
4. **Não tocar em publicação nesta fatia.** Escrita condicional, identidade
   imutável de release, tombstones e datas de zero alerta são 2B.2B. Se o
   caminho natural levar até lá, pare e registre a fronteira.

**Fronteiras duras.** A `main` do backend é pull-request-only, com bypass vazio:
nunca faça push direto, nunca adicione ator de bypass, nunca mexa em
configuração do repositório para contornar. Trabalhe em branch, abra PR, **não
faça merge**. Produção segue congelada nas Fases 2B–5: nada de escrita no R2 de
produção, nada de dispatch de workflow, nada de tocar o broker, os GitHub
Environments, o Worker `observatorio-chapada`, o bucket `araripe-cogs`, o
domínio, DNS, rotas ou ponteiros canônicos. Alterações em workflow azul exigem
aprovação humana explícita: prepare, explique o impacto e espere. Preserve
`claude/phase2b0-green-isolation` e `codex/technical-review-roadmap`.

**Armadilhas já pagas — não redescubra.**
(a) `detect_gee.yml` não é idempotente: um re-run reprocessa a janela de 16 dias
e reconta `n_sightings`. Nunca dispare só para testar; perder uma rodada é
recuperável, inflar contador não.
(b) Em runner, `ee.Initialize(project=...)` ignora
`GOOGLE_APPLICATION_CREDENTIALS`; use `ee_initialize()` de
`src/acquisition/gee_download.py`.
(c) Existe um secret `EE_PROJECT`, mas os workflows leem `vars.EE_PROJECT` —
namespaces diferentes; o secret é peso morto.
(d) `jsonschema` não está declarado no `environment.yml` da `main`; a branch
científica o traz. Declare-o se for validar contra os schemas do 2A.6.
(e) A recontagem de persistência e o limiar `CONFIRMED_MIN = 15` **já estão
mapeados** — Topic 2 aprovado, Package 2A.1 implementado em 2026-07-28, 2A.6
testado, limiar pertence à Phase 5. Não abra frente nova; ver `ROADMAP.md` §7 na
`main`.
(f) Nunca afirme invariante que o produtor não promete. Em 2026-09-07 uma
validação exigiu `first_seen <= last_seen`, que o `update_tracks` nunca
garantiu, e derrubou a produção por 0,10% das linhas. Antes de uma checagem
falhar fechado numa propriedade, ache onde ela é garantida ou reproduza-a.

**Trabalho entre repositórios.** Valide o backend primeiro, depois o site.
Commits, validação e histórico separados por repositório; nunca inicialize Git
no diretório-pai. Reporte falhas pré-existentes em separado. Se o vínculo de
contrato afetar `site/scripts/check_backend_release.py`, a migração do
consumidor entra na mesma mudança.

**Ao final:** testes fail-closed e determinísticos para cada item, rode
`/opt/anaconda3/envs/araripe/bin/python -m pytest -q` (base 212 na `main`),
commits coerentes por repositório com base verificada em SHA de 40 caracteres,
crie `docs/implementation/PHASE_2B2A_<data>.md`, confirme árvore limpa, abra
o(s) PR(s) **sem mesclar**, e termine com o estado do gate P2B — dizendo
explicitamente o que ainda falta nele.

**Não inicie o 2B.2B, o 2B.2C, a Phase 3 nem o replay 2026.**

---

## 4. Estado que este package herda

- **Package 2B.1 fechado e validado em produção** (2026-09-07, rodada
  `34137318406` verde). Fail-closed no estado do R2, lane azul serializada,
  sinal de release, alertas e chuva independentes com estado de frescor.
- **PRs mescladas hoje:** Araripe #28, #29, #30; site #15, #16. Pendentes de
  revisão quando este prompt foi escrito: Araripe #31 e site #17 (regras de
  orientação e o hook `commit-msg`).
- **Package 2A.6 fechado** em `claude/phase2a6d-mapbiomas`
  (`64fd781f1551a45914a7db32960b923c05056955`), **não mesclado na `main`** e
  não precisa ser para o 2B.2A — mas é de lá que vêm os contratos.
- **Baseline `2.1.0`** existe localmente e não está publicada; a colocação no R2
  é do Package 2B.3 e a ativação em runtime é dos packages de replay.
  `BASELINE_VERSION` em runtime segue `1.0.0`.
- **Pendência viva fora deste package:** `urs.earthdata.nasa.gov` está
  inalcançável dos runners desde 01/09; a chuva do site não atualiza desde o
  raster de 25/08 e a rodada de sexta 11/09 fica vermelha se não voltar. A saída
  verificada é definir `EARTHDATA_TOKEN` (o earthaccess então não faz chamada de
  rede no login). Decisão do dono, pendente. Não é do 2B.2.
