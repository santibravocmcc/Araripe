"""Offline integrity tests for Phase 2A.4 evidence assembly helpers."""

from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pystac
import pytest
import xarray as xr

from src.detection.baseline_manifest import sha256_file
from src.detection.identity import canonical_geometry_sha256, canonical_sha256
from src.detection.change_detect import detect_deforestation
from src.validation.phase2a4 import MaskCandidateConfig, canonical_array_record
from src.validation.phase2a4_evidence import (
    GRID_HEIGHT,
    GRID_WIDTH,
    Phase2A4EvidenceError,
    _apply_reflectance_normalization,
    _candidate_drought_status,
    _contributing_scene_records,
    _compute_indices,
    _detect,
    _disabled_drought_status,
    _evaluate_mask_candidates,
    _load_npy,
    _npy_storage_array,
    _paired_stratum_key,
    _query_items,
    _query_record,
    _reflectance_normalization_record,
    _reflectance_warp_nodata_options,
    _resolve_provider_asset_hrefs,
    _validate_query_execution,
    _validate_reflectance_normalization_binding,
    _validate_reflectance_window_values,
    _validate_unsigned_provider_href,
    _validate_baseline_provenance,
    _validate_categorical_source_values,
    _validate_output_record,
    _validate_stac_item_binding,
    _window_from_geometry,
    _write_npy,
)


def _small_geometry():
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [-39.3769, -7.0650],
                [-39.3762, -7.0650],
                [-39.3762, -7.0643],
                [-39.3769, -7.0643],
                [-39.3769, -7.0650],
            ]
        ],
    }


def test_case_window_is_integer_aligned_fixed_and_digest_bound():
    first = _window_from_geometry(_small_geometry())
    second = _window_from_geometry(copy.deepcopy(_small_geometry()))
    assert first["case_window"] == second["case_window"]
    case = first["case_window"]
    digest = case.pop("window_definition_sha256")
    assert digest == canonical_sha256(case)
    assert 0 <= case["column_offset"] < GRID_WIDTH
    assert 0 <= case["row_offset"] < GRID_HEIGHT
    assert case["column_offset"] + case["width"] <= GRID_WIDTH
    assert case["row_offset"] + case["height"] <= GRID_HEIGHT
    assert case["transform"][0:2] == [20.0, 0.0]
    assert case["transform"][3:5] == [0.0, -20.0]
    assert int(first["comparison_mask"].sum()) == case["width"] * case["height"]
    assert first["context_window"]["auxiliary_halo_m"] == 1060.0


def test_case_window_clips_at_reference_grid_without_changing_denominator():
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [-40.89236812577142, -7.840780758480428],
                [-40.8919, -7.840780758480428],
                [-40.8919, -7.8403],
                [-40.89236812577142, -7.8403],
                [-40.89236812577142, -7.840780758480428],
            ]
        ],
    }
    record = _window_from_geometry(geometry)
    case = record["case_window"]
    assert case["column_offset"] >= 0
    assert case["row_offset"] >= 0
    assert record["comparison_mask"].sum() == case["width"] * case["height"]


def test_npy_storage_normalization_is_exact_and_rejects_one_float32_ulp(
    tmp_path: Path,
):
    generated = np.asarray(
        [[np.nan, -0.0, 0.125, 0.3]], dtype=np.float64
    )
    path = tmp_path / "values.npy"
    _write_npy(path, generated)
    stored = _load_npy(path)
    expected = _npy_storage_array(generated)

    assert stored.dtype == np.dtype("<f4")
    assert np.array_equal(stored, expected, equal_nan=True)
    assert canonical_array_record(stored) == canonical_array_record(expected)

    tampered = stored.copy()
    tampered[0, 2] = np.nextafter(
        tampered[0, 2], np.float32(np.inf), dtype=np.float32
    )
    assert not np.array_equal(tampered, expected, equal_nan=True)
    assert canonical_array_record(tampered) != canonical_array_record(expected)


