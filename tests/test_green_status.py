"""The status of every green product (PHASE_6Y_2026-10-10.md).

What carries it, each proven here rather than argued:

* ages come from the data — the last date with a product, the last date looked
  at — and never from an object's stamp (``max_terminal_at``, ``promoted_utc``);
* whether a context or a sources document is current is what
  ``delivery_boundary.resolve`` answers, so the status and the route agree;
* only the two ages the owner limited are judged (attempt 5 d, date looked at
  21 d, PHASE_6Y §4); a late product fails the script;
* only facts fail: an unreadable document, a refused chain, a route refusal
  that is not "a lane has not caught up";
* the script reads with the candidate identity, through ``ReadOnlyStore``,
  without the local profile, and the lane that runs it writes nothing.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from src.publication import conditional_store as cs
from src.publication import delivery_boundary as db
from src.publication import green_context as gc
from src.publication import green_sources as gs
from src.publication import green_status as st
from src.publication import heartbeat as hb
from src.publication import state_chain as sc
from src.publication.findings import Finding
from src.publication.run_inputs import ReadOnlyStore

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "green_status.py"
LANE = REPO / ".github" / "workflows" / "v2_green_status.yml"

NOW = datetime(2026, 10, 10, 14, 0, 0, tzinfo=timezone.utc)
RELEASE_ID = "rel-g3-" + "a" * 64
OLD_RELEASE_ID = "rel-g3-" + "b" * 64
CONTEXT_ID = "ctx-g1-" + "c" * 64
OLD_CONTEXT_ID = "ctx-g1-" + "d" * 64
SOURCES_ID = "src-g1-" + "e" * 64


def _date(day, paths, terminal="2026-10-07T21:12:30Z"):
    return {"observed_on": day, "paths": paths, "max_terminal_at": terminal}


def release(dates=None):
    dates = dates if dates is not None else [
        _date("2026-09-29", ["alerts/run-2026-09-29.geojson"]),
        _date("2026-10-01", ["alerts/run-2026-10-01.geojson"]),
        _date("2026-10-02", []),
    ]
    return {
        "schema": "araripe.green.release/3",
        "release_id": RELEASE_ID,
        "release_prefix": f"releases/{RELEASE_ID}/",
        "coverage": {"first_observed_on": dates[0]["observed_on"],
                     "last_observed_on": dates[-1]["observed_on"]},
        "dates": dates,
        "objects": [],
    }


def pointer(release_id=RELEASE_ID, through="2026-10-02"):
    return {
        "schema": "araripe.green.pointer/2",
        "sequence": 18,
        "release_id": release_id,
        "promoted_utc": "2026-10-09T21:41:14Z",
        "state_watermark": {"finalized_through": through},
        "coverage": {"last_observed_on": through},
    }


def attempt(outcome, when, run="ci-37688510058", stage=None):
    return {"outcome": outcome, "stage": stage, "finished_utc": when, "run_id": run,
            "run_url": f"https://github.com/santibravocmcc/Araripe/actions/runs/{run[3:]}"}


def heartbeat(latest=None, last_success="same"):
    latest = latest or attempt("no_acquisition", "2026-10-07T21:19:55Z")
    return {"schema": hb.SCHEMA, "lane": "deposit", "latest": latest,
            "last_success": latest if last_success == "same" else last_success}


def context_pointer(release_id=RELEASE_ID, context_id=CONTEXT_ID):
    return {"schema": gc.CONTEXT_POINTER_SCHEMA, "release_id": release_id, "context_id": context_id,
            "sequence": 2, "written_utc": "2026-10-07T22:04:46Z",
            "context_path": f"contexts/{context_id}/context.json", "context_document_sha256": "0" * 64}


def context(release_id=RELEASE_ID, context_id=CONTEXT_ID):
    return {"schema": gc.CONTEXT_SCHEMA, "release_id": release_id, "context_id": context_id, "objects": []}


def sources_pointer(release_id=RELEASE_ID, context_id=CONTEXT_ID):
    return {"schema": gs.SOURCES_POINTER_SCHEMA, "release_id": release_id, "context_id": context_id,
            "sources_id": SOURCES_ID, "sequence": 1, "written_utc": "2026-10-10T13:49:17Z",
            "sources_path": f"sources/{SOURCES_ID}/sources.json", "sources_document_sha256": "f" * 64}


def sources(release_id=RELEASE_ID, context_id=CONTEXT_ID):
    return {"schema": gs.SOURCES_SCHEMA, "sources_id": SOURCES_ID, "release_id": release_id,
            "context_id": context_id}


def reading(**changes):
    base = st.Reading(
        pointer=pointer(), release=release(), heartbeat=heartbeat(),
        context_pointer=context_pointer(), context=context(),
        sources_pointer=sources_pointer(), sources=sources(),
        head=st.Head("ci-37686447368", "2026-10-02"),
    )
    return replace(base, **changes)


def rows_by_product(r):
    return {row.product: row for row in st.assess(r, NOW)}


# ── the reading ──────────────────────────────────────────────────────────────


def test_everything_live_is_ok_with_one_row_per_product_in_a_fixed_order():
    rows = st.assess(reading(), NOW)
    assert not st.late(rows)
    assert [row.product for row in rows] == [
        "alerts.shown", "alerts.observed", "deposits.unpublished",
        "automation.latest", "automation.last_success", "context", "sources",
    ]
    assert {row.state for row in rows} == {st.OK}
    assert not st.broken(rows)


def test_the_shown_date_is_the_last_with_a_product_and_the_observed_date_counts_refusals():
    """Mutation killed: reading ``coverage.last_observed_on`` for what the page shows."""

    rows = rows_by_product(reading())
    assert (rows["alerts.shown"].since, rows["alerts.shown"].age_days) == ("2026-10-01", 9)
    assert (rows["alerts.observed"].since, rows["alerts.observed"].age_days) == ("2026-10-02", 8)


def test_an_age_never_comes_from_an_objects_stamp():
    """Every live date carries max_terminal_at 2026-10-07 (the series was rebuilt);
    a January date must read as months old, not three days."""

    old = release([_date("2026-01-15", ["alerts/run-2026-01-15.geojson"], terminal="2026-10-09T23:00:00Z")])
    rows = rows_by_product(reading(release=old, pointer=pointer(through="2026-01-15"),
                                   head=st.Head("ci-1", "2026-01-15")))
    assert rows["alerts.shown"].age_days == 268
    assert rows["alerts.observed"].age_days == 268


def test_only_the_two_limited_ages_are_judged():
    """The owner's limits (PHASE_6Y §4, 2026-10-10): attempt 5 d, date looked at
    21 d. The date shown and the instants of last_success stay unjudged."""

    old = release([_date("2025-01-01", ["alerts/run-2025-01-01.geojson"])])
    stale_beat = heartbeat(attempt("deposited", "2025-01-02T06:00:00Z"))
    rows = rows_by_product(reading(release=old, pointer=pointer(through="2025-01-01"), heartbeat=stale_beat,
                                   head=st.Head("ci-1", "2025-01-01")))
    late = {p for p, r in rows.items() if r.state == st.LATE}
    assert late == {"automation.latest", "alerts.observed"}
    assert rows["alerts.shown"].state == st.OK and rows["automation.last_success"].state == st.OK
    assert "past the owner's limit of 5" in rows["automation.latest"].detail


@pytest.mark.parametrize("product, field, ok_age", [("automation.latest", "beat", 5),
                                                     ("alerts.observed", "observed", 21)])
def test_a_limit_is_strictly_more_than_its_days(product, field, ok_age):
    from datetime import timedelta

    def at(age):
        day = (NOW - timedelta(days=age))
        if field == "beat":
            return reading(heartbeat=heartbeat(attempt("no_acquisition", day.strftime(st.STAMP))))
        d = day.date().isoformat()
        return reading(release=release([_date(d, [])]), pointer=pointer(through=d), head=st.Head("ci-1", d))

    assert rows_by_product(at(ok_age))[product].state == st.OK
    assert rows_by_product(at(ok_age + 1))[product].state == st.LATE


def test_the_limits_are_exactly_the_owners():
    assert st.LIMITS_DAYS == {"automation.latest": 5, "alerts.observed": 21}


def test_a_release_with_no_product_says_so_without_a_date():
    rows = rows_by_product(reading(release=release([_date("2026-10-02", [])])))
    assert rows["alerts.shown"].since is None and rows["alerts.shown"].state == st.OK


def test_instant_ages_are_whole_days_floored():
    rows = rows_by_product(reading(heartbeat=heartbeat(attempt("no_acquisition", "2026-10-07T14:00:01Z"))))
    assert rows["automation.latest"].age_days == 2
    rows = rows_by_product(reading(heartbeat=heartbeat(attempt("no_acquisition", "2026-10-07T14:00:00Z"))))
    assert rows["automation.latest"].age_days == 3


def test_a_failed_latest_keeps_the_last_success_apart():
    failed = attempt("failed", "2026-10-09T06:10:00Z", run="ci-2", stage="detect")
    success = attempt("deposited", "2026-10-06T06:10:00Z", run="ci-1")
    rows = rows_by_product(reading(heartbeat=heartbeat(failed, success)))
    assert rows["automation.latest"].detail.startswith("failed at detect, ci-2")
    assert rows["automation.last_success"].since == "2026-10-06T06:10:00Z"
    rows = rows_by_product(reading(heartbeat=heartbeat(failed, None)))
    assert rows["automation.last_success"].state == st.ABSENT


# ── the queue between the deposit and the pointer ───────────────────────────


@pytest.mark.parametrize("covers, state", [
    ("2026-10-02", st.OK),
    ("2026-10-06", st.PENDING),
    # A new generation grows from its own root while the pointer names the old
    # one: nothing promises the head is never behind, so it is not broken.
    ("2026-04-15", st.PENDING),
])
def test_the_queue_compares_the_head_with_the_pointers_watermark(covers, state):
    row = rows_by_product(reading(head=st.Head("ci-9", covers)))["deposits.unpublished"]
    assert row.state == state and row.since == covers


def test_a_refused_chain_is_broken_and_a_missing_one_absent():
    rows = rows_by_product(reading(head=st.Unreadable("chain_forked")))
    assert rows["deposits.unpublished"].state == st.BROKEN
    assert rows_by_product(reading(head=None))["deposits.unpublished"].state == st.ABSENT


# ── context and sources: the route's own answer ─────────────────────────────


def test_a_context_for_an_earlier_release_is_pending_exactly_as_the_route_refuses_it():
    row = rows_by_product(reading(context_pointer=context_pointer(OLD_RELEASE_ID), context=None))["context"]
    assert row.state == st.PENDING and "context_not_live" in row.detail


def test_sources_wait_when_the_context_moved_after_them():
    """The sources name the old context; the route answers sources_not_live."""

    rows = rows_by_product(reading(sources_pointer=sources_pointer(context_id=OLD_CONTEXT_ID), sources=None))
    assert rows["context"].state == st.OK
    assert rows["sources"].state == st.PENDING and "sources_not_live" in rows["sources"].detail


def test_never_published_is_absent():
    rows = rows_by_product(reading(context_pointer=None, context=None, sources_pointer=None, sources=None))
    assert rows["context"].state == st.ABSENT and "context_absent" in rows["context"].detail
    assert rows["sources"].state == st.ABSENT and "sources_absent" in rows["sources"].detail


def test_a_document_that_is_not_the_one_its_pointer_names_is_broken():
    rows = rows_by_product(reading(context=context(context_id=OLD_CONTEXT_ID)))
    assert rows["context"].state == st.BROKEN and "context_document_mismatch" in rows["context"].detail


def test_the_status_calls_the_route_rather_than_restating_it(monkeypatch):
    """Mutation killed: a private copy of the comparison would not see this."""

    seen = []
    real = db.resolve

    def spy(method, url, **kwargs):
        seen.append(url)
        return real(method, url, **kwargs)

    monkeypatch.setattr(db, "resolve", spy)
    st.assess(reading(), NOW)
    assert seen == ["/data/green/context/context.json", "/data/green/sources.json"]


def test_an_unreadable_context_pointer_breaks_both_and_unreadable_sources_only_sources():
    rows = rows_by_product(reading(context_pointer=st.Unreadable("not JSON")))
    assert rows["context"].state == rows["sources"].state == st.BROKEN
    rows = rows_by_product(reading(sources=st.Unreadable("sha256 differs")))
    assert rows["context"].state == st.OK and rows["sources"].state == st.BROKEN


# ── nothing published, or nothing readable ──────────────────────────────────


def test_before_any_promotion_everything_but_the_automation_is_absent():
    rows = st.assess(reading(pointer=None, release=None, context_pointer=None, context=None,
                             sources_pointer=None, sources=None, head=None), NOW)
    states = {row.product: row.state for row in rows}
    assert states.pop("automation.latest") == states.pop("automation.last_success") == st.OK
    assert set(states.values()) == {st.ABSENT}
    assert not st.broken(rows)


@pytest.mark.parametrize("field", ["pointer", "release", "heartbeat"])
def test_an_unreadable_owner_is_broken(field):
    rows = st.assess(reading(**{field: st.Unreadable("refused")}), NOW)
    assert st.broken(rows)


def test_the_markdown_escapes_a_pipe_in_a_detail():
    rows = [st.Row("x", st.OK, None, None, "a | b")]
    assert "a \\| b" in st.as_markdown(rows, NOW)


# ── the script ───────────────────────────────────────────────────────────────


def _script():
    spec = importlib.util.spec_from_file_location("green_status_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


@pytest.fixture()
def live():
    """A promoted version-1 release, its heartbeat, its context and its sources."""

    from tests.test_chain_release import store_with_live_root
    from tests.test_green_sources import _context_for

    store, fake, _members, _bodies = store_with_live_root()
    from src.publication import atomic_publish as ap

    live_pointer, _ = ap.read_pointer(store)
    live_release = json.loads(fake.body(live_pointer["release_path"]))

    def put(key, document):
        body = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        fake.objects[key] = (body, "application/json")
        return _sha(body)

    put(db.HEARTBEAT_KEY, heartbeat(attempt("no_acquisition", "2026-04-16T06:00:00Z")))
    ctx = _context_for(live_release)
    digest = put(ctx["context_prefix"] + gc.CONTEXT_DOCUMENT_NAME, ctx)
    put(gc.CONTEXT_CURRENT_KEY, gc.pointer_document(
        context=ctx, context_document_sha256=digest, sequence=1,
        written_utc="2026-10-09T00:00:00Z", written_by={}))
    doc = sources(live_release["release_id"], ctx["context_id"])
    digest = put(f"sources/{SOURCES_ID}/sources.json", doc)
    put(gs.SOURCES_CURRENT_KEY, sources_pointer(live_release["release_id"], ctx["context_id"])
        | {"sources_document_sha256": digest})
    return fake


#: The fixture chain covers April 2026, so its reading happens then.
LIVE_NOW = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)


def _run(fake, tmp_path, monkeypatch):
    script = _script()
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    writes = len(fake.writes)
    code = script.main([], store=ReadOnlyStore(fake, cs.STAGING_BUCKET), now=LIVE_NOW)
    assert len(fake.writes) == writes, "the status writes nothing"
    return code, summary.read_text() if summary.exists() else ""


def test_the_script_reads_a_live_bucket_and_writes_the_summary(live, tmp_path, monkeypatch, capsys):
    code, summary = _run(live, tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert code == 0, out
    assert "| `context` | ok |" in summary and "| `sources` | ok |" in summary
    # No run prefix in this bucket: the chain root is absent, which is "absent".
    assert "| `deposits.unpublished` | absent |" in summary
    assert "read-only — nothing was written" in out


def test_a_live_release_whose_bytes_differ_from_the_pointers_digest_fails(live, tmp_path, monkeypatch):
    from src.publication import atomic_publish as ap

    key = json.loads(live.body(ap.POINTER_KEY))["release_path"]
    body, kind = live.objects[key]
    live.objects[key] = (body + b" ", kind)
    code, summary = _run(live, tmp_path, monkeypatch)
    assert code == 1 and "| `alerts.shown` | broken |" in summary


def test_sources_with_another_digest_are_broken_not_served(live, tmp_path, monkeypatch):
    key = f"sources/{SOURCES_ID}/sources.json"
    body, kind = live.objects[key]
    live.objects[key] = (body + b"\n", kind)
    code, summary = _run(live, tmp_path, monkeypatch)
    assert code == 1 and "| `sources` | broken |" in summary and "| `context` | ok |" in summary


def test_a_late_automation_fails_the_script(live, tmp_path, monkeypatch):
    late_now = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)
    script = _script()
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "s.md"))
    code = script.main([], store=ReadOnlyStore(live, cs.STAGING_BUCKET), now=late_now)
    assert code == 1 and "| `automation.latest` | late |" in (tmp_path / "s.md").read_text()


def test_a_forked_chain_fails_the_script(live, tmp_path, monkeypatch):
    def forked(store, root=sc.CHAIN_ROOT):
        raise sc.ChainRejected([Finding("chain_forked", "two children")])

    monkeypatch.setattr(sc, "resolve_head", forked)
    code, summary = _run(live, tmp_path, monkeypatch)
    assert code == 1 and "| `deposits.unpublished` | broken |" in summary


def test_the_script_reads_read_only_with_the_candidate_identity_and_no_profile():
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    names = {getattr(c.func, "attr", getattr(c.func, "id", "")) for c in calls}
    assert "ReadOnlyStore" in names and "ConditionalStore" not in names
    assert not names & {"put_if_absent", "put_if_match", "put_if_pointer_absent", "record", "move"}
    for call in calls:
        if getattr(call.func, "attr", "") == "build_client":
            assert not any(k.arg == "profile_fallback" for k in call.keywords)
    assert "R2_PROMOTION" not in source
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any((m or "").startswith("config") for m in imported)


# ── the lane ─────────────────────────────────────────────────────────────────


def _lane():
    return yaml.safe_load(LANE.read_text(encoding="utf-8"))


def test_the_lane_is_manual_unscheduled_read_only_and_joins_no_queue():
    d = _lane()
    assert set(d[True]) == {"workflow_dispatch"}, "no green lane has a cron before the cutover"
    assert d["permissions"] == {"contents": "read"}
    assert "concurrency" not in d
    assert list(d["jobs"]) == ["status"]
    job = d["jobs"]["status"]
    assert "concurrency" not in job
    assert job["environment"] == "v2-staging", "never name an Environment that does not exist"


def test_one_step_holds_only_the_candidate_key_and_runs_only_the_reader():
    job = _lane()["jobs"]["status"]
    holders = [s for s in job["steps"] if "secrets." in str(s.get("env") or {})]
    assert [s["name"] for s in holders] == ["Read every green product's status"]
    (step,) = holders
    assert set(step["env"]) == {"R2_STAGING_ACCESS_KEY_ID", "R2_STAGING_SECRET_ACCESS_KEY", "AWS_REGION"}
    assert step["run"].strip().splitlines()[-1] == "python3 scripts/green_status.py"
    assert job["steps"][0]["name"] == "Fail closed unless the target is exactly the approved staging bucket"
    text = LANE.read_text(encoding="utf-8")
    assert "R2_PROMOTION" not in text and "pointers/" not in text
