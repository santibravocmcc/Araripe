# Phase 6 — a chuva da página presa em 2026-10-13: diagnóstico

Registro de 2026-10-23, só leitura. Continua o achado de
[`PHASE_6ZN`](PHASE_6ZN_2026-10-23.md) §2 (PR `#131`, aberta quando este foi
escrito). Base: backend `origin/main` em
`8cc3b27ab2512aa3337a96abb80b2678217bd893` (a `#130`); site `origin/main` em
`c3bae2d` (SHA curto: o hook `commit-msg` recusa SHA de outro repositório).

**Nenhuma escrita do agente** fora desta documentação: nenhum purge, nenhum
push ao site, nenhum wrangler, nenhuma API ou token da Cloudflare. As leituras
foram `curl` com UA de navegador, `git`, e `gh api …/check-runs`.

O briefing da correção é
[`PACKAGE_P6_SITE_RAIN_BUILD_CACHE_PROMPT.md`](../operations/PACKAGE_P6_SITE_RAIN_BUILD_CACHE_PROMPT.md).

## 1. Conclusão

**Não é cache de borda. É o conteúdo implantado.** Toda versão do Worker
`observatorio-chapada` construída pelo Workers Builds desde 2026-10-16 tem,
no seu manifesto de assets, os bytes de 2026-10-13 nos três JSON de nome fixo
que o robô de chuva reescreve. Os mesmos commits, construídos localmente com
`vite build`, dão os bytes novos. Os bytes velhos entram **dentro do Workers
Builds**, entre o checkout e o upload.

A causa mais provável é o **build cache do Workers Builds**, que está ligado
neste gatilho (`docs/contracts/phase1/CLOUDFLARE_BEFORE_STATE_AND_ROLLBACK_2026-07-24.md`
linha 159: *"Build caching is enabled"*): o padrão do §4 é o de uma
restauração que sobrescreve arquivos rastreados de `public/` com uma cópia de
10-13. **Isso não foi provado**: o log do build, que diria o que foi
restaurado, só se lê no painel. O §5 diz o que o decide.

Um purge do cache da zona **não** corrigiria: o `ETag` servido é o hash de
conteúdo que o manifesto da versão nomeia (§2), e o purge não muda o
manifesto.

## 2. O `ETag` é o hash do asset no manifesto, não uma chave de cache

O wrangler calcula a chave de cada asset como
`blake3(base64(conteúdo) + extensão)`, em hexadecimal, 32 caracteres
(`hashFile`, `src/pages/hash.ts` no `wrangler-dist/cli.js`). O serviço de
assets devolve essa chave como `ETag` (`generateETagHeader(assetKey)`, no
mesmo arquivo). Conferido: `rain-2026-10-22.png` do git dá
`de74fa8cf0238c4a41817a5554eb92c3`, o mesmo `ETag` servido.

Script, re-executável (`blake3-wasm` vem com o wrangler):

```js
// h.cjs <arquivo>…
const b = require('<wrangler>/node_modules/blake3-wasm'); const fs = require('fs')
for (const f of process.argv.slice(2)) {
  const c = fs.readFileSync(f); const ext = f.split('.').pop()
  console.log(b.hash(c.toString('base64') + ext).toString('hex').slice(0, 32), f)
}
```

| arquivo | hash em `afb2810` (10-13) | hash em `c3bae2d` (10-23) | `ETag` servido |
| --- | --- | --- | --- |
| `/data/territorio/rain/manifest.json` | `b490eaf7e490e8994c557873ed668437` | `4a286126332f4c834f40266b4147f05f` | `b490eaf7…` |
| `/data/freshness/chuva.json` | `3f1731747c6802bd0b75ad83646c83e6` | `3e2304a889eff0d13ca1594a12fa1e77` | `3f173174…` |
| `/data/territorio/chuva-historico.json` | `d9e2e801c98600acc2484d72e651d566` | `88e29289bc11adf4d77f673141bb36dd` | `d9e2e801…` |

O SHA-256 do corpo servido bate com `afb2810` nos três (o mesmo do
`PHASE_6ZN` §2).

## 3. Cada versão, lida pela própria URL de prévia

O Worker de produção responde em `observatorio-chapada.sbravo-rehab.workers.dev`
e cada versão em `<8 primeiros do Version ID>-observatorio-chapada.sbravo-rehab.workers.dev`.
É outro host, logo outra entrada em qualquer cache por caminho, e a versão é
escolhida explicitamente. O `Version ID` de cada build está no resumo do check
run *"Workers Builds: observatorio-chapada"*
(`gh api repos/santibravocmcc/observatorio-site/commits/<sha>/check-runs`).

