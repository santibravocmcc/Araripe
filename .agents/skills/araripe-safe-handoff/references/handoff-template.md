# Safe handoff input and output

Never put credential values, signed URLs, authorization headers, cookies,
private keys, or secret fragments in a handoff draft or checkpoint.

## Input

Copy `handoff-input.example.json` to a regular, current-user-owned, mode-`0600`
file using an absolute, non-symlink path under `/private/tmp`. Replace every
placeholder and keep each scalar field except `codex_prompt` on one line. All
four safety assertions and their evidence are mandatory. Duplicate JSON keys,
oversized fields/files, and opaque credential-like strings are rejected.

Invoke only the path on the command line:

```bash
python .agents/skills/araripe-safe-handoff/scripts/create_handoff.py \
  --input /private/tmp/araripe-handoff-input.json
```

Do not pass handoff content as command-line arguments. Remove the temporary
draft after the checkpoint has been created and reviewed.

## Output

The helper resolves `checkpoint_repository` to its Git root and writes
exclusively to `docs/handoffs/<UTC timestamp>_<slug>.md` in that repository. It
records:

- exact missing capability, target, and activation;
- last atomic step;
- explicit canonical-pointer, public-exposure, legacy-production, and rollback
  states with evidence;
- repository roots, branches, commits, and dirty state;
- completed work, external mutations, verification, remaining work, and resume
  preflight;
- a generated self-contained Codex prompt that names the checkpoint, missing
  capability, activation, and target.

The helper rejects common secret forms, multiline scalar injection, Markdown
fences, incomplete safety assertions, unsafe input/output paths, a checkpoint
repository absent from the recorded repository set, and an existing target.
It neutralizes inline HTML/Markdown and unsafe controls, rejects opaque tokens
in user fields and Git branch names, and replaces suspicious Git path
components with labelled SHA-256 digests. Only the exact expected checkpoint
path is exempted. It terminates over-limit Git capture and rejects a symlinked
`docs/handoffs`. It records repository state immediately before installation
plus the checkpoint path as the expected delta, fsyncs the
complete temporary file, installs it once through an exclusive hard link, never
replaces an existing target, and fsyncs both a newly created directory in its
parent and the final checkpoint directory.
