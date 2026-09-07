"""The promotion lane's inertness, and the publication CLI's boundaries.

Package 2B.0 left `v2_promotion_lane.yml` an empty placeholder and said the
real logic would arrive with the Package 2B.2 publication contract "and will
use a different protected identity — never the green candidate identity and
never Claude's local credential".  Package 2B.2B fills the lane in as far as
that allows, which means the properties worth pinning are the ones that keep
it powerless:

* it carries no Environment and names no secret, so it holds no authority at
  all, and every mode reachable from it performs no object operation;
* the two modes that would need authority stop and name the missing
  capability instead of substituting a broader credential;
* the Package 2B.0 lane identity and its outstanding four-run proof survive.

The CLI half asserts the same boundary one layer down: the production bucket
is refused by name before a credential is read, and every credentialed mode
fails closed when the promotion identity is absent — which it is.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

from src.publication import conditional_store as cs
from tests.green_release_fixtures import ALERTS, REJECTED, ZERO, build_ledger

REPO = Path(__file__).parents[1]
LANE = REPO / ".github" / "workflows" / "v2_promotion_lane.yml"
CANDIDATE = REPO / ".github" / "workflows" / "v2_candidate_replay.yml"

MODULE_PATH = REPO / "scripts" / "publish_green_release.py"
SPEC = importlib.util.spec_from_file_location("publish_green_release", MODULE_PATH)
assert SPEC and SPEC.loader
publish_cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = publish_cli
SPEC.loader.exec_module(publish_cli)

STATE_SHA = "a" * 64


@pytest.fixture(scope="module")
def lane():
    return yaml.safe_load(LANE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def lane_text():
    return LANE.read_text(encoding="utf-8")


#: The job that holds the promotion identity. Every other job in the file must
#: stay provably credential-free, so the assertions below are per JOB rather
#: than per file — the distinction the 2026-09-07 rollback wiring introduced.
AUTHORITY_JOB = "pointer"


def lane_steps(lane, job=None):
    if job is not None:
        return list(lane["jobs"][job]["steps"])
    return [step for job in lane["jobs"].values() for step in job["steps"]]


def credential_free_jobs(lane):
    return {name: job for name, job in lane["jobs"].items() if name != AUTHORITY_JOB}


def executed(run: str) -> str:
    """A run script with its heredoc bodies and comments removed.

    The lane's refusal message tells an operator how to run the promotion
    locally, so the words "apply" and "rollback" legitimately appear inside a
    heredoc.  A test asserting that no mode *performs* an object operation has
    to read what the shell executes, not what it prints.
    """

    out, tag = [], None
    for line in run.splitlines():
        if tag is not None:
            if line.strip() == tag:
                tag = None
            continue
        opener = re.search(r"<<-?'?([A-Za-z_][A-Za-z_0-9]*)'?", line)
        if opener:
            tag = opener.group(1)
            out.append(line[: opener.start()])
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def all_executed(lane) -> str:
    return "\n".join(executed(step.get("run", "")) for step in lane_steps(lane))


# ── the lane holds no authority ──────────────────────────────────────────────

def test_only_the_authority_job_declares_an_environment(lane):
    """Exactly one job may hold a credential, and it is named.

    Until 2026-09-07 no job here declared an Environment, because the protected
    promotion identity did not exist. It does now, and it is proven, so the
    property is no longer "this file holds nothing" — it is "everything except
    one named job holds nothing". That is the weaker claim, so it is asserted
    per job rather than per file.
    """

    assert lane["jobs"][AUTHORITY_JOB]["environment"] == "v2-promotion"
    for name, job in credential_free_jobs(lane).items():
        assert "environment" not in job, name


def test_only_the_authority_job_names_a_secret(lane):
    for name, job in credential_free_jobs(lane).items():
        for step in job["steps"]:
            rendered = str(step.get("env") or {}) + str(step.get("run") or "")
            assert "secrets." not in rendered, f"{name}/{step['name']}"


def test_the_authority_job_names_only_the_promotion_identity(lane):
    used = set()
    for step in lane_steps(lane, AUTHORITY_JOB):
        used |= set(re.findall(r"secrets\.([A-Za-z_0-9]+)", str(step.get("env") or {})))
    assert used == {
        "R2_PROMOTION_ACCESS_KEY_ID",
        "R2_PROMOTION_SECRET_ACCESS_KEY",
    }


def test_the_lane_never_binds_the_candidate_identity(lane, lane_text):
    """Lane 3 must not borrow lane 2's key.

    Checked as a *binding* rather than a mention: the refusal message names
    those secrets precisely to say they are the wrong ones, so the property is
    that no `secrets.` reference and no `env:` value carries them.
    """

    candidate_secrets = re.findall(
        r"secrets\.([A-Za-z_0-9]+)", CANDIDATE.read_text(encoding="utf-8")
    )
    assert candidate_secrets, "the candidate lane should hold the staging identity"
    bindings = [
        str(value)
        for step in lane_steps(lane)
        for value in (step.get("env") or {}).values()
    ]
    for name in candidate_secrets:
        assert f"secrets.{name}" not in lane_text
        assert not any(name in binding for binding in bindings)


def test_the_lane_is_dispatch_only_and_read_only(lane):
    triggers = lane[True] if True in lane else lane["on"]
    assert list(triggers) == ["workflow_dispatch"]
    assert lane["permissions"] == {"contents": "read"}


def test_the_lane_keeps_its_serialized_group(lane):
    assert lane["concurrency"] == {
        "group": "araripe-green-promotion",
        "cancel-in-progress": False,
    }


def test_no_credential_free_mode_performs_an_object_operation(lane):
    """The modes that hold nothing must still be unable to touch a bucket."""

    scripts = "\n".join(
        executed(step.get("run", ""))
        for job in credential_free_jobs(lane).values()
        for step in job["steps"]
    )
    for forbidden in ("aws s3", "boto3", "r2_state.py", "upload_to_r2", "put_object"):
        assert forbidden not in scripts
    for mutating in ("apply", "rollback", "status"):
        assert f"publish_green_release.py {mutating}" not in scripts


def test_the_lane_never_publishes_and_never_promotes(lane):
    """Rollback and status, and nothing else that writes a release.

    `promote` is deliberately absent: operational promotion belongs to
    `v2_operational_publish.yml`, which validates the run with the candidate
    identity first. Two workflows able to promote would be two paths to one
    mutable object, each blind to the other's preconditions.
    """

    invocations = set(
        re.findall(r"publish_green_release\.py\s+(\w+)", all_executed(lane))
    )
    assert invocations == {"plan", "rollback", "status"}
    assert "apply" not in invocations
    assert "publish" not in invocations


def test_promote_is_refused_here_and_says_who_owns_it(lane):
    """The refusal survived, with a different and still-true reason.

    It used to say the promotion identity was missing. That went stale the day
    the Environment was created, and a stale refusal is how this programme
    keeps losing time — so the message now names the owner instead.
    """

    step = next(
        step for step in lane_steps(lane) if "second promotion path" in step["name"]
    )
    assert step["if"] == "github.event.inputs.mode == 'promote'"
    assert "v2_operational_publish.yml" in step["run"]
    assert "missing capability" not in step["run"]
    assert step["run"].rstrip().endswith("exit 1")


def test_a_malformed_release_id_never_reaches_an_object_key(lane):
    step = next(
        step for step in lane_steps(lane, AUTHORITY_JOB)
        if "release id" in step["name"].lower()
    )
    assert step["if"] == "github.event.inputs.mode == 'rollback'"
    script = executed(step["run"])
    assert "rel-g1-" in script and "64" in script and "*[!0-9a-f]*" in script
    rollback = next(
        step for step in lane_steps(lane, AUTHORITY_JOB)
        if "deliberately" in step["name"]
    )
    assert lane_steps(lane, AUTHORITY_JOB).index(step) < lane_steps(
        lane, AUTHORITY_JOB
    ).index(rollback)


def test_the_2b0_lane_proof_mode_survives(lane):
    step = next(step for step in lane_steps(lane) if "serialized lock" in step["name"])
    assert step["if"] == "github.event.inputs.mode == 'lane-proof'"
    assert "sleep" in step["run"]


def test_the_hold_input_never_reaches_shell_arithmetic_unchecked(lane):
    """`$(( ))` evaluates its operand as an expression, not as a number."""

    step = next(step for step in lane_steps(lane) if "serialized lock" in step["name"])
    script = executed(step["run"])
    assert "*[!0-9]*" in script
    assert script.index("*[!0-9]*") < script.index("$((")


def test_the_repository_guard_is_kept(lane):
    for job in lane["jobs"].values():
        assert "github.repository == 'santibravocmcc/Araripe'" in job["if"]
        assert "workflow_dispatch" in job["if"]


def test_every_declared_mode_is_handled(lane):
    """A mode with no step would exit 0 having done nothing at all."""

    announce = next(step for step in lane_steps(lane) if "Announce" in step["name"])
    declared = re.search(r"\n\s+(contract-check\|[^)]+)\)", announce["run"])
    assert declared, "the mode allowlist should be a case pattern"
    modes = set(declared.group(1).split("|"))
    handled = {
        "contract-check": False, "plan": False, "promote": False,
        "rollback": False, "status": False, "lane-proof": False,
    }
    conditions = [step.get("if") or "" for step in lane_steps(lane)]
    conditions += [job.get("if") or "" for job in lane["jobs"].values()]
    for condition in conditions:
        for mode in list(handled):
            if f"'{mode}'" in condition:
                handled[mode] = True
    assert modes == set(handled)
    assert all(handled.values()), sorted(k for k, v in handled.items() if not v)


# ── the CLI refuses production before it reads a credential ──────────────────

def test_the_production_bucket_is_refused_by_name(monkeypatch, capsys):
    monkeypatch.setenv("R2_STAGING_BUCKET", cs.PRODUCTION_BUCKET)
    monkeypatch.setenv("R2_ENDPOINT_URL", cs.STAGING_ENDPOINT)
    monkeypatch.setenv("R2_PROMOTION_ACCESS_KEY_ID", "would-not-matter")
    monkeypatch.setenv("R2_PROMOTION_SECRET_ACCESS_KEY", "would-not-matter")
    assert publish_cli.main(["status"]) == 1
    assert "production is frozen" in capsys.readouterr().err


def test_a_credentialed_mode_fails_closed_without_the_promotion_identity(
    monkeypatch, capsys
):
    """The identity is deliberately not provisioned; nothing substitutes for it."""

    monkeypatch.setenv("R2_STAGING_BUCKET", cs.STAGING_BUCKET)
    monkeypatch.setenv("R2_ENDPOINT_URL", cs.STAGING_ENDPOINT)
    monkeypatch.delenv("R2_PROMOTION_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_PROMOTION_SECRET_ACCESS_KEY", raising=False)
    assert publish_cli.main(["rollback", "--to", "rel-g1-" + "0" * 64]) == 1
    err = capsys.readouterr().err
    assert "missing R2 credentials" in err
    assert "access_key_id" in err


def test_the_candidate_identity_is_not_read_by_the_cli():
    """Lane 3 must not borrow lane 2's key, so the CLI cannot even see it."""

    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "R2_STAGING_ACCESS_KEY_ID" not in source
    assert "R2_STAGING_SECRET_ACCESS_KEY" not in source
    assert publish_cli.ACCESS_KEY_VAR == "R2_PROMOTION_ACCESS_KEY_ID"


