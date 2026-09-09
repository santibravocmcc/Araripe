"""What each replay month was composed against, and why the record is load-bearing.

The owner accepted, when he chose baseline ``2.1.0``, that calendar months 1-4
ride on products ESA is still reprocessing.  This record is the counterpart of
that acceptance: it is what turns "redo four months" into four months instead
of twelve.  So these tests are not about formatting — each one names the
mutation it drops, and the mutation was applied and observed to fail before the
test was kept.
"""
from __future__ import annotations

import copy
import json

import pytest

from src.detection.baseline_selection import resolve_baseline
from src.replay.seasonal_regime import (
    PENDING_PROVENANCE_STATE,
    SeasonalRegimeError,
    composition_regime_record,
    regimes_for_months,
    rework_scope,
)

#: The window the Phase 4 replay enumerates: 2026-01-01 .. 2026-08-31 exclusive.
WINDOW_MONTHS = range(1, 9)


@pytest.fixture(scope="module")
def manifest():
    """The real 2.1.0 manifest — the generation the replay actually used."""

    return resolve_baseline("2.1.0").load_manifest()


def _record(manifest, **overrides):
    kwargs = {
        "months": WINDOW_MONTHS,
        "baseline_version": "2.1.0",
        "window_start": "2026-01-01",
        "window_end_exclusive": "2026-08-31",
    }
    kwargs.update(overrides)
    return composition_regime_record(manifest, **kwargs)


def test_os_quatro_meses_da_estacao_chuvosa_estao_marcados_como_pendentes(manifest):
    """Derruba: `rebuild_pending` fixado em False, ou a marca simplesmente ausente.

    Se a marca fosse constante — em qualquer dos dois sentidos — o registro
    deixaria de distinguir os meses que a retirada do regime obriga a refazer
    dos que ela não toca, que é a única coisa que ele existe para dizer.
    """

    resolved = regimes_for_months(manifest, WINDOW_MONTHS)
    pending = {item.month for item in resolved if item.rebuild_pending}
    stable = {item.month for item in resolved if not item.rebuild_pending}

    assert pending == {1, 2, 3, 4}, pending
    assert stable == {5, 6, 7, 8}, stable
    for item in resolved:
        if item.month in (1, 2, 3, 4):
            assert item.regime_id == "wet-season-mixed-lineage-v1"
            assert item.provenance_state == PENDING_PROVENANCE_STATE
        else:
            assert item.provenance_state == "collection1_lineage_stable"


def test_o_alcance_do_retrabalho_e_de_quatro_meses_e_nao_do_ano(manifest):
    """Derruba: um alcance que devolvesse a janela inteira para cada regime.

    É a aritmética inteira do documento: retirar
    `wet-season-mixed-lineage-v1` refaz 4 meses. Um agrupamento que
    devolvesse 8 para o regime pendente tornaria o registro inútil sem
    parecer quebrado.
    """

    scope = rework_scope(regimes_for_months(manifest, WINDOW_MONTHS))

    assert scope == {
        "dry-season-collection1-v1": [6, 7, 8],
        "shoulder-season-collection1-v1": [5],
        "wet-season-mixed-lineage-v1": [1, 2, 3, 4],
    }, scope
    assert len(scope["wet-season-mixed-lineage-v1"]) == 4
    # and the three scopes partition the window without overlap
    flat = [month for months in scope.values() for month in months]
    assert sorted(flat) == list(WINDOW_MONTHS)
    assert len(flat) == len(set(flat))


def test_o_campo_por_mes_e_conferido_contra_a_particao_declarada(manifest):
    """Derruba DUAS mutações opostas, e é o teste central do módulo.

    (a) confiar no `source_regime` de cada mês sem conferir; e
    (b) ler a partição declarada e ignorar o campo por mês.

    O manifesto diz a mesma coisa em dois lugares — `source_regimes`, que
    particiona o calendário, e `rebuild_execution.months[*].source_regime`,
    que diz sob qual regime cada mês foi construído. O contrato promete a
    partição; **não** promete que os dois concordem. Se o módulo confiasse em
    um só, esta divergência passaria em silêncio, e o manifesto estaria
    descrevendo duas construções diferentes.
    """

    broken = copy.deepcopy(manifest)
    for entry in broken["rebuild_execution"]["months"]:
        if entry["month"] == 3:
            entry["source_regime"] = "dry-season-collection1-v1"
            break
    else:  # pragma: no cover - the manifest builds month 3
        pytest.fail("the manifest does not build month 3")

    with pytest.raises(SeasonalRegimeError, match="month 03"):
        regimes_for_months(broken, WINDOW_MONTHS)


