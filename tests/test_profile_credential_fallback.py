"""The local operator's credential comes from a named AWS profile, not the environment.

``docs/operations/CLOUDFLARE_STAGING_ACCESS_FOR_CLAUDE.md`` says **"do not use
a repository `.env`"** and prescribes ``aws configure --profile
araripe-r2-staging`` plus ``export AWS_PROFILE``.  Every green call site passed
the key explicitly from ``R2_STAGING_*``, so the prescribed profile was never
consulted: a local deposit could only happen by exporting the secret into the
process environment, which is the exposure the document exists to prevent.
``docs/implementation/PHASE_2B_GATE_2026-09-08.md`` §"Para o depósito" carries
exactly that recipe — ``aws configure export-credentials --format env`` — and
this package supersedes it.

Each test below names the mutation it kills, because a test that passes for the
wrong reason is this line of work's standing trap.  The two that matter most
are the *negative* ones: making the fallback the default, or opting the
promotion CLI in, would both leave every test here green if they only checked
the happy path.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.publication import conditional_store as cs  # noqa: E402

SCRIPTS = ROOT / "scripts"

#: Exactly the two lane-2 entry points.  A third name appearing here is a
#: decision, not a refactor.
OPTED_IN = {"assemble_green_run.py", "stage_green_run.py"}

PROFILE = "araripe-r2-staging-test-double"


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """A named profile in a throwaway credentials file, never the real one.

    ``AWS_SHARED_CREDENTIALS_FILE`` is botocore's own override, so this stays
    offline and cannot read ``~/.aws/credentials``.
    """

    path = tmp_path / "credentials"
    path.write_text(
        f"[{PROFILE}]\n"
        "aws_access_key_id = AKIAoffline\n"
        "aws_secret_access_key = offline-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(path))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "config"))
    monkeypatch.setenv(cs.PROFILE_VAR, PROFILE)
    return path


def no_explicit_credential() -> dict[str, str]:
    return {"access_key_id": "", "secret_access_key": "", "region": "auto"}


# ── the behaviour the package adds ───────────────────────────────────────────

def test_an_opted_in_call_site_resolves_the_named_profile(profile):
    """Mutation killed: dropping the profile branch entirely.

    Without it this raises "missing R2 credentials", which is precisely the
    state Phase 4 was blocked in while the credential existed all along.
    """

    client = cs.build_client(
        cs.STAGING_BUCKET,
        cs.STAGING_ENDPOINT,
        no_explicit_credential(),
        profile_fallback=True,
    )
    resolved = client._request_signer._credentials
    assert resolved.access_key == "AKIAoffline"


def test_the_secret_never_enters_this_process_environment(profile, monkeypatch):
    """The point of the profile: no credential name is set anywhere.

    Mutation killed: "just export the two variables from the profile", the
    recipe PHASE_2B_GATE_2026-09-08.md carries.  It would work and would put
    the secret in ``os.environ``, where any later command or traceback can
    print it.
    """

    import os

    cs.build_client(
        cs.STAGING_BUCKET,
        cs.STAGING_ENDPOINT,
        no_explicit_credential(),
        profile_fallback=True,
    )
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "R2_STAGING_ACCESS_KEY_ID",
        "R2_STAGING_SECRET_ACCESS_KEY",
    ):
        assert name not in os.environ, f"{name} was set into the environment"


def test_an_explicit_credential_still_wins_so_the_lane_is_unchanged(profile):
    """Mutation killed: preferring the profile over the explicit values.

    ``v2_operational_publish.yml`` passes ``R2_STAGING_*`` from its
    Environment.  If the profile took precedence, a runner that happened to
    carry ``AWS_PROFILE`` would silently use a different identity than the
    Environment granted.
    """

    client = cs.build_client(
        cs.STAGING_BUCKET,
        cs.STAGING_ENDPOINT,
        {
            "access_key_id": "AKIAfromthelane",
            "secret_access_key": "lane-secret",
            "region": "auto",
        },
        profile_fallback=True,
    )
    assert client._request_signer._credentials.access_key == "AKIAfromthelane"


# ── the refusals that must survive ──────────────────────────────────────────

def test_without_opting_in_a_missing_credential_is_still_named(profile):
    """Mutation killed: making ``profile_fallback`` default to ``True``.

    This is the load-bearing negative test.  ``AWS_PROFILE`` is set and a
    usable profile exists, and the refusal must still happen, because
    ``scripts/publish_green_release.py`` reaches this function with the
    *promotion* identity.
    """

    with pytest.raises(cs.ObjectStoreError, match="missing R2 credentials"):
        cs.build_client(
            cs.STAGING_BUCKET, cs.STAGING_ENDPOINT, no_explicit_credential()
        )


def test_a_half_set_credential_is_refused_even_with_a_profile(profile):
    """Mutation killed: ``not any(...)`` relaxed to ``not all(...)``.

    One value set and the other missing is a configuration error.  Silently
    replacing the pair with a profile would hide a typo in a secret name.
    """

    with pytest.raises(cs.ObjectStoreError, match="secret_access_key"):
        cs.build_client(
            cs.STAGING_BUCKET,
            cs.STAGING_ENDPOINT,
            {"access_key_id": "AKIAhalf", "secret_access_key": "", "region": "auto"},
            profile_fallback=True,
        )


@pytest.mark.parametrize("value", ["", "   "])
def test_an_unset_or_blank_profile_still_fails_closed(monkeypatch, value):
    """Mutation killed: dropping ``.strip()``, or testing the variable's presence.

    ``AWS_PROFILE=""`` must not be read as "use the default chain": that is how
    instance metadata or a ``[default]`` profile nobody named gets picked up.
    """

    monkeypatch.setenv(cs.PROFILE_VAR, value)
    with pytest.raises(cs.ObjectStoreError, match="missing R2 credentials"):
        cs.build_client(
            cs.STAGING_BUCKET,
            cs.STAGING_ENDPOINT,
            no_explicit_credential(),
            profile_fallback=True,
        )


def test_a_named_profile_that_does_not_exist_is_a_refusal(tmp_path, monkeypatch):
    """Mutation killed: swallowing ``ProfileNotFound`` and carrying on.

    A typo'd profile name must stop here as a named refusal, not fall through
    to whatever else the chain can find.

    **Measured, so the ``except`` is placed rather than guessed:** botocore
    raises ``ProfileNotFound`` from ``boto3.Session(...)``'s *constructor*, not
    lazily from ``get_credentials()`` — so wrapping the construction is
    sufficient and wrapping only the credential lookup would miss it.

    A mutation that does **not** distinguish anything, recorded so it is not
    re-tried as a test: replacing ``Session(profile_name=profile)`` with a bare
    ``Session()``.  With ``AWS_PROFILE`` set — which this branch requires —
    boto3 reads the same variable and raises identically.  Passing the value
    that was gated on keeps the code using exactly the string it checked; it is
    not a second line of defence and this file does not claim it is.
    """

    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "absent"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "absent-config"))
    monkeypatch.setenv(cs.PROFILE_VAR, "no-such-profile")
    with pytest.raises(cs.ObjectStoreError, match="no usable AWS profile"):
        cs.build_client(
            cs.STAGING_BUCKET,
            cs.STAGING_ENDPOINT,
            no_explicit_credential(),
            profile_fallback=True,
        )


def test_a_profile_resolving_no_credential_is_a_refusal(tmp_path, monkeypatch):
    """Mutation killed: trusting ``Session`` to raise on an empty profile.

    A profile section that exists but carries no key pair builds a Session
    without error; the refusal has to be asked for.
    """

    path = tmp_path / "credentials"
    path.write_text("[empty-profile]\nregion = auto\n", encoding="utf-8")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(path))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "config"))
    monkeypatch.setenv(cs.PROFILE_VAR, "empty-profile")
    with pytest.raises(cs.ObjectStoreError, match="resolved no credential"):
        cs.build_client(
            cs.STAGING_BUCKET,
            cs.STAGING_ENDPOINT,
            no_explicit_credential(),
            profile_fallback=True,
        )


@pytest.mark.parametrize(
    "bucket,expected",
    [
        (cs.PRODUCTION_BUCKET, "production is frozen"),
        ("some-other-bucket", "targets only"),
    ],
)
def test_a_wrong_bucket_is_refused_on_the_profile_route_too(profile, bucket, expected):
    """A wrong bucket is refused by name whatever the credential route is.

    ``tests/test_conditional_store.py`` proves this for the explicit path; the
    new branch needs its own case.  This says nothing about *ordering* — see
    the next test, which is where the first draft of this file was wrong.
    """

    with pytest.raises(cs.ObjectStoreError, match=expected):
        cs.build_client(
            bucket, cs.STAGING_ENDPOINT, no_explicit_credential(), profile_fallback=True
        )


def test_the_target_guard_runs_before_any_credential_route(tmp_path, monkeypatch):
    """Mutation killed: moving ``assert_staging_target`` below the fallback.

    The first version of this test asserted only that a wrong bucket raises
    ``ObjectStoreError``, and it **survived** that mutation: the guard placed
    last still raises, just after a credential has been resolved.  A test that
    cannot tell the two apart is the "passes for the wrong reason" trap this
    line of work has paid for repeatedly.

    Two failures are arranged at once — a forbidden bucket *and* an
    unresolvable profile — and the guard's position decides which one speaks.
    Guard first: the bucket. Guard last: the profile, which means the target
    check happened after boto3 had already been handed an identity.
    """

    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "absent"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "absent-config"))
    monkeypatch.setenv(cs.PROFILE_VAR, "no-such-profile")

    with pytest.raises(cs.ObjectStoreError) as raised:
        cs.build_client(
            cs.PRODUCTION_BUCKET,
            cs.STAGING_ENDPOINT,
            no_explicit_credential(),
            profile_fallback=True,
        )
    message = str(raised.value)
    assert "production is frozen" in message
    assert "profile" not in message, (
        "the profile was consulted before the target guard refused the bucket"
    )


# ── who is allowed to opt in, read from the sources ─────────────────────────

def opt_in_flags(path: Path) -> list[bool]:
    """Every ``build_client`` call in one script, and whether it opted in.

    Read with the AST rather than by string search: a docstring naming
    ``profile_fallback=True`` — and the ones in these scripts do — would make a
    grep-based sweep pass while the call itself did the opposite.  That
    mistake has been made three times on this line of work.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    flags = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "build_client":
            continue
        opted = any(
            kw.arg == "profile_fallback"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in node.keywords
        )
        flags.append(opted)
    return flags