def test_the_cli_does_not_touch_the_blue_release_signal():
    """`data/timeseries/RELEASE.json` stays blue; 2B.2B builds beside it.

    Read from the parsed module rather than from its text, because the module
    docstring explains the boundary and naming the blue schema there is the
    point.  What must not exist is a reference the code can act on.
    """

    import ast

    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    # Identified by position, not by value: ast.get_docstring cleans the text,
    # so comparing strings would never match the raw constant.
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    assert literals, "the module should contain non-docstring string literals"
    for literal in literals:
        assert "araripe.timeseries.release" not in literal
        assert "RELEASE.json" not in literal
        assert "timeseries.db" not in literal
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any("release_signal" in name for name in imported)


# ── the CLI's plan mode: full validation, no object store ────────────────────

@pytest.fixture
def planned(tmp_path):
    document, bodies = build_ledger(
        {"2026-04-07": [ALERTS, REJECTED], "2026-04-10": [ZERO]}
    )
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps(document, indent=2))
    artifacts = []
    for row in document["terminal_rows"]:
        body = bodies.get(row["acquisition_id"])
        if body is None:
            continue
        local = tmp_path / f"{row['acquisition_id'][7:19]}.geojson"
        local.write_bytes(body)
        artifacts += [
            "--artifact",
            f"alerts/{row['observed_on']}/{local.name}={local}",
        ]
    return ledger, artifacts, document, tmp_path


