"""O conjunto esperado da Phase 4, o filtro de cobertura, e o que eles derrubam.

Determinístico: sem Earth Engine, sem rede, sem relógio, sem credencial.

O filtro de cobertura é a peça que merece a maior desconfiança, porque ele
**pula download**. A condição de correção dele está escrita e é testada aqui:
*nada que o filtro rejeita poderia ter sido aceito pelo portão de verdade.*
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.detection.ledger_v3 import ProcessingLedgerV3, TERMINAL_STATUSES
from src.replay.enumeration import (
    GATE_ANOMALY_REASON_CODE,
    GATE_COVERAGE_REASON_CODE,
    SCREEN_REASON_CODE,
    SCREEN_SAFETY_DIVISOR,
    EnumerationError,
    expected_acquisitions,
    gate_rejection,
    reconciles,
    screen_by_coverage,
    screen_rejection,
    screen_summary,
)

_DIGEST = "c" * 64


def manifest(*datatakes, unit="datatake", method="datatake_mosaic-v1"):
    return {
        "run_manifest_id": "run-v3-" + _DIGEST,
        "run_manifest_sha256": _DIGEST,
        "collection_id": "COPERNICUS/S2_SR_HARMONIZED",
        "monitoring_extent_id": "araripe-implementation-rectangle-v1",
        "composite_method_id": method,
        "composition_unit": unit,
        "grid_id": "araripe-detection-export-epsg32724-20m-v1",
        "datatakes": list(datatakes),
    }


def datatake(platform, datatake_id, timestamp, *scenes):
    return {
        "platform": platform,
        "datatake_id": datatake_id,
        "acquisition_timestamp_utc": timestamp,
        "observed_on": timestamp[:10],
        "scene_ids": ["COPERNICUS/S2_SR_HARMONIZED/" + s for s in scenes],
    }


#: The real shape of a dual date, taken from the 2026-08-25 measurement:
#: S2A on R138 at 13:12:51 covering 5.5% of the extent, S2B on R095 at
#: 13:02:39 covering 98.4%.
R138 = datatake("S2A", "GS2A_20260825T131251_058365_N05.12",
                "2026-08-25T13:12:51Z", "a_T24MTS", "a_T24MTT")
R095 = datatake("S2B", "GS2B_20260825T130239_049456_N05.12",
                "2026-08-25T13:02:39Z", "b_T24MTS", "b_T24MUT")
DUAL = manifest(R138, R095)
COVERAGE = {R138["datatake_id"]: 0.055, R095["datatake_id"]: 0.984}


def test_uma_data_com_dois_datatakes_da_duas_aquisicoes_esperadas():
    """A cláusula do gate P4: uma linha terminal por aquisição ESPERADA."""

    acquisitions = expected_acquisitions(DUAL)
    assert len(acquisitions) == 2
    assert {a.observed_on for a in acquisitions} == {"2026-08-25"}
    assert len({a.acquisition_id for a in acquisitions}) == 2
    assert all(a.acquisition_id.startswith("acq-v3-") for a in acquisitions)


def test_um_manifest_por_data_e_recusado():
    """Derruba: enumerar a partir do manifest que o azul escreve.

    Um manifest de unidade `date` promete um composto por data, e aí duas
    aquisições esperadas dividiriam um artefato — o que o ledger não sabe
    dizer.
    """

    with pytest.raises(EnumerationError, match="cannot account for"):
        expected_acquisitions(manifest(R138, R095, unit="date",
                                       method="daily_mosaic-v1"))


@pytest.mark.parametrize(
    "field",
    ["run_manifest_id", "composite_method_id", "composition_unit", "grid_id",
     "datatakes"],
)
def test_um_manifest_incompleto_falha_fechado(field):
    document = dict(DUAL)
    document.pop(field)
    with pytest.raises(EnumerationError, match=field):
        expected_acquisitions(document)


def test_o_mesmo_datatake_duas_vezes_e_recusado():
    """Derruba: uma aquisição contada duas vezes, que faria o gate 'fechar'
    com uma linha a mais e nenhuma reclamação."""

    with pytest.raises(EnumerationError, match="duplicate acquisition"):
        expected_acquisitions(manifest(R095, dict(R095)))


def test_a_identidade_depende_do_metodo_declarado_no_manifest():
    """Derruba: ignorar o `composite_method_id` do manifest e usar um fixo."""

    a = expected_acquisitions(DUAL)
    b = expected_acquisitions(manifest(R138, R095, method="daily-mosaic-v9"))
    assert {x.acquisition_id for x in a}.isdisjoint({x.acquisition_id for x in b})


# ── o filtro de cobertura ────────────────────────────────────────────────────


def test_o_filtro_rejeita_a_fatia_e_puxa_a_passagem_cheia():
    screened = screen_by_coverage(
        expected_acquisitions(DUAL), extent_coverage=COVERAGE,
        minimum_fraction=0.20,
    )
    by_id = {s.acquisition.datatake_id: s for s in screened}
    assert by_id[R138["datatake_id"]].pull is False
    assert by_id[R095["datatake_id"]].pull is True
    assert "5.50%" in by_id[R138["datatake_id"]].screen_reason


def test_a_condicao_de_correcao_do_filtro_vale_na_faixa_toda():
    """**A condição de correção**: nada que o filtro rejeita poderia ter sido
    aceito pelo portão.

    Varre a faixa inteira de 0 a 100% e exige que todo rejeitado esteja
    estritamente abaixo do mínimo do portão. Derruba: alargar o filtro até
    encostar no portão, que é a mudança que transformaria uma otimização numa
    perda de dado.
    """

    acquisitions = expected_acquisitions(DUAL)
    minimum = 0.20
    for percent in range(0, 101):
        fraction = percent / 100.0
        coverage = {d["datatake_id"]: fraction for d in (R138, R095)}
        for item in screen_by_coverage(
            acquisitions, extent_coverage=coverage, minimum_fraction=minimum
        ):
            if not item.pull:
                assert item.extent_coverage_fraction < minimum, (
                    f"the screen rejected {percent}% coverage, which the "
                    f"{minimum:.0%} gate could have accepted"
                )
                assert item.extent_coverage_fraction < minimum / SCREEN_SAFETY_DIVISOR


def test_o_filtro_falha_aberto_dentro_da_margem():
    """Derruba: rejeitar dentro da margem.

    Entre 10% e 20% o filtro não decide — puxa e deixa o portão de verdade
    decidir. Desperdiçar um download é a direção certa de errar.
    """

    acquisitions = expected_acquisitions(DUAL)
    coverage = {d["datatake_id"]: 0.15 for d in (R138, R095)}
    screened = screen_by_coverage(
        acquisitions, extent_coverage=coverage, minimum_fraction=0.20
    )
    assert all(item.pull for item in screened)


def test_uma_aquisicao_sem_medicao_nao_e_uma_rejeitada():
    """Derruba: tratar 'não medido' como 'zero'.

    Um `.get(key, 0.0)` aqui rejeitaria em silêncio toda aquisição cuja
    medição falhou, e o gate fecharia com linhas terminais falsas.
    """

    with pytest.raises(EnumerationError, match="unmeasured acquisition"):
        screen_by_coverage(
            expected_acquisitions(DUAL),
            extent_coverage={R095["datatake_id"]: 0.98},
            minimum_fraction=0.20,
        )


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0])
def test_uma_cobertura_fora_de_0_1_falha_fechado(bad):
    with pytest.raises(EnumerationError, match="not a fraction"):
        screen_by_coverage(
            expected_acquisitions(DUAL),
            extent_coverage={R138["datatake_id"]: bad,
                             R095["datatake_id"]: 0.98},
            minimum_fraction=0.20,
        )


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.5, 1.5])
def test_um_minimo_fora_de_0_1_falha_fechado(bad):
    with pytest.raises(EnumerationError, match="strictly between"):
        screen_by_coverage(
            expected_acquisitions(DUAL), extent_coverage=COVERAGE,
            minimum_fraction=bad,
        )


def test_pedir_a_razao_de_um_nao_rejeitado_e_recusado():
    """Derruba: inventar uma razão de rejeição para uma linha aceita."""

    screened = screen_by_coverage(
        expected_acquisitions(DUAL), extent_coverage=COVERAGE,
        minimum_fraction=0.20,
    )
    pulled = next(item for item in screened if item.pull)
    with pytest.raises(EnumerationError, match="invent one"):
        screen_rejection(pulled)


def test_a_razao_do_filtro_e_aceita_pelo_ledger():
    """Derruba: uma razão que só falharia na hora de gravar a linha.

    O contrato exige `code` em minúsculas com caracteres de token; um código
    com maiúscula ou espaço só quebraria depois do compute.
    """

    screened = screen_by_coverage(
        expected_acquisitions(DUAL), extent_coverage=COVERAGE,
        minimum_fraction=0.20,
    )
    rejected = next(item for item in screened if not item.pull)
    ledger = ProcessingLedgerV3(
        run_manifest_id=DUAL["run_manifest_id"],
        run_manifest_sha256=DUAL["run_manifest_sha256"],
        acquisitions=expected_acquisitions(DUAL),
        monitoring_extent_id=DUAL["monitoring_extent_id"],
        algorithm_version="1.0.0",
        created_at="2026-09-09T00:00:00Z",
    )
    result = ledger.record_terminal(
        acquisition_id=rejected.acquisition_id,
        status="rejected_low_coverage",
        reason=screen_rejection(rejected),
        terminal_at="2026-09-09T00:00:00Z",
    )
    assert result.row["reason"]["code"] == SCREEN_REASON_CODE
    assert result.row["status"] in TERMINAL_STATUSES


def test_o_resumo_do_filtro_conta_o_que_ele_decidiu():
    summary = screen_summary(
        screen_by_coverage(
            expected_acquisitions(DUAL), extent_coverage=COVERAGE,
            minimum_fraction=0.20,
        )
    )
    assert summary["expected_acquisitions"] == 2
    assert summary["to_pull"] == 1
    assert summary["rejected_on_measured_coverage"] == 1
    assert summary["highest_rejected_coverage"] == pytest.approx(0.055)
    assert summary["lowest_pulled_coverage"] == pytest.approx(0.984)
    assert summary["dates_expected"] == 1
    assert summary["dates_with_at_least_one_pull"] == 1


# ── a tradução do portão de verdade ──────────────────────────────────────────


@dataclass
class FakeQuality:
    scene_decision: str
    rejection_reason: str
    valid_coverage_fraction: float
    minimum_required_fraction: float
    alert_fraction_of_valid: float


def test_a_rejeicao_por_cobertura_vira_rejected_low_coverage():
    status, reason = gate_rejection(
        FakeQuality("rejected", "insufficient_coverage", 0.11, 0.20, 0.01)
    )
    assert status == "rejected_low_coverage"
    assert reason["code"] == GATE_COVERAGE_REASON_CODE
    assert "11.00%" in reason["message"]


def test_a_rejeicao_por_anomalia_vira_rejected_quality():
    """Derruba: mandar toda rejeição para `rejected_low_coverage`.

    Uma cena com cobertura de sobra e fração de alerta absurda é um problema
    diferente, e o ledger tem um status para cada um.
    """

    status, reason = gate_rejection(
        FakeQuality("rejected", "anomalous_alert_fraction", 0.95, 0.20, 0.61)
    )
    assert status == "rejected_quality"
    assert reason["code"] == GATE_ANOMALY_REASON_CODE
    assert "61.00%" in reason["message"]


def test_os_dois_codigos_de_cobertura_sao_distintos():
    """Derruba: reusar o código do filtro no portão.

    Se fossem o mesmo, o ledger não diria se a linha veio de uma medição
    grosseira do servidor ou da avaliação completa.
    """

    assert SCREEN_REASON_CODE != GATE_COVERAGE_REASON_CODE


def test_traduzir_a_rejeicao_de_uma_cena_aceita_e_recusado():
    with pytest.raises(EnumerationError, match="no rejection to translate"):
        gate_rejection(FakeQuality("accepted", "", 0.95, 0.20, 0.01))


# ── a cláusula do gate ───────────────────────────────────────────────────────


def test_a_reconciliacao_so_fecha_com_o_conjunto_inteiro():
    acquisitions = expected_acquisitions(DUAL)
    rows = {
        acquisitions[0].acquisition_id: {"status": "complete_zero_alerts"},
    }
    partial = reconciles(expected=acquisitions, rows=rows)
    assert partial["complete"] is False
    assert partial["missing"] == [acquisitions[1].acquisition_id]

    rows[acquisitions[1].acquisition_id] = {"status": "rejected_low_coverage"}
    assert reconciles(expected=acquisitions, rows=rows)["complete"] is True


def test_uma_linha_inesperada_impede_o_fechamento():
    """Derruba: contar linhas em vez de casar conjuntos.

    Com uma linha a mais e uma a menos a contagem bate e o conjunto não.
    """

    acquisitions = expected_acquisitions(DUAL)
    rows = {
        acquisitions[0].acquisition_id: {"status": "complete_zero_alerts"},
        "acq-v3-" + "d" * 64: {"status": "complete_zero_alerts"},
    }
    finding = reconciles(expected=acquisitions, rows=rows)
    assert len(rows) == len(acquisitions)
    assert finding["complete"] is False
    assert finding["unexpected"] == ["acq-v3-" + "d" * 64]
    assert finding["missing"] == [acquisitions[1].acquisition_id]


def test_um_status_nao_terminal_impede_o_fechamento():
    """Derruba: aceitar qualquer string como status.

    'no artifact status is unresolved' é uma cláusula do gate, então um
    'pending' tem de ser visível.
    """

    acquisitions = expected_acquisitions(DUAL)
    rows = {
        acquisitions[0].acquisition_id: {"status": "complete_zero_alerts"},
        acquisitions[1].acquisition_id: {"status": "pending"},
    }
    finding = reconciles(expected=acquisitions, rows=rows)
    assert finding["complete"] is False
    assert finding["non_terminal_status"] == [acquisitions[1].acquisition_id]
