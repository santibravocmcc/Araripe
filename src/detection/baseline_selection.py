"""Which baseline generation a detection run compares against.

Phase 3, scope item 1a.  Baseline ``2.1.0`` was built and validated by Package
2A.6C.1/2A.6D and its record says so explicitly — *"Compatible baseline: 2.1.0
built and validated; runtime activation deliberately belongs to the replay
packages"*.  Until this module existed the detection runtime could only ever
load ``1.0.0``: ``src/detection/baseline.py`` hard-wired
``BASELINES_DIR`` + ``BASELINE_MANIFEST_PATH``, and a scan for the v2 manifest
found zero references in ``src/detection/baseline.py`` or any
``run_detection*.py``.

What this module is
-------------------
A **closed registry** of the baseline generations a run may name, and a
resolver that fails closed on anything else.  It is deliberately not a search:
there is no environment variable, no directory sniffing, no "newest wins" and
no fallback.  A run either names a registered generation or resolves the
default, and the default is read from ``config.settings.BASELINE_VERSION`` —
which is why activating v2 for the replay changes nothing about what the frozen
blue production path does today.

Why the default is read from settings rather than pinned here
-------------------------------------------------------------
Two pins for one fact is one pin too many.  ``config/settings.py`` is what the
blue path already consults, ``tests/test_baseline_manifest.py`` already binds
``settings.BASELINE_VERSION`` to the v1 manifest's own
``baseline_version``, and ``tests/test_baseline_selection.py`` binds the
default *selection* to the v1 directory and manifest.  So a change to the blue
default is visible in one place and caught in two.

Why ``2.0.0`` is registered as refused rather than simply absent
----------------------------------------------------------------
``config/baseline_manifest_v2.json`` exists and describes a real 72-object
generation, so "not in the registry" would read as an oversight.  It is not:
amendment v2 (``config/phase2a6c1_seasonal_source_regime_amendment_v2.json``)
moved May and December to a shoulder regime with a looser scene cloud filter,
12 of the 72 rasters differ, and ``2.1.0`` supersedes it — measured, and
already declared by ``BASELINE_V2_SUPERSEDED_VERSION`` in
``src.processing.baseline_rebuild_v2``.  Its manifest is retained as audit
material.  A replay that composed against it would be comparing 2026 to a
generation the owner replaced, so the refusal names the successor.

The production ``.env`` is not brought anywhere new
---------------------------------------------------
``config/settings.py`` calls ``load_dotenv`` at import, and
``tests/test_assemble_green_run.py`` forbids the green publication scripts from
importing it.  This module imports it, and so do
``src/detection/baseline.py`` and ``src/detection/baseline_manifest_v2.py``
already: the detection path *is* blue.  The guard that matters is that no green
script reach this module — direct or transitive — and that is what
``test_no_green_script_reaches_the_dotenv_loader_transitively`` now checks,
because the original guard only inspected each green script's own imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from config.settings import (
    BASELINES_DIR,
    BASELINE_MANIFEST_PATH,
    BASELINE_VERSION,
)
from src.detection.baseline_manifest import (
    load_manifest as load_manifest_v1,
    sha256_file,
)
from src.detection.baseline_manifest_v2 import (
    BASELINE_V1_KEY_PREFIX,
    BASELINE_V2_KEY_PREFIX,
    BASELINE_V2_LOCAL_DIR,
    BASELINE_V2_MANIFEST_PATH,
    BASELINE_V2_SUPERSEDED_MANIFEST_PATH,
    load_manifest_v2,
)
from src.processing.baseline_rebuild_v2 import (
    BASELINE_V1_VERSION,
    BASELINE_V2_SUPERSEDED_VERSION,
    BASELINE_V2_VERSION,
)

#: Schema family of each registered generation's manifest.  The two families
#: are validated by different modules and are not interchangeable.
MANIFEST_SCHEMA_V1 = "baseline-manifest-v1"
MANIFEST_SCHEMA_V2 = "baseline-manifest-v2"


class UnknownBaselineGeneration(ValueError):
    """The named baseline generation is not one a run may compare against."""


@dataclass(frozen=True)
class BaselineGeneration:
    """One baseline generation a detection run may be told to use."""

    version: str
    directory: Path
    manifest_path: Path
    key_prefix: str
    manifest_schema: str

    def load_manifest(self) -> dict[str, Any]:
        """Load and fully validate this generation's manifest."""

        if self.manifest_schema == MANIFEST_SCHEMA_V1:
            return load_manifest_v1(self.manifest_path)
        return load_manifest_v2(self.manifest_path)


