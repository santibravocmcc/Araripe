"""Fail-closed loading of the persistence track state (Package 2B.1).

`scripts/run_detection.py` and `scripts/run_detection_from_gee.py` used to catch
every read error and continue with `state = None`, i.e. "start from zero". That
is the same silent corruption `scripts/r2_state.py` guards against, one layer
down: a state file that arrives corrupt or truncated would reset every track's
`n_sightings`/`first_seen`/`last_seen` while the run stayed green.

Genuine absence (the first-ever run) is still allowed — and is the only case
that returns `None`.
"""
from __future__ import annotations

import json

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from config.settings import TARGET_CRS
from src.detection.persistence import (
    LegacyPersistenceStateError,
    PersistenceStateError,
    empty_persistence_state,
    load_persistence_state,
    save_persistence_state,
)


def legacy_shaped_state():
    """A forma que era válida antes do Package 2A.6 — hoje é estado legado.

    Mantida porque é exatamente o que o portão determinístico tem de recusar, e
    porque é a forma do estado de produção vivo até a reconstrução da Phase 4.
    """
    return gpd.GeoDataFrame(
        {
            "n_sightings": [3, 17],
            "first_seen": ["2026-01-05", "2026-02-01"],
            "last_seen": ["2026-02-10", "2026-03-03"],
        },
        geometry=[
            Polygon([(-39.5, -7.5), (-39.5, -7.4), (-39.4, -7.4), (-39.5, -7.5)]),
            Polygon([(-39.3, -7.3), (-39.3, -7.2), (-39.2, -7.2), (-39.3, -7.3)]),
        ],
        crs="EPSG:4326",
    )


def sample_state():
    """Um estado determinístico VÁLIDO, produzido pelo próprio produtor.

    Construído por `update_tracks` em vez de à mão: um estado montado à mão
    afirma o esquema que o teste acha que existe, e foi assim que a forma
    legada sobreviveu num teste depois de o contrato ter mudado.
    """
    from shapely.geometry import box

    from config.settings import (
        BASELINE_VERSION,
        DETECTION_ALGORITHM_VERSION,
        MONITORING_EXTENT_ID,
    )
    from src.detection.identity import create_acquisition_identity
    from src.detection.persistence import update_tracks

    alerts = gpd.GeoDataFrame(
        {"area_ha": [1.0, 2.0]},
        geometry=[box(-39.5, -7.5, -39.4, -7.4), box(-39.3, -7.3, -39.2, -7.2)],
        crs="EPSG:4326",
    ).to_crs(TARGET_CRS)
    acquisition = create_acquisition_identity(
        collection_id="COPERNICUS/S2_SR_HARMONIZED",
        observed_on="2026-01-05",
        scene_ids=["COPERNICUS/S2_SR_HARMONIZED/20260105_a"],
        monitoring_extent_id=MONITORING_EXTENT_ID,
        composite_method_id="daily_mosaic-v1",
    )
    _, state = update_tracks(
        alerts,
        None,
        "2026-01-05",
        acquisition=acquisition,
        algorithm_version=DETECTION_ALGORITHM_VERSION,
        baseline_version=BASELINE_VERSION,
        monitoring_extent_id=MONITORING_EXTENT_ID,
    )
    return state


def test_absent_state_is_the_first_run(tmp_path):
    assert load_persistence_state(tmp_path / "persistence_state.geojson") is None


def test_valid_state_round_trips(tmp_path):
    """O que volta é o que foi gravado — comparado contra o estado, não contra
    números escolhidos à mão.

    A versão anterior deste teste afirmava `n_sightings == [3, 17]`, valores de
    um estado montado à mão. Isso o fazia passar sobre uma forma de estado que o
    contrato determinístico do Package 2A.6 já não aceita, e foi o que escondeu
    a mudança de esquema. Agora a afirmação é a propriedade: ida e volta é
    identidade.
    """
    path = tmp_path / "persistence_state.geojson"
    original = sample_state()
    save_persistence_state(original, path)
    loaded = load_persistence_state(path)
    assert len(loaded) == len(original)
    assert list(loaded["event_id"]) == list(original["event_id"])
    assert list(loaded["n_sightings"]) == list(original["n_sightings"])
    assert list(loaded["first_seen"]) == list(original["first_seen"])
    assert list(loaded["last_seen"]) == list(original["last_seen"])
    assert (
        loaded.attrs["persistence_metadata"]
        == original.attrs["persistence_metadata"]
    )


def test_empty_state_is_valid(tmp_path):
    """No alert ever seen is a legitimate state, not a corrupt one."""
    path = tmp_path / "persistence_state.geojson"
    save_persistence_state(empty_persistence_state(), path)
    assert len(load_persistence_state(path)) == 0


def test_corrupt_state_raises_instead_of_resetting(tmp_path):
    """The regression: an unreadable state must stop the run, not empty it."""
    path = tmp_path / "persistence_state.geojson"
    path.write_text('{"type": "FeatureCollection", "features": [ truncated')
    with pytest.raises(PersistenceStateError):
        load_persistence_state(path)


def test_empty_file_raises(tmp_path):
    path = tmp_path / "persistence_state.geojson"
    path.write_text("")
    with pytest.raises(PersistenceStateError):
        load_persistence_state(path)


def test_state_without_track_columns_raises(tmp_path):
    """Parseable GeoJSON from another schema is still not a track state."""
    path = tmp_path / "persistence_state.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"area_ha": 2.5},
            "geometry": {"type": "Point", "coordinates": [-39.5, -7.5]},
        }],
    }))
    with pytest.raises(PersistenceStateError, match="n_sightings"):
        load_persistence_state(path)


def test_o_estado_legado_FALHA_FECHADO_em_vez_de_ser_lido(tmp_path):
    """A forma pré-2A.6 não é lida como se fosse válida.

    Este teste é o par do `test_valid_state_round_trips`: aquele prova que o
    estado determinístico volta inteiro, e este prova que o estado da geração
    anterior **para a execução** em vez de virar contagem errada. A mensagem
    nomeia as colunas que faltam, porque quem for reconstruir precisa da lista.
    """
    path = tmp_path / "persistence_state.geojson"
    gdf = legacy_shaped_state()
    gdf.to_file(path, driver="GeoJSON")
    with pytest.raises(LegacyPersistenceStateError, match="n_sightings|deterministic"):
        load_persistence_state(path)
