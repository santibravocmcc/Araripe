# Phase 6 — a lane de depósito verde em CI: responder por escrito, antes do código, de onde vêm os corpos da rodada

Escrito em 2026-09-27, depois de a decisão D5 fechar (histórico reprovado no R2
real e retenção estendida). Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é
para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: o código de depósito já existe e está provado (`assemble_green_run.py
> apply`, 74 objetos em 2026-09-16); o que falta é uma **pergunta de desenho com
> fronteira de credencial** — que identidade de Earth Engine uma lane verde pode
> usar, e como os corpos da rodada chegam ao bucket. Errar aqui é dar a uma lane
> verde uma autoridade de produção, que é mais caro do que qualquer defeito de
> código.

---

## 1. A dependência que precede tudo — confirme por conteúdo

Este briefing chega à `main` pela PR `#71`, com a extensão da retenção.

    git fetch origin
    git rev-parse origin/main
    git log origin/main --oneline --grep '#71'
    git show origin/main:config/green_promotion_history_reconstruction_v1.json | head -3
    git show origin/main:src/publication/retention.py | grep -c "release_never_live"
    git config core.hooksPath .githooks     # uma vez por clone

Se a reconstrução não estiver na `main`, a `#71` não entrou; nada deste pacote
depende dela para funcionar, mas a suíte e os números abaixo sim. **Não decida
por ancestralidade** — a `#70` entrou por merge commit e a `#71` pode entrar por
squash.

Medido em 2026-09-27, na branch da `#71`:

| repositório | comando | resultado |
| --- | --- | --- |
| backend | `/opt/anaconda3/envs/araripe/bin/python -m pytest -q` | **2119** — 2114 do código + 5 que `tests/test_handoff_prompt_method.py` roda **por briefing**, e este é um briefing novo |

Rode e use o número que sair, não este.

## 2. O que já foi verificado, para o executor não refazer

### 2.1 A D5 está fechada

[`../implementation/PHASE_6D_2026-09-27.md`](../implementation/PHASE_6D_2026-09-27.md):
sete disparos da `main` iguais à tabela do 6C §6, `verdict: consistent` nas
entradas 10–14, o registro 10 byte a byte o ponteiro de antes, e a retenção
lendo o histórico. O ponteiro verde está em `sequence 14`, no candidato
científico `rel-g1-fb722b2d…`. **Não há nada da D5 para refazer.**

### 2.2 O que o depósito já é — e o que falta

- `scripts/assemble_green_run.py` tem `plan` (sem store) e `apply` (escreve
  `runs/<run-id>/` com `put_if_absent`, `run.json` por último, nenhum ponteiro
  lido ou escrito). Provado contra o R2 real em 2026-09-16:
  `runs/rep-2026-08-30-v3/`, **74 objetos criados**, 12 min 35 s
  (`../implementation/PHASE_4C_2026-09-16.md` §4). Aquele depósito foi **local**,
  com o profile `araripe-r2-staging`.
- **Nenhum workflow roda o depósito.** O guarda
  `tests/test_phase6_precutover_checklist.py::test_a_revogacao_da_credencial_e_o_ultimo_passo_e_nao_o_primeiro`
  lê `.github/workflows/*.yml` e exige que nenhum contenha `assemble_green_run`.
  **No dia em que um workflow o rodar, esse teste falha de propósito** — e a
  mensagem dele diz o que fazer: avisar o dono de que a pré-condição para
  revogar a chave local está cumprida, e só então atualizar o teste e a
  condição em `config/phase6_owner_decisions_v1.json`
  (`d1_where_the_new_version_lives.revocation_ordering`).
- `apply` **não produz ledger**: `--ledger` é obrigatório e lido como bytes que
  o produtor selou. O produtor (`src/detection/ledger_v3.py`) **está na
  `main`** desde o landing do 2A.6 — a docstring de `assemble_green_run.py`
  ainda diz que não; é texto de 2026-09-08, desatualizado. Corrija-o quando
  tocar o arquivo.

### 2.3 A pergunta de desenho — medida, não respondida

Uma lane de depósito precisa dos **corpos** da rodada: as feições e o ledger que
uma detecção escreveu. Em CI isso quer dizer **rodar a detecção verde no
runner**, e a detecção usa Earth Engine. O que existe hoje, lido em 2026-09-27
com `gh api`:

| onde | segredos |
| --- | --- |
| repositório (qualquer workflow) | `GEE_SA_KEY`, `EE_PROJECT` — **os do azul**, usados por `detect_gee.yml` —, e as chaves R2 **de produção** (`R2_ACCESS_KEY`, `R2_SECRET_KEY`) |
| Environment `v2-staging` | `R2_STAGING_ACCESS_KEY_ID`, `R2_STAGING_SECRET_ACCESS_KEY`; variáveis `R2_STAGING_BUCKET`, `R2_ENDPOINT_URL`, `AWS_REGION` — **nenhuma credencial de Earth Engine** |
| Environments existentes | `cloudflare-green-control`, `v2-promotion`, `v2-staging` |

