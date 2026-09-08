"""No step may hold a secret it does not use.

Package 2B.3: *introduce least-privilege credentials and step-level secret
exposure.*  The first half is a Cloudflare question — measured in
``docs/operations/GREEN_LEAST_PRIVILEGE_IDENTITIES.md`` and, unavoidably, the
owner's to act on.  The second half is entirely inside these files, and it is
what this suite pins.

Two properties, and the second one caught something real.

1. **A secret is exposed at the step that uses it, never at the job.**  A
   job-level ``env:`` puts the credential in *every* step's environment,
   including checkout, `pip install`, and anything a future edit adds.  Every
   green workflow already did this; without a test it stays true by habit.

2. **A step that runs a repository script may expose only the names that
   script reads.**  ``v2_operational_publish.yml`` exported the candidate key
   twice — once as ``R2_STAGING_*``, which ``stage_green_run.py`` reads, and
   once as ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY``, which nothing
   reads.  The unused pair was not inert: it put the credential into boto3's
   **default** chain, so an AWS call that never went through ``build_client``
   and its bucket guard would have been authenticated anyway.  Measured
   2026-09-07: that key writes *and* deletes inside ``araripe-v2-staging``
   (``scripts/probe_readonly_identity.py``, run id ``local-2b3-measure-1``).

Read from the files, so a future workflow inherits the sweep.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).parents[1] / ".github/workflows"
SCRIPTS = Path(__file__).parents[1] / "scripts"

#: Workflow files whose steps run this repository's Python entry points.  The
#: blue files are read for contrast and are never edited by a green package.
GREEN_WORKFLOWS = (
    "v2_candidate_replay.yml",
    "v2_promotion_lane.yml",
    "v2_operational_publish.yml",
    "v2_promotion_identity_probe.yml",
)

SECRET_REFERENCE = re.compile(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}")
SCRIPT_CALL = re.compile(r"python3?\s+(scripts/[A-Za-z0-9_./-]+\.py)")
ENV_READ = re.compile(r"""os\.environ(?:\.get\(|\[)["']([A-Za-z0-9_]+)["']""")
#: Names bound to a module constant rather than written inline, e.g.
#: ``ACCESS_KEY_VAR = "R2_STAGING_ACCESS_KEY_ID"`` then ``os.environ.get(...)``.
ENV_CONSTANT = re.compile(r"""^[A-Z][A-Z0-9_]*\s*=\s*["']([A-Z][A-Z0-9_]+)["']""", re.M)


def workflows():
    return sorted(path for path in WORKFLOWS.glob("*.yml"))


def loaded(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def env_names_read_by(script: Path) -> set[str]:
    source = script.read_text(encoding="utf-8")
    return set(ENV_READ.findall(source)) | set(ENV_CONSTANT.findall(source))


def job_level_secrets(path: Path) -> dict[str, list[str]]:
    document = loaded(path)
    return {
        name: sorted(set(SECRET_REFERENCE.findall(str(job.get("env") or {}))))
        for name, job in (document.get("jobs") or {}).items()
        if SECRET_REFERENCE.findall(str(job.get("env") or {}))
    }


@pytest.mark.parametrize("name", GREEN_WORKFLOWS)
def test_no_green_workflow_exposes_a_secret_above_the_step_that_uses_it(name):
    """A job-level ``env:`` hands the credential to every step in the job.

    Including ``actions/checkout``, ``pip install``, and whatever a later edit
    adds between them.  Every green workflow already places its secrets at the
    step; without this the property survives only as a habit.
    """

    path = WORKFLOWS / name
    document = loaded(path)
    assert not SECRET_REFERENCE.findall(str(document.get("env") or {})), (
        f"{name} references a secret in a workflow-level env"
    )
    assert job_level_secrets(path) == {}, (
        f"{name} exposes a secret to every step in a job; a secret belongs in "
        "the env of the step that uses it"
    )


BLUE_JOB_LEVEL_SECRETS = {
    "detect_gee.yml": {
        "detect-gee": ["GEE_SA_KEY", "R2_ACCESS_KEY", "R2_ENDPOINT_URL", "R2_SECRET_KEY"]
    },
    "esa_reprocessing_watch.yml": {"watch": ["GEE_SA_KEY"]},
    "update_data.yml": {
        "detect": ["R2_ACCESS_KEY", "R2_ENDPOINT_URL", "R2_SECRET_KEY"]
    },
}


@pytest.mark.parametrize("name", sorted(BLUE_JOB_LEVEL_SECRETS))
def test_the_blue_lane_does_not_have_this_property_and_is_recorded_not_fixed(name):
    """Measured 2026-09-07, and deliberately left alone.

    The blue workflows expose their production credentials at the job, so every
    step of a blue run — including checkout — holds ``R2_ACCESS_KEY`` and
    ``GEE_SA_KEY``.  Narrowing that is a change to a blue workflow, which is
    frozen through Phase 6 and needs explicit human approval; doing it inside a
    green package would be exactly the silent production edit the freeze
    exists to prevent.

    Recording it as an assertion rather than a comment means it cannot drift
    unnoticed: if a blue file changes, this fails and someone reads why.
    """

    assert job_level_secrets(WORKFLOWS / name) == BLUE_JOB_LEVEL_SECRETS[name]


@pytest.mark.parametrize("name", GREEN_WORKFLOWS)
def test_a_step_running_a_repository_script_exposes_only_names_it_reads(name):
    """The unused-credential sweep, read from both files.

    A step may still export a name the script does not read if no script runs
    in it — ``v2_candidate_replay.yml`` calls the ``aws`` CLI, which requires
    ``AWS_ACCESS_KEY_ID`` by name — so the rule applies exactly where the
    consumer is knowable.
    """

    document = loaded(WORKFLOWS / name)
    checked = 0
    for job_name, job in (document.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            run = step.get("run") or ""
            scripts = SCRIPT_CALL.findall(run)
            if not scripts:
                continue
            exposed = {
                var
                for var, value in (step.get("env") or {}).items()
                if SECRET_REFERENCE.search(str(value))
            }
            if not exposed:
                continue
            read: set[str] = set()
            for script in scripts:
                path = SCRIPTS.parent / script
                assert path.exists(), f"{name} runs {script}, which is absent"
                read |= env_names_read_by(path)
            unused = exposed - read
            assert not unused, (
                f"{name}:{job_name} exposes {sorted(unused)} to a step that runs "
                f"{scripts}, and no such script reads those names. An unused "
                "credential name is not inert: AWS_ACCESS_KEY_ID puts the key "
                "into boto3's default chain, past the bucket guard."
            )
            checked += 1
    # ``v2_candidate_replay.yml`` legitimately checks nothing here: its
    # credentialled steps run the ``aws`` CLI rather than a repository script,
    # so the consumer of the names is not knowable from this repository. That
    # case is covered by
    # ``test_the_candidate_lane_still_needs_the_generic_names_and_says_why``.
    assert checked or name == "v2_candidate_replay.yml"


def test_the_staging_job_no_longer_exports_the_key_under_generic_aws_names():
    """The specific narrowing this package made, pinned so it stays made."""

    source = (WORKFLOWS / "v2_operational_publish.yml").read_text(encoding="utf-8")
    assert "R2_STAGING_ACCESS_KEY_ID: ${{ secrets.R2_STAGING_ACCESS_KEY_ID }}" in source
    assert "AWS_ACCESS_KEY_ID:" not in source
    assert "AWS_SECRET_ACCESS_KEY:" not in source


def test_the_candidate_lane_still_needs_the_generic_names_and_says_why():
    """The contrast case: the aws CLI reads those names, so the exposure is used.

    Asserted rather than assumed, because "this one is different" is the shape
    of an exception that later swallows the rule.
    """

    document = loaded(WORKFLOWS / "v2_candidate_replay.yml")
    steps = document["jobs"]["green-isolation-probe"]["steps"]
    credentialled = [
        step for step in steps
        if SECRET_REFERENCE.search(str(step.get("env") or {}))
    ]
    assert credentialled
    for step in credentialled:
        assert "aws " in (step.get("run") or ""), (
            "a step in the candidate lane holds a credential without running "
            "the aws CLI; it should read R2_STAGING_* through Python instead"
        )
        assert "AWS_ACCESS_KEY_ID" in step["env"]


@pytest.mark.parametrize("path", workflows(), ids=lambda p: p.name)
def test_no_workflow_prints_a_secret(path):
    """A secret interpolated into a ``run:`` body reaches the log verbatim.

    GitHub masks known secret *values*, but only where it recognises them; a
    value derived from one, or echoed after transformation, is not masked. The
    rule is simpler than the masking: never put the expression in the command.
    """

    document = loaded(path)
    for job_name, job in (document.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            body = step.get("run") or ""
            found = SECRET_REFERENCE.findall(body)
            assert not found, (
                f"{path.name}:{job_name} interpolates {found} into a run body; "
                "pass it through env instead"
            )


def test_the_two_green_identities_are_never_exposed_in_one_step():
    """Publish and promote are two authorities, and one step holding both undoes that.

    ``PROMOTION_IDENTITY_SETUP.md``: *if the two lanes used the same key, any
    candidate run could move the pointer.*  The split is enforced at the file
    level in ``tests/test_operational_publish_lane.py``; this is the same
    property one level down, at the step.
    """

    for path in workflows():
        document = loaded(path)
        for job_name, job in (document.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                names = set(SECRET_REFERENCE.findall(str(step.get("env") or {})))
                staging = {n for n in names if n.startswith("R2_STAGING")}
                promotion = {n for n in names if n.startswith("R2_PROMOTION")}
                assert not (staging and promotion), (
                    f"{path.name}:{job_name} exposes the candidate and the "
                    "promotion identity to one step"
                )