#: The closed set of loadable generations.  Adding one is a visible diff that
#: has to say where its manifest and its rasters are.
BASELINE_GENERATIONS: Mapping[str, BaselineGeneration] = {
    BASELINE_V1_VERSION: BaselineGeneration(
        version=BASELINE_V1_VERSION,
        directory=Path(BASELINES_DIR),
        manifest_path=Path(BASELINE_MANIFEST_PATH),
        key_prefix=BASELINE_V1_KEY_PREFIX,
        manifest_schema=MANIFEST_SCHEMA_V1,
    ),
    BASELINE_V2_VERSION: BaselineGeneration(
        version=BASELINE_V2_VERSION,
        directory=Path(BASELINE_V2_LOCAL_DIR),
        manifest_path=Path(BASELINE_V2_MANIFEST_PATH),
        key_prefix=BASELINE_V2_KEY_PREFIX,
        manifest_schema=MANIFEST_SCHEMA_V2,
    ),
}

#: Generations that exist as audit material and must never be composed
#: against, mapped to the generation that replaced them.
SUPERSEDED_GENERATIONS: Mapping[str, str] = {
    BASELINE_V2_SUPERSEDED_VERSION: BASELINE_V2_VERSION,
}


def default_baseline_version() -> str:
    """The generation a run uses when it names none: the blue default."""

    return BASELINE_VERSION


def resolve_baseline(version: str | None = None) -> BaselineGeneration:
    """Return the registered generation for ``version``, or the default.

    Fails closed.  An unknown version is never approximated by the nearest
    registered one, and a superseded version is refused by name rather than
    silently redirected to its successor — a run that asked for ``2.0.0``
    stated an intent, and answering a different question would make the
    resulting release's ``baseline_version`` a claim nobody made.
    """

    wanted = default_baseline_version() if version is None else version
    if not isinstance(wanted, str) or not wanted.strip():
        raise UnknownBaselineGeneration(
            "baseline version must be a non-empty string"
        )
    wanted = wanted.strip()
    generation = BASELINE_GENERATIONS.get(wanted)
    if generation is not None:
        return generation
    successor = SUPERSEDED_GENERATIONS.get(wanted)
    if successor is not None:
        raise UnknownBaselineGeneration(
            f"baseline {wanted} is superseded by {successor} and is retained "
            f"only as audit material; name {successor} explicitly"
        )
    raise UnknownBaselineGeneration(
        f"baseline {wanted} is not a registered generation; registered: "
        + ", ".join(sorted(BASELINE_GENERATIONS))
    )


def superseded_manifest_path(version: str) -> Path:
    """Where a superseded generation's retained manifest lives."""

    if version != BASELINE_V2_SUPERSEDED_VERSION:
        raise UnknownBaselineGeneration(
            f"{version} is not a recorded superseded generation"
        )
    return Path(BASELINE_V2_SUPERSEDED_MANIFEST_PATH)


def verify_object_against_manifest(
    manifest_path: Path, schema: str, path: Path
) -> None:
    """Bind one raster to one manifest: name, byte length, and SHA-256.

    The single implementation of the check.  ``src/detection/baseline.py``
    calls it through its own per-path cache for the frozen v1 default, and
    :func:`verify_baseline_object` calls it through a cache keyed on the
    manifest too — the two generations share raster *filenames*, so a cache
    keyed on the path alone would let one generation's verification answer for
    the other's identically named file.  The messages are the ones the v1
    loader has raised since Package 2A.2; a test matches on them.
    """

    path = Path(path)
    if schema == MANIFEST_SCHEMA_V1:
        manifest = load_manifest_v1(Path(manifest_path))
    elif schema == MANIFEST_SCHEMA_V2:
        manifest = load_manifest_v2(Path(manifest_path))
    else:
        raise UnknownBaselineGeneration(
            f"{schema!r} is not a baseline manifest schema"
        )
    by_filename = {obj["filename"]: obj for obj in manifest["objects"]}
    expected = by_filename.get(path.name)
    if expected is None:
        raise ValueError(
            f"Baseline is not in authoritative manifest: {path.name}"
        )
    if path.stat().st_size != expected["bytes"]:
        raise ValueError(f"Baseline size does not match manifest: {path.name}")
    if sha256_file(path) != expected["sha256"]:
        raise ValueError(
            f"Baseline checksum does not match manifest: {path.name}"
        )


@lru_cache(maxsize=256)
def _verify_cached(manifest_path_text: str, schema: str, path_text: str) -> None:
    verify_object_against_manifest(
        Path(manifest_path_text), schema, Path(path_text)
    )


def verify_baseline_object(generation: BaselineGeneration, path: Path) -> None:
    """Verify one raster against ``generation``'s manifest, or raise."""

    _verify_cached(
        str(Path(generation.manifest_path)),
        generation.manifest_schema,
        str(Path(path).resolve()),
    )


def clear_verification_cache() -> None:
    """Drop memoized verifications (tests that rewrite rasters need this)."""

    _verify_cached.cache_clear()
