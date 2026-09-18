# Os dois portões que faltam — passo a passo para o dono

**Escrito:** 2026-09-18, a pedido do dono, depois de as seis decisões serem
tomadas e a revisão pré-cutover fechar.
**Base verificada:** backend `origin/main` em
`9e1279e64edf5019c2a45f995820bb4e06d8ccca`, site `origin/main` em `6f11076`.

Cada passo abaixo foi lido do código, do workflow ou da documentação da
Cloudflare — **nenhum clique foi escrito de memória**. Onde eu não pude
verificar, está dito.

---

> ## ⚠️ ANTES DE TUDO: a mudança do broker NÃO é necessária
>
> O senhor pediu o passo a passo de *"abrir o subdomínio quando a mudança do
> broker estiver revisada"*. **Não há mudança de broker a fazer, e é melhor
> assim.** Medido em `scripts/cloudflare_green_control.py`:
>
> - `ALLOWED_OPERATIONS` é exatamente `audit`, `enforce-worker-isolation`,
>   `disable-site-branch-deploy`. **Nenhuma abre** o subdomínio — as três
>   conferem ou fecham;
> - as três existentes **reduzem** exposição. Uma operação que a *aumenta* é
>   mudança de categoria no broker, não mais uma linha na lista;
> - e `enforce-worker-isolation` **já** faz exatamente o fechamento de que
>   precisamos: ele posta `{"enabled": false, "previews_enabled": false}` e só
>   então audita.
>
> Então o caminho é: **o senhor abre no painel** (4 cliques, sem token, sem
> código, sem PR), eu verifico, e **o broker fecha**. Isso remove uma tarefa
> inteira do caminho crítico — autoria, revisão humana, merge e um disparo em
> tarefa separada — e não amplia a autoridade de control-plane de nenhum agente.
>
> **Eu recomendo não acrescentar a operação ao broker.** Se algum dia o
> subdomínio precisar ser aberto repetidamente, revisitamos; para uma
> verificação única, o painel é a ferramenta certa.

---

# Tarefa A — o Environment protegido no repositório do site (portão 3)

**O que é:** um lugar protegido, no repositório do site, para guardar o token
que implanta o Worker verde.

**Por que precisa de revisor obrigatório, e isto é medido:** no Cloudflare a
permissão de Workers é de **conta**, não de Worker. Quem consegue implantar o
Worker verde consegue implantar o de produção. Não existe escopo por Worker.

**Estado medido hoje:** `gh api repos/santibravocmcc/observatorio-site/environments`
devolve **`[]`** — nenhum Environment existe. A lane que o consome
(`site/.github/workflows/green_site_publish.yml`) **não nomeia nenhum**, de
propósito: nomear um inexistente faria o GitHub criá-lo *"with no protection
rules or secrets configured"*.

## A.1 — Criar o token na Cloudflare

1. Painel da Cloudflare → **My Profile** → **API Tokens** → **Create Token** →
   **Create Custom Token**.
2. Nome: `araripe-green-worker-deploy`.
3. Permissão: **Account** → **Workers Scripts** → **Edit**.
   - **Só essa.** Não marque Zone, DNS, R2 Admin, nem "All accounts".
   - O binding de R2 do Worker verde é **declarativo** — ele vive na
     configuração, e o deploy não precisa de permissão de R2 para declará-lo.
4. Account Resources: **Include** → apenas a conta
   `9416750169311ee4afc18a8ff3c771d4`.
5. Criar, e **copiar o valor uma vez**.

**Este token nunca vem para mim.** Não o cole no chat, em arquivo do
repositório, em `CLAUDE.md`, em `AGENTS.md` nem em configuração do Claude. Ele
vai direto do painel da Cloudflare para o campo de segredo do GitHub.

> **Por que este token é mais perigoso que o de R2 que eu tenho:** o meu alcança
> objetos de um bucket. Este alcança **qualquer Worker da conta**, incluindo
> `observatorio-chapada`, que é o site público. É a razão inteira do revisor.

## A.2 — Criar o Environment no GitHub

