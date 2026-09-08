# Package 2B.4B — briefing de execução

Escrito em 2026-09-07, depois de fechar a implementação do Package 2B.4A.
Substitui o restante de [`PACKAGE_2B4_PROMPT.md`](PACKAGE_2B4_PROMPT.md), que
continua válido como briefing do package inteiro — leia os dois, este primeiro.

Segue o método em [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md)
versão 2: o corpo é para o agente executor, e a **seção final é para o dono**.

---

## 1. Dependência que precede tudo — confirme por conteúdo

O 2B.4B move o **dado** do git para a rota que o 2B.4A construiu. Sem essa rota
não há para onde mover.

Confirme **por conteúdo, nunca por ancestralidade**, nos dois repositórios:

    # backend
    git show origin/main:tests/test_action_pinning.py | head -3
    git show origin/main:docs/contracts/phase2b/delivery_conformance_vectors.json \
      | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["cases"]), "casos")'
    # site
    git show origin/main:worker/data_route.js | head -3
    git show origin/main:wrangler.green.jsonc | head -3

Espere **19 casos**. Cuidado com `--grep`: ele busca a mensagem inteira. Filtre
por `%s`: `git log origin/main --format='%H %s' | grep '(#<número>)'`.

Gates medidos nas branches do 2B.4A: **backend 693 passed**, **site 90 pytest +
44 `node --test`**. **Meça antes de editar** — são fatos datados. Se o 2B.4A
ainda não estiver mesclado, espere 682 e 70.

Se `worker/data_route.js` não estiver na `main` do site: **pare e pergunte.**

## 2. O que já foi verificado, para o executor não refazer

Detalhe completo em `docs/implementation/PHASE_2B4A_2026-09-07.md` e
`PHASE_2B3_2026-09-07.md`.

**a. A rota existe, é conferida contra os vetores, e não define política.**
`worker/data_route.js` executa o que `src/publication/delivery_boundary.py`
decide. Se precisar de um comportamento novo, acrescente ao gerador do backend e
regenere os vetores. **Não invente política no Worker.**

**b. MEDIDO: o repositório do site tem 255,2 MiB commitados em `public/data`, e
246,8 MiB disso são alertas.** São 40 arquivos `run-*.strong.geojson` somando
242,5 MiB, mediana **5,35 MiB**, maior **17,70 MiB**. O `.git` tem **312 MiB**
com **74 commits**. O bot commitou **30 vezes em 60 dias**. Isto é o bullet 1
inteiro, e ele cresce ~600 MiB/ano de história irreversível.

**c. O `.gitignore` do site já exclui os arquivos "full" e RE-INCLUI os
"strong"**, chamando-os de "lean strong subsets". Eles não são enxutos: a
mediana é 5,35 MiB. A linha
`!public/data/alerts/run-*.strong.geojson` é o que precisa cair.

**d. MEDIDO: a `main` do site faz deploy de PRODUÇÃO.** O gatilho de produção do
Worker Builds está ativo. Só o gatilho de branch não-produção ficou inerte
(`exit 0`) no 2B.0. Cada commit do bot já é um deploy de produção — então um
merge não é anormal; o que importa é **o que muda no que é implantado**. O 2B.4A
não mudou nada e provou isso pelo fecho dos imports.

**e. MEDIDO: o repositório do site NÃO tem Environment nenhum** (`gh api …
/environments` → `[]`). Não há onde uma identidade verde viver protegida. **Não
nomeie um Environment que não existe** — o GitHub cria um, sem proteção e sem
política de branch, e isso é mudança de configuração de repositório.

**f. MEDIDO: o site não tem arquivo de dependências Python nenhum**, e o
workflow azul instala 10 pacotes sem pin (`boto3`, `python-dotenv`,
`earthaccess`, `rioxarray`, `rasterio`, `geopandas`, `numpy`, `matplotlib`,
`pillow`, `netCDF4`, `h5netcdf`). É o bullet 5, e é buraco real de
reprodutibilidade. **Fixar os pins do passo azul é edição de workflow azul** —
congelado. Um arquivo de requisitos que o caminho verde use e o azul ignore é
aditivo e permitido.

**g. O formato do site e o da release verde NÃO são o mesmo.** O
`manifest.json` do site tem `runs[]` com estatísticas por rodada (`count`,
`area_ha`, `high`, `first_obs`, `candidate`, `confirmed`, `strong`); a release
verde tem `dates[]` com `paths[]` e contagens por status do ledger. Alguém tem
de produzir o manifesto que o site lê. Ver §5 — é a decisão central deste
package.

**h. Nenhum produtor deposita `runs/<run-id>/` ainda**, então a release viva no
bucket de staging contém os dados de prova montados à mão (dois geojson
minúsculos de abril). O caminho verde é exercitável contra fixture, **não**
contra dado real. Isso é conhecido e é condição do gate P2B, não surpresa.

