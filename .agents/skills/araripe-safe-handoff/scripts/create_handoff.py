#!/usr/bin/env python3
"""Create an atomic, secret-free Araripe handoff checkpoint from JSON."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import selectors
import secrets
import stat
import subprocess
import time
from typing import Any
import unicodedata


SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
OPAQUE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_+./=-])[A-Za-z0-9_+./=-]{32,}(?![A-Za-z0-9_+./=-])"
)
SECRET_PATTERNS = (
    re.compile(
        r"(?i)(?:secret|password|token|authorization|cookie|credential|"
        r"api[_-]?key|access[_-]?key|signature)\s*[:=]\s*\S+"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)[?&](?:x-amz-signature|x-goog-signature|sig|signature|token)="),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
)
MAX_INPUT_BYTES = 256 * 1024
MAX_SCALAR_CHARS = 4_096
MAX_PROMPT_CHARS = 16_384
MAX_LIST_ITEMS = 100
MAX_GIT_OUTPUT_BYTES = 256 * 1024
MARKDOWN_META = frozenset("\\`*_{}[]()!|#>+-~")
REQUIRED_KEYS = {
    "slug",
    "task",
    "missing_capability",
    "target",
    "required_activation",
    "checkpoint_repository",
    "repositories",
    "safety",
    "completed",
    "mutations",
    "verification",
    "remaining",
    "resume_preflight",
    "codex_prompt",
}
SAFETY_KEYS = {
    "last_atomic_step",
    "canonical_pointer_changed",
    "canonical_pointer_evidence",
    "partial_artifact_public",
    "partial_artifact_evidence",
    "legacy_production_changed",
    "legacy_production_evidence",
    "rollback_state",
}


def _contains_secret(
    value: str,
    *,
    check_opaque: bool = True,
) -> bool:
    if any(pattern.search(value) for pattern in SECRET_PATTERNS):
        return True
    if not check_opaque:
        return False
    for match in OPAQUE_TOKEN.finditer(value):
        token = match.group(0)
        prefix = value[max(0, match.start() - 24):match.start()].lower()
        if (
            re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", token)
            and re.search(r"(?:commit|sha(?:-?256)?|checksum)\s*[:=]?\s*$", prefix)
        ):
            continue
        return True
    return False


def _sanitize_git_status(value: str, *, allowed_paths: tuple[str, ...] = ()) -> str:
    if _contains_secret(value, check_opaque=False):
        raise ValueError("Git status appears to contain a credential value")
    sanitized_lines: list[str] = []
    for line in value.splitlines():
        prefix = line[:3] if len(line) > 3 else ""
        path_text = line[3:] if len(line) > 3 else line
        sanitized_candidates: list[str] = []
        for candidate in path_text.split(" -> "):
            quoted = len(candidate) >= 2 and candidate.startswith('"') and candidate.endswith('"')
            normalized_candidate = candidate.strip('"')
            if normalized_candidate in allowed_paths:
                sanitized_candidates.append(candidate)
                continue
            pieces = re.split(r"([/\\\\])", normalized_candidate)
            for index in range(0, len(pieces), 2):
                component = pieces[index]
                if component and _contains_secret(component):
                    digest = hashlib.sha256(component.encode("utf-8")).hexdigest()
                    pieces[index] = f"<opaque-name sha256:{digest}>"
            sanitized = "".join(pieces)
            sanitized_candidates.append(f'"{sanitized}"' if quoted else sanitized)
        sanitized_lines.append(prefix + " -> ".join(sanitized_candidates))
    return "\n".join(sanitized_lines)


def _contains_unsafe_control(value: str, *, allow_newline: bool = False) -> bool:
    for character in value:
        if allow_newline and character == "\n":
            continue
        if unicodedata.category(character) in {"Cc", "Cf", "Cs"}:
            return True
    return False


def _display(value: str) -> str:
    return "".join(
        f"&#{ord(character)};" if character in MARKDOWN_META or character in "<>&" else character
        for character in value
    )


def _safe_scalar(value: Any, label: str, *, check_opaque: bool = True) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    value = value.strip()
    if len(value) > MAX_SCALAR_CHARS:
        raise ValueError(f"{label} exceeds the maximum length")
    if "\n" in value or _contains_unsafe_control(value):
        raise ValueError(f"{label} must be a single line without unsafe controls")
    if "```" in value:
        raise ValueError(f"{label} contains a Markdown fence")
    if _contains_secret(value, check_opaque=check_opaque):
        raise ValueError(f"{label} appears to contain a credential value")
    return value


def _safe_prompt(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("codex_prompt must be a non-empty string")
    value = value.strip()
    if len(value) > MAX_PROMPT_CHARS:
        raise ValueError("codex_prompt exceeds the maximum length")
    if _contains_unsafe_control(value, allow_newline=True) or "```" in value:
        raise ValueError("codex_prompt contains unsafe control text or a Markdown fence")
    if _contains_secret(value):
        raise ValueError("codex_prompt appears to contain a credential value")
    return value


def _safe_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    if len(value) > MAX_LIST_ITEMS:
        raise ValueError(f"{label} has too many entries")
    return [_safe_scalar(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _git(repo: Path, *args: str) -> str:
    command = ["git", "-C", str(repo), *args]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if process.stdout is None:
        process.kill()
        process.wait()
        raise ValueError("Git output could not be captured safely")
    selector = selectors.DefaultSelector()
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + 30
    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            events = selector.select(timeout=remaining)
            if not events:
                raise TimeoutError
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 65_536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > MAX_GIT_OUTPUT_BYTES:
                    raise ValueError("Git output exceeds the safe output limit")
                chunks.append(chunk)
        returncode = process.wait(timeout=max(0.01, deadline - time.monotonic()))
    except (TimeoutError, subprocess.TimeoutExpired):
        if process.poll() is None:
            process.kill()
            process.wait()
        raise ValueError("Git command timed out safely") from None
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    finally:
        selector.close()
        process.stdout.close()
    if returncode:
        raise ValueError(f"Git command failed safely ({args[0]}); details withheld") from None
    return b"".join(chunks).decode("utf-8", errors="replace").strip()


def _git_root(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()


def _repo_state(
    repo: Path,
    *,
    allowed_status_paths: tuple[str, ...] = (),
) -> str:
    root = _git_root(repo)
    branch = _safe_scalar(
        _git(root, "branch", "--show-current") or "DETACHED",
        "Git branch",
    )
    commit = _git(root, "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
        raise ValueError("Git commit identity is invalid")
    raw_dirty = _git(root, "status", "--short", "--untracked-files=all") or "clean"
    if _contains_unsafe_control(raw_dirty, allow_newline=True):
        raise ValueError("Git status contains unsafe control text")
    dirty = _sanitize_git_status(raw_dirty, allowed_paths=allowed_status_paths)
    return (
        f"- <code>{_display(str(root))}</code> — branch <code>{_display(branch)}</code>, "
        f"commit: {commit}, status:\n\n"
        f"<pre>{html.escape(dirty, quote=False)}</pre>"
    )


def _parse_created_at(value: Any | None) -> tuple[str, str]:
    if value is None:
        created = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    else:
        raw = _safe_scalar(value, "created_at")
        created = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        created = created.astimezone(dt.timezone.utc).replace(microsecond=0)
    return created.isoformat().replace("+00:00", "Z"), created.strftime("%Y%m%dT%H%M%SZ")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON keys are not allowed")
        result[key] = value
    return result


def _read_input(path: Path) -> Any:
    if not path.is_absolute():
        raise ValueError("--input must be an absolute path under /private/tmp")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError("--input cannot be resolved safely") from exc
    private_tmp = Path("/private/tmp").resolve(strict=True)
    try:
        resolved.relative_to(private_tmp)
    except ValueError:
        raise ValueError("--input must be stored under /private/tmp") from None
    if path != resolved:
        raise ValueError("--input must not contain symlinks or path aliases")

    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("--input must be a regular file, not a symlink")
    if metadata.st_uid != os.geteuid():
        raise ValueError("--input must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError("--input must have mode 0600")
    if metadata.st_size > MAX_INPUT_BYTES:
        raise ValueError("--input exceeds the safe size limit")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ValueError("--input changed while it was being opened")
        data = handle.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("--input exceeds the safe size limit")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("--input must be valid UTF-8 JSON") from exc
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys)


def _validated_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("handoff input must be a JSON object")
    keys = set(raw)
    unexpected = keys - (REQUIRED_KEYS | {"created_at"})
    if unexpected:
        raise ValueError("unexpected input keys are not allowed")
    missing = REQUIRED_KEYS - keys
    if missing:
        raise ValueError(f"missing input keys: {sorted(missing)}")
    if not isinstance(raw["safety"], dict) or set(raw["safety"]) != SAFETY_KEYS:
        raise ValueError("safety must contain every required assertion and no extras")
    for key in ("canonical_pointer_changed", "partial_artifact_public", "legacy_production_changed"):
        if not isinstance(raw["safety"][key], bool):
            raise ValueError(f"safety.{key} must be boolean")
    return raw


def _render(
    payload: dict[str, Any],
    *,
    created: str,
    checkpoint_relative: Path,
    repository_states: list[str],
    repository_state_note: str,
) -> str:
    scalar = {key: _safe_scalar(payload[key], key) for key in (
        "task", "missing_capability", "target", "required_activation"
    )}
    safety = payload["safety"]
    last_atomic = _safe_scalar(safety["last_atomic_step"], "safety.last_atomic_step")
    pointer_evidence = _safe_scalar(
        safety["canonical_pointer_evidence"], "safety.canonical_pointer_evidence"
    )
    public_evidence = _safe_scalar(
        safety["partial_artifact_evidence"], "safety.partial_artifact_evidence"
    )
    production_evidence = _safe_scalar(
        safety["legacy_production_evidence"], "safety.legacy_production_evidence"
    )
    rollback = _safe_scalar(safety["rollback_state"], "safety.rollback_state")
    values = {
        key: _safe_list(payload[key], key)
        for key in ("completed", "mutations", "verification", "remaining", "resume_preflight")
    }
    supplied_prompt = _safe_prompt(payload["codex_prompt"])
    prompt = (
        f"Continue the Araripe task from checkpoint `{checkpoint_relative.as_posix()}`. "
        f"Read it first and revalidate repository and live state. Missing capability: "
        f"{scalar['missing_capability']}. Required activation: {scalar['required_activation']}. "
        f"Exact target: {scalar['target']}.\n\n{supplied_prompt}"
    )

    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {_display(item)}" for item in items)

    return f"""# Recoverable handoff — {_display(scalar['task'])}

