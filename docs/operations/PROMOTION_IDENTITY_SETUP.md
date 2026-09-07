# A identidade de promoção verde — como o dono cria

**Escrito:** 2026-09-07, depois do Package 2B.2B
**Conta Cloudflare:** `9416750169311ee4afc18a8ff3c771d4`
**Único bucket aprovado:** `araripe-v2-staging`
**Environment do GitHub a criar:** `v2-promotion`

`CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md` já previa este passo: *"Promotion will
use a different protected identity after the publication contract is
implemented."* O contrato de publicação está implementado (Package 2B.2B,
`docs/contracts/phase2b/GREEN_RELEASE_CONTRACT_V1.md`), então é agora.

**Quem faz:** só o dono. Nenhum agente pode criar credencial, criar Environment
ou aprovar o próprio Environment. Nenhum agente deve receber, imprimir, copiar
ou guardar estes valores.

---

## Por que uma chave nova, e não a que já existe

Já existe uma identidade de staging no Environment `v2-staging`
(`R2_STAGING_ACCESS_KEY_ID` / `R2_STAGING_SECRET_ACCESS_KEY`). Ela é a
identidade da **lane 2**, a das rodadas candidatas, que escreve só em prefixos
imutáveis por rodada e **nunca move ponteiro**.

A promoção é a **lane 3** e é a única coisa no desenho que escreve num objeto
**mutável** — `pointers/green/current.json`, o objeto que diz qual release está
no ar. `docs/operations/GREEN_CONCURRENCY_LANES.md` separa as duas desde o
Package 2B.0, e o próprio comentário do workflow de promoção dizia que a lógica
real usaria *"a different protected identity — never the green candidate
identity"*.

O motivo prático: se as duas lanes usassem a mesma chave, qualquer rodada
candidata poderia mover o ponteiro. Separar é o que faz "publicar" e "promover"
serem duas autoridades diferentes.

## Passo 1 — criar o token no Cloudflare

1. Abra **Cloudflare → Storage & databases → R2 → Overview → API Tokens →
   Manage**.
2. **Create Account API token** (se não houver, um User API token).
3. Nome: `araripe-green-promotion-rw`.
4. Permissão: **Object Read & Write**.
5. **Apply to specific buckets only** → escolha exatamente
   `araripe-v2-staging`.
6. Crie e copie o **Access Key ID** e o **Secret Access Key** — o secret
   aparece **uma vez só**.

**Não** selecione Admin Read & Write, nem "all buckets", nem Workers Scripts,
nem DNS, nem Zone. **Não** cole nenhum dos dois valores em chat, em arquivo do
repositório, no `AGENTS.md`, no `CLAUDE.md` ou num `.env`.

Nota sobre `Object Read & Write`: o R2 não oferece granularidade menor, então
esse nível também permite apagar objetos **dentro daquele bucket**. Isso é
aceitável porque o limite real é o código, não o token: `ConditionalStore` não
tem operação de delete nem escrita incondicional, e cada release vive num
prefixo imutável. Retenção e exclusão são do Package 2B.3.

## Passo 2 — criar o Environment no GitHub

Em **Settings → Environments → New environment**, nome exatamente
**`v2-promotion`**.

**Secrets** (Environment secrets, não repository secrets):

| Nome | Valor |
| --- | --- |
| `R2_PROMOTION_ACCESS_KEY_ID` | o Access Key ID do passo 1 |
| `R2_PROMOTION_SECRET_ACCESS_KEY` | o Secret Access Key do passo 1 |

**Variables** — os mesmos três que o `v2-staging` já tem, porque a guarda de
alvo do código compara com eles antes de tocar em qualquer objeto:

| Nome | Valor |
| --- | --- |
| `R2_STAGING_BUCKET` | `araripe-v2-staging` |
| `R2_ENDPOINT_URL` | `https://9416750169311ee4afc18a8ff3c771d4.r2.cloudflarestorage.com` |
| `AWS_REGION` | `auto` |

**Deployment branches:** *Selected branches* → apenas `main`. Mesmo motivo do
`v2-staging`: uma branch de feature não deve alcançar uma credencial.

**Required reviewers:** **nenhum** — mas essa é uma decisão do dono, e a base
dela está registrada abaixo.

### Por que sem revisor, e quando isso deve ser revisto

Sem revisor porque:

- o token alcança **só** o bucket descartável de staging, exatamente como o
  `v2-staging`, que também não tem revisor, e a política de risco do Package
  2B.0 já trata "manual green workflows holding only staging-scoped
  credentials" como autônomo;
- o objetivo do Package 2B.2C é literalmente *"keep operational data
  publication automatic without PRs or manual merges"*. Um revisor obrigatório
  em cada publicação agendada anularia o próprio pacote;
- antes do Phase 6 **nenhum consumidor público segue esse ponteiro**, e existe
  `rollback` provado.

O `cloudflare-green-control` continua com revisor humano obrigatório e isso não
muda: o token dele edita em nível de conta.

**Revisar esta decisão quando o Phase 6 se aproximar.** No cutover o ponteiro
verde passa a ser o que o site público segue, e aí a conta de um erro deixa de
ser um sandbox.

## Passo 3 — verificar sem imprimir segredo

Depois de criar, confira só nomes e políticas:

```bash
gh api repos/santibravocmcc/Araripe/environments/v2-promotion \
  --jq '{name, rules: [.protection_rules[].type]}'
gh api repos/santibravocmcc/Araripe/environments/v2-promotion/deployment-branch-policies \
  --jq '[.branch_policies[] | "\(.type): \(.name)"]'
gh api repos/santibravocmcc/Araripe/environments/v2-promotion/secrets --jq '[.secrets[].name]'
gh api repos/santibravocmcc/Araripe/environments/v2-promotion/variables \
  --jq '[.variables[] | "\(.name)=\(.value)"]'
```

O esperado: `rules` com `branch_policy` e **sem** `required_reviewers`; a
política com só `branch: main`; os dois nomes de secret acima; e os três
variables. **Valores de secret nunca são legíveis pela API — isso é esperado, e
é o desenho.**

A primeira prova de verdade contra objeto real só é possível a partir da `main`,
porque a política de branch é `main`. Ela **não** faz parte do Package 2B.2C:
é um passo separado, depois de o 2B.2C estar mesclado.

## Passo 4 — o que o código espera

Nada mais precisa ser configurado. O caminho já está escrito e testado:

- `scripts/publish_green_release.py` lê `R2_PROMOTION_ACCESS_KEY_ID`,
  `R2_PROMOTION_SECRET_ACCESS_KEY`, `R2_STAGING_BUCKET` e `R2_ENDPOINT_URL` do
  ambiente, e **recusa `araripe-cogs` pelo nome antes de ler credencial**;
- `.github/workflows/v2_promotion_lane.yml` hoje não declara Environment
  nenhum e para nos modos `promote`/`rollback` nomeando o que falta. Ligar o
  Environment `v2-promotion` nele é trabalho do Package 2B.2C, não do dono.

## Revogação

Revogue `araripe-green-promotion-rw` se ele puder ter sido exposto, ao fim do
desenvolvimento isolado da Phase 2B, ou antes de reaproveitar o bucket. **Nunca
amplie o escopo dele** — para um propósito novo, crie um token novo.

## Referências

- Tokens do R2: <https://developers.cloudflare.com/r2/api/tokens/>
- Autenticação S3 no R2: <https://developers.cloudflare.com/r2/get-started/s3/>
- Environments do GitHub:
  <https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments>
