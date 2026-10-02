# Phase 6 — fontes e atribuição, conferidas contra o presente

Escrito em 2026-10-02, ao fim da sessão que pôs a página inicial na release
verde ([`PHASE_6S`](../implementation/PHASE_6S_2026-10-02.md)).
Método: [`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o
corpo é para o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: medium**
>
> Por quê: é auditoria de documento contra código e página, sem ciência nova
> e sem contrato. O erro plausível é de leitura — declarar uma atribuição
> "presente" porque a palavra aparece num comentário, ou "ausente" porque a
> busca usou a grafia errada — e o antídoto é método, não esforço alto.

---

## 1. A dependência que precede tudo — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C site fetch origin && git -C site rev-parse origin/main
    git -C Araripe cat-file -e origin/main:docs/contracts/phase1/DATA_SOURCE_AND_ATTRIBUTION_REGISTER_2026-07-24.md
    gh pr list -R santibravocmcc/observatorio-site --state all --limit 3 --json number,state,baseRefName,mergedAt

- **`observatorio-site#37`** (a página inicial verde) **não é** pré-requisito:
  esta tarefa não toca os cartões. Se ela ainda estiver aberta, ramifique da
  `main` do site e não a empilhe.

Suítes medidas em 2026-10-02: site `npm run test:worker` **134** na `main`
(**139** com a `#37`), `pytest` **240** com `/opt/anaconda3/bin/python3.12`;
backend **2619** (com este briefing). Use o número que sair.

## 2. O que já foi verificado, para o executor não refazer

- **O registro existe e é da Phase 1**:
  `docs/contracts/phase1/DATA_SOURCE_AND_ATTRIBUTION_REGISTER_2026-07-24.md`,
  aceito em 2026-07-28. Seções: extensão de monitoramento (§1), Sentinel-2 e
  CHIRPS (§2), MapBiomas nacional (§3, com licença e atribuição em §3.3), chuva
  do site GPM IMERG diária e mensal (§4), camadas de apresentação (§5), regras
  de atribuição e release (§6), portões de proveniência em aberto (§7). Ele
  **não** foi relido contra o sistema verde: a §7 lista portões que podem ter
  fechado desde então.
- **Arquivos de licença e citação**: backend tem `CITATION.cff`,
  `DATA_LICENSE`, `LICENSE`, `NOTICE` (`git ls-tree origin/main`); o site tem
  `NOTICE` e `README.md`, e **não** tem `CITATION.cff` nem `LICENSE`.
- **Menções de licença nas páginas do site**, contando linhas com
  `cc-by`/`cc by`/`creative commons`/`licen` (`git grep -c -i`):
  `dados-abertos.html` 8, `alertas.html` 5, `colabore.html` 2,
  `territorio.html` 1. **Resultado negativo:** `sobre.html` não tem nenhuma, e
  nem cita MapBiomas — a §4.1 de `PACKAGE_P6_PROMPT.md` o lista entre as
  páginas com CC-BY, e está errada nesse ponto.
- **`worker/metodo.js`** (`site#30`) já prende cada número do texto do método
  à fonte do backend; não é para reescrever.
- **O que o ROADMAP pede**, Phase 6, bullet 4: *"Complete the
  data-source/attribution register, MapBiomas CC-BY attribution, licence
  boundaries, citation files, README/deployment/method documentation, and final
  public-domain references."* E o topic 32 (Approved).

## 3. A tarefa

**Única tarefa: uma auditoria escrita — cada fonte de dado de terceiros que o
sistema verde usa, contra o que o registro diz e o que a página pública mostra
— e as correções que não dependem de decisão do dono.**

1. Liste as fontes que o **verde** usa de fato, do código e não da prosa:
   coleções GEE da detecção, as camadas MapBiomas (coleção e anos), a chuva do
   site, os limites municipais e da APA, e o que mais a página desenhar. Para
   cada uma: identidade, licença, texto de atribuição exigido, e onde ele
   aparece hoje (arquivo:linha) — ou "não aparece".
2. Compare com o registro de 2026-07-24. O que mudou vira uma **adição datada**
   no fim do registro, sem reescrever as linhas antigas — o mesmo padrão da
   §4.1 de `PACKAGE_P6_PROMPT.md`.
3. Corrija no site o que é só texto e tem atribuição exigida pela licença
   (por exemplo, a linha de crédito do MapBiomas onde a camada aparece), com
   teste que falhe se a linha sumir. **Leia as licenças, não as cite de
   memória.**
4. O que exigir decisão — licença do próprio produto, texto de citação
   preferido, se o site ganha `CITATION.cff` — vai como pergunta ao dono, com
   a recomendação.

**Fora de escopo, explicitamente:** a virada e as "referências do domínio
final" (o domínio final é da §4.4); qualquer afirmação de acurácia (**Phase
5**); a ordem dos gatilhos de deploy depois de cada promoção (PHASE_6P §5,
outra tarefa); os portões 2 e 3; mudar o texto do método já preso em
`worker/metodo.js`.

