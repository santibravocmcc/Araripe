# Phase 6 — o dia da virada: Fase B, hoje

Escrito em 2026-10-14, ao fim da sessão em que o dono revisou a folha e marcou
o dia ([`PHASE_6ZH`](../implementation/PHASE_6ZH_2026-10-14.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: é a Fase B de
> [`PHASE_6_CUTOVER_RUNSHEET.md`](PHASE_6_CUTOVER_RUNSHEET.md) — B0 a B6, no
> mesmo dia, com merges de produção feitos pelo dono. Cada passo para e
> pergunta. O roteiro é a folha; este briefing só diz por onde começar e o que
> já está medido.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6ZH_2026-10-14.md | head -5
    gh pr list -R santibravocmcc/Araripe --state open --json number,isDraft,headRefOid
    gh pr list -R santibravocmcc/observatorio-site --state open --json number,isDraft,headRefOid,baseRefName
    gh workflow run v2_green_status.yml --ref main -R santibravocmcc/Araripe

- Esperado: a PR de docs do A11 mesclada (o `PHASE_6ZH` existe na `main`);
  site em rascunho `#48` `95148a8`, `#42` `e2a33f5`, `#49` `6fc7491` (base
  `#42`), `#50` `ad710d8`, `#21` `ab65a55`; backend `#118` em rascunho.
- Status de 13:05Z (run `38568924312`): as sete linhas `ok`, ponteiro seq. 19,
  `alerts.observed` 2026-10-12.
- Se uma PR mudou de SHA, o status tem `broken`, ou o dia já não é
  2026-10-14: **pare e conte ao dono.**

## 2. O que já foi medido, para o executor não refazer

- A1–A9 e A11 têm bloco "Feito" na folha. A10 não foi feito (opcional).
- O A9 terminou 2026-10-14T12:54:32Z: vale para o B5 de hoje. Se a Fase B
  escorregar para depois de 2026-10-16, repita o A9 antes do B5.
- A `#48` está 1 commit atrás da `main` do site (a `#47`), `git merge-tree`
  limpo. O "Antes" do B1 pede rebaseá-la: `git rebase origin/main` e
  `git push --force-with-lease`, registrando o SHA anterior no corpo do
  commit, como no A4; `npm run test:worker` e `pytest` do site verdes antes de
  pedir o merge.
- A `#49` aponta para a `#42`: depois do B2, rebasear sobre a `main` do site e
  trocar a base da PR para `main` (bloco do A6).
- **Não medido:** se o token do Workers Builds aceita o binding de R2 no
  deploy (B1); se o `workflow_run` dispara a promoção encadeada (primeira
  rodada depois do B6, quinta 2026-10-15 06:00 UTC).

## 3. A tarefa

**Única tarefa: a Fase B da folha, B0 → B6, na ordem, hoje.**

1. Confirme o §1.
2. Execute cada passo como a folha o escreve (Quem, Aprovação, Antes, Faz,
   Depois, Volta). **Antes de cada passo com aprovação, peça ao dono o "sim"
   daquele passo e registre-o nas palavras dele.** Um "sim" vale para um passo.
3. Copie cada SHA, run e leitura da ferramenta que o produz.
4. Se um "Depois" falhar: aplique o "Volta" só com o "sim" do dono, pare e
   registre. Não remende em produção.
5. Se o tempo do dono acabar antes do B5, pare onde estiver — até o B5 o
   público vê o azul — e o resto fica para sábado 2026-10-17, com o A9 repetido
   na sexta.
6. Registro `docs/implementation/PHASE_6ZI_2026-10-14.md` (ou da data do último
   passo feito), bloco "Feito" em cada passo da folha, e o briefing seguinte:
   a leitura da primeira rodada agendada (critério "Antes" do C1). Tudo numa PR
   de docs do backend.

**Fora de escopo:** a Fase C (só depois da primeira rodada agendada lida
`ok`); o A10; qualquer mudança de workflow além das PRs já escritas; a série
temporal verde (D4); o broker.

## 4. Decisões de escopo já tomadas, com a base

- D0–D5 pelo dono em 2026-10-13; D6 = 2026-10-14 pelo dono em 2026-10-14
  (folha §3 e A11).
- Bucket: opção (a) — dono, 2026-09-30.
- Nenhuma publicação tem revisor; rollback pelo `v2-promotion` — 2026-10-02.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- **Todo merge é do dono.** A `main` do site faz deploy de produção; a do
  backend é só por PR. O agente prepara, verifica e pede.
- Nenhum `wrangler`, token Cloudflare, login ou broker. O que só o painel
  mostra (versão do Worker, hostname do `r2.dev`) o dono lê e passa. Se ele
  oferecer acesso à conta, recuse e diga por quê (`CLAUDE.md`).
- `detect_gee.yml` e `update_data.yml` nunca são disparados; nada é apagado
  em bucket nenhum.
- Nenhum valor de credencial; nenhum Environment alterado; nenhum agente
  aprova a própria run.

## 6. Armadilhas já pagas — não redescobrir

- O verificador ao vivo usa o `User-Agent` do cliente real; `Python-urllib`
  leva 403/1010 da borda.
- `grep` por `r2.dev` no bundle sempre acha `AZUL.fullBase`: a checagem do B5
  é de rede, na página padrão.
- A promoção encadeada lê o job `deposit`, não a conclusão da run.
- `automation.latest late` sem agenda é esperado até o B6.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório — no
  registro, SHA curto do site.
- `<<EOF` não citado executa os backticks: mensagem em arquivo e
  `git commit -F`.
- `node --test tests/` quebra no Node 25: use `npm run test:worker`.

## 7. Estado que o package herda

- Site em rascunho: `#48` (B1), `#42` (B2), `#49` (B5), `#50` (C2), `#21`
  (C4). Backend: `#118` (B6).
- Ponteiro verde na seq. 19; fila vazia até 2026-10-12.
- O azul parado desde 2026-09-03; o público vê o azul congelado em
  2026-08-30.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. Você aprovou o roteiro e marcou a virada para hoje.

### O que você precisa fazer

1. **Mesclar a PR de documentação desta sessão** — agora, antes de abrir a
   próxima sessão; ela não muda nada que roda, mas é dela que a próxima sessão
   lê o roteiro do dia.
2. **Abrir a próxima sessão do Claude com este briefing** — logo em seguida.
3. **Ficar disponível umas três horas** — para dizer "sim" a cada passo,
   mesclar as PRs e ler duas coisas no painel da Cloudflare quando pedido.

### Tem algo preocupante?

Não. Até o passo em que o público passa a ver os dados novos, nada que ele vê
muda; se o tempo acabar antes, dá para parar e continuar no sábado.

### O que ainda falta no caminho

- **A virada** — hoje, passo a passo, com a sua aprovação em cada um.
- **Ler a primeira rodada automática nova** — amanhã de manhã.
- **Desligar o sistema antigo** — depois dessa leitura.
- **A série de índices do sistema novo** — um pacote logo depois da virada.
- **Fase 5** — a validação independente.
