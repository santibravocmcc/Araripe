"""The green automation heartbeat (GREEN_HEARTBEAT_CONTRACT_V1.md).

Four properties carry it, and each is proven here rather than argued:

* every combination of job results maps to an outcome the schema accepts —
  a heartbeat that refused an unforeseen combination would leave the previous
  beat standing, which reads as "nothing happened";
* the merge is commutative, so a lost compare-and-swap may re-read and
  re-merge instead of refusing;
* ``last_success`` survives failures;
* the writer writes one key, by compare-and-swap, and refuses — never
  replaces — a stored document that breaks the contract.
"""

from __future__ import annotations

import ast
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.publication import conditional_store as cs
from src.publication import delivery_boundary as db
from src.publication import heartbeat as hb
from tests.fake_object_store import FakeS3

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "write_green_heartbeat.py"
SCHEMA = ROOT / "docs/contracts/phase2b/schemas/green-heartbeat-v1.schema.json"
REPO = "santibravocmcc/Araripe"


def at(day, hour=6, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)


def beat(outcome, stage=None, *, run, when):
    return hb.attempt(outcome, stage, run_number=str(run), repository=REPO, now=when)


OK = beat(hb.DEPOSITED, run=101, when=at(1))
QUIET = beat(hb.NOTHING_TO_DO, run=102, when=at(2))
EMPTY = beat(hb.NO_ACQUISITION, run=103, when=at(3))
BROKE = beat(hb.FAILED, hb.DETECT, run=104, when=at(4))
STOPPED = beat(hb.CANCELLED, hb.DEPOSIT, run=105, when=at(5))


def store_with(document=None):
    fake = FakeS3()
    if document is not None:
        fake.objects[db.HEARTBEAT_KEY] = (hb.serialise(document), hb.CONTENT_TYPE)
    return fake, cs.ConditionalStore(fake, cs.STAGING_BUCKET)


# ── which job results mean which outcome ─────────────────────────────────────


@pytest.mark.parametrize(
    "detect, deposit, proceed, will_deposit, expected",
    [
        ("success", "success", "true", "true", (hb.DEPOSITED, None)),
        ("success", "skipped", "false", "", (hb.NOTHING_TO_DO, None)),
        ("success", "skipped", "true", "false", (hb.NO_ACQUISITION, None)),
        ("failure", "skipped", "true", "", (hb.FAILED, hb.DETECT)),
        ("failure", "skipped", "", "", (hb.FAILED, hb.DETECT)),
        ("cancelled", "skipped", "true", "", (hb.CANCELLED, hb.DETECT)),
        ("success", "failure", "true", "true", (hb.FAILED, hb.DEPOSIT)),
        ("success", "cancelled", "true", "true", (hb.CANCELLED, hb.DEPOSIT)),
        # Combinations the lane does not produce: recorded, never dropped.
        ("success", "skipped", "true", "true", (hb.FAILED, hb.DEPOSIT)),
        ("success", "skipped", "", "", (hb.FAILED, hb.DETECT)),
        ("success", "skipped", "true", "", (hb.FAILED, hb.DETECT)),
        ("skipped", "skipped", "", "", (hb.FAILED, hb.DETECT)),
    ],
)
def test_each_lane_ending_maps_to_one_outcome(detect, deposit, proceed, will_deposit, expected):
    assert hb.classify_outcome(
        detect=detect, deposit=deposit, proceed=proceed, will_deposit=will_deposit
    ) == expected


def test_every_combination_is_recorded_and_the_schema_accepts_it():
    """Totality: the table is the contract, and nothing falls off its edge."""

    results = ("success", "failure", "cancelled", "skipped", "")
    flags = ("true", "false", "")
    for detect, deposit, proceed, will in itertools.product(results, results, flags, flags):
        outcome, stage = hb.classify_outcome(
            detect=detect, deposit=deposit, proceed=proceed, will_deposit=will)
        hb.check_heartbeat(hb.merge(None, beat(outcome, stage, run=7, when=at(1))))


def test_a_success_needs_a_successful_detection():
    """A deposit job that reports success after a failed detection is not one."""

    assert hb.classify_outcome(
        detect="failure", deposit="success", proceed="true", will_deposit="true"
    ) == (hb.FAILED, hb.DETECT)


