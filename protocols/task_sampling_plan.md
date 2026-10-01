# Task Sampling Plan — Held-out Evaluation Set

Round 2, 2026-10-01. Governs task construction, dependence, and sample-size
rationale for the benchmark (protocols/benchmark_plan_v2.md).

## 1. Task construction rules

Each task record (tasks/*.json, validated by code/benchmark/validate_tasks.py)
contains:
- task_id, family_id (shared by translation variants),
- intended_inquiry_skill (one of: evidence_finding, applicability_judgment,
  uncertainty_identification, finding_comparison),
- language (en or zh), question text, role, mode, specialty,
- public_source_provenance (guideline/systematic review title, publisher,
  stable URL/DOI, dated evidence cutoff),
- required_answer_elements (5-7 per task, frozen),
- acceptable_alternative_sources (alternative references that equally support
  an element — citation of a preferred paper is never required when another
  valid source supports the same conclusion),
- disqualifying_errors (fabrication, material contradiction flags),
- scoring_rubric (element-level: supported-and-correctly-cited /
  supported-but-miscited / unsupported / omitted; plus refusal and
  fabrication categories).

Constraints:
- Sources are public, traceable scholarly documents (guidelines, systematic
  reviews) — NOT participant data, NOT patient data. Educational framing:
  tasks ask the user to find evidence, judge applicability to a
  teaching/research context, identify uncertainty, or compare findings —
  not to treat a patient.
- The 4 challenge tasks are deliberately constructed: 2 insufficient-evidence
  (plausible question with no adequate published evidence at the stated
  cutoff) and 2 false-premise (question presupposes a non-existent
  intervention/finding). Correct behavior = abstention/refusal with reasons.
- Workshop questions and known developer regression cases are excluded from
  ALL sets (contamination ledger: evaluation/contamination_ledger.csv records
  each excluded item by category and reason without reproducing restricted
  workshop text).
- Evidence cutoff: per-task dated cutoff (month of source publication);
  rubric sources are the versions current at the cutoff; reviewers receive
  exact sections/pages.

## 2. Dependence structure

- Translations of the same question are PAIRED VARIANTS within one family,
  not independent tasks: at most one variant per family may count in the
  primary paired comparison; the other variant contributes only to a
  language-consistency exploratory analysis.
- Same-source dependence: tasks whose required elements draw on the same
  source document are grouped; the evaluation set spreads families across
  ≥6 distinct source documents to limit source-level clustering (recorded in
  the registry).
- Runs within a task are repetitions, never additional observations.

## 3. Sample-size and precision rationale (frozen choice logic; a local Git freeze is NOT a public preregistration)

The 24 answerable families + 4 challenges is a FEASIBILITY STARTING POINT,
not an established adequate size. We choose the final n from {24, 40, 60}
families using the following precision criteria, computed by
code/benchmark/estimate_budget.py (not by looking at pilot results):

- Primary metric p = family-level grounded-answer success rate (arm A);
  expected range p ∈ [0.5, 0.9].
- CI half-width target: 95% CI half-width ≤ ±0.15 (n=24 gives ±0.20 at p=0.5,
  ±0.16 at p=0.8; n=40 gives ±0.155/±0.124; n=60 gives ±0.127/±0.101).
- McNemar power (exact, two-sided α=0.05, computed by
  code/benchmark/estimate_budget.py's power helper at freeze time, NOT from
  pilot results): at n=24 power is
  LOW for moderate effects (0.14 at 30% discordant families with 75/25 split;
  0.49 at 40% discordant with 85/15); at n=40: 0.31/0.79; at n=60: 0.50/0.94.
  Consequence: the primary reported quantity is the paired rate difference
  WITH score-interval CI; McNemar remains the prespecified paired test
  (status fixed a priori, never reclassified from observed discordance);
  if neither CI nor test is decisive, results are a feasibility benchmark
  with uncertainty.
- Budget interaction: each arm-A family costs 3 runs × (answer + supervisor)
  + arm B 3 runs × 1 call + retrieval; n=60 ≈ 540 model calls ≈ US$2.4 at
  pinned pricing and stated token assumptions, ≈19 rater-hours; n=24 ≈ 216
  calls, ≈ US$0.96, ≈ 8.4 rater-hours.
- Decision rule: default n=24 (feasibility benchmark with honest CIs);
  escalate to 40 or 60 only with author-approved budget AND rater capacity,
  decided BEFORE generating any held-out run. Generalization limits:
  purposive, guideline-anchored tasks; inference is to "tasks of this
  designed kind", not to all scholarly inquiry or clinical practice.

## 4. What we will NOT claim

- No claim that a task was absent from a proprietary model's training data
  (unverifiable) — we report only that tasks were constructed from public
  sources with dated cutoffs and are excluded from any development data we
  control.
- No real-world prevalence inference from the 4 deliberately constructed
  challenge tasks.