def test_stac_query_is_full_geometry_bound_and_uncapped():
    geometry = _small_geometry()
    query = _query_record("2026-07-16", geometry)
    request = {
        "stac_endpoint": "https://earth-search.aws.element84.com/v1",
        "collection": "sentinel-2-l2a",
        "intersects": geometry,
        "datetime": "2026-07-16T00:00:00Z/2026-07-17T00:00:00Z",
        "query": {"eo:cloud_cover": {"lt": 60}},
        "max_items": None,
        "pagination_policy": "all_pages_until_exhausted",
    }
    assert query["result_limit"] is None
    assert query["pagination_policy"] == "all_pages_until_exhausted"
    assert query["intersects_geometry_sha256"] == canonical_geometry_sha256(geometry)[1]
    assert query["canonical_payload_sha256"] == canonical_sha256(request)


def _query_test_item(item_id: str) -> pystac.Item:
    item = pystac.Item(
        id=item_id,
        geometry=_small_geometry(),
        bbox=None,
        datetime=dt.datetime(2026, 7, 16, 10, tzinfo=dt.timezone.utc),
        properties={"eo:cloud_cover": 10},
    )
    item.collection_id = "sentinel-2-l2a"
    return item


class _FakeSearch:
    def __init__(self, pages, *, fail_after: int | None = None):
        self._pages = pages
        self._fail_after = fail_after

    def pages(self):
        for index, page in enumerate(self._pages, start=1):
            if self._fail_after == index:
                raise RuntimeError("page fetch failed")
            yield page


class _FakeClient:
    def __init__(self, search):
        self._search = search

    def search(self, **_kwargs):
        return self._search


def _trace_scenes(items):
    return [
        {
            "item_id": item.id,
            "stac_item_json_sha256": canonical_sha256(item.to_dict()),
        }
        for item in items
    ]


def test_stac_pagination_trace_records_observed_exhaustion(monkeypatch):
    first = pystac.ItemCollection(
        [_query_test_item("scene-b")],
        extra_fields={"links": [{"rel": "next", "href": "https://example/2"}]},
    )
    second = pystac.ItemCollection(
        [_query_test_item("scene-a")], extra_fields={"links": []}
    )
    monkeypatch.setattr(
        "src.validation.phase2a4_evidence.pystac_client.Client.open",
        lambda *_args, **_kwargs: _FakeClient(_FakeSearch([first, second])),
    )

    items, _query, error, execution = _query_items(
        "2026-07-16", _small_geometry()
    )

    assert error is None
    assert [item.id for item in items] == ["scene-a", "scene-b"]
    assert execution["status"] == "complete"
    assert execution["collector_observed_exhaustion"] is True
    assert execution["completed_page_count"] == 2
    source_query = {"query_error": error, "query_execution": execution}
    _validate_query_execution(
        source_query, _trace_scenes(items), sample_id="pagination-test"
    )

    tampered = copy.deepcopy(execution)
    tampered["page_trace"][0]["item_count"] = 2
    tampered["page_trace_sha256"] = canonical_sha256(tampered["page_trace"])
    with pytest.raises(Phase2A4EvidenceError, match="counts/order"):
        _validate_query_execution(
            {"query_error": error, "query_execution": tampered},
            _trace_scenes(items),
            sample_id="pagination-test",
        )

    incomplete_without_failure = copy.deepcopy(execution)
    incomplete_without_failure["status"] = "partial"
    incomplete_without_failure["collector_observed_exhaustion"] = False
    with pytest.raises(Phase2A4EvidenceError, match="no retained failure"):
        _validate_query_execution(
            {
                "query_error": None,
                "query_execution": incomplete_without_failure,
            },
            _trace_scenes(items),
            sample_id="pagination-test",
        )


def test_stac_pagination_accepts_suppressed_empty_terminal_page(monkeypatch):
    """pystac-client omits the empty page fetched from the final next link."""
    final_nonempty = pystac.ItemCollection(
        [_query_test_item("scene-a")],
        extra_fields={"links": [{"rel": "next", "href": "https://example/empty"}]},
    )
    monkeypatch.setattr(
        "src.validation.phase2a4_evidence.pystac_client.Client.open",
        lambda *_args, **_kwargs: _FakeClient(_FakeSearch([final_nonempty])),
    )

    items, _query, error, execution = _query_items(
        "2026-07-16", _small_geometry()
    )

    assert error is None
    assert [item.id for item in items] == ["scene-a"]
    assert execution["status"] == "complete"
    assert execution["collector_observed_exhaustion"] is True
    assert execution["completed_page_count"] == 1
    assert execution["page_trace"][0]["advertised_next_page"] is True
    _validate_query_execution(
        {"query_error": error, "query_execution": execution},
        _trace_scenes(items),
        sample_id="suppressed-empty-terminal-test",
    )


