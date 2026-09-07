"""A fake S3 client that enforces the preconditions R2 enforces.

Every Package 2B.2B behaviour is proven against this rather than against an
object store: no network, no clock, no credential, exactly as
``tests/test_r2_state.py`` and ``tests/test_release_signal.py`` do.  Two
things make it worth more than a stub:

* it **enforces** ``If-None-Match: *`` and ``If-Match: <etag>`` and raises
  ``412 PreconditionFailed`` when they do not hold, so a test that expects a
  conditional write to lose actually exercises the losing branch;
* it computes ETags the way a single ``PutObject`` does — quoted MD5 — so the
  code under test is forced to treat them as opaque tokens.  Nothing here ever
  makes an ETag equal a sha256, which is the confusion the multipart ``-N``
  form causes in production.

``fail_on`` and ``interrupt_after`` let a test cut a publication in half,
which is how "keep the last complete release live" is proven rather than
asserted.
"""

from __future__ import annotations

import hashlib
from io import BytesIO

from botocore.exceptions import ClientError


def client_error(code: str, op: str, status: int) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        op,
    )


def etag_of(body: bytes) -> str:
    """A single-PUT ETag: the quoted MD5 hex of the body."""

    return '"' + hashlib.md5(body).hexdigest() + '"'


class FakeS3:
    """An in-memory object store with R2's conditional-write semantics."""

    def __init__(self, objects=None, *, fail_on=None, interrupt_after=None):
        #: key -> (body, content_type)
        self.objects = dict(objects or {})
        #: keys whose write must raise a non-precondition failure
        self.fail_on = set(fail_on or ())
        #: raise after this many successful writes (None: never)
        self.interrupt_after = interrupt_after
        self.writes: list[tuple[str, str | None]] = []
        self.reads: list[str] = []
        #: set to a body to have the next matching get() return a corrupt read
        self.tamper: dict[str, bytes] = {}

    # ── reads ────────────────────────────────────────────────────────────────

    def get_object(self, Bucket, Key):
        self.reads.append(Key)
        if Key not in self.objects:
            raise client_error("NoSuchKey", "GetObject", 404)
        stored = self.objects[Key][0]
        # A tampered read models a TRUNCATED transfer: the store still reports
        # the object's real length, and only the delivered bytes are short.
        return {
            "Body": BytesIO(self.tamper.get(Key, stored)),
            "ContentLength": len(stored),
            "ETag": etag_of(stored),
        }

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise client_error("NoSuchKey", "HeadObject", 404)
        body = self.objects[Key][0]
        return {"ContentLength": len(body), "ETag": etag_of(body)}

    # ── conditional writes ───────────────────────────────────────────────────

    def put_object(
        self, Bucket, Key, Body, ContentType=None, IfNoneMatch=None, IfMatch=None
    ):
        if Key in self.fail_on:
            raise client_error("InternalError", "PutObject", 500)
        if IfNoneMatch is not None and IfMatch is not None:
            raise AssertionError("a write must carry at most one precondition")
        present = Key in self.objects
        if IfNoneMatch is not None:
            if IfNoneMatch != "*":
                raise AssertionError(f"unexpected If-None-Match {IfNoneMatch!r}")
            if present:
                raise client_error("PreconditionFailed", "PutObject", 412)
        elif IfMatch is not None:
            if not present or etag_of(self.objects[Key][0]) != IfMatch:
                raise client_error("PreconditionFailed", "PutObject", 412)
        else:
            raise AssertionError(
                "an unconditional PutObject reached the store; every green "
                "publication write must carry a precondition"
            )
        if self.interrupt_after is not None and len(self.writes) >= self.interrupt_after:
            raise client_error("RequestTimeout", "PutObject", 408)
        self.objects[Key] = (Body, ContentType)
        self.writes.append((Key, ContentType))
        return {"ETag": etag_of(Body)}

    # ── inspection helpers ───────────────────────────────────────────────────

    def body(self, key: str) -> bytes:
        return self.objects[key][0]

    def keys(self) -> list[str]:
        return sorted(self.objects)
