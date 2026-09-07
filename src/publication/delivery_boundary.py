"""What green storage may be served publicly, and how one request resolves.

Roadmap Package 2B.3, first two bullets: *create a private processing boundary
and a public release-only boundary*, and *prepare and validate a same-origin
``/data/...`` route against the isolated staging Worker first*.

Today ``runs/<run-id>/`` (processing input) and ``releases/<id>/`` (product)
live in one bucket with one exposure, because nothing serves either.  This
module is where that stops being true, and it is deliberately the **only**
place that decides.

The shape of the guarantee
--------------------------
A request never becomes an object key by string manipulation.  The path after
the mount is looked up in an **allowlist built from the live release's own
manifest**, and the key is then ``release_prefix + that declared path``.  So:

* a URL cannot address ``runs/``, a probe prefix, or any release other than
  the live one, because those strings never enter a key — the only strings
  that do are the ones the live manifest declares;
* traversal, absolute paths and backslashes are refused twice over: the
  release schema's ``logical_path`` already forbids them in what may be
  *declared*, and an undeclared path is refused for not being on the list.

That is stronger than sanitising the request, and it is why the refusal is
"not declared" rather than "looks dangerous".  A denylist has to imagine the
attack; this cannot express it.

Why the live release, and not ``releases/``
-------------------------------------------
Serving the whole ``releases/`` prefix would publish exactly the two things
the publication design spent Package 2B.2B refusing to serve: a release whose
promotion was **refused** for coverage regression, and a release that was
**rolled back away from**.  Both stay in the bucket by design
(``GREEN_RELEASE_CONTRACT_V1.md`` §6, and the 2026-09-07 proofs), and both
contradict the live release.  "Published" and "live" are different states, and
only the second is public.

Deliberately not sniffed, deliberately validated
------------------------------------------------
``content_type`` is the one manifest field the release schema leaves as
``{"type": "string", "minLength": 1}``.  The producer therefore promises
nothing about it, so this module validates it as a media type before it
reaches a response header — a header value carrying CR or LF would split the
response.  This is the ``LEDGER_CONTRACT_BINDING_V1.md`` §5 rule read in the
other direction: never *assert* an invariant the producer does not promise,
and never *rely* on one either.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from src.publication.findings import Finding, Rejected

#: Contract version of the exposure policy.
BOUNDARY_SCHEMA = "araripe.green.delivery/1"

#: The single mutable object.  Public, because a consumer cannot find the live
#: release without it, and never cached — see ``CACHE_POINTER``.
POINTER_KEY = "pointers/green/current.json"

#: Roots, with the exposure each carries.  Every key in the bucket is matched
#: against these in order, and anything unmatched is private: the policy fails
#: closed on a prefix nobody has classified yet.
RELEASES_ROOT = "releases/"
RUNS_ROOT = "runs/"
VERIFICATION_ROOTS = (
    "green-isolation-proof/",
    "promotion-identity-probe/",
    "readonly-identity-probe/",
)

#: Where the route is mounted on the staging Worker.  A separate namespace
#: from the site's existing static ``/data/...`` assets on purpose: Package
#: 2B.3's third bullet is *copy and verify before switching consumers; retain
#: the old paths for rollback*, and a mount that shadowed ``/data/alerts/…``
#: would switch every consumer the moment it deployed.
MOUNT = "/data/green/"

#: Reserved names directly under the mount.  They are the three documents a
#: consumer needs to verify what it received, and none of them is a product.
POINTER_NAME = "current.json"
MANIFEST_NAME = "release.json"
LEDGER_NAME = "ledger.json"

#: Paths inside a release prefix that the release layout owns rather than the
#: products (``GREEN_RELEASE_CONTRACT_V1.md`` §1).  A manifest may not declare
#: a product at one of these, and ``check_release_layout`` refuses one that
#: does — otherwise a product would decide what ``/data/green/release.json``
#: means.
RESERVED_RELEASE_PATHS = frozenset({MANIFEST_NAME, LEDGER_NAME})

ALLOWED_METHODS = ("GET", "HEAD")

#: The pointer is the only mutable object in the layout, so a cached copy of it
#: is precisely how a rollback fails to take effect: the release it names is
#: still complete and still served, and the consumer keeps following the
#: superseded one.  ``no-store`` rather than ``no-cache`` because there is no
#: revalidation cost worth the ambiguity — the document is ~1.5 KiB.
CACHE_POINTER = "no-store"

#: Everything else resolves *through* the pointer, so its URL is stable while
#: its bytes are not.  A short freshness window plus mandatory revalidation
#: bounds how long a consumer may keep serving a superseded release after a
#: promotion or a rollback; the ETag makes the revalidation a 304.
#:
#: An immutable, release-addressed namespace would allow ``max-age`` of a year,
#: and it is deliberately not offered: it would make every non-live release
#: publicly addressable, which is the one thing this boundary exists to
#: prevent.
CACHE_RESOLVED = "public, max-age=60, must-revalidate"

#: A media type this module is willing to put in a header: one ``type/subtype``
#: token pair, optional parameters, and no control character of any kind.  RFC
#: 9110 §8.3 shape, kept deliberately narrower than the grammar allows.
MEDIA_TYPE = re.compile(
    r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+/[A-Za-z0-9!#$%&'*+.^_`|~-]+"
    r"(?:[ \t]*;[ \t]*[A-Za-z0-9!#$%&'*+.^_`|~-]+=(?:[A-Za-z0-9!#$%&'*+.^_`|~-]+|\"[^\"\\\x00-\x1f\x7f]*\"))*$"
)

#: A filename safe to put in ``Content-Disposition`` without quoting rules
#: mattering.  Derived from the *declared* path, never from the request.
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]*$")

PUBLIC = "public"
PRIVATE = "private"


class DeliveryRefused(Rejected):
    """The request does not resolve to anything this boundary may serve."""

    subject = "delivery request"


class BoundaryViolation(Rejected):
    """A release or an inventory contradicts the exposure policy."""

    subject = "delivery boundary"


@dataclass(frozen=True)
class Exposure:
    """What one stored key is, and whether it may leave the bucket.

    ``reason`` is a stable code rather than prose so a report can be grouped
    and a test can assert the *classification*, not the wording.
    """

    key: str
    exposure: str
    reason: str

    @property
    def is_public(self) -> bool:
        return self.exposure == PUBLIC


@dataclass(frozen=True)
class Served:
    """One resolved response: which object, and the headers that describe it."""

    key: str
    status: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)
    #: ``None`` for the pointer and the manifest, whose bytes the resolver
    #: already holds; a declared sha256 for a product, so the caller can verify
    #: what it read before handing it out.
    sha256: str | None = None
    bytes: int | None = None


def classify_key(key: str, *, live_release_id: str | None) -> Exposure:
    """Classify one stored key against the exposure policy, failing closed.

    ``live_release_id`` is read from the pointer.  Passing ``None`` — no
    pointer yet, or a pointer that could not be read — makes **every** release
    private, which is the correct reading: without a pointer nothing is live,
    and a boundary that guessed would serve a release the operator never
    promoted.
    """

    if key == POINTER_KEY:
        return Exposure(key, PUBLIC, "pointer")
    if key.startswith(RUNS_ROOT):
        return Exposure(key, PRIVATE, "processing_input")
    for root in VERIFICATION_ROOTS:
        if key.startswith(root):
            return Exposure(key, PRIVATE, "verification_artifact")
    if key.startswith(RELEASES_ROOT):
        rest = key[len(RELEASES_ROOT) :]
        release_id, _, remainder = rest.partition("/")
        if not remainder:
            return Exposure(key, PRIVATE, "release_prefix_malformed")
        if live_release_id is not None and release_id == live_release_id:
            return Exposure(key, PUBLIC, "live_release")
        return Exposure(key, PRIVATE, "release_not_live")
    return Exposure(key, PRIVATE, "unclassified")


def check_release_layout(manifest: Mapping[str, Any]) -> None:
    """Refuse a release whose products would shadow the layout's own names.

    ``release.json`` and ``ledger.json`` are the release layout's, and the
    route serves them under reserved names.  A manifest declaring a *product*
    at one of those paths would make ``/data/green/release.json`` ambiguous,
    so it is refused here rather than resolved by precedence.

    Reachable, and not a re-check of the schema: ``logical_path`` permits both
    strings, and ``check_green_release`` has no opinion about them.
    """

    findings = [
        Finding(
            "product_shadows_release_document",
            f"{item['path']!r} is a reserved name in the release layout; a "
            "product may not be published at it",
            f"objects/{index}",
        )
        for index, item in enumerate(manifest["objects"])
        if item["path"] in RESERVED_RELEASE_PATHS
    ]
    if findings:
        raise BoundaryViolation(findings)


def _media_type(value: str, where: str) -> str:
    if not MEDIA_TYPE.match(value):
        raise DeliveryRefused(
            [
                Finding(
                    "content_type_unusable",
                    f"{value!r} is not a media type this boundary will put in a "
                    "header. The release schema constrains content_type only to "
                    "a non-empty string, so the producer promises nothing about "
                    "it and it is validated here instead of trusted.",
                    where,
                )
            ]
        )
    return value


def _declared(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """The allowlist: declared logical path → its manifest entry."""

    return {item["path"]: item for item in manifest["objects"]}


def _refuse(code: str, detail: str, path: str = "<request>") -> DeliveryRefused:
    return DeliveryRefused([Finding(code, detail, path)])


def resolve(
    method: str,
    url_path: str,
    *,
    pointer: Mapping[str, Any] | None,
    manifest: Mapping[str, Any] | None,
    download: bool = False,
) -> Served:
    """Resolve one request into exactly one object key, or refuse it.

    ``pointer`` and ``manifest`` are the live pointer and the manifest of the
    release it names; the caller reads both.  Nothing here contacts a store,
    so the whole boundary is decidable without one — which is what lets a
    Worker, a test and a review all evaluate the same function.
    """

    if method not in ALLOWED_METHODS:
        raise _refuse(
            "method_not_allowed",
            f"{method} is not one of {', '.join(ALLOWED_METHODS)}; this route "
            "reads published objects and writes nothing",
        )
    if not url_path.startswith(MOUNT):
        raise _refuse(
            "outside_mount",
            f"{url_path!r} is not under {MOUNT}; this route claims only its own "
            "namespace and never falls back to another prefix",
        )
    rest = url_path[len(MOUNT) :]

    if rest == POINTER_NAME:
        if pointer is None:
            raise _refuse("pointer_absent", "no green release has been promoted yet")
        return Served(
            key=POINTER_KEY,
            headers=_headers("application/json", CACHE_POINTER),
        )

    if pointer is None or manifest is None:
        raise _refuse(
            "pointer_absent",
            "no green release has been promoted yet, so nothing under this "
            "mount is live",
        )
    if manifest["release_id"] != pointer["release_id"]:
        raise _refuse(
            "manifest_is_not_live",
            f"the manifest offered is {manifest['release_id']} while the pointer "
            f"names {pointer['release_id']}; only the live release is served",
        )
    prefix = manifest["release_prefix"]

    if rest == MANIFEST_NAME:
        return Served(
            key=prefix + MANIFEST_NAME,
            headers=_headers("application/json", CACHE_RESOLVED),
        )
    if rest == LEDGER_NAME:
        return Served(
            key=prefix + LEDGER_NAME,
            headers=_headers("application/json", CACHE_RESOLVED),
        )

    entry = _declared(manifest).get(rest)
    if entry is None:
        raise _refuse(
            "not_declared_by_the_live_release",
            f"{rest!r} is not one of the {len(manifest['objects'])} object "
            "path(s) the live release declares. A path is served because the "
            "manifest lists it, never because it looks safe.",
        )

    content_type = _media_type(entry["content_type"], f"objects/{rest}")
    headers = _headers(content_type, CACHE_RESOLVED)
    # A checksum-based validator, not the store's ETag. R2's ETag is the MD5 of
    # the body for a single PutObject and the MD5 of the part MD5s with a `-N`
    # suffix for a multipart one — measured on the live blue object
    # `run-2026-08-30.geojson`, whose ETag ends in `-2`. It is a
    # compare-and-swap token, never comparable to the scientific sha256, so the
    # sha256 the manifest declares is what a consumer gets to revalidate on.
    headers["ETag"] = '"' + entry["sha256"] + '"'
    headers["X-Araripe-Sha256"] = entry["sha256"]
    headers["X-Araripe-Release-Id"] = manifest["release_id"]
    if download:
        headers["Content-Disposition"] = (
            'attachment; filename="' + _filename(rest) + '"'
        )
    return Served(
        key=prefix + rest,
        headers=headers,
        sha256=entry["sha256"],
        bytes=entry["bytes"],
    )


def _headers(content_type: str, cache_control: str) -> dict[str, str]:
    """The headers every response carries, and the ones it deliberately omits.

    **No ``Access-Control-Allow-Origin``.**  The whole purpose of a same-origin
    ``/data/...`` route is that the browser needs no cross-origin permission:
    the blue path serves 13.8 MiB of alerts from ``pub-…r2.dev`` and depends on
    a bucket CORS policy naming the final domain (measured 2026-09-07: the
    preflight answers ``Access-Control-Allow-Origin:
    https://observatoriodachapadadoararipe.com``, ``Vary: Origin``,
    ``Access-Control-Allow-Methods: GET``).  Emitting ``*`` here would rebuild,
    wider, the cross-origin surface this route exists to remove.  A
    cross-origin consumer is a decision, not a default.

    ``nosniff`` because the type is *declared* by the manifest.  Letting a
    browser sniff would put the producer's declaration and the browser's guess
    in disagreement, and the guess would win.
    """

    return {
        "Content-Type": content_type,
        "Cache-Control": cache_control,
        "X-Content-Type-Options": "nosniff",
    }


def _filename(declared_path: str) -> str:
    """A download filename derived from the declared path, never the request.

    The request only ever *selects* a declared path, so this cannot carry a
    quote, a CR or an LF into the header.  It is checked anyway: the value that
    reaches the header is the one this function returns, and a future caller
    passing something else must fail rather than inject.
    """

    name = posixpath.basename(declared_path)
    if not SAFE_FILENAME.match(name):
        raise _refuse(
            "filename_unusable",
            f"{name!r} cannot be placed in a Content-Disposition header",
            declared_path,
        )
    return name


def public_keys(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    """Every key the route can reach for this release, in serving order.

    Useful to a reviewer and to the retention planner: it is the complete
    answer to "what is public right now", derived from the same manifest the
    resolver uses rather than restated.
    """

    prefix = manifest["release_prefix"]
    return (POINTER_KEY, prefix + MANIFEST_NAME, prefix + LEDGER_NAME) + tuple(
        prefix + item["path"] for item in manifest["objects"]
    )
