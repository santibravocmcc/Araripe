"use strict";

const embedded = JSON.parse(document.getElementById("payload").textContent);
const reviewerSlot = embedded.reviewer_slot;
const cases = embedded.cases;
const methodEvidenceById = embedded.method_evidence || {};
const hasMethodEvidence = Object.keys(methodEvidenceById).length > 0;
const packagePhase = embedded.package_phase || "phase2a3";
const packageBinding = embedded.package_binding || {};
const phase2a4 = packagePhase === "phase2a4";
const reviewExportSchema = "https://observatoriodachapadadoararipe.com/data/schemas/phase2a4-review-export-v1.schema.json";
const templateReviews = structuredClone(embedded.reviews);
const templateById = Object.fromEntries(templateReviews.map((review) => [review.blind_case_id, review]));
let reviews = structuredClone(embedded.reviews);
let reviewById = Object.fromEntries(reviews.map((review) => [review.blind_case_id, review]));
let index = 0;
let caseStartedAt = Date.now();
const storageBinding = phase2a4
  ? `${packageBinding.package_id}:${packageBinding.review_template_sha256}:${packageBinding.method_evidence_index_sha256}`
  : cases.map((item) => item.blind_case_id).join(":");
const storageKey = `araripe-${packagePhase}:${reviewerSlot}:${storageBinding}`;
const revealStorageKey = `${storageKey}:method-reveal-v1`;
let revealedCases = new Set();
let lockedPrimaryById = new Map();