## 4. Decisões de escopo já tomadas, com a base

- **Nada é apagado**, nunca; o registro antigo cresce, não é reescrito.
- **A atribuição do MapBiomas é CC-BY** e é exigida — ROADMAP Phase 6 e
  registro §3.3.
- **O verde só por `?dados=verde` até a virada** — PHASE_6M §3.

Se aparecer evidência contra qualquer uma, **pare e pergunte**.

## 5. Fronteiras duras

- **A `main` do site faz deploy de produção.** Não mescle PR do site.
- **`detect_gee.yml` e `update_data.yml` não são idempotentes** e escrevem em
  produção. Nunca os dispare.
- Claude não recebe credencial de control-plane da Cloudflare; o broker só tem
  `audit`, `enforce-worker-isolation`, `disable-site-branch-deploy`.
- **Nenhum Environment é criado, renomeado ou reconfigurado por agente.**
- O agente age com a conta do dono no GitHub: **nunca aprove um Environment**.

## 6. Armadilhas já pagas — não redescobrir

- **Uma PR empilhada mesclada sem trocar a base não chega à `main`**; confira
  `baseRefName`.
- **Guarda por string literal é derrotado por paráfrase e por quebra de
  linha**: normalize espaços antes de procurar uma linha de crédito.
- **Uma menção num comentário não é texto na página**: ao contar onde a
  atribuição aparece, ignore comentários.
- **O `pytest` do site com Python 3.11** falha num teste de soma; use o 3.12.
- **`node --test tests/` quebra no Node 25**; use `npm run test:worker`.
- **O hook `commit-msg` recusa um SHA de 40 caracteres de OUTRO repositório.**

## 7. Estado que o package herda

- **Ponteiro verde:** sequência 17, `rel-g3-264ba36e…`, 103 datas até
  2026-09-27. Nada promovido nem depositado nas duas últimas sessões.
- **Página de alertas e página inicial** leem o verde atrás de `?dados=verde`
  (a inicial só depois da `site#37`).
- **O worker verde de staging** não foi reimplantado depois da `site#33`.
- **A produção azul está parada** desde 2026-09-03; o site público mostra
  alertas até 30/08.
- **O token da NASA expira em 2026-11-06.**

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Nada da tarefa. A página inicial, no modo de teste dos dados novos, agora
mostra os alertas novos, e cada cartão leva para o mesmo alerta na página de
alertas. Está numa PR do site, esperando você.

### O que você precisa fazer

1. **Mesclar a PR 37 do site, que põe os dados novos na página inicial** —
   pode esperar; o público não vê diferença, porque a mudança só aparece no
   modo de teste.
2. **Renovar o acesso à NASA antes de 6 de novembro** (até o fim de outubro).
   Sem isso a atualização da chuva para.
3. **Cancelar a chave de acesso que o assistente usa na caixa de testes** —
   só perto da virada, não agora.

### Tem algo preocupante?

Nada novo. Uma observação pequena: se a data mais recente analisada não
tiver alertas fortes, a página inicial vai dizer exatamente isso, em vez de
mostrar alertas de uma data anterior. É verdadeiro, mas pode parecer vazio;
se você preferir os alertas da última data que teve algum, é uma mudança de
texto simples. Continuam valendo os dois avisos de antes: depois da virada,
cada atualização automática só aparece na página quando o site é
reconstruído, e o prazo da NASA acima.

### O que ainda falta no caminho

- **Fontes e atribuição** — conferir que cada dado de terceiros aparece com o
  crédito e a licença certos. É a próxima sessão.
- **A ordem das atualizações depois da virada** — o site se reconstruir logo
  depois de cada publicação, e a página não cair numa versão desligada.
- **A virada** — o site passa a mostrar os dados novos para todo mundo, a
  caixa de testes vira a definitiva, e o caminho antigo é desligado.
- **Fase 5** — a validação independente, que também revê a data de maio que
  ficou a um fio do mínimo.
