# Public Export Allowlist

The private repository (ai2-ijdlt-research-private) holds the full research
archive. The public repository (ai2-ijdlt-reproducibility) receives ONLY items
listed here, through the verified export workflow. Never mirror the private
repo.

## Approved for Round 1 public scaffold

| path (public repo) | source (private repo) | status |
|---|---|---|
| README.md | reproducibility/public_templates/README.md | APPROVED round 1 |
| EXPORT_ALLOWLIST.md | this file (edited for public context) | APPROVED round 1 |
| environment_public.md | reproducibility/public_templates/environment_public.md | APPROVED round 1 |
| .gitignore | reproducibility/public_templates/.gitignore | APPROVED round 1 |
| code/verify_public_export.sh | reproducibility/verify_public_export.sh | APPROVED round 1 |

## Approved for Round 2 (harness transparency set)

| path (public repo) | source (private repo) | status |
|---|---|---|
| code/benchmark/provider_adapter.py | code/benchmark/provider_adapter.py | APPROVED round 2 (no secrets; policy code) |
| code/benchmark/run_benchmark.py | code/benchmark/run_benchmark.py | APPROVED round 2 (orchestrator; documents private dependencies) |
| code/benchmark/validate_tasks.py | code/benchmark/validate_tasks.py | APPROVED round 2 |
| code/benchmark/build_rating_package.py | code/benchmark/build_rating_package.py | APPROVED round 2 |
| code/benchmark/analyze_ratings.py | code/benchmark/analyze_ratings.py | APPROVED round 2 (2B rewrite) |
| code/benchmark/estimate_budget.py | code/benchmark/estimate_budget.py | APPROVED round 2 (2B rewrite) |
| code/benchmark/paired_proportions.py | code/benchmark/paired_proportions.py | APPROVED round 2B |
| code/benchmark/make_manifest.py | code/benchmark/make_manifest.py | APPROVED round 2B |
| tests/test_harness.py | tests/test_harness.py | APPROVED round 2 (2B: 22 adversarial tests; synthetic fixtures only) |
| tests/fixtures/README.md + example_*.{json,jsonl,csv} | same paths | APPROVED round 2 (labeled synthetic) |
| protocols/benchmark_plan_v2.md | protocols/benchmark_plan_v2.md | APPROVED round 2 (2B wording fixes) |
| protocols/task_sampling_plan.md | protocols/task_sampling_plan.md | APPROVED round 2 (2B wording fixes) |
| evaluation/rater_instructions.md | evaluation/rater_instructions.md | APPROVED round 2 (no data) |
| evaluation/annotation_codebook.md | evaluation/annotation_codebook.md | APPROVED round 2 (no data) |
| reproducibility_gaps.md | reproducibility/reproducibility_gaps.md | APPROVED round 2B |

NOT exported in Round 2 (deliberate): pipeline_bridge.js and
extract_prompts.js (depend on private frozen extracts), frozen prompt text,
all task JSONs (dev + held-out until locked), run logs, ratings, and any
workshop-derived material. The public README documents this dependency
honestly.

## Queued for Round 2+ (requires review before export)

| item | gate |
|---|---|
| Benchmark harness (new, standalone code; no production internals) | author review + no secrets + no PII |
| Frozen task registry (questions, reference URLs, DOIs) | author review; no workshop questions |
| Evaluation rubric | author review |
| Benchmark run logs + human ratings (no participant data) | author review |
| Aggregate-only workshop statistics (no PII, no participant-level rows) | permission resolution (ethics gate) |
| Figure/table generation scripts + outputs | depends on the above |
| De-identified analysis dataset (pseudonymous, aggregated) | permission resolution + author review |

## Never exported (hard exclusions)

- Participant records, emails, names, user ids, feedback text, question text
  from workshop users.
- Production server code, configs, prompts, database schemas/snapshots.
- Credentials or .env contents.
- Manuscript drafts and submission materials.
- Copyrighted full texts without redistribution permission.
- ALS/Wilson project material.

## Workflow

1. Review item against gates in this file.
2. Run `code/verify_public_export.sh` in the private repo (scans staged files
   for secrets/identifiers and checks allowlist membership).
3. Copy approved files into the public repo and commit separately.
4. Verify remote SHA and visibility after push.
