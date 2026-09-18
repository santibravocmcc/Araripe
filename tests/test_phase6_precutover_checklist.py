"""A checklist pré-cutover da §7 do runbook tem de descrever o presente.

Por que este arquivo existe. A §7 foi escrita em 2026-09-08 e submetida à
revisão do dono como se ainda valesse. Uma das suas cláusulas pedia aceitação de
que *"a produção azul continua rodando"* — e em 2026-09-17 a produção estava
parada havia quatro execuções agendadas. Uma checklist cujas cláusulas mudaram
de verdade não é uma checklist: é uma armadilha de consentimento, e ela não
falha barulhento, porque o documento continua bem formado.

`tests/test_replay_freeze.py` já impede o runbook de nomear alvos que o código
não resolve. Ele não impede o runbook de **afirmar um fato do mundo que deixou
de ser verdade**, que é outra classe de erro: a primeira se verifica contra o
repositório, esta contra uma medição datada. O que dá para exigir em teste é a
disciplina que torna a segunda auditável — que uma afirmação sobre o estado
operacional venha datada, e que a afirmação falsa específica que já enganou não
volte sem alguém apagar a correção deliberadamente.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "operations" / "PHASE_3_REPLAY_RUNBOOK.md"


def _runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Colapsa todo espaço em branco num espaço só.

    Sem isto, um guarda por frase literal é derrotado por uma **quebra de
    linha**, e derrotado em silêncio: o texto continua lá, a asserção não casa
    mais, e o teste vira verde por reformatação. Aconteceu na primeira escrita
    deste arquivo — `Não é\nemergência de horas` não casava `não é emergência
    de horas`. Toda comparação de frase aqui passa por esta função.
    """

    return " ".join(text.split())


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end)]


def test_o_runbook_nao_afirma_que_a_producao_azul_continua_rodando():
    """A frase exata que a checklist de 2026-09-08 mandava aceitar.

    Medido em 2026-09-17 com `gh run list`: `detect_gee.yml` falhou nas quatro
    execuções agendadas de 09-10, 09-14 e 09-17 (mais 09-07, por outra causa), e
    a última escrita em produção foi a execução manual de 2026-09-07 15:15 UTC.

    Esta asserção é sobre a afirmação **no presente**. O runbook pode — e deve —
    citar a instrução do roadmap de *não pausar* a automação, que é uma ordem e
    não uma medição, e pode narrar o passado com data.
    """

    text = _runbook()
    # O corte é pela ESTRUTURA, e não pela vizinhança do texto. A frase aparece
    # legitimamente três vezes dentro da §7 — na cláusula que a declara falsa e
    # na tabela do diff que a cita como a redação antiga — e um casador de
    # string não distingue "X" de "X é falso". Tentar distinguir por proximidade
    # de uma negação é frágil; o que é robusto é o limite da seção: a §7 é a
    # seção cujo trabalho inteiro é registrar o que mudou, e em todo o resto do
    # documento a frase só poderia ser uma afirmação.
    #
    # Escopar é a diferença entre proibir a AFIRMAÇÃO e proibir a PALAVRA —
    # proibir a palavra apagaria o registro do que mudou.
    revisao = _section(text, "## 7. A revisão do dono", "## 8.")
    corpo = text.replace(revisao, "")

    proibidas = (
        "produção azul continua rodando",
        "produção azul segue rodando",
        "a produção azul continua ativa",
        "o azul continua rodando",
    )
    for frase in proibidas:
        assert frase not in _flat(corpo), (
            f"o runbook volta a afirmar {frase!r} no presente; a produção está "
            "parada desde o landing do 2A.6 — ver PHASE_4C_2026-09-16.md §11"
        )


def test_o_runbook_registra_a_parada_da_producao_com_data_e_causa():
    """O contrapositivo do teste acima, para ele não passar por apagamento.

    Sem isto, remover a frase falsa **e** a correção que a substitui deixaria os
    dois testes verdes com o documento pior do que antes: silencioso sobre uma
    produção parada. A mutação que este teste derruba é exatamente essa.
    """

    text = _runbook()
    assert "LegacyPersistenceStateError" in text
    assert "PHASE_4C_2026-09-16.md" in text
    assert re.search(r"2026-09-1[047]", text), "a parada é datada"
    assert "conserto é o cutover" in _flat(text), (
        "o runbook tem de dizer que o conserto é o cutover, e não um patch: "
        "um patch no loader reabriria o contrato que o 2A.6 fechou"
    )