def test_stac_later_page_failure_retains_prior_items_and_forbids_completion(
    monkeypatch,
):
    first = pystac.ItemCollection(
        [_query_test_item("scene-a")],
        extra_fields={"links": [{"rel": "next", "href": "https://example/2"}]},
    )
    second = pystac.ItemCollection(
        [_query_test_item("scene-b")], extra_fields={"links": []}
    )
    monkeypatch.setattr(
        "src.validation.phase2a4_evidence.pystac_client.Client.open",
        lambda *_args, **_kwargs: _FakeClient(
            _FakeSearch([first, second], fail_after=2)
        ),
    )

    items, _query, error, execution = _query_items(
        "2026-07-16", _small_geometry()
    )

    assert [item.id for item in items] == ["scene-a"]
    assert error == "page fetch failed"
    assert execution["status"] == "partial"
    assert execution["collector_observed_exhaustion"] is False
    assert execution["observed_item_count"] == 1
    _validate_query_execution(
        {"query_error": error, "query_execution": execution},
        _trace_scenes(items),
        sample_id="pagination-failure-test",
    )


def _stac_binding_fixture():
    item = _query_test_item("scene-a")
    item_json = item.to_dict()
    self_href = (
        "https://earth-search.aws.element84.com/v1/collections/"
        "sentinel-2-l2a/items/scene-a"
    )
    scene = {
        "catalog": "Element84 Earth Search",
        "stac_endpoint": "https://earth-search.aws.element84.com/v1",
        "collection_id": "sentinel-2-l2a",
        "item_id": "scene-a",
        "observed_at": "2026-07-16T10:00:00Z",
        "self_href": self_href,
        "stac_item_json_sha256": canonical_sha256(item_json),
        "assets": [],
    }
    source_query = {"query": {"intersects": _small_geometry()}}
    return item_json, scene, source_query


@pytest.mark.parametrize(
    ("target", "value"),
    (
        ("collection_id", "other-collection"),
        ("observed_at", "2026-07-15T10:00:00Z"),
        ("self_href", "https://example.test/item?token=secret"),
    ),
)
def test_stac_scene_projection_tamper_is_rejected(target, value):
    item_json, scene, source_query = _stac_binding_fixture()
    scene[target] = value
    with pytest.raises(Phase2A4EvidenceError):
        _validate_stac_item_binding(
            item_json,
            scene,
            source_query,
            target_date="2026-07-16",
            sample_id="stac-binding-test",
        )


@pytest.mark.parametrize("tamper", ("collection", "date", "geometry", "cloud"))
def test_raw_stac_item_query_binding_tamper_is_rejected(tamper):
    item_json, scene, source_query = _stac_binding_fixture()
    if tamper == "collection":
        item_json["collection"] = "other-collection"
    elif tamper == "date":
        item_json["properties"]["datetime"] = "2026-07-15T10:00:00Z"
        scene["observed_at"] = "2026-07-15T10:00:00Z"
    elif tamper == "geometry":
        item_json["geometry"] = {"type": "Point", "coordinates": [0.0, 0.0]}
    else:
        item_json["properties"]["eo:cloud_cover"] = 60
    scene["stac_item_json_sha256"] = canonical_sha256(item_json)
    with pytest.raises(Phase2A4EvidenceError):
        _validate_stac_item_binding(
            item_json,
            scene,
            source_query,
            target_date="2026-07-16",
            sample_id="stac-binding-test",
        )


def test_output_record_validator_rejects_semantic_tamper():
    payload = {"status": "available", "candidate_only": True}
    record = {**payload, "output_sha256": canonical_sha256(payload)}
    _validate_output_record(record, "test")
    record["status"] = "unavailable"
    with pytest.raises(Phase2A4EvidenceError, match="output hash mismatch"):
        _validate_output_record(record, "test")