const escapeHtml = (value) => String(value ?? "").replace(
  /[&<>\"]/g,
  (character) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;"})[character],
);
const value = (id) => document.getElementById(id)?.value || null;
const checked = (id) => Boolean(document.getElementById(id)?.checked);
const choices = (items, current) => ["", ...items].map(
  (item) => `<option value="${escapeHtml(item)}" ${item === current ? "selected" : ""}>${escapeHtml(item)}</option>`,
).join("");
const lines = (text) => String(text || "").split("\n").map((item) => item.trim()).filter(Boolean);
const artifactNames = ["cloud", "shadow", "haze", "mosaic_seam", "misregistration", "phenology", "fire_like", "low_resolution", "other"];
const methodFamilies = ["cloud_mask", "daily_composition", "drought_adjustment", "mapbiomas", "contextual_signature"];

function primaryAssessmentComplete(review) {
  return Boolean(
    review.change_assessment.change_label
    && review.change_assessment.reason
    && review.change_assessment.evidence_sufficiency
    && review.temporal_assessment.confidence
    && review.temporal_assessment.reason
    && review.land_cover_assessment.context
    && review.land_cover_assessment.confidence
    && review.land_cover_assessment.reason
  );
}

function methodAssessmentStarted(review) {
  return methodFamilies.some((family) => {
    const method = review?.method_comparisons?.[family] || {};
    return method.preference || method.reviewer_confidence || method.evidence_reason;
  });
}

function primarySnapshot(review) {
  return structuredClone({
    change_assessment: review.change_assessment,
    temporal_assessment: review.temporal_assessment,
    land_cover_assessment: review.land_cover_assessment,
  });
}

function sameValue(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function immutableMethodMetadata(review) {
  return Object.fromEntries(methodFamilies.map((family) => {
    const method = review?.method_comparisons?.[family];
    if (!method) throw new Error(`Missing method metadata for ${family}.`);
    return [family, {
      availability: method.availability,
      option_a: method.option_a,
      option_b: method.option_b,
      display_order: method.display_order,
      selected_or_activated: method.selected_or_activated,
    }];
  }));
}

function phase2a4Envelope() {
  return {
    $schema: reviewExportSchema,
    schema_version: "1.0.0",
    package_phase: "phase2a4",
    package_binding: packageBinding,
    reviewer_slot: reviewerSlot,
    reveal_state: cases.map((item) => {
      const blindCaseId = item.blind_case_id;
      const revealed = revealedCases.has(blindCaseId);
      return {
        blind_case_id: blindCaseId,
        revealed,
        locked_primary: revealed ? structuredClone(lockedPrimaryById.get(blindCaseId)) : null,
      };
    }),
    reviews,
  };
}

function exportEnvelope() {
  return phase2a4
    ? phase2a4Envelope()
    : {schema_version: "1.0.0", reviewer_slot: reviewerSlot, reviews};
}

function acceptReviewExport(candidate) {
  const expectedIds = cases.map((item) => item.blind_case_id);
  if (candidate?.reviewer_slot !== reviewerSlot || !Array.isArray(candidate.reviews)) {
    throw new Error("The file belongs to another reviewer slot or has no reviews array.");
  }
  const receivedIds = candidate.reviews.map((item) => item.blind_case_id);
  if (JSON.stringify(receivedIds) !== JSON.stringify(expectedIds)) {
    throw new Error("The imported review IDs/order do not match this isolated assignment.");
  }
  let importedRevealed = new Set();
  let importedLocks = new Map();
  if (phase2a4) {
    const expectedKeys = ["$schema", "package_binding", "package_phase", "reveal_state", "reviewer_slot", "reviews", "schema_version"];
    if (!sameValue(Object.keys(candidate || {}).sort(), expectedKeys)) {
      throw new Error("The Phase 2A.4 resume envelope has unexpected or missing fields.");
    }
    if (candidate.$schema !== reviewExportSchema || candidate.schema_version !== "1.0.0" || candidate.package_phase !== "phase2a4") {
      throw new Error("The Phase 2A.4 resume envelope schema or phase is incompatible.");
    }
    if (!sameValue(candidate.package_binding, packageBinding)) {
      throw new Error("The imported review is bound to a different derivative package or evidence template.");
    }
    if (!Array.isArray(candidate.reveal_state)) {
      throw new Error("The Phase 2A.4 reveal state is missing.");
    }
    const revealIds = candidate.reveal_state.map((item) => item?.blind_case_id);
    if (!sameValue(revealIds, expectedIds)) {
      throw new Error("The reveal-state IDs/order do not match this isolated assignment.");
    }
    candidate.reviews.forEach((review, position) => {
      const template = templateById[review.blind_case_id];
      if (!template || !sameValue(immutableMethodMetadata(review), immutableMethodMetadata(template))) {
        throw new Error(`Immutable method metadata changed for ${review.blind_case_id}.`);
      }
      const reveal = candidate.reveal_state[position];
      if (typeof reveal.revealed !== "boolean") {
        throw new Error(`Invalid reveal state for ${review.blind_case_id}.`);
      }
      if (reveal.revealed) {
        if (!primaryAssessmentComplete(review) || !reveal.locked_primary || !sameValue(primarySnapshot(review), reveal.locked_primary)) {
          throw new Error(`Revealed methods do not preserve the locked primary assessment for ${review.blind_case_id}.`);
        }
        importedRevealed.add(review.blind_case_id);
        importedLocks.set(review.blind_case_id, structuredClone(reveal.locked_primary));
      } else if (reveal.locked_primary !== null || methodAssessmentStarted(review)) {
        throw new Error(`Method fields or a primary lock precede reveal for ${review.blind_case_id}.`);
      }
    });
  } else {
    candidate.reviews.forEach((review) => {
      if (methodAssessmentStarted(review) && !primaryAssessmentComplete(review)) {
        throw new Error(`Method fields precede the required primary assessment for ${review.blind_case_id}.`);
      }
    });
    importedRevealed = new Set(candidate.reviews.filter(methodAssessmentStarted).map((review) => review.blind_case_id));
    importedLocks = new Map(candidate.reviews.filter(methodAssessmentStarted).map((review) => [review.blind_case_id, primarySnapshot(review)]));
  }
  reviews = structuredClone(candidate.reviews);
  reviewById = Object.fromEntries(reviews.map((review) => [review.blind_case_id, review]));
  revealedCases = importedRevealed;
  lockedPrimaryById = importedLocks;
}

try {
  if (!phase2a4) {
    const revealed = JSON.parse(localStorage.getItem(revealStorageKey) || "[]");
    if (Array.isArray(revealed)) revealedCases = new Set(revealed);
  }
  const saved = localStorage.getItem(storageKey);
  if (saved) acceptReviewExport(JSON.parse(saved));
} catch (error) {
  console.warn("Local resume state was unavailable; JSON import/export still works.", error);
}

function persist() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(exportEnvelope()));
    if (!phase2a4) localStorage.setItem(revealStorageKey, JSON.stringify([...revealedCases].sort()));
  } catch (error) {
    console.warn("Could not save local resume state.", error);
  }
}

