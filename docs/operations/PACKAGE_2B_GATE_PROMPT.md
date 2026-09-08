# Exit gate P2B — o montador da rodada, e o fechamento da Phase 2B

Escrito em 2026-09-08, depois de fechar o Package 2B.4B.

O Package 2B.4 era **o último package da Phase 2B**. Não há 2B.5 no roadmap —
confira antes de propor um. O que resta é o **exit gate P2B**, e ele falha hoje
por uma razão só, nomeada desde o 2B.2C: nenhum produtor deposita
`runs/<run-id>/`.

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

Gates medidos nas branches do 2B.4B: **backend 771 passed**; **site 175 pytest
+ 44 `node --test`** na branch do artefato. **Meça antes de editar** — são fatos
datados. Se o 2B.4B ainda não estiver mesclado, espere 697 e 90+44.

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

1. **O montador da rodada**: o produtor que deposita `runs/<run-id>/` — o
   `run.json`, o `ledger.json` e os corpos — a partir de uma execução de
   detecção. É a peça que falta desde o 2B.2C, e é o que transforma "o caminho
   verde é exercitável contra fixture" em "o caminho verde rodou com dado real".
2. **Fazê-lo satisfazer o contrato do artefato do site** (§2b acima) e o
   `GREEN_RELEASE_CONTRACT_V1.md`, com os vetores existentes como gate.
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
- **Pendência com data: o token da NASA expira em 2026-11-06** e a chuva do site
  para de novo. A falha aparece no download — run vermelho, não congelamento
  silencioso.
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
verdade**: o servidor de teste continua sem endereço.

### O que você precisa fazer

1. **Juntar três propostas, na ordem certa.** Duas podem entrar quando você
   quiser — uma no repositório do monitoramento e outra no do site — e o que
   muda no site publicado é **nada**, provado por teste. A terceira, a que tira
   os arquivos grandes, **espera**: aplicá-la hoje quebra a aba de alertas na
   sexta seguinte.
2. **Decidir como dar um endereço temporário ao servidor de teste.** É a mesma
   pendência da etapa anterior. Precisa de alguém com acesso ao painel da
   Cloudflare.
3. **Criar um "ambiente" protegido no repositório do site**, se quiser que a
   publicação automática avance. Hoje não existe nenhum, e sem ele a publicação
   sem robô fica pronta mas parada. Peça que exija aprovação humana: a permissão
   necessária é de conta inteira, ou seja, quem publica o site de teste
   consegue publicar o de produção.
4. **Anotar 6 de novembro:** a chave da NASA expira e a chuva para de novo.

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

- **O fechamento da fase atual:** falta a peça que monta automaticamente o
  pacote de cada rodada — hoje isso é feito à mão. É a última coisa que falta
  para a fase inteira poder ser declarada pronta, e é a próxima etapa.
- **A verificação no navegador**, assim que o servidor de teste tiver endereço.
- **Uma etapa própria para a memória de publicações**, que é o que permitirá um
  dia apagar versões antigas com segurança.
- **Phase 3 — congelar e ensaiar** o reprocessamento de 2026.
- **Phase 6 — a troca final:** o novo substitui o antigo, a página passa a ler
  pelo caminho novo, o robô antigo é desligado, o endereço público antigo é
  fechado, e a publicação passa a acontecer sozinha num horário. É nessa etapa
  que a proposta guardada dos arquivos grandes entra.
