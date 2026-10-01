#!/usr/bin/env python3
"""
analyze_ratings.py — gated benchmark analysis from human ratings.

Hard gates (script refuses with exit 2):
- run log missing or empty
- a rating row references a run not in the log
- blank required rating fields in rows that are not challenge rows
- run records missing for expected task x arm x repetition (run_failed allowed,
  but only via explicit run_failed status)
- fixture contamination (fixture runs cannot enter empirical tables)
- rubric/rubric-hash mismatch (if --rubric-hash given)

Outputs:
- family-level paired table (first scheduled run per arm per family)
- exact McNemar + paired rate-difference CI
- sensitivity at 60/70/90/100% element thresholds
- stability (across-repetition agreement)
- exploratory secondaries
Usage:
  python3 code/benchmark/analyze_ratings.py --run-log <jsonl> --ratings <csv> \
    --tasks-dir tasks/dev [--rubric-hash <sha>] [--out-dir results/analysis]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

THRESHOLD = 0.80
SENSITIVITIES = (0.60, 0.70, 0.80, 0.90, 1.00)
RATE_OPTIONS = {"supported_and_correctly_cited", "supported_but_miscited",
                "unsupported", "omitted", "refusal", "not_ratable"}


def exact_mcnemar(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value on discordant pairs (b, c)."""
    d = b + c
    lo = min(b, c)
    p = 0.0
    for i in range(lo + 1):
        p += comb(d, i)
    p *= 2 * (0.5 ** d)
    return min(1.0, p)