def test_a_checklist_pre_cutover_declara_quando_foi_reescrita():
    """Uma lista submetida ao dono tem de dizer contra qual presente foi escrita.

    A data é o que permite a próxima sessão perguntar 'isto ainda vale?' em vez
    de herdar as cláusulas como se fossem atemporais.
    """

    secao = _section(_runbook(), "## 7. A revisão do dono", "## 8.")
    assert re.search(r"reescrita contra o presente em \d{4}-\d{2}-\d{2}", _flat(secao))
    assert "armadilha de consentimento" in _flat(secao)


def test_todo_item_da_checklist_carrega_evidencia_ou_data():
    """Um item sem evidência não é revisável: o dono não tem como conferir.

    Exige que cada item — aberto ou fechado — nomeie um documento, um arquivo de
    configuração, um teste, um comando ou uma data. A mutação que isto derruba é
    acrescentar uma cláusula nova em prosa, sem apontar para nada.
    """

    secao = _section(_runbook(), "## 7. A revisão do dono", "### O diff desta")
    itens = re.findall(r"^- \[[ x]\] (.+?)(?=^- \[|\Z)", secao, re.M | re.S)
    assert len(itens) >= 6, f"esperado ao menos 6 itens na checklist, li {len(itens)}"
    marcas = (".md", ".json", ".py", "pytest", "gh api", "gh run", "20" "26-")
    for item in itens:
        assert any(m in item for m in marcas), f"item sem evidência: {item[:90]!r}"


def test_a_checklist_mostra_o_diff_do_que_mudou():
    """Reescrever a lista e mostrar só o resultado esconde a reescrita.

    O dono precisa ver que uma cláusula mudou **e qual era** — senão a reescrita
    é indistinguível de sempre ter dito isso.
    """

    # Fim da fatia é o cabeçalho da §8, e não uma frase do corpo. A primeira
    # versão ancorava em "Registre a revisão", e a frase mudou quando a revisão
    # foi feita — a fatia quebrou por reescrita e não por defeito. Um cabeçalho
    # de seção é o que há de mais estável num documento markdown.
    secao = _section(_runbook(), "### O diff desta reescrita", "## 8.")
    assert "cláusula de 2026-09-08" in _flat(secao)
    for veredito in ("**reescrita", "**fechada", "**acrescentada", "**mantida"):
        assert veredito in _flat(secao), veredito
    assert "produção azul continua rodando" in _flat(secao), (
        "a frase falsa tem de aparecer na tabela do diff, citada como o que ela "
        "era — é o único lugar do documento onde ela pode aparecer"
    )


def test_a_divergencia_da_secao_8_esta_fechada_contra_o_arquivo_de_decisao():
    """A §8 pergunta; a Phase 4 respondeu. As duas metades têm de concordar.

    Se o runbook fechasse o item nomeando uma unidade que o arquivo de decisão
    não decidiu, a Phase 6 leria a errada.
    """

    decisao = json.loads(
        (ROOT / "config" / "phase4_composition_unit_decision_v1.json").read_text(
            encoding="utf-8"
        )
    )
    unidade = decisao["composition_unit"]
    grade = decisao["export_grid"]
    text = _runbook()
    assert unidade["decided"] in text
    assert unidade["composite_method_id"] in text
    assert grade["decided"] in text
    assert "phase4_composition_unit_decision_v1.json" in text


