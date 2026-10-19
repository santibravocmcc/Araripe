# Phase 6 — C1: parar o agendamento azul

Escrito em 2026-10-19, depois da leitura da rodada verde de segunda
([`PHASE_6ZK`](../implementation/PHASE_6ZK_2026-10-19.md)), que depositou,
promoveu para a seq. 22 e reconstruiu o site sozinha.
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: um comando, já escrito na folha, mas o primeiro passo da Fase C —
> mexe numa lane azul de produção e precisa do "sim" do dono nesta sessão.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6ZK_2026-10-19.md | head -5
    gh workflow list -R santibravocmcc/Araripe --all --json name,path,state
    gh run list -R santibravocmcc/Araripe --workflow v2_green_status.yml -L 1 --json databaseId,event,conclusion,createdAt

- Esperado: o `PHASE_6ZK` na `main`; `detect_gee.yml` `active`; o status mais
  recente `success`.
- **Se o status mais recente tiver `late` ou `broken`**, ou se uma rodada
  verde depois de 2026-10-19 tiver falhado: pare, registre, e não faça o C1 —
  o "Antes" dele deixou de valer.

## 2. O que já está provado — não refazer

`PHASE_6ZK` §4: a agenda verde inteira rodou de ponta a ponta em 2026-10-19
— depósito `schedule` com `chain=head`, publicação por `workflow_run`,
`stage`/`promote`/`context`/`sources`, ponteiro na seq. 22, reconciliador do
site, `built-from.json` com a release nova, status com sete `ok`, verificador
da `site#51` 61 PASS. O "Antes" do C1 está cumprido; não releia a rodada.

## 3. A tarefa

**Única tarefa: o passo C1 da
[folha](PHASE_6_CUTOVER_RUNSHEET.md) §6 — desligar o agendamento de
`detect_gee.yml`, com o "sim" explícito do dono nesta sessão.**

1. Pergunte ao dono, em uma frase, se pode desligar o agendamento azul agora.
   Sem um "sim" escrito por ele nesta sessão, pare: o C1 é dele.
2. Com o "sim": `gh workflow disable detect_gee.yml -R santibravocmcc/Araripe`.
   O arquivo do workflow fica byte-idêntico — não edite nada nele.
3. Confira: `gh workflow list -R santibravocmcc/Araripe --all` mostra
   `detect_gee.yml` `disabled_manually`; nenhuma outra lane mudou de estado.
4. Na quinta 2026-10-22, se a sessão ainda estiver aberta, ou na sessão
   seguinte: nenhum run novo de `detect_gee.yml`, e a rodada verde de quinta
   lida como no C6.

Entregue: o bloco "Feito em …" no C1 da folha, um registro
`docs/implementation/PHASE_6ZL_<data>.md` com o comando, a saída e a
listagem antes/depois, e o briefing do C2 (merge da `site#50`, só o dono).
Tudo numa PR de docs do backend.

**Fora de escopo:** C2 em diante (cada um tem a sua aprovação); a frase da
automação que envelhece depois da promoção (`PHASE_6ZK` §5, pacote do site);
mesclar a `site#51`; D4, D5; o broker.

## 4. Decisões de escopo já tomadas, com a base

- D0–D6 na folha §3; a ordem C1 → C2 → C3 → C4 → C5 → C6 é da folha §6.
- O C1 desliga, não apaga: `disable`, nunca editar nem remover o arquivo
  (a Phase 6 promete o arquivo byte-idêntico).
- Critério de leitura cumprido em `PHASE_6ZK` §4.

## 5. Fronteiras duras

- O único comando de escrita é o `gh workflow disable` do C1, e só com o
  "sim" do dono nesta sessão.
- **Todo merge é do dono.**
- Nenhum `wrangler`, token Cloudflare, login ou broker; recusar se oferecido.
- `detect_gee.yml` e `update_data.yml` nunca são disparados; nada é apagado.
- Nenhum rollback de ponteiro sem pedido do dono.

## 6. Armadilhas já pagas — não redescobrir

- O e-mail de falha do `detect_gee.yml` chega até o C1; depois dele, nenhum.
  O do robô azul do site (`update-data.yml`, job `alertas`) segue até o C2.
- `gh workflow list` sem `--all` esconde os desligados.
- Uma rodada sem imagem termina `success` com `deposit` `skipped`; leia os
  jobs, não a conclusão.
- A frase *"ela aparece aqui quando for publicada"* na página continua
  depois da promoção até a próxima rodada; não é sinal de que a promoção
  falhou (`PHASE_6ZK` §5).
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório.
- `<<EOF` não citado executa os backticks: `git commit -F`.

## 7. Estado que o package herda

- Público no verde desde 2026-10-14; ponteiro seq. 22
  `rel-g3-0a788e76…`; cabeça da cadeia `ci-39251503748` (cobre até
  2026-10-17).
- Site em rascunho: `#50` (C2), `#21` (C4), `#51` (verificador).

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. A rodada de segunda achou imagem nova, publicou sozinha e o site se
atualizou sozinho. Era a última prova antes de desligar o sistema antigo.

### O que você precisa fazer

1. **Mesclar a PR de documentação desta leitura** — quando puder; não muda
   nada que roda.
2. **Abrir a próxima sessão do Claude com este briefing** — quando quiser
   desligar o sistema antigo. Ela vai pedir o seu "sim" antes do comando.

### Tem algo preocupante?

Não. Tudo rodou verde; o único detalhe é uma frase da página que diz "vai
aparecer quando for publicada" mesmo depois de publicada, e isso é só texto.

### O que ainda falta no caminho

- **Desligar o sistema antigo** — quatro passos, cada um com o seu "sim":
  parar o agendamento antigo, parar o robô antigo do site, fechar o acesso
  público antigo, parar de guardar alertas no código do site.
- **Duas semanas de vigia** — conferir cada rodada.
- **Corrigir a frase da automação na página** — um pacote pequeno do site.
- **Avisar o tamanho antes de baixar** — um pacote pequeno do site.
- **A série de índices do sistema novo** — um pacote logo depois.
- **Fase 5** — a validação independente.
