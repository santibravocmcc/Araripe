# Package 2B.3 — briefing de execução

Escrito em 2026-09-07, depois de fechar a implementação do Package 2B.2C.
**Atualizado no mesmo dia**, depois de o 2B.2C ser mesclado e de a publicação
ser provada de ponta a ponta contra o R2 real — ver §2k e §8, e
[`GREEN_PROOFS_2026-09-07.md`](GREEN_PROOFS_2026-09-07.md).

Segue o método em [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md)
versão 2: o corpo é para o agente executor, e a **seção final é para o dono**.

---

## 1. Dependência que precede tudo — já satisfeita, mas confirme

O 2B.3 separa o que é privado do que é público **no armazenamento que o 2B.2C
passou a escrever**. Sem ele não existe `runs/<run-id>/`, não existe a lane
operacional, e a fronteira que o 2B.3 tem de traçar não tem os dois lados.

**O 2B.2C foi mesclado em 2026-09-07** pelo squash
`19cdb04121885c7a8ccd71510bc49fea538afb69` ("Package 2B.2C — automatic
operational publication (backend) (#39)"). Também entraram no mesmo dia: #38 e
#40 (o probe de identidade e o piso de botocore), #41 (o registro das provas) e
#42 (o modo `rollback`). Confirme por conteúdo de qualquer forma — a `main` pode
ter andado desde que isto foi escrito.

Confirme **por conteúdo, nunca por ancestralidade** (os dois repositórios fazem
squash merge):

    git show origin/main:src/publication/run_inputs.py | head -5
    git show origin/main:scripts/stage_green_run.py | head -5
    git show origin/main:.github/workflows/v2_operational_publish.yml | head -5
    git show origin/main:docs/contracts/phase2b/schemas/green-run-v1.schema.json | head -3

Cuidado com o `--grep`: ele busca a **mensagem inteira**, não o assunto, então
um commit que apenas *cita* a PR também casa. Filtre por `%s`:

    git log origin/main --format='%H %s' | grep '(#<número>)'

Gate medido na `main` em 2026-09-07, com tudo acima mesclado: **530 passed**
(era 445 antes do 2B.2C). **Meça antes de editar** — este número é um fato
datado, não uma promessa:

    /opt/anaconda3/envs/araripe/bin/python -m pytest -q

Se algum dos artefatos acima não estiver na `main`: **pare e pergunte.**

## 2. O que já foi verificado, para o executor não refazer

Tudo abaixo foi conferido em 2026-09-07 com a ferramenta que produz o valor.

**a. O caminho de publicação operacional existe, ponta a ponta.**
`runs/<run-id>/run.json` + `ledger.json` + corpos → `stage` (identidade de
candidato, só leitura) → `promote` (identidade de promoção) → `releases/<id>/`
e um compare-and-swap em `pointers/green/current.json`. Documento:
`docs/implementation/PHASE_2B2C_2026-09-07.md`. **Consuma isso; não
reimplemente.**

**b. A identidade de promoção EXISTE, está ligada e está PROVADA — na segunda
tentativa.** O dono criou o Environment `v2-promotion` em 2026-09-07. Lido de
volta antes de ligar:
`rules ["branch_policy"]` sem revisor, política `["branch: main"]`, os secrets
`R2_PROMOTION_ACCESS_KEY_ID` / `R2_PROMOTION_SECRET_ACCESS_KEY` e os três
variables. Confirme você mesmo, sem pedir valor nenhum:

    gh api repos/santibravocmcc/Araripe/environments --jq '[.environments[].name]'
    gh api repos/santibravocmcc/Araripe/environments/v2-promotion/variables \
      --jq '[.variables[] | "\(.name)=\(.value)"]'

**E aqui está a lição que custou uma rodada:** a PRIMEIRA chave criada tinha
escopo amplo demais — **lia o bucket de produção**. A configuração do
Environment estava perfeita nas duas vezes; o que diferia era o escopo do token
no Cloudflare, **invisível do lado do GitHub**. Ler a API prova só a *forma*:
nomes de secret, política de branch, variables.

> **Escopo de credencial só se prova com uma chamada real que precisa ser
> recusada.**

É por isso que `v2_promotion_identity_probe.yml` testa a recusa em
`araripe-cogs` como uma checagem **invertida**, e por isso a polaridade dela é
afirmada nas duas direções em `tests/test_promotion_identity_probe.py`
(`test_a_readable_production_bucket_is_a_failure`). Se o 2B.3 criar qualquer
credencial nova — e ele vai, "least-privilege credentials" é bullet dele —
**prove o escopo do mesmo jeito, com uma recusa observada, não com a
configuração lida.**

**c. NUNCA nomeie um Environment que não existe.** O GitHub não falha — ele
**cria** um, "with no protection rules or secrets configured"
(<https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments>).
Um erro de digitação fabrica um Environment sem política de branch nenhuma, o
que é mudança de configuração de repositório e é justamente a errada.

**d. MEDIDO: o pin de dependências azul não expressa o compare-and-swap.**
`environment.yml` fixa `botocore>=1.35.0,<1.36.0`. Desempacotando os wheels e
lendo `PutObjectRequest` no service model do S3:

| botocore | `IfNoneMatch` | `IfMatch` |
| --- | --- | --- |
| 1.35.0 | ausente | ausente |
| 1.35.16 | **presente** | ausente |
| 1.35.36 | **presente** | ausente |
| 1.36.0 | presente | presente |

Ou seja, a faixa azul cai numa janela onde a escrita imutável funciona e o
ponteiro **não pode** ser movido — a pior forma possível.
`require_conditional_write_support` checa os **dois** parâmetros antes de tocar
em objeto, então falha fechado. As lanes verdes instalam por `pip` com piso
`botocore>=1.36.0`, **medido** e não mínimo (1.35.37–1.35.99 não foram
testadas). Não troque por `environment.yml`.

**e. A unidade de uma lane agora é (workflow, job), não o arquivo.**
`v2_operational_publish.yml` tem `concurrency` por job e nenhum no nível do
arquivo. `tests/test_workflow_lanes.py` lê só o nível do arquivo, então a
varredura de distinção foi refeita sobre os dois níveis em
`tests/test_operational_publish_lane.py`. Se acrescentar workflow ou job com
grupo, é lá que a propriedade é mantida.

**f. Um grupo PODE ter mais de um membro.** `v2_promotion_lane.yml` e o job
`promote` compartilham `araripe-green-promotion` de propósito: os dois movem o
mesmo ponteiro, e sem compartilhar não haveria serialização entre eles — o
mesmo argumento que põe os dois escritores azuis em `araripe-legacy-state`. O
que nunca pode acontecer é um grupo aparecer em duas **lanes**.

**g. Nada em runtime emite ledger v3.** `src/detection/ledger_v3.py` vive só em
`claude/phase2a6d-mapbiomas` e nenhum `run_detection*.py` importa ledger, em
nenhuma das duas refs. Por isso o 2B.2C **aceita** uma rodada em vez de emitir
uma. Não invente um segundo produtor de ledger.

**h. `data/timeseries/RELEASE.json` é sinal AZUL e permanece.** O consumidor
`site/scripts/check_backend_release.py` valida só
`araripe.timeseries.release/1`. Os dois se encontram no cutover do Phase 6.

**i. Nenhum workflow roda pytest.** O gate é local.

**j. Nada foi deletado, em lugar nenhum.** `ConditionalStore` não tem operação
de delete nem escrita incondicional. Lápides são registradas no ponteiro. A
política de retenção e exclusão é **deste** package.

**k. A publicação foi provada de ponta a ponta contra o R2 real**, e o bucket
não está mais vazio. Cinco dispatches em 2026-09-07, detalhados em
`GREEN_PROOFS_2026-09-07.md` §6 e §7:

- o R2 aplica `If-None-Match` **e** `If-Match` — era só documentação até então;
- publicar → verificar → mover o ponteiro funciona (`sequence 1`);
- republicar a mesma rodada é no-op e **não** avança a sequência;
- cobertura mais antiga é **recusada** (`coverage_regression`), e os objetos
  dela ficam publicados no prefixo imutável dela **enquanto o ponteiro não se
  move**;
- supersede com tombstone real, e **reversão** com `sequence` subindo para 3
  enquanto a cobertura volta de 04-13 para 04-10.

**Consequência direta para o seu escopo:** `araripe-v2-staging` contém agora 3
releases imutáveis, 3 prefixos de rodada, e objetos de dois probes — inventário
em `GREEN_PROOFS_2026-09-07.md` §8. **Eles são o primeiro caso de teste da sua
política de retenção**, e não são todos iguais: um release **que já esteve
live** e foi revertido (`rel-g1-5ffad23a…`) não é o mesmo caso que um release
**que nunca foi promovido** (`rel-g1-9f1ed344…`, o da cobertura recusada). Uma
política que apague "releases não referenciados pelo ponteiro" apagaria os dois
— e o primeiro é exatamente o alvo de uma reversão futura.

## 3. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: o 2B.3 é o primeiro package que desenha uma **fronteira de
> exposição pública** e a primeira política de **exclusão** do projeto. Errar
> para o lado permissivo publica dado que não devia sair; errar para o lado
> restritivo quebra o site. E exclusão é a única coisa no desenho que não tem
> volta — todo o resto até aqui foi aditivo e imutável por construção.
>
> O executor roda sozinho dentro das fronteiras de §5 e para quando bater em
> workflow azul, credencial mais ampla, mudança de configuração de
> repositório, ou qualquer operação de exclusão em objeto real.

Continue o Observatório da Chapada do Araripe com o **Package 2B.3 — separação
do R2 e entrega em estágio**.

**Orientação obrigatória antes de qualquer conclusão.** Siga a seção
"Establishing the real state" do `AGENTS.md` do workspace em cada repositório
afetado; leia documento canônico com `git show origin/main:<path>`, não da
árvore de trabalho; **nunca decida se algo foi mesclado por ancestralidade**.
Confirme o SHA de 40 caracteres da base com `git rev-parse origin/main` e
**cole-o** — o hook `commit-msg` rejeita SHA inexistente. Ative com
`git config core.hooksPath .githooks`.

**Base.** Crie `claude/phase2b3-r2-separation` a partir de `origin/main`,
**depois** de confirmar §1.

**Leia integralmente antes de agir.** `AGENTS.md` e `CLAUDE.md` do workspace e
do backend; o roadmap completo da branch de planejamento (Package 2B.3,
Package 2B.4, gate P2B); `GREEN_RELEASE_CONTRACT_V1.md`;
`docs/implementation/PHASE_2B2C_2026-09-07.md`;
`docs/operations/GREEN_CONCURRENCY_LANES.md`; e a skill
`araripe-safe-handoff`.

### Escopo do 2B.3

Os bullets do roadmap, na ordem em que se sustentam:

1. **Fronteira privada de processamento e fronteira pública só de release.**
   Hoje `runs/<run-id>/` (insumo de processamento) e `releases/<id>/` (produto)
   vivem no mesmo bucket com a mesma exposição. Decida e registre o que é
   público, e prove a partir do código que o privado não pode virar público
   por acidente.
2. **Credenciais de menor privilégio e exposição de secret por passo.** Hoje
   `v2-staging` e `v2-promotion` são ambos Object Read & Write no bucket
   inteiro — o limite real é o código, não o token
   (`PROMOTION_IDENTITY_SETUP.md`). Diga o que dá para estreitar de verdade e o
   que não dá, com o que o R2 realmente oferece, medido.
3. **Copiar e verificar antes de trocar consumidor; manter o caminho antigo
   para rollback; não apagar na migração inicial.**
4. **Preparar e validar a rota `/data/...` de mesma origem contra o Worker de
   staging isolado.** **Não** encoste a rota do domínio final antes do Phase 6.
5. **Validar CORS, content types, cache, checksums, downloads e o modo de
   alerta completo no navegador.**
6. **Retenção e exclusão conservadoras, em dry-run revisado primeiro.** Esta é
   a parte irreversível: nada de exclusão real em objeto sem aprovação humana
   explícita e nomeada.
7. **Preparar e ensaiar** o desligamento do caminho público do bucket interno
   azul — **sem executar** antes do cutover do Phase 6.

**Fora de escopo, explicitamente:** o artefato do site, o deploy verde e "sem
bot pushes" no lado do site são **2B.4**. O cutover, o desligamento do bot azul
e qualquer coisa no domínio final são **Phase 6**. A prova em objeto real da
publicação e o replay 2026 não são deste package. Não comece nenhum, nem a
Phase 3.

## 4. Decisões de escopo já tomadas, com sua base

- **O release verde vai para o R2, não para o git**, e o `RELEASE.json` azul
  não é substituído. Herdado do 2B.2B/2B.2C e reconfirmado: nenhum consumidor
  do site menciona ledger, manifesto ou contrato.
- **Nada é apagado enquanto a migração não estiver provada.** O contrato já diz
  "nothing is deleted" e a classe de armazenamento não tem delete. Introduzir
  exclusão é acrescentar uma capacidade que hoje não existe — trate como tal.
- **Lanes verdes não carregam cron antes do Phase 6.** O que o 2B.2C tirou do
  caminho de dados foi a PR e o merge, não a decisão do operador de rodar.

Se aparecer evidência contra qualquer uma, **pare e pergunte** em vez de trocar
por conta própria.

## 5. Fronteiras duras

- A `main` do backend é **pull-request-only**, com bypass vazio. Nunca faça
  push direto, nunca adicione ator de bypass, nunca mexa em configuração do
  repositório para contornar. Trabalhe em branch, abra PR, **não faça merge**.
- Produção segue congelada nas Fases 2B–5: nada de escrita em `araripe-cogs`,
  nada de tocar o Worker `observatorio-chapada`, o domínio final, DNS, rotas,
  ponteiros canônicos, artefatos publicados atuais, ou os workflows azuis.
- **Exclusão de objeto real exige aprovação humana explícita**, mesmo em
  staging. Dry-run revisado primeiro, sempre.
- Claude não recebe credencial de control-plane da Cloudflare. O único caminho
  é uma operação já allowlistada no broker
  `.github/workflows/cloudflare_green_control.yml`; se ela não existir lá,
  **pare e faça handoff**. Não edite o broker e despache na mesma tarefa, e
  nunca aprove seu próprio Environment.
- **Não alargue a política de branch de nenhum Environment.** As duas admitem
  só `main`, de propósito: uma branch de feature não deve alcançar credencial.
- Autonomia: desenvolvimento e branches locais, objetos em
  `araripe-v2-staging`, workflows verdes manuais com identidade de staging,
  verificações read-only, commits, pushes de branch e abrir PR seguem sem
  aprovação repetida. Qualquer coisa com autoridade ou efeito em produção
  espera.
- Preserve `claude/phase2b0-green-isolation`, `codex/technical-review-roadmap`,
  `claude/phase2a6d-mapbiomas` e `ci/promotion-identity-probe`.

## 6. Armadilhas já pagas — não redescobrir

- **Outra sessão pode estar no mesmo clone.** Em 2026-09-07 duas frentes
  editaram esta árvore ao mesmo tempo e a branch mudou no meio da sessão.
  **Nunca use `git stash` numa árvore com trabalho alheio** — confira
  `git status` e `git rev-parse --abbrev-ref HEAD` antes de commitar, e
  adicione arquivos por nome, nunca `git add -A`.
- **`detect_gee.yml` não é idempotente**: um re-run reprocessa a janela de 16
  dias e infla `n_sightings`. Nunca dispare só para testar.
- **As duas armadilhas de shell do passo de publicação azul**: `shell: bash`
  sobrepõe o default `bash -l {0}` e o corpo nunca chama `exit 0`, porque o
  `setup-miniconda` deixa `set -eo pipefail` no `~/.profile` e o
  `~/.bash_logout` do runner falha sem TTY. Não desfaça.
- **ETag não é checksum.** Multipart é MD5 dos MD5s com sufixo `-N`. É token
  opaco de compare-and-swap; integridade é o `sha256` do manifesto.
- **Nunca afirme invariante que o produtor não promete.** `first_seen <=
  last_seen` derrubou a produção em 2026-09-07; `max(last_seen)` **não** é
  watermark.
- **Não escreva ramo inalcançável.** Antes de acrescentar checagem
  fail-closed, ache o caminho por onde ela falha.
- **Não adivinhe intenção por checksum.** Intenção se declara. E recuse a
  declaração que os bytes contradizem — foi assim que o 2B.2C pegou o
  artefato selado declarado como produto de data.
- **Ao testar workflow, leia o que o shell executa, não o que ele imprime.** O
  helper `executed()` em `tests/test_promotion_lane.py` já resolve isso.
- **Colete todos os achados, não pare no primeiro** — `findings.py` dá o
  padrão.
- **Prove por mutação.** O 2B.2C desligou cada checagem nova, uma a uma, e
  confirmou que só o teste correspondente cai. Um teste que passa pelo motivo
  errado vale tão pouco quanto um que falha pelo motivo errado.

## 7. Ao final

Testes fail-closed e determinísticos para cada item — sem rede, sem relógio
real, sem object store: injete cliente S3 falso e relógio, como
`tests/fake_object_store.py` faz. Reuse `tests/green_release_fixtures.py`.
Rode `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` e reporte falhas
pré-existentes em separado. Commits coerentes com base verificada em SHA de 40
caracteres copiado da ferramenta. Crie
`docs/implementation/PHASE_2B3_<data>.md`. Confirme árvore limpa — os
untracked `data/baselines_v2/`, `data/landcover/updated/` e `data/validation/`
são artefatos pré-existentes do 2A.6 e ficam **fora** do commit. Abra a PR
**sem mesclar**. Termine com o estado do gate P2B, dizendo explicitamente o que
ainda falta nele, e com a seção final obrigatória do método de handoff.

**Não inicie o 2B.4, a Phase 3 nem o replay 2026.**

## 8. Estado que este package herda

- **Package 2B.2C MESCLADO** em 2026-09-07 (`19cdb04`, #39). Gate na `main`
  depois de tudo o que entrou no dia: **530 passed** (base 445).
- **Packages 2B.2A e 2B.2B na `main`** (#33, #35).
- **A Phase 2B.2 está inteira na `main`**: A, B e C. O que falta da fase são
  provas e os packages 2B.3/2B.4, não implementação do 2B.2.
- **Package 2B.1 fechado e validado em produção.**
- **Package 2B.0 na `main`**: broker verde isolado, lanes verdes, Environments
  `v2-staging` e `cloudflare-green-control` (este com revisor obrigatório).
- **Environment `v2-promotion` existe** desde 2026-09-07, sem revisor, política
  `main`, com os dois secrets e os três variables — e a chave dentro dele é a
  **segunda**, restrita ao bucket. A primeira lia produção; ver §2b, porque a
  lição vale para as credenciais que este package vai criar.
- **Package 2A.6 fechado** em `claude/phase2a6d-mapbiomas`
  (`64fd781f1551a45914a7db32960b923c05056955`), **não mesclado** e não precisa
  ser.
- **Baseline `2.1.0`** existe localmente e não está publicada; colocação no R2
  é deste package. `BASELINE_VERSION` em runtime segue `1.0.0`.
- **`v2_promotion_identity_probe.yml` está na `main`** (#38, com o piso de
  botocore em #40) e reporta **9 de 9**. Usa o grupo próprio
  `araripe-green-promotion-probe`, porque nunca toca o ponteiro real.
- **`v2_promotion_lane.yml` ganhou `rollback` e `status`** (#42), num job
  separado que é o único do arquivo a declarar `environment: v2-promotion`.
  `promote` continua recusado **ali** de propósito: a promoção operacional é do
  `v2_operational_publish.yml`, que valida com a identidade de candidato
  primeiro. Dois workflows capazes de promover seriam dois caminhos para um
  mesmo objeto mutável.
- **Nenhum produtor deposita `runs/<run-id>/` ainda.** A lane consome; o
  produtor 2A.6 não está na `main`. Nas provas de 2026-09-07 a rodada foi
  **montada à mão** e enviada com a identidade local de staging, por um script
  de andaime que ficou **fora** do repositório, no scratchpad da sessão.
  `stage_green_run.py` só valida. Automatizar a montagem **não é deste
  package** — o roadmap não pede, e o produtor de ledger é outra frente.
- **A prova das lanes do 2B.0 está FEITA** (2026-09-07), com três execuções e
  não quatro. A quarta pedia disparar `update_data.yml`, que lê e escreve no R2
  de **produção** — o procedimento tinha sido escrito antes do congelamento e
  envelheceu. Corrigido em `GREEN_CONCURRENCY_LANES.md`; a metade azul da
  propriedade é estrutural e não precisa de execução. Não redescubra isto.
- **A chuva do site está RESOLVIDA e verificada** em 2026-09-07, e isto
  substitui a pendência que este briefing carregava. O diagnóstico estava certo
  e incompleto: o passo `chuva` entregava só `EARTHDATA_USERNAME` e
  `EARTHDATA_PASSWORD`, enquanto `fetch_gpm.py:98` e `earthdata_login.py:178`
  leem `EARTHDATA_TOKEN` — nome que nunca chegava ao script. A PR
  `observatorio-site#18` foi mesclada, o dono criou o secret, e o dispatch
  `34165003418` gravou `gpm_7day_rainfall_2026_09_04.tif` com
  `chuva.json: **updated**` (não `skipped` — é essa a distinção que separa
  "atualizei" de "pulei"). O buraco desde 25/08 está fechado.
  **Medido no `earthaccess` 0.16.0**, não recordado: `_get_credentials()` testa
  `if user_token is not None` PRIMEIRO e esse ramo não faz chamada de rede,
  então as três variáveis convivem. **Pendência com data: o token expira em
  2026-11-06**, e como o ramo do token não o valida no login, a expiração
  aparece no download — run vermelho, não congelamento silencioso.
- **Mesmo padrão suspeito no fallback do backend**, sem prazo: o passo "Run
  detection pipeline" do `update_data.yml` passa só usuário e senha. Não
  verifiquei se `run_detection.py` chega a fazer login no Earthdata — pode ser
  que a correção certa seja **remover** as duas linhas. Não é deste package.

## 9. Para o dono — em linguagem simples

Esta seção foi reescrita em 2026-09-07, depois de o 2B.2C ser mesclado e de as
provas rodarem. A versão anterior descrevia um estado que já não existe.

### O que ficou pendente da tarefa atual

**Nada.** A etapa 2B.2 está inteira no ramo principal, e tudo o que faltava
provar foi provado contra o armazenamento de verdade — não mais com um
armazenamento de mentira dentro da máquina.

O sistema publicou uma rodada, republicou a mesma sem duplicar nada, **recusou**
uma rodada mais antiga que tentaria substituir uma mais nova, publicou uma mais
nova registrando o que ficou obsoleto, e **voltou atrás** por comando. Nenhum
pull request participou de nenhum desses cinco movimentos — que era exatamente
o objetivo da etapa.

Duas coisas continuam faltando para fechar a fase inteira, e nenhuma é trabalho
de programação parado: **rodar uma vez com dados de uma execução real** (hoje
nada em produção produz esse formato ainda) e **preparar a rodada
automaticamente** (hoje é uma pessoa que monta os arquivos; nas provas fui eu).

### O que você precisa fazer

1. **Juntar a PR de documentação** que registra a reversão e atualiza este
   briefing. Não tem código, não tem nada para aprovar.
2. **Nada urgente além disso.** Não há aprovação de produção esperando, nem
   credencial para criar, nem prazo correndo.
3. **Começar o 2B.3 quando quiser**, com o prompt no fim desta resposta. Ele é a
   etapa que mais pede cuidado, pela razão da próxima seção.
4. **Anotar 6 de novembro:** a chave da NASA expira e a chuva para de novo.
   Dessa vez com aviso vermelho, não em silêncio — isso foi medido.

### Tem algo preocupante?

**Não.** Pela primeira vez em vários dias, nada nesta lista é preocupante: a
chuva voltou e está verificada, a chave de promoção foi refeita e está provada
como restrita à caixa de testes, e nada tocou produção.

Vale um aviso sobre o que vem, que é diferente de uma preocupação: **o 2B.3 é a
primeira etapa em que este projeto poderá apagar coisas.** Até agora nada nunca
foi apagado, por construção — não existe nem o comando. Isso deixa de ser
verdade quando a política de retenção existir, e é por isso que essa etapa pede
mais cuidado que as anteriores, não porque haja algo errado hoje.

Uma lição do dia que vale guardar, porque vai reaparecer: **ler a configuração
no GitHub prova só a forma da coisa.** A primeira chave de promoção tinha a
configuração perfeita e o escopo errado, e isso só apareceu numa chamada real
que precisava ser recusada. O 2B.3 vai criar credenciais mais restritas — cada
uma delas precisa da mesma prova.

### O que ainda falta no caminho

- **2B.3 — separar o público do privado:** decidir o que fica visível para quem,
  apertar as chaves, criar o endereço `/data/...` num ambiente de teste, e
  definir por quanto tempo cada arquivo fica guardado. É a próxima etapa.
- **2B.4 — o site novo:** parar de guardar arquivos grandes de alerta dentro do
  repositório e preparar a publicação do site.
- **Phase 3 — congelar e ensaiar** o reprocessamento de 2026: escolher a data de
  corte e fotografar tudo antes de começar.
- **Phase 6 — a troca final:** o sistema novo substitui o antigo, o site aponta
  para ele, o robô antigo é desligado, e a publicação passa a acontecer sozinha
  num horário. É também quando a decisão de "sem revisor" na chave de promoção
  deve ser reconsiderada, porque aí o ponteiro deixa de ser um ambiente de
  teste.

Além das etapas, as duas provas citadas acima: rodar com dados de uma execução
real, e automatizar a montagem da rodada.