@pytest.mark.parametrize(
    ("asset_key", "value"),
    (("scl", 12), ("cloud", 101)),
)
def test_categorical_source_range_tamper_is_rejected(asset_key, value):
    with pytest.raises(Phase2A4EvidenceError, match="range mismatch"):
        _validate_categorical_source_values(
            asset_key, np.asarray([[value]], dtype=np.uint8)
        )


def _reflectance_asset_metadata():
    return {
        "href": "https://example.test/reflectance.tif",
        "raster:bands": [{"scale": 0.0001, "offset": -0.1}],
    }


def test_reflectance_normalization_is_fixed_and_zero_fill_precedes_resampling():
    normalization = _reflectance_normalization_record(
        _reflectance_asset_metadata()
    )
    assert normalization == {
        "policy_version": (
            "sentinel2-l2a-stac-scale-offset-zero-fill-nonnegative-v1"
        ),
        "scale_offset_source": "raster:bands[0].scale_and_offset_required",
        "raw_zero_fill": "invalid_before_resampling_and_scaling",
        "negative_scaled_reflectance": "clip_to_zero",
        "output_dtype": "float32",
        "status": "available",
        "reason": None,
        "scale": 0.0001,
        "offset": -0.1,
    }
    warp = _reflectance_warp_nodata_options("nir", None)
    assert warp["src_nodata"] == 0.0
    assert np.isnan(warp["nodata"])
    assert warp["dtype"] == "float32"


def test_provider_s3_cloud_href_maps_to_same_public_bucket_key():
    provider = "s3://sentinel-s2-l2a/tiles/24/M/US/2026/5/7/0/qi/CLD_20m.jp2"
    assert _resolve_provider_asset_hrefs(provider, label="cloud") == (
        provider,
        "https://sentinel-s2-l2a.s3.amazonaws.com/"
        "tiles/24/M/US/2026/5/7/0/qi/CLD_20m.jp2",
    )
    https = "https://sentinel-cogs.s3.us-west-2.amazonaws.com/object.tif"
    assert _resolve_provider_asset_hrefs(https, label="reflectance") == (
        https,
        https,
    )
    with pytest.raises(Phase2A4EvidenceError, match="not an allowed public"):
        _resolve_provider_asset_hrefs(
            "s3://unapproved-bucket/object.jp2", label="cloud"
        )
    assert _validate_unsigned_provider_href(
        "s3://unapproved-but-unsigned-optional-asset/object.bin",
        label="optional asset",
    ).startswith("s3://")
    with pytest.raises(Phase2A4EvidenceError, match="not unsigned"):
        _validate_unsigned_provider_href(
            "https://example.test/object?token=secret", label="optional asset"
        )


@pytest.mark.parametrize("missing", ("scale", "offset"))
def test_reflectance_normalization_rejects_missing_scale_or_offset(missing):
    metadata = _reflectance_asset_metadata()
    del metadata["raster:bands"][0][missing]
    with pytest.raises(Phase2A4EvidenceError, match=f"{missing} metadata is required"):
        _reflectance_normalization_record(metadata)


def test_reflectance_zero_fill_is_invalid_and_negative_values_clip_to_zero():
    normalization = _reflectance_normalization_record(
        _reflectance_asset_metadata()
    )
    values, valid = _apply_reflectance_normalization(
        np.asarray([[0.0, 500.0, 2000.0, np.nan]], dtype=np.float32),
        np.ones((1, 4), dtype=bool),
        normalization,
    )
    np.testing.assert_array_equal(valid, [[False, True, True, False]])
    assert np.isnan(values[0, 0])
    assert values[0, 1] == np.float32(0.0)
    assert values[0, 2] == pytest.approx(0.1)
    assert np.isnan(values[0, 3])
    _validate_reflectance_window_values(values, valid, label="normalization-test")


