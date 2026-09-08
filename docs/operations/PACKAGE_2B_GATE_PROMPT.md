# Exit gate P2B — o montador da rodada, e o fechamento da Phase 2B

> **FECHADO em 2026-09-08.** Os quatro itens do escopo foram entregues e o
> gate foi provado contra o R2 real com dado de execução real. O registro é
> [`../implementation/PHASE_2B_GATE_2026-09-08.md`](../implementation/PHASE_2B_GATE_2026-09-08.md),
> e é ele que diz o que ficou provado e o que continua sem prova. Este
> documento fica como o briefing que foi executado — **não é mais uma tarefa
> aberta**. O ponto de entrada que faltava é `scripts/assemble_green_run.py`.

Escrito em 2026-09-08 depois de fechar o Package 2B.4B, e **revisado no mesmo
dia** — leia a §0 antes de qualquer coisa, porque o item 1 do escopo mudou de
estado.

O Package 2B.4 era **o último package da Phase 2B**. Não há 2B.5 no roadmap —
confira antes de propor um. O que resta é o **exit gate P2B**.

## 0. O que mudou depois de este briefing ser escrito — leia primeiro

O montador da rodada **já existe**. Mesclado como `bf2c2cf` (`#49`),
`src/publication/run_assembler.py`, 33 testes, com uma prova ponta a ponta de
duas releases: montar → subir → `load_run` → publicar → verificar → promover A →
promover B (supersede) → reverter para A (`sequence` 3, cobertura de volta).

**Mas ele é biblioteca, e nada além do próprio teste o importa.** Medido:

    for f in $(git ls-tree -r --name-only origin/main | grep -E '^(scripts|src|tests)/.*\.py$'); do
      git show "origin/main:$f" | grep -q run_assembler && echo "$f"
    done
    # tests/test_run_assembler.py    <- só isto

Então o item 1 do escopo (§3) **não é mais "escrever o montador"**: é
**escrever o ponto de entrada de operador** que o liga a uma execução de
detecção real, em vez de a uma fixture. Não reescreva a biblioteca. Leia o
módulo primeiro — ele documenta no próprio docstring o que deliberadamente
**não** faz (não produz ledger, não decide o que é forte) e por quê.

O item 2 do escopo (satisfazer o contrato do artefato do site) **também já
está feito**: o montador importa `site_artifact` e `ledger_gate`, e chama
`site_artifact.strong_features` e `classify_run_objects` em vez de reimplementar
a regra.

Restam, portanto, **quatro** itens: o ponto de entrada, a prova de falha e de
concorrência, a publicação real no `araripe-v2-staging` com ida e volta do
ponteiro, e o registro do fechamento.

Segue o método em [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md)
versão 2: o corpo é para o agente executor, e a **seção final é para o dono**.

---

## 1. Dependência que precede tudo — confirme por conteúdo

    # backend
    git rev-parse origin/main
    git show origin/main:src/publication/site_artifact.py | head -3
    git show origin/main:docs/contracts/phase2b/site_artifact_conformance_vectors.json \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); print({g: len(d[g]) for g in ("object_cases","run_cases","index_cases","rejection_cases")})'
    # site
    git show origin/main:scripts/site_artifact.py | head -3

Espere `{'object_cases': 8, 'run_cases': 10, 'index_cases': 4,
'rejection_cases': 9}` — **31 casos**. Cuidado com `--grep`: ele busca a
mensagem inteira. Filtre por `%s`:
`git log origin/main --format='%H %s' | grep '(#<número>)'`.

Gates **medidos na `main` em 2026-09-08**, depois de `#46`-`#50` no backend e
`#20`/`#22`/`#23` no site:

| repositório | comando | resultado medido |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **812 passed** |
| site | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **201 passed** |
| site | `npm ci && npm run test:worker` | **44 tests, 44 pass** |

**Use `npm run test:worker`, não `node --test tests/`.** Nesta máquina o Node é
v25.8.2, e ali `node --test tests/` tenta *carregar* `tests/` como módulo e
morre com `MODULE_NOT_FOUND` — um fracasso que parece do repositório e é da
invocação. O script do `package.json` passa o glob
(`node --test tests/*.test.mjs`), que é o que funciona.

