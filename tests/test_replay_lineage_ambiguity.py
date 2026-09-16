"""A linhagem indeterminável vira evento novo — a regra que o dono escolheu.

O teste central não é que a regra funcione: é que ela **não muda o azul**. A
produção está congelada, o guarda do Package 2A.1 continua sendo contrato, e a
reformulação do guarda em conjunto só é aceitável se levantar exatamente nos
mesmos casos em que a formulação de dois ramos levantava. Isso é provado por
força bruta, não por leitura.
"""
from __future__ import annotations

import json
from collections import defaultdict
from itertools import product

import pytest

from src.detection.persistence import (
    AMBIGUOUS_LINEAGE_MODES,
    AMBIGUOUS_LINEAGE_ORIGIN,
    AMBIGUOUS_LINEAGE_RAISE,
    AmbiguousLineageError,
    update_tracks,
)
from src.replay.lineage_decision import (
    DECIDED_RESOLUTION,
    RULE_ID,
    LineageDecisionError,
    load_decision,
)


# ── the equivalence the blue path depends on ────────────────────────────────


def _two_branch_raises(links):
    """The ORIGINAL two-branch guard, transcribed, as the reference."""

    parents = defaultdict(set)
    children = defaultdict(set)
    for current, parent in links:
        parents[current].add(parent)
        children[parent].add(current)
    for current, ps in parents.items():
        if len(ps) > 1 and any(len(children[p]) > 1 for p in ps):
            return True
        if len(ps) == 1:
            parent = next(iter(ps))
            siblings = children[parent]
            if len(siblings) > 1 and any(
                len(parents[s]) > 1 for s in siblings
            ):
                return True
    return False


def _ambiguous_set(links):
    """The SET formulation the patched guard uses."""

    parents = defaultdict(set)
    children = defaultdict(set)
    for current, parent in links:
        parents[current].add(parent)
        children[parent].add(current)
    return {
        current for current, ps in parents.items()
        if len(ps) > 1 and any(len(children[p]) > 1 for p in ps)
    }


def test_a_reformulacao_do_guarda_levanta_nos_MESMOS_casos():
    """Derruba: uma reformulação que mudasse o comportamento do azul.

    O guarda passou de dois ramos para "o conjunto das detecções ambíguas".
    Se o segundo ramo pudesse disparar com esse conjunto vazio, o azul teria
    mudado de comportamento — e o azul está congelado. Força bruta sobre TODO
    grafo bipartido até 3 detecções por 3 eventos, em vez de argumentar.
    """

    checked = 0
    for n_current in (1, 2, 3):
        for n_parent in (1, 2, 3):
            edges = list(product(range(n_current), range(n_parent)))
            for mask in range(1 << len(edges)):
                links = [e for i, e in enumerate(edges) if mask >> i & 1]
                checked += 1
                assert _two_branch_raises(links) == bool(_ambiguous_set(links)), (
                    links, _two_branch_raises(links), _ambiguous_set(links)
                )
    assert checked == 682, checked


def test_derrubar_ligacoes_nunca_cria_uma_violacao_nova():
    """Derruba: assumir que o drop silencia o guarda sem reconferir.

    A regra remove ligações dos ambíguos. Como contagens de pais e de filhos só
    diminuem, nenhuma violação nova pode aparecer — mas isso é exatamente o
    tipo de "não pode acontecer" que já esteve errado nesta sessão, então é
    exercido sobre todos os grafos.
    """

    for n_current in (1, 2, 3):
        for n_parent in (1, 2, 3):
            edges = list(product(range(n_current), range(n_parent)))
            for mask in range(1 << len(edges)):
                links = [e for i, e in enumerate(edges) if mask >> i & 1]
                dropped = _ambiguous_set(links)
                remaining = [(c, p) for c, p in links if c not in dropped]
                assert not _ambiguous_set(remaining), (links, dropped, remaining)
                assert not _two_branch_raises(remaining), (links, remaining)


# ── the rule, against the real update_tracks ────────────────────────────────


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


