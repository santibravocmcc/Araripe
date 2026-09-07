# Package 2B.2C — briefing de execução

Escrito em 2026-09-07, depois de fechar a implementação do Package 2B.2B.
Base de referência do 2B.2B: `origin/main` em
`b0b8518f01b669ca437fcca8397aaa230a6da1f2`.

Segue o método em [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md)
versão 2: o corpo é para o agente executor, e a **seção final é para o dono**.

---

## 1. Dependência que precede tudo: a PR #35

**O 2B.2C automatiza o caminho de publicação que o 2B.2A e o 2B.2B
construíram.** Sem a #35 mesclada não existe `publish_release`,
`verify_release`, `promote` nem `rollback` na `main`, e não há o que automatizar.

Confirme **por conteúdo, nunca por ancestralidade** (os dois repositórios fazem
squash merge):

    git show origin/main:src/publication/atomic_publish.py | head -5
    git show origin/main:src/publication/conditional_store.py | head -5
    git show origin/main:docs/contracts/phase2b/GREEN_RELEASE_CONTRACT_V1.md | head -5
    git log origin/main --format='%H %s' | grep '(#35)'

Cuidado com o `--grep`: ele busca a **mensagem inteira**, não o assunto, então
`git log --grep '(#35)'` também casa commits que apenas *citam* a PR no corpo.
Filtre por `%s` como acima, ou decida por conteúdo.

Se a #35 não estiver na `main`: **pare e pergunte.** Não ramifique de
`claude/phase2b2b-atomic-publish` para adiantar.

Gate esperado na `main` depois da #35: **439 passed** (era 281). Se a PR do
método de handoff também estiver mesclada, são **445**. Meça antes de editar:

    /opt/anaconda3/envs/araripe/bin/python -m pytest -q

## 2. O que já foi verificado, para o executor não refazer

Tudo abaixo foi conferido em 2026-09-07 com a ferramenta que produz o valor.

**a. O caminho de publicação verde existe e está provado localmente.**
`src/publication/`: `green_release.py` (identidade imutável derivada do ledger,
manifesto, portão), `conditional_store.py` (escrita condicional, guarda de
bucket), `atomic_publish.py` (publicar → verificar → promover/reverter),
`findings.py`. Operador: `scripts/publish_green_release.py`
(`plan|apply|rollback|status`). Contrato:
`docs/contracts/phase2b/GREEN_RELEASE_CONTRACT_V1.md`. **Consuma isso; não
reimplemente.**

**b. A automação AZUL de hoje, medida linha por linha.** O passo *"Publish
time-series DB through a pull request"* do `detect_gee.yml`:
`git add data/timeseries/`; recusa qualquer caminho *staged* fora de
`data/timeseries/`; commita; `git fetch origin main` + `git rebase origin/main`
(aborta e falha se der conflito); `git push origin HEAD:refs/heads/auto/timeseries-<run_id>`;
`gh pr create`; e então `gh pr merge --squash --delete-branch` com **até 5
tentativas e 15 s de espera** entre elas, falhando se não mesclar. O job declara
`permissions: pull-requests: write`. Existe por um motivo: a ruleset da `main`
tem bypass vazio, então nem o `github-actions[bot]` empurra direto.
**Os alertas já não passam pelo git — vivem no R2.** Só o banco da série
temporal usa essa lane.

**c. Esse passo carrega duas armadilhas de shell já pagas, documentadas no
próprio arquivo.** `shell: bash` sobrepõe o default `bash -l {0}` do job e o
corpo nunca chama `exit 0`, porque o `setup-miniconda` reescreve o `~/.profile`
terminando em `set -eo pipefail` e o `~/.bash_logout` do runner roda
`clear_console`, que falha sem TTY — o que fez as rodadas de 20/08 e 24/08
reportarem falha **depois** de publicar com sucesso. Se você tocar nesse passo,
não desfaça isso.

**d. Falta a identidade protegida de promoção, e isso condiciona o package.**
Mover o ponteiro verde escreve em `pointers/green/current.json` no
`araripe-v2-staging`. A lane 3 **não pode** usar a identidade do *candidate*
(`docs/operations/GREEN_CONCURRENCY_LANES.md`), e criar um GitHub Environment é
mudança de configuração de repositório — trabalho do dono, não do agente. O
`v2_promotion_lane.yml` já para e nomeia exatamente o que falta.

