"""A geração verde anotada com o MapBiomas 2025 (PHASE_6W, 2026-10-07).

O dono decidiu abandonar os recortes de 2023 antes da virada. Estes testes
prendem as quatro coisas que essa troca exige e que nenhum outro teste vê:

* o replay detecta sob a SUA versão (`1.1.0`) e anota com os recortes 2025,
  verificados por sha256 — e o azul continua onde a produção o deixou;
* o freeze v2 fotografa os recortes por sha256 e não nomeia 2023;
* uma rodada desta geração recusa continuar o estado de outra, antes de baixar
  um byte — `update_tracks` carimba a versão que recebe e não compara;
* um raster ausente ou trocado para o replay, em vez de anotar em silêncio.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from config import settings
from src.publication import conditional_store as cs
from src.publication import state_chain as sc
from src.publication.green_release import sha256_bytes
from src.publication.run_inputs import ReadOnlyStore
from src.replay import freeze as fz
from src.replay import generation as gen
from tests.fake_object_store import FakeS3
from tests.green_release_fixtures import ZERO, build_ledger

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── a geração e o azul ───────────────────────────────────────────────────────


def test_a_geracao_verde_e_1_1_0_e_o_azul_nao_se_move():
    """O azul lê `DETECTION_ALGORITHM_VERSION` e `LANDCOVER_RASTERS`, e a
    produção está congelada até a Phase 5: a troca é do replay, não dele."""

    assert gen.GREEN_ALGORITHM_VERSION == "1.1.0"
    assert gen.GREEN_ALGORITHM_VERSION not in gen.PREVIOUS_GREEN_ALGORITHM_VERSIONS
    assert settings.DETECTION_ALGORITHM_VERSION == "1.0.0"
    assert settings.DETECTION_ALGORITHM_VERSION in gen.PREVIOUS_GREEN_ALGORITHM_VERSIONS
    blue = {k: Path(v).name for k, v in settings.LANDCOVER_RASTERS.items()}
    assert blue == {
        "mapbiomas10m": "mapbiomas10m_araripe_2023.tif",
        "mapbiomas30m": "mapbiomas30m_araripe_2023.tif",
    }


def test_os_recortes_da_geracao_sao_os_2025_e_batem_com_o_relatorio():
    crops = gen.landcover_crops(ROOT)
    assert sorted(crops) == ["mapbiomas10m", "mapbiomas30m"]
    for entry in crops.values():
        assert entry["report"]["year"] == 2025
        assert "2023" not in entry["path"].name
        assert entry["sha256"] == entry["report"]["crop"]["sha256"]


def test_um_recorte_trocado_e_recusado_antes_de_anotar(tmp_path):
    for stem in gen.GREEN_LANDCOVER_CROPS.values():
        for suffix in (".tif", ".report.json"):
            source = ROOT / "data" / "landcover" / f"{stem}{suffix}"
            target = tmp_path / "data" / "landcover" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    gen.landcover_crops(tmp_path)  # a cópia fiel passa
    victim = tmp_path / "data" / "landcover" / f"{gen.GREEN_LANDCOVER_CROPS['mapbiomas30m']}.tif"
    body = bytearray(victim.read_bytes())
    body[-1] ^= 0xFF
    victim.write_bytes(bytes(body))
    with pytest.raises(gen.GenerationError, match="mapbiomas30m"):
        gen.landcover_rasters(tmp_path)
    victim.unlink()
    with pytest.raises(gen.GenerationError, match="absent"):
        gen.landcover_rasters(tmp_path)


def test_o_modulo_da_geracao_nao_importa_config():
    """Os scripts da cadeia o importam, e eles nunca podem importar
    `config.settings` (carrega o `.env` de produção)."""

    tree = ast.parse((ROOT / "src" / "replay" / "generation.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "hashlib", "json", "pathlib"}


def test_o_contexto_usa_a_mesma_receita_que_a_release():
    context = load_script("publish_green_context")
    assert context.CROPS == gen.GREEN_LANDCOVER_CROPS


# ── o replay ─────────────────────────────────────────────────────────────────


def _replay_tree():
    return ast.parse((ROOT / "scripts" / "replay_2026.py").read_text(encoding="utf-8"))


def test_o_replay_nao_le_a_versao_nem_os_rasters_do_azul():
    """Pela AST: a docstring do replay pode citar os nomes, um import não."""

    from_settings, from_generation = set(), set()
    for node in ast.walk(_replay_tree()):
        if isinstance(node, ast.ImportFrom) and node.module == "config.settings":
            from_settings |= {alias.name for alias in node.names}
        if isinstance(node, ast.ImportFrom) and node.module == "src.replay.generation":
            from_generation |= {alias.name for alias in node.names}
        if isinstance(node, ast.Attribute):
            assert node.attr != "LANDCOVER_RASTERS"
        if isinstance(node, ast.Name):
            assert node.id != "LANDCOVER_RASTERS"
    assert from_settings and not from_settings & {
        "DETECTION_ALGORITHM_VERSION", "DEFAULT_LANDCOVER_COLLECTION", "LANDCOVER_RASTERS",
    }
    assert {"GREEN_ALGORITHM_VERSION", "landcover_rasters"} <= from_generation


def test_o_replay_anota_com_rasters_explicitos_e_sem_engolir_a_falha():
    calls = [
        node for node in ast.walk(_replay_tree())
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "annotate_alerts_all_collections"
    ]
    assert len(calls) == 1
    assert "rasters" in {keyword.arg for keyword in calls[0].keywords}
    for node in ast.walk(_replay_tree()):
        if isinstance(node, ast.Try):
            inside = {
                getattr(call.func, "id", None)
                for call in ast.walk(ast.Module(body=node.body, type_ignores=[]))
                if isinstance(call, ast.Call)
            }
            assert "annotate_alerts_all_collections" not in inside


# ── o freeze v2 ──────────────────────────────────────────────────────────────


def test_o_freeze_v2_fotografa_os_recortes_2025_por_sha256_e_nao_nomeia_2023():
    document = fz.load_freeze()
    assert document["replay_freeze_version"] == "phase3-replay-freeze-v2"
    assert fz.FREEZE_PATH.name == "phase3_replay_freeze_v2.json"
    rasters = document["mapbiomas"]["rasters"]
    crops = gen.landcover_crops(ROOT)
    assert sorted(rasters) == sorted(crops)
    for key, entry in rasters.items():
        assert entry["sha256"] == crops[key]["sha256"]
        assert entry["bytes"] == crops[key]["bytes"]
        assert entry["year"] == 2025
    assert "2023" not in json.dumps(document["mapbiomas"])
    algorithm = document["algorithm"]
    assert algorithm["detection_algorithm_version"] == gen.GREEN_ALGORITHM_VERSION
    assert algorithm["runtime_default_algorithm_version"] == settings.DETECTION_ALGORITHM_VERSION


def test_o_freeze_v1_fica_como_registro_e_ninguem_o_carrega():
    v1 = json.loads((ROOT / "config" / "phase3_replay_freeze_v1.json").read_text(encoding="utf-8"))
    assert v1["replay_freeze_version"] == "phase3-replay-freeze-v1"
    with pytest.raises(fz.FreezeError):
        fz.validate_freeze(v1)


# ── a cadeia recusa continuar outra geração ─────────────────────────────────


def _run(run_id: str, last: str, parent: str | None = None) -> dict:
    ledger, _ = build_ledger({last: [ZERO]})
    state = f'{{"run":"{run_id}"}}\n'.encode()
    document = {
        "schema": "araripe.green.run/2",
        "run_id": run_id,
        "ledger": "ledger.json",
        "persistence_state": {"sha256": sha256_bytes(state), "bytes": len(state)},
        "objects": [],
        "predecessor": None if parent is None else {
            "run_id": parent, "persistence_state_sha256": "0" * 64},
    }
    return {
        f"runs/{run_id}/ledger.json": (json.dumps(ledger).encode(), "application/json"),
        f"runs/{run_id}/persistence_state.geojson": (state, "application/geo+json"),
        f"runs/{run_id}/run.json": (json.dumps(document).encode(), "application/json"),
    }


def test_a_fixture_e_de_outra_geracao():
    """A premissa dos dois testes abaixo, medida e não suposta — eu a supus
    `1.0.0` e a fixture do contrato diz `2.0.0`; o que importa é ser outra."""

    ledger, _ = build_ledger({"2026-09-07": [ZERO]})
    assert ledger["algorithm_version"] != gen.GREEN_ALGORITHM_VERSION


def test_o_fetch_recusa_um_antecessor_de_outra_geracao_antes_do_estado(tmp_path):
    fetch = load_script("fetch_green_state")
    fake = FakeS3(_run("ci-old", "2026-09-07"))
    store = ReadOnlyStore(fake, cs.STAGING_BUCKET)
    with pytest.raises(sc.ChainRejected) as excinfo:
        fetch.fetch(store, "ci-old", "2026-09-08", tmp_path / "out", "ci-new")
    assert excinfo.value.codes == ("predecessor_other_generation",)
    assert "runs/ci-old/persistence_state.geojson" not in fake.reads
    assert not (tmp_path / "out").exists()
    assert fake.writes == []


def test_a_cabeca_de_outra_geracao_nao_da_janela(monkeypatch):
    resolve = load_script("resolve_chain_head")
    fake = FakeS3(_run(sc.CHAIN_ROOT, "2026-08-30"))
    store = ReadOnlyStore(fake, cs.STAGING_BUCKET)
    with pytest.raises(sc.ChainRejected) as excinfo:
        resolve.resolve(store, "2026-10-07")
    assert excinfo.value.codes == ("predecessor_other_generation",)


def test_o_guarda_compara_a_versao_que_o_ledger_sela():
    same = sc.Predecessor("r", "a" * 64, 1, "2026-09-07", algorithm_version="1.1.0")
    sc.check_generation(same, "1.1.0")
    for other in ("1.0.0", None):
        with pytest.raises(sc.ChainRejected):
            sc.check_generation(
                sc.Predecessor("r", "a" * 64, 1, "2026-09-07", algorithm_version=other), "1.1.0")


# ── a raiz cujas datas foram todas recusadas (run 37659861235) ──────────────


def test_um_lote_sem_data_aceita_deixa_um_estado_vazio_equivalente_ao_nenhum(tmp_path):
    """A 1ª janela da raiz 1.1.0 (2026-01-01..01-17) teve 7 aquisições, todas
    recusadas; o replay não gravou estado e o montador recusou a rodada. O
    estado vazio gravado tem de ser lido de volta como o `update_tracks` trata
    `None`: nenhuma linha, nenhuma marca d'água, nenhuma geração carimbada."""

    from src.detection import persistence as ps

    replay = load_script("replay_2026")
    path = tmp_path / "persistence_state.geojson"
    ps.save_persistence_state(replay.state_to_save(None), path)
    loaded = ps.load_persistence_state(path)
    assert loaded is not None and len(loaded) == 0
    fresh = ps.empty_persistence_state()
    assert ps._state_metadata(loaded) == ps._state_metadata(fresh)
    assert ps._state_metadata(loaded).get("algorithm_version") is None
    kept = ps.empty_persistence_state()
    assert replay.state_to_save(kept) is kept


def test_o_replay_grava_o_estado_sempre():
    saves = [
        node for node in ast.walk(_replay_tree())
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "save_persistence_state"
    ]
    assert len(saves) == 1
    (call,) = saves
    assert getattr(call.args[0].func, "id", None) == "state_to_save"
    for node in ast.walk(_replay_tree()):
        if isinstance(node, ast.If):
            inside = [n for n in ast.walk(ast.Module(body=node.body, type_ignores=[])) if n is call]
            assert not inside, "o estado não pode depender de uma condição"
