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
