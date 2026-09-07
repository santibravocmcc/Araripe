"""RFC 8785 canonical JSON, restricted to the subset the v3 ledger uses.

Why a restricted port instead of importing the producer
-------------------------------------------------------
The Package 2A.6 producer hashes every contract document with
``src.detection.identity.canonical_sha256``.  That module is not on ``main``
and cannot be, without also bringing ``identity_v3``, ``persistence_v3`` and
their Shapely geometry primitives — Package 2A.6 is deliberately not merged
(``docs/contracts/phase2b/LEDGER_CONTRACT_BINDING_V1.md``).  The publication
gate still has to recompute the digests the producer embedded, or it can only
believe them.

So this is a port of exactly one property: the producer's ``jcs_dumps`` for
the value types a ``processing-ledger-v3`` document actually contains —
strings, integers, booleans, null, arrays and objects.  Everything the port
cannot reproduce byte-for-byte it **refuses** rather than guesses:

* ``float`` — RFC 8785 §3.2.2.3 number formatting is the one part of JCS with
  real implementation risk, and the ledger has no floating-point field.  A
  float here means the document is not the contract's ledger, so raising is
  both safer and more informative than agreeing by luck.
* non-``str`` object keys, lone surrogates, and integers outside the JCS
  interoperable range — the producer rejects all three, in the same places.

The port therefore either agrees with the producer or refuses; it has no
silent-disagreement path.  Agreement is not asserted, it is executed:
``tests/test_ledger_contract_binding.py`` recomputes every digest embedded in
the pinned producer example — the six document/collection digests, both
per-row digests and the daily-summary digests — and requires equality with the
values the producer committed.  If this file ever drifts from
``jcs_dumps``, that test fails before the gate is used.

Key order is UTF-16BE code-unit order, as in the producer and RFC 8785 §3.2.3.
That differs from Python's default code-point ordering only above U+FFFF, but
it is written out explicitly so the two implementations agree by construction
rather than because contract keys happen to be ASCII.
"""

from __future__ import annotations

import hashlib
from typing import Any


UNIT_SEPARATOR = "\x1f"
LINE_FEED = "\n"

#: Integers outside this range have no exact IEEE-754 double, so RFC 8785
#: leaves them interoperably undefined.  The producer raises; so do we.
JCS_MAX_SAFE_INTEGER = 9_007_199_254_740_991

_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


class CanonicalJsonError(TypeError):
    """A value cannot be canonicalized reproducibly, so it is refused."""


def _encode_string(value: str) -> str:
    out = ['"']
    for character in value:
        code = ord(character)
        if 0xD800 <= code <= 0xDFFF:
            raise CanonicalJsonError(
                "canonical JSON strings cannot contain lone surrogate code points"
            )
        if character in _ESCAPES:
            out.append(_ESCAPES[character])
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            out.append(character)
    out.append('"')
    return "".join(out)


def canonical_json_text(value: Any) -> str:
    """Serialize the reproducible JCS subset, refusing everything else."""

    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _encode_string(value)
    if isinstance(value, int):
        if abs(value) > JCS_MAX_SAFE_INTEGER:
            raise CanonicalJsonError(
                "integer exceeds the JCS interoperable range"
            )
        return str(value)
    if isinstance(value, float):
        raise CanonicalJsonError(
            "this canonicalizer refuses floating-point values: RFC 8785 number "
            "formatting is not reproduced here and the v3 ledger has no "
            "floating-point field, so a float means the document is not a "
            "processing-ledger-v3"
        )
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_json_text(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise CanonicalJsonError("canonical JSON object keys must be strings")
        keys = sorted(
            value,
            key=lambda item: item.encode("utf-16be", errors="surrogatepass"),
        )
        return (
            "{"
            + ",".join(
                f"{_encode_string(key)}:{canonical_json_text(value[key])}"
                for key in keys
            )
            + "}"
        )
    raise CanonicalJsonError(
        f"unsupported canonical JSON value type: {type(value).__name__}"
    )


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_json_text(value).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """The producer's ``canonical_sha256`` over the reproducible subset."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def identity_sha256(*components: str) -> str:
    """The contract's ``SHA256_US`` identity primitive.

    Unit-separator joined UTF-8 components, exactly as
    ``docs/contracts/phase2a/V2_IDENTITY_PERSISTENCE_LEDGER.md`` specifies and
    ``src/detection/identity.identity_sha256`` implements.
    """

    if not all(isinstance(component, str) for component in components):
        raise CanonicalJsonError("identity components must be strings")
    return hashlib.sha256(
        UNIT_SEPARATOR.join(components).encode("utf-8")
    ).hexdigest()
