# D4C — a série verde no ar: conferir a primeira rodada, reconstruir desde janeiro, publicar

Escrito em 2026-11-17, no fim da D4B
([`PHASE_D4B_2026-11-17.md`](../implementation/PHASE_D4B_2026-11-17.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: a sessão dispara workflows que escrevem no bucket (`series/`) e uma
> lane que mescla na `main` sozinha, e a primeira execução da reconstrução é a
> prova real de que o Earth Engine devolve os bytes de outubro. Uma divergência
> ali é decisão do dono, não do agente.

**Quando abrir:** depois que o dono mesclar a PR do backend da D4B
(`claude/d4b-serie-verde`), o que só acontece depois de o C6B fechar, **e**
depois da primeira rodada agendada da lane de depósito que vier depois do
merge (segunda ou quinta, 06:00 UTC, que o GitHub costuma atrasar horas).

---

## 1. A dependência — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:src/timeseries/green_series.py | head -3
    git -C Araripe show origin/main:.github/workflows/v2_green_timeseries.yml | head -3
    git -C Araripe log origin/main --grep 'd4b' --oneline
    /opt/anaconda3/envs/araripe/bin/python -m pytest -q

- Esperado: os dois arquivos na `main`; a suíte com **3065 passed** ou mais
  (base da D4B: 3022 → 3065). Se `green_series.py` não estiver lá, pare: a PR
  não foi mesclada.
- Leia `PHASE_D4B_2026-11-17.md` inteiro, em especial §2 (a medição) e §4
  (a reconstrução).

## 2. O que já foi verificado — não refazer

- **Bytes do Earth Engine:** 2026-06-06 puxado em 2026-11-17 = puxado em
  2026-09-09 = hash selado; 2026-11-13 puxado num Mac = hash que o CI selou
  com a conta verde. Não depende de tempo, máquina nem conta (§2 do registro).
  Março (S2C) e abril (S2A) também batem. **Não medido:** um hash de outubro
  da cadeia viva, nem janeiro e fevereiro. A reconstrução mede isso de fato.
- A junção membro ↔ documento (`ledger_id` + `run_manifest_id`) foi conferida
  com o ponteiro e a release /3 reais (registro §6-ter).
- Os ledgers dos membros **não** são legíveis pela rota pública; só o índice da
  release /3. Nenhuma sessão tem credencial de bucket: tudo pelas lanes.
- Os 29 membros da release viva em 2026-11-17 não têm documento `series/`;
  até a reconstrução, `v2_green_timeseries.yml` **falha por desenho** a cada
  publicação (buraco recusa).
- Com só as aceitas, o gráfico do replay local começa em 2026-02-11: as cinco
  aquisições até 02-01 são todas `rejected_quality` (registro §6-bis). Confira
  o mesmo na cadeia viva e diga ao dono a primeira data do gráfico.
- O portão da promoção exige os jobs `detect`, `deposit`, `heartbeat`; a D4B
  os manteve (teste amarra).

## 3. A tarefa

1. **A primeira rodada depois do merge.** `gh run list --workflow
   v2_green_deposit_lane.yml`: no job `deposit`, o passo *Deposit the run's
   series rows…* imprime `created series/ci-<id>/timeseries_rows.json`; no
   `detect`, *Measure the series rows…* imprime as contagens. Se a rodada não
   achou aquisição (`deposit` pulado), espere a seguinte. Se o passo falhou,
   leia o log antes de tudo: o C6B mostrou o que uma falha no `deposit` custa.
2. **A reconstrução.** Dispare `v2_green_series_rebuild.yml` com `max_runs`
   6 e leia o job `measure`: cada rodada termina em *hashes bound*. Repita até
   o `plan` dizer `nothing — every chain run has its rows`.
   **Se o `measure` falhar com `the ledger sealed`, pare.** Não re-dispare,
   não mude código: anote data, datatake, hash esperado e obtido, e leve ao
   dono (opção b da §7 da D4 — série só dali para a frente — volta à mesa).
3. **A série.** Dispare `v2_green_timeseries.yml`. O `build` deve dizer
   `changed: yes` e o `publish` abrir e mesclar `auto/timeseries-<run id>`
   com só `data/timeseries/green_series.db` e `GREEN_SERIES.json`. Confira na
   `main` que o sha256 do banco é o do sinal.
4. **Conferir o conteúdo** (só leitura, local): `green_series.db` deve ter uma
   geração, aquisições de janeiro até a última promovida, e as cinco datas
   recusadas (01-02, 01-04, 01-12, 01-22, 02-01) com `qa_status
   rejected_quality`, não `accepted`.
5. **O site.** A PR rascunho do site (`claude/d4b-serie-verde` no repositório
   do site) troca o consumidor; ela só pode sair do rascunho **depois** do
   passo 3. Rebaseie sobre a `main` do site, rode `pytest`, `node --test` e
   `npm run build`, e marque pronta para o dono. O robô de terça/sexta
   publica a série no dia seguinte.
6. Registro `PHASE_D4C_<data>.md` e o briefing seguinte; atualizar a linha da
   série em `ESTADO_DAS_FRENTES.md` se ele já estiver na `main`.

## 4. Fronteiras duras

- Nenhum push na `main` de nenhum repositório; a única escrita na `main` é a
  da lane de PR da série, pelo `GITHUB_TOKEN`. Nenhuma mudança de ruleset.
- Escrita de objeto só em `araripe-v2-staging`, e só pelas lanes. Nenhum
  `wrangler`, token Cloudflare ou broker; nenhum Environment aprovado.
- `detect_gee.yml` e `update_data.yml` não são reativados nem disparados.
- Não disparar a lane de depósito nem a de publicação para "testar": elas são
  produção desde a virada.

## 5. Armadilhas já pagas

- `ee.Initialize()` ignora `GOOGLE_APPLICATION_CREDENTIALS` em CI; a
  reconstrução usa `--service-account`.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório.
- `<<EOF` não citado executa os backticks: `git commit -F`.
- Um worktree novo não tem os dados ignorados de `data/` nem o
  `node_modules` do site: ligue por symlink.
- Nunca `git stash` num worktree: a pilha de stash é do repositório inteiro.
- A rota verde recusa o User-Agent padrão do urllib (403/1010); use o do
  compositor do site.

## Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

A série nova está ligada às rotinas, mas nada rodou ainda: as rotinas só
rodam depois que você mesclar. Faltam a primeira rodada real, refazer a série
desde janeiro e publicar no site.

### O que você precisa fazer

1. **Esperar o C6B fechar e mesclar a PR do backend da série verde.** Não é
   urgente; muda a rotina que o C6B está vigiando, por isso espera.
2. **Deixar a PR do site como está** até a próxima sessão dizer que pode.
   Mesclar antes faz o robô do site ficar vermelho.
3. **Abrir uma sessão do Claude com este briefing** depois da primeira rodada
   automática que vier depois do merge (segunda ou quinta).

### Tem algo preocupante?

Não. Um aviso só: com "só as imagens aceitas", o gráfico deve começar em
fevereiro, porque todas as imagens de janeiro foram recusadas pelo controle de
qualidade; os dados de janeiro ficam guardados. Medimos que as imagens baixadas de novo saem idênticas às de setembro e
às da rotina automática; se alguma de outubro não sair, a reconstrução para
sozinha e a decisão volta para você.

### O que ainda falta no caminho

- **A vigia (C6B)** — em curso noutra sessão; a série espera ela fechar.
- **A série (D4C)** — conferir a primeira rodada, refazer desde janeiro,
  publicar e ligar o site.
- **Avisar o tamanho antes de baixar** e **a frase da automação** — pacotes
  pequenos do site.
- **Fase 5** — a validação independente.
