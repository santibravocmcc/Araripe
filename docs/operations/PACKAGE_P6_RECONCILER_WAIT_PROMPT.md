# Phase 6 — a espera do reconciliador do site

Escrito em 2026-11-17, no fecho do C6B
([`PHASE_6ZQ_2026-11-17.md`](../implementation/PHASE_6ZQ_2026-11-17.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: a mudança provável é pequena, mas mora num workflow da `main` do
> site, que faz deploy de produção a cada merge, e a razão de ele ser só
> agendado é de segurança (credencial). O risco é "resolver" a espera dando
> ao backend um poder de push no site, ou trocar um atraso medido por uma
> suposição sobre o agendador do GitHub.

**Quando abrir:** quando o dono quiser; não há prazo. Não abrir numa segunda
ou quinta entre 14:00Z e 23:00Z sem antes ler se há promoção em curso.

**Por que existe:** o C6B mediu, nas quatro rodadas de novembro, de
**4 h 17 min a 6 h 42 min** entre a linha `pointer : promote` do log da
publicação e o commit `deploy(verde)` no site (`PHASE_6ZQ` §2.1). Durante
esse tempo o domínio serve o `current.json` novo com o índice da release
anterior. O status diário não vê isso: nenhuma das sete linhas lê o
`built-from.json` do site, e três dos quatro status do dia da rodada rodaram
antes do `deploy(verde)`.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/implementation/PHASE_6ZQ_2026-11-17.md | head -5
    git -C site fetch origin && git -C site show origin/main:.github/workflows/green_site_rebuild.yml | sed -n '1,60p'
    gh run list -R santibravocmcc/observatorio-site --workflow green_site_rebuild.yml -L 200 --json databaseId,createdAt,conclusion

- Esperado: `PHASE_6ZQ` na `main` do backend (se não estiver, a PR do C6B
  não foi mesclada: pare e diga ao dono). O cron do reconciliador é
  `41 */3 * * *` mais `workflow_dispatch`.
- A suíte do backend não muda neste pacote; o que se testa é do site
  (`npm run test:worker` e os testes Python dele — veja o `AGENTS.md` do
  site, não use `node --test tests/` no Node 25).

## 2. O que já está provado — não refazer

- As esperas, por rodada (`PHASE_6ZQ` §2.1, horários copiados dos logs):
  11-02 4 h 16 min (`PHASE_6ZP` §2), 11-05 5 h 36 min, 11-09 6 h 42 min,
  11-12 5 h 06 min, 11-16 4 h 17 min.
- O GitHub iniciou **42** runs do reconciliador de 2026-11-03 a 2026-11-16
  (8 agendadas por dia → 112), e **55** de 10-20 a 11-02. As que rodam
  saem muito depois do minuto 41 (ex.: 20:14:44Z, 22:41:04Z). Ou seja, o
  agendador **atrasa e descarta** passadas; ainda não se mediu qual dos dois
  pesa mais nem em que horas.
- Por que o reconciliador é agendado e não disparado pelo backend: o
  comentário do próprio `green_site_rebuild.yml` (seção "Por que agendado,
  e não por evento do backend") — um `repository_dispatch` exigiria guardar
  no backend, num Environment sem revisor, uma credencial capaz de empurrar
  à `main` do site, que é deploy de produção. **Não reabrir sem evidência
  nova.**
- Nenhum push de outro autor caiu entre promoção e `deploy(verde)` nas seis
  rodadas lidas (`PHASE_6ZP` §6, `PHASE_6ZQ` §7).
- Promoções caem entre 14:39Z e 16:00Z nas segundas e quintas (depósito com
  cron 06:00 que começa entre 14:00Z e 15:30Z, mais ~25 min de publicação).

## 3. A tarefa

**Medir, propor ao dono, e só então fazer o que ele escolher.**

1. **Medir** com os 200 últimos runs: para cada run, o slot `:41` a que ele
   pertence (o mais recente antes do `createdAt`) e o atraso; quantos slots
   por dia ficaram sem run. Separe segunda/quinta das 14:00Z às 23:00Z, que
   é a janela que importa.
2. **Propor**, com números, ao menos estas opções ao dono, sem escolher por
   ele:
   - (a) mais passadas só na janela da promoção, por exemplo um segundo
     `cron` nas segundas e quintas, fora da hora cheia; custo em minutos de
     Actions (o repositório é privado; o comentário do workflow estima
     ~240 min/mês para 8 por dia);
   - (b) uma linha a mais no status verde que compare o `built-from.json`
     servido com o ponteiro — torna a espera visível, não a encurta, e muda
     a contagem "sete linhas" que as vigias usam;
   - (c) aceitar a espera e só documentá-la na página ou no `AGENTS.md`;
   - qualquer outra que não dê ao backend poder de escrita no site.
3. **Fazer** a opção escolhida numa PR do repositório certo, com testes, e
   parar. **Não mescle**: no site quem mescla é o dono.
4. Registrar em `docs/implementation/PHASE_6ZR_<data>.md` e escrever o
   briefing seguinte.

**Fora de escopo:** o robô do IBAMA (conferido à parte na rodada de
2026-11-22); a chuva parada pelo certificado do CPTEC (pacote do site, se
repetir na sexta 11-20); a série verde (D4B); a Phase 5; qualquer mudança
nas lanes de depósito e publicação do backend.

## 4. Decisões de escopo já tomadas, com a base

- Reconciliador agendado, sem credencial do backend no site: comentário do
  `green_site_rebuild.yml`. Não reabrir.
- A folga de 24 h entre a detecção (seg/qui) e o robô do site (ter/sex):
  `AGENTS.md` do workspace. Qualquer cron novo a respeita.
- Uma espera longa não é falha da vigia: `PACKAGE_P6_WATCH_B_PROMPT.md` §3.1
  mandou medir, não consertar; o C6B fechou sem falha.

## 5. Fronteiras duras

- Nenhum `workflow_dispatch` do reconciliador "para testar" e nenhum push na
  `main` do site: a `main` do site faz deploy de produção.
- Nenhum `wrangler`, token Cloudflare, login, chamada à API da Cloudflare
  ou broker; recusar se oferecido.
- Nenhuma credencial nova entre os repositórios; nenhum Environment novo.
- A `main` do backend só aceita PR.

## 6. Armadilhas já pagas — não redescobrir

- `gh workflow list` sem `--all` esconde os desligados.
- O cron do GitHub atrasa de 40 min a mais de 9 h e pula passadas; uma
  amostra de poucos dias engana — use os 200 runs.
- O `deploy(verde)` só aparece quando o build com o índice novo muda algo;
  um reconciliador que roda e não acha diferença não faz commit.
- A borda da Cloudflare devolve 403/1010 a cliente sem UA de navegador.
- O hook `commit-msg` recusa SHA de 40 caracteres de outro repositório:
  SHAs do site entram na mensagem pela forma curta.
- `<<EOF` não citado executa os backticks: `git commit -F`.
- Decidir merge por conteúdo ou pelo assunto `(#N)`, nunca por ancestralidade.

## 7. Estado que o package herda

- Phase 6 fechada em 2026-11-03; C6B fechado em 2026-11-17 sem falha
  (`PHASE_6ZQ`).
- Ponteiro seq. 30 `rel-g3-a955dc07…`, contexto `ctx-g1-4a5776ca…` seq. 12,
  fontes `src-g1-a665f3d9…` seq. 11; site com o `deploy(verde)` `26e9d95`.
- `detect_gee.yml` `disabled_manually`; os outros 14 do backend e os 8 do
  site `active`.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da vigia: as quatro rodadas de novembro passaram sem falha. Ficou só a
medição de um atraso, que é o assunto deste próximo pacote.

### O que você precisa fazer

1. **Mesclar a PR de documentação da vigia (C6B)** no backend — quando
   quiser; ela só registra.
2. **Decidir se este pacote vale a pena** — não é urgente. Se sim, abra a
   próxima sessão do Claude com este briefing; ela vai medir e trazer as
   opções para você escolher.

### Tem algo preocupante?

Não. A página mostra o dado novo de 4 a 7 horas depois de ele ficar pronto;
nada se perde, só chega mais tarde.

### O que ainda falta no caminho

- **Este pacote** — encurtar ou tornar visível a espera da página depois de
  cada rodada.
- **A série de índices do sistema novo (D4B)** — a aba "Séries" parada em
  setembro; a sessão já está em curso.
- **Robô do IBAMA** — conferir a primeira rodada consertada, domingo 22/11.
- **Chuva** — o servidor do CPTEC está com o certificado vencido; se o robô
  de sexta 20/11 também pular, vira um pacote pequeno do site.
- **Fase 5** — a validação independente; a sessão de execução já tem
  briefing.
