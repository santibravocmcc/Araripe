# Como escrever um prompt de handoff de package

**Método versão:** `2`
**Definido:** 2026-09-07, a pedido do dono, depois do Package 2B.2B

Ao fim de cada sessão de package, o agente escreve o briefing da sessão
seguinte em `docs/operations/PACKAGE_<pacote>_PROMPT.md`. Ele vive na `main`
pelo mesmo motivo dos dois primeiros: o executor trabalha a partir da `main`, e
um briefing que só existisse noutra branch repetiria a falha de leitura entre
branches que o `AGENTS.md` proíbe.

O documento tem **dois públicos** e é isso que o método precisa resolver:

- o **agente executor**, que precisa de precisão — SHAs, caminhos, nomes de
  teste, medições, as armadilhas já pagas;
- o **dono**, que precisa saber o que fazer com o que acabou de ser entregue,
  sem ler 300 linhas de detalhe técnico.

Até a versão 1 do método só o primeiro público era servido. O dono tinha de
extrair as suas próprias ações do meio da precisão técnica. A versão 2 corrige
isso com uma seção final obrigatória.

---

## 1. Corpo do briefing (para o agente executor)

As seções que já funcionam nos dois primeiros prompts, nesta ordem:

1. **A dependência que precede tudo.** O que tem de estar mesclado/existir
   antes de qualquer linha de código, e **como confirmar por conteúdo, nunca
   por ancestralidade** — com os comandos exatos. Diga o número esperado de
   testes na base.
2. **O que já foi verificado, para o executor não refazer.** Achados, não
   suposições, cada um com a ferramenta que produziu o valor. Inclua os
   **resultados negativos** — "verifiquei que X não é o caso" é o que impede a
   próxima sessão de rederivar.
3. **A tarefa**, com o modelo e o effort recomendados em destaque, e o porquê.
4. **O escopo**, item por item, na ordem em que se sustentam. E o **fora de
   escopo, explicitamente**, nomeando o package que é dono de cada coisa.
5. **Decisões de escopo já tomadas, com a base.** Com a instrução de não
   reabrir sem evidência contrária.
6. **Fronteiras duras.** Produção, `main` protegida, credenciais, aprovações.
7. **Armadilhas já pagas — não redescobrir.**
8. **Estado que o package herda.**

Regras de conteúdo: copie todo identificador da ferramenta que o produz, nunca
complete um de memória; nunca afirme invariante que o produtor não promete; e
prefira apontar para o documento canônico a duplicá-lo.

## 2. Seção final obrigatória (para o dono)

**Todo prompt de handoff termina com esta seção, e ela é a última.** Em
linguagem simples: frases curtas, sem jargão, sem SHA, sem nome de função, sem
nome de teste. Se um detalhe técnico for indispensável, ele fica no corpo do
documento e aqui entra só a consequência.

Quatro perguntas, sempre nesta ordem, sempre com estes títulos:

```markdown
## N. Para o dono — em linguagem simples

### O que ficou pendente da tarefa atual

### O que você precisa fazer

### Tem algo preocupante?

### O que ainda falta no caminho
```

O que cada uma responde:

- **O que ficou pendente** — o que a sessão que acabou *não* terminou, e por
  quê. Se terminou tudo, diga isso em uma frase. Não repita aqui o que foi
  entregue; o dono quer saber o que sobrou.
- **O que você precisa fazer** — a lista de ações do **dono**, não do agente:
  mesclar uma PR, aprovar algo, criar uma credencial, decidir uma questão,
  rodar uma prova. Cada item numerado, começando com o verbo, e dizendo se é
  urgente ou pode esperar. Se não há nada, diga "nada" — e diga isso com
  clareza, porque é uma informação boa.
- **Tem algo preocupante?** — só o que exige atenção do dono e tem custo real
  se for ignorado: produção que vai quebrar, prazo que vence, dado que se
  perde, decisão que bloqueia o resto. **Se não há nada preocupante, escreva
  "Não." e a razão em uma linha.** Nunca inflar esta seção para parecer
  diligente: uma seção de alarme que sempre tem alarme deixa de ser lida.
- **O que ainda falta no caminho** — a lista das etapas seguintes (2B.2C,
  2B.3, 2B.4, Phase 3…), uma linha cada, dizendo em português comum o que cada
  uma faz e o que ainda falta nela. É a resposta a "onde estamos?" sem abrir o
  roadmap.

### Por que separada, e não distribuída pelo texto

Porque a informação que o dono precisa é sobre *ações*, e a que o agente
precisa é sobre *fatos*. Misturar as duas fez o dono ter de reconstruir a sua
própria lista de tarefas a partir de um documento escrito para outra pessoa.

### O mesmo bloco fecha a resposta no chat

Quando a sessão termina, ou quando a skill `araripe-safe-handoff` cria um
checkpoint por falta de capacidade, a resposta no chat termina com as mesmas
quatro perguntas. O checkpoint gerado pela skill ainda não carrega este bloco
no próprio arquivo — o gerador tem validação própria e mudá-lo é tarefa
separada.

## 3. O método é testado, não só escrito

`tests/test_handoff_prompt_method.py` exige a seção final e os seus quatro
títulos em todo `docs/operations/PACKAGE_*_PROMPT.md`, exige que ela seja a
última, e proíbe SHA de 40 caracteres dentro dela.

Os prompts do 2B.2A e do 2B.2B **antecedem** este método e estão numa lista de
exceção explícita no teste. Essa lista não pode crescer em silêncio: aumentá-la
é um diff visível. Os dois não foram reescritos de propósito — um bloco "o que
ficou pendente" acrescentado hoje a um briefing já consumido descreveria um
presente que não era o presente deles.