function renderProfile() {
  const reviewer = reviews[0]?.reviewer || {};
  document.getElementById("profile").innerHTML = `
    <label>Reviewer ID <input id="reviewer-id" value="${escapeHtml(reviewer.pseudonymous_id)}" autocomplete="off"></label>
    <label><input id="qualified" type="checkbox" ${reviewer.qualification_attested ? "checked" : ""}> qualified to interpret the assigned land-change evidence</label>
    <label><input id="independent" type="checkbox" ${reviewer.independence_attested ? "checked" : ""}> reviewing independently without coordinator/system labels</label>`;
}

function sourceSummary(source) {
  if (!source) return "";
  const observed = source.observed_at || source.before?.observed_at || "";
  const after = source.after?.observed_at || "";
  const identity = source.item_id || source.dataset || source.collection || "provenance recorded";
  const gap = source.temporal_gap_days == null ? "" : `; gap ${source.temporal_gap_days} days`;
  const coverage = source.coverage_fraction == null ? "" : `; coverage ${(source.coverage_fraction * 100).toFixed(1)}%`;
  return `${identity}${observed ? `; ${observed}` : ""}${after ? ` → ${after}` : ""}${gap}${coverage}`;
}

function evidenceCard(evidence) {
  const detail = sourceSummary(evidence.source);
  const body = evidence.local_path
    ? `<img src="${escapeHtml(evidence.local_path)}" alt="${escapeHtml(evidence.role)}">`
    : `<div class="missing">${escapeHtml(evidence.status)}: ${escapeHtml(evidence.reason)}</div>`;
  return `<figure><figcaption><strong>${escapeHtml(evidence.role)}</strong> — ${escapeHtml(evidence.status)}</figcaption>${body}<div class="meta">${escapeHtml(detail || evidence.reason)}</div></figure>`;
}

function methodPanel(option, record) {
  if (!record || !record.local_path) {
    return `<figure class="method-panel"><figcaption><strong>Panel ${escapeHtml(option)}</strong></figcaption><div class="missing">${escapeHtml(record?.status || "unreviewable")}: ${escapeHtml(record?.reason || "No comparison panel is available.")}</div></figure>`;
  }
  const coverage = record.valid_coverage_fraction == null
    ? ""
    : ` · valid coverage ${(record.valid_coverage_fraction * 100).toFixed(1)}%`;
  const contributors = record.contributing_scene_count == null
    ? ""
    : ` · ${record.contributing_scene_count} contributing scene(s)`;
  return `<figure class="method-panel"><figcaption><strong>Panel ${escapeHtml(option)}</strong> — ${escapeHtml(record.status)}</figcaption>
    <img src="${escapeHtml(record.local_path)}" alt="Blinded method comparison panel ${escapeHtml(option)}">
    <div class="meta">${escapeHtml(`${coverage}${contributors}`.replace(/^ · /, ""))}</div></figure>`;
}