def test_um_mes_que_o_manifesto_nao_constroi_falha_fechado(manifest):
    """Derruba: um default silencioso para um mês ausente.

    Um mês sem entrada é o manifesto não sabendo responder. Devolver um
    regime plausível ali seria inventar a procedência de pixels reais.
    """

    broken = copy.deepcopy(manifest)
    broken["rebuild_execution"]["months"] = [
        entry for entry in broken["rebuild_execution"]["months"]
        if entry["month"] != 4
    ]

    with pytest.raises(SeasonalRegimeError, match="does not record calendar month 04"):
        regimes_for_months(broken, WINDOW_MONTHS)


def test_um_regime_sem_estado_de_procedencia_falha_fechado(manifest):
    """Derruba: tratar procedência ausente como estável.

    Essa é a direção perigosa do erro: um default "estável" declararia que
    janeiro-abril não precisam ser refeitos, que é exatamente a afirmação
    falsa que o custo aceito pelo dono depende de não fazer.
    """

    broken = copy.deepcopy(manifest)
    for regime in broken["source_regimes"]:
        if regime["regime_id"] == "wet-season-mixed-lineage-v1":
            del regime["provenance_state"]
            break
    else:  # pragma: no cover
        pytest.fail("the wet-season regime is not declared")

    with pytest.raises(SeasonalRegimeError, match="no provenance_state"):
        regimes_for_months(broken, WINDOW_MONTHS)


def test_o_registro_recusa_nomear_uma_geracao_que_nao_foi_usada(manifest):
    """Derruba: aceitar qualquer `baseline_version` no registro.

    O documento afirma contra o que o ano foi composto. Se ele aceitasse
    `1.0.0` enquanto os rasters vieram da `2.1.0`, a afirmação seria falsa e
    plausível ao mesmo tempo — e `1.0.0` é justamente o default do azul, o
    valor que um erro de digitação produz.
    """

    with pytest.raises(SeasonalRegimeError, match="1.0.0"):
        _record(manifest, baseline_version="1.0.0")


def test_o_documento_nao_carrega_float(manifest):
    """Derruba: gravar uma fração no registro.

    `json.dumps` e a forma RFC 8785 discordam num float de valor integral
    (`1.0` contra `1`) e no expoente (`1e-07` contra `1e-7`), então um float
    aqui quebraria a assinatura de um documento selado mais tarde, longe
    daqui.
    """

    def floats(value, path="$"):
        if isinstance(value, bool):
            return []
        if isinstance(value, float):
            return [path]
        if isinstance(value, dict):
            return [p for k, v in value.items() for p in floats(v, f"{path}.{k}")]
        if isinstance(value, list):
            return [p for i, v in enumerate(value) for p in floats(v, f"{path}[{i}]")]
        return []

    document = _record(manifest)
    assert floats(document) == []
    # and it round-trips, which is what a later signing step would do
    assert json.loads(json.dumps(document, sort_keys=True)) == document


def test_o_registro_e_o_mesmo_documento_em_qualquer_lote(manifest):
    """Derruba: um registro que dependesse do lote em execução.

    Cada lote escreve este arquivo. Se ele variasse com o lote, o último a
    rodar apagaria a verdade dos outros — e o arquivo passaria a descrever
    julho em vez do ano.
    """

    first = _record(manifest)
    second = _record(manifest)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["window"]["calendar_months"] == list(WINDOW_MONTHS)


def test_o_registro_aponta_para_a_vigilancia_que_retira_o_regime(manifest):
    """Derruba: descrever a condição de retirada em prosa e não por caminho.

    A retirada é acionada por uma medição, não por lembrança. O documento
    nomeia o script e a consulta que a medem.
    """

    pending = _record(manifest)["pending_on_esa_reprocessing"]
    assert pending["months"] == [1, 2, 3, 4]
    assert pending["regimes"] == ["wet-season-mixed-lineage-v1"]
    assert pending["watched_by"] == "scripts/check_esa_reprocessing.py"
    assert pending["watch_query_config"] == (
        "config/esa_reprocessing_watch_query_v1.json"
    )


# ── the fail-closed persistence refusal, and how the replay records it ───────