**Meça antes de editar** — são fatos datados.

Se `src/publication/site_artifact.py` não estiver na `main` do backend: **pare e
pergunte.**

## 2. O que já foi verificado, para o executor não refazer

Detalhe completo em `docs/implementation/PHASE_2B4B_2026-09-08.md` e
`PHASE_2B4A_2026-09-07.md`.

**a. Quem produz o manifesto do site está DECIDIDO e registrado.**
`SITE_ARTIFACT_CONTRACT_V1.md`: o índice é derivado por um passo verde, não
selado numa release. Publicá-lo como `date_product` foi recusado por medição —
o prefixo da release é função do **ledger só**, então um renderer diferente
colide com o próprio prefixo. **Não reabra essa decisão** sem evidência nova.

**b. O contrato já impõe requisitos SOBRE o montador da rodada, e eles são o
seu ponto de partida.** Por data, a release tem de declarar **exatamente um**
objeto terminando `.geojson` (e não `.strong.geojson`) e **exatamente um**
terminando `.strong.geojson`. E o objeto forte tem de conter **exatamente as
feições contadas que são fortes** — `strong_features`, não `is_strong`: a
diferença é geometria, e errá-la publica uma contagem errada. Os 8
`object_cases` e os `expected_strong_indices` fixam os dois.

**c. MEDIDO: `boto3` não está instalado** no interpretador que roda os scripts
do site, e o caminho verde não depende dele. O compositor lê por HTTP ou
diretório.

**d. MEDIDO: o repositório do site NÃO tem Environment nenhum**
(`total_count: 0`). **Não nomeie um que não existe** — o GitHub cria, sem
proteção e sem política de branch.

**e. MEDIDO: remover a re-inclusão do `.gitignore` QUEBRA o azul.** Está numa
branch própria, `claude/phase2b4b-stop-committing-alerts`, com a condição de
merge escrita. Um arquivo de data nova fica ignorado, `git add public/data`
**sai 0 em silêncio**, e `manifest.json` continua sendo commitado nomeando um
arquivo que nunca é implantado → 404 na data mais recente. **Não mescle essa
branch** antes de a página ler pela rota (Phase 6).

**f. O Worker verde de staging continua sem hostname**, então `--from-route`
nunca correu contra HTTP de verdade. Capacidade nomeada em
`GREEN_RETENTION_AND_MIGRATION.md` §5.

**g. Mover e reverter o ponteiro verde estão provados no R2 real** (2026-09-07).
O gate não espera por isso.

**h. Um ramo do validador foi apagado por ser inalcançável** (o schema já
recusava). A regra que ficou: **as duas metades têm de rodar** — schema e
validador. Se você escrever um check novo, pergunte primeiro se o schema já o
faz.

## 3. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: este é o **exit gate de uma fase inteira**, e o montador da rodada é
> o produtor que decide o que entra numa release imutável. Um objeto mal
> declarado não é corrigível por republicação — o prefixo é função do ledger, e
> bytes diferentes no mesmo prefixo falham fechado. Errar aqui custa uma
> release, não um commit.

Feche o **exit gate P2B**: *"A deliberately failed or racing green run cannot
corrupt blue or expose a partial release; a staged test release can move and
roll back its green pointer without a manual data PR or any production
effect."*

**Orientação obrigatória antes de qualquer conclusão.** Siga "Establishing the
real state" do `AGENTS.md` do workspace nos **dois** repositórios. Leia canônico
com `git show origin/main:<path>`. Confirme o SHA de 40 caracteres da base com
`git rev-parse origin/main` e **cole-o**. Ative o hook com
`git config core.hooksPath .githooks` nos dois. **O hook recusa qualquer SHA de
40 caracteres que não exista naquele repositório** — inclusive um SHA legítimo
de outro repositório, como o pin do `actions/checkout`, ou o SHA do outro
repositório do workspace. Deixe esses no arquivo, não na mensagem de commit.

