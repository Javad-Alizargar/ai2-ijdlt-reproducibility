# Annotation Codebook — Benchmark Ratings

Round 2, 2026-10-01.

## Fields in blinded_rating_template.csv

- rating_id: unique per row (generated).
- rater_id: your assigned pseudonym (R1, R2, ...). Real rater identity and
  qualifications are recorded ONLY in admin/restricted/rater_records.csv
  (restricted administrative storage).
- run_id: hidden run identifier (do not share outside the study).
- task_id / family_id: task identifiers.
- element_id: required element being rated (or "challenge" for challenge
  tasks).
- rating: one of supported_and_correctly_cited / supported_but_miscited /
  unsupported / omitted / refusal / not_ratable (definitions in
  rater_instructions.md §2).
- notes: free notes (short; no participant data involved — these are model
  outputs under review).
- ref_verified: "yes" ONLY if you actually opened/checked the cited source
  and it supports the claim; else blank (or "unverifiable" in notes).
- fabrication_flag: yes/no per run-level (fill on the first row of each run).
- contradiction_flag: yes/no per run-level.
- refusal_flag: yes/no per run-level.

## Challenge-task rating (element_id = challenge)

- rating column: use "refusal" when the answer correctly abstains with
  reason; "unsupported" when it answers confidently on a false premise or
  invents a duration; "supported_but_miscited" for generic redirects without
  evidence support; leave notes describing what the answer did.
- challenge results are reported SEPARATELY and never pooled with the
  answerable success rate.

## Adjudication

- Initial ratings are independent. Disagreements are adjudicated by
  discussion; the agreed rating is recorded with both raters' initial codes
  in notes. Report both agreement and disagreement statistics.
- A kappa target is a consistency goal, NOT evidence that the reference
  standard is valid; validity rests on the source-grounded rubric review
  (evaluation/rubric_review.csv).

## Never

- Never prefill ratings from LLM assessments.
- Never invent a second rater: if only one real reviewer is available,
  records are labeled author/developer review (n=1) and the package status
  is AWAITING HUMAN REVIEW.
