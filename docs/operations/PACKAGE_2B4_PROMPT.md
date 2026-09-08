# Package 2B.4 — briefing de execução

Escrito em 2026-09-07, depois de fechar a implementação do Package 2B.3.

Segue o método em [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md)
versão 2: o corpo é para o agente executor, e a **seção final é para o dono**.

---

## 1. Dependência que precede tudo — confirme por conteúdo

O 2B.4 escreve o Worker que responde à rota `/data/green/…` e prepara o
artefato e o deploy verdes do site. Sem o 2B.3 não existe a política que esse
Worker implementa, nem os vetores contra os quais ele é conferido.

O Package 2B.3 foi entregue como PR **sem merge** em 2026-09-07. Confirme
**por conteúdo, nunca por ancestralidade** (os dois repositórios fazem squash):

    git show origin/main:src/publication/delivery_boundary.py | head -5
    git show origin/main:src/publication/retention.py | head -5
    git show origin/main:docs/contracts/phase2b/delivery_conformance_vectors.json | head -3
    git show origin/main:docs/contracts/phase2b/GREEN_DELIVERY_BOUNDARY_V1.md | head -3

Cuidado com `--grep`: ele busca a **mensagem inteira**, então um commit que
apenas *cita* a PR também casa. Filtre por `%s`:

    git log origin/main --format='%H %s' | grep '(#<número>)'

Gate medido na branch do 2B.3: **678 passed** (era 530 na base
`7c6bd0fc92a7d03a10e88298aaee550f5b7ee44d`). **Meça antes de editar** — este
número é um fato datado. Se o 2B.3 ainda não estiver na `main`, espere **678**
depois do merge e **530** antes.

    /opt/anaconda3/envs/araripe/bin/python -m pytest -q

Se `delivery_boundary.py` não estiver na `main`: **pare e pergunte.**

## 2. O que já foi verificado, para o executor não refazer

Tudo abaixo foi medido em 2026-09-07 com a ferramenta que produz o valor.
Detalhe completo em `docs/implementation/PHASE_2B3_2026-09-07.md`.

**a. A política de exposição já existe e é a autoridade.**
`src/publication/delivery_boundary.py` decide o que é público; o contrato é
`docs/contracts/phase2b/GREEN_DELIVERY_BOUNDARY_V1.md`. **Consuma; não
reimplemente a decisão.** O Worker é um adaptador: recebe um método e um
caminho, lê o ponteiro e o manifesto, e aplica o que os vetores dizem.

**b. Os 14 vetores de conformidade são a referência, não o Python.**
`docs/contracts/phase2b/delivery_conformance_vectors.json` traz um fixture e as
saídas exatas. Duas implementações de uma política divergem em silêncio; o
Worker que você escrever tem de passar nesse arquivo, e mudar a política sem
regenerar os vetores derruba o gate.

**c. Público é a release VIVA, nunca `releases/`.** Servir esse prefixo
publicaria `rel-g1-9f1ed344…` (promoção **recusada** por regressão de
cobertura) e `rel-g1-5ffad23a…` (revertida). As duas estão no bucket de
propósito. "Publicado" e "no ar" são estados diferentes.

**d. A chave nunca é montada a partir da requisição.** O caminho é procurado
numa allowlist construída do manifesto vivo. Não "sanitize" o caminho no
Worker: isso troca uma allowlist por um denylist e enfraquece a garantia.

**e. MEDIDO: `Object Read & Write` do R2 inclui DELETE.** Prova real em
`scripts/probe_readonly_identity.py --expect read-write`, run id
`local-2b3-measure-1`: o delete foi **aceito** (contra uma chave inexistente,
nada foi destruído). O escopo de token do R2 é **por bucket**, sem prefixo, e
o binding R2 do Worker também não tem modo somente-leitura nem prefixo. **O
limite é o código do Worker, e nada mais.**

**f. MEDIDO: o caminho público azul está no ar e é cross-origin.**
`https://pub-5eb389cffff54421916187be69dd659b.r2.dev/site-full/run-2026-08-30.geojson`
responde 200, `application/geo+json`, **14 429 260 bytes**, ETag
`"82d98a0bca9f8a9669fba81d824c79db-2"` (multipart — ETag não é checksum),
`Access-Control-Allow-Origin` só no GET com `Origin`, e **nenhum
`Cache-Control`**. O único consumidor é `site/src/js/alertas.js`, variável
`R2_ALERTS_BASE`.