**Base.** `claude/phase2b-gate` a partir de `origin/main`, **depois** de
confirmar §1.

### Escopo

1. ~~O montador da rodada~~ **— FEITO em `bf2c2cf`. Ver §0.** O que resta é o
   **ponto de entrada de operador**: o script que monta `runs/<run-id>/` a
   partir de uma execução de detecção real e o deposita, em vez de a partir de
   fixture. É a peça que transforma "o caminho verde é exercitável contra
   fixture" em "o caminho verde rodou com dado real". O ledger é **insumo** dele,
   não produto — não existe segundo produtor de ledger (§4).
2. ~~Fazê-lo satisfazer o contrato do artefato do site~~ **— FEITO. Ver §0.** O
   montador importa `site_artifact` e `ledger_gate`. O que resta é rodar os
   vetores existentes como gate **no caminho novo**, com dado de execução real
   em vez de fixture.
3. **A prova de execução falhada e de execução concorrente**: o gate fala de
   "deliberately failed or racing", e as duas metades precisam de uma prova
   executada, não de um argumento.
4. **Publicar uma release de teste com dado de execução real** no
   `araripe-v2-staging` e mover e reverter o ponteiro. Autônomo: staging,
   identidade bucket-scoped, `v2-staging` sem revisor.
5. **Registrar o fechamento** do gate e da Phase 2B, com o que ficou provado e
   o que continua não provado.

**Fora de escopo, explicitamente:** o cutover, o desligamento do bot azul, o
desligamento do caminho público azul, ligar a página a `object_base` e qualquer
coisa no domínio final são **Phase 6**. O replay 2026 é **Phase 3** — o dado
real deste gate é uma execução, não o reprocessamento do ano. O histórico de
promoção e qualquer exclusão real são pacotes próprios. Reescrever a história do
git para recuperar os 247 MiB não é deste package.

## 4. Decisões de escopo já tomadas, com sua base

- **A política de exposição e a das estatísticas são do backend**; o Worker e o
  compositor do site são adaptadores. Os vetores são a referência.
- **O índice do site é derivado, não selado.** Ver §2a.
- **A rota verde é aditiva em `/data/green/`** e o `/data/…` estático fica
  intocado — é o caminho antigo, e mantê-lo é o rollback.
- **Nada é apagado.** Nem no R2 nem na história do git.
- **Nenhuma lane verde carrega cron antes da Phase 6.**
- **Nenhum segundo produtor de ledger.** O montador da rodada **usa** o ledger
  que a detecção produz; ele não escreve um.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- A `main` do backend é **pull-request-only**, bypass vazio. Branch, PR, **sem
  merge**.
- **A `main` do site faz deploy de produção.** Prove o que muda pelo fecho dos
  imports e pelo conteúdo de `dist/`.
- Produção congelada nas Fases 2B–5.
- **Exclusão de objeto real exige aprovação humana explícita e nomeada.**
- Claude não recebe credencial de control-plane da Cloudflare.
- **Nunca nomeie um Environment que não existe.**
- Preserve `claude/phase2b0-green-isolation`, `codex/technical-review-roadmap`,
  `claude/phase2a6d-mapbiomas`, `ci/promotion-identity-probe`,
  `claude/phase2b3-r2-separation`, as branches do 2B.4A e as **duas** do 2B.4B.

## 6. Armadilhas já pagas — não redescobrir

- **Outra sessão pode estar no mesmo clone.** Existe um `stash@{0}` de outra
  sessão no backend. **Nunca `git stash` em árvore alheia**; adicione por nome.
- **O hook `commit-msg` recusa SHA estrangeiro.** Ver §3.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca dispare para testar.
- **ETag não é checksum** — multipart é MD5 dos MD5s com sufixo `-N`.
- **Não confie em invariante que o produtor não promete.**
- **Um teste pode passar pelo motivo errado.** No 2B.4B, um teste que exigia
  ausência de `boto3` acusou a **docstring** que explica por que `boto3` não é
  usado — docstring não começa com `#`. Use `ast` para import, e
  `executable_lines()` para shell e YAML. Pergunte sempre **qual mutação o
  teste derruba**.
