"""A folha da virada (`docs/operations/PHASE_6_CUTOVER_RUNSHEET.md`) tem forma.

PHASE_6Z_2026-10-13. A folha é o roteiro do primeiro dia em que o público vê
outra coisa, e os erros plausíveis nela não são de prosa: um passo sem caminho
de volta, um merge na `main` do site (que é um deploy) sem a aprovação do dono,
o desligamento do `r2.dev` antes da troca do consumidor, um hostname copiado
errado, ou uma operação de broker que não existe. Cada um deles é afirmado
aqui, porque um método que só vive em prosa falha na primeira sessão apressada.

O texto é normalizado com ``" ".join(text.split())`` antes de qualquer busca de
frase: uma quebra de linha no meio derrotava os guardas de string literal.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
RUNSHEET = ROOT / "docs" / "operations" / "PHASE_6_CUTOVER_RUNSHEET.md"
MIGRATION = ROOT / "docs" / "operations" / "GREEN_RETENTION_AND_MIGRATION.md"
BROKER = ROOT / "scripts" / "cloudflare_green_control.py"
WORKFLOWS = ROOT / ".github" / "workflows"

FIELDS = ("Quem", "Aprovação", "Antes", "Faz", "Depois", "Volta")
STEP = re.compile(r"^### ([ABC]\d+)(?: \([^)]*\))?\. ", re.M)
OWNER = "dono, explícita"
#: Verbos de "Faz" que mudam produção, credencial ou o painel: o passo tem de
#: pedir o dono. Mesclar na `main` do site é deploy.
NEEDS_OWNER = ("mescla", "merge", "painel", "revoga", "rollback", "disable", "desabilita")
BLUE_HOST = re.compile(r"pub-[0-9a-f]{32}\.r2\.dev")


def normalized(text: str) -> str:
    return " ".join(text.split())


def steps() -> dict[str, dict[str, str]]:
    text = RUNSHEET.read_text(encoding="utf-8")
    heads = list(STEP.finditer(text))
    out: dict[str, dict[str, str]] = {}
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[head.end():end].split("\n## ")[0]
        fields = re.findall(r"^- \*\*([^*]+):\*\* (.*?)(?=^- \*\*|\Z)", body, re.M | re.S)
        out[head.group(1)] = {name: normalized(value) for name, value in fields}
        out[head.group(1)]["_order"] = tuple(name for name, _ in fields)
    return out


def test_the_runsheet_has_the_three_phases():
    ids = list(steps())
    assert ids, "no step found; the heading format changed"
    for phase in "ABC":
        assert any(i.startswith(phase) for i in ids), f"phase {phase} has no step"


def test_every_step_has_the_six_fields_in_order():
    for step, fields in steps().items():
        assert fields["_order"] == FIELDS, f"{step}: {fields['_order']}"
        for name in FIELDS:
            assert fields[name].strip(), f"{step}: field {name} is empty"


def test_every_step_that_merges_or_touches_the_dashboard_needs_the_owner():
    for step, fields in steps().items():
        action = fields["Faz"].lower()
        if any(verb in action for verb in NEEDS_OWNER):
            assert fields["Aprovação"].startswith(OWNER), (
                f"{step} does {action[:80]!r} with approval {fields['Aprovação']!r}"
            )


def test_every_phase_b_and_c_step_says_how_to_go_back():
    for step, fields in steps().items():
        if step[0] in "BC":
            assert len(fields["Volta"]) > len("nada"), step


def _first_step(predicate) -> str:
    for step, fields in steps().items():
        if predicate(fields["Faz"]):
            return step
    raise AssertionError("no step matches")


def _position(step: str) -> int:
    return list(steps()).index(step)


def test_the_public_switch_comes_after_the_route_and_before_the_blue_path_is_disabled():
    route = _first_step(lambda f: "merge da PR de A2" in f)
    switch = _first_step(lambda f: "FONTE_PADRAO" in f and "merge" in f.lower())
    disable = _first_step(lambda f: "acesso público" in f and "desabilita" in f)
    stop_blue = _first_step(lambda f: "gh workflow disable detect_gee.yml" in f)
    schedule = _first_step(lambda f: "merge da PR de A5" in f)
    assert _position(route) < _position(switch) < _position(disable), (route, switch, disable)
    assert _position(schedule) < _position(stop_blue), (schedule, stop_blue)


def test_the_blue_hostname_is_the_recorded_one_and_only_one():
    text = RUNSHEET.read_text(encoding="utf-8")
    recorded = set(BLUE_HOST.findall(MIGRATION.read_text(encoding="utf-8")))
    written = set(BLUE_HOST.findall(text))
    assert len(recorded) == 1, recorded
    assert written == recorded, (written, recorded)


def _allowed_operations() -> tuple[str, ...]:
    tree = ast.parse(BROKER.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ALLOWED_OPERATIONS" for t in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("ALLOWED_OPERATIONS not found in the broker")


def test_the_runsheet_names_exactly_the_broker_operations_that_exist():
    text = normalized(RUNSHEET.read_text(encoding="utf-8"))
    match = re.search(r"só fecha \(([^)]*)\)", text)
    assert match, "the boundary sentence about the broker is gone"
    named = tuple(re.findall(r"`([a-z-]+)`", match.group(1)))
    assert named == _allowed_operations()


def test_every_backend_workflow_the_runsheet_names_exists():
    text = RUNSHEET.read_text(encoding="utf-8")
    named = set(re.findall(r"\b((?:v2_[a-z0-9_]+|detect_gee|update_data|cloudflare_green_control)\.yml)\b", text))
    assert named, "the runsheet names no backend workflow; the pattern changed"
    missing = sorted(n for n in named if not (WORKFLOWS / n).exists())
    assert not missing, missing