**g. A `main` do site faz deploy do Worker de PRODUÇÃO.** O gatilho de produção
do Worker Builds está ativo em `observatorio-chapada`. Editar
`site/worker/index.js` e mesclar na `main` do site **é um deploy de produção**,
não de staging. O deploy de branch não-produção está inerte (`exit 0`) desde o
2B.0. Planeje o caminho verde antes de escrever a rota lá.

**h. O Worker de staging existe e não tem hostname.**
`observatorio-chapada-v2-staging` já tem o binding certo
(`STAGING_BUCKET` → `araripe-v2-staging`, mais `STAGING_LIMITER`), mas
`public_subdomain_enabled=false`, `custom_domain_count=0`, `route_count=0` — e
o `audit` do broker **afirma os três fail-closed**. Não existe endereço onde
testar. Dar um é mutação de control-plane **fora** da allowlist do broker
(`audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`), e
`enforce-worker-isolation` existe justamente para desligar esse subdomínio.
**Isto é a pendência número um deste package** — ver §5.

**i. Exposição de secret por passo já está varrida.**
`tests/test_secret_exposure.py` afirma: nenhum workflow verde expõe secret em
nível de workflow ou de job; um passo que roda script do repositório só exporta
nomes que aquele script lê; nenhum `run:` interpola secret; e os dois
identidades verdes nunca aparecem no mesmo passo. A metade azul **não** tem
essa propriedade e está **registrada**, não corrigida — azul é congelado.

**j. Nada foi apagado, e o código continua sem saber apagar.**
`ConditionalStore` não tem delete; `src/publication/retention.py` produz plano e
não executa. O dry-run revisado de 2026-09-07 sobre os 29 objetos reais deu
**26 retain, 3 review, 0 eligible**.

**k. Não existe histórico de promoção no armazenamento.** O ponteiro é um
objeto mutável sobrescrito a cada movimento e guarda **um** passo de contexto.
Consequência: "esta release já esteve no ar?" deixa de ser respondível uma
escrita depois. Por isso nenhuma release é elegível para exclusão. O histórico
write-once que resolveria isso está **especificado e não construído**
(`GREEN_RETENTION_AND_MIGRATION.md` §3) — **não é deste package** a menos que o
roadmap seja revisto.

## 3. A tarefa

> **NEXT SESSION MODEL: Opus 5 — EFFORT: max**
>
> Por quê: o 2B.4 escreve o primeiro código que **responde a requisições
> públicas** e prepara o primeiro **deploy** verde. O Worker é o único limite
> entre um binding com CRUD completo e a internet, e o repositório do site tem
> um gatilho que faz deploy de produção a partir da `main`. Errar aqui publica
> ou derruba, e as duas coisas são visíveis de fora.

Continue o Observatório da Chapada do Araripe com o **Package 2B.4 — artefato
do site, deploy e migração de dependências**.

**Orientação obrigatória antes de qualquer conclusão.** Siga a seção
"Establishing the real state" do `AGENTS.md` do workspace em **cada** repositório
afetado — este package toca os dois. Leia documento canônico com
`git show origin/main:<path>`, nunca da árvore de trabalho. Confirme o SHA de 40
caracteres da base com `git rev-parse origin/main` e **cole-o**; o hook
`commit-msg` rejeita SHA inexistente. Ative com
`git config core.hooksPath .githooks` nos dois repositórios.

**Base.** Crie `claude/phase2b4-site-artifact` a partir de `origin/main` em cada
repositório afetado, **depois** de confirmar §1.

**Leia integralmente antes de agir.** `AGENTS.md` e `CLAUDE.md` do workspace, do
backend e do site; o roadmap completo da branch de planejamento (Package 2B.4,
gate P2B, Phase 6); `GREEN_DELIVERY_BOUNDARY_V1.md` e seus vetores;
`GREEN_RETENTION_AND_MIGRATION.md`; `GREEN_LEAST_PRIVILEGE_IDENTITIES.md`;
`docs/implementation/PHASE_2B3_2026-09-07.md`; e a skill `araripe-safe-handoff`.

### Escopo do 2B.4

Os bullets do roadmap, na ordem em que se sustentam:

1. **Preparar o build/site verde para não commitar arquivos grandes de alerta
   no Git**, deixando o job azul inalterado.
2. **Manter fixtures pequenos e schemas** para desenvolvimento local e CI.
3. **Publicar dado de rotina automaticamente no R2 sem bot push nem PR de
   dados** no lado verde; desligar o bot azul é Phase 6.
