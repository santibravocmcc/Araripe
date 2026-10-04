# Phase 6 — a ordem dos gatilhos depois de cada promoção

Escrito em 2026-10-04, ao fim da sessão que conferiu fontes e atribuição
([`PHASE_6T`](../implementation/PHASE_6T_2026-10-04.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: high**
>
> Por quê: é desenho de automação entre dois repositórios com a produção do
> outro lado — o deploy de rotina do site **é** o gatilho de produção. O erro
> plausível é uma ordem que funciona no caminho feliz e deixa a página
> recusando o índice, ou caindo numa fonte que a virada vai desligar. Isso
> pede medição antes de escrever, e esforço alto.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C site fetch origin && git -C site rev-parse origin/main
    gh pr list -R santibravocmcc/observatorio-site --state all --limit 4 --json number,state,baseRefName,mergedAt
    gh pr list -R santibravocmcc/Araripe --state all --limit 4 --json number,state,baseRefName,mergedAt

- **`observatorio-site#38`** (créditos) **não é** pré-requisito: não toca a
  porta verde nem o build. Se estiver aberta, ramifique da `main` do site e
  não a empilhe.

Suítes medidas em 2026-10-04: site `npm run test:worker` **139** na `main`
(**150** com a `#38`), `pytest` **240** com `/opt/anaconda3/bin/python3.12`;
backend: rode e use o número que sair.

## 2. O que já foi verificado, para o executor não refazer

- **A decisão está tomada**: P2 = (a), registrada em
  `config/phase6_publication_authority_v1.json` (`proposed_decisions`, P2,
  `decided: yes`, 2026-10-02). O deploy de rotina do site é o gatilho de
  produção do Workers Builds num push à `main` do site; o Environment revisado
  da D4 governa só deploys manuais do Worker verde de staging.
- **Por que cada promoção pede um deploy**: o índice de alertas é artefato de
  build, não objeto da release (`SITE_ARTIFACT_CONTRACT_V1.md` §1); a página
  recusa o verde quando `built-from.json` nomeia outra release
  (`indice_de_outra_release`, site `src/js/alertas-fonte.js`).
- **A janela**: com detecção seg/qui e site ter/sex às 06:00 UTC, a página
  recusaria o índice por ~24 h depois de cada promoção — **aritmética sobre os
  horários, não medição** (PHASE_6P §5).
- **Ao recusar, a página cai no azul.** Depois do passo 3 da §4.4 de
  `PACKAGE_P6_PROMPT.md` não haverá azul.

## 3. A tarefa

**Única tarefa: amarrar o deploy do site à promoção, e trocar o "cair no
azul" por uma recusa que não dependa do azul — desenho medido, implementação
nas branches, nada mesclado no site.**

1. **Meça primeiro, sem credencial nova** — os dois "não medido" da P2:
   a imagem de build do Workers Builds tem o Python que
   `scripts/site_artifact.py` usa? O build alcança a rota verde? Leia a
   configuração versionada (`wrangler.jsonc`, `package.json`, `DEPLOY.md`) e
   os logs públicos de build que o dono puder colar; **não** use Wrangler nem
   token. Se não der para medir, pare e diga o que falta.
2. **Desenhe a ordem**: promoção → build do site → página. Opções a comparar,
   com a recomendação: um `repository_dispatch` do backend para um workflow do
   site que só empurra um commit à `main` (o bot do site ainda empurra, sem
   ruleset); ou o cron do site movido para depois da promoção. Respeite o
   intervalo de 24 h entre os crons (`AGENTS.md`).
3. **A recusa sem azul**: o que a página mostra quando o índice nomeia outra
   release e não há para onde cair. Proposta com texto, teste, e atrás de
   `?dados=verde` até a virada.

**Fora de escopo, explicitamente:** a virada; mudar o contrato do índice
(opção (c) da P2); qualquer acurácia (**Phase 5**); os créditos (feitos na
`#38`); a chave da CARTO e o contexto MapBiomas, que são decisões do dono
registradas na PHASE_6T §4.

## 4. Decisões de escopo já tomadas, com a base

- **P2 = (a)** — `phase6_publication_authority_v1.json`, 2026-10-02.
- **Nenhuma publicação tem revisor** (P1 retirada pelo dono, 2026-10-02).
- **O verde só por `?dados=verde` até a virada** — PHASE_6M §3.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- **A `main` do site faz deploy de produção.** Não mescle PR do site, e
  nenhum workflow novo pode empurrar à `main` do site nesta sessão — só
  existir numa branch.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare.
- Claude não recebe credencial de control-plane da Cloudflare; o broker só tem
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Nenhum Environment é criado, renomeado ou reconfigurado por agente**, e
  escrever `environment:` com um nome inexistente CRIA um.
- O agente age com a conta do dono no GitHub: **nunca aprove um Environment**.

## 6. Armadilhas já pagas — não redescobrir

- **Uma PR empilhada mesclada sem trocar a base não chega à `main`**; confira
  `baseRefName`.
- **Aritmética de horário não é medição** — a janela de ~24 h nunca foi vista.
- **Um verificador que difere do cliente prova o errado**: a borda da
  Cloudflare recusou User-Agent próprio com 403/1010.
- **`node --test tests/` quebra no Node 25**; use `npm run test:worker`.
- **O hook `commit-msg` recusa um SHA de 40 caracteres de OUTRO repositório.**

## 7. Estado que o package herda

- **Ponteiro verde:** sequência 17, `rel-g3-264ba36e…`, 103 datas até
  2026-09-27. Nada promovido nem depositado nas três últimas sessões.
- **Página de alertas e página inicial** leem o verde atrás de `?dados=verde`.
- **`site#38` aberta** — créditos de dados; independente desta tarefa.
- **Os tiles da CARTO estão quebrados em produção** (exigem chave desde
  setembro de 2026); decisão do dono, PHASE_6T §4.
- **A produção azul está parada** desde 2026-09-03.
- **O token da NASA expira em 2026-11-06.**

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da tarefa. Os créditos que as licenças dos dados exigem agora aparecem
onde o dado aparece — o aviso do satélite europeu, que não existia em lugar
nenhum, o crédito do MapBiomas no mapa de alertas, e as citações certas da
chuva. Está numa PR do site, esperando você.

### O que você precisa fazer

1. **Mesclar a PR 38 do site, a dos créditos** — sem pressa técnica, mas é
   obrigação das licenças, e hoje o site público não cumpre.
2. **Decidir o mapa claro**: a empresa que fornece o fundo de mapa claro
   passou a exigir uma chave, e o mapa claro do site está aparecendo com o
   aviso "API KEY REQUIRED" no lugar do mapa. Recomendo pedir a chave
   gratuita para ONG em carto.com/basemaps/apikey, limitada ao domínio do
   site. Com ela, ligar o mapa de volta é uma linha no código.
3. **Decidir o mapa de uso do solo dos alertas**: ele usa o MapBiomas de
   2023, e o plano dizia o de 2024. Recomendo manter como está até a
   validação independente e trocar lá, porque a troca muda quais alertas
   contam como fortes.
4. **Renovar o acesso à NASA antes de 6 de novembro** (até o fim de outubro).
   Sem isso a atualização da chuva para.
5. **Cancelar a chave de acesso que o assistente usa na caixa de testes** —
   só perto da virada, não agora.

### Tem algo preocupante?

Sim, um: **o mapa claro está quebrado no site público hoje**, nos dois mapas
da página Território e na opção "claro" dos alertas. Não foi nada que
fizemos — o fornecedor mudou a regra no fim de setembro. O mapa de satélite,
que é o padrão dos alertas, segue funcionando. O resto é menor: no celular o
crédito ocupa uma faixa de baixo do mapa de alertas, que é pequeno ali.

### O que ainda falta no caminho

- **A ordem das atualizações depois da virada** — o site se reconstruir logo
  depois de cada publicação, e a página não cair numa versão desligada. É a
  próxima sessão.
- **Os dados dizerem de onde vêm** — cada publicação levar junto a lista de
  fontes e créditos. É uma mudança no formato da publicação, ainda não
  desenhada.
- **A virada** — o site passa a mostrar os dados novos para todo mundo, a
  caixa de testes vira a definitiva, e o caminho antigo é desligado.
- **Fase 5** — a validação independente, que também revê a data de maio que
  ficou a um fio do mínimo e, se você concordar, troca o mapa de uso do solo
  para o de 2024.