def _tangle():
    """Two adjacent disjoint events and two detections straddling both.

    Measured: each detection sits 50% in each event, so at a 0.05 overlap
    threshold both events claim both detections — the 2x2 tangle that the
    measurement found is the commonest shape in the real data.
    """
    from shapely.geometry import box

    parents = [
        box(-40.000, -7.000, -39.990, -6.990),
        box(-39.990, -7.000, -39.980, -6.990),
    ]
    crossing = [
        box(-39.9945, -6.9970, -39.9855, -6.9950),
        box(-39.9945, -6.9930, -39.9855, -6.9910),
    ]
    return parents, crossing


def _run(parents, crossing, **kwargs):
    from config.settings import DETECTION_ALGORITHM_VERSION, MONITORING_EXTENT_ID

    common = dict(
        algorithm_version=DETECTION_ALGORITHM_VERSION,
        baseline_version="2.1.0",
        monitoring_extent_id=MONITORING_EXTENT_ID,
        mode="rebuild",
    )
    _, state = update_tracks(
        _frame(parents), None, "2026-01-01",
        acquisition=_acquisition("2026-01-01", "s1"), **common)
    return update_tracks(
        _frame(crossing), state, "2026-01-06",
        acquisition=_acquisition("2026-01-06", "s2"),
        min_overlap_frac=0.05, **common, **kwargs)


def test_o_default_do_azul_CONTINUA_levantando():
    """Derruba: carregar a regra do replay para dentro do caminho azul.

    A produção está congelada nas Fases 2B-5. O parâmetro é aditivo e o default
    é `raise`, então o pipeline agendado se comporta exatamente como antes.
    """

    parents, crossing = _tangle()
    with pytest.raises(AmbiguousLineageError):
        _run(parents, crossing)  # sem nomear o modo
    with pytest.raises(AmbiguousLineageError):
        _run(parents, crossing, ambiguous_lineage=AMBIGUOUS_LINEAGE_RAISE)


def test_a_regra_do_dono_registra_como_evento_NOVO_e_nao_levanta():
    """Derruba: resolver a ambiguidade atribuindo uma ancestralidade.

    As duas detecções ficam sem pai — `persistence_count` 1 — porque a
    linhagem não pôde ser determinada. Se a regra tivesse escolhido um pai, a
    contagem passaria de 1 e este teste cairia.
    """

    parents, crossing = _tangle()
    merged, state = _run(parents, crossing,
                         ambiguous_lineage=AMBIGUOUS_LINEAGE_ORIGIN)

    assert len(merged) == 2
    assert (merged["persistence_count"] == 1).all(), (
        "a detecção ambígua recebeu ancestralidade; a regra é registrá-la como "
        "evento novo"
    )
    transition = merged.attrs["persistence_transition"]
    assert transition["lineage_ambiguity_resolved_count"] == 2
    assert merged["lineage_ambiguity_resolved"].tolist() == [True, True]
    # os eventos antigos continuam no estado, não foram apagados
    assert len(state) >= 2


def test_a_coluna_so_aparece_quando_a_regra_dispara():
    """Derruba: acrescentar uma propriedade a todo alerta do azul.

    Os arquivos de alerta publicados têm um conjunto de propriedades que o site
    consome. A coluna de registro só existe quando a regra realmente disparou,
    senão esta mudança alteraria o esquema do produto azul.
    """

    from shapely.geometry import box

    parents = [box(-40.000, -7.000, -39.990, -6.990)]
    # uma detecção bem dentro do único evento: continuação limpa, sem tangle
    clean = [box(-39.9980, -6.9980, -39.9920, -6.9920)]
    merged, _ = _run(parents, clean, ambiguous_lineage=AMBIGUOUS_LINEAGE_ORIGIN)

    assert "lineage_ambiguity_resolved" not in merged.columns
    assert merged.attrs["persistence_transition"][
        "lineage_ambiguity_resolved_count"] == 0