# ── the attempt and the merge ────────────────────────────────────────────────


def test_an_attempt_names_its_run_and_nothing_else():
    assert OK == {
        "outcome": "deposited",
        "stage": None,
        "finished_utc": "2026-10-01T06:00:00Z",
        "run_id": "ci-101",
        "run_url": "https://github.com/santibravocmcc/Araripe/actions/runs/101",
    }


def test_the_first_beat_of_a_failure_has_no_success_to_carry():
    document = hb.merge(None, BROKE)
    assert document == {"schema": hb.SCHEMA, "lane": "deposit", "latest": BROKE,
                         "last_success": None}
    hb.check_heartbeat(document)


def test_last_success_is_carried_forward_across_failures():
    document = hb.merge(hb.merge(hb.merge(None, OK), BROKE), STOPPED)
    assert document["latest"] == STOPPED
    assert document["last_success"] == OK
    hb.check_heartbeat(document)


@pytest.mark.parametrize("success", [OK, QUIET, EMPTY])
def test_each_success_becomes_the_last_success(success):
    document = hb.merge(hb.merge(None, BROKE), success | {"finished_utc": "2026-10-09T06:00:00Z"})
    assert document["latest"] == document["last_success"]


def test_the_merge_is_commutative_over_every_order():
    """Whoever wins the race, the stored document is the same."""

    attempts = [OK, QUIET, EMPTY, BROKE, STOPPED]
    results = set()
    for order in itertools.permutations(attempts):
        document = None
        for item in order:
            document = hb.merge(document, item)
        hb.check_heartbeat(document)
        results.add(hb.serialise(document))
    assert len(results) == 1
    (only,) = results
    assert json.loads(only)["latest"] == STOPPED
    assert json.loads(only)["last_success"] == EMPTY


def test_an_older_attempt_finishing_into_a_newer_beat_changes_nothing():
    newer = hb.merge(None, QUIET)
    assert hb.merge(newer, OK) == newer


def test_two_attempts_in_the_same_second_are_ordered_by_run_number_numerically():
    nine = beat(hb.FAILED, hb.DETECT, run=9, when=at(1))
    ten = beat(hb.FAILED, hb.DETECT, run=10, when=at(1))
    assert hb.merge(hb.merge(None, ten), nine)["latest"] == ten
    assert hb.merge(hb.merge(None, nine), ten)["latest"] == ten


# ── the contract, read back ──────────────────────────────────────────────────


def _codes(document):
    with pytest.raises(hb.HeartbeatRejected) as excinfo:
        hb.check_heartbeat(document)
    return set(excinfo.value.codes)


def test_a_success_finishing_after_the_latest_is_refused():
    document = hb.merge(None, BROKE)
    document["last_success"] = OK | {"finished_utc": "2026-10-30T00:00:00Z"}
    assert "last_success_after_latest" in _codes(document)


def test_a_successful_latest_that_is_not_the_last_success_is_refused():
    document = hb.merge(hb.merge(None, OK), QUIET)
    document["last_success"] = OK
    assert _codes(document) == {"successful_latest_is_not_last_success"}


def test_a_run_url_naming_another_run_is_refused():
    document = hb.merge(None, BROKE)
    document["latest"] = BROKE | {"run_url": "https://github.com/x/y/actions/runs/999"}
    assert _codes(document) == {"run_url_names_another_run"}


@pytest.mark.parametrize(
    "patch",
    [
        {"stage": "detect"},                       # a success with a stage
        {"outcome": "failed"},                     # a failure without one
        {"outcome": "promoted"},                   # not an outcome
        {"run_id": "ci-0"},
        {"run_id": "36500000001"},
        {"finished_utc": "2026-10-01 06:00:00"},
        {"release_id": "rel-g3-" + "0" * 64},      # names a release
        {"window": {"start": "2026-09-28"}},       # names a window
    ],
)
def test_the_schema_refuses_a_malformed_attempt(patch):
    document = hb.merge(None, OK)
    document["latest"] = OK | patch
    document["last_success"] = document["latest"]
    assert "schema" in _codes(document)


def test_a_failure_cannot_be_the_last_success():
    document = hb.merge(None, BROKE)
    document["last_success"] = BROKE
    assert "schema" in _codes(document)


