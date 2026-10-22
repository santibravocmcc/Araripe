# Phase 6 — C3: desligar o acesso público de `araripe-cogs`

Escrito em 2026-10-22, logo depois do C2
([`PHASE_6ZM`](../implementation/PHASE_6ZM_2026-10-22.md)): a
`observatorio-site#50` mesclada pelo dono, o robô do site sem o job
`alertas`.
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: o passo é um clique do dono no painel; a sessão confere o "Antes"
> pela rede do navegador, pede o clique, e prova o "Depois" com leituras.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6ZM_2026-10-22.md | head -5
    gh workflow list -R santibravocmcc/Araripe --all --json path,state
    gh run list -R santibravocmcc/Araripe --workflow detect_gee.yml -L 1 --json databaseId,createdAt
    gh run list -R santibravocmcc/Araripe --workflow v2_green_status.yml -L 1 --json databaseId,event,conclusion,createdAt
    gh run list -R santibravocmcc/observatorio-site --workflow update-data.yml -L 2 --json databaseId,event,conclusion,createdAt

- Esperado: `PHASE_6ZM` na `main`; `detect_gee.yml` `disabled_manually`, as
  outras 14 `active`, e o último run dele ainda `39255074543`; o status mais
  recente `success`, com as linhas `ok` (leia o log, não a conclusão).
- **O "Depois" do C2 — a primeira terça ou sexta depois do merge.** O merge
  foi em 2026-10-22 18:04:09Z; o primeiro cron de `update-data.yml` depois
  dele é a **sexta 2026-10-23 06:00 UTC**. Leia esse run (e o de terça
  2026-10-27, se já houver) com
  `gh run view <id> -R santibravocmcc/observatorio-site --json jobs`:
  um job só, `chuva`, `success`; nenhum job `alertas`; nenhum passo com
  `R2_*` no log; um commit `chore: atualizar chuva (<data>)` na `main` do
  site; a página de chuva com a data nova. Registre os ids.
- **Se o run ainda tiver um job `alertas`**, o merge não chegou à `main` ou
  foi revertido: pare e registre, não peça o C3.
- **Se o job `chuva` falhar**, registre e siga com o C3 só se a falha for
  da fonte de chuva (rede do runner, MERGE fora do ar) e não do arquivo
  que a `#50` mudou; na dúvida, pare e pergunte.
- **Se o status tiver `late` ou `broken`**, ou uma rodada verde tiver
  falhado: pare, registre, e não peça o C3.

## 2. O que já está provado — não refazer

- O hostname público de `araripe-cogs`, lido pelo dono nas configurações do
  bucket no B0 (2026-10-14): `pub-5eb389cffff54421916187be69dd659b.r2.dev`
  (folha §5, B0; [`PHASE_6ZI`](../implementation/PHASE_6ZI_2026-10-14.md)).
- O B5 (2026-10-14, folha §5): sem parâmetro, `alertas`, `/` e
  `dados-abertos` não fazem **nenhum** pedido a `r2.dev` nem a
  `/data/alerts/`. O único `pub-5eb389…` fora de docs e testes no site é
  `src/js/alertas-fonte.js`, para `?dados=azul` (`PHASE_6Z` §3: o `grep` no
  bundle falha sempre, a checagem certa é de rede). Relido em 2026-10-19
  (`PHASE_6ZK` §3): nenhum `r2.dev` na carga padrão.
- C1 (2026-10-19) e C2 (2026-10-22) feitos: nada azul agendado escreve mais
  em `araripe-cogs` (`PHASE_6ZL`, `PHASE_6ZM`).

## 3. A tarefa

**Única tarefa: o passo C3 da [folha](PHASE_6_CUTOVER_RUNSHEET.md) §6 —
o dono desliga o acesso público `r2.dev` de `araripe-cogs` no painel.**

1. Refaça o "Antes" do C3 pela **rede do navegador** (o navegador embutido
   basta): carregue `alertas.html`, `/` e `dados-abertos.html` do domínio
   final sem parâmetro e confirme nenhum pedido a `pub-5eb389…r2.dev`.
   Leia também, só com `curl -sI` e o UA de um navegador real, um objeto
   conhecido em `https://pub-5eb389cffff54421916187be69dd659b.r2.dev/` —
   a linha de base que o "Depois" vai contradizer.
