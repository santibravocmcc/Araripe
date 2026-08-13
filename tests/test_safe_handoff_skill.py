"""Cross-tool discovery and checkpoint tests for araripe-safe-handoff."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents/skills/araripe-safe-handoff"
PRIVATE_INPUTS: list[Path] = []


@pytest.fixture(autouse=True)
def _remove_private_inputs():
    yield
    for path in PRIVATE_INPUTS:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    PRIVATE_INPUTS.clear()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "README.md").write_text("checkpoint fixture\n", encoding="utf-8")
    docs = repo / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("handoff directory fixture\n", encoding="utf-8")
    _git(repo, "add", "README.md", "docs/README.md")
    _git(
        repo,
        "-c", "user.name=Araripe Test",
        "-c", "user.email=araripe-test@example.invalid",
        "commit", "-q", "-m", "fixture",
    )
    return repo


def _payload(repo: Path) -> dict:
    return {
        "slug": "r2-control-plane",
        "task": "Configure staging bucket CORS",
        "missing_capability": "Cloudflare control-plane connector",
        "target": "R2 bucket araripe-v2-staging",
        "required_activation": "Open the Cloudflare plugin in Codex",
        "checkpoint_repository": str(repo),
        "repositories": [str(repo)],
        "safety": {
            "last_atomic_step": "Local contract prepared",
            "canonical_pointer_changed": False,
            "canonical_pointer_evidence": "No pointer write was attempted",
            "partial_artifact_public": False,
            "partial_artifact_evidence": "No public route was attached",
            "legacy_production_changed": False,
            "legacy_production_evidence": "No live resource was mutated",
            "rollback_state": "No rollback required because no live mutation occurred",
        },
        "completed": ["Local contract prepared"],
        "mutations": ["No external mutation"],
        "verification": ["Repository status recorded"],
        "remaining": ["Configure and verify CORS"],
        "resume_preflight": ["Inspect live bucket state before mutation"],
        "codex_prompt": "Verify the staging target, configure CORS, and preserve production.",
        "created_at": "2026-08-11T18:00:00Z",
    }


def _input(tmp_path: Path, payload: dict) -> Path:
    path = Path("/private/tmp") / f"araripe-handoff-test-{uuid.uuid4().hex}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    PRIVATE_INPUTS.append(path)
    return path


def _raw_input(text: str) -> Path:
    path = Path("/private/tmp") / f"araripe-handoff-test-{uuid.uuid4().hex}.json"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    PRIVATE_INPUTS.append(path)
    return path


def _run(input_path: Path, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SKILL / "scripts/create_handoff.py"), "--input", str(input_path)],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _helper_module():
    path = SKILL / "scripts/create_handoff.py"
    spec = importlib.util.spec_from_file_location("araripe_safe_handoff_helper", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_is_exposed_to_codex_and_claude_from_one_canonical_source():
    canonical = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    adapter = (
        ROOT / ".claude/skills/araripe-safe-handoff/SKILL.md"
    ).read_text(encoding="utf-8")
    assert canonical.startswith("---\nname: araripe-safe-handoff\n")
    assert "cloudflare-control-plane" in canonical
    assert "earth-engine" in canonical
    assert "Never fall back silently to another project" in canonical
    assert "docs/handoffs/" in canonical
    assert "../../../.agents/skills/araripe-safe-handoff/SKILL.md" in adapter


def test_checkpoint_is_repo_anchored_exclusive_durable_and_self_contained(tmp_path):
    repo = _repository(tmp_path)
    input_path = _input(tmp_path, _payload(repo))
    unrelated_cwd = tmp_path / "unrelated"
    unrelated_cwd.mkdir()
    first = _run(input_path, cwd=unrelated_cwd)
    assert first.returncode == 0, first.stderr
    checkpoint = Path(first.stdout.strip())
    assert checkpoint == repo / "docs/handoffs/20260811T180000Z_r2-control-plane.md"
    assert not (unrelated_cwd / "docs/handoffs").exists()
    assert os.stat(checkpoint).st_mode & 0o077 == 0
    text = checkpoint.read_text(encoding="utf-8")
    assert "Canonical pointer changed: false" in text
    assert "Partial artifact exposed publicly: false" in text
    assert "Legacy/current production changed: false" in text
    assert "Rollback state:" in text
    assert "docs/handoffs/20260811T180000Z_r2-control-plane.md" in text
    assert "Cloudflare control-plane connector" in text
    assert "Open the Cloudflare plugin in Codex" in text
    assert "expected new Git delta" in text
    second = _run(input_path)
    assert second.returncode != 0
    assert "refusing to replace existing checkpoint" in second.stderr


@pytest.mark.parametrize(
    "secret",
    [
        "token=secret-value",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        "https://example.invalid/object?X-Amz-Signature=abcdef",
        "-----BEGIN PRIVATE KEY-----",
        "ghp_abcdefghijklmnopqrstuvwxyz123456",
        "abcdefghijklmnopqrstuvwxyzABCDEFGH123456",
        "550e8400-e29b-41d4-a716-446655440000",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature",
        "abcDEF0123_-+/=.abcDEF0123_-+/=.abcDEF",
        "aaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-cccc",
    ],
)
def test_checkpoint_rejects_secret_forms_without_passing_them_as_cli_args(tmp_path, secret):
    repo = _repository(tmp_path)
    payload = _payload(repo)
    payload["codex_prompt"] = secret
    input_path = _input(tmp_path, payload)
    result = _run(input_path)
    assert result.returncode != 0
    assert "credential value" in result.stderr or "PRIVATE KEY" in result.stderr
    assert secret not in " ".join(result.args)
    assert not (repo / "docs/handoffs").exists()


@pytest.mark.parametrize(
    "value",
    ["unsafe\n## injected heading", "unsafe ``` fence"],
)
def test_checkpoint_rejects_markdown_structure_injection(tmp_path, value):
    repo = _repository(tmp_path)
    payload = _payload(repo)
    payload["task"] = value
    result = _run(_input(tmp_path, payload))
    assert result.returncode != 0
    assert "single line" in result.stderr or "Markdown fence" in result.stderr
    assert not (repo / "docs/handoffs").exists()


@pytest.mark.parametrize("value", ["unsafe\x1b[31m", "unsafe\u202etext"])
def test_checkpoint_rejects_control_and_bidi_text(tmp_path, value):
    repo = _repository(tmp_path)
    payload = _payload(repo)
    payload["task"] = value
    result = _run(_input(tmp_path, payload))
    assert result.returncode != 0
    assert "unsafe controls" in result.stderr
    assert not (repo / "docs/handoffs").exists()


def test_checkpoint_neutralizes_block_markdown_inside_lists(tmp_path):
    repo = _repository(tmp_path)
    payload = _payload(repo)
    payload["completed"] = [
        "# heading",
        "> quote",
        "- nested item",
        "+ alternate item",
        "~strike~",
    ]
    result = _run(_input(tmp_path, payload))
    assert result.returncode == 0, result.stderr
    text = Path(result.stdout.strip()).read_text(encoding="utf-8")
    for raw in ("- # heading", "- > quote", "- - nested", "- + alternate", "~strike~"):
        assert raw not in text
    assert "&#35; heading" in text
    assert "&#62; quote" in text


def test_checkpoint_requires_all_safety_assertions(tmp_path):
    repo = _repository(tmp_path)
    payload = _payload(repo)
    del payload["safety"]["canonical_pointer_evidence"]
    result = _run(_input(tmp_path, payload))
    assert result.returncode != 0
    assert "every required assertion" in result.stderr
    assert not (repo / "docs/handoffs").exists()


def test_checkpoint_neutralizes_inline_markdown_html_and_remote_images(tmp_path):
    repo = _repository(tmp_path)
    payload = _payload(repo)
    payload["task"] = "Review `state` <!-- hidden --> ![pixel](https://example.invalid/pixel)"
    result = _run(_input(tmp_path, payload))
    assert result.returncode == 0, result.stderr
    text = Path(result.stdout.strip()).read_text(encoding="utf-8")
    assert "`state`" not in text
    assert "<!-- hidden -->" not in text
    assert "![pixel](" not in text
    assert "&#96;state&#96;" in text
    assert "&#60;&#33;&#45;&#45; hidden &#45;&#45;&#62;" in text


def test_unexpected_key_name_is_not_echoed(tmp_path):
    repo = _repository(tmp_path)
    payload = _payload(repo)
    secret_key = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    payload[secret_key] = "unexpected"
    result = _run(_input(tmp_path, payload))
    assert result.returncode != 0
    assert "unexpected input keys are not allowed" in result.stderr
    assert secret_key not in result.stderr


def test_duplicate_json_keys_are_rejected(tmp_path):
    repo = _repository(tmp_path)
    serialized = json.dumps(_payload(repo))
    duplicated = serialized.replace(
        '"slug": "r2-control-plane"',
        '"slug": "first", "slug": "r2-control-plane"',
        1,
    )
    result = _run(_raw_input(duplicated))
    assert result.returncode != 0
    assert "duplicate JSON keys are not allowed" in result.stderr


def test_input_must_be_private_regular_file_under_private_tmp(tmp_path):
    repo = _repository(tmp_path)
    outside = tmp_path / "outside-input.json"
    outside.write_text(json.dumps(_payload(repo)), encoding="utf-8")
    outside.chmod(0o600)
    outside_result = _run(outside)
    assert outside_result.returncode != 0
    assert "under /private/tmp" in outside_result.stderr

    public_input = _input(tmp_path, _payload(repo))
    public_input.chmod(0o644)
    mode_result = _run(public_input)
    assert mode_result.returncode != 0
    assert "mode 0600" in mode_result.stderr


def test_input_and_output_symlinks_are_rejected(tmp_path):
    repo = _repository(tmp_path)
    real_input = _input(tmp_path, _payload(repo))
    linked_input = Path("/private/tmp") / f"araripe-handoff-link-{uuid.uuid4().hex}.json"
    linked_input.symlink_to(real_input)
    PRIVATE_INPUTS.append(linked_input)
    input_result = _run(linked_input)
    assert input_result.returncode != 0
    assert "symlinks or path aliases" in input_result.stderr

    external = tmp_path / "external-handoffs"
    external.mkdir()
    (repo / "docs/handoffs").symlink_to(external, target_is_directory=True)
    output_result = _run(real_input)
    assert output_result.returncode != 0
    assert list(external.iterdir()) == []


def test_exclusive_install_never_replaces_an_existing_target(tmp_path):
    helper = _helper_module()
    directory = tmp_path / "handoffs"
    directory.mkdir()
    descriptor = helper._open_directory(directory)
    try:
        first = helper._write_temporary(descriptor, "checkpoint.md", "complete first\n")
        helper._link_checkpoint(descriptor, first, "checkpoint.md")
        second = helper._write_temporary(descriptor, "checkpoint.md", "replacement\n")
        with pytest.raises(FileExistsError, match="refusing to replace"):
            helper._link_checkpoint(descriptor, second, "checkpoint.md")
        assert (directory / "checkpoint.md").read_text(encoding="utf-8") == "complete first\n"
        source = (SKILL / "scripts/create_handoff.py").read_text(encoding="utf-8")
        assert "os.replace(" not in source
    finally:
        os.close(descriptor)


def test_git_capture_stops_when_stream_limit_is_crossed(tmp_path):
    helper = _helper_module()
    repo = _repository(tmp_path)
    (repo / ("x" * 80)).write_text("bounded output test\n", encoding="utf-8")
    helper.MAX_GIT_OUTPUT_BYTES = 32
    with pytest.raises(ValueError, match="safe output limit"):
        helper._git(repo, "status", "--short", "--untracked-files=all")


@pytest.mark.parametrize(
    "opaque",
    [
        "abcdefghijklmnopqrstuvwxyzABCDEFGH123456",
        "abcdEFGH1234-abcdEFGH1234-abcdEFGH1234.json",
    ],
)
def test_checkpoint_redacts_an_opaque_untracked_filename(tmp_path, opaque):
    repo = _repository(tmp_path)
    (repo / opaque).write_text("not a credential value\n", encoding="utf-8")
    result = _run(_input(tmp_path, _payload(repo)))
    assert result.returncode == 0, result.stderr
    text = Path(result.stdout.strip()).read_text(encoding="utf-8")
    assert opaque not in text
    assert "opaque-name sha256:" in text


def test_checkpoint_rejects_an_opaque_branch_name(tmp_path):
    repo = _repository(tmp_path)
    opaque = "abcdefghijklmnopqrstuvwxyzABCDEFGH123456"
    _git(repo, "checkout", "-q", "-b", opaque)
    result = _run(_input(tmp_path, _payload(repo)))
    assert result.returncode != 0
    assert "Git branch appears to contain a credential value" in result.stderr
    assert opaque not in result.stderr
    assert not (repo / "docs/handoffs").exists()


def test_git_status_redacts_suspicious_components_and_rejects_known_secrets():
    helper = _helper_module()
    status = "\n".join(
        [
            " M docs/contracts/phase1/CONFIGURATION_REGISTER_2026-07-24.md",
            "?? config/phase2a_candidate_generation_decisions_v2.json",
            "?? docs/contracts/phase2a/schemas/phase2a-candidate-generation-decisions-v2.schema.json",
        ]
    )
    sanitized = helper._sanitize_git_status(status)
    assert "CONFIGURATION_REGISTER_2026-07-24.md" not in sanitized
    assert "phase2a_candidate_generation_decisions_v2.json" not in sanitized
    assert "opaque-name sha256:" in sanitized
    with pytest.raises(ValueError, match="credential value"):
        helper._sanitize_git_status("?? token=secret-value")