def test_the_document_carries_no_release_window_or_count():
    """GREEN_HEARTBEAT_CONTRACT_V1.md §4, pinned on the schema's own names."""

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert set(schema["properties"]) == {"schema", "lane", "latest", "last_success"}
    assert set(schema["$defs"]["attempt"]["properties"]) == {
        "outcome", "stage", "finished_utc", "run_id", "run_url"}
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["attempt"]["additionalProperties"] is False
    assert schema["properties"]["schema"]["const"] == hb.SCHEMA == db.HEARTBEAT_SCHEMA


def test_the_outcomes_in_the_schema_are_the_modules():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert set(schema["$defs"]["success"]["enum"]) == hb.SUCCESSES
    assert set(schema["$defs"]["attempt"]["properties"]["outcome"]["enum"]) == (
        hb.SUCCESSES | {hb.FAILED, hb.CANCELLED})


# ── the write ────────────────────────────────────────────────────────────────


def test_the_first_beat_is_created_with_if_none_match():
    fake, store = store_with()
    recorded = hb.record(store, BROKE)
    assert (recorded.result, recorded.tries) == ("created", 1)
    assert fake.writes == [(db.HEARTBEAT_KEY, "application/json")]
    assert json.loads(fake.body(db.HEARTBEAT_KEY)) == hb.merge(None, BROKE)


def test_a_later_beat_replaces_by_if_match_and_carries_the_success():
    fake, store = store_with(hb.merge(None, OK))
    recorded = hb.record(store, BROKE)
    assert recorded.result == "replaced"
    stored = json.loads(fake.body(db.HEARTBEAT_KEY))
    assert stored["latest"] == BROKE and stored["last_success"] == OK


def test_the_same_beat_twice_writes_nothing_the_second_time():
    fake, store = store_with()
    hb.record(store, OK)
    assert hb.record(store, OK).result == "unchanged"
    assert len(fake.writes) == 1


def test_only_the_heartbeat_key_is_ever_written():
    fake, store = store_with()
    for item in (OK, BROKE, QUIET, STOPPED):
        hb.record(store, item)
    assert {key for key, _ in fake.writes} == {db.HEARTBEAT_KEY}
    assert fake.keys() == [db.HEARTBEAT_KEY]


class RacingS3(FakeS3):
    """Another lane writes its beat between this one's read and its write."""

    def __init__(self, rival, races=1, **kwargs):
        super().__init__(**kwargs)
        self.rival = rival
        self.races = races

    def put_object(self, Bucket, Key, Body, **kwargs):
        if self.races:
            self.races -= 1
            stored = self.objects.get(Key)
            current = json.loads(stored[0]) if stored else None
            rival = self.rival(current)
            self.objects[Key] = (hb.serialise(hb.merge(current, rival)), hb.CONTENT_TYPE)
        return super().put_object(Bucket, Key, Body, **kwargs)


@pytest.mark.parametrize("seeded", [False, True])
def test_a_lost_race_is_re_read_and_re_merged_and_both_beats_survive(seeded):
    fake = RacingS3(lambda current: QUIET)
    if seeded:
        fake.objects[db.HEARTBEAT_KEY] = (hb.serialise(hb.merge(None, OK)), hb.CONTENT_TYPE)
    recorded = hb.record(cs.ConditionalStore(fake, cs.STAGING_BUCKET), BROKE)
    assert recorded.tries == 2
    stored = json.loads(fake.body(db.HEARTBEAT_KEY))
    assert stored["latest"] == BROKE          # the later finish
    assert stored["last_success"] == QUIET    # the rival's success, not lost
    expected = hb.merge(hb.merge(hb.merge(None, OK) if seeded else None, QUIET), BROKE)
    assert stored == expected


