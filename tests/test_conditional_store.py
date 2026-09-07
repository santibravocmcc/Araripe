"""Conditional writes: the precondition semantics the release layer rests on.

Roadmap Package 2B.2, bullet 3 — *use conditional writes so older/racing jobs
cannot replace a newer release*.  Two questions are answered here and nowhere
else:

* does this environment's boto3 actually express the preconditions, and
* does the store wrapper fail closed on every outcome that is not "the
  precondition held"?

No network: the boto3 client is constructed but never called, and every
behavioural test drives the in-memory ``FakeS3``, which enforces the same
preconditions R2 does and refuses an unconditional ``PutObject`` outright.
"""

from __future__ import annotations

import boto3
import pytest
from botocore.validate import ParamValidator

from src.publication import conditional_store as cs
from src.publication.conditional_store import (
    ConditionalStore,
    ImmutableObjectConflict,
    ObjectStoreError,
    PreconditionFailed,
)
from tests.fake_object_store import FakeS3, client_error, etag_of

BUCKET = cs.STAGING_BUCKET


def store(**kwargs):
    fake = FakeS3(**kwargs)
    return ConditionalStore(fake, BUCKET), fake


def _s3_client():
    """A client object.  Constructing one makes no network call."""

    session = boto3.session.Session(
        aws_access_key_id="unused", aws_secret_access_key="unused", region_name="auto"
    )
    return session.client("s3", endpoint_url=cs.STAGING_ENDPOINT)


# ── what boto3 really accepts, measured rather than assumed ──────────────────

def test_the_preconditions_are_native_putobject_parameters():
    """Measured 2026-09-07: no custom-header workaround is needed for these.

    The briefing carried Cloudflare's recipe for per-request custom headers —
    register ``before-parameter-build.s3.PutObject`` and
    ``before-call.s3.PutObject`` and move the header into the request context.
    That recipe predates AWS S3's own conditional writes.  In this botocore
    ``IfMatch`` and ``IfNoneMatch`` are members of the ``PutObject`` input
    shape, so they travel as ordinary parameters and no hook into botocore's
    private plumbing exists in this package.
    """

    shape = _s3_client().meta.service_model.operation_model("PutObject").input_shape
    assert set(cs.CONDITIONAL_PARAMETERS) <= set(shape.members)
    report = ParamValidator().validate(
        {"Bucket": BUCKET, "Key": "k", "Body": b"x", "IfNoneMatch": "*"}, shape
    )
    assert not report.generate_report()


def test_an_arbitrary_extra_argument_really_is_rejected():
    """The other half of the measurement: the briefing's warning is true.

    It just does not apply to these two parameters.  Keeping the negative
    result pinned is what stops someone "restoring" the header workaround
    later without re-measuring.
    """

    shape = _s3_client().meta.service_model.operation_model("PutObject").input_shape
    report = ParamValidator().validate(
        {"Bucket": BUCKET, "Key": "k", "Body": b"x", "ExtraHeaders": {"If-Match": "x"}},
        shape,
    )
    assert "ExtraHeaders" in report.generate_report()


def test_a_real_client_passes_the_capability_check():
    cs.require_conditional_write_support(_s3_client())


class _NoConditionalWrites:
    class meta:  # noqa: N801 - mirrors botocore's attribute layout
        class service_model:
            @staticmethod
            def operation_model(name):
                class Shape:
                    input_shape = type("S", (), {"members": {"Bucket", "Key", "Body"}})()

                return Shape()


def test_a_botocore_without_conditional_writes_refuses_to_publish():
    """An unconditional PutObject would overwrite silently — never proceed."""

    with pytest.raises(ObjectStoreError, match="IfMatch, IfNoneMatch"):
        cs.require_conditional_write_support(_NoConditionalWrites())


def test_a_client_that_is_not_s3_at_all_fails_closed():
    with pytest.raises(ObjectStoreError, match="cannot establish"):
        cs.require_conditional_write_support(object())


# ── the target guard: production is frozen ───────────────────────────────────

def test_the_production_bucket_is_refused_by_name():
    with pytest.raises(ObjectStoreError, match="production is frozen"):
        cs.assert_staging_target(cs.PRODUCTION_BUCKET, cs.STAGING_ENDPOINT)


@pytest.mark.parametrize("bucket", ["araripe-cogs", "araripe", "", "araripe-v2-stagin"])
def test_only_the_approved_staging_bucket_is_accepted(bucket):
    with pytest.raises(ObjectStoreError):
        cs.assert_staging_target(bucket, cs.STAGING_ENDPOINT)


@pytest.mark.parametrize(
    "endpoint",
    [None, "", "https://example.com", "https://other.r2.cloudflarestorage.com"],
)
def test_only_the_approved_account_endpoint_is_accepted(endpoint):
    with pytest.raises(ObjectStoreError, match="endpoint"):
        cs.assert_staging_target(cs.STAGING_BUCKET, endpoint)


def test_the_approved_target_is_accepted():
    cs.assert_staging_target(cs.STAGING_BUCKET, cs.STAGING_ENDPOINT)


def test_the_target_is_checked_before_a_credential_is_used():
    """A wrong bucket is refused even with no credential to hand."""

    with pytest.raises(ObjectStoreError, match="production is frozen"):
        cs.build_client(cs.PRODUCTION_BUCKET, cs.STAGING_ENDPOINT, {})


def test_a_missing_credential_is_named():
    with pytest.raises(ObjectStoreError, match="access_key_id"):
        cs.build_client(
            cs.STAGING_BUCKET,
            cs.STAGING_ENDPOINT,
            {"access_key_id": "", "secret_access_key": "s"},
        )


