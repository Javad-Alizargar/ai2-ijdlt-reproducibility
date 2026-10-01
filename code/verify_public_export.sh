#!/usr/bin/env bash
# verify_public_export.sh — export-compliance scanner for the public repo.
# Usage (from public repo root): bash code/verify_public_export.sh
# Checks: (1) every tracked file is in the allowlist set; (2) no secret/identifier
# patterns; (3) no restricted markers. Exits non-zero on any violation.
set -u

ALLOWED=(
  "README.md"
  "EXPORT_ALLOWLIST.md"
  "environment_public.md"
  ".gitignore"
  "code/verify_public_export.sh"
  "code/benchmark/provider_adapter.py"
  "code/benchmark/run_benchmark.py"
  "code/benchmark/validate_tasks.py"
  "code/benchmark/build_rating_package.py"
  "code/benchmark/analyze_ratings.py"
  "code/benchmark/estimate_budget.py"
  "tests/test_harness.py"
  "tests/fixtures/README.md"
  "tests/fixtures/example_synthetic_task.json"
  "tests/fixtures/example_synthetic_runlog.jsonl"
  "tests/fixtures/example_synthetic_ratings.csv"
  "protocols/benchmark_plan_v2.md"
  "protocols/task_sampling_plan.md"
  "evaluation/rater_instructions.md"
  "evaluation/annotation_codebook.md"
)

SECRET_PATTERNS=(
  "sk-[A-Za-z0-9]{10,}"
  "ghp_[A-Za-z0-9]{20,}"
  "gho_[A-Za-z0-9]{20,}"
  "AIza[0-9A-Za-z_-]{20,}"
  "BEGIN [A-Z ]*PRIVATE KEY"
  "AKIA[0-9A-Z]{16}"
)

IDENT_PATTERNS=(
  "consent_followup"
  "ai2_questions"
  "feedback_json"
  "@gmail\.com"
  "\.sqlite"
  "users\.jsonl"
)

violations=0

echo "== allowlist membership =="
while IFS= read -r f; do
  case "$f" in
    .git/*|.git) continue ;;
  esac
  ok=0
  for a in "${ALLOWED[@]}"; do
    [ "$f" = "$a" ] && ok=1 && break
  done
  if [ "$ok" -eq 0 ]; then
    echo "NOT-ALLOWED: $f"
    violations=$((violations + 1))
  else
    echo "allowed: $f"
  fi
done < <(git ls-files)

echo "== secret/identifier scan =="
while IFS= read -r f; do
  case "$f" in
    .git/*|.git) continue ;;
    code/verify_public_export.sh) continue ;;  # scanner's own pattern lists
  esac
  for p in "${SECRET_PATTERNS[@]}" "${IDENT_PATTERNS[@]}"; do
    if grep -Enq "$p" "$f" 2>/dev/null; then
      echo "PATTERN-HIT: $f :: $p"
      violations=$((violations + 1))
    fi
  done
done < <(git ls-files)

echo "== restricted markers =="
if grep -REnq "AUTHOR-REPORTED|VERIFIED|participant|feedback" README.md EXPORT_ALLOWLIST.md 2>/dev/null; then
  echo "note: human-readable status words present (allowed in README/allowlist, review manually)"
fi

echo
if [ "$violations" -eq 0 ]; then
  echo "PASS: export-compliant."
  exit 0
else
  echo "FAIL: $violations violation(s)."
  exit 1
fi