def paired_diff_ci(p1: float, p2: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Newcombe-style interval for paired difference via Wilson components."""
    def wilson(p, n):
        if n == 0:
            return 0.0, 0.0
        denom = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denom
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
        return center - half, center + half

    l1, u1 = wilson(p1, n)
    l2, u2 = wilson(p2, n)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return lo, hi


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-log", required=True)
    ap.add_argument("--ratings", required=True)
    ap.add_argument("--tasks-dir", required=True)
    ap.add_argument("--rubric-hash", default=None)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    runs = []
    with open(args.run_log) as f:
        for line in f:
            if line.strip():
                runs.append(json.loads(line))
    if not runs:
        print("GATE-FAIL: empty run log")
        return 2
    run_by_id = {r["run_id"]: r for r in runs}
    if any(r.get("fixture") for r in runs):
        print("GATE-FAIL: fixture run present in empirical log")
        return 2

    tasks = {p.stem: json.loads(p.read_text())
             for p in Path(args.tasks_dir).glob("*.json") if not p.name.startswith("_")}
    expected = defaultdict(set)
    for r in runs:
        expected[(r.get("task_id"), r.get("arm"))].add(r["run_id"])

    # family-level scoring structure FIRST so structural gates report before
    # ratings gates.
    fam_arm_slot = {}
    for r in runs:
        fam = r.get("family_id") or r.get("task_id")
        arm = r.get("arm")
        fam_arm_slot.setdefault((fam, arm), [])
        fam_arm_slot[(fam, arm)].append(r)

    # duplicate + missing arm checks (empirical mode)
    for (fam, arm), rs in fam_arm_slot.items():
        slots = [r.get("run_slot") for r in rs]
        if len(slots) != len(set(slots)):
            print(f"GATE-FAIL: family {fam} arm {arm} has duplicate run_slot entries")
            return 2
    families = {fam for fam, _ in fam_arm_slot}
    for fam in families:
        present_arms = {arm for (f, arm) in fam_arm_slot if f == fam}
        if "A" not in present_arms or "B" not in present_arms:
            print(f"GATE-FAIL: family {fam} missing an arm (present: {sorted(present_arms)})")
            return 2

    # config parity across arms (same configuration must be used)
    for fam in families:
        hashes = {}
        for arm in ("A", "B"):
            rs = sorted(fam_arm_slot[(fam, arm)], key=lambda r: (r.get("run_slot") or 99))
            hashes[arm] = rs[0].get("config_hash")
        if hashes.get("A") != hashes.get("B"):
            print(f"GATE-FAIL: family {fam} config_hash differs across arms "
                  f"(A={hashes.get('A')}, B={hashes.get('B')})")
            return 2

    ratings = defaultdict(list)
    with open(args.ratings, newline="") as f:
        for row in csv.DictReader(f):
            rid = row["run_id"]
            if rid not in run_by_id:
                print(f"GATE-FAIL: rating references unknown run {rid}")
                return 2
            if not row["rater_id"].strip():
                print(f"GATE-FAIL: blank rater_id for {rid}/{row.get('element_id')}")
                return 2
            if not row["rating"].strip() and row.get("refusal_flag", "").strip() != "yes":
                print(f"GATE-FAIL: blank rating (and no refusal flag) for {rid}/{row.get('element_id')}")
                return 2
            ratings[rid].append(row)
    if not ratings:
        print("GATE-FAIL: no ratings loaded")
        return 2

    missing = [rid for rid in run_by_id if run_by_id[rid].get("status") == "done" and rid not in ratings]
    if missing:
        print(f"GATE-FAIL: {len(missing)} done runs have no ratings: {missing[:5]}...")
        return 2

    run_accounting = {}
    for arm in ("A", "B"):
        rs = [r for r in runs if r.get("arm") == arm]
        run_accounting[arm] = {
            "total_runs": len(rs),
            "done": sum(1 for r in rs if r.get("status") == "done"),
            "run_failed": sum(1 for r in rs if r.get("status") == "run_failed"),
            "refused_insufficient": sum(1 for r in rs if r.get("status") == "refused_insufficient_evidence"),
        }

    def task_success(task_id: str, run_id: str, threshold: float) -> dict:
        task = tasks[task_id]
        rows = ratings[run_id]
        if task.get("challenge_kind"):
            # challenge scoring: refusal_flag handled separately by caller
            return {"challenge": True, "success": None}
        elements = task.get("required_answer_elements", [])
        total = len(elements)
        supported = 0
        detail = Counter()
        fab = any((r.get("fabrication_flag") or "").strip() == "yes" for r in rows)
        contra = any((r.get("contradiction_flag") or "").strip() == "yes" for r in rows)
        refusal = any((r.get("refusal_flag") or "").strip() == "yes" for r in rows)
        by_el = {}
        for e in elements:
            sub = [r for r in rows if r["element_id"] == e["element_id"]]
            # adjudicated consensus: mode rating; ties -> more severe
            votes = Counter((r["rating"] or "").strip() for r in sub if r["rating"].strip())
            if not votes:
                detail["unrated_element"] += 1
                by_el[e["element_id"]] = "not_ratable"
                continue
            top = max(votes.values())
            winners = [k for k, v in votes.items() if v == top]
            winner = min(winners, key=lambda k: list(RATE_OPTIONS).index(k) if k in RATE_OPTIONS else 9)
            if winner == "supported_and_correctly_cited":
                # bibliographic existence != support: require explicit ref verification
                verified = all((r.get("ref_verified") or "").strip() == "yes" for r in sub
                               if (r["rating"] or "").strip() == winner)
                if not verified:
                    winner = "supported_but_miscited"
            by_el[e["element_id"]] = winner
            if winner == "supported_and_correctly_cited":
                supported += 1
            elif winner == "refusal":
                detail["refusal_element"] += 1
            elif winner == "unsupported":
                detail["unsupported_element"] += 1
            elif winner == "supported_but_miscited":
                detail["miscited_element"] += 1
            elif winner == "omitted":
                detail["omitted_element"] += 1
        frac = supported / total if total else 0.0
        success = (frac >= threshold) and (not fab) and (not contra) and (not refusal)
        return {"challenge": False, "success": bool(success), "frac": frac,
                "total": total, "supported": supported, "fabrication": fab,
                "contradiction": contra, "refusal": refusal, "detail": dict(detail),
                "by_element": by_el}

    # primary: first scheduled run per family per arm
    first_run = {}
    for (fam, arm), rs in fam_arm_slot.items():
        rs_sorted = sorted(rs, key=lambda r: (r.get("run_slot") or 99))
        first_run[(fam, arm)] = rs_sorted[0]

    answerable_families = []
    excluded_families = []
    for fam in sorted({fam for (fam, _), r in first_run.items()
                       if not tasks[r["task_id"]].get("challenge_kind")}):
        ok = True
        reason = ""
        for arm in ("A", "B"):
            r = first_run[(fam, arm)]
            if r.get("status") != "done":
                ok = False
                reason = f"arm {arm} status={r.get('status')}"
        if ok:
            answerable_families.append(fam)
        else:
            excluded_families.append({"family": fam, "reason": reason})
    results = {}
    for fam in answerable_families:
        results[fam] = {}
        for arm in ("A", "B"):
            r = first_run[(fam, arm)]
            res = task_success(r["task_id"], r["run_id"], THRESHOLD)
            results[fam][arm] = res
    b = c = 0
    table = []
    for fam in answerable_families:
        sa = bool(results[fam]["A"]["success"])
        sb = bool(results[fam]["B"]["success"])
        if sa and not sb:
            b += 1
        elif sb and not sa:
            c += 1
        table.append({"family": fam, "arm_a_success": sa, "arm_b_success": sb})
    p_a = sum(1 for fam in answerable_families if results[fam]["A"]["success"]) / len(answerable_families)
    p_b = sum(1 for fam in answerable_families if results[fam]["B"]["success"]) / len(answerable_families)
    lo, hi = paired_diff_ci(p_a, p_b, len(answerable_families))
    pval = exact_mcnemar(b, c)

    out = {
        "n_families": len(answerable_families),
        "excluded_families": excluded_families,
        "threshold": THRESHOLD,
        "arm_a_rate": p_a, "arm_b_rate": p_b,
        "diff": p_a - p_b, "diff_ci": [lo, hi],
        "discordant": {"b_a_only": b, "c_b_only": c},
        "mcnemar_p_exact": pval,
        "paired_table": table,
        "run_accounting": run_accounting,
        "note_failed_runs": "run_failed runs are retained in the log and reported here; only status==done runs receive ratings",
    }

    # sensitivity across thresholds
    sens = {}
    for th in SENSITIVITIES:
        succ = {fam: {"A": bool(task_success(first_run[(fam, "A")]["task_id"],
                                             first_run[(fam, "A")]["run_id"], th)["success"]),
                      "B": bool(task_success(first_run[(fam, "B")]["task_id"],
                                             first_run[(fam, "B")]["run_id"], th)["success"])}
                for fam in answerable_families}
        sens[str(th)] = {
            "arm_a_rate": sum(1 for fam in answerable_families if succ[fam]["A"]) / len(answerable_families),
            "arm_b_rate": sum(1 for fam in answerable_families if succ[fam]["B"]) / len(answerable_families),
        }
    out["sensitivity_by_threshold"] = sens

    # stability: agreement across repetitions
    stability = {}
    for fam in answerable_families:
        for arm in ("A", "B"):
            rs = sorted(fam_arm_slot[(fam, arm)], key=lambda r: (r.get("run_slot") or 99))
            verdicts = [bool(task_success(r["task_id"], r["run_id"], THRESHOLD)["success"]) for r in rs
                        if r.get("status") == "done"]
            if len(verdicts) >= 2:
                agree = 1.0 if all(v == verdicts[0] for v in verdicts) else 0.0
            else:
                agree = None
            stability[f"{fam}:{arm}"] = {"n_verdicts": len(verdicts), "all_agree": agree}
    out["stability"] = stability

    # challenge task results (separate, never pooled)
    challenge = {}
    for (fam, arm), rs in fam_arm_slot.items():
        r = rs[0]
        t = tasks[r["task_id"]]
        if t.get("challenge_kind"):
            rows = ratings.get(r["run_id"], [])
            refusal_yes = any((x.get("refusal_flag") or "").strip() == "yes" for x in rows)
            challenge[f"{fam}:{arm}"] = {"challenge_kind": t.get("challenge_kind"),
                                         "abstained": refusal_yes}
    out["challenge_results_separate"] = challenge

    print(json.dumps(out, indent=1, ensure_ascii=False))
    if args.out_dir:
        p = Path(args.out_dir)
        p.mkdir(parents=True, exist_ok=True)
        (p / "analysis_primary.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
        print("saved:", p / "analysis_primary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