# ── If-None-Match: write once ────────────────────────────────────────────────

def test_an_absent_key_is_created():
    s, fake = store()
    outcome = s.put_if_absent("releases/x/a.json", b"body", "application/json")
    assert outcome.result == "created"
    assert fake.body("releases/x/a.json") == b"body"
    assert fake.writes == [("releases/x/a.json", "application/json")]


def test_the_same_bytes_again_are_an_idempotent_no_op():
    """Republishing a release must be free, not a conflict."""

    s, fake = store()
    s.put_if_absent("k", b"body", "application/json")
    outcome = s.put_if_absent("k", b"body", "application/json")
    assert outcome.result == "unchanged"
    assert len(fake.writes) == 1


def test_different_bytes_under_an_immutable_key_fail_closed():
    s, fake = store()
    s.put_if_absent("k", b"first", "application/json")
    with pytest.raises(ImmutableObjectConflict, match="never rewritten"):
        s.put_if_absent("k", b"second", "application/json")
    assert fake.body("k") == b"first"


def test_a_write_failure_that_is_not_a_precondition_is_raised():
    s, fake = store(fail_on={"k"})
    with pytest.raises(ObjectStoreError, match="InternalError"):
        s.put_if_absent("k", b"body", "application/json")


# ── If-Match: compare and swap ───────────────────────────────────────────────

def test_a_matching_etag_replaces_the_object():
    s, fake = store()
    s.put_if_absent("p", b"v1", "application/json")
    s.put_if_match("p", b"v2", "application/json", etag_of(b"v1"))
    assert fake.body("p") == b"v2"


def test_a_stale_etag_loses_the_race_and_is_not_retried():
    s, fake = store()
    s.put_if_absent("p", b"v1", "application/json")
    stale = etag_of(b"v1")
    s.put_if_match("p", b"v2", "application/json", stale)
    with pytest.raises(PreconditionFailed, match="not retried"):
        s.put_if_match("p", b"v3", "application/json", stale)
    assert fake.body("p") == b"v2"


def test_a_pointer_appearing_mid_promotion_loses_the_race():
    """Identical bytes are idempotence for an object and a lost race here.

    Two promoters starting from an empty pointer must not both conclude they
    created it, so this path does not share ``put_if_absent``'s forgiveness.
    """

    s, fake = store()
    s.put_if_pointer_absent("p", b"v1", "application/json")
    with pytest.raises(PreconditionFailed, match="another writer"):
        s.put_if_pointer_absent("p", b"v1", "application/json")


def test_no_write_may_reach_the_store_without_a_precondition():
    """Enforced by the fake, and asserted here so the guarantee is explicit."""

    _, fake = store()
    with pytest.raises(AssertionError, match="unconditional PutObject"):
        fake.put_object(Bucket=BUCKET, Key="k", Body=b"x", ContentType="application/json")


# ── reads fail closed ────────────────────────────────────────────────────────

def test_an_absent_object_reads_as_none():
    s, _ = store()
    assert s.get("nothing") is None


@pytest.mark.parametrize(
    "code,status",
    [("AccessDenied", 403), ("InvalidAccessKeyId", 403), ("InternalError", 500),
     ("SlowDown", 503)],
)
def test_a_read_failure_is_never_absence(code, status):
    """A 403 hides existence rather than denying it.

    Reading either as "there is no pointer yet" is how a promoter would
    overwrite a live release, which is the same defect Package 2B.1 fixed in
    ``scripts/r2_state.py`` one layer down.
    """

    class Denied(FakeS3):
        def get_object(self, Bucket, Key):
            raise client_error(code, "GetObject", status)

    s = ConditionalStore(Denied(), BUCKET)
    with pytest.raises(ObjectStoreError, match=code):
        s.get("k")


def test_a_truncated_read_is_refused():
    s, fake = store()
    s.put_if_absent("k", b"0123456789", "application/json")
    fake.tamper["k"] = b"012"
    with pytest.raises(ObjectStoreError, match="truncated"):
        s.get("k")


def test_require_names_the_absent_key():
    s, _ = store()
    with pytest.raises(ObjectStoreError, match="is absent"):
        s.require("releases/x/release.json")


# ── ETag is a token, not a checksum ──────────────────────────────────────────

def test_an_etag_is_never_treated_as_a_content_checksum():
    """A multipart ETag is `md5-of-md5s-N` and matches no sha256 of anything.

    The store hands the ETag back verbatim in ``If-Match`` and parses nothing,
    so an opaque or composite value works identically.
    """

    class Composite(FakeS3):
        def put_object(self, Bucket, Key, Body, ContentType=None, IfNoneMatch=None,
                       IfMatch=None):
            if IfMatch is not None and IfMatch != self.etags.get(Key):
                raise client_error("PreconditionFailed", "PutObject", 412)
            if IfNoneMatch is not None and Key in self.objects:
                raise client_error("PreconditionFailed", "PutObject", 412)
            self.objects[Key] = (Body, ContentType)
            self.etags[Key] = '"d41d8cd98f00b204e9800998ecf8427e-7"'
            self.writes.append((Key, ContentType))
            return {"ETag": self.etags[Key]}

        def get_object(self, Bucket, Key):
            response = super().get_object(Bucket, Key)
            response["ETag"] = self.etags[Key]
            return response

    fake = Composite()
    fake.etags = {}
    s = ConditionalStore(fake, BUCKET)
    created = s.put_if_absent("k", b"body", "application/json")
    assert created.etag.endswith('-7"')
    stored = s.require("k")
    s.put_if_match("k", b"next", "application/json", stored.etag)
    assert fake.body("k") == b"next"
