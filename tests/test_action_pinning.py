"""Toda action que uma lane verde executa está pinada por SHA.

Package 2B.4, bullet *pin GitHub Actions in the green workflow files after the
full workflow inventory; do not edit blue workflow activation before Phase 6*.

Por que um SHA e não uma tag
----------------------------
Uma tag é um ponteiro móvel no repositório de outra pessoa. `actions/checkout@v4`
resolve para o que quer que `v4` aponte no dia do run, e quem move essa tag não
somos nós. As lanes verdes carregam credenciais de objeto para
``araripe-v2-staging`` — e a medição do Package 2B.3 é que uma chave
bucket-scoped `Object Read & Write` do R2 **escreve e apaga** no bucket inteiro
(``scripts/probe_readonly_identity.py``, run id ``local-2b3-measure-1``). Uma
action re-taggeada roda com essa credencial no ambiente do passo.

O inventário completo, medido em 2026-09-07, e o que ele mostrou
----------------------------------------------------------------
As lanes verdes **já estavam** 100% pinadas: todas usam
``actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683`` e nenhuma outra
action. Este arquivo não corrige nada — ele impede a regressão, que é a parte
que o bullet do roadmap realmente compra. ``v2_candidate_replay.yml`` não usa
action nenhuma: é só ``run:`` com a CLI da AWS.

O oposto vale para as azuis, e elas ficam como estão: ``detect_gee.yml``,
``update_data.yml`` e ``esa_reprocessing_watch.yml`` usam quatro actions por
tag. Mudá-las é editar workflow azul, congelado até a Phase 6 e sujeito a
aprovação humana explícita. O estado atual é **afirmado** em vez de comentado,
pelo mesmo motivo de ``tests/test_secret_exposure.py``: um fato registrado num
teste não deriva sem que alguém leia por quê.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"

#: As lanes verdes. Mesma lista de ``tests/test_secret_exposure.py``; se um
#: workflow verde novo aparecer e não for acrescentado às duas, a varredura de
#: cobertura abaixo falha.
GREEN_WORKFLOWS = (
    "v2_candidate_replay.yml",
    "v2_promotion_lane.yml",
    "v2_operational_publish.yml",
    "v2_promotion_identity_probe.yml",
    "cloudflare_green_control.yml",
)

#: Medido em 2026-09-07 lendo os arquivos. As azuis ficam assim até a Phase 6.
BLUE_UNPINNED = {
    "detect_gee.yml": {"actions/checkout@v4", "conda-incubator/setup-miniconda@v3"},
    "update_data.yml": {"actions/checkout@v4", "conda-incubator/setup-miniconda@v3"},
    "esa_reprocessing_watch.yml": {
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "actions/upload-artifact@v4",
    },
}

PINNED = re.compile(r"^[^@]+@[0-9a-f]{40}$")


def workflows() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


def uses(path: Path) -> set[str]:
    """Toda referência ``uses:`` do arquivo, em qualquer job ou passo."""

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for job in (document.get("jobs") or {}).values():
        if isinstance(job.get("uses"), str):
            found.add(job["uses"])
        for step in job.get("steps") or []:
            if isinstance(step.get("uses"), str):
                found.add(step["uses"])
    return found


@pytest.mark.parametrize("name", GREEN_WORKFLOWS)
def test_toda_action_de_lane_verde_esta_pinada_por_sha(name):
    unpinned = sorted(ref for ref in uses(WORKFLOWS / name) if not PINNED.match(ref))
    assert unpinned == [], (
        f"{name} usa {unpinned} por tag. Uma tag é um ponteiro móvel no "
        "repositório de outra pessoa, e esta lane carrega credencial de objeto "
        "para o bucket de staging."
    )


@pytest.mark.parametrize("name", sorted(BLUE_UNPINNED))
def test_a_lane_azul_usa_tags_e_isso_fica_registrado_nao_corrigido(name):
    """Congelada até a Phase 6, e o estado é afirmado para não derivar em silêncio."""

    assert {ref for ref in uses(WORKFLOWS / name) if not PINNED.match(ref)} == (
        BLUE_UNPINNED[name]
    )


def test_o_inventario_cobre_todo_workflow_do_repositorio():
    """Nem verde nem azul não existe: um arquivo novo cai em alguma das listas.

    Sem isto, um workflow verde acrescentado depois não seria varrido por nada e
    a propriedade valeria só para os arquivos que existiam quando ela foi
    escrita.
    """

    on_disk = {path.name for path in workflows()}
    classified = set(GREEN_WORKFLOWS) | set(BLUE_UNPINNED)
    assert on_disk == classified, (
        f"não classificados: {sorted(on_disk - classified)}; "
        f"listados e ausentes: {sorted(classified - on_disk)}"
    )


def test_as_lanes_verdes_compartilham_um_unico_sha_de_checkout():
    """Uma revisão pinada, não cinco. Cada SHA distinto é uma coisa a auditar."""

    green = set()
    for name in GREEN_WORKFLOWS:
        green |= uses(WORKFLOWS / name)
    checkouts = {ref for ref in green if ref.startswith("actions/checkout@")}
    assert checkouts == {"actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"}


def test_nenhuma_lane_verde_usa_action_de_terceiro():
    """Só ``actions/*``, que é a organização do próprio GitHub.

    Um SHA pinado prova imutabilidade, não procedência: ele fixa *qual* código
    roda, e não de quem ele é. Restringir o publicador é a outra metade, e é a
    que importa num passo que segura credencial.
    """

    for name in GREEN_WORKFLOWS:
        for ref in uses(WORKFLOWS / name):
            owner = ref.split("/", 1)[0]
            assert owner == "actions", (
                f"{name} usa {ref}, de {owner!r}; uma lane verde com credencial "
                "roda só actions publicadas pelo próprio GitHub"
            )
