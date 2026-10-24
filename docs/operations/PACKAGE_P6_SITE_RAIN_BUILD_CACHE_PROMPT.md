# Phase 6 — destravar a chuva da página (build cache do Workers Builds)

Escrito em 2026-10-23, depois do diagnóstico
[`PHASE_6_CHUVA_PRESA_2026-10-23.md`](../implementation/PHASE_6_CHUVA_PRESA_2026-10-23.md).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: a correção é do dono, no painel. A sessão lê o log que ele
> mostrar, pede um clique por vez, e prova o "Depois" pelos `ETag`. Nada a
> construir, a menos que o dono escolha a defesa C.

Este pacote é independente do C3/C4 da folha da virada. Não o misture com
eles, e não segure o C4 por causa dele.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6_CHUVA_PRESA_2026-10-23.md | head -8
    git -C site fetch origin && git -C site log --oneline -3 origin/main

Depois, os três `ETag` no domínio, com UA de navegador (o verificador que
difere do cliente prova o errado):

    UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
    for p in /data/territorio/rain/manifest.json /data/freshness/chuva.json /data/territorio/chuva-historico.json; do
      curl -sS -A "$UA" -D - -o /dev/null "https://observatoriodachapadadoararipe.com$p" | grep -iE '^(cf-cache-status|etag)'
    done

e os hashes esperados, do commit mais novo da `main` do site, com o script
de `PHASE_6_CHUVA_PRESA` §2 (`blake3(base64(conteúdo) + extensão)`, 32
hex; copie-o para `$TMP/v/h.cjs`; o `blake3-wasm` vem com o wrangler
instalado, sem rodar o wrangler):

    for p in data/territorio/rain/manifest.json data/freshness/chuva.json data/territorio/chuva-historico.json; do
      mkdir -p "$TMP/v/$(dirname $p)"; git -C site show origin/main:public/$p > "$TMP/v/$p"
    done
    (cd "$TMP/v" && node h.cjs data/territorio/rain/manifest.json data/freshness/chuva.json data/territorio/chuva-historico.json)

- **Se os `ETag` já forem os esperados**, o problema se resolveu sozinho (o
  build cache expira 7 dias depois da última leitura). Registre com os ids e
  pare: nada a pedir ao dono.
- **Se forem `b490eaf7…`, `3f173174…`, `d9e2e801…`** (os de 10-13), siga.

## 2. O que já foi verificado, para não refazer

Tudo em `PHASE_6_CHUVA_PRESA` §§2–4, com os ids:

- O `ETag` é a chave de conteúdo do manifesto da versão; a URL de prévia de
  cada versão (`<8 hex do Version ID>-observatorio-chapada.sbravo-rehab.workers.dev`)
  mostra o mesmo, então **cada versão desde 10-16 foi implantada com os bytes
  de 10-13** nesses três arquivos.
- `vite build` limpo de `c3bae2d` dá os bytes novos. Os PNG de nome novo e o
  índice verde gerado no build chegam ao ar.
- Negativos: não é `run_worker_first`, `_headers`, cache por caminho, query,
  encoding, o robô, o reconciliador nem script do build.
- O build cache está ligado no gatilho de produção desde antes de 2026-07-24
  (`docs/contracts/phase1/CLOUDFLARE_BEFORE_STATE_AND_ROLLBACK_2026-07-24.md`
  linha 159). Falta a prova direta: o log do build.

## 3. A tarefa

**Atualizado em 2026-10-24** (`PHASE_6_CHUVA_PRESA` §5a): o log do build já
provou a causa. O *build output cache* é restaurado por cima do clone e
regravado no fim, e o laço se perpetua. Limpar não basta; o passo é
**desligar**.

1. **Ler o log do build mais recente**, se o dono já pediu *Clear Cache* +
   *Retry build*: se ainda disser `Build output restored from build cache`, ou
   se o primeiro build depois da limpeza estiver certo e o seguinte não, é o
   laço do §5a.
2. **Pedir ao dono**: Settings → Build → Build cache → **desligar**; depois
   *Retry build* no build mais recente da `main`. O log novo não pode ter
   `Restoring from build output cache`, e o upload tem de enviar os três
   hashes novos (`Uploaded N new or modified static assets`, não
   `No updated asset files`). É deploy de produção do que a `main` já é:
   **sem o "sim" do dono no chat, não peça o clique.**
