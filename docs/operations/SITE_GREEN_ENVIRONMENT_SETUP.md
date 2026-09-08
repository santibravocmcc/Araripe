# O Environment verde do repositório do site — como o dono cria

**Escrito:** 2026-09-07, depois do Package 2B.4A
**Conta Cloudflare:** `9416750169311ee4afc18a8ff3c771d4`
**Repositório:** `santibravocmcc/observatorio-site`
**Environments existentes hoje:** **nenhum** (`gh api … /environments` → `[]`,
medido em 2026-09-07)

**Quem faz:** só o dono. Nenhum agente cria credencial, cria Environment ou
aprova o próprio Environment. Nenhum agente deve receber, imprimir, copiar ou
guardar estes valores.

---

## 1. Leia isto antes de criar qualquer coisa: o token não é como os do backend

Os Environments do backend (`v2-staging`, `v2-promotion`) guardam chaves R2
**escopadas a um bucket**. Se vazarem, alcançam só `araripe-v2-staging`, que é
descartável. É por isso que eles não têm revisor obrigatório.

**O Environment do site é diferente em natureza, não em grau.** O que ele
precisa fazer é **implantar um Worker**, e permissão de Workers na Cloudflare é
**de nível de conta** — não existe escopo "só este script". O próprio
`CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md` registrou isso em 2026-08-11:

> Cloudflare Workers permissions are account-scoped rather than safely limited
> to one existing Worker.