def test_deep_replay_helpers_reject_normalization_and_value_tampering():
    metadata = _reflectance_asset_metadata()
    normalization = _reflectance_normalization_record(metadata)
    asset = {
        "status": "available",
        "reason": None,
        "reflectance_normalization": normalization,
        "http_metadata": {
            "status_code": 200,
            "content_length": 1,
            "etag": None,
            "last_modified": None,
            "content_type": "image/tiff",
            "accept_ranges": "bytes",
        },
    }
    assert (
        _validate_reflectance_normalization_binding(
            "nir", asset, metadata, label="binding-test"
        )
        == normalization
    )
    tampered = copy.deepcopy(asset)
    tampered["reflectance_normalization"]["offset"] = 0.0
    with pytest.raises(Phase2A4EvidenceError, match="normalization mismatch"):
        _validate_reflectance_normalization_binding(
            "nir", tampered, metadata, label="binding-test"
        )

    invalid_values = np.asarray([[-0.01, 0.2]], dtype=np.float32)
    invalid_validity = np.asarray([[True, True]], dtype=bool)
    with pytest.raises(Phase2A4EvidenceError, match="value/validity semantics"):
        _validate_reflectance_window_values(
            invalid_values, invalid_validity, label="binding-test"
        )


def test_accepted_baseline_status_literal_is_not_weakened():
    source = (Path(__file__).resolve().parent.parent / "src/validation/phase2a4_evidence.py").read_text(
        encoding="utf-8"
    )
    assert 'value.get("status") != "accepted_audit_generation"' in source


def _baseline_provenance_fixture(tmp_path):
    root = tmp_path / "evidence"
    case_root = root / "cases" / "sample"
    base_url = "https://baseline.example.test"
    objects = []
    range_objects = []
    artifacts = []
    for index_number, index_name in enumerate(("evi2", "nbr", "ndmi")):
        for statistic_number, statistic in enumerate(("mean", "std")):
            key = f"baselines/{index_name}_month07_{statistic}.tif"
            etag = f"etag-{index_number}-{statistic_number}"
            size = 1000 + index_number * 10 + statistic_number
            objects.append(
                {
                    "key": key,
                    "bytes": size,
                    "sha256": f"{index_number * 2 + statistic_number + 1:064x}",
                    "r2_etag": etag,
                }
            )
            path = case_root / "baseline-windows" / f"{index_name}-{statistic}.npy"
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, np.ones((2, 2), dtype=np.float32), allow_pickle=False)
            artifact = {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "media_type": "application/x-npy",
                "role": "accepted_baseline_window",
            }
            artifacts.append(artifact)
            range_objects.append(
                {
                    "key": key,
                    "status": "available",
                    "reason": None,
                    "manifest_bytes": size,
                    "manifest_sha256": objects[-1]["sha256"],
                    "manifest_r2_etag": etag,
                    "unsigned_href": f"{base_url}/{key}",
                    "http_metadata": {
                        "status_code": 200,
                        "content_length": size,
                        "etag": f'"{etag}"',
                        "last_modified": "Mon, 03 Aug 2026 00:00:00 GMT",
                        "content_type": "image/tiff",
                        "accept_ranges": "bytes",
                    },
                    "read_mode": "remote_cog_range_read_to_aligned_context_window",
                    "local_window": artifact,
                    "checksum_scope_limitation": (
                        "accepted_manifest_sha256_binds_full_object; "
                        "local_window_sha256_binds_only_aligned_context_derivative"
                    ),
                }
            )
    manifest = {
        "baseline_id": "accepted-baseline",
        "baseline_version": "1.0.0",
        "objects": objects,
    }
    record = {
        "status": "available",
        "reason": None,
        "baseline_id": "accepted-baseline",
        "baseline_version": "1.0.0",
        "manifest_sha256": (
            "15a1ed3cea7c804d18d2c82c86a7b9a030687fedb01b315d543965b1f26f0a82"
        ),
        "range_read": {
            "month": 7,
            "status": "available",
            "reason": None,
            "objects": range_objects,
        },
        "artifacts": artifacts,
    }
    return root, case_root, manifest, base_url, record


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("manifest_sha256", "0" * 64),
        ("http_etag", '"wrong"'),
        ("unsigned_href", "https://wrong.example.test/object"),
        ("local_sha256", "0" * 64),
    ),
)
def test_baseline_provenance_tamper_is_rejected(tmp_path, field, value):
    root, case_root, manifest, base_url, record = _baseline_provenance_fixture(
        tmp_path
    )
    arrays, artifacts = _validate_baseline_provenance(
        root,
        case_root,
        record,
        baseline_manifest=manifest,
        baseline_public_base_url=base_url,
        context_shape=(2, 2),
        month=7,
        sample_id="baseline-test",
    )
    assert arrays is not None and len(artifacts) == 6

    tampered = copy.deepcopy(record)
    first = tampered["range_read"]["objects"][0]
    if field == "manifest_sha256":
        first["manifest_sha256"] = value
    elif field == "http_etag":
        first["http_metadata"]["etag"] = value
    elif field == "unsigned_href":
        first["unsigned_href"] = value
    else:
        first["local_window"]["sha256"] = value
    with pytest.raises(Phase2A4EvidenceError):
        _validate_baseline_provenance(
            root,
            case_root,
            tampered,
            baseline_manifest=manifest,
            baseline_public_base_url=base_url,
            context_shape=(2, 2),
            month=7,
            sample_id="baseline-test",
        )


