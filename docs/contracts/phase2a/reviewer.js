"use strict";

const embedded = JSON.parse(document.getElementById("payload").textContent);
const reviewerSlot = embedded.reviewer_slot;
const cases = embedded.cases;
let reviews = structuredClone(embedded.reviews);
let reviewById = Object.fromEntries(reviews.map((review) => [review.blind_case_id, review]));
let index = 0;
let caseStartedAt = Date.now();
const storageKey = `araripe-phase2a3:${reviewerSlot}:${cases.map((item) => item.blind_case_id).join(":")}`;

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

function acceptReviewExport(candidate) {
  const expectedIds = cases.map((item) => item.blind_case_id);
  if (candidate?.reviewer_slot !== reviewerSlot || !Array.isArray(candidate.reviews)) {
    throw new Error("The file belongs to another reviewer slot or has no reviews array.");
  }
  const receivedIds = candidate.reviews.map((item) => item.blind_case_id);
  if (JSON.stringify(receivedIds) !== JSON.stringify(expectedIds)) {
    throw new Error("The imported review IDs/order do not match this isolated assignment.");
  }
  reviews = structuredClone(candidate.reviews);
  reviewById = Object.fromEntries(reviews.map((review) => [review.blind_case_id, review]));
}

try {
  const saved = localStorage.getItem(storageKey);
  if (saved) acceptReviewExport(JSON.parse(saved));
} catch (error) {
  console.warn("Local resume state was unavailable; JSON import/export still works.", error);
}

