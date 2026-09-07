"""Every package handoff prompt ends with the owner's four questions.

`docs/operations/HANDOFF_PROMPT_METHOD.md` version 2 exists because the first
two briefings served only the executing agent: precise, and leaving the owner
to extract their own actions from three hundred lines of technical detail. The
fix is a mandatory closing section in plain language — what is still pending,
what the owner must do, whether anything is genuinely worrying, and which
stages remain.

A method that lives only in prose is a method that lapses the first time a
session is in a hurry, so it is asserted here instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

OPERATIONS = Path(__file__).parents[1] / "docs" / "operations"
METHOD = OPERATIONS / "HANDOFF_PROMPT_METHOD.md"

OWNER_HEADING = "## "
OWNER_SECTION_SUFFIX = "Para o dono — em linguagem simples"

#: The four questions, in the order the method fixes.
REQUIRED_QUESTIONS = (
    "### O que ficou pendente da tarefa atual",
    "### O que você precisa fazer",
    "### Tem algo preocupante?",
    "### O que ainda falta no caminho",
)

#: Briefings written BEFORE the method existed. Deliberately not retrofitted:
#: a "what is still pending" block added today to a briefing that was already
#: consumed would describe a present that was not its present. This list must
#: never grow in silence — adding to it is a visible diff, and a new prompt
#: belongs in the method, not in the exception.
PREDATES_THE_METHOD = frozenset(
    {"PACKAGE_2B2A_PROMPT.md", "PACKAGE_2B2B_PROMPT.md"}
)

SHA40 = re.compile(r"\b[0-9a-f]{40}\b")


def prompts() -> list[Path]:
    return sorted(OPERATIONS.glob("PACKAGE_*_PROMPT.md"))


def governed() -> list[Path]:
    return [p for p in prompts() if p.name not in PREDATES_THE_METHOD]


def owner_section(text: str) -> str | None:
    """The closing owner section, or None when it is absent."""

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(OWNER_HEADING) and line.rstrip().endswith(
            OWNER_SECTION_SUFFIX
        ):
            return "\n".join(lines[index:])
    return None


def test_there_is_at_least_one_governed_prompt():
    """Guards the whole file: an empty glob would make every test below vacuous."""

    assert governed(), (
        "no PACKAGE_*_PROMPT.md is governed by the method; either the naming "
        "changed or the exception list swallowed everything"
    )


def test_the_method_document_exists_and_declares_its_version():
    text = METHOD.read_text(encoding="utf-8")
    assert re.search(r"\*\*Método versão:\*\* `\d+`", text)
    for question in REQUIRED_QUESTIONS:
        assert question in text, f"the method must show {question!r} verbatim"


@pytest.mark.parametrize("path", governed(), ids=lambda p: p.name)
def test_the_prompt_ends_with_the_owner_section(path):
    text = path.read_text(encoding="utf-8")
    section = owner_section(text)
    assert section is not None, (
        f"{path.name} has no '{OWNER_SECTION_SUFFIX}' section; the owner would "
        "have to extract their own actions from the technical body"
    )
    # Last section: no further top-level heading may follow it.
    following = section.splitlines()[1:]
    assert not [line for line in following if line.startswith(OWNER_HEADING)], (
        f"{path.name} continues with another top-level section after the owner "
        "section; it must be the last thing the owner reads"
    )


@pytest.mark.parametrize("path", governed(), ids=lambda p: p.name)
def test_the_four_questions_are_present_and_in_order(path):
    section = owner_section(path.read_text(encoding="utf-8"))
    assert section is not None
    positions = []
    for question in REQUIRED_QUESTIONS:
        assert question in section, f"{path.name} is missing {question!r}"
        positions.append(section.index(question))
    assert positions == sorted(positions), (
        f"{path.name} asks the four questions out of order; the order is part of "
        "the method because it goes from 'what happened' to 'what is next'"
    )


@pytest.mark.parametrize("path", governed(), ids=lambda p: p.name)
def test_the_owner_section_carries_no_forty_character_sha(path):
    """Plain language means plain language.

    A SHA in this block is a sign the technical body leaked into the part
    written for someone who should not need it.
    """

    section = owner_section(path.read_text(encoding="utf-8"))
    assert section is not None
    found = SHA40.findall(section)
    assert not found, (
        f"{path.name} puts {found[0][:12]}… in the owner section; identifiers "
        "belong in the body, and only their consequence belongs here"
    )


@pytest.mark.parametrize("path", governed(), ids=lambda p: p.name)
def test_each_question_is_actually_answered(path):
    """A heading with nothing under it answers nothing.

    Cheap to satisfy and cheap to forget, which is exactly the combination
    worth asserting: "Não." is a complete answer, an empty section is not.
    """

    section = owner_section(path.read_text(encoding="utf-8"))
    assert section is not None
    for index, question in enumerate(REQUIRED_QUESTIONS):
        start = section.index(question) + len(question)
        end = (
            section.index(REQUIRED_QUESTIONS[index + 1])
            if index + 1 < len(REQUIRED_QUESTIONS)
            else len(section)
        )
        body = section[start:end].strip()
        assert len(body) >= 10, (
            f"{path.name} leaves {question!r} empty or near-empty"
        )
