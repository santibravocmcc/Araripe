# Phase 6 — ler a primeira rodada verde agendada

Escrito em 2026-10-14, ao fim da sessão da Fase B da virada
([`PHASE_6ZI`](../implementation/PHASE_6ZI_2026-10-14.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: é leitura — quatro runs e uma página — contra critérios já
> escritos. O julgamento difícil (o que conta como "ok" quando não houve
> imagem nova) está decidido abaixo; o resto é copiar identificadores da
> ferramenta.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6ZI_2026-10-14.md | head -5
    git -C Araripe show origin/main:.github/workflows/v2_green_deposit_lane.yml | grep -n "cron"
    gh run list -R santibravocmcc/Araripe --workflow v2_green_deposit_lane.yml -L 3 --json databaseId,event,status,conclusion,createdAt
    gh run list -R santibravocmcc/Araripe --workflow v2_operational_publish.yml -L 3 --json databaseId,event,status,conclusion,createdAt
    gh run list -R santibravocmcc/Araripe --workflow v2_green_status.yml -L 3 --json databaseId,event,status,conclusion,createdAt

- Esperado: a PR de docs da Fase B mesclada (o `PHASE_6ZI` existe na
  `main`); `0 6 * * 1,4` no depósito; uma run de depósito com
  `event: schedule` criada em ou depois de 2026-10-15T06:00Z.
- **Se a rodada agendada ainda não rodou** (o cron do GitHub atrasou 40 min a
  12 h 10 min em setembro–outubro, `PHASE_6U` §2): pare e diga ao dono quando
  voltar. Não dispare nada à mão no lugar dela — uma rodada manual não prova o
  agendamento nem o `workflow_run`.

## 2. O que já foi medido, para o executor não refazer

- Fase B inteira na folha (blocos "Feito" de B0–B6). O público vê o verde
  desde 2026-10-14T16:36:27Z (build do merge `1978b15` do site).
- Ponteiro verde na seq. 21 `rel-g3-b1913263…` (o B3 fez 19 → 20 → 21 de
  ida e volta; a seq. 21 é a mesma release da 19). Contexto
  `ctx-g1-5b1ac5a0…` seq. 3 e fontes `src-g1-e9e0ba1a…` seq. 2 descrevem
  essa release.
- Status `38597782742` (2026-10-14, depois do B3): sete linhas `ok`.
- O ciclo rollback → reconciliador → rebuild funciona com a página no ar
  (B3). O reconciliador está agendado `41 */3` na `main` do site desde o B2.
- O verificador ao vivo certo é o da `observatorio-site#51` (rascunho,
  `ddf2599`); o da `main` do site cai numa checagem dele mesmo
  (`PHASE_6ZI` §3). Rode-o de uma cópia da branch
  `claude/p6-verificador-contexto` até a `#51` ser mesclada.
- **Não medido:** o `workflow_run` disparando a promoção encadeada, o
  `actions: read` e o `v2-promotion` aceitando esse evento (bloco do A5).

## 3. A tarefa

**Única tarefa: ler a primeira rodada verde agendada e dizer se ela cumpre o
"Antes" do C1.**

Leia, nesta ordem, copiando cada id da ferramenta:

1. **O depósito agendado** (`v2_green_deposit_lane.yml`, `event: schedule`):
   conclusão; o job `deposit` (`success` ou `skipped`); `chain=head`; a run
   depositada (`ci-<run id>`) ou o motivo (`no_acquisition`) no resumo.
2. **A promoção encadeada** (`v2_operational_publish.yml`,
   `event: workflow_run`): existe? qual run de depósito ela nomeia? Se o
   depósito depositou: `stage`, `promote`, `context`, `sources` com sucesso e
   o ponteiro na seq. 22. Se o job `deposit` foi `skipped`: a promoção não
   promove (o portão lê o job, não a conclusão — bloco do A5).
3. **O reconciliador do site** (`green_site_rebuild.yml`): se houve
   promoção, um commit vazio `deploy(verde): reconstruir para release=…` na
   `main` do site e o check run do Workers Builds `success`; depois
   `built-from.json` nomeando a release nova.
4. **O status agendado** (`v2_green_status.yml`, `event: schedule`, 12:00
   UTC): sete linhas `ok`, nenhum `late` nem `broken`.
5. **A página**, sem parâmetro: `alertas` mostra a release viva e as três
   datas; o verificador da `#51` passa.

**Critério, decidido aqui para não ser decidido no meio:**

- **Cumpre o "Antes" do C1** se 1–5 estão como acima **e** a promoção veio
  por `workflow_run`. Diga ao dono que o C1 pode ser feito.
- **Não cumpre ainda** se a rodada não teve aquisição (`deposit` `skipped`):
  o status pode estar `ok`, mas a promoção encadeada não foi exercitada.
  Registre e recomende esperar a rodada de segunda 2026-10-19 antes do C1.
- **Falhou** se qualquer run ficou vermelha, a promoção não veio depois de um
  depósito, ou o status tem `late`/`broken`: registre, **não remende**,
  ofereça o "Volta" da folha só com o "sim" do dono, e escreva o pacote do
  conserto como briefing seguinte.

Entregue: registro `docs/implementation/PHASE_6ZJ_<data>.md` com cada run e
leitura; e o briefing seguinte — a Fase C (C1 em diante) se cumpriu, ou a
nova leitura/o conserto se não. Tudo numa PR de docs do backend.

**Fora de escopo:** executar qualquer passo da Fase C (nem o C1 — o C1 tem
aprovação própria e entra no briefing seguinte); mesclar a `#51`; o aviso de
tamanho da visão completa (D5, pacote do site); a série temporal verde (D4);
o A10; o broker.

## 4. Decisões de escopo já tomadas, com a base

- D0–D5 pelo dono em 2026-10-13; D6 = 2026-10-14 (folha §3).
- D5 medida no B4: mediana 26 MiB; a virada seguiu e o aviso vira pacote.
- Bucket: opção (a) — dono, 2026-09-30.
- Nenhuma publicação tem revisor; rollback pelo `v2-promotion` — 2026-10-02.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- Esta sessão só lê. Nenhuma lane de escrita, nenhum rollback, nenhum
  disparo manual de depósito ou publicação.
- **Todo merge é do dono.** A `main` do site faz deploy; a do backend é só
  por PR.
- Nenhum `wrangler`, token Cloudflare, login ou broker. Se o dono oferecer
  acesso à conta, recuse e diga por quê (`CLAUDE.md`).
- `detect_gee.yml` e `update_data.yml` nunca são disparados; nada é apagado
  em bucket nenhum.

## 6. Armadilhas já pagas — não redescobrir

- **O azul também roda quinta 06:00** (`detect_gee.yml` segue ativo até o
  C1) e falha por contrato (`LegacyPersistenceStateError`, desde
  2026-09-03). É esperado; não é sinal sobre o verde.
- **O robô azul do site roda sexta 06:00** (`update-data.yml`, job `alertas`,
  até o C2). Também esperado.
- A promoção encadeada lê o job `deposit`, não a conclusão: uma rodada sem
  aquisição termina `success` com `deposit` `skipped`.
- O verificador ao vivo usa o `User-Agent` do cliente real; `Python-urllib`
  leva 403/1010 da borda.
- O verificador da `main` do site falha em "o header de contexto" por
  defeito dele; use o da `#51`.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório — no
  registro, SHA curto do site.
- `<<EOF` não citado executa os backticks: mensagem em arquivo e
  `git commit -F`.

## 7. Estado que o package herda

- Público no verde; azul inteiro em `?dados=azul` e no `r2.dev` até o C3.
- Site em rascunho: `#50` (C2), `#21` (C4), `#51` (o verificador). Backend:
  nenhuma PR de código aberta.
- Ponteiro verde seq. 21; agenda verde ativa desde 2026-10-14T16:50Z.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da virada de hoje. Fica só a correção do verificador (uma ferramenta de
conferência, não o site) esperando o seu merge, sem pressa.

### O que você precisa fazer

1. **Mesclar a PR de documentação desta sessão** — hoje; ela não muda nada
   que roda, mas é dela que a próxima sessão lê o que fazer.
2. **Abrir a próxima sessão do Claude com este briefing na quinta à tarde**
   (depois das 15h de Brasília), quando a primeira rodada automática nova já
   deve ter rodado.
3. **Mesclar a correção do verificador quando quiser** — pode esperar; não
   muda o que o público vê.

### Tem algo preocupante?

Não. O público já vê os dados novos, todas as checagens passaram, e o único
ponto ainda não provado — a primeira rodada automática — é o que a próxima
sessão lê.

### O que ainda falta no caminho

- **Ler a primeira rodada automática nova** — quinta.
- **Desligar o sistema antigo** — quatro passos, cada um com o seu "sim",
  depois dessa leitura.
- **Duas semanas de vigia** — conferir cada rodada.
- **Avisar o tamanho antes de baixar** — a visão completa de um dia típico
  passa de 25 MB; um pacote pequeno do site.
- **A série de índices do sistema novo** — um pacote logo depois.
- **Fase 5** — a validação independente.