**e. RESTRIÇÃO DURA MEDIDA: o Environment `v2-staging` só aceita a `main`.**
Uma protection rule do tipo `branch_policy`, **sem revisor**, e exatamente uma
entrada em `deployment-branch-policies`: `main`. Consequência para o
planejamento: **toda a lógica tem de ser desenvolvida e provada localmente**,
com cliente S3 falso e relógio injetado, e a prova em objeto real só acontece
depois do merge. **Não alargue a branch policy** — é mudança de configuração
que amplia onde uma credencial vale. Se achar necessário, pare e peça.

**f. Nenhum workflow roda pytest.** O gate é local. Só `detect_gee.yml` e
`update_data.yml` instalam o `environment.yml`. O `v2_promotion_lane.yml` usa o
Python do runner e um `pip install jsonschema`, de propósito, para não acoplar
uma lane verde ao arquivo que os workflows azuis resolvem. Não invente confiança
em CI que não existe.

**g. `jsonschema>=4.23.0` já está na `main`** (`environment.yml`, mesclado com a
#33). Não há aprovação pendente de dependência.

**h. Escrita condicional no boto3: use os parâmetros nativos.** Medido: no
botocore 1.42.42, `IfMatch` e `IfNoneMatch` são **membros nativos** do input
shape do `PutObject`. A receita de dois handlers da documentação da Cloudflare
existe para cabeçalhos *arbitrários* — e para esses a validação do boto3 mesmo
rejeita, o que está fixado como resultado negativo em
`tests/test_conditional_store.py`. Não reintroduza a receita sem re-medir.

**i. ETag não é checksum.** Multipart é o MD5 dos MD5s com sufixo `-N`. Trate
como token opaco de compare-and-swap; integridade de conteúdo é o `sha256` que
o manifesto declara.

**j. `data/timeseries/RELEASE.json` é sinal AZUL e permanece.** O consumidor do
site (`site/scripts/check_backend_release.py`) valida só
`araripe.timeseries.release/1` e não menciona ledger, manifesto ou contrato. O
release verde foi construído **ao lado** dele. Os dois se encontram no cutover
do Phase 6.

## 3. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: o 2B.2B era corretude de concorrência num módulo isolado e
> testável. O 2B.2C é **integração com automação viva**: precisa produzir a
> entrada que o caminho de publicação consome, dentro de um agendamento, sem
> tocar a lane azul que sustenta a produção hoje — e a lane azul carrega duas
> armadilhas de shell que já fizeram rodadas mentirem sobre o próprio
> resultado (§2c). Errar aqui não quebra um teste; quebra a publicação
> operacional.
>
> O executor roda sozinho dentro das fronteiras de §5 e para quando bater em
> workflow azul, credencial mais ampla, ou mudança de configuração de
> repositório.

Continue o Observatório da Chapada do Araripe com o **Package 2B.2C —
publicação operacional automática**, terceira e última fatia da Phase 2B.2.

**Orientação obrigatória antes de qualquer conclusão.** Siga a seção
"Establishing the real state" do `AGENTS.md` do workspace em cada repositório
afetado; leia documento canônico com `git show origin/main:<path>`, não da
árvore de trabalho; **nunca decida se algo foi mesclado por ancestralidade**.
Confirme o SHA de 40 caracteres da base com `git rev-parse origin/main` e
**cole-o** — o hook `commit-msg` rejeita SHA inexistente. Ative com
`git config core.hooksPath .githooks`.

**Base.** Crie `claude/phase2b2c-auto-publish` a partir de `origin/main`,
**depois** de confirmar §1.

**Leia integralmente antes de agir.** `AGENTS.md` e `CLAUDE.md` do workspace e
do backend; o roadmap completo da branch de planejamento (Package 2B.2 último
bullet, Package 2B.4, gate P2B); `GREEN_RELEASE_CONTRACT_V1.md`;
`LEDGER_CONTRACT_BINDING_V1.md`; `docs/implementation/PHASE_2B2B_2026-09-07.md`;
`docs/operations/GREEN_CONCURRENCY_LANES.md`; os dois workflows v2; o passo de
publicação do `detect_gee.yml`; e a skill `araripe-safe-handoff`.

### Escopo do 2B.2C

O bullet que sobrou do Package 2B.2: *"keep operational data publication
automatic without PRs or manual merges."*

1. **Uma lane verde que publica sozinha.** Um workflow verde que produz o
   ledger e os artefatos de uma rodada e chama `publish → verify → promote`
   sem passar pelo git. Concorrência: lane 2 para o trabalho de candidato,
   lane 3 (serializada) para a promoção — nunca as duas no mesmo grupo.
2. **Nada de PR nem de merge no caminho de dados.** A propriedade tem de ser
   **estrutural**, não uma política: se a lane verde não tem `contents: write`
   nem token de PR, ela não *pode* abrir PR. Prove isso a partir do arquivo,
   como `tests/test_workflow_lanes.py` faz.
3. **De onde vem a entrada.** O caminho de publicação consome um ledger v3 e
   artefatos com os checksums que ele sela. Hoje nada em runtime emite um
   ledger v3 (`ledger_v3.py` vive na branch do 2A.6 e não é importado por
   `run_detection*.py`). **Decida e registre** como a lane obtém um: emitir na
   rodada verde, ou aceitar um artefato de uma rodada anterior. Não invente um
   segundo produtor de ledger.
4. **Inércia enquanto a identidade não existir (§2d).** A lane pode ser
   completa e ficar inerte, falhando fechado e nomeando a capacidade que falta,
   como o `v2_promotion_lane.yml` faz. **Não** crie Environment, não referencie
   secret inexistente como se existisse, não use a identidade do candidate.
5. **A lane azul intocada.** `detect_gee.yml`, `update_data.yml` e o
   `update-data.yml` do site ficam byte-idênticos. O desligamento do bot azul é
   **Phase 6**.

**Fora de escopo, explicitamente:** a separação público/privado do R2, a rota
`/data/...`, credenciais de menor privilégio e política de retenção/exclusão
são **2B.3**. O artefato do site, o deploy e "sem bot pushes" no lado do site
são **2B.4**. Não comece nenhum, nem a Phase 3, nem o replay 2026.

## 4. Decisões de escopo já tomadas, com sua base

- **O release verde vai para o R2, não para o git.** O passo de publicação do
  `detect_gee.yml` recusa qualquer caminho fora de `data/timeseries/`, e mudar
  essa guarda é mudança de **workflow azul**. O roadmap ("automatic without
  PRs or manual merges") aponta para o R2. Já é o que o 2B.2B faz.
- **O `RELEASE.json` não é substituído** (§2j). Vale igual aqui.
- **A promoção é serializada na lane 3 e o compare-and-swap fica atrás dela,
  não em vez dela** — grupos de concorrência são por repositório, então uma
  rodada local ou um re-dispatch de outra ref está fora da lane.

Se aparecer evidência contra qualquer uma, **pare e pergunte** em vez de trocar
por conta própria.

## 5. Fronteiras duras

- A `main` do backend é **pull-request-only**, com bypass vazio. Nunca faça
  push direto, nunca adicione ator de bypass, nunca mexa em configuração do
  repositório para contornar. Trabalhe em branch, abra PR, **não faça merge**.
- Produção segue congelada nas Fases 2B–5: nada de escrita em `araripe-cogs`,
  nada de tocar o Worker `observatorio-chapada`, o domínio final, DNS, rotas,
  ponteiros canônicos, artefatos publicados atuais, ou os workflows azuis.
- **Alteração em workflow azul exige aprovação humana explícita**: prepare,
  explique o impacto, espere. O mesmo para qualquer mudança de configuração de
  repositório, incluindo a branch policy do Environment (§2e).
- Claude não recebe credencial de control-plane da Cloudflare. O único caminho
  é uma operação já allowlistada no broker
  `.github/workflows/cloudflare_green_control.yml`; se ela não existir lá,
  **pare e faça handoff**. Não edite o broker e despache na mesma tarefa, e
  nunca aprove seu próprio Environment.
- Autonomia: desenvolvimento e branches locais, objetos em
  `araripe-v2-staging`, workflows verdes manuais com só a identidade de
  staging, verificações read-only, commits, pushes de branch e abrir PR seguem
  sem aprovação repetida. Qualquer coisa com autoridade ou efeito em produção
  espera.
- Preserve `claude/phase2b0-green-isolation`, `codex/technical-review-roadmap`
  e `claude/phase2a6d-mapbiomas`.

## 6. Armadilhas já pagas — não redescobrir

- **`detect_gee.yml` não é idempotente**: um re-run reprocessa a janela de 16
  dias e infla `n_sightings`. Nunca dispare só para testar.
- **As duas armadilhas de shell do passo de publicação** (§2c). Não desfaça o
  `shell: bash` nem acrescente `exit 0`.
- **Em runner, `ee.Initialize(project=...)` ignora
  `GOOGLE_APPLICATION_CREDENTIALS`**; use `ee_initialize()` de
  `src/acquisition/gee_download.py`. Existe um secret `EE_PROJECT`, mas os
  workflows leem `vars.EE_PROJECT` — o secret é peso morto.
- **Nunca afirme invariante que o produtor não promete.** `first_seen <=
  last_seen` derrubou a produção em 2026-09-07; `max(last_seen)` **não** é
  watermark, porque `update_tracks` o move para trás na janela de 16 dias.
- **Não escreva ramo inalcançável.** O 2B.2B recusou uma checagem de watermark
  intra-release porque o portão do ledger já a torna verdadeira por construção.
  Antes de acrescentar checagem fail-closed, ache o caminho por onde ela falha.
- **Colete todos os achados, não pare no primeiro** — `findings.py` já dá o
  padrão: código estável, caminho, contagem e histograma na primeira linha.
- **Não adivinhe intenção por checksum.** A CLI do 2B.2B, no primeiro
  rascunho, rotulava silenciosamente como "produto de data" um arquivo que não
  casava com nenhum checksum selado — então um artefato **adulterado** passava
  como outro tipo de objeto. Intenção se declara (`--artifact` vs `--product`),
  não se deduz.
- **Ao testar workflow, leia o que o shell executa, não o que ele imprime.**
  Quatro testes do 2B.2B liam prosa de heredoc como se fosse código. O helper
  `executed()` em `tests/test_promotion_lane.py` já resolve isso.
- **A recontagem de persistência e o limiar `CONFIRMED_MIN = 15` já estão
  mapeados** (Topic 2, Package 2A.1 implementado, limiar é Phase 5). Não abra
  frente nova.

## 7. Ao final

Testes fail-closed e determinísticos para cada item — sem rede, sem relógio
real, sem object store: injete cliente S3 falso e relógio, como
`tests/fake_object_store.py` e `tests/test_atomic_publish.py` fazem. Reuse
`tests/green_release_fixtures.py` em vez de montar ledger novo. Rode
`/opt/anaconda3/envs/araripe/bin/python -m pytest -q` e reporte falhas
pré-existentes em separado. Commits coerentes com base verificada em SHA de 40
caracteres copiado da ferramenta. Crie
`docs/implementation/PHASE_2B2C_<data>.md`. Confirme árvore limpa — os
untracked `data/baselines_v2/`, `data/landcover/updated/` e `data/validation/`
são artefatos pré-existentes do 2A.6 e ficam **fora** do commit. Abra a PR
**sem mesclar**. Termine com o estado do gate P2B, dizendo explicitamente o que
ainda falta nele, e com a seção final obrigatória do método de handoff.

**Não inicie o 2B.3, o 2B.4, a Phase 3 nem o replay 2026.**

## 8. Estado que este package herda

- **Package 2B.2B implementado**, PR #35 aberta em 2026-09-07 com **439
  passed** (base 281), **sem nenhuma aprovação humana pendente**.
- **Package 2B.2A na `main`** (#33), com o `environment.yml` já aprovado.
- **Package 2B.1 fechado e validado em produção.**
- **Package 2B.0 na `main`**: broker verde isolado, lanes verdes, Environments
  `v2-staging` (sem revisor, só `main`) e `cloudflare-green-control` (com
  revisor humano obrigatório).
- **Package 2A.6 fechado** em `claude/phase2a6d-mapbiomas`
  (`64fd781f1551a45914a7db32960b923c05056955`), **não mesclado** e não precisa
  ser — o contrato consumido já está fixado na `main`.
- **Baseline `2.1.0`** existe localmente e não está publicada; colocação no R2
  é do 2B.3. `BASELINE_VERSION` em runtime segue `1.0.0`.
- **Falta a identidade protegida de promoção** (§2d) — decisão do dono.
- **Prova executável das lanes do 2B.0 ainda pendente** (quatro rodadas
  concorrentes, quatro URLs registradas). Agora despachável com
  `mode=lane-proof`. É gate do 2B.0, **não** deste package.
- **Pendência viva fora deste package:** `urs.earthdata.nasa.gov` inalcançável
  dos runners desde 01/09; a chuva do site não atualiza desde o raster de
  25/08. Saída verificada: definir `EARTHDATA_TOKEN`. Decisão do dono.

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

A sessão do 2B.2B terminou tudo o que se propôs: o código está escrito, testado
e numa PR. Não sobrou trabalho de programação.

O que sobrou é de outra natureza: **nada disso rodou de verdade ainda.** Tudo
foi provado com um armazenamento de mentira, dentro da máquina. Rodar contra o
armazenamento real depende de duas coisas suas — juntar a PR e criar uma chave
de acesso nova. Enquanto isso não acontecer, o sistema novo existe mas está
desligado.

### O que você precisa fazer

1. **Juntar (merge) a PR #35 na `main`.** Pode fazer sem medo: nada nela é
   ligado ao sistema que roda hoje. Não muda nenhum programa em produção, não
   muda o que as máquinas instalam, e nada no que roda hoje chama esse código
   novo. Sem urgência, mas nada avança antes disso.
2. **Juntar a PR do método de handoff** (esta, com o documento de método e o
   novo formato de prompt). Só documentação e testes.
3. **Criar uma chave de acesso separada para a promoção.** É a única coisa que
   eu não posso fazer: criar credencial é decisão sua. Precisa ser uma chave que
   só alcance a caixa de testes `araripe-v2-staging`, diferente da que já
   existe. Sem ela, a publicação automática fica pronta mas desligada.
4. **Decidir sobre o `EARTHDATA_TOKEN`** — ver a próxima seção, é a única coisa
   com prazo.
5. **Opcional, quando quiser:** rodar a prova das quatro execuções simultâneas
   que ficou pendente desde o 2B.0. Agora é possível com um clique.

### Tem algo preocupante?

**Sim, uma coisa — e não é do 2B.2B.**

A chuva do site não atualiza desde 25 de agosto, porque o servidor da NASA de
onde vêm os dados parou de responder às nossas máquinas em 1º de setembro. **A
execução de sexta-feira, 11 de setembro, vai falhar se nada for feito.** A
solução já está identificada e é simples: definir uma chave chamada
`EARTHDATA_TOKEN`. É decisão sua e continua pendente.

Do resto: **não.** O trabalho do 2B.2B é todo aditivo — código novo que nada em
produção chama. Não mexi em produção, não escrevi em nenhum armazenamento real,
e os programas que rodam hoje estão idênticos ao que eram.

### O que ainda falta no caminho

- **2B.2C — publicação automática** (é o que este briefing pede). Fazer o
  sistema publicar sozinho, sem depender de juntar PRs a cada rodada.
  *Depende da chave de acesso nova para rodar de verdade.*
- **2B.3 — separar o que é público do que é privado** no armazenamento, criar
  o endereço `/data/...` do site, e definir por quanto tempo cada arquivo fica
  guardado.
- **2B.4 — o site novo**: parar de guardar arquivos grandes de alerta dentro do
  repositório, e preparar a publicação do site.
- **Phase 3 — congelar e ensaiar** o reprocessamento de 2026: escolher a data
  de corte e tirar uma fotografia de tudo antes de começar.
- **Phase 6 — a troca final**: o dia em que o sistema novo substitui o antigo,
  o site aponta para ele, e o robô antigo é desligado. Só depois de tudo acima.

Além dessas etapas, duas provas ainda faltam para fechar a Phase 2B: rodar a
publicação contra o armazenamento real (depende da chave), e rodar tudo uma vez
com dados de uma execução real e não de exemplo.