- **Um check pode ser inalcançável.** Ver §2h.
- **`grep` desta máquina é `ugrep`**: `grep -qv` retorna 1 mesmo com linhas
  selecionadas. Capture a saída e teste se está vazia.
- **`cut` não está disponível no shell das ferramentas**; use Python.
- **`node --test tests/` quebra no Node v25** com `MODULE_NOT_FOUND`, que parece
  falha do repositório e é da invocação. Use `npm run test:worker`. Ver §1.
- **Dois orçamentos de 14 dias medem coisas diferentes** na chuva do site, e
  divergem: `MAX_DIAS_SEM_ATUALIZAR` em `fetch_gpm.py` conta do **raster mais
  novo em disco**, e `freshness.py check chuva --max-age-days 14` conta de
  **`updated_utc`**. Não são redundantes e não estouram no mesmo dia. Ver §8.
- **`cd` composto no shell das ferramentas pode não pegar.** Use caminho
  absoluto em cada comando.

## 7. Ao final

Testes fail-closed e determinísticos: sem rede, sem relógio real, sem object
store. Reuse `tests/green_release_fixtures.py`, `tests/fake_object_store.py`, o
bucket falso de `tests/data_route.test.mjs` e a fixture
`site/tests/fixtures/green-release`. Rode
`/opt/anaconda3/envs/araripe/bin/python -m pytest -q` no backend, e
`npm ci && npm run build && npm test && npm run test:worker` no site; reporte
falhas pré-existentes em separado. Commits por repositório, **nunca
misturados**, com base verificada. Crie
`docs/implementation/PHASE_2B_GATE_<data>.md`. Confirme árvore limpa — os
untracked `data/baselines_v2/`, `data/landcover/updated/` e `data/validation/`
ficam **fora**. Abra as PRs **sem mesclar**. Termine com o estado do gate P2B e
com a seção final obrigatória do método de handoff.

**Não inicie a Phase 3, a Phase 6 nem o replay 2026.**

## 8. Estado que este gate herda

- **Tudo mesclado até `05e2a12`** na `main` do backend, e até `826fc0d` na do
  site. Nenhuma PR aberta nos dois repositórios em 2026-09-08. Confira, não
  confie nesta linha.
- **O montador da rodada está na `main`** (`bf2c2cf`), como biblioteca sem
  ponto de entrada. **Ver §0** — é o que mais muda o escopo deste gate.
- **O registro da Fase 5 ganhou portão de revisão** (`05e2a12`, `#50`): a Fase 5
  não começa sem revisão do dono, porque o objetivo passou a ser uma publicação
  científica. **Isso não trava este gate, nem as Fases 6 e 7.** Mas cria um
  requisito que a Phase 6 terá de honrar: um artigo cita **uma** release, e
  aquela release passa a ter de existir para sempre
  (`PACKAGE_P5_PROTOCOL_PROMPT.md` §0-ter).
- **O arnês de verificação da rota verde vazava um `workerd` por execução**,
  corrigido no site `#23` (`826fc0d`). Se você rodar
  `scripts/verify_green_route.sh`, confira ao fim que a porta ficou livre e que
  nenhum `workerd` sobrou: `pgrep -fl workerd`. O defeito real foi medido —
  cinco runtimes órfãos, um vivo cinco horas.
- **Package 2B.4B entregue**, 2026-09-08: o contrato do artefato do site, 31
  vetores, o compositor do site, a fixture offline, a lane verde inerte e os
  pins medidos. Três defeitos achados e corrigidos no caminho.
- **A remoção da re-inclusão do `.gitignore` está pronta e NÃO deve ser
  mesclada ainda.** Ver §2e.
- **Package 2B.4A mesclado** (backend `#45`, site `#19`).
- **Package 2B.3 mesclado.** A Phase 2B.2 está inteira na `main`. 2B.1 fechado
  e validado em produção. 2B.0 na `main`.
- **Environments do backend:** `cloudflare-green-control` (com revisor),
  `v2-staging` e `v2-promotion` (sem revisor, política `main`).
  **O repositório do site não tem Environment nenhum.**