**i. O `STAGING_LIMITER` é declarado e não aplicado**, de propósito: 8
requisições/60 s é limite de chat e um carregamento de página faz várias
buscas.

**j. Provado por mutação no 2B.4A**, 15 checagens. Se mexer numa delas, o teste
correspondente cai — é assim que se sabe que a mudança foi intencional.

## 3. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: este package decide **o formato que o site público vai consumir** e
> tira 246 MiB do caminho de dado. Errar o formato obriga a refazer o produtor;
> errar a ordem da migração deixa o site sem alertas. E as duas coisas só
> aparecem depois do cutover, quando voltar atrás custa caro.

Continue o Observatório da Chapada do Araripe com o **Package 2B.4B — artefato
do site, publicação sem bot push e travamento de ambiente**.

**Orientação obrigatória antes de qualquer conclusão.** Siga "Establishing the
real state" do `AGENTS.md` do workspace nos **dois** repositórios. Leia canônico
com `git show origin/main:<path>`. Confirme o SHA de 40 caracteres da base com
`git rev-parse origin/main` e **cole-o**. Ative o hook com
`git config core.hooksPath .githooks` nos dois. **O hook recusa qualquer SHA de
40 caracteres que não exista naquele repositório** — inclusive um SHA legítimo
de outro repositório, como o pin do `actions/checkout`. Deixe esses no arquivo
de teste, não na mensagem de commit; foi o que aconteceu no 2B.4A.

**Base.** `claude/phase2b4b-site-artifact` a partir de `origin/main` em cada
repositório afetado, **depois** de confirmar §1.

### Escopo do 2B.4B

1. **Decidir e registrar quem produz o manifesto que o site lê** (§5), num
   contrato com schema, do mesmo jeito que o 2B.2A fez para o ledger.
2. **Parar de commitar os arquivos de alerta**: tirar a re-inclusão do
   `.gitignore`, e fazer o build verde consumir da rota. **O job azul fica
   byte-idêntico.**
3. **Manter fixtures pequenos e schemas** para desenvolvimento local e CI —
   o suficiente para `npm run build` e os testes rodarem sem rede.
4. **Publicar dado de rotina sem bot push nem PR de dados** no lado verde. O
   Environment não existe: construa completo e **inerte**, nomeando a
   capacidade em falta, como o 2B.2C fez com o `v2-promotion`.
5. **Travar os ambientes Python/Node** o bastante para reproduzir o build. Um
   arquivo de requisitos com pins **medidos**, não plausíveis.

**Fora de escopo, explicitamente:** o cutover, o desligamento do bot azul, o
desligamento do caminho público azul e qualquer coisa no domínio final são
**Phase 6**. O histórico de promoção e qualquer exclusão real são pacotes
próprios. O replay 2026 é **Phase 3**. Reescrever a história do git para
recuperar os 246 MiB já commitados **não é deste package** e provavelmente não é
de nenhum: é rewrite de história num repositório com automação ativa.

## 4. Decisões de escopo já tomadas, com sua base

- **A política de exposição é do backend; o Worker é adaptador.** Os vetores são
  a referência entre os dois.
- **A rota verde é aditiva em `/data/green/`** e o `/data/…` estático fica
  intocado — é o caminho antigo, e mantê-lo é o rollback.
- **Nada é apagado.** Nem no R2 nem na história do git.
- **O `RELEASE.json` azul continua azul** e não é substituído.
- **Nenhuma lane verde carrega cron antes da Phase 6.**

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. A decisão central: quem produz o manifesto do site

O site lê `/data/alerts/manifest.json` com `runs[]` e estatísticas por rodada. A
release verde não tem esse documento. Três caminhos, e o package tem de
**escolher e registrar** um:

1. **A release publica o manifesto do site como `date_product`.** É legal no
   contrato (um `date_product` é computado pelo publicador, não selado pelo
   ledger) e põe o documento sob o mesmo checksum e a mesma imutabilidade dos
   demais. Custo: alguém tem de computá-lo, e esse alguém é o montador da
   rodada, que ainda não existe.
2. **O site deriva o manifesto do `release.json`.** Sem produtor novo, mas o
   `release.json` não tem as estatísticas (`high`, `candidate`, `confirmed`,
   `area_ha`) — elas viriam de ler todos os geojson no navegador, o que é
   inviável com 429 mil feições.
3. **Um passo verde de preparação computa e publica o manifesto**, separado do
   montador da rodada.

A opção 1 parece certa e **não decida por essa frase**: verifique se as
estatísticas que o site mostra são todas derivávheis do que o ledger sela. Se
alguma não for, ela vem do geojson e a opção 1 exige que o publicador o leia —
o que muda o custo da decisão.

