# Holdout paper workspaces

This directory holds one workspace per candidate holdout paper. It contains **no certified
paper today**: the live manifest is at `blocked_no_certified_papers` with an empty `papers`
list.

The complete operator guide is [../INTAKE_GUIDE.md](../INTAKE_GUIDE.md). Read it before
running any command. The human marking rules are in
[../CERTIFICATION_PROTOCOL.md](../CERTIFICATION_PROTOCOL.md); dataset composition is in
[../HOLDOUT_REQUIREMENTS.md](../HOLDOUT_REQUIREMENTS.md).

## Quick start

```bash
python -m benchmark.holdout.intake init holdout-01 \
  --items /secure/items.json --topic algebra --difficulty higher --marks 50
python -m benchmark.holdout.intake pages holdout-01 --role student --files /secure/student_p*.png
python -m benchmark.holdout.intake pages holdout-01 --role scheme --files /secure/scheme_p*.png
python -m benchmark.holdout.intake markers holdout-01 --role marker_a \
  --marker-id MARKER_A_01 --file /secure/marker_a_raw.json
python -m benchmark.holdout.intake markers holdout-01 --role marker_b \
  --marker-id MARKER_B_01 --file /secure/marker_b_raw.json
python -m benchmark.holdout.intake adjudicate holdout-01 --file /secure/adjudication.json
python -m benchmark.holdout.intake build holdout-01 --audit /secure/audit.json
python -m benchmark.holdout.intake attest holdout-01 --role marker_a --file /secure/marker_a_attestation.json
python -m benchmark.holdout.intake attest holdout-01 --role marker_b --file /secure/marker_b_attestation.json
python -m benchmark.holdout.intake attest holdout-01 --role adjudicator --file /secure/adjudicator_attestation.json
python -m benchmark.holdout.intake attest holdout-01 --role custodian --file /secure/custodian_attestation.json
python -m benchmark.holdout.intake validate holdout-01
python -m benchmark.holdout.intake register holdout-01 --dry-run
python -m benchmark.holdout.intake register holdout-01
```

Promotion is a separate, explicitly approved operation:

```bash
python -m benchmark.holdout.intake promote \
  --revision holdout/registrations/holdout-01/reg-holdout-01-1a2b3c4d5e6f.json \
  --approval /secure/approval.json
```

Registration writes an immutable candidate revision and does **not** change the live
manifest. Promotion writes a new manifest revision and does not move a live pointer.

## Naming

`paper_id` is `holdout-01` … `holdout-NN`. `paper-01` is reserved for the design paper and
is rejected by both the workspace validator and the manifest.

## Workspace contents

```
holdout-01/
  intake.json
  items.json
  events.jsonl
  pages/student/…
  pages/scheme/…
  markers/original/…      preserved raw submissions
  markers/marker_a.json
  markers/marker_b.json
  adjudication.json
  audit.json
  reference.json
  certification.json
  attestations/…
```

Only anonymised page copies belong here. Raw submissions are preserved byte-for-byte; do
not edit them to correct a marking error. The CLI refuses a different re-submission, so a
correction requires a fresh intake path (see the guide's "Corrected marker sheets").

## What must not be placed here

- Original scans, PDFs or re-encoded copies of `paper-01`.
- Student names, candidate numbers, school identifiers or teacher names.
- Model output, escalation responses or benchmark results.
- A reference produced by a model or copied from the candidate reference.
- Fabricated attestations, approvals or signatures.
- A hand-edited `holdout_manifest.json`.

## Safety

- A generated certification draft is not a certified paper.
- A registered candidate is not a promoted paper.
- A detached hash proves integrity, not identity.
- Automated text scanning is heuristic; pixel-level anonymisation is a human custodian
  responsibility.
- Do not treat this workflow as production-ready for real papers until a real certified
  intake has been completed and reviewed.
