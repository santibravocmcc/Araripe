# Phase 6 — revogar a chave local de staging e reescrever o documento dela

Escrito em 2026-10-14, ao fim da sessão que tirou o job `alertas` do robô do
site ([`PHASE_6ZE`](../implementation/PHASE_6ZE_2026-10-14.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: é o passo A8 de
> [`PHASE_6_CUTOVER_RUNSHEET.md`](PHASE_6_CUTOVER_RUNSHEET.md). A revogação é
> do dono, no painel; o agente prova por chamada recusada e reescreve um
> documento. Pouco código, nenhum; o cuidado é **não** derrubar a chave do
> Environment `v2-staging` (a lane de depósito vive dela) e nunca ler um valor
> de credencial.

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    gh pr list -R santibravocmcc/Araripe --state open --json number,isDraft,headRefName
    gh pr list -R santibravocmcc/observatorio-site --state open --json number,isDraft,headRefName
    aws configure list-profiles

- Ao fim da sessão anterior: site em rascunho `#48`, `#42`, `#49` (base
  `#42`), `#21` e `#50` (A7, `ad710d8`); backend em rascunho `#118` (A5) e a
  PR de docs desta sessão anterior.
- `aws configure list-profiles` lista **só nomes**. Nunca `cat`, `Read` nem
  `aws configure get` em `~/.aws/credentials` — está no `deny` local e é
  fronteira de segredo.
- Leia `docs/operations/CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md` da `main`
  inteiro antes de concluir qualquer coisa sobre credencial (memória
  `araripe-credencial-de-staging-esta-no-profile-aws`).

## 2. O que já foi medido, para o executor não refazer

- **Dois profiles locais de staging**, não um (2026-10-14):
  `araripe-r2-staging` — a chave do Claude, `claude-araripe-v2-staging-rw`,
  escopo `araripe-v2-staging`, Object Read & Write — e
  `araripe-r2-github-staging`, que `PHASE_2B0_2026-08-11.md` registra como a
  **identidade do GitHub Actions** verificada desta máquina em 2026-08-11.
  **Não se sabe** se essa segunda é a chave que está hoje no Environment
  `v2-staging` (pode ter sido trocada desde então). É a pergunta nova deste
  passo (§3, passo 1).
- **Quem usa o profile local.** Só `scripts/baseline_v2_staging.py` cita
  `araripe-r2-staging` em `scripts/`/`.github` (`git grep`, 2026-10-14);
  memória `credencial-por-profile-e-opt-in-por-call-site`: só os scripts de
  depósito local o aceitam, por opção. Nenhum passo restante da folha
  deposita localmente — A9 e a rotina usam as lanes.
- **Como provar escopo:** só uma chamada real recusada prova (memória
  `chave-promocao-escopo-amplo`). Ler configuração prova só a forma.
- **A lane viva:** `v2_green_status.yml` disparada da `main` lê o staging com
  a chave do Environment; `ok` depois da revogação prova que a chave certa
  ficou.

## 3. A tarefa

**Única tarefa: o passo A8 da folha.**

1. **Antes de qualquer revogação, com o dono:** ele confere no painel
   (R2 → Manage API tokens) os nomes e datas de criação das chaves e diz:
   (a) `claude-araripe-v2-staging-rw` **não** é a chave do Environment
   `v2-staging`; (b) a que está no profile `araripe-r2-github-staging` é a
   mesma do Environment, outra, ou uma já revogada. O agente pode ajudar com
   o *Access Key ID* (não é o segredo) só se o dono pedir — `aws configure
   list --profile <p>` mostra o ID mascarado; nunca o segredo.
2. **O dono revoga** `claude-araripe-v2-staging-rw`. Sobre o segundo profile,
   a recomendação é: se for a chave do Environment, **apagar o profile
   local** (a chave continua no Environment; a lane não para) — e não
   revogar; se for outra chave, revogá-la também. A decisão é do dono.
3. **O agente prova:** `aws s3 ls s3://araripe-v2-staging --profile
   araripe-r2-staging --endpoint-url …` **recusado** (o erro, sem
   credencial no texto); o mesmo para o segundo profile, se o dono o
   revogou ou apagou. Depois `gh workflow run v2_green_status.yml --ref main
   -R santibravocmcc/Araripe` (só leitura) e o resultado `ok`.
4. **O agente reescreve** `CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md` para o
   papel canônico — opção (a): o bucket `araripe-v2-staging` vira o que o
   público lê na virada; Claude não tem mais credencial local nele; toda
   escrita é pelas lanes. A revogação entra como fato medido (data, comando,
   erro). O histórico de 2026-08-11 fica, marcado como histórico.
5. Bloco "Feito" no A8 da folha, registro `PHASE_6ZF_<data>.md`, e o próximo
   briefing (A9, na véspera — ou o primeiro passo sem "Feito"; confira a
   folha na `main`). Tudo numa PR de docs do backend.

**Fora de escopo:** criar chave nova; mexer em Environment (nomes, segredos,
revisores); A9 (drenar a fila); qualquer merge do site.

## 4. Decisões de escopo já tomadas, com a base

- Bucket: opção (a), o staging vira o definitivo na virada — dono,
  2026-09-30 (`PACKAGE_P6_PROMPT.md` §3).
- Nenhuma publicação tem revisor; rollback pelo `v2-promotion` —
  decisão de 2026-10-02.
- D0–D6 da folha, decididas em 2026-10-13.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- **Nenhum valor de credencial** lido, impresso, copiado ou colado — nem
  para "conferir". `~/.aws/credentials` e `.env` estão fora.
- O agente não revoga, não cria e não troca chave: é o dono, no painel.
- Nenhum Environment criado ou reconfigurado (memória
  `araripe-nunca-nomear-environment-inexistente`).
- Nenhum `wrangler`, nenhum token Cloudflare, nenhum broker.
- A `main` do backend é só por PR; a do site faz deploy — nenhum merge.

## 6. Armadilhas já pagas — não redescobrir

- Ausência de variável de ambiente não é ausência de credencial: a convenção
  é o profile.
- `boto3` real em teste polui a sessão padrão (`ProfileNotFound` na suíte).
- O hook `commit-msg` do backend recusa SHA de 40 caracteres de outro
  repositório — no registro, SHA curto do site.
- `<<EOF` não citado executa os backticks do corpo: mensagem em arquivo e
  `git commit -F`.

## 7. Estado que o package herda

- Site em rascunho: `#48` (B1), `#42` (B2), `#49` (B5, base `#42`), `#50`
  (C2), `#21` (C4). Backend: `#118` (B6).
- Ponteiro verde seq. 18 (107 datas até 2026-10-04); a fila de depósito
  desde 2026-10-05 cresce um dia por dia (A9 a drena na véspera).
- O azul parado desde 2026-09-03; o robô do site vermelho no job `alertas`
  até o C2.

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada. O desligamento do robô antigo do site está escrito, testado e guardado
sem publicar; ele só entra no dia da virada.

### O que você precisa fazer

1. **Não mesclar as mudanças do site que estão em rascunho.** Cada uma tem o
   seu momento no roteiro da virada.
2. **Na próxima sessão, abrir o painel da Cloudflare** (R2 → Manage API
   tokens) e dizer quais chaves existem, com nome e data — a sessão precisa
   disso antes de você revogar a chave antiga.

### Tem algo preocupante?

Um ponto de atenção, não um problema: nesta máquina há **duas** chaves
guardadas para o bucket novo, não uma. A segunda parece ser a do robô do
GitHub. Se for, a sessão vai sugerir apagá-la só desta máquina — sem
revogar, para o robô continuar funcionando.

### O que ainda falta no caminho

- **Revogar a chave local antiga** — a próxima sessão, com você.
- **Processar os dias acumulados**, na véspera.
- **Você revisar o roteiro e marcar o dia.**
- **A virada** — executar o roteiro, com a sua aprovação em cada passo que
  mexe no site público.
- **A série de índices do sistema novo** — um pacote logo depois da virada.
- **Fase 5** — a validação independente.