def test_a_fila_pos_corte_nao_e_mais_declarada_vazia_sem_ressalva():
    """A Phase 3 registrou 0 datas medindo o banco azul, que não podia saber.

    A Phase 4 re-enumerou e achou 3 — e esse 3 também envelhece, porque foi
    medido numa janela que fechou. O runbook tem de carregar a ressalva, senão a
    drenagem reusa um número em vez de re-enumerar.
    """

    secao = _section(_runbook(), "## 6. Drenagem da fila", "## 7.")
    assert "3** datas" in _flat(secao) or "**3** datas" in _flat(secao)
    assert "envelhecido" in _flat(secao) or "envelheceu" in _flat(secao)
    assert "Re-enumere" in _flat(secao) or "re-enumere" in _flat(secao)


# ── o dossiê de decisão do dono ─────────────────────────────────────────────

DOSSIE = ROOT / "docs" / "operations" / "PHASE_6_OWNER_DECISIONS_2026-09-17.md"


def _decisoes() -> list[tuple[str, str]]:
    """Devolve (título, corpo) de cada bloco `## Dn — …` do dossiê."""

    text = DOSSIE.read_text(encoding="utf-8")
    partes = re.split(r"^## (D\d — .+)$", text, flags=re.M)
    return list(zip(partes[1::2], partes[2::2]))


def test_toda_decisao_do_dossie_carrega_os_cinco_elementos():
    """O contrato pedido: em jogo, opções, custo medido, recomendação, e o que
    acontece se esperar.

    Um dossiê a que falta o "se esperar" transforma seis decisões numa lista de
    tarefas sem prioridade — que é a forma mais fácil de o dono adiar a errada.
    E um a que falta "custo medido" é uma opinião com aparência de análise.

    A mutação que isto derruba: acrescentar uma sétima decisão em prosa, ou
    apagar a seção de custo de uma existente.
    """

    decisoes = _decisoes()
    assert len(decisoes) >= 6, f"esperava ao menos 6 decisões, li {len(decisoes)}"
    for titulo, corpo in decisoes:
        for elemento in ("**Em jogo:**", "### As opções", "### Recomendação", "### Se esperar"):
            assert elemento in _flat(corpo), f"{titulo}: falta {elemento}"
        assert re.search(r"### Custo", _flat(corpo)), f"{titulo}: falta a seção de custo"


def test_o_dossie_nao_recomenda_sem_dizer_o_porque():
    """Uma recomendação sem razão é uma ordem, e o dono não delegou isso."""

    for titulo, corpo in _decisoes():
        rec = corpo[corpo.index("### Recomendação") :]
        rec = rec[: rec.index("### Se esperar")]
        assert len(rec.split()) >= 25, (
            f"{titulo}: a recomendação tem {len(rec.split())} palavras — "
            "curta demais para carregar o porquê"
        )


def test_o_dossie_registra_o_que_eu_retirei_depois_de_medir():
    """Duas linhas de raciocínio foram escritas e retiradas por medição.

    Registrá-las é o que impede a próxima sessão de as redescobrir e as tratar
    como novas — e é o que permite ao dono ver que a recomendação mudou por
    evidência, e não por preferência.
    """

    text = DOSSIE.read_text(encoding="utf-8")
    assert "retirei" in text or "retirado" in text or "retirada" in text
    assert "inalcançáveis" in _flat(text), (
        "a medição que derrubou o argumento do `runs/` exposto tem de estar no "
        "documento, não só na minha cabeça"
    )
    assert "anula o próprio pacote" in _flat(text), (
        "a razão de o revisor em v2-promotion não servir como mitigação"
    )


def test_o_dossie_nao_inventa_urgencia_sem_medicao():
    """A urgência declarada é a produção parada, e ela tem de vir com a medição
    que a sustenta — data, exceção e o que conserta.
    """

    text = DOSSIE.read_text(encoding="utf-8")
    assert "LegacyPersistenceStateError" in text
    assert "2026-09-17" in text
    assert "gh run list" in text
    assert "não é emergência de horas" in _flat(text).lower(), (
        "a urgência tem de vir calibrada: exagerá-la é tão ruim quanto omiti-la"
    )


# ── as decisões do dono, e o que elas NÃO autorizam ─────────────────────────

DECISOES = ROOT / "config" / "phase6_owner_decisions_v1.json"


def _decisoes_json() -> dict:
    return json.loads(DECISOES.read_text(encoding="utf-8"))