def _baseline(shape):
    return {
        name: {
            "mean": np.full(shape, 0.5, dtype=np.float32),
            "std": np.full(shape, 0.1, dtype=np.float32),
        }
        for name in ("evi2", "nbr", "ndmi")
    }


def _reflectance(shape=(2, 3)):
    # blue, red, broad NIR, narrow NIR, SWIR1, SWIR2
    return np.stack(
        [
            np.full(shape, 0.05),
            np.full(shape, 0.10),
            np.full(shape, 0.20),
            np.full(shape, 0.20),
            np.full(shape, 0.20),
            np.full(shape, 0.20),
        ]
    )


def test_detection_preserves_invalid_pixels_and_applies_only_supplied_adjustment():
    values = _reflectance()
    comparison = np.array([[True, True, False], [True, True, False]])
    composite_valid = np.array([[True, False, True], [True, True, True]])
    valid, confidence, record = _detect(
        values,
        composite_valid,
        _baseline((2, 3)),
        comparison_mask=comparison,
        z_adjustment=0.0,
    )
    assert record["case_window_pixel_count"] == 4
    assert record["valid_pixel_count"] == 3
    assert record["valid_coverage_fraction"] == pytest.approx(0.75)
    assert confidence[0, 1] == -1
    assert confidence[0, 2] == -1
    assert valid[0, 1] == np.bool_(False)
    _, _, adjusted = _detect(
        values,
        composite_valid,
        _baseline((2, 3)),
        comparison_mask=comparison,
        z_adjustment=0.5,
    )
    assert adjusted["z_thresholds"] == {"high": -3.5, "medium": -3.0, "low": -2.5}
    assert record["z_thresholds"] == {"high": -3.0, "medium": -2.5, "low": -2.0}


def test_detection_matches_accepted_union_eligibility_and_std_floor():
    values = _reflectance((1, 3))
    baseline = _baseline((1, 3))
    for name in baseline:
        baseline[name]["mean"][:] = np.nan
        baseline[name]["std"][:] = np.nan
    baseline["evi2"]["mean"][0, 0] = 0.5
    baseline["evi2"]["std"][0, 0] = 0.0
    baseline["ndmi"]["mean"][0, 1] = 0.5
    baseline["ndmi"]["std"][0, 1] = 0.1

    valid, confidence, record = _detect(
        values,
        np.ones((1, 3), dtype=bool),
        baseline,
        comparison_mask=np.ones((1, 3), dtype=bool),
        z_adjustment=0.0,
    )

    np.testing.assert_array_equal(valid, [[True, True, False]])
    assert confidence[0, 0] >= 0
    assert confidence[0, 1] >= 0
    assert confidence[0, 2] == -1
    assert record["standard_deviation_floor"] == 0.01
    assert record["valid_pixel_rule"].startswith("union_of_per_index")


