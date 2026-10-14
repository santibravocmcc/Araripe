# Phase 6 — drenar a fila de depósito desde 2026-10-05

Escrito em 2026-10-14, ao fim da sessão que revogou a chave local de staging
([`PHASE_6ZF`](../implementation/PHASE_6ZF_2026-10-14.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: é o passo A9 de
> [`PHASE_6_CUTOVER_RUNSHEET.md`](PHASE_6_CUTOVER_RUNSHEET.md). Nenhum
> código: disparar duas lanes já provadas, na ordem, e ler o resultado. O
> cuidado é a ordem (depósito antes da publicação), nunca abrir uma segunda
> cadeia, e não confundir `no_acquisition` com falha.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    gh pr list -R santibravocmcc/Araripe --state open --json number,isDraft,headRefName
    gh pr list -R santibravocmcc/observatorio-site --state open --json number,isDraft,headRefName
    gh run list -R santibravocmcc/Araripe --workflow v2_green_deposit_lane.yml --limit 3
    gh workflow run v2_green_status.yml --ref main -R santibravocmcc/Araripe

- Esperado: site em rascunho `#48`, `#42`, `#49`, `#50`, `#21`; backend
  `#118` em rascunho e a PR de docs do A8 (mesclada ou não — confira por
  conteúdo: `git show origin/main:docs/implementation/PHASE_6ZF_2026-10-14.md`).
- A última rodada da lane de depósito é `37688510058` (2026-10-07,
  `no_acquisition`); a cabeça da cadeia é `ci-37686447368`, cobrindo até
  2026-10-04, e o ponteiro está na seq. 18 (`rel-g3-76601bbf…`).
- A run de status de 2026-10-14 (`38559580150`) leu tudo e falhou só por
  `automation.latest late` (6 dias, limite 5). **É esperado**: nenhuma agenda
  verde antes do B6. O "Antes" do A9 pede só *sem `broken`*; `late` não
  bloqueia.

## 2. O que já foi medido, para o executor não refazer

- A lane `v2_green_deposit_lane.yml` com `chain=head` deriva a cabeça do
  bucket e a janela: do dia seguinte ao último coberto até `hoje − 1`
  exclusivo (ou seja, até `hoje − 2`), no máximo 16 dias. Uma janela vazia
  não deposita e passa; uma de 16 dias vazia falha. Ela recusa continuar uma
  run que já tem filha (memória `araripe-cabeca-da-cadeia`).
- A publicação é `v2_operational_publish.yml` com `source=chain` (sem
  `run_id`): `stage` com `v2-staging`, `promote` com `v2-promotion`, nenhum
  revisor (decisão de 2026-10-02). Feita assim em 2026-10-07
  (`PHASE_6W_2026-10-07.md`, a release `rel-g3-76601bbf…`).
- Claude **não tem** credencial local do bucket desde 2026-10-14 (A8). Tudo
  pelas lanes; para ler o estado, `v2_green_status.yml`.
- O custo dominante é o estado (~1 GB por rodada; memória
  `araripe-release-da-cadeia`). Uma rodada por janela, não por dia.

## 3. A tarefa

**Única tarefa: o passo A9 da folha.**

1. `v2_green_status.yml` sem `broken` (`late` é aceito, §1).
2. `gh workflow run v2_green_deposit_lane.yml --ref main -R
   santibravocmcc/Araripe -f chain=head`. Espere terminar e leia o resumo:
   depositou (run id novo, datas cobertas) ou `no_acquisition`.
3. Se a janela de 16 dias não alcançou `hoje − 2`, repita o passo 2 (só
   depois do anterior terminar — a concorrência serializa, mas leia cada
   resultado).
4. Se alguma rodada depositou: `gh workflow run v2_operational_publish.yml
   --ref main -f source=chain`. Espere `stage` e `promote` com sucesso e
   anote a release nova e a seq. do ponteiro.
5. `v2_green_status.yml` de novo: `deposits.unpublished` ok e
   `alerts.observed` com no máximo 2 dias — ou o motivo (`no_acquisition`)
   no resumo da rodada. `automation.latest` volta a `ok`.
6. Bloco "Feito" no A9 da folha (run ids, release, seq.), registro
   `PHASE_6ZG_<data>.md`, e o próximo briefing — o A11 (revisão da folha
   pelo dono; o A10 é opcional e do dono). Tudo numa PR de docs do backend.

**Sobre "na véspera":** a fila volta a crescer um dia por dia até o B6. Se o
dia da virada ainda não estiver marcado (A11), drene agora e registre que
o passo 2 se repete na véspera — o mesmo comando, que só cobre o que faltar.

**Fora de escopo:** qualquer merge (`#118` é o B6); rollback do ponteiro
(só a pedido do dono); mexer em workflow; depósito local de qualquer tipo.

## 4. Decisões de escopo já tomadas, com a base

- Bucket: opção (a) — dono, 2026-09-30 (`PACKAGE_P6_PROMPT.md` §3).
- Nenhuma publicação tem revisor; rollback pelo `v2-promotion` — 2026-10-02.
- D0–D6 da folha, decididas em 2026-10-13; D2 (depósito pendente > 1 dia é
  `late`) e D3 (status diário) só valem depois do B6.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- Nenhum valor de credencial; nenhuma chave nova; nenhum Environment
  alterado.
- Nenhum `wrangler`, token Cloudflare ou broker.
- Nenhuma `from_run` nem `empty` sem o dono: só `chain=head` mantém uma
  cadeia só.
- A `main` do backend é só por PR; a do site faz deploy — nenhum merge.

## 6. Armadilhas já pagas — não redescobrir

- A promoção lê o job `deposit`, não a conclusão da run (memória
  `araripe-agenda-verde`).
- `last_seen` pode andar para trás; não é invariante.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório — no
  registro, SHA curto do site.
- `<<EOF` não citado executa os backticks do corpo: mensagem em arquivo e
  `git commit -F`.

## 7. Estado que o package herda

- Site em rascunho: `#48` (B1), `#42` (B2), `#49` (B5, base `#42`), `#50`
  (C2), `#21` (C4). Backend: `#118` (B6).
- Chave do Claude revogada; a do Environment `v2-staging` viva.
- O azul parado desde 2026-09-03.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. A chave antiga do Claude foi apagada, a do robô do GitHub continua
funcionando, e esta máquina não guarda mais nenhuma chave do bucket novo.

### O que você precisa fazer

1. **Desconectar o acesso da Cloudflare que você ligou nesta sessão** — pode
   esperar, mas não deve ficar: ele alcança a conta inteira, inclusive o site
   público, e o Claude não pode usá-lo.
2. **Revisar e mesclar a PR de documentação desta sessão** — pode esperar;
   não muda nada que roda.

### Tem algo preocupante?

Não. O aviso vermelho de "automação atrasada" é esperado: o sistema novo só
roda sozinho depois da virada, e a próxima sessão processa os dias acumulados.

### O que ainda falta no caminho

- **Processar os dias acumulados** — a próxima sessão; repete-se na véspera.
- **Você revisar o roteiro e marcar o dia** (quarta ou sábado de manhã).
- **A virada** — executar o roteiro, com a sua aprovação em cada passo que
  mexe no site público.
- **Desligar o sistema antigo** — depois da primeira rodada automática nova.
- **A série de índices do sistema novo** — um pacote logo depois da virada.
- **Fase 5** — a validação independente.