def test_uma_linhagem_ambigua_nunca_vira_um_status_de_sucesso():
    """Derruba: registrar a data como completa, ou como rejeitada de cena.

    A camada de persistência RECUSOU amarrar a linhagem de eventos daquela
    data. Registrá-la como `complete_*` afirmaria observações que ninguém
    amarrou; registrá-la como `rejected_quality` culparia o portão de cena,
    que aceitou a aquisição. `failed_processing` é o único status honesto, e o
    bullet 4 do roadmap o nomeia.
    """

    from src.detection.persistence import AmbiguousLineageError
    from src.replay.enumeration import lineage_failure

    status, reason = lineage_failure(
        AmbiguousLineageError("many-to-many split/merge component requires "
                              "reviewed correction")
    )
    assert status == "failed_processing"
    assert status not in ("complete_with_alerts", "complete_zero_alerts")
    assert status != "rejected_quality"
    assert set(reason) == {"code", "message"}
    assert reason["code"] == "persistence-ambiguous-lineage"
    assert "reviewed correction" in reason["message"]


def test_a_linha_que_o_replay_grava_e_aceita_pelo_ledger_de_verdade():
    """Derruba: um `reason` que o ledger recusaria em tempo de execução.

    Este é o teste que vale. O portão de saída exige UMA linha terminal por
    aquisição esperada; se `record_terminal` recusasse este `reason` — código
    com caractere inválido, campo a mais, mensagem vazia — o lote morreria no
    tratamento do erro em vez de na causa dele, e a data ficaria sem linha
    nenhuma. Então a linha é gravada num ledger real e o documento é exigido.
    """

    from src.detection.ledger_v3 import ProcessingLedgerV3
    from src.detection.persistence import AmbiguousLineageError
    from src.replay.enumeration import expected_acquisitions, lineage_failure

    manifest = {
        "run_manifest_id": "run-v3-" + "a" * 64,
        "run_manifest_sha256": "b" * 64,
        "collection_id": "COPERNICUS/S2_SR_HARMONIZED",
        "monitoring_extent_id": "araripe-implementation-rectangle-v1",
        "composite_method_id": "datatake_mosaic-v1",
        "composition_unit": "datatake",
        "grid_id": "araripe-detection-export-epsg32724-20m-v1",
        "datatakes": [{
            "platform": "S2B",
            "datatake_id": "GS2B_20260427T130239_047740_N05.12",
            "acquisition_timestamp_utc": "2026-04-27T13:02:39Z",
            "scene_ids": ["20260427T130239_20260427T130235_T24MUS"],
        }],
    }
    acquisitions = expected_acquisitions(manifest)
    ledger = ProcessingLedgerV3(
        run_manifest_id=manifest["run_manifest_id"],
        run_manifest_sha256=manifest["run_manifest_sha256"],
        acquisitions=acquisitions,
        monitoring_extent_id=manifest["monitoring_extent_id"],
        algorithm_version="1.0.0",
        created_at="2026-09-09T18:00:00Z",
    )
    status, reason = lineage_failure(AmbiguousLineageError("many-to-many"))
    ledger.record_terminal(
        acquisition_id=acquisitions[0].acquisition_id,
        status=status, reason=reason,
        terminal_at="2026-09-09T18:30:00Z",
    )
    # the whole set is terminal, so the document must serialize
    document = ledger.to_dict()
    rows = document["terminal_rows"]
    assert len(rows) == 1
    assert rows[0]["status"] == "failed_processing"
    assert rows[0]["reason"]["code"] == "persistence-ambiguous-lineage"
    assert rows[0]["output"]["observation_ids"] == []


def test_o_driver_captura_a_recusa_em_vez_de_apenas_importa_la():
    """Derruba: importar a exceção e não a tratar.

    Antes desta sessão o driver não a capturava, e um lote inteiro de trabalho
    já pago morria no meio. Uma varredura de string veria o nome no import e
    diria que está tratado, então isto lê a árvore e exige um `except` que a
    nomeia — e exige o `continue`, porque tratar sem seguir para a data
    seguinte pararia o replay do mesmo jeito.
    """

    import ast
    from pathlib import Path

    driver = Path(__file__).resolve().parents[1] / "scripts" / "replay_2026.py"
    tree = ast.parse(driver.read_text(encoding="utf-8"))

    handlers = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and node.type is not None
        and "AmbiguousLineageError" in ast.dump(node.type)
    ]
    assert handlers, "the driver imports the refusal but never catches it"
    body = ast.dump(ast.Module(body=handlers[0].body, type_ignores=[]))
    assert "record_terminal" in body, "the handler records nothing"
    assert "lineage_failure" in body, "the handler invents its own status"
    assert "Continue" in body, "the handler stops the batch instead of the date"