**Responda por escrito, antes de qualquer linha de código** (como o 6C §2 fez
para a D5):

1. **Que identidade de Earth Engine a lane verde usa?** Reusar `GEE_SA_KEY` do
   repositório é a saída óbvia e **pode** ser uma autoridade de produção: meça o
   que aquela conta de serviço pode fazer além de ler imagem (escrever assets?
   em que projeto? a cota é a mesma do azul?) **com chamada real**, não pela
   documentação — escopo de credencial só se prova com chamada recusada. Se a
   resposta for "uma identidade nova, num Environment verde", isso é ação do
   dono, e o briefing seguinte a pede.
2. **Onde a lane roda o replay**, e se cabe no runner: o replay de 2026-09-16
   leu e escreveu 1,78 GB e levou minutos; meça antes de assumir.
3. **Um job ou dois?** O depósito é lane 2 (identidade de candidato); a
   detecção não escreve no bucket. Separar autoridades, como
   `v2_operational_publish.yml` separa `stage` e `promote`, é o precedente.
4. **O que o `run_id` é**, e como o reexecutar não duplica nada
   (`put_if_absent` já recusa bytes diferentes na mesma chave — conferir que o
   montador é determinístico sobre as mesmas entradas).

Se a resposta à pergunta 1 exigir uma credencial que não existe, **pare e use a
skill `araripe-safe-handoff`** — não substitua por uma credencial mais ampla.

## 3. A tarefa

Desenhar por escrito e, se a identidade de Earth Engine permitir, construir a
lane que deposita uma rodada verde em `runs/<run-id>/` a partir da `main`, com
a identidade `v2-staging`, **sem** mover ponteiro — e provar um depósito real
de uma data já conhecida.

## 4. O escopo, na ordem em que se sustenta

1. As quatro respostas da §2.3, num documento de implementação novo, **antes**
   do código.
2. Se a identidade existir e for verde: o workflow, `workflow_dispatch` apenas,
   `permissions: contents: read`, Environment `v2-staging` (que **existe**;
   nunca nomeie um que não exista — o GitHub o cria sem proteção), grupo de
   concorrência `araripe-green-candidate`.
3. Testes que leem o workflow (como `tests/test_operational_publish_lane.py`
   faz para a lane de publicação) e a varredura de mutação.
4. Depois do merge: um depósito real de uma data que já tem release, num
   `run_id` novo, conferido por `stage_green_run.py` (só leitura). **Não
   promova** — a promoção já está provada; o que se prova aqui é o depósito.
5. Quando o guarda da revogação cair: **avisar o dono** e atualizar o teste e a
   condição, na mesma PR ou na seguinte.

**Fora de escopo, explicitamente:**

- **o agendamento** da lane (Seg/Qui) e a semeadura pela marca-d'água
  reconstruída — Phase 6 §4.5, e só com a virada;
- **mover o ponteiro verde** — nada neste pacote promove;
- **a virada**, o domínio final, o site;
- **revogar a chave local** — é do dono, e só depois do aviso;
- **a validação de acurácia** — Phase 5.

## 5. Decisões de escopo já tomadas, com a base

- **D1** — `araripe-v2-staging` é o bucket verde canônico;
  `config/phase6_owner_decisions_v1.json`.
- **A revogação da chave local espera um depósito em CI** — a mesma decisão,
  `revocation_ordering`, corrigida duas vezes e hoje ancorada em código.
- **Nenhum segundo produtor de ledger** — o montador usa o ledger que a
  detecção escreve.
- **Nada é apagado**, em nenhum bucket, nunca — fronteira de todo briefing
  desde o 2B.3, feita requisito em `../implementation/PHASE_4C_2026-09-16.md`
  §10. A D5 tornou a retenção decidível, não a exclusão possível.
- **As quatro decisões científicas da Phase 4** não reabrem.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 6. Fronteiras duras

- A `main` dos dois repositórios é **pull-request-only**, e **a `main` do site
  faz deploy de produção**.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare. Uma lane verde **não** pode herdar o cron deles.
- Nenhum workflow verde pode importar `config.settings`: ele carrega o `.env`
  de produção no import (`test_no_green_script_imports_the_dotenv_loader`, e o
  guarda é transitivo).
- Nunca aprove a sua própria requisição de Environment; nunca nomeie um
  Environment inexistente.
- Claude não recebe credencial de control-plane da Cloudflare; a allowlist do
  broker é exatamente `audit`, `enforce-worker-isolation`,
  `disable-site-branch-deploy`.