3. **Provar o "Depois"** pela rede, sem credencial:
   - o check run *"Workers Builds: observatorio-chapada"* do retry `success`, e
     o novo `Version ID` no resumo dele;
   - na prévia dessa versão e no domínio, os três `ETag` = os hashes do §1;
   - `/data/alert-index/built-from.json` ainda com a release do ponteiro (o
     build continua compondo o índice);
   - a página de chuva mostrando a data nova (o navegador pode guardar até 1 h
     por causa do `max-age=3600`; o `ETag` é a prova, não a tela).
4. **Se continuar preso**, pedir o passo B: desligar o build cache, *Retry
   build*, e provar de novo. Se ainda assim ficar preso, a causa não é o build
   cache: registre, junte o log, e entregue ao dono para o suporte da
   Cloudflare. Não tente outro caminho.
5. **Defesa C, só se o dono escolher**: uma PR no site que, depois do
   `vite build`, confira que cada arquivo rastreado de `public/` chegou ao
   `dist/` com o conteúdo do `HEAD` (`git ls-files public` + comparação de
   bytes; `public/data/alert-index/` é ignorado pelo git, então fica de fora
   sozinho) e falhe fechado se não. Rascunho; o merge é do dono e implanta.
   Antes de escrevê-la, leia o `AGENTS.md` do site e `scripts/indice_no_build.py`,
   que já é o passo do build versionado pelo `package.json`.
6. Registro em `docs/implementation/` e PR de documentação no backend.

## 4. Fora de escopo

- **Purge do cache da zona.** Não corrige (o manifesto é que está velho) e é
  ação de produção. Não peça.
- `wrangler`, API da Cloudflare, token: proibidos (`CLAUDE.md`). O broker
  verde exclui produção.
- O C3/C4 da folha da virada e a `#131`.
- Os PNG de chuva idênticos (`PHASE_6_CHUVA_PRESA` §6): outro pacote.

## 5. Fronteiras duras

- Produção congelada, salvo passo aprovado pelo dono. A `main` do site
  implanta a cada push: nenhum push nela, nenhum commit vazio para "forçar" o
  build.
- Nenhum agente aprova o próprio pedido, e nenhum contorna uma recusa.
- Copie todo id (Build ID, Version ID, run) da ferramenta que o produz.

## 6. Armadilhas já pagas — não redescobrir

- `cf-cache-status: HIT` nos assets do Workers é normal: o serviço de assets
  guarda por chave de conteúdo. O `ETag` é o que diz qual conteúdo.
- A URL de prévia de versão é a forma de ler o manifesto de uma versão sem
  credencial; o `workers.dev` sozinho só mostra a versão ativa.
- Caminho codificado (`%61`) recebe `307` para o canônico: não serve para
  contornar cache.
- No zsh, `$c:scripts/…` é lido como modificador `:s`; use `${c}:scripts/…`.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório.
- `<<EOF` não citado executa os backticks: `git commit -F`.

## 7. Estado que o package herda

- Domínio servindo a versão `10a5894d-268e-40cd-ba86-1daf0643ffea` (de
  `c3bae2d`) ou mais nova; chuva presa em 2026-10-12 na página.
- Robô de chuva verde e commitando (ter/sex 06:00 UTC); próximo commit
  esperado terça 2026-10-27.
- Build cache ligado no gatilho de produção (registro de 2026-07-24).

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

O diagnóstico está feito, mas falta a prova final da causa. Ela está no log de
um build, que só você enxerga no painel da Cloudflare. Nada foi mudado.

### O que você precisa fazer

1. **Mesclar a PR de documentação** — quando puder; não muda nada que roda.
2. **Abrir uma sessão do Claude com este briefing** — quando quiser destravar
   a chuva. Ela vai pedir que você cole umas linhas do log do build e depois
   que limpe o cache de build do site no painel e refaça o build. São dois
   cliques seus, um de cada vez, e é você quem diz "sim".

### Tem algo preocupante?

Sim, moderado. A página mostra a chuva de 13 de outubro como se fosse a
atual, há dez dias, e cada nova atualização do robô também fica de fora até
isso ser corrigido. Nenhum dado se perde: tudo está guardado no código do
site e aparece assim que o build sair limpo.

### O que ainda falta no caminho

- **Destravar a chuva** — este pacote: dois cliques seus e a conferência.
- **Desligar o sistema antigo** — fechar o acesso antigo (feito) e parar de
  guardar alertas no código do site (o próximo passo da virada).
- **Registrar a virada** — um documento que junta todos os passos.
- **Duas semanas de vigia** — conferir cada rodada.
- **Os mapas de chuva iguais** — um olhar à parte, sem pressa.
