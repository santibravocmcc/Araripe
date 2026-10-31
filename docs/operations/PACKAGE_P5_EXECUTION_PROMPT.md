# Phase 5 — P5.1: o quadro amostral e o pacote de rotulagem

Escrito em 2026-10-31, depois de o dono decidir as três decisões do portão e a
meta de precisão (registro: bloco datado de 2026-10-31 de
[`PACKAGE_P5_PROTOCOL_PROMPT.md`](PACKAGE_P5_PROTOCOL_PROMPT.md)). Método:
[`HANDOFF_PROMPT_METHOD.md`](HANDOFF_PROMPT_METHOD.md) versão 2 — o corpo é para
o agente executor e a **seção final é para o dono**.

> **NEXT SESSION MODEL: Opus 5.5 — EFFORT: max**
>
> Por quê: esta sessão desenha a amostra que vai sustentar um número que
> outras pessoas vão citar. Uma amostra enviesada não se corrige rotulando mais
> casos, e refazê-la gasta o tempo das pessoas, que é o recurso mais escasso do
> roadmap. O risco é o contrário do cansaço: confiar numa conta que passa pelo
> motivo errado — a de 2026-09-17 passou, e o número que ela imprime não alcança
> o erro-padrão que a dimensiona (§2, item 5).

**Quando abrir:** quando o dono quiser. **Não depende do C6** nem de nenhuma
outra fase: a Phase 5 não é portão das Fases 6 e 7 (decisão do dono,
2026-09-08). O desenho, o sorteio e a geração do pacote **não precisam de
nenhuma ação pendente do dono**; **distribuir o pacote a um revisor precisa**
(§3, ponto de parada).

---

## 1. O estado de partida — confirme por conteúdo

    git -C Araripe fetch origin && git -C Araripe rev-parse origin/main
    git -C Araripe show origin/main:docs/operations/PACKAGE_P5_PROTOCOL_PROMPT.md | sed -n 1,30p
    git -C Araripe show origin/main:docs/implementation/PHASE_5_2026-09-17.md | head -5
    git -C Araripe ls-tree --name-only origin/main src/validation/ scripts/ | grep -E "accuracy|plan_phase5|measure_candidate"

- Esperado: o bloco *"Bloco datado de 2026-10-31"* na `main`. Se não estiver,
  a PR de docs desta passagem não foi mesclada: **pare e diga ao dono**.
- **Meça a base de testes e registre o número**; este briefing não o afirma.
- **Worktree.** Siga a receita medida em `PACKAGE_P5_PROTOCOL_PROMPT.md`, bloco
  de 2026-09-17, §6: pasta separada com os cinco caminhos ignorados ligados por
  symlink (≈22,5 GB que um worktree novo não tem) e `.git/info/exclude` para os
  symlinks. `git worktree list` mostra um worktree antigo da Phase 5 em
  `/Users/sbravo/araripe-phase5`: **confira se está limpo e em que branch** antes
  de reusá-lo; o padrão é criar um novo a partir de `origin/main`.
- Branch ≤ 31 caracteres, a partir de `origin/main`.

## 2. O que já está provado ou decidido — não refazer

1. **Referência canônica localizada e lida:** Olofsson et al. (2014), doi
   `10.1016/j.rse.2014.02.015`; equações (1)–(13) como código em
   `src/validation/accuracy.py`, ancoradas na Table 5 do artigo
   (`tests/test_accuracy_estimators.py`; 12 mutações aplicadas, 12 mortas).
   Registro: `docs/implementation/PHASE_5_2026-09-17.md` §1 e §3.
2. **A unidade é pixel/área.** Os estimadores de variância não valem para
   polígono (§4.3 do artigo). Os rótulos do piloto 2A.3 amostraram polígonos e
   **não entram** nos estimadores. Herda-se cegamento, ordem, taxonomia e dupla
   revisão do 2A.3; **não** a unidade.
3. **A população do candidato está medida** (`PHASE_5_CANDIDATE_POPULATION_2026-09-17.json`):
   extent 2 093 558 ha; conjunto completo = união de 733 051 ha, `W = 0,350146`;
   subconjunto forte = 123 390 ha, `W = 0,058938`. Somar `area_ha` por data
   daria 94,4% do extent — errado. A área é geodésica (`pyproj.Geod`).
4. **As decisões do dono (2026-10-31)** — não reabrir sem evidência contrária:
   (a) opção 3 como quadro primário, opção 1 como estrato auxiliar; (b) drone
   fora, sem estrato e sem calibração; (c) pseudônimo `R1`, `R2`… no git, nome
   só no artigo, tabela nome↔ID fora do git. **Meta:** `S(Ô) ≤ 0,01`; ±0,10 (IC
   95%) na acurácia do usuário do estrato forte; ≥ 100 casos por estrato de
   mudança; omissão e recall com IC, sem meta.