- **Não ligue** `green_site_publish.yml` ao Environment `v2-green-deploy`.

## 7. Armadilhas já pagas — não redescobrir

- **Mensagem de commit por arquivo, não por heredoc** — escreva-a em Python e
  use `git commit -F`. E **heredoc sem aspas come `\\`** também em scripts de
  teste: use `<<'EOF'`.
- **Depois de cada push, `gh pr list --head <branch> --state all`**: uma PR
  **MERGED** quer dizer que o próximo commit fica órfão.
- **Escopo de credencial só se prova com chamada recusada** — e com o cliente
  real, não um verificador próprio.
- **`ee.Initialize()` ignora `GOOGLE_APPLICATION_CREDENTIALS`**; em CI a conta
  de serviço é passada de outro jeito — leia como `detect_gee.yml` faz antes de
  copiar.
- **Uma mutação também sobrevive pelo motivo errado**: na varredura do 6D, uma
  mutação que eu escrevi era equivalente ao original. Leia o código mutado
  antes de concluir que um teste é fraco.
- **Limpe `__pycache__` e use `PYTHONDONTWRITEBYTECODE=1` antes de cada
  mutação.**
- **No zsh desta máquina, `echo =====` falha** (`= not found`); `grep` é
  `ugrep` e `grep -c` com zero casamentos sai 1.
- `botocore` 1.35.x tem `IfNoneMatch` mas não `IfMatch`; as lanes verdes
  instalam `boto3>=1.36.0`.

## 8. Estado que o pacote herda

- **PR `#71`** — a retenção que lê o histórico; esta sessão não depende dela
  para o depósito, só para a contagem da suíte.
- **Ponteiro verde:** `sequence 14`, `rel-g1-fb722b2d…`, histórico 10–14
  consistente. Sete releases em `releases/`, nenhuma apagada.
- **Worker verde implantado**, versão `ee433c7a-dbf7-43ae-95c6-98b57ee64327`,
  sem endereço público.
- **PRs abertas:** `observatorio-site#26` (o `RouteReader` recusado pela
  borda), sem mesclar.
- **A produção azul está parada**: seis execuções agendadas de `detect_gee.yml`
  falharam desde a última agendada bem-sucedida (2026-09-03, run
  `33747456220`) — a mais recente em 2026-09-24 (run `35993515768`), medido em
  2026-09-27. O conserto é a virada.
- **Achados esperando a sua vez:** o site atribui "Landsat 8/9" e o sistema só
  usa Sentinel-2; a visão completa pesa até 89,1 MiB por data; o índice não tem
  campo para a última tentativa de automação.
- **O token da NASA expira em 2026-11-06.**

## 9. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da tarefa anterior. O registro de versões foi provado no depósito de
verdade — sete movimentos, todos registrados certo, e a versão científica
voltou ao ar no fim. A regra de limpeza agora usa o registro para dizer, de
cada versão guardada, se ela já esteve no ar ou não. Continua sem apagar nada.

### O que você precisa fazer

1. **Aprovar e mesclar a mudança número 71 do backend.** Não é urgente e não
   muda nada no site: só ensina a regra de limpeza a ler o registro.
2. **Abrir a próxima sessão com este documento**, no modelo e esforço do topo.
3. **Aprovar e mesclar a mudança número 26 do site** — pode esperar; lembre que
   mesclar no site publica o site.
4. **Manter a chave de testes ativa** — não apague até eu avisar que o depósito
   automático existe. A próxima sessão é justamente a que constrói esse
   depósito, e pode ser que ela precise pedir a você uma credencial nova do
   Earth Engine só para a versão nova; se precisar, ela vai dizer exatamente
   qual e por quê.

### Tem algo preocupante?

Sim, o mesmo de antes: a detecção automática falhou seis vezes seguidas e o
site mostra dados de 30 de agosto. A próxima tentativa agendada (hoje cedo)
deve falhar também. O conserto é a virada; o depósito automático é um dos
passos que faltam até ela.

### O que ainda falta no caminho

- **Depósito automático** — a próxima sessão; hoje só eu, da minha máquina,
  coloco dados novos no depósito. É o que libera apagar a minha chave.
- **Detecção agendada da versão nova** — religar a detecção duas vezes por
  semana sobre o estado reconstruído; é o que tira o sistema da cegueira.
- **As páginas do site** — linguagem, fonte (tirar o Landsat), as três datas
  separadas, e as datas muito pesadas.
- **A virada** — o site passa a ler os dados novos no próprio domínio, e só
  depois o caminho antigo é desligado.
- **Fase 5** — a validação independente; até ela, nada é publicado como
  "precisão do sistema".