def base_args(ledger):
    return [
        "--ledger", str(ledger),
        "--state-sha256", STATE_SHA,
        "--state-bytes", "126469137",
    ]


def test_plan_validates_and_reports_each_dates_classification(planned, capsys, monkeypatch):
    ledger, artifacts, *_ = planned
    monkeypatch.setattr(
        publish_cli, "build_store",
        lambda: pytest.fail("plan must not contact an object store"),
    )
    assert publish_cli.main(["plan", *base_args(ledger), *artifacts]) == 0
    out = capsys.readouterr().out
    assert "2026-04-07  alerts" in out
    assert "coverage=partial" in out
    assert "2026-04-10  zero_alerts" in out
    assert "coverage=complete" in out
    assert "sealed artifacts : 2 of 2 published" in out
    assert "plan only — no object store was contacted" in out


def test_plan_prints_the_manifest_as_json_on_request(planned, capsys):
    ledger, artifacts, *_ = planned
    assert publish_cli.main(["plan", "--json", *base_args(ledger), *artifacts]) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["schema"] == "araripe.green.release/1"
    assert manifest["release_id"].startswith("rel-g1-")


def test_an_artifact_matching_no_sealed_checksum_is_fatal(planned, tmp_path):
    """Never a quiet downgrade to `date_product`: one of the two is wrong."""

    ledger, _, _, _ = planned
    stray = tmp_path / "stray.geojson"
    stray.write_bytes(b'{"type":"FeatureCollection","features":[]}')
    with pytest.raises(SystemExit) as raised:
        publish_cli.main(
            ["plan", *base_args(ledger),
             "--artifact", f"alerts/2026-04-07/stray.geojson={stray}"]
        )
    assert "no acquisition on 2026-04-07 seals" in str(raised.value)
    assert "--product" in str(raised.value)