def test_a_revisao_pre_cutover_so_e_declarada_feita_com_registro_datado():
    """A revisão foi FEITA em 2026-09-18. Este guarda mudou de direção nesse dia.

    Ele nasceu exigindo `review_performed: false`, porque a resposta que existia
    era de **cronograma** — o dono havia escolhido *quando* revisar, e fechar o
    portão com isso seria fabricar consentimento a partir de um "sim" sobre
    outra pergunta. Em 2026-09-18 o dono confirmou os três itens, e a asserção
    antiga passou a proibir o fato.

    Então ele inverteu, e **a proteção não foi perdida** — foi movida: declarar
    a revisão feita agora exige o registro datado, a resposta literal, os itens
    nomeados, e a afirmação de qual TEXTO foi revisado. A mutação que isto
    derrubaria é a mesma de antes numa roupa nova: alguém marcar
    `review_performed: true` sem registro, no próximo item que precise de
    revisão.

    A cláusula sobre qual texto foi revisado não é zelo. A lista foi reescrita
    contra o presente antes de ser submetida, e um registro que não dissesse
    isso seria indistinguível, num ano, de uma revisão feita sobre as frases
    velhas — que é exatamente o que a reescrita existiu para evitar.
    """

    d = _decisoes_json()["d2_pre_cutover_review"]
    assert d["decided"] == "review_now"

    if not d["review_performed"]:
        # Estado anterior a 2026-09-18, preservado: sem revisão, o runbook tem
        # de continuar com item aberto e nomear o que falta.
        assert d.get("items_still_awaiting_the_owner"), "tem de nomear o que falta"
        assert "- [ ]" in _runbook(), "sem revisão, o runbook tem item aberto"
        return

    assert d["review_performed_on"] == "2026-09-18"
    assert d["review_answered"], "a resposta literal do dono tem de ficar registrada"
    assert d["items_confirmed"], "e os itens que ela confirmou"
    assert d["reviewed_text_was_the_rewritten_list"] is True
    assert d["why_that_distinction_is_recorded"]
    assert d["gate_1_closed"] is True

    registro = ROOT / d["review_record"]
    assert registro.is_file(), f"o registro {d['review_record']} não existe"
    texto = _flat(registro.read_text(encoding="utf-8"))
    assert d["review_answered"] in texto, "o registro tem de citar a resposta"
    assert "reescrita" in texto, "e dizer que a lista revisada era a reescrita"

    # E o portão fechado não é os outros três.
    assert "portão 1" in texto or "portao 1" in texto
    for nao_autoriza in ("não autoriza a virada", "revogar"):
        assert nao_autoriza in texto, nao_autoriza


def test_fechar_a_revisao_nao_abre_os_outros_portoes():
    """Um portão de quatro. Sem isto, "a revisão está feita" lê como "pode ir".

    Os portões 2 e 3 são CAPACIDADES que faltam — um hostname e um Environment —
    e nenhuma revisão as cria.
    """

    d = _decisoes_json()
    assert d["authorization"]["cutover_execution_authorized_by_this_decision"] is False
    assert d["d2_pre_cutover_review"]["what_it_does_not_authorize"]
    # medido em 2026-09-17 e 2026-09-18, e é o portão 3
    assert d["d4_site_protected_environment"]["measured_state_before"].count("[]") >= 1
    secao = _flat(_section(_runbook(), "## 7. A revisão do dono", "## 8."))
    assert "portões 2" in secao and "fechados" in secao


def test_as_decisoes_nao_autorizam_o_cutover():
    """Seis respostas abrem portões. Nenhuma autoriza executar a virada.

    Sem isto, uma sessão futura leria "o dono decidiu tudo" e trataria os passos
    do §4.4 como aprovados — quando cada passo que afeta produção espera
    aprovação explícita no momento em que é executado.
    """

    a = _decisoes_json()["authorization"]
    assert a["production_mutation_permitted"] is False
    assert a["cutover_execution_authorized_by_this_decision"] is False
    assert a["why_the_cutover_is_not_authorized_here"]