5. **O achado que esta sessão tem de reproduzir.** O plano de 2026-09-17
   (`plan_phase5_sample.py`, desenho B, `n = 507`, alocação 75 / 75 / 357) dá,
   por uma conta à mão, `S(Ô) ≈ 0,016` — **não** 0,01 —, porque a Eq. (13)
   supõe alocação ótima e a regra de 50–100 por estrato não é essa. A alocação
   100 / 285 / 138 (`n = 523`) dá `≈ 0,0100`. As acurácias do usuário
   conjecturadas (0,70 / 0,30 / 0,99) são da sessão 1, **não medidas**.
   Detalhe e as duas saídas (A: sair da banda no estrato fraco; B: afrouxar a
   meta para 0,015): bloco de 2026-10-31, §3.
6. **Negativos verificados em 2026-10-31:** a branch
   `origin/claude/phase5-publication-scope` não tem nada fora da `main` — o
   arquivo é byte a byte o da #50 (mesmo `shasum`); nenhuma outra branch da
   Phase 5 tem PR aberta; nenhuma fonte achada declara meta para omissão nem
   referência para a taxa de dupla revisão (o 20% é herança do piloto).

## 3. A tarefa

**Única tarefa: P5.1 — do portão aberto ao pacote pronto e parado antes dos
revisores.** Em ordem; cada passo só começa com o anterior provado.

1. **Reproduza a alocação com código testado.** A conta de §2.5 é à mão. Escreva
   (em `src/validation/accuracy.py`, com testes) a função que dá o `S(Ô)`
   alcançado por uma alocação e os pesos; ancore-a no exemplo publicado da Table
   5 do artigo (não numa invariante sua) e rode **mutações** — limpe
   `__pycache__` antes de cada uma. Reproduza a tabela do bloco de 2026-10-31 e
   **registre qualquer discordância**. Se discordar, o dono volta a decidir; não
   escolha em silêncio.
2. **Escolha A ou B** (§2.5) com o motivo escrito, e **leia Tang et al. (2019)**,
   doi `10.1016/j.rse.2019.02.003` (só o resumo foi lido): registre se o
   arcabouço de atraso de detecção e tamanho mínimo detectável se aplica e o que
   muda no desenho. `allocate_sample` recusa fora de 50–100 de propósito; sair da
   banda é decisão registrada, não argumento de palavra-chave.
3. **Desenhe o quadro amostral** em unidade pixel/área sobre o candidato:
   estratos forte / fraco / sem mudança, pesos reais, e o estrato **auxiliar da
   opção 1** — **escolha e justifique um produto independente de alerta** que
   cubra o extent (meça a cobertura; se não cobrir, diga quanto). Registre a
   alternativa recusada. O sem-mudança precisa ser amostrado de forma a estimar
   **omissão**; amostrar só dentro do mapeado dá recall falso (teste da sessão 1).
4. **Refaça `n` a partir de uma primeira rodada pequena**, se o desenho permitir:
   as acurácias conjecturadas trocadas pelas medidas. Declare o alvo antes de
   amostrar; **um número escolhido antes do alvo não sustenta o intervalo**.
5. **Sorteie a amostra de forma determinística** (semente registrada), com o
   tratamento explícito de `unreviewable` (taxa e efeito entram no relatório).
6. **Monte o pacote de rotulagem** herdando o gerador do 2A.3
   (`scripts/build_validation_pilot.py`): protocolo adaptado à unidade
   pixel/área, `R1`, `R2`… sem dado pessoal, ordem fixa, cegamento, **dupla
   revisão em subconjunto** (decida se 20% basta para o alvo de concordância e
   escolha a estatística de concordância; nenhuma fonte achada dá referência),
   `manifest.json` com `claims` em `false` e `CHECKSUMS.sha256`. **Pacote novo é
   diretório novo**: os existentes são imutáveis.
7. **Escreva a redação do aviso do site** (que a Phase 6 só cola): dados e
   método sim, nenhum número de acurácia até o relatório.

**PONTO DE PARADA.** O pacote fica **gerado e não distribuído**. Nenhum revisor
o recebe, e ninguém é instruído, até o dono responder o que está em §8
("antes de os revisores começarem"). Entregue tudo numa PR e escreva o briefing
do P5.2 (rotulagem, cálculo e relatório) com as quatro perguntas.

**Fora de escopo:** rotular; recrutar ou instruir revisor; **qualquer drone**;
estimar acurácia real; escrever o artigo; **mudar qualquer default** (seca
desabilitada, máscara SCL v2, composição por datatake, MapBiomas contextual,
rótulos espectrais públicos desligados — a Phase 5 os valida, e mudar exige
evidência qualificada); a Phase 6 e o C6; tocar produção, o site ou o ponteiro.

## 4. Decisões de escopo já tomadas, com a base

- O quadro, o drone, a identidade dos revisores e a meta: §2.4. A base é o bloco
  de 2026-10-31 do briefing do protocolo, com as palavras do dono.
- A Phase 5 não trava as Fases 6 e 7 — decisão do dono, 2026-09-08.
- Os defaults aceitos ficam como estão até haver evidência qualificada.
- O MapBiomas segue contextual, **não** é referência de acurácia (defasagem de 2–3
  anos e comparação mapa contra mapa).