| commit do site | build terminou | Build ID | Version ID | `ETag` de `chuva.json` | o commit tem |
| --- | --- | --- | --- | --- | --- |
| `08fc897` (10-08) | — | — | `1f23c8c9-b453-4837-92f0-27d063869ec2` | `98f499b0…` | `98f499b0…` ✔ |
| `f2a8fdc` (10-09) | — | — | `41c71b65-c3ad-46f5-9e93-be63ae34baec` | `c01cfef0…` | `c01cfef0…` ✔ |
| `afb2810` (10-13) | 10-13T13:34:33Z | `52712ed2-2c18-4cc7-b61f-c29f89a67193` | `11454fd0-4cba-4fd3-9027-107adf749361` | `3f173174…` | `3f173174…` ✔ |
| `a0c3390` (#47) | 10-13T17:12:45Z | `5b351db5-8689-46c8-b136-d798bd2f4a49` | `3d910ec8-1176-4d90-841c-4aec750232ec` | `3f173174…` | igual a `afb2810` |
| `11d1b65` (#48, B1) | 10-14T14:37:16Z | `ddaa97c3-5f7e-4bb9-a008-a052fdf75431` | `ff2e53b2-b811-4cc4-b7b6-2e1e2ede8a31` | `3f173174…` | igual |
| `198be57` (#42, `COMPOR = True`) | 10-14T15:05:51Z | `6c99f14d-2199-46c4-a54a-3b6ed4254b68` | `b46a10c7-6a07-4368-9bd8-d9525b337840` | `3f173174…` | igual |
| `91bffea` | 10-14T16:09:04Z | `c1f9392c-0c4b-424f-8cda-5b8045cb667a` | `9f93e8d6-a753-478d-890f-22319be52d02` | `3f173174…` | igual |
| `a5bdad5` | 10-14T16:23:40Z | `a33fa667-7e4f-46be-bccb-cebe41163e0d` | `0e0b5e4d-17f1-456a-9769-ae163e940b2a` | `3f173174…` | igual |
| `1978b15` (#49) | 10-14T16:36:27Z | `e47cba4f-3a27-40c3-8dbd-a8dd6337b68b` | `f682ca85-28ec-478f-97f0-74e96a097206` | `3f173174…` | igual |
| **`df60f0b` (chuva 10-16)** | 10-16T10:47:04Z | `f3cc2e1c-1e48-46c3-83e7-8f8b98655abe` | `c1c065d4-8ead-401b-bdc5-05fef2bb0f86` | **`3f173174…`** | `fdbf452e…` ✘ |
| `8723e41` | 10-19T14:03:07Z | `8ad0b7d2-2415-45ea-8412-c03a9bcc9665` | `315bdf2f-747b-4b66-a2ab-be2fecd5deee` | `3f173174…` | `fdbf452e…` ✘ |
| `6bf0fb3` (chuva 10-20) | 10-20T11:01:28Z | `1195f3a4-6014-4f9c-ac4c-e6e7e981167e` | `24eec4ca-0ca0-42f8-a69c-f0d678af3e14` | `3f173174…` | `870d887f…` ✘ |
| `e959123` | 10-22T12:29:03Z | `fe856548-750b-4098-9e89-e9c02fe0a97e` | `ae9a4160-c306-41a6-908a-6b48745376db` | `3f173174…` | `870d887f…` ✘ |
| `e0bd263` (#50) | 10-22T18:12:07Z | `c6caedcf-c084-46ef-a140-107938d27a70` | `80df53aa-806b-416f-9cf4-16adc8d5b57d` | `3f173174…` | `870d887f…` ✘ |
| `c3bae2d` (chuva 10-23) | 10-23T11:06:33Z | `d94a451c-9193-41b4-9f5f-a04a287c3b57` | `10a5894d-268e-40cd-ba86-1daf0643ffea` | `3f173174…` | `3e2304a8…` ✘ |

O que a tabela prova:

- **As versões não compartilham resposta por caminho.** `08fc897` e `f2a8fdc`
  servem cada uma o próprio conteúdo; `11454fd0` (de `afb2810`) devolve `404`
  em `/data/alert-index/built-from.json`, que só passou a existir no `198be57`.
  Cada prévia lê o próprio manifesto.
- **A falha começou entre o build de `afb2810` (10-13 13:34) e o de `df60f0b`
  (10-16).** Antes, toda reescrita do robô aparecia na versão seguinte.
  Desde então nenhuma aparece. Entre os dois estão os merges do B1 e do B2
  (`11d1b65`, `198be57`): o primeiro build com `COMPOR = True`, que cria
  `.cache/build-venv` e `.cache/build-backend`, foi o de `198be57`. É uma
  coincidência de data, **não uma causa medida**.
- **O domínio serve a versão atual.** O `ETag` de `/data/alert-index/built-from.json`
  no domínio (`77e635e9…`) é o de `ae9a4160`/`10a5894d`; o de `c1c065d4` é
  `6cbaf5ba…` e o de `24eec4ca` `73103341…`.

## 4. Quais arquivos ficaram presos, e quais não

`git diff --stat afb2810 c3bae2d -- public` lista **nove** arquivos, e só
nove:

| tipo | arquivos | no ar |
| --- | --- | --- |
| rastreados, nome fixo, **conteúdo mudou** | `rain/manifest.json`, `freshness/chuva.json`, `chuva-historico.json` | **10-13** ✘ |
| rastreados, **nome novo** | `rain/rain-2026-10-{15,19,22}.png`, `figures/rain-2026-10-{15,19,22}.png` | sim ✔ (`404` nas versões anteriores ao commit que os criou) |
| gerados no build, fora do git | `public/data/alert-index/*` (o `.gitignore` os ignora; `indice_no_build.py` apaga e reescreve) | atuais ✔ |

Os JSON estáticos que não mudaram desde 10-13 batem com a `main`
(`PHASE_6ZN` §2). O conjunto preso é **exatamente** "arquivo rastreado de
`public/` cujo conteúdo mudou desde 10-13". Uma restauração de uma cópia de
`public/` tirada em 10-13, por cima do checkout, produziria esse padrão:
sobrescreve os que existiam, não apaga os novos, e perde para o que o build
reescreve depois.

### Resultados negativos

- **Não é `run_worker_first`.** `["/api/*", "/data/green/*"]` não casa
  `/data/territorio/…` nem `/data/freshness/…`; esses caminhos são servidos
  pela plataforma direto do manifesto, sem passar por `worker/index.js`. O
  Worker, quando roda, só faz `env.ASSETS.fetch(request)` fora das duas rotas.
- **Não é `public/_headers`.** A regra `/data/*` só põe
  `Cache-Control: public, max-age=3600` (o que o navegador guarda). Não muda o
  que o manifesto aponta, e a mudança de 10-14 não tocou o `_headers`.
- **Não é cache de borda por caminho.** Query aleatória, `Accept-Encoding`
  `br`/`gzip`/`identity`, `Cache-Control: no-cache` na requisição, o host
  `workers.dev` e a URL de prévia da versão devolvem o mesmo `ETag`.
  `If-None-Match` com o hash velho dá `304`; com o novo, `200` com o velho. Um
  caminho codificado (`chuv%61.json`) recebe `307` para o canônico.
- **Não é o build reescrevendo os arquivos.** Nenhum script do site, fora os
  do robô, escreve esses três caminhos (procurado em todo `.py`/`.js`/`.mjs`
  fora de `public/` e `tests/`). `indice_no_build.py` escreve só em
  `public/data/alert-index/`; `site_artifact.py compose --from-route` só lê
  `/data/green/…`.
- **Não é o commit do robô.** O conteúdo de `chuva.json` em `c3bae2d`, lido
  pela API do GitHub, tem SHA-256 `ab79c08d…`, o novo. Não há `.gitattributes`.
- **Não é o `vite build`.** `git archive origin/main` (em `c3bae2d`) num
  diretório limpo, `vite build`, e o script do §2 em `dist/`: `3e2304a8…`,
  `4a286126…`, `88e29289…`, os hashes novos.
- **Não é o reconciliador.** `green_site_rebuild.yml` só faz commit vazio à
  `main` quando o ponteiro muda (`reconcilia_deploy.py`); quem constrói e
  implanta é sempre o Workers Builds, a partir do commit.

## 5. O que decide a causa, e o que corrige

Só o dono enxerga, no painel da Cloudflare (Workers & Pages →
`observatorio-chapada` → Builds):

1. O **log do build `d94a451c-9193-41b4-9f5f-a04a287c3b57`**: as linhas do
   build cache (restauração no começo, gravação no fim) e a contagem de assets
   enviados. Se a restauração lista `public/` (ou a gravação falha ou é
   pulada desde 10-14), a causa é o build cache. Ler é inofensivo.
2. Settings → Build → **Build cache**: se está ligado.

A correção proposta, em ordem:

- **A. Limpar o build cache e refazer o build da `main` atual** (Settings →
  Build → Build cache → *Clear Cache*; depois *Retry build* no build mais
  recente, ou esperar o próximo commit do robô, terça 2026-10-27). É um
  deploy de produção do que a `main` já é. Esperado depois: os `ETag` do §2
  passam a ser os hashes de `git show origin/main:public/<arquivo>`, no domínio
  e na prévia da versão nova; `built-from.json` continua nomeando a release do
  ponteiro.
- **B. Se A não bastar**: desligar o build cache e refazer o build. Se mesmo
  assim ficar preso, a causa não é o build cache; o log do build e o suporte
  da Cloudflare são o próximo passo.
- **C. Defesa no código (decisão separada)**: o build do site conferir, depois
  do `vite build`, que cada arquivo rastreado de `public/` chegou ao `dist/`
  com o conteúdo do `HEAD`, e falhar fechado se não. Mesclar isso na `main`
  do site é deploy de produção.

**Quem aprova:** o dono, para A, B e C. São ações no Worker de produção pelo
painel, com permissão de conta, ou merge na `main` do site, que implanta.
Nenhuma passa pelo broker (`cloudflare_green_control.yml` exclui produção), e
nenhum agente tem, nem pode receber, a credencial.

## 5a. O log do build, lido pelo dono em 2026-10-24 — causa provada

O dono colou o log do build de `c3bae2d` (Version ID
`10a5894d-268e-40cd-ba86-1daf0643ffea`). A ordem das linhas fecha a causa:

| hora (10-23) | linha do log |
| --- | --- |
| 11:00:43Z | `Cloning repository...` |
| 11:01:04Z | `Restoring from build output cache` |
| 11:01:10Z | `Success: Build output restored from build cache.` |
| 11:01:16Z | `Executing user build command: npm run build` |
| 11:06:24Z | `No updated asset files to upload. Proceeding with deployment...` |
| 11:06:31Z | `Success: Build output uploaded to build cache.` |

- A restauração do *build output cache* vem **depois** do clone e **antes**
  do build: ela escreve por cima do checkout.
- `No updated asset files to upload`: se o `dist/` tivesse os bytes novos de
  `c3bae2d`, os três hashes novos do §2 (nunca implantados antes) teriam de
  subir. Nenhum subiu, então o `dist/` tinha só conteúdo que o serviço já
  conhecia, o de 10-13.
- No fim, o build grava o resultado de volta no cache. **O laço se
  auto-perpetua:** restaura o velho, constrói com o velho, grava o velho. Por
  isso ficou preso dez dias, e não um build atrás.

Consequência para a correção: **limpar o cache não basta.** O primeiro build
depois da limpeza sai certo e grava esse resultado; o seguinte restaura essa
cópia por cima do commit novo do robô, e o laço recomeça uma versão adiante.
A correção durável é **desligar** o build cache (o passo B vira o principal).
Na leitura de 2026-10-24 14:35Z, depois de o dono limpar o cache e pedir
*Retry build*, o domínio ainda servia `b490eaf7…`/`3f173174…`/`d9e2e801…`.
O único check run *"Workers Builds"* da `main` continuava sendo o de 10-23, e
o retry não tinha ainda versão nova confirmada.

Segundo log colado pelo dono (2026-10-24 15:00Z), depois de desligar o
cache: não há mais `Restoring from …cache`, mas o build é de uma **branch de
prévia**, não da `main`. O `dist/` tem `monitor.html`, que só existe em
`claude/integracao-car-site` e `claude/monitor-no-ar` (site `#52`/`#53`,
rascunhos). O compose tem `--eventos`, e o deploy é `exit 0`: o gatilho
inerte de não-produção do Package 2B.0. Nada foi implantado:
`/monitor.html` no domínio responde `404`, e os `ETag` da chuva às 15:08Z
continuam os de 10-13. Falta o *Retry build* de um build **da `main`**
(deploy `npx wrangler deploy`).

Não foi medido quais diretórios o *build output cache* guarda nem por que o
laço começou entre 10-13 e 10-16: o log não lista os caminhos.

## 6. Observação à parte, não investigada

27 dos 42 PNG de `rain/` são o mesmo blob (`git ls-tree`), todas as datas de
`2026-05-22` a `2026-10-22`. A estação seca explica a maioria, mas
`2026-10-19` e `2026-10-22` têm `max_mm` `13.8` no `manifest.json` e saem
iguais ao de `2026-10-12`, que tem `0.0`. Pode ser a escala de cor tornando
transparente a chuva baixa, ou o desenho falhando. Não tem relação com este
diagnóstico (os PNG chegam ao ar). Fica para quem mexer na chuva.
