"""Major-version separation guards for the audit-only v1 identity helpers."""

from copy import deepcopy

import pytest

from src.detection.identity import (
    AcquisitionIdentity,
    child_event_id,
    contribution_key,
    create_acquisition_identity,
    lineage_id,
    observation_id,
    origin_event_id,
)


SHA_A = "a" * 64
SHA_B = "b" * 64


def _acquisition():
    return create_acquisition_identity(
        collection_id="hls-v2.0",
        observed_on="2026-04-07",
        scene_ids=["hls-v2.0/scene-b", "hls-v2.0/scene-a"],
        monitoring_extent_id="araripe-implementation-rectangle-v1",
        composite_method_id="daily_mosaic-v1",
    )


def _v1_ids():
    acquisition = _acquisition()
    observation = observation_id(
        acquisition.acquisition_id,
        SHA_A,
        "1.0.0",
        "1.0.0",
    )
    event = origin_event_id(observation)
    child = child_event_id("split", [event], [observation])
    return acquisition, observation, event, child


def test_valid_v1_identity_family_still_round_trips():
    acquisition, observation, event, child = _v1_ids()

    assert AcquisitionIdentity.from_dict(acquisition.to_dict()) == acquisition
    assert observation.startswith("obs-v1-")
    assert event.startswith("evt-v1-")
    assert child.startswith("evt-v1-")
    assert lineage_id(
        relation="split",
        parent_event_ids=[event],
        child_event_ids=[child],
        acquisition_id=acquisition.acquisition_id,
        observed_on=acquisition.observed_on,
        trigger_observation_ids=[observation],
        algorithm_version="1.0.0",
    ).startswith("lin-v1-")
    assert contribution_key(event, acquisition.acquisition_id).startswith("pc-v1-")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("acquisition_id", f"acq-v2-{SHA_A}"),
        ("acquisition_id", "acq-v1-not-a-digest"),
        ("identity_inputs_sha256", "A" * 64),
    ],
)
def test_v1_acquisition_metadata_rejects_mixed_or_invalid_major(field, value):
    metadata = deepcopy(_acquisition().to_dict())
    metadata[field] = value

    with pytest.raises(ValueError):
        AcquisitionIdentity.from_dict(metadata)


@pytest.mark.parametrize(
    ("acquisition_id", "geometry_sha256", "algorithm_version", "baseline_version"),
    [
        (f"acq-v2-{SHA_A}", SHA_B, "1.0.0", "1.0.0"),
        ("acq-v1-short", SHA_B, "1.0.0", "1.0.0"),
        (f"acq-v1-{SHA_A}", "B" * 64, "1.0.0", "1.0.0"),
    ],
)
def test_v1_observation_id_rejects_mixed_or_invalid_identity_inputs(
    acquisition_id, geometry_sha256, algorithm_version, baseline_version
):
    with pytest.raises(ValueError):
        observation_id(
            acquisition_id,
            geometry_sha256,
            algorithm_version,
            baseline_version,
        )


@pytest.mark.parametrize(
    "first_observation_id",
    [f"obs-v2-{SHA_A}", "obs-v1-short", f"evt-v1-{SHA_A}"],
)
def test_v1_origin_event_rejects_mixed_or_invalid_observation_id(
    first_observation_id,
):
    with pytest.raises(ValueError):
        origin_event_id(first_observation_id)


@pytest.mark.parametrize(
    ("parents", "triggers"),
    [
        ([f"evt-v2-{SHA_A}"], [f"obs-v1-{SHA_B}"]),
        (["evt-v1-short"], [f"obs-v1-{SHA_B}"]),
        ([f"evt-v1-{SHA_A}"], [f"obs-v2-{SHA_B}"]),
        ([f"evt-v1-{SHA_A}"], ["obs-v1-short"]),
    ],
)
def test_v1_child_event_rejects_mixed_or_invalid_reference_ids(parents, triggers):
    with pytest.raises(ValueError):
        child_event_id("split", parents, triggers)


@pytest.mark.parametrize(
    ("parents", "children", "acquisition", "triggers", "algorithm"),
    [
        (
            [f"evt-v2-{SHA_A}"],
            [f"evt-v1-{SHA_B}"],
            f"acq-v1-{SHA_A}",
            [f"obs-v1-{SHA_A}"],
            "1.0.0",
        ),
        (
            ["evt-v1-short"],
            [f"evt-v1-{SHA_B}"],
            f"acq-v1-{SHA_A}",
            [f"obs-v1-{SHA_A}"],
            "1.0.0",
        ),
        (
            [f"evt-v1-{SHA_A}"],
            [f"evt-v2-{SHA_B}"],
            f"acq-v1-{SHA_A}",
            [f"obs-v1-{SHA_A}"],
            "1.0.0",
        ),
        (
            [f"evt-v1-{SHA_A}"],
            ["evt-v1-short"],
            f"acq-v1-{SHA_A}",
            [f"obs-v1-{SHA_A}"],
            "1.0.0",
        ),
        (
            [f"evt-v1-{SHA_A}"],
            [f"evt-v1-{SHA_B}"],
            f"acq-v2-{SHA_A}",
            [f"obs-v1-{SHA_A}"],
            "1.0.0",
        ),
        (
            [f"evt-v1-{SHA_A}"],
            [f"evt-v1-{SHA_B}"],
            "acq-v1-short",
            [f"obs-v1-{SHA_A}"],
            "1.0.0",
        ),
        (
            [f"evt-v1-{SHA_A}"],
            [f"evt-v1-{SHA_B}"],
            f"acq-v1-{SHA_A}",
            [f"obs-v2-{SHA_A}"],
            "1.0.0",
        ),
        (
            [f"evt-v1-{SHA_A}"],
            [f"evt-v1-{SHA_B}"],
            f"acq-v1-{SHA_A}",
            ["obs-v1-short"],
            "1.0.0",
        ),
    ],
)
def test_v1_lineage_rejects_mixed_major_references(
    parents, children, acquisition, triggers, algorithm
):
    with pytest.raises(ValueError):
        lineage_id(
            relation="split",
            parent_event_ids=parents,
            child_event_ids=children,
            acquisition_id=acquisition,
            observed_on="2026-04-07",
            trigger_observation_ids=triggers,
            algorithm_version=algorithm,
        )


@pytest.mark.parametrize(
    ("event_id", "acquisition_id"),
    [
        (f"evt-v2-{SHA_A}", f"acq-v1-{SHA_B}"),
        ("evt-v1-short", f"acq-v1-{SHA_B}"),
        (f"evt-v1-{SHA_A}", f"acq-v2-{SHA_B}"),
        (f"evt-v1-{SHA_A}", "acq-v1-short"),
    ],
)
def test_v1_contribution_key_rejects_mixed_or_invalid_reference_ids(
    event_id, acquisition_id
):
    with pytest.raises(ValueError):
        contribution_key(event_id, acquisition_id)
