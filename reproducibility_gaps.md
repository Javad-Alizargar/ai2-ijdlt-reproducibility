# Reproducibility Gap List — Public Package vs Full Study

2026-10-01. The public repository is a PARTIAL transparency package. The gaps
below are deliberate and recorded; a generic substitute that is independently
runnable would NOT by itself reproduce the actual AI2 system, and no such
claim is made anywhere.

| # | missing component | why needed | disclosure/licensing status | proposed shareable substitute or future export |
|---|---|---|---|---|
| 1 | pipeline_bridge.js (frozen retrieval/scoring/audit stages) | executes the actual deployed pipeline logic in the benchmark | author-owned production-derived code; NOT exported; licensing decision open | a documented extraction procedure + hash manifest; a schematic walkthrough in the public README; possible future export after author licensing decision |
| 2 | frozen prompt texts (answer + supervisor system prompts) | define the exact system under test | extracted from production code; same status as #1 | prompt hash pinning in the frozen manifest (hashes are shareable); verbatim texts only if author later authorizes |
| 3 | task files (dev + held-out) | benchmark inputs | held-out tasks are withheld until evaluation lock (anti-contamination); dev tasks withheld for the same reason | public task SCHEMA (validate_tasks.py) + synthetic fixture tasks; task registry with source URLs/DOIs after the evaluation is locked |
| 4 | run logs and retrieval snapshots | raw provenance of benchmark outputs | contains model outputs and retrieval metadata; export gated on author review | aggregate run-accounting tables after review |
| 5 | human ratings and adjudication | the primary outcome data | human-review records; restricted | aggregate 2×2 + CI values in the final report only |
| 6 | workshop feedback records | workshop-derived evidence | participant data; permission unresolved | process-level counts only (already in reports) |
| 7 | production server code/config (server.js etc.) | the system's full implementation | private production code; never exported | frozen SHA-256 manifest + replay-equivalence documentation |

All exported items pass the allowlist scanner (code/verify_public_export.sh).
No new software license has been applied; licensing remains an open author
decision.