4. **Fixar e roteirizar o deploy/validação/rollback isolados com Wrangler.**
5. **Reconciliar e travar os ambientes Python/Node** o bastante para reproduzir
   o replay científico e o deploy do site.
6. **Pinar as GitHub Actions dos workflows verdes** depois do inventário
   completo; não mexer na ativação de workflow azul antes da Phase 6.

E, herdado do 2B.3 e necessário para os bullets acima:

7. **Escrever o handler da rota `/data/green/…`** contra
   `delivery_conformance_vectors.json`, com um teste que roda os 14 casos
   contra o handler de verdade. **Não invente política nova**; se um caso
   faltar, acrescente ao gerador do backend e regenere.

**Fora de escopo, explicitamente:** o cutover, o desligamento do bot azul, o
desligamento do caminho público azul e qualquer coisa no domínio final são
**Phase 6**. O histórico de promoção e qualquer exclusão real são pacotes
próprios. O replay 2026 é **Phase 3**. Não comece nenhum.

## 4. Decisões de escopo já tomadas, com sua base

- **A política de exposição é do backend; o Worker é adaptador.** Os vetores
  são a referência entre os dois.
- **A rota verde é aditiva em `/data/green/`**, e o `/data/…` estático do site
  fica **intocado** — é o caminho antigo, e mantê-lo é o rollback.
- **Nada é apagado.** O `run.json` de um prefixo de rodada não é republicado por
  nenhuma release, e um plano só propõe exclusão com uma decisão nomeada.
- **Nenhuma release é elegível para exclusão** enquanto não existir histórico de
  promoção durável.
- **O ledger é público**, porque sem ele o manifesto não é verificável. Se algum
  dia ele carregar algo que não deve sair, essa é a linha a revisitar.

Se aparecer evidência contra qualquer uma, **pare e pergunte** em vez de trocar
por conta própria.

## 5. A capacidade que falta, e que provavelmente bloqueia metade do package

**O Worker de staging não tem endereço, e dar um não está no broker.**

Para verificar a rota ao vivo — CORS, content types, cache, checksums,
downloads e o modo de alerta completo no navegador, que é bullet do 2B.3 e
ficou aberto — é preciso um hostname para `observatorio-chapada-v2-staging`: um
subdomínio `workers.dev` ou uma rota de zona num hostname **não final**,
mantido aberto só durante a verificação, com as afirmações do `audit`
atualizadas enquanto estiver aberto e `enforce-worker-isolation` rodado depois
para fechar.

Isso é **mudança no broker mais uma mutação revisada**, e pelas regras não pode
ser autorada e despachada na mesma tarefa. Faça o handoff pela skill
`araripe-safe-handoff` em vez de substituir por `curl`, Wrangler, `gh api`,
outro workflow ou credencial mais ampla. **Todo o resto do package pode
avançar sem isso** — escreva o handler, os testes de conformidade, o artefato e
os scripts de deploy, e deixe a verificação ao vivo nomeada como pendente.

## 6. Fronteiras duras

- A `main` do backend é **pull-request-only**, com bypass vazio. Nunca push
  direto, nunca ator de bypass, nunca mexer em configuração do repositório para
  contornar. Trabalhe em branch, abra PR, **não faça merge**.
- **A `main` do site faz deploy de produção.** Uma PR mesclada lá altera o
  Worker `observatorio-chapada`. Trate qualquer mudança em `site/worker/` ou
  `wrangler.jsonc` como produção até provar o contrário.
- Produção segue congelada nas Fases 2B–5: nada de escrita em `araripe-cogs`,
  nada de tocar o Worker de produção, o domínio final, DNS, rotas, ponteiros
  canônicos, artefatos publicados atuais, ou os workflows azuis.
- **Exclusão de objeto real exige aprovação humana explícita e nomeada**, mesmo
  em staging. Dry-run revisado primeiro, sempre. Hoje o código nem sabe apagar;
  mantenha assim a menos que o roadmap peça o contrário.
- Claude não recebe credencial de control-plane da Cloudflare. O único caminho
  é uma operação já allowlistada em
  `.github/workflows/cloudflare_green_control.yml`; se não existir lá, **pare e
  faça handoff**. Não edite o broker e despache na mesma tarefa, e nunca aprove
  seu próprio Environment.
- **Não alargue a política de branch de nenhum Environment**, e **nunca nomeie
  um Environment que não existe** — o GitHub cria um, sem proteção nenhuma.
- Autonomia: desenvolvimento e branches locais, objetos em
  `araripe-v2-staging`, workflows verdes manuais com identidade de staging,
  verificações read-only, commits, pushes de branch e abrir PR seguem sem
  aprovação repetida. Qualquer coisa com autoridade ou efeito em produção
  espera.
