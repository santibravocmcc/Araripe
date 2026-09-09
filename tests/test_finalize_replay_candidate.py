"""The two things the finalizer must get right, and the mutation each drops.

Everything else this script does is a call into a library that already has its
own tests — the ledger gate, the cutoff resolver, ``site_artifact``, the run
assembler.  What is *new* here is a write that could reach a production product
and a refusal that stops a plausible shortcut, so those are what is tested.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "finalize_replay_candidate.py"


def _load():
    spec = importlib.util.spec_from_file_location("finalize_replay_candidate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


finalize = _load()


def test_a_base_de_serie_temporal_nao_pode_sair_do_diretorio_isolado(tmp_path):
    """Derruba: um teste de prefixo de string, e a ausência da checagem.

    A única escrita deste script que poderia alcançar um produto de produção é
    a base de série temporal. O caminho perigoso não é um caminho absoluto
    óbvio — é `<out-dir>/../data/timeseries/timeseries.db`, que **começa com**
    o out-dir e sai dele. Um `str.startswith` aceitaria exatamente esse.
    """

    out = tmp_path / "isolated"
    out.mkdir()

    # the honest case
    assert finalize.require_inside(out / "timeseries_replay.db", out, label="db")

    # the traversal that a string-prefix check would accept
    escaping = out / ".." / "data" / "timeseries" / "timeseries.db"
    assert str(escaping).startswith(str(out)), (
        "the fixture must be a path that a prefix test would wrongly accept"
    )
    with pytest.raises(finalize.FinalizeError, match="not under the isolated"):
        finalize.require_inside(escaping, out, label="db")

    # and a plainly outside path
    with pytest.raises(finalize.FinalizeError):
        finalize.require_inside(Path("/tmp/elsewhere.db"), out, label="db")


def test_sem_ledger_o_script_recusa_em_vez_de_resolver_o_corte(tmp_path, capsys):
    """Derruba: resolver o corte de qualquer outra fonte.

    O corte toma as datas terminais **do ledger que o replay produziu**. O
    banco azul conhece só as datas que o azul processou, e uma data provisória
    é a da Phase 3. Se este script caísse para qualquer das duas quando o
    ledger falta, ele produziria um corte plausível para um replay que não
    terminou — e `ledger.json` só existe quando as 107 estão terminais.
    """

    out = tmp_path / "isolated"
    out.mkdir()
    # a half-finished replay: rows on disk, no ledger
    (out / "terminal_rows.json").write_text("[]", encoding="utf-8")

    code = finalize.main(["--out-dir", str(out), "--run", "rep-2026-test"])
    assert code == 1
    message = capsys.readouterr().err
    assert "ledger.json" in message
    assert "not finished" in message


def test_o_id_da_rodada_e_um_unico_segmento(tmp_path):
    """Derruba: aceitar um run id que endereça outro prefixo.

    O assembler valida isto, e o teste existe para fixar que o finalizador
    passa o valor por ele em vez de compor um caminho por conta própria.
    """

    from src.publication.run_inputs import RunRejected, validate_run_id

    assert validate_run_id("rep-2026-08-30") == "rep-2026-08-30"
    for bad in ("a/b", "..", "a b", "a\\b"):
        with pytest.raises(RunRejected):
            validate_run_id(bad)


def test_o_script_nao_nomeia_producao_no_codigo_executavel():
    """Derruba: um caminho de escrita em produção acrescentado aqui.

    Lê o texto executável e ignora docstring e comentário — a §7 dos insumos
    registra que uma varredura ingênua já se enganou nos dois sentidos, e o
    docstring deste próprio arquivo MENCIONA o banco azul para explicar por que
    não o toca.
    """

    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            text = ast.get_docstring(node, clean=False)
            if text is not None:
                docstrings.add(text)
    literals = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value not in docstrings
    ]
    haystack = "\n".join(literals).lower()
    for forbidden in (
        "araripe-cogs",
        "observatorio-chapada",
        "pointers/green/current.json",
        "data/timeseries/timeseries.db",
        "detect_gee.yml",
        "cloudflare",
    ):
        assert forbidden not in haystack, f"the finalizer names {forbidden!r}"

    # the docstring DOES name the blue database, on purpose; prove the scan
    # above would have caught it if it were executable, so the test is not
    # passing merely because the string is absent everywhere.
    assert any("data/timeseries/timeseries.db" in text for text in docstrings)


# ── end to end, on a synthetic replay directory ─────────────────────────────


def _synthetic_replay(tmp_path):
    """A complete, minimal replay out-dir: two datatakes on two dates.

    Built with the real libraries so every document is valid rather than
    plausible — the ledger comes from ``ProcessingLedgerV3.to_dict()``, which
    refuses to serialize until every expected acquisition is terminal.
    """

    import hashlib

    from src.detection.ledger_v3 import ProcessingLedgerV3
    from src.replay.enumeration import expected_acquisitions

    out = tmp_path / "isolated"
    (out / "alerts").mkdir(parents=True)

    manifest = {
        "run_manifest_version": "run-manifest-v3",
        "run_manifest_id": "run-v3-" + "c" * 64,
        "run_manifest_sha256": "d" * 64,
        "collection_id": "COPERNICUS/S2_SR_HARMONIZED",
        "monitoring_extent_id": "araripe-implementation-rectangle-v1",
        "composite_method_id": "datatake_mosaic-v1",
        "composition_unit": "datatake",
        "grid_id": "araripe-detection-export-epsg32724-20m-v1",
        "query": {"start": "2026-01-01", "end_exclusive": "2026-01-10"},
        "exported_dates": ["2026-01-02", "2026-01-05"],
        "datatakes": [
            {
                "platform": "S2C",
                "datatake_id": "GS2C_20260102T130251_006929_N05.11",
                "acquisition_timestamp_utc": "2026-01-02T13:02:51Z",
                "observed_on": "2026-01-02",
                "scene_ids": ["20260102T130251_20260102T130247_T24MUS"],
            },
            {
                "platform": "S2A",
                "datatake_id": "GS2A_20260105T131251_006972_N05.11",
                "acquisition_timestamp_utc": "2026-01-05T13:12:51Z",
                "observed_on": "2026-01-05",
                "scene_ids": ["20260105T131251_20260105T131247_T24MVS"],
            },
        ],
    }
    (out / "run_manifest_v3.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # one alerting date and one whose lineage was refused, which is exactly
    # the pair this session's replay produces
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[
                [-40.0, -7.0], [-40.0, -7.001], [-39.999, -7.001],
                [-39.999, -7.0], [-40.0, -7.0]]]},
            "properties": {
                # BOTH confidence fields, because two consumers read two
                # different ones and the real files carry both: site_artifact
                # reads the string `confidence_label`, and
                # alerts.summarize_alerts reads the integer `confidence`
                # (3/2/1). A fixture with only one of them made this test fail
                # with KeyError('confidence') — which is how the omission was
                # found, and it was the fixture that was wrong, not the code.
                "confidence": 3,
                "confidence_label": "high",
                "area_ha": 12.5,
                "persistence_count": 3,
                "lc_natural_frac_10m": 0.9,
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[
                [-40.1, -7.1], [-40.1, -7.101], [-40.099, -7.101],
                [-40.099, -7.1], [-40.1, -7.1]]]},
            "properties": {
                "confidence": 1,
                "confidence_label": "low",
                "area_ha": 3.25,
                "persistence_count": 1,
                "lc_natural_frac_10m": 0.1,
            },
        },
    ]
    (out / "alerts" / "alerts_2026-01-02.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8")

    state = {"type": "FeatureCollection", "features": []}
    (out / "persistence_state.geojson").write_text(
        json.dumps(state), encoding="utf-8")

    acquisitions = expected_acquisitions(manifest)
    ledger = ProcessingLedgerV3(
        run_manifest_id=manifest["run_manifest_id"],
        run_manifest_sha256=manifest["run_manifest_sha256"],
        acquisitions=acquisitions,
        monitoring_extent_id=manifest["monitoring_extent_id"],
        algorithm_version="1.0.0",
        created_at="2026-09-09T18:00:00Z",
    )
    from src.detection.identity_v3 import create_observation_v3
    from shapely.geometry import shape

    observation_ids = [
        create_observation_v3(
            acquisition=acquisitions[0],
            geometry=shape(item["geometry"]),
            algorithm_version="1.0.0",
            baseline_version="2.1.0",
            area_ha=float(item["properties"]["area_ha"]),
            created_at="2026-09-09T18:10:00Z",
        ).observation_id
        for item in features
    ]
    ledger.record_terminal(
        acquisition_id=acquisitions[0].acquisition_id,
        status="complete_with_alerts",
        observation_ids=observation_ids,
        terminal_at="2026-09-09T18:10:00Z",
        artifact_sha256=hashlib.sha256(b"composite").hexdigest(),
    )
    ledger.record_terminal(
        acquisition_id=acquisitions[1].acquisition_id,
        status="failed_processing",
        reason={"code": "persistence-ambiguous-lineage",
                "message": "update_tracks failed closed for reviewed correction"},
        terminal_at="2026-09-09T18:11:00Z",
    )
    (out / "ledger.json").write_text(
        json.dumps(ledger.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return out


def test_o_finalizador_roda_ponta_a_ponta_num_replay_sintetico(tmp_path, capsys):
    """Derruba: qualquer erro de execução no caminho que só roda uma vez.

    O finalizador roda **uma vez** sobre o replay do ano inteiro. Um
    `NameError` numa linha tardia, um campo com nome errado ou uma forma de
    documento equivocada só apareceria depois de horas de máquina — e este
    teste já pegou uma referência morta a uma variável renomeada.

    O replay sintético tem exatamente o par que a execução real produz: uma
    data com alertas e uma cuja linhagem foi recusada.
    """

    out = _synthetic_replay(tmp_path)
    code = finalize.main(["--out-dir", str(out), "--run", "rep-synthetic"])
    printed = capsys.readouterr().out
    assert code == 0, printed

    # the cutoff is the last FULLY TERMINAL date, resolved from this ledger
    record = json.loads((out / "execution_record.json").read_text(encoding="utf-8"))
    assert record["cutoff"]["date"] == "2026-01-05"
    assert record["cutoff"]["date_is_provisional"] is False
    assert record["cutoff"]["inclusive_on_the_batch_side"] is True
    # and the queue was built with exactly that cutoff, not another
    assert record["post_cutoff_queue"]["cutoff"]["date"] == record["cutoff"]["date"]
    assert record["post_cutoff_window_enumerated"] is False

    # bullet 8: one strong feature of the two, and the isolated database
    assert record["bullet_8"]["strong_feature_counts"]["2026-01-02"] == 1
    assert record["bullet_8"]["per_date_statistics"]["2026-01-02"]["count"] == 2
    assert record["bullet_8"]["timeseries_rows_written"] == 1
    assert (out / finalize.REPLAY_DB_NAME).exists()

    # the refused date classifies as unobserved and publishes nothing
    assert record["reconciliation"]["dates_by_alert_state"]["2026-01-05"] == (
        "no_valid_coverage")

    # the run prefix is materialised, and every declared object is on disk
    prefix = out / "run_prefix"
    for key in record["assembly"]["object_keys"]:
        relative = key.split("/", 2)[2]
        assert (prefix / relative).exists(), key
    assert record["assembly"]["run_prefix"] == "runs/rep-synthetic/"
    # one full and one strong object for the alerting date, plus the ledger
    assert any(p.endswith("run-2026-01-02.strong.geojson")
               for p in record["assembly"]["object_digests"])


def test_a_base_isolada_do_replay_nao_e_a_do_azul(tmp_path):
    """Derruba: escrever as linhas regeneradas no banco que o site serve.

    O banco azul é o produto no ar. Este teste prova que a base que o
    finalizador escreve fica dentro do out-dir e que o caminho azul continua
    intocado — não por leitura do código, mas porque o arquivo azul não é
    criado nem modificado por uma execução completa.
    """

    blue = tmp_path / "data" / "timeseries" / "timeseries.db"
    out = _synthetic_replay(tmp_path)
    assert finalize.main(["--out-dir", str(out), "--run", "rep-synthetic"]) == 0

    written = out / finalize.REPLAY_DB_NAME
    assert written.exists() and written.stat().st_size > 0
    assert not blue.exists(), "a replay must not create the blue product"
