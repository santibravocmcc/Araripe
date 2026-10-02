"""O desenho de autoridade de publicação tem de descrever os workflows que existem.

`config/phase6_publication_authority_v1.json` responde "quem publica em
produção sem clique" (PHASE_6P). Ele é uma proposta ao dono, e uma proposta
sobre um inventário só vale enquanto o inventário for o de verdade: um job que
ganhe uma identidade sem entrar na tabela é exatamente a autoridade que a
decisão deixou de ver.

E a lição que custou caro neste projeto vira asserção: **nunca nomear um
Environment que não existe** — o GitHub o cria sem proteção e sem política de
branch. O Environment proposto para o rollback (`v2-rollback`) não existe na
medição de 2026-10-02, então nenhum workflow pode citá-lo até uma medição nova
entrar no arquivo.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "config" / "phase6_publication_authority_v1.json"
WORKFLOWS = ROOT / ".github" / "workflows"


def _decision() -> dict:
    return json.loads(DECISION.read_text(encoding="utf-8"))


def _jobs_with_an_environment() -> dict[tuple[str, str], str]:
    found = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, job in document["jobs"].items():
            environment = job.get("environment")
            if environment is not None:
                if isinstance(environment, dict):
                    environment = environment["name"]
                found[(path.name, name)] = environment
    return found


def _measured_names() -> set[str]:
    return {
        e["name"] for e in _decision()["measured"]["backend_repository"]["environments"]
    }


def test_o_inventario_nao_esta_vazio():
    """Guarda o arquivo inteiro: sem jobs, toda asserção abaixo seria vazia."""

    assert len(_jobs_with_an_environment()) >= 8


def test_todo_environment_citado_num_workflow_foi_medido():
    """Um nome fora da medição é um Environment que o GitHub criaria sem proteção."""

    named = set(_jobs_with_an_environment().values())
    unmeasured = named - _measured_names()
    assert not unmeasured, (
        f"workflows citam {sorted(unmeasured)}, que a medição de "
        f"{_decision()['measured']['measured_on']} não mostra existir. Meça com "
        "gh api .../environments e registre ANTES de citar."
    )


def test_o_environment_proposto_ainda_nao_e_citado():
    """O espelho do teste acima, para o nome que a proposta introduz."""

    proposed = {
        op["proposed"]["environment"]
        for op in _decision()["operations"]
        if isinstance(op.get("proposed"), dict)
        and op["proposed"].get("environment_exists") is False
    }
    assert proposed == {"v2-rollback"}
    assert not proposed & set(_jobs_with_an_environment().values())


def test_todo_job_com_identidade_esta_no_inventario():
    """Uma identidade nova sem linha na tabela é autoridade que a decisão não viu."""

    decision = _decision()
    listed: dict[tuple[str, str], str] = {}
    for op in decision["operations"]:
        today = op.get("today")
        if isinstance(today, dict) and "workflow" in today:
            for job in today["jobs"]:
                listed[(today["workflow"], job)] = today["environment"]
    for other in decision["other_jobs_holding_an_identity"]:
        listed[(other["workflow"], other["job"])] = other["environment"]

    assert listed == _jobs_with_an_environment()


def test_so_o_rollback_pode_andar_para_tras_e_so_ele_pede_revisor_novo():
    """A hipótese do briefing, depois de medida: o eixo é a direção, não o gatilho.

    `promote()` recusa `coverage_regression` e `coverage_dates_dropped` sem
    override (`tests/test_atomic_publish.py`, `tests/test_chain_release.py`),
    então só `rollback()` move o ponteiro para trás — e só ele ganha revisor.
    Uma publicação de rotina com revisor contradiz ROADMAP.md:97.
    """

    moves = [op for op in _decision()["operations"] if op["moves_the_pointer"]]
    reviewed = [op["operation"] for op in moves if op["proposed"]["reviewer"]]
    assert len(reviewed) == 1 and reviewed[0].startswith("rollback")
    for op in moves:
        if not op["proposed"]["reviewer"]:
            assert op["direction"].startswith("forward only"), op["operation"]


def test_a_proposta_nao_se_declara_decidida_sem_o_dono():
    decision = _decision()
    authorization = decision["authorization"]
    undecided = [p["id"] for p in decision["proposed_decisions"] if p["decided"] is None]
    if authorization["status"] == "proposed":
        assert authorization["authorized_by"] is None
        assert undecided == ["P1", "P2"]
    else:
        assert authorization["authorized_by"] == "project_owner"
        assert authorization["authorized_on"]
    assert authorization["production_mutation_permitted"] is False
