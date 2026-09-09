"""The owner's overlap rule, and the requirement it has to enforce.

The owner's instruction carried a design requirement as well as a value:
*nothing that needs human review may remain in the final production system*.
A threshold that merely was not observed to raise does not meet that. So the
central test here is not that the reader parses a number — it is that a value
which leaves the refusal reachable is REFUSED, and that the chosen value makes
the refusal impossible on geometry that provably triggers it at the old value.
"""
from __future__ import annotations

import json

import pytest

from src.replay.overlap_decision import (
    MAJORITY_BOUND,
    OverlapDecisionError,
    load_decision,
)


def _document(**overrides):
    body = {
        "decision_id": "araripe-phase4-persistence-overlap-decision-v1",
        "decision_date": "2026-09-09",
        "authorization": {
            "decided_by": "project_owner",
            "blue_default_change_permitted": False,
            "production_mutation_permitted": False,
        },
        "decided": {
            "min_overlap_fraction": "0.55",
            "rule_in_words": "a majority of the new detection must lie inside the event",
            "supersedes_for_the_replay": "0.05",
        },
    }
    body.update(overrides)
    return body


def _write(tmp_path, document):
    path = tmp_path / "decision.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_a_decisao_real_do_dono_e_lida_e_e_uma_regra_de_maioria():
    """O caminho honesto: a decisão gravada, lida, e coerente com as palavras.

    Nota: `is_majority_rule` NÃO afirma que a recusa de linhagem ficou
    impossível. A primeira versão deste módulo afirmava isso e a medição a
    desmentiu — ver o docstring de `src/replay/overlap_decision.py`.
    """

    decision = load_decision()
    assert decision.decided_by == "project_owner"
    assert decision.min_overlap_fraction == 0.55
    assert decision.min_overlap_fraction > MAJORITY_BOUND
    assert decision.is_majority_rule is True
    assert not hasattr(decision, "guard_is_structurally_unreachable"), (
        "the property that asserted impossibility was removed because the "
        "claim was measured false; it must not come back"
    )
    assert decision.supersedes == "0.05"
    assert "majority" in decision.rule_in_words.lower()


def test_um_valor_que_nao_e_maioria_e_RECUSADO(tmp_path):
    """Derruba: um número que contradiz as palavras da própria decisão.

    O documento declara, em palavras, uma regra de **maioria**: a maioria da
    área da nova detecção tem de estar dentro do evento. Um valor de `0.30`
    grava um número que não é maioria de nada, e o par documento-número passa
    a dizer duas coisas.

    Este teste **não** afirma que `0.55` torna a recusa impossível. A primeira
    versão dele afirmava, com o argumento de que dois pais disjuntos não cabem
    acima de meio — e a medição mostrou que os pais **não são disjuntos** depois
    que a linhagem opera. O piso é política coerente com a regra, não prova.
    """

    for reachable in ("0.30", "0.40", "0.50", "0.05", "0.01"):
        document = _document()
        document["decided"]["min_overlap_fraction"] = reachable
        with pytest.raises(OverlapDecisionError, match="not the majority rule"):
            load_decision(_write(tmp_path, document))

    # and strictly above the bound is accepted
    document = _document()
    document["decided"]["min_overlap_fraction"] = "0.51"
    assert load_decision(_write(tmp_path, document)).min_overlap_fraction == 0.51


def test_a_regra_e_do_dono_e_nao_do_agente(tmp_path):
    """Derruba: um agente decidindo a régua por si.

    Isto muda o que o sistema chama de "o mesmo evento em duas datas", que é
    científico. A sessão anterior mediu a consequência e escalou em vez de
    escolher; o leitor exige que a autoria seja a do dono.
    """

    document = _document()
    document["authorization"]["decided_by"] = "executing_agent"
    with pytest.raises(OverlapDecisionError, match="must be the owner"):
        load_decision(_write(tmp_path, document))


def test_a_decisao_nao_pode_se_autoconceder_producao(tmp_path):
    """Derruba: a decisão do replay movendo o default do azul."""

    for field in ("blue_default_change_permitted", "production_mutation_permitted"):
        document = _document()
        document["authorization"][field] = True
        with pytest.raises(OverlapDecisionError):
            load_decision(_write(tmp_path, document))