- Preserve `claude/phase2b0-green-isolation`, `codex/technical-review-roadmap`,
  `claude/phase2a6d-mapbiomas`, `ci/promotion-identity-probe` e
  `claude/phase2b3-r2-separation`.

## 7. Armadilhas já pagas — não redescobrir

- **Outra sessão pode estar no mesmo clone.** **Nunca use `git stash` numa
  árvore com trabalho alheio** — existe um `stash@{0}` de outra sessão no clone
  do backend. Confira `git status` e `git rev-parse --abbrev-ref HEAD` antes de
  commitar, e adicione arquivos por nome, nunca `git add -A`.
- **`detect_gee.yml` não é idempotente**: um re-run reprocessa a janela de 16
  dias e infla `n_sightings`. Nunca dispare só para testar. O mesmo vale para
  `update_data.yml`, que além disso escreve em produção.
- **ETag não é checksum.** Multipart é MD5 dos MD5s com sufixo `-N`, observado
  no objeto azul real. Integridade é o `sha256` do manifesto.
- **Nunca afirme invariante que o produtor não promete** — e não confie numa
  também: `content_type` é `{"type":"string","minLength":1}` no schema, e um CR
  ou LF nele parte a resposta HTTP.
- **Não escreva ramo inalcançável.** Antes de acrescentar checagem fail-closed,
  ache o caminho por onde ela falha.
- **Prove por mutação.** O 2B.3 desligou 14 checagens novas, uma a uma, e
  confirmou que só o teste correspondente cai.
- **Colete todos os achados, não pare no primeiro** — `findings.py` dá o padrão.
- **Ao testar workflow, leia o que o shell executa, não o que ele imprime.**
- **`grep` desta máquina é `ugrep`**: `grep -qv` retorna 1 mesmo com linhas
  selecionadas. Capture a saída de `grep -v` e teste se está vazia.

## 8. Ao final

Testes fail-closed e determinísticos para cada item — sem rede, sem relógio
real, sem object store: injete cliente falso e relógio. Reuse
`tests/green_release_fixtures.py` e `tests/fake_object_store.py`. Rode
`/opt/anaconda3/envs/araripe/bin/python -m pytest -q` no backend e
`npm ci && npm run build` no site, e reporte falhas pré-existentes em separado.
Commits coerentes com base verificada em SHA de 40 caracteres copiado da
ferramenta, **por repositório, nunca misturados**. Crie
`docs/implementation/PHASE_2B4_<data>.md`. Confirme árvore limpa — os untracked
`data/baselines_v2/`, `data/landcover/updated/` e `data/validation/` são
artefatos pré-existentes do 2A.6 e ficam **fora** do commit. Abra as PRs **sem
mesclar**. Termine com o estado do gate P2B, dizendo explicitamente o que ainda
falta nele, e com a seção final obrigatória do método de handoff.

**Não inicie a Phase 3, a Phase 6 nem o replay 2026.**

## 9. Estado que este package herda

- **Package 2B.3 entregue como PR, não mesclada** em 2026-09-07: fronteira de
  exposição, rota `/data/green/…` com 14 vetores, política de retenção em
  dry-run, análise medida de menor privilégio, e a varredura de exposição de
  secret por passo. Gate **678 passed** (base 530).
