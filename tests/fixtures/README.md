# Synthetic fixtures (software tests only — NOT research findings)

These files exist solely to exercise the harness gates in
tests/test_harness.py. Everything here is labeled `fixture: true` and the
analysis gates REFUSE to accept fixture rows in empirical result tables.

- example_synthetic_task.json — a minimal answerable task with fabricated
  provenance (never rated as research evidence).
- example_synthetic_runlog.jsonl — synthetic run records incl. one run_failed
  and one arm-mismatch example for gate tests.
- example_synthetic_ratings.csv — synthetic rating rows incl. a deliberately
  blank field (for the blank-rating gate test).