No repositório `santibravocmcc/observatorio-site`:

1. **Settings** → **Environments** → **New environment**.
2. Nome: **`v2-green-deploy`**.
   - Este nome exato importa: eu vou acrescentar `environment: v2-green-deploy`
     ao workflow numa PR, e nomear um Environment que não existe cria um sem
     proteção. **Se o senhor usar outro nome, me diga qual** — eu não escrevo o
     nome antes de ele existir.
   - Ele segue a convenção do backend (`v2-staging`, `v2-promotion`).
3. Em **Deployment protection rules**:
   - marcar **Required reviewers** e adicionar **você mesmo**;
   - deixar **Wait timer** em 0.
4. Em **Deployment branches and tags**: **Selected branches and tags** → regra
   **`main`**.
   - Igual aos três do backend, que têm todos política `main` só — conferido por
     `gh api` em 2026-09-18.
5. Em **Environment secrets** → **Add secret**:
   - nome **`CLOUDFLARE_API_TOKEN`**, valor = o token do passo A.1.
6. Em **Environment variables** → **Add variable**:
   - nome **`CLOUDFLARE_ACCOUNT_ID`**, valor `9416750169311ee4afc18a8ff3c771d4`.
   - É **variável** e não segredo de propósito: esse identificador já está em
     texto claro no repositório (`src/publication/conditional_store.py`), e
     tratá-lo como segredo daria uma falsa sensação de proteção.

## A.3 — Conferir sem imprimir segredo

    gh api repos/santibravocmcc/observatorio-site/environments \
      --jq '.environments[] | {name, rules: [.protection_rules[].type]}'

Tem de sair `v2-green-deploy` com `branch_policy` **e** `required_reviewers`.
Me mande essa saída e eu abro a PR que liga a lane ao Environment.

**Não rode nada da lane ainda.** Ela é `workflow_dispatch` só, e o job de
publicação hoje recusa nomeando as duas capacidades que faltam.

---

# Tarefa B — o hostname do Worker verde (portão 2)

**O que é:** um endereço alcançável para `observatorio-chapada-v2-staging`,
aberto **só pela duração da verificação** e fechado depois.

## B.0 — O pré-requisito que não estava explícito: o Worker tem de ter o código

O código da rota existe no repositório (`site/worker/green.js`), mas o
`wrangler.green.jsonc` registra que **o Worker implantado hoje é um placeholder
do Package 2B.0** e que *"o primeiro deploy verde o substitui inteiro"*.

**Eu não verifiquei o estado implantado** — isso exige credencial de
control-plane, que eu não tenho. Se o placeholder ainda estiver lá, abrir o
subdomínio dá um endereço que responde 404 em tudo, e a verificação não mede
nada.

Então **o deploy vem antes do hostname**. Dois caminhos:

**(1) Pela lane, depois da Tarefa A** — o caminho durável, com trilha de
auditoria e o seu revisor no meio.

**(2) Do seu computador, uma vez** — mais rápido para desbloquear a
verificação:

    cd <repo do site>
    export CLOUDFLARE_API_TOKEN=…            # o token do passo A.1
    export CLOUDFLARE_ACCOUNT_ID=9416750169311ee4afc18a8ff3c771d4
    scripts/green_worker.sh dry-run
    scripts/green_worker.sh deploy GREEN-ONLY

O script tem as guardas: ele recusa qualquer alvo que não seja
`observatorio-chapada-v2-staging` **antes** de invocar o wrangler, pina o
wrangler em `4.129.1`, e passa `--config wrangler.green.jsonc` em toda
invocação. Um `wrangler deploy` sem `--config` leria `wrangler.jsonc`, que é o
Worker de **produção** — é essa a razão de o script existir.

Recomendo **(1)** se o senhor não tem pressa de horas, e **(2)** se tem. Os dois
usam o mesmo token.

## B.1 — Abrir o subdomínio, no painel

**Nesta ordem, e a ordem não é preferência.** `wrangler.green.jsonc` declara
`"workers_dev": false`, e a documentação da Cloudflare é explícita: um deploy
com esse campo **desliga** a rota `workers.dev`. Abrir antes de implantar
desperdiça o passo.

