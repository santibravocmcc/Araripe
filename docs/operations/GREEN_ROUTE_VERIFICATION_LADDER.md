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

## Degrau 2 — bindings remotos: R2 real, Worker local, nenhum endereço público

**Custo: um token de API da Cloudflare, e ele é mais amplo do que parece.**

Acrescentar `"experimental_remote": true` ao binding R2 faz o `wrangler dev`
rodar o Worker **localmente** e mandar as chamadas de R2 para o **bucket real**
(<https://developers.cloudflare.com/workers/local-development/#remote-bindings>).
Isso fecha "o binding real se comporta igual" sem publicar nada, sem subdomínio
e sem tocar o Worker implantado — a auditoria do broker continua verde.

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

1. Cloudflare → **R2** → **API Tokens** → **Manage** → **Create Account API
   token**. Nome `araripe-remote-binding-ro`, permissão **`Admin Read`**,
   e uma data de expiração curta (dias, não meses).
2. Na máquina, **sem** colocar em arquivo do repositório:

       export CLOUDFLARE_API_TOKEN=…      # cole o valor aqui, no shell, e só

3. No `site/wrangler.green.jsonc`, acrescente `"experimental_remote": true` ao
   objeto de `r2_buckets` — **temporariamente, e não commite**. Se preferir não
   editar o arquivo, use uma cópia:
   `cp wrangler.green.jsonc /tmp/green-remote.jsonc` e edite a cópia.
4. `npx --yes wrangler@4.129.1 dev --config /tmp/green-remote.jsonc --port 8790`
5. Repita à mão as checagens que mais importam contra o bucket real — o ponteiro
   e um produto:

       curl -sS -D - -o /dev/null http://localhost:8790/data/green/current.json
       curl -sS http://localhost:8790/data/green/release.json | python3 -m json.tool | head -30
       curl -sS http://localhost:8790/data/green/alerts/2026-04-07/19741870aa21.geojson | shasum -a 256

   O sha256 deve dar
   `a5a2103c187c1324911479c5931df0eb8d2271a10c4b0dbb47f2202677f1e675`.
6. **Revogue o token** e apague a cópia da configuração.

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
| **2** | o binding R2 real | token `Admin Read` de conta, guardado pelo dono, TTL curto | quando der |
| **3** | a borda da Cloudflare | auditoria vermelha + exposição pública | **Phase 6** |

**O degrau 1 é suficiente para o Package 2B.4B seguir.** O que falta dos degraus
2 e 3 não bloqueia escrever o artefato do site nem a publicação sem bot push —
bloqueia apenas afirmar que a borda não interfere, e essa afirmação só é
necessária no cutover.