- **Package 2A.6 fechado** em `claude/phase2a6d-mapbiomas`, não mesclado.
- **A chuva do site está pulando por rede, e o relógio está medido.** Não é o
  token e não é o nosso código. Fatos de 2026-09-08:
  - run `34216040390` (cron, 10:33Z) saiu **success** com
    `public/data/freshness/chuva.json` em `status: "skipped"` e
    `ConnectTimeoutError` em `urs.earthdata.nasa.gov:443`. Só o `checked_utc`
    andou; o `updated_utc` ficou em `2026-09-07T21:59:06Z`;
  - o run anterior (`34165003418`, `workflow_dispatch`, 21:58Z) **atualizou** a
    chuva com o mesmo token e o mesmo código — então a credencial funciona;
  - o URS respondeu `302` em `0,16 s` desta máquina, por IPv4 **e** IPv6, no
    mesmo dia. O endpoint está no ar;
  - `force_ipv4()` **já é chamado** por `fetch_gpm.py`, então não é a
    regressão de IPv6 antiga.
  - **Conclusão sustentada pela medição:** é o caminho de rede entre o runner
    do GitHub e o URS. `n=1` no regime pós-correção do token, então ainda não
    dá para dizer se é crônico.
  - **O relógio:** o raster mais novo é `2026-09-04`, e
    `MAX_DIAS_SEM_ATUALIZAR = 14` conta dele — estoura no cron de
    **terça 2026-09-22** (`atraso=18`). `freshness.py` conta de `updated_utc` e
    estoura em `2026-09-21 21:59Z`, observado no mesmo cron. **Sexta 2026-09-11
    não fica vermelha** — quem afirmar isso está lendo uma nota velha, escrita
    antes de o run de 09-07 zerar o contador. Uma única rodada bem-sucedida
    zera tudo de novo.
- **Pendência com data: o token da NASA expira em 2026-11-06** e a chuva do site
  para de novo. Essa falha, sim, aparece no download — run vermelho, não
  congelamento silencioso.
- **Mesmo padrão suspeito no fallback do backend**, sem prazo: o passo "Run
  detection pipeline" do `update_data.yml` passa só usuário e senha do
  Earthdata, e não foi verificado se `run_detection.py` chega a fazer login.
  Pode ser que a correção certa seja **remover** as duas linhas.

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

**A etapa foi entregue inteira, e a decisão central que a bloqueava está
tomada.** O sistema agora sabe quem monta o índice que a página de alertas lê —
e a resposta não foi a que o plano imaginava. A ideia original era guardar esse
índice dentro do "pacote lacrado" de cada publicação. Medindo, descobri que isso
criaria uma armadilha: o pacote é endereçado por uma impressão digital dos dados
brutos, então mudar qualquer critério de exibição depois faria a publicação
colidir com ela mesma e travar. E os critérios **estão previstos para mudar**,
numa etapa mais adiante. Então o índice passou a ser **recalculado** a partir do
pacote lacrado, o que dá o mesmo resultado sem a armadilha.

Ficou pendente uma coisa, e ela é uma decisão sua: **tirar os arquivos grandes
de dentro do repositório quebra o site atual.** Medi exatamente como: o índice
continuaria sendo salvo apontando para arquivos que deixariam de ser enviados, e
a aba de alertas ficaria sem a data mais recente — sem nenhum aviso, porque o
robô não falha. Então deixei essa mudança pronta e **separada**, numa proposta
própria que não deve ser aplicada antes de a página aprender a ler pelo caminho
novo. O resto da etapa não depende dela.

Continua pendente, do mesmo jeito que antes, **testar a rota num navegador de
verdade**: o servidor de teste continua sem endereço. **Este portão não depende
disso.**

Uma atualização importante desde que este documento foi escrito: **a peça que
faltava — o montador — já entrou** (`bf2c2cf`). Ela sabe montar uma rodada e
foi provada de ponta a ponta com duas publicações e uma volta atrás. O que
falta é ligá-la a uma execução de verdade, em vez de a um exemplo montado à
mão. A §0 explica isso ao agente para ele não reescrever o que já existe.