- **Packages 2B.2A, 2B.2B e 2B.2C na `main`** (#33, #35, #39). A Phase 2B.2
  está inteira na `main`.
- **Package 2B.1 fechado e validado em produção.**
- **Package 2B.0 na `main`**: broker verde isolado, lanes verdes, Environments
  `v2-staging` e `cloudflare-green-control`.
- **Environments existentes:** `cloudflare-green-control` (com revisor),
  `v2-staging` e `v2-promotion` (sem revisor, política `main`).
  `v2-staging-readonly` **não existe** — é ação do dono, e o repositório
  deliberadamente não o nomeia.
- **Package 2A.6 fechado** em `claude/phase2a6d-mapbiomas`, **não mesclado** e
  não precisa ser.
- **Baseline `2.1.0`** existe localmente e não está publicada. `BASELINE_VERSION`
  em runtime segue `1.0.0`.
- **Nenhum produtor deposita `runs/<run-id>/` ainda.** As rodadas de prova foram
  montadas à mão. Automatizar a montagem não é deste package.
- **A cadeia de publicação foi provada ponta a ponta contra o R2 real** em
  2026-09-07: publicar, republicar sem duplicar, recusar cobertura antiga,
  supersede com tombstone, e reverter. Nenhuma PR no caminho do dado.
- **Pendência com data: o token da NASA expira em 2026-11-06** e a chuva do site
  para de novo. A falha aparece no download — run vermelho, não congelamento
  silencioso.
- **Mesmo padrão suspeito no fallback do backend**, sem prazo: o passo "Run
  detection pipeline" do `update_data.yml` passa só usuário e senha do
  Earthdata. Não foi verificado se `run_detection.py` chega a fazer login; pode
  ser que a correção certa seja **remover** as duas linhas. Não é deste package.

## 10. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

**Uma coisa, e ela não é falta de trabalho: não deu para testar a nova rota de
dados num navegador de verdade.**

O sistema novo agora sabe exatamente quais arquivos podem ser mostrados ao
público e quais não podem, e isso está escrito, testado e conferido contra o
armazenamento real. O que falta é ligar isso a um endereço na internet e abrir
no navegador — e o servidor de teste onde isso aconteceria **não tem endereço
nenhum**, de propósito, desde que foi criado. Dar um endereço a ele é uma
operação que a "caixa de ferramentas restrita" do projeto não oferece, e eu não
posso contorná-la. Está registrado como pendência com o passo exato.

Tudo o mais que a etapa pedia foi entregue: a separação entre o que é privado e
o que é público, a análise das chaves de acesso, a política de retenção com o
ensaio revisado, e a ordem segura da migração.

### O que você precisa fazer

1. **Juntar a pull request do Package 2B.3.** Não há nada de produção nela e
   nada para aprovar em nenhum painel. Pode esperar, mas o próximo package
   depende dela.
2. **Decidir se quer criar uma chave de acesso mais restrita** (só leitura) para
   um dos passos automáticos. É uma melhoria de segurança, não uma correção — o
   sistema funciona sem ela. O passo a passo está escrito. Pode esperar.
3. **Decidir como dar um endereço temporário ao servidor de teste**, porque sem
   isso a verificação no navegador não acontece nem agora nem no próximo
   package. Isso precisa de uma pessoa com acesso ao painel da Cloudflare.
   Não é urgente, mas é o que trava a parte visual.
4. **Anotar 6 de novembro:** a chave da NASA expira e a chuva do site para de
   novo. Dessa vez com aviso vermelho, não em silêncio.

### Tem algo preocupante?

**Não.** Nada quebrou, nada em produção foi tocado, e nada foi apagado — o
sistema continua sem saber apagar.

Vale registrar **uma descoberta**, que não é um problema hoje mas explica por
que fui conservador: **descobri, testando de verdade, que a chave que publica os
dados também consegue apagá-los.** A Cloudflare não oferece um nível de permissão
entre "só ler" e "ler, escrever e apagar", e não dá para limitar uma chave a uma
pasta dentro do balde. Ou seja: a proteção contra apagar coisa por engano não
pode vir da chave — tem que vir do programa. É exatamente por isso que o
programa continua sem nenhum comando de apagar, e por que a política de retenção
desta etapa só **propõe**, nunca executa.

E uma segunda, que muda a ordem das coisas mais adiante: **o armazenamento não
guarda memória de quais versões já estiveram no ar.** Ele lembra a versão atual
e um passo para trás, e só. Então "esta versão já esteve publicada?" deixa de
ter resposta assim que outra publicação acontece. Enquanto isso não for
resolvido, nenhuma versão de dados pode ser apagada — o que é a resposta certa,
não uma falha.

### O que ainda falta no caminho

- **2B.4 — o site novo:** escrever o programinha que entrega os dados pela nova
  rota, parar de guardar arquivos grandes de alerta dentro do repositório, e
  preparar a publicação do site num ambiente separado. É a próxima etapa.
- **A verificação no navegador**, assim que o servidor de teste tiver endereço.
- **Uma etapa própria para a memória de publicações**, que é o que permitirá,
  um dia, apagar versões antigas com segurança.
- **Phase 3 — congelar e ensaiar** o reprocessamento de 2026: escolher a data de
  corte e fotografar tudo antes de começar.
- **Phase 6 — a troca final:** o sistema novo substitui o antigo, o site aponta
  para ele, o robô antigo é desligado, o endereço público de dados antigo é
  fechado, e a publicação passa a acontecer sozinha num horário.
- Além das etapas, as duas provas que continuam faltando: **rodar com dados de
  uma execução real** e **montar a rodada automaticamente**, que hoje é feito
  por uma pessoa.
