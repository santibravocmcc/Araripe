# D4B — a série verde: ligar o produtor às lanes e o site ao banco novo

Escrito em 2026-11-03, no fim da primeira sessão do D4
([`PHASE_D4_2026-11-03.md`](../implementation/PHASE_D4_2026-11-03.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: é a fiação de uma lane que roda sozinha em produção, com escrita no
> bucket, uma lane de PR na `main` protegida e um consumidor noutro
> repositório. O risco é dar `contents: write` a quem não deve, criar em
> `runs/` um prefixo que a resolução da cabeça leria, ou mesclar durante o C6B
> uma mudança no job `deposit` que ele vigia.

**Quando abrir:** depois que a PR desta sessão (`claude/d4-serie-verde`) for
mesclada pelo dono, e de preferência depois de 2026-11-17 (fim do C6B). Pode
abrir antes para trabalhar numa branch, sem mesclar.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:src/timeseries/green_rows.py | head -3
    git -C Araripe show origin/main:docs/implementation/PHASE_D4_2026-11-03.md | head -3
    /opt/anaconda3/envs/araripe/bin/python -m pytest -q

- Esperado: `green_rows.py` e `PHASE_D4` na `main`. Se não, pare: a PR da
  sessão 1 não foi mesclada.
- Leia `PHASE_D4_2026-11-03.md` inteiro: §2 (medição), §3 (o esquema do 2A.2),
  §6 (o desenho), §7 (as decisões do dono).

## 2. O que já foi verificado — não refazer

- `runs/<id>/` não guarda os compostos; `green-run-v2/v3` têm
  `additionalProperties: false`. A série só pode ser medida no job `detect`.
- Verde × azul em 41 datas comuns: \|Δ média\| ≤ 0,0065; comparável, não
  idêntico (§2 do registro).
- O banco legado está em quarentena (2A.2); a série verde vai para o esquema
  limpo, num banco novo. `build` recusa o nome `timeseries.db`.
- `green_timeseries.py` não alcança `config` nem por import transitivo
  (`GREEN_SCRIPTS`).

## 3. A tarefa

1. **No job `detect`** de `v2_green_deposit_lane.yml`, depois do `replay_2026.py
   run`: `green_timeseries.py rows`, e `timeseries_rows.json` no artefato.
   O passo não segura identidade de R2 (o teste
   `test_every_step_holding_r2_runs_only_scripts_clear_of_the_dotenv` exige).
2. **No job `deposit`**, depois de `stage_green_run.py`: gravar o documento em
   `series/<run-id>/timeseries_rows.json` com `put_if_absent`. Nunca em
   `runs/`. Ensinar `retention.classify` o prefixo novo (RETAIN).
3. **Um workflow novo da série** (`v2_green_timeseries.yml`): `workflow_run`
   da publicação concluída com sucesso + `workflow_dispatch`. Job 1, só
   leitura (`v2-staging`): ponteiro → membros da release → documentos das
   rodadas → banco limpo → sinal. Job 2, a lane de PR do
   `PENDING_CAPABILITIES.md` §6: branch `auto/timeseries-<run id>`, recusa
   arquivo fora de `data/timeseries/`, squash-merge com o `GITHUB_TOKEN`.
   `shell: bash` e sem `exit 0` explícito (§6.1).
4. **A reconstrução**, se o dono escolher (a) em §7 do registro: dispatch
   manual que puxa de novo, como a conta verde, os compostos das aquisições da
   cadeia viva que entram na série e confere o hash contra o ledger. **Meça
   primeiro** com uma só data se o Earth Engine devolve o mesmo byte que em
   outubro; se não devolver, pare e leve ao dono.
5. **Testes que derrubem:** um job que escreve fora de `data/timeseries/`; um
   push direto na `main`; a publicação ganhando `contents: write`; o job da
   série com identidade de escrita no bucket.
6. **PR do site, rascunho:** `export_timeseries()` lê `regional_stats_v1`
   (`qa_status` conforme a decisão do dono) e volta a um job do robô de
   terça/sexta; `check_backend_release.py` valida o sinal novo.

## 4. Fronteiras duras

- Nenhum push na `main` de nenhum repositório; nenhuma mudança de ruleset ou
  de configuração. Nenhum `wrangler`, token Cloudflare ou broker.
- `detect_gee.yml` e `update_data.yml` não são reativados nem disparados.
- Nenhum dispatch de lane de produção para testar; escrita de objeto só em
  `araripe-v2-staging`.
- Nada mesclado antes de 2026-11-17 que mude o job `deposit` ou a publicação,
  sem aprovação explícita do dono. As PRs ficam como rascunho; o dono mescla.

## 5. Armadilhas já pagas

- `ee.Initialize()` ignora `GOOGLE_APPLICATION_CREDENTIALS` em CI; use
  `--service-account`.
- Um segredo de Environment num workflow chamado chega vazio.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório.
- `<<EOF` não citado executa os backticks: `git commit -F`.
- Um worktree novo não tem os 22,5 GB ignorados de `data/`: ligue por
  symlink e ponha os de diretório em `.git/info/exclude`.

## Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

A aba "Séries" ainda não anda. A primeira sessão mediu de onde a série nova
pode sair e escreveu a peça que calcula os números. Falta ligá-la às rotinas
automáticas e ao site.

### O que você precisa fazer

1. **Mesclar a PR da série verde (primeira parte)** quando quiser; ela não muda
   nada do que roda.
2. **Responder às duas perguntas**: se a série é refeita desde janeiro, e se o
   gráfico mostra só as imagens aceitas.
3. **Abrir uma sessão do Claude com este briefing**, de preferência depois de
   17/11.

### Tem algo preocupante?

Não. A série nova mede quase o mesmo que a antiga: nas 41 datas que as duas
têm, a média muda no máximo na terceira casa decimal.

### O que ainda falta no caminho

- **A série (D4B)** — ligar às rotinas, publicar por PR e o site ler o banco
  novo.
- **A vigia (C6B)** — até 17/11.
- **Avisar o tamanho antes de baixar** e **a frase da automação** — pacotes
  pequenos do site.
- **Fase 5** — a validação independente.