def test_a_revogacao_da_credencial_e_o_ultimo_passo_e_nao_o_primeiro():
    """A condição de ordem que eu escrevi errado, agora em teste.

    Eu recomendei revogar `claude-araripe-v2-staging-rw` depois de os produtos
    do site estarem gerados. Medido depois: os produtos nunca precisaram dela
    (`RouteReader` é um GET sem credencial), e quem precisa é a reprova da D5,
    que roda numa branch — e os três Environments só aceitam `main`.

    A mutação que isto derruba: alguém "simplificar" a condição de volta para a
    versão antiga, que autoriza revogar cedo e torna a D5 improvável.
    """

    d = _decisoes_json()["d1_where_the_new_version_lives"]
    ordering = d["revocation_ordering"]
    assert "D5" in ordering["condition"]
    assert ordering["corrected_on"] == "2026-09-18"
    assert ordering["the_condition_as_first_written"], (
        "a condição errada tem de ficar registrada; apagá-la deixa a próxima "
        "sessão sem saber que esta já foi pensada de outro jeito"
    )
    assert ordering["why_that_was_too_early"]
    d5 = _decisoes_json()["d5_durable_promotion_history"]
    assert d5["blocks_revocation"] is True, (
        "o campo é booleano de propósito: uma string como 'yes — ver X' passa "
        "por um `== 'yes'` errado e falha por prosa, não por conteúdo"
    )


def test_toda_acao_do_dono_diz_por_que_o_agente_nao_pode_faze_la():
    """Uma lista de ações do dono sem o porquê convida a tentativa.

    Este projeto já pagou por isso: um pré-requisito da Phase 6 viajou como
    pedido ao dono por quatro briefings sem ninguém dizer que era ação dele.
    Aqui o inverso também tem de valer — se um item é ação do dono, o arquivo
    diz qual capacidade falta ao agente.
    """

    acoes = _decisoes_json()["owner_actions_outstanding"]
    assert len(acoes) >= 4
    for acao in acoes:
        assert acao["agent_can_do_it"] is False, acao["action"]
        assert acao.get("why") or acao.get("do_not_do_it_before"), acao["action"]
        assert acao["blocks"], acao["action"]


def test_o_runbook_e_o_arquivo_de_decisao_concordam_sobre_o_bucket():
    """Duas metades que discordassem fariam a virada ler a errada."""

    d = _decisoes_json()["d1_where_the_new_version_lives"]
    assert d["bucket"] == "araripe-v2-staging"
    from src.publication import conditional_store as cs

    assert d["bucket"] == cs.STAGING_BUCKET, (
        "a decisão nomeia um bucket que o código não é o que escreve"
    )
    secao = _section(_runbook(), "## 7. A revisão do dono", "## 8.")
    assert "phase6_owner_decisions_v1.json" in _flat(secao)
    assert "promover" in _flat(secao) and d["bucket"] in secao


# ── os roteiros do dono para os portões 2 e 3 ───────────────────────────────

ROTEIROS = ROOT / "docs" / "operations" / "PHASE_6_OWNER_RUNBOOKS_2026-09-18.md"
BROKER = ROOT / ".github" / "workflows" / "cloudflare_green_control.yml"


def _roteiros() -> str:
    return ROTEIROS.read_text(encoding="utf-8")


def test_o_roteiro_nao_manda_ampliar_o_broker():
    """A saída barata do portão 2 é acrescentar uma operação ao broker. Não é.

    O briefing da fase assumia que seria — *"mudança de broker mais mutação
    revisada"*. Medido: `ALLOWED_OPERATIONS` tem exatamente três operações e
    **nenhuma abre** o subdomínio; as três conferem ou fecham. Uma operação que
    *aumenta* exposição é mudança de categoria no broker, e
    `enforce-worker-isolation` já faz o fechamento de que a janela precisa.

    A mutação que isto derruba: um roteiro futuro que instrua a abrir o
    subdomínio por uma operação nova do broker, ampliando a autoridade de
    control-plane de um agente para uma verificação única.
    """

    texto = _flat(_roteiros())
    assert "NÃO é necessária" in texto or "não é necessária" in texto
    assert "recomendo não acrescentar a operação ao broker" in texto.lower()
    assert "o senhor abre no painel" in texto, (
        "o roteiro tem de dizer de quem é a ação: do dono, no painel"
    )


