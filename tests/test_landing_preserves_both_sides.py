"""O landing do Package 2A.6 não pode apagar a Phase 2B, e o merge limpo mente.

Este arquivo existe por causa de uma medição feita em 2026-09-08, ao levar a
branch científica `claude/phase2a6d-mapbiomas` para a `main`:

* `git diff origin/main <branch>` mostrava **97 arquivos** presentes na `main` e
  ausentes na branch, entre eles os **13 módulos** de `src/publication/`. Aquele
  número assustou o briefing anterior, e estava lido errado: é um diff de dois
  pontos entre as pontas, não o que um merge aplica. **Nenhum** dos 97 existia
  no merge base, então a branch nunca os apagou — a `main` os acrescentou depois
  da divergência, e o merge de três vias os preserva. Medido: 97 de 97 sobrevivem.
* O risco real era o oposto do temido, e **silencioso**: os dois lados
  acrescentaram, cada um por sua conta, uma função `load_persistence_state` em
  regiões diferentes de um arquivo que não a tinha no merge base. Git não vê
  conflito nenhum — regiões distintas — e o módulo mesclado ficou com **duas
  definições da mesma função**, onde a segunda vence em silêncio. A da `main`
  (Package 2B.1, fail-closed contra estado ilegível) foi a sombreada.

Daí os dois testes abaixo. O primeiro fixa a superfície que não pode
desaparecer; o segundo é o que teria pegado a colisão, e pega a próxima.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]

#: Os 13 módulos de `src/publication/`, a Phase 2B inteira em código. A lista é
#: explícita de propósito: um `glob` que contasse arquivos passaria se alguém
#: trocasse um módulo por outro.
MODULOS_DE_PUBLICACAO = (
    "__init__",
    "atomic_publish",
    "canonical_json",
    "conditional_store",
    "delivery_boundary",
    "findings",
    "green_release",
    "ledger_binding",
    "ledger_gate",
    "retention",
    "run_assembler",
    "run_inputs",
    "site_artifact",
)

#: Os workflows verdes. `cloudflare_green_control.yml` é o broker protegido: se
#: ele desaparecer, o único caminho de control-plane permitido desaparece com ele.
WORKFLOWS_VERDES = (
    "cloudflare_green_control.yml",
    "v2_candidate_replay.yml",
    "v2_operational_publish.yml",
)

#: Scripts operacionais da Phase 2B que um landing não pode levar embora.
SCRIPTS_DA_PHASE_2B = (
    "assemble_green_run.py",
    "check_delivery_boundary.py",
    "cloudflare_green_control.py",
    "plan_retention.py",
    "probe_readonly_identity.py",
    "publish_green_release.py",
    "stage_green_run.py",
)


def modulos_python() -> list[Path]:
    """Todo módulo de primeira mão do repositório: `src/` e `scripts/`."""

    arquivos = sorted(
        p
        for base in ("src", "scripts")
        for p in (RAIZ / base).rglob("*.py")
        if "__pycache__" not in p.parts
    )
    assert arquivos, "a varredura não encontrou módulo nenhum — o teste seria vazio"
    return arquivos


def test_os_treze_modulos_de_publicacao_existem():
    faltando = [
        nome
        for nome in MODULOS_DE_PUBLICACAO
        if not (RAIZ / "src" / "publication" / f"{nome}.py").is_file()
    ]
    assert not faltando, (
        f"src/publication/ perdeu {faltando}. É a Phase 2B em código: o portão "
        "do ledger, a escrita condicional, a fronteira de entrega e o montador "
        "da rodada. Um landing que os remova apaga cinco packages."
    )


def test_nenhum_modulo_de_publicacao_a_mais_nem_a_menos():
    """Fixa a contagem também, para uma adição silenciosa aparecer no diff."""

    presentes = {
        p.stem
        for p in (RAIZ / "src" / "publication").glob("*.py")
        if "__pycache__" not in p.parts
    }
    assert presentes == set(MODULOS_DE_PUBLICACAO), (
        "a lista deste teste e src/publication/ divergiram: "
        f"só no disco {sorted(presentes - set(MODULOS_DE_PUBLICACAO))}, "
        f"só na lista {sorted(set(MODULOS_DE_PUBLICACAO) - presentes)}"
    )


@pytest.mark.parametrize("nome", WORKFLOWS_VERDES)
def test_os_workflows_verdes_existem(nome):
    assert (RAIZ / ".github" / "workflows" / nome).is_file(), (
        f"{nome} desapareceu. Sem o broker não há caminho de control-plane "
        "permitido, e sem as lanes v2 não há publicação verde."
    )


@pytest.mark.parametrize("nome", SCRIPTS_DA_PHASE_2B)
def test_os_scripts_operacionais_da_phase_2b_existem(nome):
    assert (RAIZ / "scripts" / nome).is_file(), f"scripts/{nome} desapareceu"


def test_os_vetores_de_conformidade_continuam_no_lugar():
    vetores = RAIZ / "docs" / "contracts" / "phase2b"
    assert vetores.is_dir(), "docs/contracts/phase2b/ desapareceu"
    assert list(vetores.rglob("*conformance_vectors.json")), (
        "os vetores de conformidade desapareceram — são a referência "
        "cruzada entre o backend em Python e o Worker em JS"
    )


def test_nenhum_modulo_define_o_mesmo_nome_de_topo_duas_vezes():
    """A guarda que teria pegado a colisão do `load_persistence_state`.

    Dois lados de um merge podem acrescentar a MESMA função em regiões
    diferentes de um arquivo. Git não reporta conflito, e Python usa a última
    definição — a primeira fica inalcançável, sem aviso, sem erro de sintaxe e
    possivelmente sem teste que a exercite pelo nome.

    Este teste lê a árvore sintática e não o texto: uma varredura textual
    acusaria a docstring acima, que menciona o nome duas vezes.
    """

    ofensas = []
    for arquivo in modulos_python():
        try:
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        except SyntaxError as e:  # marcador de conflito não resolvido, por ex.
            ofensas.append(f"{arquivo.relative_to(RAIZ)}: não parseia ({e})")
            continue
        vistos: dict[str, int] = {}
        for no in arvore.body:  # só o topo do módulo: overload em classe é legítimo
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if no.name in vistos:
                    ofensas.append(
                        f"{arquivo.relative_to(RAIZ)}: '{no.name}' definido nas "
                        f"linhas {vistos[no.name]} e {no.lineno} — a primeira é "
                        "inalcançável"
                    )
                else:
                    vistos[no.name] = no.lineno

    assert not ofensas, "definições de topo duplicadas:\n  " + "\n  ".join(ofensas)