def test_um_vizinho_NAO_ambiguo_no_mesmo_emaranhado_mantem_a_linhagem():
    """Derruba: descartar o componente inteiro em vez de só os ambíguos.

    Numa data real há ~2000 grupos e ~15 emaranhados. Dentro de um emaranhado,
    uma detecção com UM pai não é ambígua — ela claramente continua aquele
    evento — e jogar a linhagem dela fora perderia informação real sem ganho.
    """

    from shapely.geometry import box

    parents, crossing = _tangle()
    # acrescenta uma detecção inteiramente dentro do primeiro evento
    clean = box(-39.9985, -6.9985, -39.9955, -6.9955)
    merged, _ = _run(parents, crossing + [clean],
                     ambiguous_lineage=AMBIGUOUS_LINEAGE_ORIGIN)

    flags = merged["lineage_ambiguity_resolved"].tolist()
    assert flags[:2] == [True, True], flags
    assert flags[2] is False or flags[2] == False, flags  # noqa: E712
    assert int(merged["persistence_count"].iloc[2]) > 1, (
        "o vizinho não ambíguo perdeu a linhagem; só os ambíguos devem perder"
    )


def test_um_modo_desconhecido_falha_fechado():
    """Derruba: aceitar qualquer string e cair no default silenciosamente."""

    parents, crossing = _tangle()
    with pytest.raises(ValueError, match="ambiguous_lineage"):
        _run(parents, crossing, ambiguous_lineage="melhor_pai")
    assert set(AMBIGUOUS_LINEAGE_MODES) == {"raise", "origin"}


# ── the recorded decision ───────────────────────────────────────────────────


def _document(**overrides):
    body = {
        "decision_id": "araripe-phase4-lineage-ambiguity-decision-v1",
        "decision_date": "2026-09-16",
        "authorization": {
            "decided_by": "project_owner",
            "blue_default_change_permitted": False,
            "production_mutation_permitted": False,
        },
        "decided": {
            "resolution": "origin",
            "rule_id": "ambiguous-lineage-as-origin-v1",
            "rule_in_words": "an undeterminable lineage becomes a new event",
            "supersedes_for_the_replay": "raise",
        },
    }
    body.update(overrides)
    return body


def _write(tmp_path, document):
    path = tmp_path / "decision.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_a_decisao_real_do_dono_e_lida():
    decision = load_decision()
    assert decision.decided_by == "project_owner"
    assert decision.resolution == DECIDED_RESOLUTION == "origin"
    assert decision.rule_id == RULE_ID
    assert decision.supersedes == "raise"


def test_a_opcao_RETIRADA_nao_volta_por_edicao_de_documento(tmp_path):
    """Derruba: reabrir a opção (a) editando o JSON.

    `largest_overlap` é a tentadora — preserva mais continuidade — e é menos
    fiel que o merge que o `update_tracks` já faz ao lado. Ela foi recomendada
    por mim, retirada, e as três opções foram apresentadas ao dono, que
    escolheu a (c). Trocar a string do documento não é como isso se reabre.
    """

    for other in ("largest_overlap", "merge_component", "raise"):
        document = _document()
        document["decided"]["resolution"] = other
        with pytest.raises(LineageDecisionError):
            load_decision(_write(tmp_path, document))


def test_a_regra_e_do_dono_e_nao_do_agente(tmp_path):
    document = _document()
    document["authorization"]["decided_by"] = "executing_agent"
    with pytest.raises(LineageDecisionError, match="must be the owner"):
        load_decision(_write(tmp_path, document))


def test_a_decisao_nao_pode_se_autoconceder_producao(tmp_path):
    for field in ("blue_default_change_permitted", "production_mutation_permitted"):
        document = _document()
        document["authorization"][field] = True
        with pytest.raises(LineageDecisionError, match=field):
            load_decision(_write(tmp_path, document))


def test_o_driver_passa_a_regra_para_update_tracks():
    """Derruba: ler a decisão e deixar o default resolver.

    O bug plausível não é esquecer de ler — é ler, imprimir, e não passar.
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
        assert "ambiguous_lineage" in named, named
        source = next(kw.value for kw in call.keywords
                      if kw.arg == "ambiguous_lineage")
        assert isinstance(source, ast.Attribute), ast.dump(source)
        assert source.attr == "resolution", ast.dump(source)
