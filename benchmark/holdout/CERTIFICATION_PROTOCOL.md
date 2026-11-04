# Teacher certification protocol

This protocol produces the **only** reference marks a holdout evaluation may use. A
reference that does not satisfy every requirement here is not certified, and no accuracy
figure may be computed against it.

The benchmark author is not a marker. AI output is never a marker. The existing
`benchmark/ground_truth/paper-01.json` reference stays **candidate** until it is put through
this protocol.

## 1. Roles

| Role | Who | Must not be |
|---|---|---|
| Marker A | Qualified mathematics teacher, marks every scoreable item independently | The benchmark author; anyone who has seen model output or the candidate reference |
| Marker B | A second qualified teacher, marks the same items independently | The same person as A; anyone who has seen A's sheet |
| Adjudicator | A third qualified teacher (or senior examiner) | Either marker |
| Data custodian | Person who anonymises and hashes the pages | Any marker (so markers cannot identify a student) |

Markers are recorded under pseudonymous IDs (`MARKER_A_01`, …). Real names and contact
details stay outside the repository in the school's own records.

## 2. Inputs a marker receives

- The anonymised student pages (no names, no school, no candidate number).
- The printed mark scheme pages.
- The item list with printed marks available.
- A blank per-criterion sheet.

A marker never receives: model output, the candidate reference, the other marker's sheet,
escalation results, or any AI-generated marking.

## 3. Marking rules (identical for both markers)

1. Award each printed criterion independently, in printed order (method first, then
   accuracy).
2. Apply follow-through only where the scheme explicitly allows it.
3. A blank or crossed-out answer earns 0. Do not infer work from the scheme.
4. Record `awarded: true/false` per criterion, the item total, a short evidence note, and
   `ambiguous` / `illegible` flags where they apply.
5. Do not "correct" the student. Mark what is written.
6. If the printed question and the scheme disagree, mark the item `source_mismatch` and
   stop; the custodian records the exclusion. If a scheme part is not printed on the student
   page, record `not_printed` and stop.

## 4. Independence and blinding

- Markers work from separate copies and do not discuss items before both sheets are sealed.
- Neither marker sees the other's sheet until both are submitted and hashed.
- Each sheet is hashed (`sha256`) and stored with the paper.

## 5. Disagreements

1. Compare at **criterion** level, not just item totals.
2. Every criterion where the markers differ is a **disagreement record** containing:
   item, criterion, marker A award, marker B award, both evidence notes, and the page
   region or quoted working.
3. The adjudicator resolves each disagreement to `a`, `b`, `third`, or `excluded`, with a
   written rationale. A resolution is never a silent average.
4. Unresolved disagreements are **review cases**. They are reported separately and are
   never used as an evaluation label. If an item cannot be resolved, the item is excluded
   with reason `unresolved_disagreement` and its marks leave the denominator.
5. Raw sheets from both markers are preserved. Only the adjudicated reference is scored.

## 6. Agreement statistics (reported before any model result)

- Cohen's κ over criterion-level binary awards, per paper.
- Item-total exact agreement and mean absolute marker difference.
- Pre-registered acceptance: κ ≥ 0.80 preferred; 0.60 ≤ κ < 0.80 accepted with every
  disagreement adjudicated and listed; κ < 0.60 → the paper is re-marked before acceptance.
- A 10% random audit re-mark by the adjudicator checks both sheets for transcription and
  arithmetic errors. Any error found triggers a full re-check of that sheet.

## 7. Certification artifact

`certification.json` per paper, stored beside its reference:

```json
{
  "paper_id": "holdout-01",
  "reference_sha256": "<sha256 of reference JSON>",
  "markers": [
    {"id": "MARKER_A_01", "kind": "human_teacher", "role": "marker_a",
     "declaration": "I marked every item independently from the anonymised pages and the printed scheme.",
     "signed_on": "YYYY-MM-DD", "items_marked": 38}
  ],
  "adjudicator": {"id": "ADJ_01", "kind": "human_teacher", "signed_on": "YYYY-MM-DD"},
  "coverage": {"items_total": 38, "items_marked_by_both": 38, "criteria_total": 87},
  "agreement": {"criterion_kappa": 0.0, "item_exact_agreement": 0.0,
                "mean_absolute_item_difference": 0.0, "audit_sample": 0},
  "disagreements": [
    {"item": "23", "criterion": "A1", "marker_a": false, "marker_b": true,
     "resolution": "a", "resolved_by": "ADJ_01", "rationale": "..."}
  ],
  "exclusions": [
    {"item": "12", "reason": "source_mismatch", "marks": 2, "evidence": "..."}
  ],
  "pending": []
}
```

## 8. Prohibited shortcuts

- Copying a candidate reference and calling it certified.
- Using a model (including an LLM) as marker A or B, or as adjudicator.
- Marking only the items a strategy failed.
- Changing a mark after seeing model performance.
- Dropping an item because two models agreed on it.
- Reporting accuracy before the certification artifact and its hash exist.

## 9. Data protection

Anonymised pages only; no names, schools, candidate numbers or teacher names. No original
PDFs or raw scans in the repository. No API keys, provider responses or credentials in
certification artifacts. The manifest stores page hashes, not student identity.

## 10. Implementation notes (current tooling)

The rules above are unchanged. The software that records and re-verifies them is described
in [INTAKE_GUIDE.md](INTAKE_GUIDE.md). Operators should know the following boundaries.

### Artifact lifecycle

| Stage | Command | Record state |
|---|---|---|
| reference derived | `intake build` | `reference.json` with `verification.status: adjudicated_pending_certification` |
| draft certification | `intake build` | `certification.json` with `status: draft`, non-empty `pending` |
| detached evidence | `intake attest` | `status: attested_pending_approval` only when every gate is complete |
| independent check | `intake validate` | no writes; exit 1 on any problem |
| candidate registration | `intake register` | immutable revision with `status: candidate` |
| approved manifest entry | `intake promote` | new manifest revision with the paper at `status: certified` |

The generated certification also records `protocol_version`, `record_version`, input
hashes (`sources`), frozen Strategy H/evaluator/schema digests (`frozen`), agreement and
audit detail, disagreements, exclusions, a `signatures` map, and a `verification` block
with `method: detached_sha256` and `identity_verified: false`.

A persisted `status: certified` in the certification record is rejected. Only promotion may
place a certified paper entry into a manifest revision, and promotion requires an explicit
approval record naming the exact candidate revision.

### Markers and adjudication

- Marker sheets must cover every registry item and every printed criterion in order;
  repeated codes are distinguished by occurrence (`M1#0`, `M1#1`).
- The adjudication must contain exactly one record for every computed disagreement, no
  records for agreed criteria, and no duplicates.
- `third` requires a complete third-marker item; `excluded` requires an exclusion record and
  the item leaves the denominator.
- Cohen's κ is recomputed from the raw sheets. The enforced floor is 0.60; 0.80 remains the
  preferred level in §6.
- The audit sample must cover at least 10% of items and every sampled item must have a
  re-mark record that agrees with the recorded sheet.

### Detached evidence and identity

SHA-256 hashes in `attestations/*.json` and `certification.json` prove that the school-held
form has not changed. They do **not** prove who signed it, and no identity-verification
process is implemented. `identity_verified` must be `false`; the tooling rejects `true`.
Real names and contact details stay outside the repository.

### Data and verification

`python -m benchmark.holdout.manifest --check-code` must pass before any scoring run. It
checks the frozen code digests and the live manifest state. The live manifest must remain at
`blocked_no_certified_papers` until a real paper has been certified, registered and
promoted; the current repository has zero certified papers.
