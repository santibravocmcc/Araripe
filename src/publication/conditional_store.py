"""Conditional object writes: the guard that keeps a release immutable.

Roadmap Package 2B.2: *use conditional writes so older/racing jobs cannot
replace a newer release*.  Two preconditions carry the whole mechanism:

* ``If-None-Match: *`` — write only if the key does not exist.  Every object
  under an immutable release prefix goes out this way, so a second publication
  of the same release cannot rewrite it.  A ``412`` is not an error yet: the
  bytes are read back and compared, and an identical object is an idempotent
  no-op while a differing one fails closed.
* ``If-Match: <etag>`` — write only if the object is still the version we
  read.  The green pointer moves this way, so a promotion that raced with
  another loses instead of clobbering.

Both are R2 extensions of the S3 API and fail with ``412 PreconditionFailed``
(https://developers.cloudflare.com/r2/api/s3/extensions/).

Measured, 2026-09-07: boto3 needs no header workaround for these two
--------------------------------------------------------------------
The Package 2B.2B briefing carried the Cloudflare recipe for per-request
custom headers — move the header into the request context across
``before-parameter-build.s3.PutObject`` and ``before-call.s3.PutObject``,
because botocore's parameter validation rejects unknown arguments.  That
advice is correct in general and was verified here: validating a ``PutObject``
call carrying ``ExtraHeaders`` reports *Unknown parameter in input:
"ExtraHeaders"*.

It does not apply to these two preconditions.  In botocore 1.42.42 — the
version this environment resolves — ``IfMatch`` and ``IfNoneMatch`` are
**native members** of the ``PutObject`` input shape, because AWS S3 gained
conditional writes after the Cloudflare example was written.  So the
preconditions are passed as ordinary parameters and no event-system hook is
registered.  Fewer moving parts, and nothing reaching into botocore's private
plumbing.

``require_conditional_write_support`` keeps that from becoming a silent
assumption.  It is not a duplicate of botocore's own validation: it asks the
loaded service model whether the members exist *before* any object is touched,
so an environment whose botocore predates conditional writes refuses to
publish instead of discovering it halfway through a release.

ETag is a CAS token, never a checksum
-------------------------------------
An ETag from a single ``PutObject`` is the MD5 of the body; from a multipart
upload it is the MD5 of the concatenated part MD5s with a ``-N`` suffix.  It
is therefore never comparable to the scientific ``sha256`` a release declares,
and this module treats it as an opaque token: it is read, kept, and handed
back in ``If-Match``, and never parsed or compared to content.  Content
integrity is the release manifest's ``sha256`` fields, verified by re-reading
the bytes.

Copy-time destination conditions (``cf-copy-destination-if-match`` and
siblings) are in beta, so nothing here is built on them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: R2/S3 codes meaning "your precondition did not hold".  Both forms are
#: accepted because the code and the HTTP status arrive by different paths,
#: exactly as ``scripts/r2_state.py`` does for absence.
PRECONDITION_CODES = frozenset({"PreconditionFailed", "412"})

#: Codes meaning "the object is not there", as opposed to "we could not find
#: out".  Deliberately narrow: a 403 hides existence rather than denying it.
ABSENT_CODES = frozenset({"404", "NoSuchKey", "NoSuchBucket"})

#: The only bucket this package may write to before the Phase 6 cutover, and
#: the only account endpoint it may reach.  Same values, and the same
#: fail-closed discipline, as ``.github/workflows/v2_candidate_replay.yml``.
STAGING_BUCKET = "araripe-v2-staging"
STAGING_ENDPOINT = "https://9416750169311ee4afc18a8ff3c771d4.r2.cloudflarestorage.com"
PRODUCTION_BUCKET = "araripe-cogs"

CONDITIONAL_PARAMETERS = ("IfMatch", "IfNoneMatch")


class ObjectStoreError(RuntimeError):
    """An object operation could not be completed or could not be trusted."""


class PreconditionFailed(ObjectStoreError):
    """The write was refused because its precondition did not hold."""


class ImmutableObjectConflict(ObjectStoreError):
    """A write-once key already holds different bytes."""


@dataclass(frozen=True)
class StoredObject:
    key: str
    body: bytes
    etag: str

    @property
    def size(self) -> int:
        return len(self.body)


@dataclass(frozen=True)
class PutOutcome:
    """What a conditional write did.

    ``created`` — the precondition held and the bytes were written.
    ``unchanged`` — the key already held exactly these bytes; nothing was
    written and nothing needed to be.
    """

    key: str
    result: str
    etag: str | None
    size: int


def error_code(exc: Exception) -> str | None:
    """Best-effort S3 error code for a botocore ``ClientError``."""

    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    code = (response.get("Error") or {}).get("Code")
    if code is not None:
        return str(code)
    status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return str(status) if status is not None else None


def is_precondition_failure(exc: Exception) -> bool:
    return error_code(exc) in PRECONDITION_CODES


def is_absent(exc: Exception) -> bool:
    return error_code(exc) in ABSENT_CODES


def assert_staging_target(bucket: str, endpoint_url: str | None) -> None:
    """Refuse anything but the approved staging sandbox, before any call.

    Production is frozen through Roadmap Phases 2B–5 and this package has no
    business addressing it.  The check is on the *target*, not on the
    credential, because a bucket-scoped key is a second line of defence and
    this is the first.
    """

    if bucket == PRODUCTION_BUCKET:
        raise ObjectStoreError(
            f"refusing to address the production bucket {PRODUCTION_BUCKET!r}: "
            "production is frozen through Roadmap Phases 2B-5 and green "
            "publication writes only to " + STAGING_BUCKET
        )
    if bucket != STAGING_BUCKET:
        raise ObjectStoreError(
            f"refusing bucket {bucket!r}: green publication targets only "
            f"{STAGING_BUCKET!r}"
        )
    if endpoint_url != STAGING_ENDPOINT:
        raise ObjectStoreError(
            f"refusing endpoint {endpoint_url!r}: it is not the approved account "
            "endpoint"
        )


def require_conditional_write_support(client: Any) -> None:
    """Refuse to publish unless ``PutObject`` really accepts the preconditions.

    Asked of the loaded service model rather than of a request, so the refusal
    happens before any object is touched.  Without conditional writes this
    package's immutability and compare-and-swap guarantees do not exist, and a
    plain ``PutObject`` would overwrite silently — the one failure mode the
    whole design is built to prevent.
    """

    try:
        shape = client.meta.service_model.operation_model("PutObject").input_shape
        members = set(shape.members)
    except Exception as exc:  # pragma: no cover - a non-S3 client
        raise ObjectStoreError(
            f"cannot establish whether this client supports conditional writes: {exc}"
        ) from exc
    missing = [name for name in CONDITIONAL_PARAMETERS if name not in members]
    if missing:
        raise ObjectStoreError(
            "this botocore does not accept "
            + ", ".join(missing)
            + " on PutObject, so an immutable write and a pointer "
            "compare-and-swap cannot be expressed. Refusing to publish: an "
            "unconditional PutObject would overwrite silently."
        )


def build_client(bucket: str, endpoint_url: str | None, credentials: dict[str, str]):
    """A boto3 S3 client for the staging bucket, or a refusal.

    The target guard runs first, so a misconfigured bucket or endpoint is
    refused before a credential is even handed to boto3.
    """

    assert_staging_target(bucket, endpoint_url)
    missing = [name for name, value in credentials.items() if not value]
    if missing:
        raise ObjectStoreError(
            "missing R2 credentials in the environment: " + ", ".join(sorted(missing))
        )
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=credentials["access_key_id"],
        aws_secret_access_key=credentials["secret_access_key"],
        region_name=credentials.get("region") or "auto",
    )
    require_conditional_write_support(client)
    return client


class ConditionalStore:
    """The object operations green publication is allowed to perform.

    Deliberately small: read one object, create one object that must not exist,
    and replace one object that must still be the version read.  There is no
    delete and no unconditional put — retention and lifecycle are Package
    2B.3, and an unconditional put is the mistake this class exists to make
    unavailable.

    The client is injected so every behaviour here is provable without a
    network or an object store.
    """

    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self.bucket = bucket

    # ── reads ────────────────────────────────────────────────────────────────

    def get(self, key: str) -> StoredObject | None:
        """The object, or ``None`` only when it is genuinely absent.

        Every other outcome raises.  Reading a credential or network failure as
        absence is how a promoter would conclude "there is no pointer yet" and
        overwrite a live one.
        """

        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if is_absent(exc):
                return None
            raise ObjectStoreError(
                f"cannot read {self.bucket}/{key} "
                f"({error_code(exc) or 'unknown'}): {exc}"
            ) from exc
        try:
            body = response["Body"].read()
        except Exception as exc:
            raise ObjectStoreError(f"reading the body of {key} failed: {exc}") from exc
        declared = response.get("ContentLength")
        if declared is not None and len(body) != declared:
            raise ObjectStoreError(
                f"truncated read of {key}: got {len(body)} bytes, the store "
                f"reports {declared}"
            )
        return StoredObject(key=key, body=body, etag=str(response.get("ETag") or ""))

    def require(self, key: str) -> StoredObject:
        stored = self.get(key)
        if stored is None:
            raise ObjectStoreError(f"{self.bucket}/{key} is absent")
        return stored

    # ── conditional writes ───────────────────────────────────────────────────

    def put_if_absent(self, key: str, body: bytes, content_type: str) -> PutOutcome:
        """Create ``key``, or accept it if it already holds these exact bytes.

        The ``412`` path is what makes republication safe rather than merely
        forbidden: a release identity is a function of its ledger, so the same
        run publishing twice offers the same bytes and the second attempt is a
        no-op.  Different bytes under the same immutable key mean two
        different releases claimed one identity, which is never resolved
        automatically.
        """

        try:
            response = self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                IfNoneMatch="*",
            )
        except Exception as exc:
            if not is_precondition_failure(exc):
                raise ObjectStoreError(
                    f"cannot write {self.bucket}/{key} "
                    f"({error_code(exc) or 'unknown'}): {exc}"
                ) from exc
            existing = self.get(key)
            if existing is None:
                raise ObjectStoreError(
                    f"{key} refused an If-None-Match write but then read as "
                    "absent; the store is not behaving consistently and nothing "
                    "further will be written"
                ) from exc
            if existing.body != body:
                raise ImmutableObjectConflict(
                    f"{self.bucket}/{key} already holds {existing.size} bytes that "
                    f"differ from the {len(body)} being published. An immutable "
                    "release key is never rewritten; two different contents "
                    "claiming one release identity is not resolvable here."
                ) from exc
            return PutOutcome(key, "unchanged", existing.etag, existing.size)
        return PutOutcome(key, "created", str(response.get("ETag") or ""), len(body))

    def put_if_match(
        self, key: str, body: bytes, content_type: str, etag: str
    ) -> PutOutcome:
        """Replace ``key`` only if it is still the version whose ETag this is.

        A failed precondition raises rather than retrying.  The caller read a
        version, decided against it, and that decision is now stale; retrying
        the same bytes would apply a decision made about a different state.
        """

        try:
            response = self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                IfMatch=etag,
            )
        except Exception as exc:
            if is_precondition_failure(exc):
                raise PreconditionFailed(
                    f"{self.bucket}/{key} changed since it was read (ETag {etag}); "
                    "another writer won the race. Re-read and re-evaluate: this "
                    "write is not retried, because the decision behind it was "
                    "made about a version that is no longer live."
                ) from exc
            raise ObjectStoreError(
                f"cannot write {self.bucket}/{key} "
                f"({error_code(exc) or 'unknown'}): {exc}"
            ) from exc
        return PutOutcome(key, "created", str(response.get("ETag") or ""), len(body))

    def put_if_pointer_absent(
        self, key: str, body: bytes, content_type: str
    ) -> PutOutcome:
        """Create the pointer for the first time, refusing if one appeared.

        Separate from ``put_if_absent`` because the pointer is mutable: an
        identical-bytes ``412`` here is still a lost race, not idempotence.
        Two promoters starting from an empty pointer must not both believe
        they created it.
        """

        try:
            response = self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                IfNoneMatch="*",
            )
        except Exception as exc:
            if is_precondition_failure(exc):
                raise PreconditionFailed(
                    f"{self.bucket}/{key} was created by another writer while this "
                    "promotion was preparing. Re-read and re-evaluate."
                ) from exc
            raise ObjectStoreError(
                f"cannot write {self.bucket}/{key} "
                f"({error_code(exc) or 'unknown'}): {exc}"
            ) from exc
        return PutOutcome(key, "created", str(response.get("ETag") or ""), len(body))
