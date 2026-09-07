"""Concurrency lanes and blue-lane guards for the workflows (Package 2B.1).

`detect_gee.yml` declared no `concurrency:` at all, so two overlapping runs —
a manual dispatch during a scheduled run, or a re-run — could interleave their
read-modify-write of the SAME R2 persistence state. Detection is not idempotent
(a re-run inflates `n_sightings`), so serializing the blue lane is a safety
property, not a tidiness one.

`update_data.yml` touches the same object, so the two share ONE group: separate
groups would serialize each file against itself and still let them interleave.

The green lanes installed by Package 2B.0 must stay distinct from that group,
so a long green replay can never queue behind — or block — a blue schedule.
See `docs/operations/GREEN_CONCURRENCY_LANES.md`.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"

LEGACY_STATE_GROUP = "araripe-legacy-state"
# Workflows that read-modify-write the blue persistence state in `araripe-cogs`.
LEGACY_STATE_WORKFLOWS = ("detect_gee.yml", "update_data.yml")
GREEN_GROUPS = {
    "v2_candidate_replay.yml": "araripe-green-candidate",
    "v2_promotion_lane.yml": "araripe-green-promotion",
    # The identity probe carries the promotion credential but touches no shared
    # object -- it never writes the real pointer -- so it gets its own group
    # rather than queueing behind, or delaying, a real promotion.
    "v2_promotion_identity_probe.yml": "araripe-green-promotion-probe",
    "cloudflare_green_control.yml": "araripe-cloudflare-green-control",
}
# The blue detection cadence is load-bearing (ROADMAP.md §6); pin it so a
# schedule change has to be deliberate.
BLUE_DETECTION_CRON = "0 6 * * 1,4"


def load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text())


def steps(doc):
    return [s for job in doc["jobs"].values() for s in job["steps"]]


def all_workflows():
    return sorted(p.name for p in WORKFLOWS.glob("*.yml"))


# ─── the blue state lane ─────────────────────────────────────────────────────

@pytest.mark.parametrize("name", LEGACY_STATE_WORKFLOWS)
def test_state_writers_share_one_serialized_group(name):
    concurrency = load(name).get("concurrency")
    assert concurrency is not None, f"{name} declares no concurrency lane"
    assert concurrency["group"] == LEGACY_STATE_GROUP
    assert concurrency["cancel-in-progress"] is False


def test_no_lane_cancels_a_run_in_progress():
    """Cancelling mid-run would leave alerts in R2 without their state update."""
    for name in all_workflows():
        concurrency = load(name).get("concurrency")
        if concurrency is not None:
            assert concurrency["cancel-in-progress"] is False, name


# ─── lane distinctness: green must never block blue ──────────────────────────

@pytest.mark.parametrize("name, group", sorted(GREEN_GROUPS.items()))
def test_green_lanes_keep_their_own_groups(name, group):
    assert load(name)["concurrency"]["group"] == group


def test_green_groups_are_distinct_from_the_blue_group():
    assert LEGACY_STATE_GROUP not in set(GREEN_GROUPS.values())


def test_every_declared_group_is_unique_to_its_lane():
    """A long green replay must not queue behind, or block, a blue schedule."""
    seen = {}
    for name in all_workflows():
        concurrency = load(name).get("concurrency")
        if concurrency is None:
            continue
        seen.setdefault(concurrency["group"], []).append(name)
    assert seen[LEGACY_STATE_GROUP] == list(LEGACY_STATE_WORKFLOWS)
    for group, members in seen.items():
        if group != LEGACY_STATE_GROUP:
            assert len(members) == 1, f"{group} is shared by {members}"


def test_green_lanes_cannot_inherit_a_schedule():
    """Inertness of the green route (Package 2B.0) still holds."""
    for name in GREEN_GROUPS:
        assert "schedule" not in load(name)[True], name


# ─── blue-lane guards ────────────────────────────────────────────────────────

def test_blue_detection_schedule_is_unchanged():
    # `on` parses as the boolean True in YAML 1.1 — hence the `[True]` key.
    crons = [c["cron"] for c in load("detect_gee.yml")[True]["schedule"]]
    assert crons == [BLUE_DETECTION_CRON]


def test_the_manual_fallback_has_no_schedule():
    """Only one detection path may run automatically."""
    assert "schedule" not in load("update_data.yml")[True]


@pytest.mark.parametrize("name", LEGACY_STATE_WORKFLOWS)
def test_state_fetch_requires_the_object_to_exist(name):
    """An absent state is a deletion here, never a first run."""
    fetch = [s for s in steps(load(name)) if "r2_state.py get" in s.get("run", "")]
    assert len(fetch) == 1, name
    assert "--require-existing" in fetch[0]["run"]


@pytest.mark.parametrize("name", LEGACY_STATE_WORKFLOWS)
def test_the_release_signal_is_written_before_publication(name):
    """The signal must land in the same commit as the DB it describes."""
    names = [s.get("name", "") for s in steps(load(name))]
    signal = names.index("Write the time-series release signal")
    publish = names.index("Publish time-series DB through a pull request")
    assert signal < publish


@pytest.mark.parametrize("name", LEGACY_STATE_WORKFLOWS)
def test_publication_still_goes_through_a_pull_request(name):
    """`main` is ruleset-protected: never restore a direct push (ROADMAP.md §6)."""
    publish = [s for s in steps(load(name))
               if s.get("name") == "Publish time-series DB through a pull request"]
    assert len(publish) == 1
    run = publish[0]["run"]
    assert "gh pr create" in run and "gh pr merge" in run
    assert "git push origin HEAD:refs/heads/main" not in run
