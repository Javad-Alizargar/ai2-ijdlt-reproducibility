# ai2-ijdlt-reproducibility (PUBLIC)

Public reproducibility workspace for the study:

> Expert-informed design and evaluation of an AI-supported evidence workspace
> for scientific inquiry (AI2, https://ai2.statwhy.com).

Target journal: International Journal on Digital Learning Technology
(數位學習科技期刊, ISSN 2071-260X).

## Status (Round 2)

The study is UNDER DEVELOPMENT. This repository contains the shareable
harness-transparency set (policy-compliant provider adapter, orchestrator,
task/rating validators, gated analysis script, budget estimator, synthetic
fixture tests, and protocol documentation). No participant records, private
production code, manuscript drafts, findings, task questions, held-out
answers, or ratings are included.

KNOWN PARTIAL DEPENDENCY (recorded honestly): the benchmark orchestrator
references two components that live only in the private research repository —
the frozen-pipeline bridge (Node) and the hash-pinned prompt file extracted
from the author's production code. This harness is therefore shared for
transparency and audit, but is not fully runnable by itself without those
private components. All policy logic, gates, and analysis paths are
independently testable with the included synthetic fixtures.

Planned later exports (after gates in EXPORT_ALLOWLIST.md): frozen task
registry (after evaluation lock), rubric, aggregate-only statistics (after
permission resolution), and figure/table scripts.

## What AI2 is (verified from the deployed system)

AI2 is a web workspace for professors, researchers, and health-professions
learners that retrieves PubMed and OpenAlex literature first and then uses a
language model to synthesize cited answers restricted to retrieved sources,
with a citation-supervision pass and an insufficient-evidence refusal path.
It was used in a hands-on session of the StatWhy Clinical AI Workshop
(2026-09-15, NTUNHS), and same-day expert-informed revisions are archived.

## Contents

- EXPORT_ALLOWLIST.md — what may ever be exported from the private research repo.
- environment_public.md — public, credential-free environment description.
- code/verify_public_export.sh — export-compliance scanner.

## Licensing

Licensing decisions for this repository are OPEN and will be decided by the
author in a later round. Nothing here relicenses third-party work. Public
benchmark tasks will reference public guideline documents by URL/DOI rather
than redistributing them.