**Não invente um segundo produtor de ledger** em nenhum dos três caminhos.

## 6. Fronteiras duras

- A `main` do backend é **pull-request-only**, bypass vazio. Branch, PR, **sem
  merge**.
- **A `main` do site faz deploy de produção.** Qualquer mudança em
  `worker/index.js`, `wrangler.jsonc`, `public/` ou `src/` muda o que é
  implantado. Prove o que muda, pelo fecho dos imports e pelo conteúdo de
  `dist/`, como o 2B.4A fez.
- Produção congelada nas Fases 2B–5: nada de escrita em `araripe-cogs`, nada de
  tocar o Worker de produção, o domínio final, DNS, rotas, ponteiros canônicos,
  artefatos publicados atuais, ou os workflows azuis.
- **Exclusão de objeto real exige aprovação humana explícita e nomeada.** O
  código não sabe apagar; mantenha assim.
- Claude não recebe credencial de control-plane da Cloudflare. O único caminho é
  uma operação já allowlistada no broker; se não existir lá, **pare e faça
  handoff**.
- **Nunca nomeie um Environment que não existe.**
- Autonomia: desenvolvimento e branches locais, objetos em
  `araripe-v2-staging`, workflows verdes manuais com identidade de staging,
  verificações read-only, commits, pushes de branch e abrir PR seguem sem
  aprovação repetida. Qualquer coisa com autoridade ou efeito em produção
  espera.
- Preserve `claude/phase2b0-green-isolation`, `codex/technical-review-roadmap`,
  `claude/phase2a6d-mapbiomas`, `ci/promotion-identity-probe`,
  `claude/phase2b3-r2-separation` e as branches do 2B.4A.

## 7. Armadilhas já pagas — não redescobrir

- **Outra sessão pode estar no mesmo clone.** Existe um `stash@{0}` de outra
  sessão no backend. **Nunca `git stash` em árvore alheia**; adicione por nome,
  nunca `git add -A`.
- **O hook `commit-msg` recusa SHA estrangeiro.** Ver §3.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca dispare para testar.
- **ETag não é checksum** — multipart é MD5 dos MD5s com sufixo `-N`, observado
  no objeto azul real.
- **Não confie em invariante que o produtor não promete**: `content_type` é
  `{"type":"string","minLength":1}` no schema, e um CR nele parte a resposta.
- **Um teste pode passar pelo motivo errado.** No 2B.4A, "falha de leitura não é
  ausência" afirmava só o status, e as duas situações davam o mesmo status. Só a
  mutação revelou. **Ao escrever um teste, pergunte qual mutação ele derruba** —
  e se a resposta for "nenhuma", conserte o código, não o teste.
- **Ao testar script ou workflow, leia o que o shell EXECUTA, não o que ele
  documenta.** Uma varredura por `npx` pegou uma linha de comentário no 2B.4A.
- **`grep` desta máquina é `ugrep`**: `grep -qv` retorna 1 mesmo com linhas
  selecionadas. Capture a saída e teste se está vazia.
- **`cut` não está disponível no shell das ferramentas**; use Python para
  processar campos.

## 8. Ao final

Testes fail-closed e determinísticos: sem rede, sem relógio real, sem object
store. Reuse `tests/green_release_fixtures.py`, `tests/fake_object_store.py` e o
bucket falso de `tests/data_route.test.mjs`. Rode
`/opt/anaconda3/envs/araripe/bin/python -m pytest -q` no backend, e
`npm ci && npm run build && npm test && npm run test:worker` no site; reporte
falhas pré-existentes em separado. Commits por repositório, **nunca
misturados**, com base verificada. Crie
`docs/implementation/PHASE_2B4B_<data>.md`. Confirme árvore limpa — os untracked
`data/baselines_v2/`, `data/landcover/updated/` e `data/validation/` ficam
**fora**. Abra as PRs **sem mesclar**. Termine com o estado do gate P2B e com a
seção final obrigatória do método de handoff.

**Não inicie a Phase 3, a Phase 6 nem o replay 2026.**

## 9. Estado que este package herda

- **Package 2B.4A entregue como duas PRs**, backend e site, em 2026-09-07: a
  rota `/data/green/…`, os 19 vetores, a configuração verde isolada, o script de
  deploy pinado e a varredura de pinagem de actions.