def test_a_writer_that_never_wins_gives_up_and_overwrites_nothing():
    rivals = iter(beat(hb.FAILED, hb.DETECT, run=200 + n, when=at(9, minute=n)) for n in range(50))
    fake = RacingS3(lambda current: next(rivals), races=hb.MAX_TRIES)
    with pytest.raises(cs.ObjectStoreError, match="compare-and-swap"):
        hb.record(cs.ConditionalStore(fake, cs.STAGING_BUCKET), OK)
    stored = json.loads(fake.body(db.HEARTBEAT_KEY))
    assert OK not in (stored["latest"], stored["last_success"])
    assert fake.writes == []


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        json.dumps({"schema": "araripe.green.heartbeat/2"}).encode(),
        json.dumps({"schema": "araripe.green.pointer/2", "sequence": 17}).encode(),
    ],
)
def test_a_stored_document_that_breaks_the_contract_is_refused_not_replaced(body):
    fake = FakeS3({db.HEARTBEAT_KEY: (body, "application/json")})
    with pytest.raises(hb.HeartbeatRejected):
        hb.record(cs.ConditionalStore(fake, cs.STAGING_BUCKET), BROKE)
    assert fake.writes == [] and fake.body(db.HEARTBEAT_KEY) == body


def test_a_failed_read_is_not_absence():
    class Unreadable(FakeS3):
        def get_object(self, Bucket, Key):
            from tests.fake_object_store import client_error
            raise client_error("AccessDenied", "GetObject", 403)

    fake = Unreadable()
    with pytest.raises(cs.ObjectStoreError):
        hb.record(cs.ConditionalStore(fake, cs.STAGING_BUCKET), BROKE)
    assert fake.writes == []


# ── the script the lane runs ─────────────────────────────────────────────────


def _load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("write_green_heartbeat", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LANE_ENV = {
    "R2_STAGING_BUCKET": cs.STAGING_BUCKET,
    "R2_ENDPOINT_URL": cs.STAGING_ENDPOINT,
    "R2_STAGING_ACCESS_KEY_ID": "test-key",
    "R2_STAGING_SECRET_ACCESS_KEY": "test-secret",
    "GITHUB_RUN_ID": "36500000009",
    "GITHUB_REPOSITORY": REPO,
    "GITHUB_SERVER_URL": "https://github.com",
}


def test_the_script_records_a_failed_detection_end_to_end(monkeypatch):
    script = _load_script()
    fake = FakeS3()
    seen = {}

    def build_client(bucket, endpoint, credentials, **kwargs):
        cs.assert_staging_target(bucket, endpoint)
        seen.update(kwargs)
        return fake

    monkeypatch.setattr(cs, "build_client", build_client)
    env = LANE_ENV | {"DETECT_RESULT": "failure", "DEPOSIT_RESULT": "skipped",
                      "PROCEED": "", "WILL_DEPOSIT": ""}
    assert script.main(env) == 0
    stored = json.loads(fake.body(db.HEARTBEAT_KEY))
    assert stored["latest"]["outcome"] == "failed" and stored["latest"]["stage"] == "detect"
    assert stored["latest"]["run_id"] == "ci-36500000009"
    assert stored["latest"]["run_url"].endswith("/santibravocmcc/Araripe/actions/runs/36500000009")
    assert seen == {}, "the lane's writer never opts into the local profile"


@pytest.mark.parametrize(
    "patch",
    [
        {"R2_STAGING_BUCKET": "araripe-cogs"},
        {"R2_ENDPOINT_URL": "https://example.r2.cloudflarestorage.com"},
        {"R2_STAGING_SECRET_ACCESS_KEY": ""},
        {"GITHUB_RUN_ID": ""},
    ],
)
def test_the_script_fails_closed_before_writing(patch, monkeypatch):
    script = _load_script()
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    env = LANE_ENV | {"DETECT_RESULT": "success", "DEPOSIT_RESULT": "success",
                      "PROCEED": "true", "WILL_DEPOSIT": "true"} | patch
    fake = FakeS3()
    # The real build_client, so its refusals are the ones exercised — but
    # boto3 stubbed: a real client would create boto3's process-wide default
    # session, and a later test's AWS_PROFILE would then resolve against it.
    import boto3

    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: fake)
    monkeypatch.setattr(cs, "require_conditional_write_support", lambda client: None)
    assert script.main(env) == 1
    assert fake.writes == []


def test_the_script_does_not_opt_into_the_profile_or_name_another_identity():
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "build_client":
            assert not any(k.arg == "profile_fallback" for k in node.keywords)
    assert "R2_PROMOTION" not in source
    assert "ReadOnlyStore" not in source
