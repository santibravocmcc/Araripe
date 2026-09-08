"""Static invariants for the isolated Phase 2A.5 reviewer gate."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT / "docs/contracts/phase2a/phase2a5-reviewer.js"
).read_text(encoding="utf-8")


def test_all_five_families_are_gated_before_panels_are_built():
    assert (
        'const methodFamilies = ["cloud_mask", "daily_composition", '
        '"drought_adjustment", "mapbiomas", "contextual_signature"]'
        in SCRIPT
    )
    start = SCRIPT.index("function methodSection")
    end = SCRIPT.index("function render()", start)
    section = SCRIPT[start:end]
    gate = section.index("!revealedCases.has")
    panel_build = section.index("return methodFamilies.map")
    assert gate < panel_build
    assert "primaryAssessmentComplete(review)" in section[:panel_build]
    assert 'id="reveal-methods"' in section[:panel_build]


def test_primary_gate_and_lock_include_contextual_signature_fields():
    primary_start = SCRIPT.index("function primaryAssessmentComplete")
    primary_end = SCRIPT.index("function methodAssessmentStarted", primary_start)
    primary = SCRIPT[primary_start:primary_end]
    assert "review.contextual_signature.label" in primary
    assert "review.contextual_signature.reason" in primary
    snapshot_start = SCRIPT.index("function primarySnapshot")
    snapshot_end = SCRIPT.index("function sameValue", snapshot_start)
    assert "contextual_signature: review.contextual_signature" in SCRIPT[
        snapshot_start:snapshot_end
    ]
    assert 'id="signature-label" ${primaryLocked}' in SCRIPT
    assert 'id="signature-reason" ${primaryLocked}' in SCRIPT
    locked_start = SCRIPT.index("const locked = lockedPrimaryById.get")
    assert (
        "review.contextual_signature = structuredClone(locked.contextual_signature)"
        in SCRIPT[locked_start:]
    )


def test_reveal_saves_validates_snapshots_then_renders_panels():
    start = SCRIPT.index('if (reveal) reveal.addEventListener("click"')
    end = SCRIPT.index("renderProgress();", start)
    handler = SCRIPT[start:end]
    assert handler.index("saveCurrent") < handler.index("primaryAssessmentComplete")
    assert handler.index("primarySnapshot") < handler.index("revealedCases.add")
    assert handler.index("revealedCases.add") < handler.index("render();")


def test_resume_export_is_package_bound_and_rejects_method_first_state():
    accept_start = SCRIPT.index("function acceptReviewExport")
    accept_end = SCRIPT.index("try {", accept_start)
    accept = SCRIPT[accept_start:accept_end]
    assert "candidate.package_binding" in accept
    assert "immutableMethodMetadata" in accept
    assert "candidate.reveal_state" in accept
    assert "primarySnapshot(review)" in accept
    assert "methodAssessmentStarted(review)" in accept
    assert "revealedCases = importedRevealed" in accept
    assert "lockedPrimaryById = importedLocks" in accept
    assert 'package_phase: "phase2a5"' in SCRIPT
    assert "context_evidence_index_sha256" in SCRIPT


def test_reviewer_script_contains_no_true_candidate_or_threshold_tokens():
    for token in (
        "natural-vegetation-share-0.50-v1",
        "natural-vegetation-share-0.75-v1",
        "dominant-assessed-share-0.60-v1",
        "plurality-assessed-margin-0.15-v1",
        "candidate_id",
        "sample_id",
        "threshold",
        "mechanical",
    ):
        assert token not in SCRIPT