function methodSection(currentCase, review) {
  const evidence = methodEvidenceById[currentCase.blind_case_id]?.families || {};
  const generated = methodFamilies.some((family) => review.method_comparisons[family].availability !== "not_generated_in_2a3");
  if (generated && !revealedCases.has(currentCase.blind_case_id)) {
    const ready = primaryAssessmentComplete(review);
    return `<section class="method-gate"><p><strong>The review interface does not render blinded panels until the primary change, temporal, and land-cover assessment is saved.</strong></p>
      <button id="reveal-methods" type="button" ${ready ? "" : "disabled"}>Save primary assessment and reveal blinded comparisons</button>
      <p class="meta">${ready ? "The required primary fields are complete." : "Complete the required primary fields above before revealing any method output."}</p></section>`;
  }
  return methodFamilies.map((family) => {
    const method = review.method_comparisons[family];
    if (method.availability === "not_generated_in_2a3") {
      return `<section class="method"><strong>${escapeHtml(family)}</strong>: no blinded alternatives generated in 2A.3.</section>`;
    }
    const familyEvidence = evidence[family] || {};
    const panels = method.display_order.map((option) => methodPanel(option, familyEvidence.options?.[option])).join("");
    return `<section class="method"><h4>${escapeHtml(family)}</h4>
      <p>Opaque alternatives only · availability: ${escapeHtml(method.availability)}</p>
      <div class="method-grid">${panels}</div>
      <label>Preference <select id="method-${family}-preference">${choices(["A", "B", "equivalent", "inconclusive", "unreviewable"], method.preference)}</select></label>
      <label>Confidence <select id="method-${family}-confidence">${choices(["high", "medium", "low", "not_assessable"], method.reviewer_confidence)}</select></label>
      <label>Evidence/reason <textarea id="method-${family}-reason">${escapeHtml(method.evidence_reason)}</textarea></label>
    </section>`;
  }).join("");
}

