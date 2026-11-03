# D4 — a série temporal verde: a aba "Séries" volta a andar

Escrito em 2026-11-03, no fecho da Phase 6
([`PHASE_6ZP_2026-11-03.md`](../implementation/PHASE_6ZP_2026-11-03.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: é código novo numa lane que roda sozinha em produção, com duas
> autoridades (o bucket verde e a `main` protegida do backend) e um consumidor
> noutro repositório. O risco é reabrir um push direto na `main`, misturar a
> série azul congelada com a verde sem dizer, ou afirmar que a série verde
> mede o mesmo que a azul sem medir.

**Origem:** decisão D4 da folha da virada, tomada pelo dono em 2026-10-13
(`PHASE_6_CUTOVER_RUNSHEET.md` §3): *virar sem a série atualizada, com a
data dela dita na página, e a série verde como pacote logo depois da
virada.* Este é esse pacote. Pode correr em paralelo com o C6B
(`PACKAGE_P6_WATCH_B_PROMPT.md`), que só lê; nada aqui muda as lanes que o
C6B vigia antes de a PR ser mesclada pelo dono.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6ZP_2026-11-03.md | head -5
    git -C Araripe log -1 --format='%h %cI %s' origin/main -- data/timeseries/
    git -C site log -1 --format='%h %cI %s' origin/main -- public/data/timeseries/series.json
    gh api repos/santibravocmcc/Araripe/actions/permissions/workflow
    /opt/anaconda3/envs/araripe/bin/python -m pytest -q

- Esperado: `PHASE_6ZP` na `main`; a última escrita em `data/timeseries/`
  é `5574b1f` `chore: update time-series 2026-09-07 (#30)` de
  2026-09-07T15:52:44Z (lido em 2026-11-03).
- Anote a contagem do pytest na base antes de mudar qualquer linha.

## 2. O que já foi verificado — não refazer

Lido em 2026-11-03 na `main` dos dois repositórios:

- **Quem escreve a série hoje: ninguém.** O único produtor de linhas
  `regional_stats` é `store_regional_stats` (`src/timeseries/builder.py:72`),
  chamado em `scripts/run_detection_from_gee.py:191` — o caminho **azul** do
  `detect_gee.yml`, `disabled_manually` desde 2026-10-19 (C1) e falhando
  desde 2026-09-03. `update_data.yml` é só manual e não é disparado.
- **A lane verde não grava série.** `git grep` por `store_regional_stats` e
  `timeseries` em `scripts/replay_2026.py`, `scripts/assemble_green_run.py` e
  `.github/workflows/v2_green_deposit_lane.yml`: nenhum resultado. A única
  série verde já escrita são 2 linhas na base isolada `timeseries_replay.db`
  do replay da Phase 4 (`PHASE_4B_2026-09-09.md` §9,
  `scripts/finalize_replay_candidate.py:52`).
- **A publicação verde não pode commitar, por construção.**
  `v2_operational_publish.yml` tem `permissions: contents: read`, e
  `tests/test_operational_publish_lane.py` o exige. Isso é desenho, não
  lacuna: não mude.
- **A lane de PR da série** (`PENDING_CAPABILITIES.md` §6): o job grava
  `data/timeseries/` numa branch `auto/timeseries-<run id>`, abre PR, recusa
  qualquer arquivo fora de `data/timeseries/` e faz squash-merge com o
  `GITHUB_TOKEN` (o ruleset exige zero aprovações). Funcionou em produção de
  2026-08-20 a 2026-09-07 (`#13`, `#14`, `#30`). Ela vive hoje em
  `detect_gee.yml` (linhas ~156–180) e `update_data.yml` (~105–126). O sinal
  `data/timeseries/RELEASE.json` (`scripts/write_release_signal.py`, schema
  `araripe.timeseries.release/1`) vai no mesmo commit.
- **O que o site lê.** `site/scripts/prepare_data.py` `export_timeseries()`
  lê `data/timeseries/timeseries.db` do checkout do backend
  (`regional_stats`, `index_name` em `ndmi`/`nbr`/`evi2`, `region='full_aoi'`,
  `date >= 2026-01-01`) e grava `public/data/timeseries/series.json`, com a
  linha de base mensal dos rasters de `data/baselines/` (ou a já publicada,
  se os rasters faltam no CI). O job que rodava isso, `alertas`, saiu do
  `update-data.yml` no passo A7/C2; o cabeçalho do workflow diz que a série
  fica congelada até este pacote. `site/scripts/check_backend_release.py`
  valida o `RELEASE.json` antes de usar a base.
- **O que a página mostra hoje.** `series.json` na `main` do site tem 55
  pontos por índice, o último em **2026-08-30**, escrito por `4c638a5`
  (2026-09-01). A base do backend vai até 2026-09-07, mas o site nunca
  chegou a ler essa versão.
- **Negativo:** nenhuma branch ou PR aberta com uma série verde foi achada
  pela sessão do C6 — confira de novo com
  `gh pr list -R santibravocmcc/Araripe --state all --search timeseries`.

## 3. A tarefa

**Fazer a série da aba "Séries" sair das rodadas verdes, automática, sem
push direto na `main` do backend.** Uma PR no backend e, se precisar, uma
no site. Nenhuma das duas é mesclada pelo agente.

## 4. O escopo, na ordem em que se sustenta

1. **Medir de onde a série verde pode sair.** A rodada de depósito já
   calcula os índices por data para detectar. Ache onde (no `replay_2026.py
   run` ou no que ele chama) e se o `runs/<id>/` do bucket guarda o que
   basta para a média e o desvio por índice em `full_aoi`. Responda com
   arquivo e linha. **Unidade:** a azul é por composto de data; a verde é por
   datatake sob `datatake_mosaic-v1`. Diga se o valor de uma data é
   comparável, e não afirme que é sem medir numa data que as duas têm.
2. **O produtor.** Um passo novo que, a cada rodada que depositou, grava as
   linhas daquela janela. Recomendação a confirmar: gravar a série como
   produto da rodada (no `runs/<id>/`, sem git), e um job **separado** da
   publicação — porque a publicação é `contents: read` — que, depois da
   promoção, monta `timeseries.db` e o sinal e os publica **pela lane de PR
   do §6, sempre por PR**. Escritas são `INSERT OR REPLACE` por
   `UNIQUE(date, index_name, region)`: uma rodada repetida não duplica.
3. **De onde a série começa.** A cadeia verde cobre desde 2026-01-02. A
   página mostra desde 2026-01-01. Proponha ao dono: reconstruir a série
   verde inteira a partir da cadeia, ou só daqui para frente com a azul até
   2026-08-30. Não misture as duas na mesma linha sem marcar a fonte.
4. **O consumidor.** O que o site precisa para voltar a gerar `series.json`
   a partir da base nova — provavelmente devolver o `export_timeseries()` a
   um job do robô de terça/sexta. Isso é uma PR do site, rascunho, e é o
   dono quem mescla, porque a `main` do site faz deploy.
5. **Testes** que derrubem: um job que tente escrever fora de
   `data/timeseries/`; um push direto na `main`; a publicação ganhando
   `contents: write`.

**Fora de escopo, com dono:** o C6B (vigia, `PACKAGE_P6_WATCH_B_PROMPT.md`);
mover `timeseries.db` para fora do git (o "structural follow-up" do §6 —
pacote próprio, porque muda a base canônica); qualquer afirmação de acurácia
(Phase 5); o aviso de tamanho (D5) e a frase da automação (pacotes do site);
a Phase 7; o robô do IBAMA.

## 5. Decisões de escopo já tomadas, com a base

- D4 = 1: a série verde é pacote depois da virada (folha §3).
- A `main` do backend é só por PR, sem exceção nem para o bot
  (`AGENTS.md`, `PENDING_CAPABILITIES.md` §6). Uma GitHub App ou deploy key
  na lista de bypass já foi rejeitada lá. Não reabrir.
- A publicação verde não tem git (`v2_operational_publish.yml`, Package
  2B.2C). Não reabrir.
- A série tem de continuar automática (ROADMAP §1.1).

## 6. Fronteiras duras

- Nenhum push na `main` de nenhum repositório; nenhuma mudança de ruleset,
  de lista de bypass ou de configuração do repositório.
- Nenhum `workflow_dispatch` de lane de produção; teste a lane nova numa
  branch ou com uma base descartável.
- Escrita em objeto só em `araripe-v2-staging`, só se o escopo pedir, e
  nunca em `araripe-cogs`.
- Nenhum `wrangler`, token Cloudflare, login ou broker.
- `detect_gee.yml` e `update_data.yml` não são reativados nem disparados.

## 7. Armadilhas já pagas — não redescobrir

- `bash -l {0}` com `setup-miniconda` e `exit 0` explícito sai com 1
  (`PENDING_CAPABILITIES.md` §6.1): o passo de publicação usa `shell: bash`
  e termina sem `exit 0`.
- Um segredo de Environment num workflow chamado chega vazio; `inherit`
  traria o azul.
- `ee.Initialize()` ignora `GOOGLE_APPLICATION_CREDENTIALS` em CI.
- `config.settings` carrega o `.env` de produção: nenhum script verde o
  importa.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório.
- `<<EOF` não citado executa os backticks: `git commit -F`.
- Decidir merge por conteúdo ou pelo assunto `(#N)`, nunca por
  ancestralidade.

## 8. Estado que o package herda

- Phase 6 fechada em 2026-11-03 (C6 encurtado); C6B aberto até 2026-11-17.
- Ponteiro verde seq. 26 `rel-g3-79eef163…`, cabeça `ci-41466713190` até
  2026-10-31.
- Série na `main` do backend até 2026-09-07; `series.json` do site até
  2026-08-30.

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada desta etapa ainda: ela começa na próxima sessão.

### O que você precisa fazer

1. **Abrir uma sessão do Claude com este briefing** — quando quiser; pode
   ser antes do fim da vigia, porque não mexe no que roda até você mesclar.
2. **Decidir, quando a sessão perguntar, de onde a série começa** — refeita
   desde janeiro pelo sistema novo, ou só daqui para frente.

### Tem algo preocupante?

Não. A aba "Séries" está parada no fim de agosto e a página diz a data; nada
se perde enquanto isso.

### O que ainda falta no caminho

- **Esta série (D4)** — fazer a aba "Séries" voltar a andar sozinha.
- **A vigia que continua (C6B)** — quatro rodadas de novembro e as partes
  novas do site, até 17/11.
- **Avisar o tamanho antes de baixar** — um pacote pequeno do site.
- **Corrigir a frase da automação na página** — um pacote pequeno do site.
- **Fase 5** — a validação independente.