- **Package 2B.3 MESCLADO** em 2026-09-07 (`ed6d9ce`, #44).
- **A Phase 2B.2 está inteira na `main`.** Package 2B.1 fechado e validado em
  produção. Package 2B.0 na `main`.
- **Environments do backend:** `cloudflare-green-control` (com revisor),
  `v2-staging` e `v2-promotion` (sem revisor, política `main`).
  `v2-staging-readonly` **não existe** — é ação do dono.
  **O repositório do site não tem Environment nenhum.**
- **Package 2A.6 fechado** em `claude/phase2a6d-mapbiomas`, não mesclado.
- **Nenhum produtor deposita `runs/<run-id>/`.** As rodadas de prova foram
  montadas à mão.
- **O Worker de staging não tem hostname**, e dar um não está no broker. É a
  capacidade nomeada em `GREEN_RETENTION_AND_MIGRATION.md` §5, e continua
  bloqueando a verificação no navegador.
- **Pendência com data: o token da NASA expira em 2026-11-06** e a chuva do site
  para de novo. A falha aparece no download — run vermelho, não congelamento
  silencioso.
- **Mesmo padrão suspeito no fallback do backend**, sem prazo: o passo "Run
  detection pipeline" do `update_data.yml` passa só usuário e senha do
  Earthdata, e não foi verificado se `run_detection.py` chega a fazer login.
  Pode ser que a correção certa seja **remover** as duas linhas.

## 10. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

**A etapa foi dividida em duas, e a primeira metade está pronta.** O sistema
agora tem o programa que entrega os dados pela rota nova — escrito, testado
contra a referência do backend, com a configuração de publicação isolada da de
produção e um script que se recusa a publicar no lugar errado.

Ficou para a segunda metade o que **depende de decisões que ainda não foram
tomadas**: tirar os arquivos grandes de alerta de dentro do repositório e passar
a publicá-los sozinho. Dois motivos, os dois concretos. Primeiro, é preciso
decidir quem passa a montar o índice que a página de alertas lê — o formato
antigo e o novo não são o mesmo, e escolher errado obriga a refazer. Segundo, o
repositório do site não tem onde guardar uma chave de acesso com proteção, e
criar esse lugar é uma ação sua.

Continua pendente, do mesmo jeito que antes, **testar a rota num navegador de
verdade**: o servidor de teste continua sem endereço.

### O que você precisa fazer

1. **Juntar as duas pull requests do 2B.4A** — uma no repositório do
   monitoramento, outra no do site. A do site dispara um deploy de produção,
   como todo commit do bot já faz duas vezes por semana; o que muda no site
   publicado é **nada**, e isso está provado por teste. Pode esperar.
2. **Decidir como dar um endereço temporário ao servidor de teste.** É a mesma
   pendência da etapa anterior e agora ela bloqueia a verificação visual de algo
   que já existe. Precisa de alguém com acesso ao painel da Cloudflare.
3. **Criar um "ambiente" protegido no repositório do site**, se quiser que a
   publicação automática de dados avance na próxima etapa. Hoje não existe
   nenhum, e sem ele a publicação sem robô não sai do papel.
4. **Anotar 6 de novembro:** a chave da NASA expira e a chuva para de novo.

### Tem algo preocupante?

**Não.** Nada quebrou, produção não foi tocada, e o site publicado continua
exatamente igual.

Vale registrar **um número**, que não é um problema hoje mas é o motivo da
próxima etapa existir: **o repositório do site carrega 255 MB de dados, e 247 MB
disso são arquivos de alerta** — 40 arquivos, o maior com quase 18 MB. Como o
histórico do git guarda tudo para sempre, isso cresce cerca de meio gigabyte por
ano e não encolhe apagando os arquivos. Não quebra nada agora; só fica mais caro
de carregar a cada semana.

E uma lição do dia que vale guardar: **um teste pode passar pelo motivo errado.**
Um dos testes que escrevi conferia que o sistema reagia certo a uma falha, mas a
resposta certa e a errada eram idênticas por fora — então ele teria passado de
qualquer jeito. Só descobri porque desligo cada proteção de propósito para ver
se algum teste reclama. Foi o programa que precisou ser corrigido, não o teste.

### O que ainda falta no caminho

- **2B.4B — a segunda metade:** decidir quem monta o índice de alertas, tirar os
  arquivos grandes do repositório, publicar sozinho sem robô, e travar as
  versões das ferramentas. É a próxima etapa.
- **A verificação no navegador**, assim que o servidor de teste tiver endereço.
- **Uma etapa própria para a memória de publicações**, que é o que permitirá um
  dia apagar versões antigas com segurança.
- **Phase 3 — congelar e ensaiar** o reprocessamento de 2026.
- **Phase 6 — a troca final:** o novo substitui o antigo, o site aponta para
  ele, o robô antigo é desligado, o endereço público de dados antigo é fechado,
  e a publicação passa a acontecer sozinha num horário.
- As duas provas que continuam faltando: **rodar com dados de uma execução real**
  e **montar a rodada automaticamente**, que hoje é feito por uma pessoa.