def test_only_the_two_lane_two_entry_points_opt_in():
    """Mutation killed: opting the promotion CLI in, or a third script.

    ``PROMOTION_IDENTITY_SETUP.md``: *"if the two lanes used the same key, any
    candidate run could move the pointer. Separating them is what makes
    'publish' and 'promote' two different authorities."*  A shell holding
    ``AWS_PROFILE=araripe-r2-staging`` must not be able to publish a release
    and move the green pointer with the candidate key.

    Swept over every script rather than asserted about one, so a future entry
    point cannot opt in unnoticed.
    """

    opted_in = set()
    called = set()
    for path in sorted(SCRIPTS.glob("*.py")):
        flags = opt_in_flags(path)
        if flags:
            called.add(path.name)
        if any(flags):
            opted_in.add(path.name)

    assert "publish_green_release.py" in called, (
        "the promotion CLI no longer calls build_client; this sweep has "
        "stopped measuring what it claims to"
    )
    assert opted_in == OPTED_IN, (
        f"scripts opting into the profile fallback are {sorted(opted_in)}, "
        f"expected exactly {sorted(OPTED_IN)}"
    )


def test_every_build_client_call_in_the_promotion_cli_refuses_the_fallback():
    """The same property stated positively about the file that matters most."""

    flags = opt_in_flags(SCRIPTS / "publish_green_release.py")
    assert flags and not any(flags)


def test_the_publication_lane_needs_no_new_environment_name():
    """Mutation killed: "solve it in the workflow instead".

    The fix is in the library precisely so ``v2_operational_publish.yml`` stays
    byte-identical — its explicit variables take the unchanged branch. A
    generic ``AWS_*`` name reappearing there would put the key back into
    boto3's default chain, past the bucket guard, which is the defect
    ``tests/test_secret_exposure.py`` records.
    """

    source = (
        ROOT / ".github/workflows/v2_operational_publish.yml"
    ).read_text(encoding="utf-8")
    assert "AWS_ACCESS_KEY_ID:" not in source
    assert "AWS_SECRET_ACCESS_KEY:" not in source
    assert "AWS_PROFILE" not in source