def test_um_float_no_documento_e_recusado(tmp_path):
    """Derruba: gravar a fração como número JSON.

    `json.dumps` e a forma RFC 8785 discordam em float de valor integral e em
    expoente, e um documento que pode ser canonicalizado depois não carrega um.
    """

    document = _document()
    document["decided"]["min_overlap_fraction"] = 0.55
    with pytest.raises(OverlapDecisionError, match="must be recorded as a string"):
        load_decision(_write(tmp_path, document))


def test_uma_decisao_que_nao_muda_nada_e_recusada(tmp_path):
    """Derruba: um documento que declara o próprio default do azul.

    Um documento que diz ter mudado a régua e grava `0.05` é pior que documento
    nenhum, porque some da revisão.
    """

    from src.detection.persistence import DEFAULT_MIN_OVERLAP_FRAC

    document = _document()
    # phrase it above the structural bound so it fails on the right check
    document["decided"]["min_overlap_fraction"] = repr(DEFAULT_MIN_OVERLAP_FRAC)
    with pytest.raises(OverlapDecisionError):
        load_decision(_write(tmp_path, document))


def test_o_default_do_azul_continua_005():
    """Derruba: carregar a decisão do replay para dentro do caminho azul.

    Espelha `test_decidir_o_replay_nao_move_o_default_do_azul` da baseline: os
    dois valores têm de continuar diferentes e ambos gravados. A produção está
    congelada nas Fases 2B-5.
    """

    from src.detection.persistence import DEFAULT_MIN_OVERLAP_FRAC

    assert DEFAULT_MIN_OVERLAP_FRAC == 0.05
    assert load_decision().min_overlap_fraction != DEFAULT_MIN_OVERLAP_FRAC


def test_o_driver_passa_o_valor_decidido_para_update_tracks():
    """Derruba: ler a decisão e não usá-la.

    O bug plausível não é esquecer de ler — é ler, imprimir, e deixar
    `update_tracks` resolver o default. Uma varredura de string veria o import
    e diria que está ligado, então isto lê a árvore e exige o argumento
    nomeado na chamada.
    """

    import ast
    from pathlib import Path

    driver = Path(__file__).resolve().parents[1] / "scripts" / "replay_2026.py"
    tree = ast.parse(driver.read_text(encoding="utf-8"))

    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "update_tracks"
    ]
    assert calls, "the driver does not call update_tracks"
    for call in calls:
        named = {kw.arg for kw in call.keywords}
        assert "min_overlap_frac" in named, (
            "update_tracks is called without min_overlap_frac, so it resolves "
            "the blue default and the owner's decision does nothing"
        )
        source = next(
            kw.value for kw in call.keywords if kw.arg == "min_overlap_frac"
        )
        # it must come from the decision object, not a literal
        assert isinstance(source, ast.Attribute), ast.dump(source)
        assert source.attr == "min_overlap_fraction", ast.dump(source)


# ── the structural property, against the real update_tracks ─────────────────


def _acquisition(date, scene_id):
    from config.settings import MONITORING_EXTENT_ID
    from src.detection.identity import create_acquisition_identity

    return create_acquisition_identity(
        collection_id="COPERNICUS/S2_SR_HARMONIZED",
        observed_on=date,
        scene_ids=[scene_id],
        monitoring_extent_id=MONITORING_EXTENT_ID,
        composite_method_id="datatake_mosaic-v1",
    )


def _frame(polygons):
    import geopandas as gpd

    return gpd.GeoDataFrame(
        {"confidence": [3] * len(polygons), "area_ha": [1.0] * len(polygons)},
        geometry=list(polygons),
        crs="EPSG:4326",
    )


