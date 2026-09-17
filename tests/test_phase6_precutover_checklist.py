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
    # A tabela do diff (§7) cita a frase falsa como o que ela *era*, e o teste
    # `test_a_checklist_mostra_o_diff_do_que_mudou` exige essa citação. Os dois
    # guardas juntos dizem uma coisa só: a frase pode existir citada como
    # história, e em lugar nenhum mais. Escopar é a diferença entre proibir a
    # afirmação e proibir a palavra — e proibir a palavra apagaria o registro.
    citacao = _section(text, "### O diff desta reescrita", "Registre a revisão")
    corpo = text.replace(citacao, "")

    proibidas = (
        "produção azul continua rodando",
        "produção azul segue rodando",
        "a produção azul continua ativa",
        "o azul continua rodando",
    )
    for frase in proibidas:
        assert frase not in corpo, (
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
    assert "conserto é o cutover" in text, (
        "o runbook tem de dizer que o conserto é o cutover, e não um patch: "
        "um patch no loader reabriria o contrato que o 2A.6 fechou"
    )


def test_a_checklist_pre_cutover_declara_quando_foi_reescrita():
    """Uma lista submetida ao dono tem de dizer contra qual presente foi escrita.

    A data é o que permite a próxima sessão perguntar 'isto ainda vale?' em vez
    de herdar as cláusulas como se fossem atemporais.
    """

    secao = _section(_runbook(), "## 7. A revisão do dono", "## 8.")
    assert re.search(r"reescrita contra o presente em \d{4}-\d{2}-\d{2}", secao)
    assert "armadilha de consentimento" in secao


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

    secao = _section(_runbook(), "### O diff desta reescrita", "Registre a revisão")
    assert "cláusula de 2026-09-08" in secao
    for veredito in ("**reescrita", "**fechada", "**acrescentada", "**mantida"):
        assert veredito in secao, veredito
    assert "produção azul continua rodando" in secao, (
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
    assert "3** datas" in secao or "**3** datas" in secao
    assert "envelhecido" in secao or "envelheceu" in secao
    assert "Re-enumere" in secao or "re-enumere" in secao
