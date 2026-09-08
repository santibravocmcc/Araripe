"""Static invariants for the audited offline reviewer gate."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (ROOT / "docs/contracts/phase2a/reviewer.js").read_text(encoding="utf-8")


def test_method_paths_are_gated_before_family_panels_are_built():
    start = SCRIPT.index("function methodSection")
    end = SCRIPT.index("function render()", start)
    section = SCRIPT[start:end]
    gate = section.index("!revealedCases.has")
    panel_build = section.index("return methodFamilies.map")
    assert gate < panel_build
    assert "primaryAssessmentComplete(review)" in section[:panel_build]
    assert 'id="reveal-methods"' in section[:panel_build]


def test_reveal_saves_and_validates_primary_before_exposing_panels():
    start = SCRIPT.index('if (reveal) reveal.addEventListener("click"')
    end = SCRIPT.index("renderProgress();", start)
    handler = SCRIPT[start:end]
    assert handler.index("saveCurrent") < handler.index("primaryAssessmentComplete")
    assert handler.index("primaryAssessmentComplete") < handler.index("revealedCases.add")
    assert handler.index("revealedCases.add") < handler.index("render();")


def test_import_rejects_method_first_records_and_reveal_locks_primary_fields():
    accept_start = SCRIPT.index("function acceptReviewExport")
    accept_end = SCRIPT.index("try {", accept_start)
    accept = SCRIPT[accept_start:accept_end]
    assert "methodAssessmentStarted(review) && !primaryAssessmentComplete(review)" in accept
    assert "throw new Error" in accept
    assert 'const primaryLocked = revealedCases.has' in SCRIPT
    for field in (
        "change-label",
        "change-reason",
        "temporal-confidence",
        "temporal-reason",
        "land-cover-context",
        "land-cover-confidence",
        "land-cover-reason",
    ):
        assert f'id="{field}"' in SCRIPT
    assert SCRIPT.count("${primaryLocked}") >= 7
    assert 'data-artifact="${name}"' in SCRIPT
    assert '${primaryLocked}> ${name}' in SCRIPT


def test_phase2a3_and_phase2a4_resume_namespaces_are_separate():
    assert 'const packagePhase = embedded.package_phase || "phase2a3";' in SCRIPT
    assert "`araripe-${packagePhase}:" in SCRIPT
    assert "packageBinding.package_id" in SCRIPT
    assert "packageBinding.review_template_sha256" in SCRIPT
    assert "packageBinding.method_evidence_index_sha256" in SCRIPT
    assert 'package_phase: "phase2a4"' in SCRIPT
    assert "reveal_state: cases.map" in SCRIPT
    assert "locked_primary" in SCRIPT


def test_phase2a4_import_is_bound_and_replaces_reveal_state_atomically():
    start = SCRIPT.index("function acceptReviewExport")
    end = SCRIPT.index("try {", start)
    accept = SCRIPT[start:end]
    assert "candidate.package_binding" in accept
    assert "immutableMethodMetadata" in accept
    assert "candidate.reveal_state" in accept
    assert "primarySnapshot(review)" in accept
    assert "revealedCases = importedRevealed" in accept
    assert "lockedPrimaryById = importedLocks" in accept


def test_reveal_snapshot_is_exported_and_locked_save_does_not_reassign_primary():
    assert "lockedPrimaryById.set(currentCase.blind_case_id, primarySnapshot(updated))" in SCRIPT
    start = SCRIPT.index("function saveCurrent")
    end = SCRIPT.index("function renderProgress", start)
    save = SCRIPT[start:end]
    guard = save.index("if (!primaryLocked)")
    assert save.index("review.change_assessment.change_label =", guard) > guard
    assert "review.change_assessment = structuredClone(locked.change_assessment)" in save