2. Peça ao dono, em uma frase, o clique: R2 → `araripe-cogs` → Settings →
   Public access → `r2.dev` → Disable. **Você não clica e não recebe
   credencial.** Sem o "desliguei" dele nesta sessão, pare aqui e entregue
   o registro do que conferiu.
3. Depois do clique: o mesmo `curl -sI` não devolve mais o objeto; as três
   páginas padrão continuam iguais (verde, as três datas, a visão completa
   pela rota); `?dados=azul` perde a visão completa — **aceito** pela folha.
   O status verde seguinte segue `ok`.

Entregue: o bloco "Feito em …" no C3 da folha (e o "Depois" do C2 lido, se
a sexta já rodou), um registro `docs/implementation/PHASE_6ZN_<data>.md`
com ids copiados das ferramentas, e o briefing do C4. Tudo numa PR de docs
do backend.

**Fora de escopo:** C4 (`site#21`) em diante; apagar qualquer objeto de
`araripe-cogs`; os scripts do site sem chamador; a `site#51`; D4, D5; o
broker.

## 4. Decisões de escopo já tomadas, com a base

- A ordem C1 → C6 e o "Antes" de cada passo são da folha §6.
- O C3 **não vai para o broker** (folha §6, C3): é um clique do dono.
- Nenhum objeto é apagado: o bucket azul fica inteiro, só sem a porta
  pública; a volta é reabilitar no mesmo lugar, e o hostname volta igual
  (folha §7).

## 5. Fronteiras duras

- Nenhuma escrita em lane, bucket, Worker, DNS ou rota. Nenhum merge.
- Nenhum `wrangler`, token Cloudflare, login, chamada à API da Cloudflare
  ou broker; recusar se oferecido. O painel é do dono.
- `detect_gee.yml` e `update_data.yml` nunca são disparados nem reativados.
- Nenhum rollback de ponteiro sem pedido do dono.

## 6. Armadilhas já pagas — não redescobrir

- A borda da Cloudflare devolve 403/1010 a cliente sem UA de navegador: um
  `curl` cru "prova" o acesso fechado antes do clique. Use o UA real e
  compare com a linha de base do §3.1.
- `gh workflow list` sem `--all` esconde os desligados.
- A `main` do site faz deploy de produção a cada push, inclusive o commit
  de chuva do robô.
- Uma rodada sem imagem termina `success` com `deposit` `skipped`; leia os
  jobs, não a conclusão.
- Testar o site num worktree fora de `site/` precisa de `../Araripe` em
  `origin/main` e de `node_modules`; sem eles, 7 testes Python e
  `producao_rota.test.mjs` falham por ambiente (`PHASE_6ZM` §3).
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório.
- `<<EOF` não citado executa os backticks: `git commit -F`.

## 7. Estado que o package herda

- Público no verde desde 2026-10-14; ponteiro seq. 23 `rel-g3-7b69385c…`
  (ou mais nova, depois da segunda 2026-10-26).
- `detect_gee.yml` `disabled_manually` desde 2026-10-19T23:03:30Z.
- Robô do site só com `chuva` desde o merge `e0bd263` (2026-10-22).
- Site em rascunho: `#21` (C4), `#51` (verificador).

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Só confirmar, na sexta, que o robô do site rodou apenas a parte da chuva e
deu certo. A próxima sessão faz essa leitura antes de qualquer outra coisa.

### O que você precisa fazer

1. **Mesclar a PR de documentação deste passo** — quando puder; não muda
   nada que roda.
2. **Abrir a próxima sessão do Claude com este briefing** — a partir de
   sexta, quando quiser fechar o acesso público antigo. Ela confere tudo e
   depois pede um clique seu no painel da Cloudflare.

### Tem algo preocupante?

Não. Os e-mails de falha do robô antigo do site param a partir da sexta; se
chegar mais um, avise a próxima sessão.

### O que ainda falta no caminho

- **Desligar o sistema antigo** — dois passos, cada um com o seu "sim":
  fechar o acesso público antigo, parar de guardar alertas no código do
  site.
- **Registrar a virada** — um documento que junta todos os passos.
- **Duas semanas de vigia** — conferir cada rodada.
- **Corrigir a frase da automação na página** — um pacote pequeno do site.
- **Avisar o tamanho antes de baixar** — um pacote pequeno do site.
- **A série de índices do sistema novo** — um pacote logo depois.
- **Fase 5** — a validação independente.