- Se um default mudar depois, os estágios de 2026 afetados são refeitos e há
  nova promoção; o artigo cita **uma** release, e a antiga continua existindo.

## 5. Fronteiras duras

- Só desenho, código testado e documentação. Nenhuma lane disparada, nenhuma
  escrita em R2 ou GEE, nenhum `wrangler`, token ou login da Cloudflare; o
  candidato é lido do disco, sem credencial.
- **O repositório é público.** Nenhum nome, CPF, documento ou endereço de
  revisor em arquivo algum, nem em mensagem de commit. Só `R1`, `R2`…
- `documentacao/` e `institucional/` têm identificadores pessoais: não transcrever.
- A `main` do backend é só por PR; o agente não mescla e não empurra nela.
- Não staged: dados MapBiomas, caches, saída de build, pacotes de validação
  (`data/validation/` é ignorado de propósito).

## 6. Armadilhas já pagas — não redescobrir

- Somar área por data duplica; área tem de ser geodésica; `lc_group` é lido, não
  recomputado (`PHASE_5_2026-09-17.md` §2).
- **Teste que afirma a própria saída sob a autoridade do artigo:** a primeira
  versão do teste da Table 5 afirmava 163/328 e passou. Leia a tabela inteira,
  não o trecho.
- `grep` é ugrep (`grep -qv` engana); `<<EOF` não citado executa backticks —
  use `git commit -F`.
- Symlink de diretório não casa o padrão `data/validation/` do `.gitignore`:
  `git add -A` comitaria um caminho absoluto. Commite por caminho; nunca
  `git stash`.
- O hook `commit-msg` recusa SHA de 40 caracteres que não existe no repositório
  — inclusive o de outro repositório; use a forma curta.
- Decidir merge por conteúdo ou pelo assunto `(#N)`, nunca por ancestralidade.
- `last_seen` não é invariante e `first_seen <= last_seen` não é promessa do
  produtor: não construa validação em cima de propriedade não prometida.

## 7. Estado que o package herda

- Phase 6: virada feita em 2026-10-14; C1–C5 feitos; falta o C6 (quatro rodadas
  de vigia, a partir de 2026-11-10). Ponteiro verde na seq. 24 no registro do C5;
  não o releia aqui, é de outro pacote.
- Phase 5: sessão 1 feita (PR `#68`, o instrumento e a população medida; antes
  dela `#48`, `#50`, `#65`, `#66`, todas de briefing); portão aberto em
  2026-10-31.
- Candidato 2026: 107 aquisições, 36 datas com alertas de 90, 67 068 feições
  fortes (`PHASE_4C_2026-09-16.md`).

## 8. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

Esta passagem só escreveu o briefing e registrou as suas decisões. Nada de
medição foi feito: a amostra ainda não existe, e nenhum revisor foi acionado.

### O que você precisa fazer

1. **Mesclar a PR de documentação** que registra as suas decisões e traz este
   briefing — quando puder; não muda nada que roda.
2. **Abrir a sessão do Claude com este briefing** — quando quiser; não precisa
   esperar a vigia da Phase 6. A sessão para antes de qualquer revisor receber o
   material.
3. **Perguntar à sua instituição, se houver vínculo, se há exigência de
   aprovação ética** para o trabalho de interpretação feito por pessoas — antes
   de os revisores começarem; pode esperar o desenho.
4. **Decidir onde fica a lista que liga cada revisor ao seu código** (R1, R2…),
   fora do git, e pedir o consentimento deles para serem creditados no artigo —
   antes de os revisores começarem.
5. **Confirmar o vínculo institucional dos revisores e quem será o autor
   correspondente** — antes de escrever o artigo; pode esperar.
6. **Escolher onde a release do artigo fica guardada para sempre** (Zenodo ou
   equivalente) — antes do relatório; não é urgente.

### Tem algo preocupante?

Um ponto, sem urgência: o plano de amostra de setembro não alcançava a precisão
que se queria. Já foi corrigido no papel, e a primeira tarefa da sessão é
conferir a conta com código antes de qualquer número valer. Se a conferência
discordar, a sessão volta a você antes de seguir. Nada em produção é afetado.

### O que ainda falta no caminho

- **Esta sessão (P5.1):** desenhar a amostra e montar o pacote de rotulagem, e
  parar antes de qualquer revisor.
- **Rotulagem:** as pessoas interpretam as imagens às cegas; só começa depois
  dos itens 3 e 4 acima.
- **Cálculo e relatório da Phase 5:** precisão, omissão, intervalos e o
  relatório versionado; o que permite afirmar acurácia.
- **Duas semanas de vigia da Phase 6 (C6):** conferir quatro rodadas seguidas
  do sistema novo, a partir de 10 de novembro. Roda em paralelo a esta.
- **A série de índices do sistema novo:** a aba "Séries" parou em setembro; um
  pacote logo depois da vigia.
- **Fase 7:** testes completos, proteção de branch, acessibilidade e as skills
  reutilizáveis.