def test_detection_preserves_accepted_exact_zero_denominator_rule():
    values = _reflectance((1, 1))
    values[3, 0, 0] = 1e-13
    values[4, 0, 0] = 0.0
    baseline = _baseline((1, 1))
    for name in baseline:
        baseline[name]["mean"][:] = np.nan
        baseline[name]["std"][:] = np.nan
    baseline["ndmi"]["mean"][:] = 0.5
    baseline["ndmi"]["std"][:] = 0.1

    valid, confidence, _record = _detect(
        values,
        np.ones((1, 1), dtype=bool),
        baseline,
        comparison_mask=np.ones((1, 1), dtype=bool),
        z_adjustment=0.0,
    )

    assert valid[0, 0]
    assert confidence[0, 0] >= 0


def test_detection_replay_matches_accepted_float32_boundary_semantics():
    values = _reflectance((1, 3)).astype(np.float32)
    values[3, 0] = np.asarray([0.21, 0.20, 0.19], dtype=np.float32)
    values[4, 0] = np.asarray([0.19, 0.20, 0.21], dtype=np.float32)
    values[5, 0] = np.asarray([0.19, 0.21, 0.20], dtype=np.float32)
    indices = _compute_indices(values)
    assert all(value.dtype == np.float32 for value in indices.values())

    baseline = {
        name: {
            "mean": np.asarray(current + np.float32(0.15), dtype=np.float32),
            "std": np.full(current.shape, np.float32(0.05), dtype=np.float32),
        }
        for name, current in indices.items()
    }
    # Exercise the accepted union-validity behavior together with its exact
    # z-score implementation when one index has a non-finite std.
    baseline["evi2"]["std"][0, 1] = np.nan
    comparison = np.ones((1, 3), dtype=bool)
    composite_valid = np.ones((1, 3), dtype=bool)

    valid, confidence, _record = _detect(
        values,
        composite_valid,
        baseline,
        comparison_mask=comparison,
        z_adjustment=0.0,
    )

    current = xr.Dataset(
        {name: (("y", "x"), array) for name, array in indices.items()}
    )
    means = {
        name: xr.DataArray(parts["mean"], dims=("y", "x"))
        for name, parts in baseline.items()
    }
    stds = {
        name: xr.DataArray(parts["std"], dims=("y", "x"))
        for name, parts in baseline.items()
    }
    accepted = detect_deforestation(current, means, stds, spi_3month=None)
    expected_valid = np.asarray(accepted["valid_pixel_mask"].values, dtype=bool)
    expected_confidence = np.where(
        expected_valid,
        np.asarray(accepted["confidence"].values),
        -1,
    ).astype(np.int8)
    np.testing.assert_array_equal(valid, expected_valid)
    np.testing.assert_array_equal(confidence, expected_confidence)


def _extended_mask_candidate():
    return MaskCandidateConfig(
        candidate_id="scl-cloudprob-darkshadow-dilate-v1",
        scl_clear_classes=(4, 5, 6, 7),
        scl_shadow_classes=(3,),
        scl_invalid_classes=(0, 1),
        scl_cloud_classes=(8, 9, 10, 11),
        cloud_probability_max_percent=40,
        cloud_probability_uint8_required=True,
        shadow_mode="scl_or_projected_dark_nir",
        dark_nir_reflectance_max=0.15,
        within_cloud_distance_m=1000,
        pixel_size_m=20,
        dilation_m=60,
    )


def _mask_scene(scene_id, *, cloud=True, nir_value=0.2):
    shape = (1, 1)
    arrays = {
        name: np.full(shape, nir_value if name == "nir" else 0.2, dtype=np.float32)
        for name in ("blue", "red", "nir", "nir08", "swir16", "swir22")
    }
    arrays["scl"] = np.full(shape, 4, dtype=np.uint8)
    arrays["cloud"] = np.zeros(shape, dtype=np.uint8) if cloud else None
    validities = {
        name: np.ones(shape, dtype=bool) for name in arrays if arrays[name] is not None
    }
    validities["cloud"] = np.ones(shape, dtype=bool) if cloud else None
    return {"scene_id": scene_id, "arrays": arrays, "validities": validities}


