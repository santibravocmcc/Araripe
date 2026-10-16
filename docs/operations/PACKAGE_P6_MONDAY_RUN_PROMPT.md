# Phase 6 — ler a rodada verde de segunda 2026-10-19

Escrito em 2026-10-16, depois da leitura da primeira rodada agendada
([`PHASE_6ZJ`](../implementation/PHASE_6ZJ_2026-10-16.md)), que rodou sem
imagem e por isso não exercitou a promoção.
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: a mesma leitura de
> [`PACKAGE_P6_FIRST_SCHEDULED_RUN_PROMPT.md`](PACKAGE_P6_FIRST_SCHEDULED_RUN_PROMPT.md),
> com os critérios já escritos; o que muda é a rodada e o que já está provado.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6ZJ_2026-10-16.md | head -5
    gh run list -R santibravocmcc/Araripe --workflow v2_green_deposit_lane.yml -L 3 --json databaseId,event,status,conclusion,createdAt
    gh run list -R santibravocmcc/Araripe --workflow v2_operational_publish.yml -L 3 --json databaseId,event,status,conclusion,createdAt
    gh run list -R santibravocmcc/Araripe --workflow v2_green_status.yml -L 3 --json databaseId,event,status,conclusion,createdAt

- Esperado: o `PHASE_6ZJ` na `main`; uma run de depósito `event: schedule`
  criada em ou depois de 2026-10-19T06:00Z, e uma de status `schedule` depois
  das 12:00Z do mesmo dia. Em 10-15 o GitHub atrasou o depósito ~5 h e o
  status ~4,6 h.
- **Se a rodada de segunda ainda não rodou:** pare e diga ao dono quando
  voltar. Nunca dispare depósito ou publicação à mão no lugar dela.

## 2. O que já está provado — não refazer

Da rodada de 2026-10-15 (`PHASE_6ZJ` §2): o `schedule` do depósito roda da
`main` com `chain=head`; o `workflow_run` dispara a publicação; o `gate` lê
o job `deposit` da tentativa que disparou e não promove quando ele é
`skipped`; o `schedule` do status roda e lê tudo.

**Falta só:** a promoção vinda da agenda — `stage`, `promote` (o
`v2-promotion` aceitando o job de `workflow_run`), `context` e `sources` — e
o reconciliador reconstruindo o site depois dela.

A janela de segunda vai de 2026-10-13 a 2026-10-17 (fim exclusivo 10-18):
cinco dias, contra uma passagem a cada 1–3 dias medida no A9.

## 3. A tarefa

**Única tarefa: ler a rodada de segunda pelo §3 de
[`PACKAGE_P6_FIRST_SCHEDULED_RUN_PROMPT.md`](PACKAGE_P6_FIRST_SCHEDULED_RUN_PROMPT.md)**
— as cinco leituras (depósito, promoção encadeada, reconciliador, status,
página) e o mesmo critério de três saídas: cumpre o "Antes" do C1, não
cumpre ainda (de novo sem imagem — então a rodada de quinta 10-22), ou
falhou (registrar, não remendar, oferecer o "Volta" só com o "sim" do dono).

Se cumprir, confira também: o ponteiro na seq. 22, `built-from.json` com a
release nova, e o verificador da `observatorio-site#51` (ou da `main` do
site, se ela já tiver sido mesclada) passando contra o domínio.

Entregue: registro `docs/implementation/PHASE_6ZK_<data>.md` e o briefing
seguinte — a Fase C (C1 em diante) se cumpriu; a próxima leitura ou o
conserto se não. Tudo numa PR de docs do backend.

**Fora de escopo:** qualquer passo da Fase C; mesclar a `#51`; o aviso de
tamanho da visão completa (D5); a série temporal verde (D4); o broker.

## 4. Decisões de escopo já tomadas, com a base

- D0–D6 na folha §3; D5 medida no B4 (`PHASE_6ZI` §4).
- Critério de leitura: `PACKAGE_P6_FIRST_SCHEDULED_RUN_PROMPT.md` §3,
  aplicado em `PHASE_6ZJ` ("não cumpre ainda").
- Bucket (a), 2026-09-30; nenhuma publicação tem revisor, 2026-10-02.

## 5. Fronteiras duras

- Só leitura. Nenhuma lane de escrita, nenhum rollback, nenhum disparo
  manual de depósito ou publicação.
- **Todo merge é do dono.**
- Nenhum `wrangler`, token Cloudflare, login ou broker; recusar se oferecido.
- `detect_gee.yml` e `update_data.yml` nunca são disparados; nada é apagado.

## 6. Armadilhas já pagas — não redescobrir

- O e-mail de falha do `detect_gee.yml` (azul) chega toda segunda e quinta
  até o C1, e o do robô azul do site (`update-data.yml`, job `alertas`) toda
  terça e sexta até o C2. Esperados; nenhum é sinal sobre o verde.
- Uma rodada sem imagem termina `success` com `deposit` `skipped`, e a
  publicação também `success` com tudo `skipped`. Leia os jobs, não a
  conclusão.
- `alerts.observed` só avança com depósito; uma rodada `no_acquisition` não
  muda a data olhada.
- O verificador da `main` do site cai em "o header de contexto" por defeito
  dele; use o da `#51` até ela ser mesclada.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório.
- `<<EOF` não citado executa os backticks: `git commit -F`.

## 7. Estado que o package herda

- Público no verde desde 2026-10-14; ponteiro seq. 21 `rel-g3-b1913263…`;
  cabeça da cadeia `ci-38561001665`.
- Site em rascunho: `#50` (C2), `#21` (C4), `#51` (verificador).

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

A prova de que a publicação automática funciona de ponta a ponta. A rodada
de quinta rodou sozinha e sem erro, mas não havia imagem nova no único dia
que ela olhou, então não houve nada para publicar.

### O que você precisa fazer

1. **Mesclar a PR de documentação desta leitura** — quando puder; não muda
   nada que roda.
2. **Abrir a próxima sessão do Claude com este briefing na segunda à tarde**
   (depois das 15h de Brasília).

### Tem algo preocupante?

Não. O sistema novo rodou sozinho na hora certa (com o atraso de sempre do
GitHub), decidiu certo que não havia o que publicar, e o site continua no
verde.

### O que ainda falta no caminho

- **Ler a rodada de segunda** — a primeira com chance real de imagem nova.
- **Desligar o sistema antigo** — quatro passos, cada um com o seu "sim".
- **Duas semanas de vigia** — conferir cada rodada.
- **Avisar o tamanho antes de baixar** — um pacote pequeno do site.
- **A série de índices do sistema novo** — um pacote logo depois.
- **Fase 5** — a validação independente.
