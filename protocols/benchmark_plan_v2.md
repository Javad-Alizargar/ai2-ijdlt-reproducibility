# Benchmark Plan v2 — Frozen-Pipeline Evaluation

Round 2, 2026-10-01. Supersedes protocols/benchmark_plan_v1.md. A dated Git
commit is a protocol freeze for this project; it is NOT a public
preregistration and will not be described as one.

## 1. Design overview

- System under test: frozen deployed AI2 pipeline (system/frozen_system_manifest.json,
  system/replay_equivalence.md). Answer model gpt-4.1-mini; supervisor
  gpt-4.1-mini; production prompts verbatim; paper_count=12, year_range=last5,
  prefer_recent=true, use_journal_rank=false; response language per task.
- Arms:
  - Arm A (system): full pipeline — retrieval → scoring/filters → answer
    (1 model call) → citation supervisor (1 model call) → stored answer.
  - Arm B (baseline): same answer model, same answer system prompt minus the
    evidence-dependent parts, no retrieval, no supervisor (1 model call per
    run); instruction comparable and scholarly-task matched: "Answer the
    scholarly question as a careful academic assistant; do not invent
    references; state uncertainty; if you cannot support a claim, say so."
    Output allowance matched to Arm A (max_tokens 1700).
- Task wording, response language, model, temperature, and generation
  settings are matched across arms. Arm A's extra supervisor calls, tokens,
  latency, and cost are recorded separately (budget accounting, §8).
- Interpretation: end-to-end system comparison. It CANNOT by itself separate
  the causal contributions of retrieval vs supervision; a supervision-off
  ablation is PROPOSED for a later round, not silently added here.

## 2. Task sets (see task_sampling_plan.md for construction rules)

- Development/calibration set: 6 tasks (also used for the Round-2 pilot).
- Held-out evaluation set: answerable tasks drawn from ≥24 independent task
  families + 4 challenge tasks. Exact n and precision rationale in
  task_sampling_plan.md. Held-out answers are NOT generated or viewed in
  Round 2.
- Excluded from held-out set: workshop questions, known developer regression
  cases; contamination/provenance ledger maintained without reproducing
  restricted text.

## 3. Primary outcome: grounded-answer success

Operational definition: a task run is a SUCCESS iff:
1. ≥80% of REQUIRED rubric elements are rated "answered with appropriate
   supporting citation" (element-level), AND
2. no fabricated reference is present in the answer, AND
3. no prespecified material contradiction is present.

Clarifications (binding):
- Denominator = REQUIRED rubric elements only (fixed per task in the frozen
  rubric), not whatever claims the model happens to produce.
- Omitted required elements count against completeness (not success).
- Extra materially unsupported or contradictory statements are assessed via
  the contradiction/fabrication checks and the secondary unsupported-claim
  count; they can fail a run only through those channels, not by changing
  the denominator.
- Unverifiable references (cannot be resolved/resolved ambiguously) are
  DISTINCT from demonstrated fabrications; a run with an unverifiable
  reference is scored per the rubric item and recorded in the failure-mode
  table under "unverifiable reference", not automatically failed.
- Bibliographic existence is DISTINCT from support: a real paper cited for a
  claim it does not support fails the element-level support test.
- A valid refusal on an answerable task (correctly says evidence insufficient)
  is recorded separately from success/failure (category "refusal_on_answerable");
  it does not count as success.
- Challenge tasks use their own scoring: appropriate abstention/refusal =
  correct; confident answer on false-premise task = incorrect. Challenge
  results are NEVER pooled into the main answerable-task success rate; their
  deliberate sampling implies nothing about real-world prevalence.
- The 80% cutoff is a study-defined operational threshold, NOT a validated
  educational or clinical safety standard. Prespecified sensitivity analyses:
  success recomputed at 60%, 70%, 90%, 100% thresholds (reported as
  sensitivity, no multiplicity claim).

## 4. Statistical unit and primary comparison

- One prespecified paired binary observation per independent task family:
  the FIRST scheduled run from each arm (run order fixed in the task
  registry before generation; never "best run" selection).
- Additional repetitions (runs 2-3) feed a separate stability analysis:
  per-task agreement across runs, and a task-weighted comparison that
  preserves task families in resampling (bootstrap over families, not over
  runs; runs nested in families).
- Primary test: two-sided exact McNemar on discordant task-family pairs
  (arm A vs arm B), α=0.05, with 95% CI for the paired rate difference
  (Wilson/Newcombe interval for paired proportions).
- If independent-pair assumptions cannot be supported after inspecting the
  run structure, the pre-registered fallback is a cluster-aware comparison
  (families as clusters; exact permutation test over families) — decided
  BEFORE the main evaluation from pilot data structure, not after seeing
  held-out results.
- Report paired effect sizes and uncertainty; distinguish uncertainty across
  sampled task families (bootstrap over families) from stochastic run
  variation (per-family run agreement). No pooling of runs, citations, or
  rubric items as independent observations.
- Multiplicity: ONE primary comparison. Secondaries (must-include recall,
  citation-validity, refusal correctness, inappropriate-confidence rate,
  failure-mode counts) are exploratory and labeled.

## 5. Execution and failure rules (pre-specified)

- Timeout: 10 min per run (all stages); truncated answers recorded as such.
- API failures: ≤2 retries per stage with 60 s backoff; then stage-failed →
  run-failed (recorded, never silently removed).
- Retry budget counts against the global ceiling.
- Zero-evidence refusals scored with the refusal rubric.
- Missing ratings: a run with no human ratings is EXCLUDED from the primary
  analysis and reported (analyze_ratings.py refuses to emit scored results
  from incomplete rating sets).
- Exclusion log is part of results and never edited post-hoc.
- Run selection for primary: first scheduled run per arm per family — fixed
  in the task registry (run_slot field) before any generation.

## 6. Rating process

- 2 independent human raters minimum (planned; see evaluation/ package).
  Rubric-relevant source sections/pages are cited in the rubric; raters
  judge support against those sources, not against the model's claims.
- Calibration on development tasks before held-out rating; agreement
  reported (kappa); disagreements adjudicated with documented decisions.
- Blinding: answer-to-arm mapping kept out of rating materials; blinding is
  IMPERFECT (answer style/absence of citations can reveal the arm) and will
  be described as such.
- LLM outputs are never used to prefill or replace human ratings.

## 7. Budget ceiling (this round)

- Round-2 development pilot ceiling: US$5 AND ≤24 paid requests, whichever
  is reached first; includes retries, supervisor calls, and any helper calls.
- Full held-out evaluation budget is estimated separately (estimate_budget.py)
  and requires explicit author approval in a later round.

## 8. Cost accounting

- Per-run: attempts, stage latency, prompt/completion tokens per stage,
  computed USD cost from pinned pricing (gpt-4.1-mini $0.40/$1.60 per 1M;
  recorded in provider_adapter.py), all logged to run records.
- Arm A: answer + supervisor calls; Arm B: answer only. Comparison reports
  the pipeline's additional supervision cost as a measured difference.
