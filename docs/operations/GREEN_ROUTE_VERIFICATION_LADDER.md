# Verificar a rota verde — três degraus, e o primeiro já está feito

**Escrito:** 2026-09-07, depois do Package 2B.4A
**Conta Cloudflare:** `9416750169311ee4afc18a8ff3c771d4`
**Worker de staging:** `observatorio-chapada-v2-staging`

Os Packages 2B.3 e 2B.4A registraram a verificação da rota `/data/green/…` como
**bloqueada** por o Worker de staging não ter hostname. Isso estava certo sobre
o que precisa da borda da Cloudflare, e **errado sobre o tamanho do bloqueio**:
quase tudo naquela lista é comportamento do *Worker*, não da borda, e é
verificável sem endereço público, sem credencial e sem tocar bucket nenhum.

Este documento reordena a pendência em três degraus, do mais barato ao mais
caro, com o que cada um fecha e o que cada um custa. **O degrau 1 foi executado
em 2026-09-07 e passou inteiro.**

---

## Degrau 1 — `wrangler dev` local com a release real. FEITO.

**Custo: zero.** Nenhuma credencial, nenhum endereço público, nenhuma mudança de
configuração, nenhum objeto tocado em bucket algum.

`wrangler dev` usa uma **simulação local de R2**: os objetos vivem em
`.wrangler/state` e não afetam bucket nenhum
(<https://developers.cloudflare.com/r2/get-started/workers-api/>). Então dá para
semear a release verde de verdade num R2 local e exercitar o Worker sobre HTTP,
num `curl` ou num navegador.

### Como refazer

    cd site
    bash scripts/verify_green_route.sh          # ou: scripts/verify_green_route.sh 8791

O script sobe o Worker, semeia
`site/tests/fixtures/green-release/` — que são os **documentos reais** lidos de
`araripe-v2-staging` em 2026-09-07 — roda 29 checagens sobre a rede, e derruba
o servidor e o estado local ao sair.

Para olhar com os próprios olhos, em vez de ler o resumo:

    npx --yes wrangler@4.129.1 dev --config wrangler.green.jsonc --port 8790 --local

e abrir `http://localhost:8790/data/green/current.json`.

### O que o degrau 1 fechou, executado em 2026-09-07 — 29 de 29

| Checagem | Resultado |
| --- | --- |
| o ponteiro responde `Cache-Control: no-store` | **PASS** |
| manifesto, ledger e produtos respondem `public, max-age=60, must-revalidate` | **PASS** |
| o `Content-Type` do produto vem do manifesto (`application/geo+json`) | **PASS** |
| o `ETag` é o `sha256` declarado, e não o token do armazenamento | **PASS** |
| `X-Araripe-Sha256` e `X-Araripe-Release-Id` presentes | **PASS** |
| `X-Content-Type-Options: nosniff` em tudo | **PASS** |
| **o sha256 do corpo servido == o sha256 do manifesto** | **PASS** |
| **nenhum header `Access-Control-*`, mesmo com `Origin:` do domínio final** | **PASS** |
| preflight `OPTIONS` é recusado (405) | **PASS** |
| `If-None-Match` com o ETag atual devolve **304** com corpo vazio | **PASS** |
| `?download=1` → `attachment; filename="19741870aa21.geojson"` | **PASS** |
| `runs/…`, traversal, prefixo de probe, `releases/<live>/…` → **404** | **PASS** |
| **o objeto da release que NUNCA foi promovida → 404** | **PASS** |
| `PUT`/`POST`/`DELETE`/`PATCH` → **405** com `Allow: GET, HEAD` | **PASS** |
| `/data/alerts/manifest.json` (asset estático do site) não é sombreado | **PASS** |
| **mover o ponteiro troca o que é servido, sem reiniciar nada** | **PASS** |
| **reverter o ponteiro devolve o que era servido antes** | **PASS** |

Duas falhas apareceram na primeira execução e **as duas eram do arnês, não do
Worker** — vale registrar porque cada uma ensinou algo:

1. O `awk` do macOS é o BSD e **não tem `IGNORECASE`**, então a leitura do header
   `Allow:` comparava contra `allow:` e voltava vazia. Uma checagem verdadeira
   falhando por causa da ferramenta de medida.
2. O fixture da release `rel-g1-5ffad23a…` estava **incompleto** — faltavam um
   produto declarado e o `ledger.json`. A rota respondeu `503
   manifest_is_not_live`, que é **exatamente o comportamento certo**: o ponteiro
   só pode nomear uma release que ainda esteja completa. O defeito era do
   fixture, e a rota o detectou.

### O que o degrau 1 **não** fecha

- se a borda da Cloudflare acrescenta, remove ou sobrepõe algum header;
- se o binding R2 real se comporta como a simulação local;
- o modo de alerta completo do site em escala real — que depende do artefato do
  site (Package 2B.4B) e de dado real, e portanto não está bloqueado só por
  hostname.

## Degrau 2 — bindings remotos. NÃO RECOMENDADO: o custo é maior do que o ganho.

> **Corrigido em 2026-09-08, depois de uma tentativa real.** A primeira versão
> desta seção dizia que o degrau 2 custava um token **somente de leitura** de
> R2. Isso estava **errado**, e o erro só apareceu quando o dono tentou.
>
> Bindings remotos funcionam por uma **sessão de proxy remoto**: o wrangler cria
> um Worker **na conta** e roteia as chamadas do binding por ele
> (`startRemoteProxySession`, `remoteProxyConnectionString` —
> <https://developers.cloudflare.com/workers/local-development/>). Logo o token
> precisa de **`Workers Scripts: Edit`**, que é de nível de conta.
>
> Um token `Admin Read` de R2 falha, e falha exatamente assim:
>
>     ✘ [ERROR] This Worker uses bindings that need to run remotely, even when
>       developing locally, but the remote session could not be authenticated.
>
> A mensagem sugere token inválido; o token estava válido. O que faltava era
> Workers, e o resumo do token confirmava: *"list buckets and view bucket
> configuration, read and list objects, and read access to data catalog"* — só
> R2, nenhuma permissão de Workers.
>
> **Consequência: o degrau 2 custa a mesma autoridade que o token de deploy** —
> aquele que, como `SITE_GREEN_ENVIRONMENT_SETUP.md` §1 registra, é capaz de
> implantar `observatorio-chapada`. Não existe escopo "só este script".

**O que ele fecharia, e por que isso vale pouco.** A pergunta é "o binding R2
real se comporta como a simulação local?". Mas os objetos que o degrau 1 serve
**são os objetos reais**: eles foram lidos de `araripe-v2-staging` com a chave
S3 bucket-scoped e são os fixtures, e o sha256 do corpo servido foi conferido
contra o manifesto. Então "o que está no bucket é o que a rota serve" já está
estabelecido.

O que resta sem verificação é apenas se a API de binding do R2 (`.get()`,
`object.size`, streaming) se comporta como o miniflare — uma pergunta sobre a
plataforma da Cloudflare, não sobre este projeto. A falha dela apareceria no
cutover, que é justamente quando a janela da Phase 6 existe para observar.

**Recomendação: pular o degrau 2.** Pagar Workers-Edit em nível de conta para
fechar essa margem é o pior lado do trade. Se a conta ganhar um token de deploy
verde algum dia (Phase 6, ou o Environment de `SITE_GREEN_ENVIRONMENT_SETUP.md`),
o degrau 2 sai de graça junto — rode-o então.

### Se ainda assim quiser rodar, o custo real é este

Acrescentar **`"remote": true`** ao binding R2 faz o `wrangler dev` rodar o
Worker **localmente** e mandar as chamadas de R2 para o **bucket real**
(<https://developers.cloudflare.com/workers/local-development/#remote-bindings>).
Isso fecha "o binding real se comporta igual" sem publicar nada, sem subdomínio
e sem tocar o Worker implantado — a auditoria do broker continua verde.

O nome do campo é `remote`, medido no wrangler 4.129.1. **Não** é
`experimental_remote`: esse produz `Unexpected fields found in r2_buckets[0]` e é
**ignorado**, o que faria a verificação rodar contra a simulação local
reportando sucesso. `scripts/verify_green_route_remote.sh` gera a configuração e
recusa seguir se o wrangler reclamar, exatamente para que esse aviso não passe
por ruído.

**A pegadinha, medida:** bindings remotos falam com a **REST API** da
Cloudflare, e tokens de nível *Object* (`Object Read only`, `Object Read &
Write`) **só funcionam na API S3-compatível**, não na REST
(<https://developers.cloudflare.com/r2/platform/troubleshooting/>). Então o token
necessário é **`Admin Read`**, que é de **nível de conta** e alcança **todos** os
buckets — inclusive `araripe-cogs`. É somente leitura, mas alcança dado de
produção.

Consequências, e não são negociáveis:

- **o dono guarda esse token e roda isso na própria máquina.** Ele não vai para
  Environment nenhum, nem para `.env` de repositório, nem para transcrição de
  agente;
- Claude não recebe esse token (`CLAUDE.md` do backend e do site);
- vale criá-lo com **TTL curto** e revogá-lo ao fim da verificação
  (<https://developers.cloudflare.com/fundamentals/api/how-to/restrict-tokens/>).

### Passo a passo do degrau 2

**Um comando, depois do token.** A primeira versão desta seção pedia para editar
o JSON à mão e tinha três defeitos — §"O procedimento que isto substitui" abaixo.

1. Cloudflare → ícone do perfil → **API Tokens** → **Create Custom Token** —
   **não** o menu de tokens do R2, que só emite permissões de R2 e falha na
   sessão de proxy. Permissões:

   | Tipo | Recurso | Nível |
   | --- | --- | --- |
   | Account | **Workers Scripts** | **Edit** |
   | Account | **Workers R2 Storage** | **Read** |

   Deixe **Zone Resources vazio**, restrinja a conta a
   `9416750169311ee4afc18a8ff3c771d4`, e ponha expiração curta (dias). Note que
   `Workers Scripts: Edit` **alcança o Worker de produção** — é o motivo da
   recomendação acima.
2. No shell, e **só** no shell:

       export CLOUDFLARE_API_TOKEN=…      # cole o valor aqui, e em nenhum arquivo

   **Qual dos três valores.** A página de criação mostra **Access Key ID**,
   **Secret Access Key** e **Token Value** juntos. `CLOUDFLARE_API_TOKEN` quer o
   **Token Value** — os outros dois são da API S3-compatível (é o que o perfil
   `araripe-r2-staging` do AWS CLI usa) e não servem aqui. É a armadilha do
   Package 2B.2B invertida: lá o erro era usar o Token Value onde se queria o
   Access Key ID.

3. Rode:

       cd site
       bash scripts/verify_green_route_remote.sh

4. **Revogue o token** na Cloudflare quando terminar. O script termina lembrando.

O script gera a configuração com o binding remoto, confere que o wrangler
**aceitou** o campo, sobe o Worker com estado local **vazio**, e então verifica
contra `araripe-v2-staging` de verdade: o ponteiro, o manifesto, o ledger, o
sha256 de cada produto declarado, e que `runs/`, o prefixo de probe e a release
recusada por cobertura seguem em 404. No fim apaga a configuração gerada e o
estado local.

Sem `CLOUDFLARE_API_TOKEN` ele para com a explicação e aponta o degrau 1. **Se
o wrangler falhar, o script imprime a saída dele** — a primeira versão a
descartava e morria com "token inválido? sem rede?", uma adivinhação onde havia
um log.

### O `.env` do repositório não pertence ao Worker — MEDIDO

`wrangler dev` carrega o `.env` do repositório do site e o injeta como variáveis
de ambiente **do Worker**. Contado na saída do próprio wrangler em 2026-09-08:

| | `Using secrets defined in .env` | bindings de credencial |
| --- | --- | --- |
| default | 1 | **5** |
| `CLOUDFLARE_LOAD_DEV_VARS_FROM_DOT_ENV=false` | 0 | **0** |

Os cinco incluem `env.R2_ACCESS_KEY` e `env.R2_SECRET_KEY` — as chaves de
**produção** do bucket `araripe-cogs` — mais os três do Earthdata. O Worker
verde não as lê, e o ponto é que não tem por que tê-las ao alcance: uma edição
futura em `data_route.js` que lesse `env.R2_ACCESS_KEY` funcionaria localmente
sem ninguém notar.

Os dois arnêses e a entrada `worker-verde` do `launch.json` desligam isso, e um
teste afirma que desligam. **Não afeta o deploy:** `.env` é só de
desenvolvimento local, e o `deploy --dry-run` desta configuração imprime
exatamente dois bindings — conferido.

### A prova de que o binding é realmente remoto

O script parte de um estado local **vazio** de propósito. Se a rota devolve o
ponteiro nessas condições, ele só pode ter vindo do R2 — porque não há nada
localmente para vir. Se o binding não estivesse remoto, a resposta seria
`503 pointer_absent`, que é exatamente o que o degrau 1 vê antes de semear.

Sem essa checagem o script teria o mesmo defeito do procedimento que substitui:
reportar sucesso sobre a simulação local.

### O procedimento que isto substitui, e por que ele falhava

Registrado porque o terceiro defeito é o interessante.

1. **Mandava copiar a configuração para `/tmp`.** Medido: `main` é resolvido
   relativo ao **arquivo de configuração**, não ao diretório de trabalho. Rodado
   de dentro de `site/` com `--config /tmp/copia.jsonc`, o wrangler falha com
   *The entry-point file at "worker/green.js" was not found* — ele procurou
   `/tmp/worker/green.js`. Por isso a configuração gerada fica **ao lado** de
   `worker/`, e um teste afirma que o nome dela não tem componente de diretório.
2. **Um passo dizia que a cópia era opcional e o seguinte fixava o caminho
   dela.** Quem editasse o arquivo no lugar batia num `ENOENT`.
3. **Mandava acrescentar `"experimental_remote": true`, que não é campo
   válido.** Medido no wrangler 4.129.1: ele responde
   `Unexpected fields found in r2_buckets[0] field: "experimental_remote"` — um
   **aviso**, não um erro, e segue rodando. O campo certo é `"remote": true`,
   que passa sem aviso nenhum.
4. **Descartava a saída do wrangler** e, quando o dev server não subia, morria
   com "token inválido? sem rede?". O dono bateu nisso com o token definido, e a
   mensagem não deu nenhuma pista. O erro real era legível o tempo inteiro; só
   estava no `/dev/null`.

O defeito 3 é da mesma família de um teste que passa pelo motivo errado: o
operador teria lido a simulação **local** acreditando estar lendo o bucket real,
e a verificação reportaria sucesso sem ter verificado nada. É por isso que o
script recusa seguir se o wrangler reclamar de campo inesperado, em vez de
tratar o aviso como ruído.

## Degrau 3 — um hostname temporário. Só quando a borda importar.

**Custo: a auditoria do broker fica VERMELHA enquanto o hostname existir, e o
Worker fica exposto na internet pública.**

`scripts/cloudflare_green_control.py::audit` afirma fail-closed que
`subdomain == {"enabled": false, "previews_enabled": false}`,
`custom_domain_count == 0` e `route_count == 0`. Ligar o subdomínio
`workers.dev` faz essa auditoria **falhar** — e a auditoria é a prova de
isolação do Package 2B.0. Além disso, `enforce-worker-isolation` existe
justamente para desligá-lo, então rodar o broker por qualquer outra razão
fecharia a janela no meio da verificação.

Por isso a recomendação é **não fazer isto agora**. O que este degrau fecha —
se a borda mexe nos headers — só passa a importar quando o site público for
apontado para a rota, e isso é o cutover da **Phase 6**. Deixe para lá, onde a
auditoria pode ser reestabelecida deliberadamente como parte da própria janela
de cutover.

### Se ainda assim for preciso antes, o procedimento é este

1. **Anuncie a janela e cronometre-a.** Enquanto ela estiver aberta, a auditoria
   verde não é confiável e ninguém deve tirar conclusão dela.
2. Cloudflare → **Workers & Pages** → `observatorio-chapada-v2-staging` →
   **Settings** → **Domains & Routes** → em `workers.dev`, **Enable**.
   **Não** habilite Preview URLs — são um segundo endereço público, e a
   auditoria também os afirma desligados.
3. Anote o hostname que aparecer. **Não** o coloque em arquivo de repositório.
4. Rode as checagens do degrau 1 contra ele, trocando a base:

       BASE=https://observatorio-chapada-v2-staging.<subdominio>.workers.dev/data/green
       curl -sS -D - -o /dev/null "$BASE/current.json"
       curl -sS -D - -o /dev/null "$BASE/alerts/2026-04-07/19741870aa21.geojson"

   O que se está procurando é **diferença** em relação ao degrau 1: header que
   a borda acrescentou (`CF-*`, `Server`), `Cache-Control` sobreposto,
   compressão aplicada, `ETag` alterado.
5. **Feche a janela**, e prefira fechá-la pelo broker em vez do painel, porque
   o broker deixa registro e reafirma tudo o mais:

       gh workflow run cloudflare_green_control.yml \
         -f operation=enforce-worker-isolation -f confirmation=GREEN-ONLY \
         -R santibravocmcc/Araripe

   Ele exige o revisor humano do Environment `cloudflare-green-control`, o que é
   correto: fechar a janela é uma mutação.
6. **Confirme que a auditoria voltou ao verde:**

       gh workflow run cloudflare_green_control.yml -f operation=audit \
         -R santibravocmcc/Araripe

   Espere `public_subdomain_enabled=false`, `custom_domain_count=0`,
   `route_count=0`, `production_mutated=false`.

### Uma alternativa que talvez dispense o degrau 3

`wrangler dev --remote` roda o Worker **na borda** através de uma sessão de
desenvolvimento, acessível por um proxy local, sem publicar deployment. Se ela
não exigir o subdomínio `workers.dev`, fecha o mesmo que o degrau 3 sem abrir
endereço público nenhum.

**Isto não foi verificado** e não deve ser assumido: a documentação diz que
*Preview URLs* só existem sob `workers.dev`, e não afirma nada sobre a sessão de
`dev --remote`. Antes de contar com isso, teste `--remote` e observe se o
wrangler pede subdomínio — e se pedir, o degrau 3 volta a ser o caminho.

## Resumo da recomendação

| | fecha | custo | quando |
| --- | --- | --- | --- |
| **1** | comportamento do Worker, inteiro | zero | **feito** |
| **2** | a API de binding do R2 | **`Workers Scripts: Edit` de conta** — alcança o Worker de produção | **pular**; sai de graça se um token de deploy existir |
| **3** | a borda da Cloudflare | auditoria vermelha + exposição pública | **Phase 6** |

**O degrau 1 é suficiente para o Package 2B.4B seguir.** O que falta dos degraus
2 e 3 não bloqueia escrever o artefato do site nem a publicação sem bot push —
bloqueia apenas afirmar que a plataforma da Cloudflare não interfere, e essa
afirmação só é necessária no cutover.

**Nenhum dos dois vale um token de conta hoje.** A tentativa de 2026-09-08
mostrou que o degrau 2 custa `Workers Scripts: Edit`, e o degrau 3 custa a
auditoria de isolação. Os dois se pagam sozinhos quando a Phase 6 revisitar o
desenho de credenciais inteiro; até lá, o degrau 1 é a verificação, e ela é
sólida.