1. Painel → **Workers & Pages**.
2. Em **Overview**, selecione **`observatorio-chapada-v2-staging`**.
3. **Settings** → **Domains & Routes**.
4. Em `workers.dev`, clique **Enable** e confirme.
5. **Deixe Preview URLs desligado.** Eles são um endereço separado
   (`<preview>-<worker>.<subdominio>.workers.dev`) e não precisamos deles.
6. Copie o hostname que aparecer —
   `observatorio-chapada-v2-staging.<seu-subdominio>.workers.dev` — e me mande.

## B.2 — O que fica quebrado enquanto está aberto, e é de propósito

`audit()` exige `subdomain == {"enabled": False, "previews_enabled": False}`.
Com o subdomínio aberto:

| operação do broker | o que acontece |
| --- | --- |
| `audit` | **falha**, dizendo `staging public subdomain is not disabled`. Esperado: é a isolação reportando o estado real |
| `enforce-worker-isolation` | **funciona** — ele fecha primeiro e audita depois, então converge |
| `disable-site-branch-deploy` | **não rode.** Ele faz o `PATCH` e **só então** audita: a mutação entra e a execução reporta falha. Ficaria parecendo que não funcionou |

Isso não é defeito a consertar agora — é o motivo de a janela ser curta.

## B.3 — Eu verifico

Com o hostname, eu rodo as checagens que só uma rede real responde:
`Content-Length` e `sha256` de um produto contra o manifesto; `Cache-Control:
no-store` no ponteiro; **ausência** de `Access-Control-Allow-Origin` em toda
resposta; a visão completa de alertas (~13,8 MiB) renderizando pela rota; e
`?download=1` nomeando o arquivo pelo caminho declarado.

As 29/29 checagens de conformidade já passaram sem rede, contra a simulação
local do R2 no `wrangler dev`. O que só a rede prova é a identidade de bytes
contra a release **real** e o comportamento da borda.

## B.4 — Fechar, pelo broker

No repositório **backend**, Actions → **restricted Cloudflare green control** →
**Run workflow**:

- branch: **`main`** (o workflow recusa qualquer outra);
- `operation`: **`enforce-worker-isolation`**;
- `confirmation`: **`GREEN-ONLY`**, exatamente.

O Environment `cloudflare-green-control` tem revisor humano obrigatório, então a
execução **para e espera a sua aprovação**. Aprove-a você — eu não aprovo
requisição de Environment, nem a minha nem nenhuma.

## B.5 — Confirmar que fechou

Mesmo workflow, `operation`: **`audit`**, `confirmation` **em branco**. Tem de
sair verde, com `public_subdomain_enabled: false`, `custom_domain_count: 0`,
`route_count: 0`.

**Se o `audit` sair verde, a janela fechou.** Se sair vermelho no subdomínio, o
fechamento não pegou — me diga antes de qualquer outra coisa.

---

## O que NÃO fazer em nenhum dos dois

- **não abra rota de zona nem domínio customizado** para o Worker verde. O
  domínio final é de produção, e a auditoria afirma `custom_domain_count == 0`;
- **não mude `workers_dev` nem `preview_urls`** no `wrangler.green.jsonc`.
  `tests/test_green_worker_config.py` amarra os dois campos às afirmações da
  auditoria, e mudá-los quebraria a prova de isolação junto;
- **não dispare `detect_gee.yml` nem `update_data.yml`.** Não são idempotentes e
  escrevem em produção;
- **não revogue `claude-araripe-v2-staging-rw` ainda.** É o último passo da D1,
  depois de a D5 estar construída e reprovada;
- **não mescle a PR draft `#21` do site** antes da troca do consumidor.

## A ordem completa, numa linha

Tarefa A (Environment) → deploy verde → B.1 (abrir no painel) → B.3 (eu
verifico) → B.4 (fechar pelo broker) → B.5 (confirmar) → e só então a troca do
consumidor em `alertas.js`, que é o §4.4 e tem a sua própria aprovação.