function persist() {
  try {
    localStorage.setItem(storageKey, JSON.stringify({
      schema_version: "1.0.0",
      reviewer_slot: reviewerSlot,
      reviews,
    }));
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

const artifactNames = ["cloud", "shadow", "haze", "mosaic_seam", "misregistration", "phenology", "fire_like", "low_resolution", "other"];
const methodFamilies = ["cloud_mask", "daily_composition", "drought_adjustment", "mapbiomas", "contextual_signature"];

function methodSection(review) {
  const primaryDone = Boolean(review.change_assessment.change_label && review.change_assessment.reason);
  return methodFamilies.map((family) => {
    const method = review.method_comparisons[family];
    if (method.availability === "not_generated_in_2a3") {
      return `<section class="method"><strong>${escapeHtml(family)}</strong>: no blinded alternatives generated in 2A.3.</section>`;
    }
    const disabled = primaryDone ? "" : "disabled";
    return `<section class="method"><h4>${escapeHtml(family)}</h4>
      <p>A: ${escapeHtml(method.option_a)} · B: ${escapeHtml(method.option_b)} · availability: ${escapeHtml(method.availability)}</p>
      <label>Preference <select id="method-${family}-preference" ${disabled}>${choices(["A", "B", "equivalent", "inconclusive", "unreviewable"], method.preference)}</select></label>
      <label>Confidence <select id="method-${family}-confidence" ${disabled}>${choices(["high", "medium", "low", "not_assessable"], method.reviewer_confidence)}</select></label>
      <label>Evidence/reason <textarea id="method-${family}-reason" ${disabled}>${escapeHtml(method.evidence_reason)}</textarea></label>
    </section>`;
  }).join("");
}

function render() {
  const currentCase = cases[index];
  const review = reviewById[currentCase.blind_case_id];
  caseStartedAt = Date.now();
  document.getElementById("counter").textContent = `${index + 1} / ${cases.length} — ${currentCase.blind_case_id}`;
  const evidence = Object.values(currentCase.evidence).map(evidenceCard).join("");
  const artifactFlags = artifactNames.map((name) => `
    <label class="check"><input type="checkbox" data-artifact="${name}" ${review.change_assessment.artifact_flags.includes(name) ? "checked" : ""}> ${name}</label>`).join("");
  document.getElementById("app").innerHTML = `<section class="case">
    <h2>${escapeHtml(currentCase.blind_case_id)}</h2><p>Target date: ${escapeHtml(currentCase.target_date)}</p>
    <div class="evidence-grid">${evidence}</div>
    <h3>Primary change assessment</h3>
    <div class="form-grid">
      <label>Change label <select id="change-label">${choices(["real_change", "no_change", "uncertain", "unreviewable"], review.change_assessment.change_label)}</select></label>
      <label>Evidence sufficiency <select id="evidence-sufficiency">${choices(["sufficient", "conflicting", "insufficient"], review.change_assessment.evidence_sufficiency)}</select></label>
    </div>
    <label>Change reason <textarea id="change-reason">${escapeHtml(review.change_assessment.reason)}</textarea></label>
    <fieldset><legend>Evidence/artifact flags</legend><div class="checks">${artifactFlags}</div></fieldset>
    <h3>Temporal assessment</h3><div class="form-grid">
      <label>Temporal confidence <select id="temporal-confidence">${choices(["high", "medium", "low", "not_assessable"], review.temporal_assessment.confidence)}</select></label>
      <label>Reason <textarea id="temporal-reason">${escapeHtml(review.temporal_assessment.reason)}</textarea></label>
    </div>
    <h3>Land-cover context</h3><div class="form-grid">
      <label>Context <select id="land-cover-context">${choices(["natural_vegetation", "anthropic_agriculture_pasture", "built_or_extractive", "water_or_wetland", "bare_or_other_natural", "mixed", "unknown", "not_assessable"], review.land_cover_assessment.context)}</select></label>
      <label>Confidence <select id="land-cover-confidence">${choices(["high", "medium", "low", "not_assessable"], review.land_cover_assessment.confidence)}</select></label>
    </div><label>Land-cover reason <textarea id="land-cover-reason">${escapeHtml(review.land_cover_assessment.reason)}</textarea></label>
    <h3>Contextual signature</h3><div class="form-grid">
      <label>Signature <select id="signature-label">${choices(["fire_like", "exposed_soil_or_clearing_like", "mixed_or_uncertain", "not_assessed"], review.contextual_signature.label)}</select></label>
      <label>Reason <textarea id="signature-reason">${escapeHtml(review.contextual_signature.reason)}</textarea></label>
    </div>
    <h3>Blinded method comparisons</h3><p>Complete the primary assessment first. A preference is evidence for later analysis and never activates a method.</p>${methodSection(review)}
    <h3>Tool usability</h3>
    <label>Missing or confusing evidence (one item per line)<textarea id="missing-evidence">${escapeHtml(review.usability.missing_or_confusing_evidence.join("\n"))}</textarea></label>
    <label>Tool issue<textarea id="tool-issue">${escapeHtml(review.usability.tool_issue)}</textarea></label>
    <label>Other notes<textarea id="notes">${escapeHtml(review.notes)}</textarea></label>
    <label>Review status <select id="review-status">${choices(["unreviewed", "in_progress", "complete"], review.review_status)}</select></label>
    <p class="meta">A complete record requires reviewer attestations and all primary assessment fields/reasons. Exported JSON must pass the coordinator review validator.</p>
  </section>`;
  renderProgress();
}

function completeEnough(review) {
  return Boolean(
    review.reviewer.pseudonymous_id && review.reviewer.qualification_attested && review.reviewer.independence_attested
    && review.change_assessment.change_label && review.change_assessment.reason && review.change_assessment.evidence_sufficiency
    && review.temporal_assessment.confidence && review.temporal_assessment.reason
    && review.land_cover_assessment.context && review.land_cover_assessment.confidence && review.land_cover_assessment.reason
    && review.contextual_signature.label && review.contextual_signature.reason
    && review.usability.review_duration_seconds != null
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
  review.change_assessment.change_label = value("change-label");
  review.change_assessment.reason = value("change-reason");
  review.change_assessment.evidence_sufficiency = value("evidence-sufficiency");
  review.change_assessment.artifact_flags = [...document.querySelectorAll("[data-artifact]:checked")].map((item) => item.dataset.artifact);
  review.temporal_assessment.confidence = value("temporal-confidence");
  review.temporal_assessment.reason = value("temporal-reason");
  review.land_cover_assessment.context = value("land-cover-context");
  review.land_cover_assessment.confidence = value("land-cover-confidence");
  review.land_cover_assessment.reason = value("land-cover-reason");
  review.contextual_signature.label = value("signature-label");
  review.contextual_signature.reason = value("signature-reason");
  review.usability.missing_or_confusing_evidence = lines(value("missing-evidence"));
  review.usability.tool_issue = value("tool-issue");
  review.notes = value("notes");
  methodFamilies.forEach((family) => {
    const method = review.method_comparisons[family];
    if (method.availability !== "not_generated_in_2a3") {
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
  const payload = {schema_version: "1.0.0", reviewer_slot: reviewerSlot, reviews};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `phase2a3-${reviewerSlot}-reviews.json`;
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