def test_the_same_bytes_are_accepted_as_a_date_product(planned, tmp_path, capsys):
    ledger, artifacts, *_ = planned
    stray = tmp_path / "summary.json"
    stray.write_bytes(b'{"alerts":1}')
    assert publish_cli.main(
        ["plan", *base_args(ledger), *artifacts,
         "--product", f"summary/2026-04-07.json={stray}"]
    ) == 0
    assert "date_product" in capsys.readouterr().out


def test_requiring_sealed_artifacts_is_opt_in_and_catches_a_gap(planned):
    """Not the default: a release of date-level products only is permitted."""

    ledger, artifacts, *_ = planned
    assert publish_cli.main(["plan", *base_args(ledger)]) == 1  # alerts, no object
    with pytest.raises(SystemExit) as raised:
        publish_cli.main(
            ["plan", "--require-sealed-artifacts", *base_args(ledger), *artifacts[:2]]
        )
    assert "seal an artifact checksum that no --artifact publishes" in str(raised.value)


def test_an_alert_date_with_no_object_is_reported_with_every_finding(planned, capsys):
    ledger, *_ = planned
    assert publish_cli.main(["plan", *base_args(ledger)]) == 1
    err = capsys.readouterr().err
    assert "alert_date_publishes_nothing" in err
    assert "green release rejected" in err


def test_an_ambiguous_object_path_asks_for_the_date_rather_than_guessing(
    planned, tmp_path
):
    ledger, *_ = planned
    stray = tmp_path / "summary.json"
    stray.write_bytes(b"{}")
    with pytest.raises(SystemExit) as raised:
        publish_cli.main(
            ["plan", *base_args(ledger), "--product", f"summary.json={stray}"]
        )
    assert "cannot tell which UTC date" in str(raised.value)
    assert "2026-04-07, 2026-04-10" in str(raised.value)


def test_a_malformed_object_specification_is_refused(planned):
    ledger, *_ = planned
    with pytest.raises(SystemExit) as raised:
        publish_cli.main(["plan", *base_args(ledger), "--product", "no-equals-sign"])
    assert "logical/path=local/file" in str(raised.value)


def test_a_ledger_that_is_not_a_ledger_is_reported_not_crashed(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": "2.0.0"}')
    assert publish_cli.main(
        ["plan", "--ledger", str(bad), "--state-sha256", STATE_SHA, "--state-bytes", "1"]
    ) == 1
    assert "contract_binding_mismatch" in capsys.readouterr().err