- Created (UTC): <code>{created}</code>
- Status: **BLOCKED — SAFE CHECKPOINT**
- Missing capability: {_display(scalar['missing_capability'])}
- Exact target: {_display(scalar['target'])}
- Required activation: {_display(scalar['required_activation'])}

## Safety state

- Last atomic step completed: {_display(last_atomic)}
- Canonical pointer changed: {str(safety['canonical_pointer_changed']).lower()} — {_display(pointer_evidence)}
- Partial artifact exposed publicly: {str(safety['partial_artifact_public']).lower()} — {_display(public_evidence)}
- Legacy/current production changed: {str(safety['legacy_production_changed']).lower()} — {_display(production_evidence)}
- Rollback state: {_display(rollback)}

## Repository state

{_display(repository_state_note)}

{chr(10).join(repository_states)}

## Completed

{bullets(values['completed'])}

## External mutations already made

{bullets(values['mutations'])}

## Verification performed

{bullets(values['verification'])}

## Remaining work

{bullets(values['remaining'])}

## Resume preflight

{bullets(values['resume_preflight'])}

## Codex handoff prompt

<pre>{html.escape(prompt, quote=False)}</pre>
"""


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError(f"required directory is unsafe: {path}")
    return descriptor


def _prepare_output_directory(checkpoint_repo: Path) -> tuple[Path, int]:
    docs = checkpoint_repo / "docs"
    docs_descriptor = _open_directory(docs)
    try:
        try:
            os.mkdir("handoffs", mode=0o700, dir_fd=docs_descriptor)
        except FileExistsError:
            pass
        else:
            os.fsync(docs_descriptor)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        output_descriptor = os.open("handoffs", flags, dir_fd=docs_descriptor)
    finally:
        os.close(docs_descriptor)
    if not stat.S_ISDIR(os.fstat(output_descriptor).st_mode):
        os.close(output_descriptor)
        raise ValueError("docs/handoffs is not a real directory")
    return docs / "handoffs", output_descriptor


def _write_temporary(directory_descriptor: int, target_name: str, content: str) -> str:
    temporary_name = f".{target_name}.{secrets.token_hex(12)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary_name, flags, 0o600, dir_fd=directory_descriptor)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.unlink(temporary_name, dir_fd=directory_descriptor)
        except FileNotFoundError:
            pass
        raise
    return temporary_name


def _link_checkpoint(
    directory_descriptor: int,
    temporary_name: str,
    target_name: str,
) -> tuple[int, int]:
    source = os.stat(temporary_name, dir_fd=directory_descriptor, follow_symlinks=False)
    try:
        os.link(
            temporary_name,
            target_name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileExistsError:
        raise FileExistsError(f"refusing to replace existing checkpoint: {target_name}") from None
    finally:
        try:
            os.unlink(temporary_name, dir_fd=directory_descriptor)
        except FileNotFoundError:
            pass

    current = os.stat(target_name, dir_fd=directory_descriptor, follow_symlinks=False)
    identity = (current.st_dev, current.st_ino)
    if not stat.S_ISREG(current.st_mode) or identity != (source.st_dev, source.st_ino):
        raise ValueError("checkpoint target identity changed during creation")
    os.fsync(directory_descriptor)
    return identity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()

    payload = _validated_payload(_read_input(args.input))
    slug = _safe_scalar(payload["slug"], "slug")
    if not SLUG.fullmatch(slug):
        parser.error("slug must contain lowercase letters, digits, and hyphens")

    checkpoint_repo = _git_root(
        Path(
            _safe_scalar(
                payload["checkpoint_repository"], "checkpoint_repository", check_opaque=False
            )
        ).resolve()
    )
    repositories = payload["repositories"]
    if not isinstance(repositories, list) or not repositories or len(repositories) > MAX_LIST_ITEMS:
        raise ValueError("repositories must be a non-empty bounded list")
    repository_paths = [
        Path(_safe_scalar(item, f"repositories[{index}]", check_opaque=False)).resolve()
        for index, item in enumerate(repositories)
    ]
    repository_roots = [_git_root(repo) for repo in repository_paths]
    if checkpoint_repo not in set(repository_roots):
        raise ValueError("checkpoint_repository must be included in repositories")

    created, stamp = _parse_created_at(payload.get("created_at"))
    output_root = checkpoint_repo / "docs/handoffs"
    target = output_root / f"{stamp}_{slug}.md"
    relative = target.relative_to(checkpoint_repo)
    repository_states = [
        _repo_state(
            repo,
            allowed_status_paths=(relative.as_posix(),) if repo == checkpoint_repo else (),
        )
        for repo in repository_roots
    ]
    checkpoint = _render(
        payload,
        created=created,
        checkpoint_relative=relative,
        repository_states=repository_states,
        repository_state_note=(
            "Captured immediately before the exclusive checkpoint installation. The "
            f"checkpoint itself is the expected new Git delta: ?? {relative.as_posix()}."
        ),
    )
    if _contains_secret(checkpoint, check_opaque=False):
        raise ValueError("rendered checkpoint appears to contain a credential value")

    output_root, directory_descriptor = _prepare_output_directory(checkpoint_repo)
    try:
        temporary = _write_temporary(directory_descriptor, target.name, checkpoint)
        _link_checkpoint(directory_descriptor, temporary, target.name)
    finally:
        os.close(directory_descriptor)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