def test_mask_candidate_retains_completed_scenes_before_later_failure():
    result = _evaluate_mask_candidates(
        [_mask_scene("scene-a"), _mask_scene("scene-b", cloud=False)],
        {"mask": _extended_mask_candidate()},
        comparison_mask=np.ones((1, 1), dtype=bool),
        scene_fatal=None,
    )["mask"]
    assert result["status"] == "unavailable"
    assert result["reason"] == "scene-b lacks usable cloud probability"
    assert [scene["scene_id"] for scene, _mask in result["per_scene"]] == [
        "scene-a"
    ]


def test_mask_candidate_input_error_is_explicit_unavailable_not_case_abort():
    result = _evaluate_mask_candidates(
        [_mask_scene("scene-a", nir_value=np.nan)],
        {"mask": _extended_mask_candidate()},
        comparison_mask=np.ones((1, 1), dtype=bool),
        scene_fatal=None,
    )["mask"]
    assert result["status"] == "unavailable"
    assert result["per_scene"] == []
    assert "scene-a mask input error" in result["reason"]


def test_drought_status_distinguishes_parameter_from_applied_adjustment():
    disabled = _disabled_drought_status()
    wet = _candidate_drought_status(
        {
            "status": "available",
            "spi_3month": -0.7,
            "is_drought": False,
            "reference_complete_count": 45,
        }
    )
    dry = _candidate_drought_status(
        {
            "status": "available",
            "spi_3month": -1.3,
            "is_drought": True,
            "reference_complete_count": 45,
        }
    )
    missing = _candidate_drought_status(
        {
            "status": "unavailable",
            "unavailable_reason": "missing_target_precipitation",
            "reference_complete_count": 44,
        }
    )
    assert disabled["z_threshold_adjustment"] == 0.0
    assert wet["status"] == "not_drought" and wet["z_threshold_adjustment"] == 0.0
    assert dry["status"] == "drought" and dry["z_threshold_adjustment"] == 0.5
    assert missing["z_threshold_adjustment"] is None
    assert missing["reason"] == "missing_target_precipitation"


def test_paired_panel_rows_hold_other_factors_constant():
    cells = []
    for cloud in ("cloud-a", "cloud-b"):
        for composition in ("composition-a", "composition-b"):
            for drought in ("drought-a", "drought-b"):
                cells.append(
                    {
                        "cell_id": f"{cloud}/{composition}/{drought}",
                        "candidates": {
                            "cloud_mask": cloud,
                            "daily_composition": composition,
                            "drought_adjustment": drought,
                        },
                    }
                )

    for family in ("cloud_mask", "daily_composition", "drought_adjustment"):
        candidates = sorted({cell["candidates"][family] for cell in cells})
        ordered = [
            sorted(
                (cell for cell in cells if cell["candidates"][family] == candidate),
                key=lambda cell: _paired_stratum_key("blind-case", family, cell),
            )
            for candidate in candidates
        ]
        for left, right in zip(*ordered, strict=True):
            assert {
                name: value
                for name, value in left["candidates"].items()
                if name != family
            } == {
                name: value
                for name, value in right["candidates"].items()
                if name != family
            }


def test_composition_contributors_are_not_dropped_by_detector_ineligibility():
    result = SimpleNamespace(
        source_scene_ids=("scene-a", "scene-b"),
        per_scene_pixel_counts={"scene-a": 2, "scene-b": 1},
        contributor_map=np.asarray([[0, 0, 1]], dtype=np.int32),
        record={
            "valid_pixel_count": 3,
            "per_scene_valid_pixel_counts": {"scene-a": 2, "scene-b": 1},
        },
    )
    records = _contributing_scene_records(
        result,
        np.asarray([[True, False, False]], dtype=bool),
        np.ones((1, 3), dtype=bool),
    )
    assert records == [
        {
            "scene_id": "scene-a",
            "selected_pixel_count": 2,
            "detector_valid_pixel_count": 1,
            "scene_valid_pixel_count": 2,
            "scene_valid_coverage_fraction": 2 / 3,
        },
        {
            "scene_id": "scene-b",
            "selected_pixel_count": 1,
            "detector_valid_pixel_count": 0,
            "scene_valid_pixel_count": 1,
            "scene_valid_coverage_fraction": 1 / 3,
        },
    ]
