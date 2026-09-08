"""A least-privilege probe must fail when the privilege is there, not when it is not.

Package 2B.3: *introduce least-privilege credentials and step-level secret
exposure.*  On 2026-09-07 a promotion key with a perfect GitHub Environment
reached the **production** bucket, because the scope that mattered lived in
Cloudflare and is invisible from GitHub
(``docs/operations/GREEN_PROOFS_2026-09-07.md`` §2).  The lesson recorded there
is that credential scope is only ever proven by a call that must be refused —
and an inverted check with the polarity wrong is worse than no check, because
it reports PASS for exactly the breakage it exists to catch.

``tests/test_promotion_identity_probe.py`` pins that for isolation.  This file
pins it for privilege, in both directions and for both operations: a write and
a delete that **succeed** must fail a ``read-only`` probe, and the same probe
run with ``--expect read-write`` must read those successes as passes.

No network: the client is a stub and nothing reaches an object store.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from src.publication import conditional_store as cs
from src.publication.conditional_store import ConditionalStore
from tests.fake_object_store import FakeS3, client_error

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "probe_readonly_identity.py"
SPEC = importlib.util.spec_from_file_location("probe_readonly_identity", MODULE_PATH)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)

KEY = "readonly-identity-probe/run-test/write-attempt.json"
ABSENT = "readonly-identity-probe/run-test/never-created.json"


@pytest.fixture(autouse=True)
def clean_checks():
    probe.CHECKS.clear()
    yield
    probe.CHECKS.clear()


def only_check():
    assert len(probe.CHECKS) == 1
    return probe.CHECKS[0]


class DeniedStore(ConditionalStore):
    """A store whose writes are refused the way R2 refuses a read-only token."""

    def put_if_absent(self, key, body, content_type):
        raise cs.ObjectStoreError("denied") from client_error(
            "AccessDenied", "PutObject", 403
        )


class DeletingClient:
    """A client whose delete succeeds and whose head reports absence."""

    def __init__(self, *, present=False, delete_error=None):
        self.present = present
        self.delete_error = delete_error
        self.deleted: list[str] = []

    def head_object(self, Bucket, Key):
        if not self.present:
            raise client_error("NoSuchKey", "HeadObject", 404)
        return {"ContentLength": 1}

    def delete_object(self, Bucket, Key):
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(Key)
        return {}


# ── the write half ───────────────────────────────────────────────────────────


def test_a_refused_write_passes_a_read_only_probe():
    probe.probe_write_is_denied(
        DeniedStore(FakeS3(), cs.STAGING_BUCKET), KEY, "read-only"
    )
    name, ok, detail = only_check()
    assert ok is True
    assert "AccessDenied" in detail


def test_a_successful_write_fails_a_read_only_probe():
    """The polarity, in the direction that matters.

    A token that writes is not read-only, and in R2 it also deletes — there is
    no permission level between them.  Reporting PASS here would certify a
    credential that can erase a release.
    """

    probe.probe_write_is_denied(
        ConditionalStore(FakeS3(), cs.STAGING_BUCKET), KEY, "read-only"
    )
    name, ok, detail = only_check()
    assert ok is False
    assert "THE WRITE SUCCEEDED" in detail


def test_the_same_probe_reads_a_successful_write_as_a_pass_for_a_write_identity():
    probe.probe_write_is_denied(
        ConditionalStore(FakeS3(), cs.STAGING_BUCKET), KEY, "read-write"
    )
    name, ok, _ = only_check()
    assert ok is True
    assert name == "writing into the staging bucket succeeds"


def test_a_refused_write_fails_a_probe_that_expected_a_write_identity():
    probe.probe_write_is_denied(
        DeniedStore(FakeS3(), cs.STAGING_BUCKET), KEY, "read-write"
    )
    assert only_check()[1] is False


# ── the delete half ──────────────────────────────────────────────────────────


def test_a_refused_delete_passes_a_read_only_probe():
    client = DeletingClient(
        delete_error=client_error("AccessDenied", "DeleteObject", 403)
    )
    probe.probe_delete_is_denied(client, cs.STAGING_BUCKET, ABSENT, "read-only")
    name, ok, detail = only_check()
    assert ok is True
    assert client.deleted == []


def test_an_accepted_delete_fails_a_read_only_probe():
    client = DeletingClient()
    probe.probe_delete_is_denied(client, cs.STAGING_BUCKET, ABSENT, "read-only")
    name, ok, detail = only_check()
    assert ok is False
    assert "THE DELETE WAS ACCEPTED" in detail


def test_an_accepted_delete_is_how_a_write_identity_is_measured():
    """``Object Read & Write`` bundles delete with write, and this measures it.

    Run against the real local staging identity on 2026-09-07 with
    ``--expect read-write``: the delete was accepted, so every identity able to
    publish a release is also able to erase one.  That measurement is why this
    package keeps deletion out of the code entirely — the boundary cannot be
    the token.
    """

    client = DeletingClient()
    probe.probe_delete_is_denied(client, cs.STAGING_BUCKET, ABSENT, "read-write")
    name, ok, detail = only_check()
    assert ok is True
    assert name == "this identity holds DELETE inside the bucket"
    assert client.deleted == [ABSENT]


def test_the_probe_refuses_to_delete_a_key_that_exists():
    """It only ever deletes a key that is not there.

    A permitted delete against a real object would destroy it to learn
    something a nonexistent key answers just as well.
    """

    client = DeletingClient(present=True)
    probe.probe_delete_is_denied(client, cs.STAGING_BUCKET, ABSENT, "read-only")
    name, ok, detail = only_check()
    assert ok is False
    assert "EXISTS" in detail
    assert client.deleted == []


def test_an_unreadable_key_state_stops_the_delete_probe():
    class Unreadable(DeletingClient):
        def head_object(self, Bucket, Key):
            raise client_error("InternalError", "HeadObject", 500)

    client = Unreadable()
    probe.probe_delete_is_denied(client, cs.STAGING_BUCKET, ABSENT, "read-only")
    name, ok, detail = only_check()
    assert ok is False
    assert "state is unknown" in detail
    assert client.deleted == []


# ── isolation, and what counts as a refusal ──────────────────────────────────


def test_a_denied_production_bucket_is_a_pass():
    class Denied:
        def list_objects_v2(self, Bucket, MaxKeys=None):
            assert Bucket == cs.PRODUCTION_BUCKET
            raise client_error("AccessDenied", "ListObjectsV2", 403)

    probe.probe_production_is_denied(Denied())
    assert only_check()[1] is True


def test_a_readable_production_bucket_is_a_failure():
    class Readable:
        def list_objects_v2(self, Bucket, MaxKeys=None):
            return {"KeyCount": 0}

    probe.probe_production_is_denied(Readable())
    name, ok, detail = only_check()
    assert ok is False
    assert "over-scoped" in detail


def test_a_404_is_not_read_as_a_refusal():
    """A missing bucket denies existence; a 403 denies access.

    Treating "not found" as "refused" would let a typo in the bucket name pass
    the isolation check without measuring anything, which is the same class of
    mistake as reading a read failure as absence in ``ConditionalStore.get``.
    """

    assert "404" not in probe.DENIED_CODES
    assert "NoSuchKey" not in probe.DENIED_CODES
    assert "AccessDenied" in probe.DENIED_CODES


def test_every_object_the_probe_could_write_is_classified_as_scaffolding():
    """Its prefix is a known verification root, so retention never sees it as unknown."""

    from src.publication import delivery_boundary as db
    from src.publication import retention as rt

    assert probe.PROBE_ROOT + "/" in db.VERIFICATION_ROOTS
    entry = db.classify_key(f"{probe.PROBE_ROOT}/run-1/x.json", live_release_id=None)
    assert entry.exposure == db.PRIVATE
    assert entry.reason == "verification_artifact"
    assert rt.DEFAULT_VERIFICATION_HORIZON_DAYS > rt.DEFAULT_RUN_HORIZON_DAYS


def test_the_probe_reports_a_failure_as_a_nonzero_exit():
    probe.record("something", False, "why")
    assert probe.report() == 1
    probe.CHECKS.clear()
    probe.record("something", True)
    assert probe.report() == 0