def test_o_valor_decidido_resolve_uma_ambiguidade_QUE_O_ANTIGO_RECUSAVA():
    """Derruba: a suposição de que o valor escolhido não muda nada.

    Esta é a prova em código, e ela não é sintética no comportamento: chama o
    `update_tracks` de verdade, com o guarda de verdade, sobre uma geometria
    construída para ser ambígua.

    Dois pais adjacentes e disjuntos, e duas detecções novas que atravessam a
    fronteira entre eles. No valor congelado os dois pais se ligam às duas
    detecções — um componente muitos-para-muitos — e a camada recusa. No valor
    do dono nenhuma ligação se forma, porque nenhuma detecção tem a MAIORIA da
    sua área dentro de um único evento.

    Medido: C fica 25% em cada pai e D fica 50% em cada.

    O que este teste **não** mostra: que a recusa ficou impossível. Ele usa
    dois pais DISJUNTOS. Medido no estado real, depois que a linhagem opera os
    tracks ativos se sobrepõem em área — 1308 pares após 2026-03-13 e 5655
    após 2026-04-04, com sobreposição máxima de 1,000000 — e aí dois pais
    distintos podem ambos ter a maioria da mesma detecção. A recusa continua
    alcançável, e a execução real a viu novamente.
    """

    from shapely.geometry import box

    from config.settings import DETECTION_ALGORITHM_VERSION, MONITORING_EXTENT_ID
    from src.detection.persistence import AmbiguousLineageError, update_tracks

    parents = [
        box(-40.000, -7.000, -39.990, -6.990),
        box(-39.990, -7.000, -39.980, -6.990),
    ]
    crossing = [
        box(-39.9945, -6.9910, -39.9855, -6.9890),
        box(-39.9945, -6.9950, -39.9855, -6.9930),
    ]

    common = dict(
        algorithm_version=DETECTION_ALGORITHM_VERSION,
        baseline_version="2.1.0",
        monitoring_extent_id=MONITORING_EXTENT_ID,
        mode="rebuild",
    )
    _, state = update_tracks(
        _frame(parents), None, "2026-01-01",
        acquisition=_acquisition("2026-01-01", "s1"), **common)
    assert len(state) == 2

    # the frozen value refuses this geometry — so the fixture really is ambiguous
    with pytest.raises(AmbiguousLineageError):
        update_tracks(
            _frame(crossing), state.copy(), "2026-01-06",
            acquisition=_acquisition("2026-01-06", "s2"),
            min_overlap_frac=0.05, **common)

    # and so does the lowest value that cleared the refusal on the real date,
    # which is exactly why that value was not chosen
    with pytest.raises(AmbiguousLineageError):
        update_tracks(
            _frame(crossing), state.copy(), "2026-01-06",
            acquisition=_acquisition("2026-01-06", "s2"),
            min_overlap_frac=0.20, **common)

    # the owner's value does not refuse it
    decided = load_decision().min_overlap_fraction
    merged, _ = update_tracks(
        _frame(crossing), state.copy(), "2026-01-06",
        acquisition=_acquisition("2026-01-06", "s2"),
        min_overlap_frac=decided, **common)
    assert len(merged) == 2
    # nothing chained, because neither detection is a majority of any event —
    # which is the rule working, not the rule failing
    assert (merged["persistence_count"] == 1).all()


def test_a_aritmetica_vale_para_pais_disjuntos_e_NAO_TRANSFERE():
    """Fixa a aritmética E a razão pela qual ela não prova o que eu afirmei.

    A aritmética é verdadeira: partes **disjuntas** de um polígono têm frações
    que somam no máximo 1, logo no máximo uma pode exceder 1/2. Foi daí que
    saiu a afirmação de que acima de meio a recusa era impossível.

    A premissa é que os pais sejam disjuntos, e ela é **falsa** no estado real
    depois que a linhagem opera. Este teste fixa as duas metades: a aritmética
    vale, e a hipótese de disjunção é o que ela exige — para que ninguém
    reconstrua a afirmação a partir da metade verdadeira.
    """

    # the arithmetic, for DISJOINT parts
    for first in range(0, 101):
        second = 100 - first
        fractions = (first / 100.0, second / 100.0)
        above = [f for f in fractions if f > MAJORITY_BOUND]
        assert len(above) <= 1, (fractions, above)

    # and with three parts, likewise
    for first in range(0, 101, 5):
        for second in range(0, 101 - first, 5):
            third = 100 - first - second
            fractions = (first / 100.0, second / 100.0, third / 100.0)
            above = [f for f in fractions if f > MAJORITY_BOUND]
            assert len(above) <= 1, (fractions, above)

    # and the hypothesis the arithmetic needs: OVERLAPPING parents break it.
    # Two parents that each cover 0.6 of the same polygon are possible exactly
    # when they overlap each other, which is what the real state does.
    overlapping = (0.6, 0.6)
    assert sum(overlapping) > 1.0
    assert len([f for f in overlapping if f > MAJORITY_BOUND]) == 2, (
        "two overlapping parents can both hold a majority, which is why the "
        "threshold reduces the refusal instead of preventing it"
    )