### O que você precisa fazer

1. **Juntar três propostas, na ordem certa.** Duas podem entrar quando você
   quiser — uma no repositório do monitoramento e outra no do site — e o que
   muda no site publicado é **nada**, provado por teste. A terceira, a que tira
   os arquivos grandes, **espera**: aplicá-la hoje quebra a aba de alertas na
   sexta seguinte.
2. **Decidir como dar um endereço temporário ao servidor de teste.** É a mesma
   pendência da etapa anterior. Precisa de alguém com acesso ao painel da
   Cloudflare. **Este portão não depende disso** — mover e reverter o ponteiro é
   trabalho de objeto no armazenamento, e o endereço só é necessário para ver a
   rota num navegador.
3. **Criar um "ambiente" protegido no repositório do site**, se quiser que a
   publicação automática avance. Hoje não existe nenhum, e sem ele a publicação
   sem robô fica pronta mas parada. Peça que exija aprovação humana: a permissão
   necessária é de conta inteira, ou seja, quem publica o site de teste
   consegue publicar o de produção.
4. **Chuva do site — decisão de uma linha, e só se você quiser.** O mapa de
   chuva parou de atualizar por problema de rede entre o robô do GitHub e o
   servidor da NASA, e o sistema está fazendo exatamente o que foi desenhado
   para fazer: pula em silêncio e só fica vermelho quando deixa de ser um
   soluço. **Há 14 dias de folga e três tentativas automáticas** antes disso
   (11, 15 e 18 de setembro); o primeiro dia vermelho é **22 de setembro**, e
   qualquer rodada bem-sucedida zera o contador. Não é preciso fazer nada. Se
   quiser antecipar, a única ação útil é **pedir uma rodada manual num horário
   diferente** — se ela passar, o mapa volta e o contador zera; se falhar, a
   gente aprende que o problema não é hora do dia. Isso publica dado no site,
   então não faço por conta.
5. **Anotar 6 de novembro:** a chave da NASA expira e a chuva para de novo — e
   essa falha é vermelha, não silenciosa.

### Tem algo preocupante?

**Não.** Nada quebrou, produção não foi tocada, e o site publicado continua
exatamente igual.

Vale registrar duas coisas, e nenhuma é um problema hoje.

A primeira: **encontrei três defeitos escrevendo esta etapa, e os três eram
meus.** O mais interessante é este — o sistema montava o "subconjunto forte" (o
que a página mostra por padrão) usando só as características do alerta, e
esquecia de checar se o alerta tinha forma desenhável. O resultado seria um
arquivo com mais itens do que o número exibido ao lado dele. Não apareceu em
nenhum teste isolado; apareceu quando montei um exemplo pequeno de ponta a ponta
e os dois caminhos discordaram. É um bom argumento para ter esses exemplos.

A segunda: **um dos meus testes acusou o próprio comentário que explicava o que
ele proibia.** Bobo, e revelador — a checagem lia o texto do arquivo em vez do
que o programa executa. Corrigi lendo a estrutura do código. É a mesma
armadilha da etapa anterior, no sentido contrário.

### O que ainda falta no caminho

- **O fechamento da fase atual:** falta ligar o montador a uma execução real,
  provar que uma rodada quebrada e duas rodadas ao mesmo tempo não estragam
  nada, publicar uma release de teste de verdade com ida e volta, e registrar o
  fechamento. Nada disso depende de você.
- **A verificação no navegador**, assim que o servidor de teste tiver endereço.
- **Uma etapa própria para a memória de publicações**, que é o que permitirá um
  dia apagar versões antigas com segurança.
- **Phase 3 — congelar e ensaiar** o reprocessamento de 2026.
- **Phase 6 — a troca final:** o novo substitui o antigo, a página passa a ler
  pelo caminho novo, o robô antigo é desligado, o endereço público antigo é
  fechado, e a publicação passa a acontecer sozinha num horário. É nessa etapa
  que a proposta guardada dos arquivos grandes entra.
