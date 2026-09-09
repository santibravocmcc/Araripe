"""A decisão da unidade de composição da Phase 4, e o que ela derruba.

Phase 4, item 2 do escopo. A Phase 3 **mediu** a divergência e deixou a
decisão aberta de propósito
(`docs/operations/PHASE_3_REPLAY_RUNBOOK.md` §8); esta sessão decidiu, e estes
testes são o que impede a decisão de virar prosa.

A pergunta que cada teste responde é sempre a mesma: **qual mutação ele
derruba**. Um teste que não derruba nenhuma passa pelo motivo errado, o que já
aconteceu três vezes nesta linha de trabalho.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import settings
from src.detection.identity_v3 import create_acquisition_v3
from src.processing.composition_v2 import (
    COMPOSITION_METHOD_ID as LIBRARY_DATATAKE_METHOD,
)
from src.replay import composition_unit as unit_mod
from src.replay.composition_unit import (
    AVAILABLE_NOT_CHOSEN_METHOD_ID,
    COMPOSITE_METHOD_ID,
    DECIDED_UNIT,
    GRID_DECISION,
    SUPERSEDED_METHOD_ID,
    CompositionUnitError,
    load_decision,
)

REPO = Path(settings.ROOT_DIR)
DECISION = REPO / "config" / "phase4_composition_unit_decision_v1.json"

#: A run-manifest binding shaped like the export writes one. The digest is
#: arbitrary but well-formed; the contract only requires id == prefix+digest.
_DIGEST = "b" * 64
_BINDING = {"run_manifest_id": "run-v3-" + _DIGEST, "run_manifest_sha256": _DIGEST}


def _mutated(tmp_path: Path, **edits) -> Path:
    """Write the real decision with one nested value replaced."""

    document = json.loads(DECISION.read_text(encoding="utf-8"))
    for dotted, value in edits.items():
        keys = dotted.split(".")
        node = document
        for key in keys[:-1]:
            node = node[key]
        if value is _DELETE:
            node.pop(keys[-1], None)
        else:
            node[keys[-1]] = value
    path = tmp_path / "decision.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


_DELETE = object()


def test_a_decisao_esta_registrada_e_carrega():
    decision = load_decision()
    assert decision.unit == DECIDED_UNIT == "physical_datatake"
    assert decision.composite_method_id == COMPOSITE_METHOD_ID == "datatake_mosaic-v1"
    assert decision.superseded_method_id == "daily_mosaic-v1"
    assert decision.grid_decision == GRID_DECISION == "do_not_pin_crs_transform"
    assert decision.decision_date == "2026-09-09"
    assert decision.decision_path == (
        "config/phase4_composition_unit_decision_v1.json"
    )


def test_o_digest_e_do_arquivo_de_verdade():
    """Derruba: um digest inventado, que foi exatamente o defeito da §10.5.

    O arquivo de decisão da baseline nasceu com um sha256 plausível e falso.
    Aqui o valor tem de bater com o do arquivo lido do disco.
    """

    import hashlib

    expected = hashlib.sha256(DECISION.read_bytes()).hexdigest()
    assert load_decision().decision_sha256 == expected


def test_a_decisao_ausente_falha_fechado_em_vez_de_assumir(tmp_path):
    """Derruba: um default silencioso.

    Se a decisão sumir, a unidade de contabilidade do ledger fica indefinida.
    Assumir `physical_datatake` aqui decidiria por omissão a pergunta mais
    consequente da fase.
    """

    with pytest.raises(CompositionUnitError, match="absent"):
        load_decision(tmp_path / "nao-existe.json")


def test_uma_unidade_por_data_e_recusada(tmp_path):
    """Derruba: voltar para a composição por data mantendo o resto.

    É a opção que o ledger não sabe representar: numa data com dois datatakes,
    um artefato teria de responder por duas aquisições esperadas.
    """

    path = _mutated(tmp_path, **{"composition_unit.decided": "utc_date"})
    with pytest.raises(CompositionUnitError, match="different replay"):
        load_decision(path)


def test_o_metodo_do_azul_e_recusado(tmp_path):
    """Derruba: cunhar identidade v3 sob `daily_mosaic-v1`.

    Seria a colisão que esta decisão existe para impedir — dois produtores
    diferentes cunhando sob o mesmo método.
    """

    path = _mutated(
        tmp_path, **{"composition_unit.composite_method_id": SUPERSEDED_METHOD_ID}
    )
    with pytest.raises(CompositionUnitError, match="collision this"):
        load_decision(path)


def test_o_metodo_da_baseline_e_recusado(tmp_path):
    """Derruba: reivindicar `coverage-ranked-first-valid-v1` para um mosaic.

    A biblioteca ordena por `valid_pixel_count` e toma todas as bandas da
    primeira cena válida; o `mosaic()` do Earth Engine toma a última imagem
    não mascarada da ordem da coleção. Os dois não estão provados iguais.
    """

    path = _mutated(
        tmp_path,
        **{"composition_unit.composite_method_id": AVAILABLE_NOT_CHOSEN_METHOD_ID},
    )
    with pytest.raises(CompositionUnitError, match="not proven equal"):
        load_decision(path)


def test_o_metodo_decidido_nao_e_o_da_biblioteca():
    """Derruba: alguém 'unificar' os dois IDs achando que são a mesma coisa.

    Se um dia forem provados iguais, este teste cai e obriga a prova a ser
    escrita antes da unificação.
    """

    assert COMPOSITE_METHOD_ID != LIBRARY_DATATAKE_METHOD
    assert AVAILABLE_NOT_CHOSEN_METHOD_ID == LIBRARY_DATATAKE_METHOD


def test_fixar_a_transform_e_recusado(tmp_path):
    """Derruba: pinar `crsTransform` — a mudança que mexeria em pixel.

    Medido: as duas grades já coincidem, então pinar não ganha nada e é a
    única das duas opções que muda o que é exportado.
    """

    path = _mutated(tmp_path, **{"export_grid.decided": "pin_crs_transform"})
    with pytest.raises(CompositionUnitError, match="change exported pixels"):
        load_decision(path)


@pytest.mark.parametrize(
    "flag",
    [
        "blue_default_change_permitted",
        "production_mutation_permitted",
        "quality_gate_change_permitted",
    ],
)
def test_a_decisao_nao_pode_conceder_permissao_de_producao(tmp_path, flag):
    """Derruba: um documento de decisão que se autoconcede escopo.

    `quality_gate_change_permitted` é o que importa aqui: reinterpretar o
    portão de cobertura contra a pegada do datatake aceitaria as fatias R138 e
    não perderia nada — e é decisão científica, da Phase 5.
    """

    path = _mutated(tmp_path, **{f"authorization.{flag}": True})
    with pytest.raises(CompositionUnitError, match=flag):
        load_decision(path)


def test_a_decisao_registra_quem_decidiu(tmp_path):
    """Derruba: uma decisão do agente que se apresenta como sendo do dono.

    A da baseline é do dono e científica; esta é técnica e delegada. Trocar a
    atribuição apagaria essa diferença.
    """

    path = _mutated(tmp_path, **{"authorization.decided_by": "project_owner"})
    with pytest.raises(CompositionUnitError, match="who decided"):
        load_decision(path)


def test_a_decisao_carrega_a_medicao_e_nao_so_a_conclusao(tmp_path):
    """Derruba: apagar os números e deixar só a escolha.

    Uma decisão sem a contagem medida é uma opinião, e a próxima sessão não
    tem como conferir se o mundo mudou.
    """

    path = _mutated(
        tmp_path, **{"consequence_of_the_decision.acquisitions_expected": _DELETE}
    )
    with pytest.raises(CompositionUnitError, match="acquisitions_expected"):
        load_decision(path)


def test_menos_aquisicoes_do_que_datas_e_incoerente(tmp_path):
    """Derruba: números medidos trocados de lugar.

    Uma data tem pelo menos uma aquisição, então 90 aquisições em 107 datas é
    aritmeticamente impossível e denuncia a troca.
    """

    path = _mutated(
        tmp_path, **{"consequence_of_the_decision.acquisitions_expected": 3}
    )
    with pytest.raises(CompositionUnitError, match="fewer acquisitions"):
        load_decision(path)


def test_a_escolha_do_metodo_muda_de_verdade_a_identidade():
    """Derruba: a suposição de que a unidade é só um rótulo.

    Se `acquisition_id` não dependesse de `composite_method_id`, a decisão
    seria cosmética. Ela não é: o mesmo datatake cunha IDs diferentes sob os
    dois métodos, que é exatamente por que o export se recusa a pré-computar
    o ID.
    """

    common = dict(
        collection_id="COPERNICUS/S2_SR_HARMONIZED",
        platform="S2A",
        datatake_id="GS2A_20260825T131251_058365_N05.12",
        acquisition_timestamp_utc="2026-08-25T13:12:51Z",
        scene_ids=("COPERNICUS/S2_SR_HARMONIZED/20260825T131251_x_T24MTS",),
        monitoring_extent_id="araripe-implementation-rectangle-v1",
        grid_id="araripe-detection-export-epsg32724-20m-v1",
        **_BINDING,
    )
    decided = create_acquisition_v3(composite_method_id=COMPOSITE_METHOD_ID, **common)
    blue = create_acquisition_v3(composite_method_id=SUPERSEDED_METHOD_ID, **common)
    library = create_acquisition_v3(
        composite_method_id=AVAILABLE_NOT_CHOSEN_METHOD_ID, **common
    )
    assert len({decided.acquisition_id, blue.acquisition_id, library.acquisition_id}) == 3


def test_o_metodo_decidido_e_aceito_pelo_contrato_v3():
    """Derruba: um ID de método que o contrato recusaria só na hora do replay.

    `datatake_mosaic-v1` tem de passar `require_versioned_method`, senão a
    decisão só falharia depois de horas de compute.
    """

    acquisition = create_acquisition_v3(
        collection_id="COPERNICUS/S2_SR_HARMONIZED",
        platform="S2C",
        datatake_id="GS2C_20260830T130241_010361_N05.12",
        acquisition_timestamp_utc="2026-08-30T13:02:41Z",
        scene_ids=("COPERNICUS/S2_SR_HARMONIZED/20260830T130241_x_T24MTS",),
        monitoring_extent_id="araripe-implementation-rectangle-v1",
        composite_method_id=load_decision().composite_method_id,
        grid_id="araripe-detection-export-epsg32724-20m-v1",
        **_BINDING,
    )
    assert acquisition.acquisition_id.startswith("acq-v3-")
    assert acquisition.observed_on == "2026-08-30"


def test_o_caminho_padrao_aponta_para_o_documento_versionado():
    """Derruba: apontar o loader para um arquivo fora do controle de versão."""

    assert unit_mod.DECISION_PATH == DECISION
    assert DECISION.exists()