function render() {
  const currentCase = cases[index];
  const review = reviewById[currentCase.blind_case_id];
  caseStartedAt = Date.now();
  document.getElementById("counter").textContent = `${index + 1} / ${cases.length} — ${currentCase.blind_case_id}`;
  const evidence = Object.values(currentCase.evidence).map(evidenceCard).join("");
  const primaryLocked = revealedCases.has(currentCase.blind_case_id) ? "disabled" : "";
  const artifactFlags = artifactNames.map((name) => `
    <label class="check"><input type="checkbox" data-artifact="${name}" ${review.change_assessment.artifact_flags.includes(name) ? "checked" : ""} ${primaryLocked}> ${name}</label>`).join("");
  document.getElementById("app").innerHTML = `<section class="case">
    <h2>${escapeHtml(currentCase.blind_case_id)}</h2><p>Target date: ${escapeHtml(currentCase.target_date)}</p>
    <div class="evidence-grid">${evidence}</div>
    <h3>Primary change assessment</h3>
    <div class="form-grid">
      <label>Change label <select id="change-label" ${primaryLocked}>${choices(["real_change", "no_change", "uncertain", "unreviewable"], review.change_assessment.change_label)}</select></label>
      <label>Evidence sufficiency <select id="evidence-sufficiency" ${primaryLocked}>${choices(["sufficient", "conflicting", "insufficient"], review.change_assessment.evidence_sufficiency)}</select></label>
    </div>
    <label>Change reason <textarea id="change-reason" ${primaryLocked}>${escapeHtml(review.change_assessment.reason)}</textarea></label>
    <fieldset><legend>Evidence/artifact flags</legend><div class="checks">${artifactFlags}</div></fieldset>
    <h3>Temporal assessment</h3><div class="form-grid">
      <label>Temporal confidence <select id="temporal-confidence" ${primaryLocked}>${choices(["high", "medium", "low", "not_assessable"], review.temporal_assessment.confidence)}</select></label>
      <label>Reason <textarea id="temporal-reason" ${primaryLocked}>${escapeHtml(review.temporal_assessment.reason)}</textarea></label>
    </div>
    <h3>Land-cover context</h3><div class="form-grid">
      <label>Context <select id="land-cover-context" ${primaryLocked}>${choices(["natural_vegetation", "anthropic_agriculture_pasture", "built_or_extractive", "water_or_wetland", "bare_or_other_natural", "mixed", "unknown", "not_assessable"], review.land_cover_assessment.context)}</select></label>
      <label>Confidence <select id="land-cover-confidence" ${primaryLocked}>${choices(["high", "medium", "low", "not_assessable"], review.land_cover_assessment.confidence)}</select></label>
    </div><label>Land-cover reason <textarea id="land-cover-reason" ${primaryLocked}>${escapeHtml(review.land_cover_assessment.reason)}</textarea></label>
    <h3>Contextual signature</h3><div class="form-grid">
      <label>Signature <select id="signature-label">${choices(["fire_like", "exposed_soil_or_clearing_like", "mixed_or_uncertain", "not_assessed"], review.contextual_signature.label)}</select></label>
      <label>Reason <textarea id="signature-reason">${escapeHtml(review.contextual_signature.reason)}</textarea></label>
    </div>
    <h3>Blinded method comparisons</h3><p>Complete and save the primary assessment first. A preference is evidence for later analysis and never activates a method.</p>${methodSection(currentCase, review)}
    <h3>Tool usability</h3>
    <label>Missing or confusing evidence (one item per line)<textarea id="missing-evidence">${escapeHtml(review.usability.missing_or_confusing_evidence.join("\n"))}</textarea></label>
    <label>Tool issue<textarea id="tool-issue">${escapeHtml(review.usability.tool_issue)}</textarea></label>
    <label>Other notes<textarea id="notes">${escapeHtml(review.notes)}</textarea></label>
    <label>Review status <select id="review-status">${choices(["unreviewed", "in_progress", "complete"], review.review_status)}</select></label>
    <p class="meta">A complete record requires reviewer attestations and all primary assessment fields/reasons. Exported JSON must pass the coordinator review validator.</p>
  </section>`;
  const reveal = document.getElementById("reveal-methods");
  if (reveal) reveal.addEventListener("click", () => {
    saveCurrent({quiet: true});
    const updated = reviewById[currentCase.blind_case_id];
    if (!primaryAssessmentComplete(updated)) {
      window.alert("Complete the primary change, temporal, and land-cover fields before revealing method panels.");
      return;
    }
    lockedPrimaryById.set(currentCase.blind_case_id, primarySnapshot(updated));
    revealedCases.add(currentCase.blind_case_id);
    persist();
    render();
  });
  renderProgress();
}

function completeEnough(review) {
  const methodsComplete = methodFamilies.every((family) => {
    const method = review.method_comparisons[family];
    return method.availability === "not_generated_in_2a3"
      || Boolean(method.preference && method.reviewer_confidence && method.evidence_reason);
  });
  return Boolean(
    review.reviewer.pseudonymous_id && review.reviewer.qualification_attested && review.reviewer.independence_attested
    && review.change_assessment.change_label && review.change_assessment.reason && review.change_assessment.evidence_sufficiency
    && review.temporal_assessment.confidence && review.temporal_assessment.reason
    && review.land_cover_assessment.context && review.land_cover_assessment.confidence && review.land_cover_assessment.reason
    && review.contextual_signature.label && review.contextual_signature.reason
    && review.usability.review_duration_seconds != null
    && methodsComplete
  );
}