def test_o_roteiro_nomeia_a_allowlist_do_broker_exatamente_como_ela_e():
    """Um roteiro que prometesse uma quarta operação convidaria a tentativa.

    Lido do arquivo do broker, não da memória: se alguém acrescentar uma
    operação lá e não aqui, isto cai.
    """

    broker = BROKER.read_text(encoding="utf-8")
    import re

    bloco = broker[broker.index("options:") : broker.index("confirmation:")]
    operacoes = set(re.findall(r"^\s+- ([a-z-]+)$", bloco, re.M))
    assert operacoes == {"audit", "enforce-worker-isolation", "disable-site-branch-deploy"}, operacoes

    texto = _flat(_roteiros())
    for operacao in operacoes:
        assert operacao in texto, operacao
    assert "exatamente" in texto


def test_o_roteiro_poe_o_deploy_antes_de_abrir_o_subdominio():
    """A ordem inversa desperdiça o passo, e a razão é documentada pela Cloudflare.

    `wrangler.green.jsonc` declara `workers_dev: false`, e um deploy com esse
    campo **desliga** a rota workers.dev. Abrir no painel e depois implantar
    fecha o que acabou de abrir — e o operador leria o 404 como defeito da rota.
    """

    texto = _roteiros()
    assert texto.index("B.0") < texto.index("B.1"), "o pré-requisito vem antes"
    flat = _flat(texto)
    assert "o deploy vem antes do hostname" in flat
    assert "workers_dev" in flat and "desliga" in flat
    assert "não é preferência" in flat, (
        "a ordem tem de ser declarada como restrição e não como estilo"
    )


def test_o_roteiro_avisa_que_o_audit_falha_com_a_janela_aberta():
    """`audit` exige o subdomínio desligado, e duas das três operações o chamam.

    Sem este aviso o dono veria `audit` vermelho e pensaria ter quebrado algo.
    E `disable-site-branch-deploy` é pior: ele MUTA e só então audita, então a
    mutação entra e a execução reporta falha.
    """

    controlador = (ROOT / "scripts" / "cloudflare_green_control.py").read_text(encoding="utf-8")
    # a ordem no código é o que o roteiro descreve: PATCH e depois audit
    corpo = controlador[controlador.index("def disable_site_nonproduction_deploy") :]
    corpo = corpo[: corpo.index("def parse_args")]
    assert corpo.index('client.request(\n        "PATCH"') < corpo.index("audit(client)")

    flat = _flat(_roteiros())
    assert "não rode" in flat.lower()
    assert "a mutação entra e a execução reporta falha" in flat


def test_o_roteiro_diz_que_o_token_nunca_vem_para_o_agente():
    """Permissão de Workers é de CONTA. O token alcança o Worker de produção.

    O roteiro manda o dono criar um token que implanta qualquer Worker da conta.
    Ele tem de dizer, no mesmo lugar, que o token não passa por mim e por quê —
    senão a instrução mais perigosa do documento viaja sem a sua ressalva.
    """

    flat = _flat(_roteiros())
    assert "nunca vem para mim" in flat
    assert "permissão de Workers é de" in flat and "conta" in flat
    assert "observatorio-chapada" in flat, "e tem de nomear o Worker que ele alcança"
    assert "Workers Scripts" in flat and "Edit" in flat


def test_o_roteiro_nao_afirma_que_o_environment_do_site_existe():
    """Ele PROPÕE um nome. Afirmar que existe seria o erro que o projeto já pagou.

    E a assimetria é deliberada: eu não escrevo `environment:` em workflow
    nenhum antes de o dono confirmar o nome que ele criou, porque o GitHub cria
    o que for nomeado, sem proteção.
    """

    flat = _flat(_roteiros())
    assert "[]" in flat, "o estado medido (nenhum Environment) tem de estar no texto"
    assert "me diga qual" in flat, (
        "o roteiro tem de pedir o nome de volta em vez de presumi-lo"
    )
    assert "eu não escrevo o nome antes de ele existir" in flat