E a referência de permissões da Cloudflare confirma: permissões de conta têm
escopo `com.cloudflare.api.account`
(<https://developers.cloudflare.com/fundamentals/api/reference/permissions/>).

**Consequência que decide tudo abaixo:** um token capaz de implantar
`observatorio-chapada-v2-staging` é capaz de implantar
`observatorio-chapada` — o Worker de **produção**, ligado ao domínio final.
Nenhuma configuração muda isso.

Por isso, e ao contrário dos Environments do backend:

> **Este Environment tem revisor humano obrigatório.** O revisor *é* a proteção,
> porque o token não pode ser estreitado.

## 2. Decisão que o dono deve tomar primeiro

Há dois desenhos possíveis, e vale escolher antes de clicar em nada.

**Opção A — o Environment vive no repositório do site.**
Mais simples: o workflow verde do site constrói e implanta num só lugar.
O custo é que um token com poder de produção passa a existir no repositório que
qualquer PR do site pode tentar alcançar. As mitigações são o revisor
obrigatório e a política de branch `main`.

**Opção B — o deploy verde passa pelo backend.**
O backend já tem o padrão provado: o broker
`cloudflare_green_control.yml` com o Environment `cloudflare-green-control`,
revisor obrigatório, lista fixa de operações e nenhum input que carregue nome de
recurso. Acrescentar uma operação `deploy-green-worker` a ele reusa a proteção
que já existe, e o site publicaria só o artefato de build.
O custo é mais peças: o artefato tem de viajar entre repositórios.

**Recomendação: opção A com revisor obrigatório**, porque a proteção real é o
revisor nos dois casos, e a opção B acrescenta um mecanismo novo para obter a
mesma garantia. Mas registre a escolha — o Package 2B.4B vai construir sobre
ela, e trocar depois custa retrabalho.

O resto deste documento assume a **opção A**.

## 3. Passo 1 — criar o token na Cloudflare

1. Cloudflare → ícone do perfil → **API Tokens** → **Create Token** →
   **Create Custom Token**.
   (Não é o menu de tokens do R2: aquele só cria chaves S3, que não implantam
   Worker.)
2. Nome: `araripe-green-worker-deploy`.
3. Permissões, e **apenas estas**:

   | Tipo | Recurso | Nível |
   | --- | --- | --- |
   | Account | **Workers Scripts** | **Edit** |
   | Account | **Workers R2 Storage** | **Read** |

   A segunda é necessária porque o deploy resolve o binding R2 e falha sem ela.
   **Não** adicione Zone, DNS, Workers Routes, Workers KV, Account Settings, nem
   `Workers R2 Storage: Edit`.
4. **Account Resources:** *Include* → apenas a conta
   `9416750169311ee4afc18a8ff3c771d4`.
5. **Zone Resources:** deixe **vazio**. Sem zona, o token não consegue criar
   rota nem encostar no domínio final — é a única restrição real disponível, e
   ela vale.
6. **TTL:** ponha uma data de expiração. Um ano é razoável; "nunca" não é.
7. Crie e copie o valor **uma vez**.

**Não** cole esse valor em chat, em arquivo de repositório, no `AGENTS.md`, no
`CLAUDE.md` ou num `.env`.

## 4. Passo 2 — criar o Environment no GitHub

Em **Settings → Environments → New environment**, no repositório
`observatorio-site`, nome exatamente **`green-deploy`**.

**Secrets** (Environment secrets, não repository secrets):

| Nome | Valor |
| --- | --- |
| `CLOUDFLARE_API_TOKEN` | o token do passo 1 |

**Variables:**

| Nome | Valor |
| --- | --- |
| `CLOUDFLARE_ACCOUNT_ID` | `9416750169311ee4afc18a8ff3c771d4` |
| `GREEN_WORKER_NAME` | `observatorio-chapada-v2-staging` |

`GREEN_WORKER_NAME` existe para o workflow poder recusar antes de invocar o
wrangler, do mesmo jeito que `scripts/green_worker.sh` já faz localmente e que
`assert_staging_target` faz no backend: a checagem é sobre o **alvo**, não sobre
a credencial.

**Deployment branches:** *Selected branches* → apenas **`main`**.
Mesmo motivo dos Environments do backend: uma branch de feature não deve
alcançar credencial. Aqui o motivo é mais forte, porque esta credencial alcança
produção.

**Required reviewers:** **você**. Isto é o oposto da decisão tomada para
`v2-promotion`, e a diferença é a do §1: aquele token alcança um bucket
descartável, este alcança o Worker de produção.

## 5. Passo 3 — verificar, sem imprimir segredo

    gh api repos/santibravocmcc/observatorio-site/environments \
      --jq '[.environments[].name]'
    gh api repos/santibravocmcc/observatorio-site/environments/green-deploy \
      --jq '{name, rules: [.protection_rules[].type]}'
    gh api repos/santibravocmcc/observatorio-site/environments/green-deploy/deployment-branch-policies \
      --jq '[.branch_policies[] | "\(.type): \(.name)"]'
    gh api repos/santibravocmcc/observatorio-site/environments/green-deploy/secrets \
      --jq '[.secrets[].name]'
    gh api repos/santibravocmcc/observatorio-site/environments/green-deploy/variables \
      --jq '[.variables[] | "\(.name)=\(.value)"]'

O esperado: `rules` contendo **`required_reviewers`** e `branch_policy`; a
política com só `branch: main`; o secret `CLOUDFLARE_API_TOKEN`; e os dois
variables. **Valor de secret nunca é legível pela API — isso é o desenho, não um
problema.**

## 6. Passo 4 — e então prove o escopo, porque configuração não prova nada

Esta é a lição que custou uma rodada em 2026-09-07: a primeira chave de promoção
tinha o Environment **perfeito** — nomes de secret certos, política de branch
certa, variables certos — e alcançava o bucket de **produção**. O escopo que
importava vivia na Cloudflare e é invisível do lado do GitHub
(`GREEN_PROOFS_2026-09-07.md` §2).

> **Escopo de credencial só se prova com uma chamada real que precisa ser
> recusada.**

Para este token, as recusas que importam são **duas**, e nenhuma delas é
"consegue implantar o Worker verde" — essa é a que deve **funcionar**:

| Checagem | Condição de aprovação |
| --- | --- |
| listar os Workers da conta | **sucesso** — o token funciona |
| ler o bucket `araripe-v2-staging` | **sucesso** — o binding resolve |
| criar uma **rota de zona** | **recusado** — sem Zone Resources |
| **escrever** em `araripe-cogs` | **recusado** — só `R2 Storage: Read` |

A terceira e a quarta são checagens **invertidas**: o sucesso delas é a falha da
prova. E note o que **não** dá para provar por recusa: que o token não implanta
`observatorio-chapada`. Ele implanta. Não há chamada que recuse isso, porque a
permissão é de conta. **É por isso que o revisor é obrigatório** — a prova de
escopo termina aqui, e o resto é processo.

**Não existe script para isso ainda**, e escrevê-lo é trabalho do Package
2B.4B, junto com o workflow que usa o Environment. O padrão a seguir é
`scripts/probe_promotion_identity.py` e `scripts/probe_readonly_identity.py`: a
recusa é a condição de aprovação, e a polaridade é afirmada nas duas direções
num teste, para que uma edição futura não transforme silenciosamente uma recusa
em aprovação.

## 7. O que NÃO fazer

- **Não nomeie `green-deploy` em nenhum workflow antes de criá-lo.** O GitHub
  não falha com um Environment desconhecido — ele **cria** um, *"with no
  protection rules or secrets configured"*
  (<https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments>).
  Um erro de digitação fabrica um Environment sem política de branch nenhuma, o
  que é mudança de configuração de repositório e é justamente a errada. O
  Package 2B.2C esperou o `v2-promotion` existir por esta razão, e o 2B.4B deve
  esperar este.
- **Não dê `Workers R2 Storage: Edit`.** O deploy só precisa resolver o binding.
  Escrita ali seria acesso a `araripe-cogs` de escrita, e a medição do Package
  2B.3 é que no R2 escrita **inclui apagar**.
- **Não adicione Zone Resources.** É o que impede o token de criar rota e de
  encostar no domínio final — a única restrição real que este token admite.
- **Não reuse este token para nada.** Para um propósito novo, um token novo.
- **Não remova o revisor** "porque atrasa o CI". A automação que o Package 2B.2C
  buscava é a da **publicação de dado**, que não passa por aqui: o dado verde é
  publicado pelo backend direto no R2, sem PR e sem revisor. Deploy de Worker é
  outra coisa, e é raro.

## 8. Revogação

Revogue `araripe-green-worker-deploy` se ele puder ter sido exposto, ao fim do
desenvolvimento isolado da Phase 2B, ou antes do cutover da Phase 6 — quando o
desenho de quem implanta o quê deve ser reconsiderado inteiro, junto com a
decisão de "sem revisor" do `v2-promotion`.

## 9. Referências

- Criar API token: <https://developers.cloudflare.com/fundamentals/api/get-started/create-token/>
- Escopo das permissões: <https://developers.cloudflare.com/fundamentals/api/reference/permissions/>
- Restringir uso de token (IP, TTL): <https://developers.cloudflare.com/fundamentals/api/how-to/restrict-tokens/>
- Environments do GitHub: <https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments>
- O padrão equivalente no backend: [`PROMOTION_IDENTITY_SETUP.md`](PROMOTION_IDENTITY_SETUP.md)
- Por que o escopo se prova por recusa: [`GREEN_PROOFS_2026-09-07.md`](GREEN_PROOFS_2026-09-07.md) §2
  e [`GREEN_LEAST_PRIVILEGE_IDENTITIES.md`](GREEN_LEAST_PRIVILEGE_IDENTITIES.md)
