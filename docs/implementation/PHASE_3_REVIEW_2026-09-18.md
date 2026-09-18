# A revisão pré-cutover do dono — FEITA em 2026-09-18

**O bullet do roadmap:** *"an explicit **pre-cutover** review of the runbook and
resolved targets"*. Este documento é essa revisão, e com ela **o portão 1 da
Phase 6 está fechado**.

**Base verificada:** `origin/main` em
`9e1279e64edf5019c2a45f995820bb4e06d8ccca`.

## O que foi confirmado, e sobre qual texto

A lista de [`../operations/PHASE_3_REPLAY_RUNBOOK.md`](../operations/PHASE_3_REPLAY_RUNBOOK.md)
§7 foi **reescrita contra o presente em 2026-09-17** antes de ser submetida,
porque três das suas quatro cláusulas abertas tinham deixado de descrever o
mundo. O dono revisou a lista **reescrita**, não a original — e essa distinção é
o registro que importa aqui.

Confirmados em 2026-09-18, com a resposta literal *"3 itens confirmados"*:

1. **Os alvos resolvidos da §1 continuam certos.** Reconferidos no código em
   2026-09-17: `pytest tests/test_replay_freeze.py` → **55/55**, que é o guarda
   que cai se um nome mudar no código e não no runbook. Os Environments foram
   relidos do GitHub na mesma data — o backend tem três
   (`cloudflare-green-control` **com** revisor, `v2-promotion` e `v2-staging`
   sem, todos com política de branch `main`), e o repositório do site
   continua com **`[]`**.
2. **O corte é o literal `2026-08-30`.** A regra da §2.2 foi **exercida**, não
   aceita em abstrato: `resolve_recorded_cutoff` tomou as datas terminais do
   ledger `pl-v3-af8d6c78fb2ad7fa15e40a47e631fd9596ece4b519c22b5fd6e6dccf731b4442`
   e fixou o literal com `date_is_provisional: false`
   ([`PHASE_4B_2026-09-09.md`](PHASE_4B_2026-09-09.md) §9). **Com a ressalva
   registrada:** a fila pós-corte de 3 datas foi enumerada sobre
   `2026-08-31..2026-09-10`, janela que fechou — ela é **re-enumerada** no passo
   1 da drenagem, e o número antigo não é reusado.
3. **A produção azul está PARADA, e a cláusula original afirmava o contrário.**
   O que foi confirmado é o procedimento da §3 **com a premissa corrigida**:
   quatro execuções agendadas de `detect_gee.yml` falharam — 2026-09-10,
   2026-09-14 e 2026-09-17 com `LegacyPersistenceStateError`, mais 2026-09-07
   por outra causa — e a última escrita em produção foi a execução **manual** de
   2026-09-07 15:15 UTC (run `34137318406`). O procedimento em si foi executado
   e fechou; o que caiu foi a última frase dele.

## Os outros dois itens, fechados por decisão e não por revisão

A lista reescrita tinha cinco itens abertos. Dois fecharam em 2026-09-18 pelas
decisões D1 e D5 do dono, registradas em
[`../../config/phase6_owner_decisions_v1.json`](../../config/phase6_owner_decisions_v1.json):

- **onde os dados da versão nova vivem** → **D1: promover `araripe-v2-staging`**;
- **o ponteiro verde vira público sem revisor nem histórico** → **D5: construir
  o histórico durável antes da virada**.

## O que esta revisão NÃO autoriza

- **não autoriza a virada.** Ela fecha o portão 1 de quatro. Os portões 2
  (hostname do Worker verde) e 3 (Environment protegido no site) continuam
  **fechados**, e cada passo do §4.4 que afeta produção espera aprovação
  explícita no momento em que for executado;
- **não autoriza revogar `claude-araripe-v2-staging-rw`.** A revogação é o
  **último** passo da D1, depois de a D5 estar construída e reprovada;
- **não muda nenhuma das quatro decisões científicas da Phase 4**, que não
  reabrem;
- **não permite afirmação de acurácia** em nada publicado. Isso é Phase 5.

## Como esta revisão é guardada em teste

`tests/test_replay_freeze.py::test_o_runbook_declara_a_revisao_pre_cutover_ainda_aberta`
existia para impedir o runbook de se declarar revisado por conta própria, e a
sua docstring dizia: *"se algum dia todos fecharem, este teste cai e a linha tem
de mudar deliberadamente"*. **Este é esse dia**, e a mudança é deliberada: o
teste passou a exigir o inverso — que a revisão, quando declarada feita, carregue
data, autorização e os itens nomeados, e que o documento não a declare feita sem
este arquivo existir.

`tests/test_phase6_precutover_checklist.py` guarda a distinção que gerou este
documento: `review_performed: true` só é aceito com registro datado. Uma
resposta de **cronograma** — *"revisar agora"* — não fecha o portão, e há
mutação verificada que derruba a tentativa.
