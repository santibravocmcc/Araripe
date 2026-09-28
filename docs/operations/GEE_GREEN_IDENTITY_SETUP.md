# A identidade verde de Earth Engine — como o dono cria

**Escrito:** 2026-09-28, depois do desenho da lane de depósito
(`docs/implementation/PHASE_6E_2026-09-28.md` §1)
**Projeto do Google:** `ee-araripe`
**Onde a chave vai:** Environment `v2-staging` do repositório do backend
(**já existe** — não crie outro)
**Nome do segredo:** `GEE_GREEN_SA_KEY`

**Quem faz:** só o dono. Nenhum agente cria conta de serviço, cria chave ou
grava segredo. Nenhum agente deve receber, imprimir, copiar ou guardar o
arquivo da chave — **não cole o conteúdo dele em chat**, nem se um agente
pedir. Se isso acontecer, trate a chave como queimada e gere outra.

---

## Por que uma conta nova, e não a que já existe

O repositório já tem `GEE_SA_KEY`, a conta que a detecção antiga usa. Ela não
serve para a versão nova por três motivos, medidos no registro acima:

1. O papel que ela declara, *Earth Engine Resource Writer*, permite **apagar
   assets e criar exportações** — muito mais do que a detecção precisa.
2. Ela é a identidade do sistema em produção. Um workflow verde que a use
   deixa de ser verde, e cada execução passaria a precisar de aprovação.
3. Ela é um segredo de **repositório**: qualquer workflow de qualquer branch a
   lê. Um segredo do Environment `v2-staging` só é liberado para a `main`.

A conta nova fica no **mesmo projeto** `ee-araripe`: a cota é do projeto, não
da conta, e depois da virada a detecção nova **é** a detecção.

## Passo 1 — um papel com só o que a detecção usa

1. Abra **console.cloud.google.com**, selecione o projeto **`ee-araripe`**.
2. **IAM & Admin → Roles → Create role.** Se o console pedir para ativar a
   API de IAM, ative — é necessária para papéis customizados.
3. Título: `Araripe green detection`. ID: `araripeGreenDetection`.
4. **Add permissions**, e adicione exatamente estas três:
   - `earthengine.computations.create`
   - `earthengine.thumbnails.create`
   - `serviceusage.services.use`
5. Crie.

**Não** use *Earth Engine Resource Writer*, *Admin*, *Editor* nem *Owner*.
**Não** adicione nenhuma permissão `earthengine.assets.*` de escrita,
`earthengine.exports.*`, nem nada de `storage.*`.

Estas três são o desenho, não uma medição: a página de papéis do Google não
lista o conteúdo de cada papel predefinido de forma legível daqui. A primeira
coisa que a próxima sessão faz é um **probe** que prova duas coisas —
computar e baixar funcionam, **criar asset é recusado**. Se faltar uma
permissão de leitura, o probe diz qual, e o pedido volta a você com o nome
exato. Nunca a solução será "use o Writer".

## Passo 2 — a conta de serviço

1. **IAM & Admin → Service Accounts → Create service account.**
2. Nome: `araripe-green-detect`. Descrição: *detecção da versão nova; só
   computação, sem escrita de asset*.
3. Em **Grant this service account access to project**, escolha o papel
   **`Araripe green detection`** do passo 1 — e só ele.
4. Pule "Grant users access". Conclua.

## Passo 3 — a chave

1. Abra a conta `araripe-green-detect` → **Keys → Add key → Create new key →
   JSON**. O navegador baixa um arquivo `.json`.
2. Não mova o arquivo para dentro da pasta do projeto.

## Passo 4 — o segredo no GitHub

1. GitHub → repositório **`Araripe`** → **Settings → Environments →
   `v2-staging`**.
2. **Environment secrets → Add environment secret.**
3. Nome: **`GEE_GREEN_SA_KEY`**. Valor: o conteúdo inteiro do arquivo `.json`.
4. Salve. **Apague o arquivo `.json`** do computador (e da lixeira).

**Não** altere a política de branch do `v2-staging` (continua só `main`) e
**não** adicione revisor — as duas coisas estão certas como estão.
**Não** crie um segredo de repositório; tem de ser do Environment.

## Como saber que deu certo

Você não precisa conferir nada. A próxima sessão confere pela API do GitHub
que o segredo `GEE_GREEN_SA_KEY` existe em `v2-staging` (o valor nunca é
legível, e isso é o desenho) e roda o probe. O resultado vai no registro dela.