function saveCurrent({quiet = false} = {}) {
  const currentCase = cases[index];
  const review = reviewById[currentCase.blind_case_id];
  const elapsed = Math.max(0, (Date.now() - caseStartedAt) / 1000);
  review.usability.review_duration_seconds = (review.usability.review_duration_seconds || 0) + elapsed;
  caseStartedAt = Date.now();
  const reviewerId = document.getElementById("reviewer-id")?.value.trim() || null;
  const qualification = checked("qualified");
  const independence = checked("independent");
  reviews.forEach((item) => {
    item.reviewer.pseudonymous_id = reviewerId;
    item.reviewer.qualification_attested = qualification;
    item.reviewer.independence_attested = independence;
  });
  const primaryLocked = revealedCases.has(currentCase.blind_case_id);
  if (!primaryLocked) {
    review.change_assessment.change_label = value("change-label");
    review.change_assessment.reason = value("change-reason");
    review.change_assessment.evidence_sufficiency = value("evidence-sufficiency");
    review.change_assessment.artifact_flags = [...document.querySelectorAll("[data-artifact]:checked")].map((item) => item.dataset.artifact);
    review.temporal_assessment.confidence = value("temporal-confidence");
    review.temporal_assessment.reason = value("temporal-reason");
    review.land_cover_assessment.context = value("land-cover-context");
    review.land_cover_assessment.confidence = value("land-cover-confidence");
    review.land_cover_assessment.reason = value("land-cover-reason");
  } else {
    const locked = lockedPrimaryById.get(currentCase.blind_case_id);
    if (!locked || !sameValue(primarySnapshot(review), locked)) {
      if (!locked) throw new Error(`Missing primary lock for ${currentCase.blind_case_id}.`);
      review.change_assessment = structuredClone(locked.change_assessment);
      review.temporal_assessment = structuredClone(locked.temporal_assessment);
      review.land_cover_assessment = structuredClone(locked.land_cover_assessment);
    }
  }
  review.contextual_signature.label = value("signature-label");
  review.contextual_signature.reason = value("signature-reason");
  review.usability.missing_or_confusing_evidence = lines(value("missing-evidence"));
  review.usability.tool_issue = value("tool-issue");
  review.notes = value("notes");
  methodFamilies.forEach((family) => {
    const method = review.method_comparisons[family];
    if (method.availability !== "not_generated_in_2a3" && document.getElementById(`method-${family}-preference`)) {
      method.preference = value(`method-${family}-preference`);
      method.reviewer_confidence = value(`method-${family}-confidence`);
      method.evidence_reason = value(`method-${family}-reason`);
    }
  });
  const requestedStatus = value("review-status") || "unreviewed";
  review.review_status = requestedStatus;
  if (requestedStatus === "complete" && !completeEnough(review)) {
    review.review_status = "in_progress";
    if (!quiet) window.alert("This record is incomplete. It was saved as in_progress; fill all primary fields/reasons and reviewer attestations before marking complete.");
  } else if (requestedStatus === "unreviewed" && review.change_assessment.change_label) {
    review.review_status = "in_progress";
  }
  persist();
}

function renderProgress() {
  const counts = {unreviewed: 0, in_progress: 0, complete: 0};
  reviews.forEach((review) => { counts[review.review_status] += 1; });
  document.getElementById("progress").textContent = `Progress: ${counts.complete} complete, ${counts.in_progress} in progress, ${counts.unreviewed} unreviewed.`;
}

document.getElementById("prev").addEventListener("click", () => {
  saveCurrent(); index = (index - 1 + cases.length) % cases.length; render();
});
document.getElementById("next").addEventListener("click", () => {
  saveCurrent(); index = (index + 1) % cases.length; render();
});
document.getElementById("export").addEventListener("click", () => {
  saveCurrent();
  const payload = exportEnvelope();
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${hasMethodEvidence ? "phase2a4" : "phase2a3"}-${reviewerSlot}-reviews.json`;
  link.click();
  URL.revokeObjectURL(link.href);
});
document.getElementById("import").addEventListener("change", async (event) => {
  try {
    const imported = JSON.parse(await event.target.files[0].text());
    acceptReviewExport(imported); persist(); renderProfile(); render();
  } catch (error) {
    window.alert(`Import failed: ${error.message}`);
  } finally {
    event.target.value = "";
  }
});
window.addEventListener("beforeunload", () => saveCurrent({quiet: true}));

renderProfile();
render();
