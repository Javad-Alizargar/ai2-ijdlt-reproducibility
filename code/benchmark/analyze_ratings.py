#!/usr/bin/env python3
"""
analyze_ratings.py — gated benchmark analysis from human ratings (Round 2B).

PRIMARY ESTIMAND (fixed before any held-out inspection; do not change it
afterwards): for each scheduled answerable task family, did each arm deliver
a successful grounded answer in its PRESPECIFIED primary run under the fixed
retry policy? Delivery rules:

- A terminal generation failure (run_failed) on an answerable task counts as
  an UNSUCCESSFUL delivered answer; the family REMAINS in the denominator.
- A pipeline refusal (refused_insufficient_evidence) on an answerable task
  likewise counts as unsuccessful; status preserved and reported.
- A later successful repetition NEVER substitutes for a failed primary run.
- A missing run record is INCOMPLETE EXECUTION (analysis blocked until the
  schedule is completed), not an automatic failure.
- Missing human assessments of an existing answer are INCOMPLETE EVALUATION
  (blocked), not automatic failures or exclusions.
- Challenge tasks are scored separately; appropriate abstention is a
  HUMAN-rated category and absence of an answer is NOT automatically a
  correct refusal; technical failure is a system status, not abstention.

Rating decisions are NOT auto-adjudicated: no mode, no tie-breaking by
enumeration order, no severity ordering. Independent ratings are preserved;
disagreements require an explicit adjudication file (run_id, element_id,
final_rating, reviewer_id, date, rationale). Final scored analysis is
BLOCKED until every disagreement is adjudicated.

Exit codes: 0 = scored results; 2 = structural gate violation; 3 = blocked
pending human input (missing assessments/adjudication/incomplete execution).

Usage:
  python3 code/benchmark/analyze_ratings.py \
    --run-log <jsonl> --ratings <csv> --tasks-dir <dir> \
    --manifest <expected-run manifest json> \
    [--adjudication <csv>] [--rubric-hash <sha>] [--out-dir <dir>]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paired_proportions import (cluster_bootstrap_paired_diff,  # noqa: E402
                                exact_mcnemar, score_paired_diff_ci)

THRESHOLD = 0.80
SENSITIVITIES = (0.60, 0.70, 0.80, 0.90, 1.00)

RATE_ORDER = ("supported_and_correctly_cited", "supported_but_miscited",
              "unsupported", "omitted", "refusal", "not_ratable")
RATE_VALUES = set(RATE_ORDER)
CHALLENGE_ORDER = ("appropriate_abstention", "inappropriate_confidence",
                   "partial_redirect", "not_ratable")
CHALLENGE_VALUES = set(CHALLENGE_ORDER)
FLAG_VALUES = {"yes", "no"}
REF_VERIFIED_VALUES = {"yes", "no", ""}
TERMINAL_STATUSES = {"done", "run_failed", "refused_insufficient_evidence"}
RATING_COLS = {"rating_id", "rater_id", "run_id", "task_id", "family_id",
               "element_id", "rating", "notes", "ref_verified",
               "fabrication_flag", "contradiction_flag", "refusal_flag"}
ADJUDICATION_COLS = {"run_id", "task_id", "family_id", "element_id",
                     "final_rating", "reviewer_id", "date", "rationale"}
MANIFEST_CONFIG_KEYS = {"shared_config_hash", "arm_config_hash",
                        "arm_config_required", "rubric_hash",
                        "expected_raters", "repetitions"}
MANIFEST_ROW_KEYS = {"task_id", "family_id", "variant_language", "arm",
                     "repetition", "is_primary", "rubric_hash",
                     "challenge_kind"}

BLOCKED = 3
GATE = 2
OK = 0


def gate(msg: str) -> int:
    print("GATE-FAIL:", msg)
    return GATE


def blocked(report: dict, reasons: list[str]) -> int:
    report["blocked"] = True
    report["blocked_reasons"] = reasons
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return BLOCKED


def load_manifest(path: Path) -> dict:
    with open(path) as f:
        m = json.load(f)
    if "schedule" not in m or not isinstance(m["schedule"], list):
        raise ValueError("manifest missing schedule list")
    if "config" not in m:
        raise ValueError("manifest missing config block")
    unknown_cfg = set(m["config"]) - MANIFEST_CONFIG_KEYS
    if unknown_cfg:
        raise ValueError(f"manifest config has unknown keys: {sorted(unknown_cfg)}")
    for row in m["schedule"]:
        unknown = set(row) - MANIFEST_ROW_KEYS
        if unknown:
            raise ValueError(f"manifest row has unknown keys: {sorted(unknown)}")
    return m


def resolve_element(run_id: str, element_id: str, ratings: dict,
                    adjudication: dict, report: dict) -> tuple[str, bool]:
    """Deterministic element resolution: unanimous agreement or explicit
    adjudication. Returns (final_rating, resolved). Never auto-ties."""
    order = RATE_ORDER + CHALLENGE_ORDER
    votes = ratings.get((run_id, element_id), {})
    values = list(votes.values())
    if not values:
        report["missing_assessments"].append({"run_id": run_id,
                                              "element_id": element_id})
        return "not_ratable", False
    uniq = sorted(set(values), key=order.index)
    if len(uniq) == 1:
        return uniq[0], True
    adj = adjudication.get((run_id, element_id))
    if adj is not None:
        return adj["final_rating"], True
    report["pending_adjudications"].append({
        "run_id": run_id, "element_id": element_id,
        "independent_ratings": votes,
    })
    return "", False


def resolve_flag(run_id: str, flag: str, ratings: dict, report: dict) -> tuple[str, bool]:
    """Flags are per rater; unanimous yes/no resolves, disagreement blocks."""
    per_rater = ratings.get((run_id, "_flag_" + flag), {})
    values = sorted(set(per_rater.values()))
    if not values:
        return "no", True
    if len(values) == 1:
        return values[0], True
    report["pending_adjudications"].append({
        "run_id": run_id, "element_id": "_flag_" + flag,
        "independent_ratings": per_rater,
    })
    return "", False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-log", required=True)
    ap.add_argument("--ratings", required=True)
    ap.add_argument("--tasks-dir", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--adjudication", default=None)
    ap.add_argument("--rubric-hash", default=None)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    try:
        manifest = load_manifest(Path(args.manifest))
    except Exception as e:
        return gate(f"manifest invalid: {e}")

    # ---- runs ----
    runs = []
    with open(args.run_log) as f:
        for line in f:
            if line.strip():
                runs.append(json.loads(line))
    if not runs:
        return gate("empty run log")
    seen_ids = set()
    run_by_id = {}
    for r in runs:
        rid = r.get("run_id")
        if rid in seen_ids:
            return gate(f"duplicate run_id in log: {rid}")
        seen_ids.add(rid)
        run_by_id[rid] = r
    if any(r.get("fixture") for r in runs):
        return gate("fixture run present in empirical log")
    for r in runs:
        st = r.get("status")
        if st not in TERMINAL_STATUSES:
            return gate(f"nonterminal/unknown status {st!r} for {r.get('run_id')}")

    # ---- tasks ----
    tasks = {}
    for p in Path(args.tasks_dir).glob("*.json"):
        if p.name.startswith("_"):
            continue
        t = json.loads(p.read_text())
        if t.get("fixture"):
            return gate(f"fixture task in empirical tasks dir: {p.name}")
        tasks[p.stem] = t

    # ---- rubric hash enforcement (advertised but previously unverified) ----
    cfg = manifest["config"]
    rubric_hash = cfg.get("rubric_hash")
    if args.rubric_hash is not None:
        if rubric_hash is not None and args.rubric_hash != rubric_hash:
            return gate(f"--rubric-hash {args.rubric_hash} != manifest rubric_hash {rubric_hash}")
        if rubric_hash is None:
            return gate("--rubric-hash provided but manifest has no rubric_hash")
    if rubric_hash is not None:
        for row in manifest["schedule"]:
            if row.get("rubric_hash") != rubric_hash:
                return gate(f"manifest row {row.get('task_id')} rubric_hash mismatch")
        for tid, t in tasks.items():
            if t.get("rubric_hash") != rubric_hash:
                return gate(f"task {tid} rubric_hash missing or mismatched")

    # ---- manifest structure ----
    schedule = manifest["schedule"]
    if not schedule:
        return gate("empty manifest schedule")
    dup_slots = set()
    primary_flags = defaultdict(list)
    manifest_rows = {}
    for row in schedule:
        key = (row["task_id"], row["arm"], row["repetition"])
        if key in dup_slots:
            return gate(f"duplicate logical run slot {key}")
        dup_slots.add(key)
        if row.get("is_primary"):
            primary_flags[(row["family_id"], row["arm"])].append(row["repetition"])
        manifest_rows[key] = row
    # exactly one primary run per (family, arm)
    fam_arm_slots = defaultdict(set)
    for row in schedule:
        fam_arm_slots[(row["family_id"], row["arm"])].add(row["repetition"])
    for (fam, arm), primaries in primary_flags.items():
        if len(primaries) != 1:
            return gate(f"family {fam} arm {arm}: expected exactly 1 primary run, got {sorted(primaries)}")
    for (fam, arm), reps in fam_arm_slots.items():
        if not primary_flags.get((fam, arm)):
            return gate(f"family {fam} arm {arm}: no primary run designated")
        if primary_flags[(fam, arm)][0] not in reps:
            return gate(f"family {fam} arm {arm}: primary run not in scheduled slots")
    if "repetitions" in cfg and cfg["repetitions"] is not None:
        for (fam, arm), reps in fam_arm_slots.items():
            if max(reps) > cfg["repetitions"] or min(reps) < 1:
                return gate(f"family {fam} arm {arm}: repetition out of declared range")

    # unexpected runs
    manifest_run_ids = set()
    for row in schedule:
        manifest_run_ids.add(f"{row['task_id']}__{row['arm']}__r{row['repetition']}")
    for rid in run_by_id:
        if rid not in manifest_run_ids:
            return gate(f"run record not in manifest: {rid}")

    # missing run records -> incomplete execution (blocked, not failures)
    incomplete_runs = []
    for row in schedule:
        rid = f"{row['task_id']}__{row['arm']}__r{row['repetition']}"
        if rid not in run_by_id:
            incomplete_runs.append({"run_id": rid, "task_id": row["task_id"],
                                    "arm": row["arm"], "repetition": row["repetition"]})

    # config hashes
    if cfg.get("shared_config_hash"):
        for rid, r in run_by_id.items():
            if r.get("shared_config_hash") != cfg["shared_config_hash"]:
                return gate(f"{rid}: shared_config_hash mismatch (or missing)")
    if cfg.get("arm_config_required"):
        if not cfg.get("arm_config_hash") or not isinstance(cfg["arm_config_hash"], dict):
            return gate("manifest arm_config_required but arm_config_hash missing")
        for rid, r in run_by_id.items():
            want = cfg["arm_config_hash"].get(r.get("arm"))
            if want is None or r.get("arm_config_hash") != want:
                return gate(f"{rid}: arm_config_hash mismatch (or missing)")

    # development/synthetic records entering held-out analysis
    if cfg.get("rubric_hash") is not None and manifest.get("set") == "heldout":
        for rid, r in run_by_id.items():
            if r.get("set") != "heldout":
                return gate(f"{rid}: non-heldout run in held-out analysis")

    # ---- ratings ----
    expected_raters = cfg.get("expected_raters") or []
    ratings_by_run = defaultdict(list)
    with open(args.ratings, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not RATING_COLS.issubset(set(reader.fieldnames)):
            return gate("ratings CSV missing required columns")
        for row in reader:
            rid = row["run_id"]
            if rid not in run_by_id:
                return gate(f"rating references unknown run {rid}")
            run = run_by_id[rid]
            row_task = run.get("task_id")
            if row.get("task_id") != row_task or row.get("family_id") != run.get("family_id"):
                return gate(f"rating metadata mismatch for {rid}")
            rater = (row.get("rater_id") or "").strip()
            if not rater:
                return gate(f"blank rater_id for {rid}/{row.get('element_id')}")
            if expected_raters and rater not in expected_raters:
                return gate(f"unknown rater {rater!r} for {rid}")
            rating = (row.get("rating") or "").strip()
            if rating not in RATE_VALUES and rating not in CHALLENGE_VALUES:
                return gate(f"invalid rating {rating!r} for {rid}/{row.get('element_id')}")
            for fl in ("fabrication_flag", "contradiction_flag", "refusal_flag"):
                v = (row.get(fl) or "").strip().lower()
                if v not in FLAG_VALUES:
                    return gate(f"malformed flag {fl}={v!r} for {rid}")
            ref = (row.get("ref_verified") or "").strip()
            if ref not in REF_VERIFIED_VALUES:
                return gate(f"malformed ref_verified {ref!r} for {rid}")
            ratings_by_run[rid].append(row)
    if not ratings_by_run and any(run.get("status") == "done" for run in run_by_id.values()):
        return gate("no ratings loaded but done runs exist")
    if not ratings_by_run and not any(run.get("status") == "done" for run in run_by_id.values()):
        pass  # all-failed/all-unassessed schedules have no ratings to load

    # duplicate rater/element rows
    for rid, rows in ratings_by_run.items():
        seen = set()
        for row in rows:
            key = (row["rater_id"], row["element_id"])
            if key in seen:
                return gate(f"duplicate rater/element row for {rid}: {key}")
            seen.add(key)

    # per-rater flag consistency within a run
    for rid, rows in ratings_by_run.items():
        for rater in {r["rater_id"] for r in rows}:
            sub = [r for r in rows if r["rater_id"] == rater]
            for fl in ("fabrication_flag", "contradiction_flag", "refusal_flag"):
                vals = {(r.get(fl) or "").strip().lower() for r in sub}
                if len(vals) > 1:
                    return gate(f"rater {rater} inconsistent {fl} across rows for {rid}")

    # ---- completeness of assessments ----
    missing_assessments = []
    for rid, run in run_by_id.items():
        if run.get("status") != "done":
            continue
        task = tasks.get(run.get("task_id"))
        if task is None:
            return gate(f"run {rid} references unknown task {run.get('task_id')}")
        if task.get("challenge_kind"):
            elements = ["challenge"]
        else:
            elements = [e["element_id"] for e in task.get("required_answer_elements", [])]
        raters_here = {r["rater_id"] for r in ratings_by_run[rid]}
        want_raters = expected_raters if expected_raters else raters_here
        for rater in want_raters:
            for eid in elements:
                has = any(r["rater_id"] == rater and r["element_id"] == eid
                          for r in ratings_by_run[rid])
                if not has:
                    missing_assessments.append({"run_id": rid, "rater_id": rater,
                                                "element_id": eid})
        extra = [r for r in ratings_by_run[rid]
                 if r["element_id"] not in set(elements)]
        if extra:
            return gate(f"extra rating elements for {rid}: {[r['element_id'] for r in extra][:5]}")

    # ---- adjudication file ----
    adjudication = {}
    if args.adjudication:
        with open(args.adjudication, newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or not ADJUDICATION_COLS.issubset(set(reader.fieldnames)):
                return gate("adjudication CSV missing required columns")
            for row in reader:
                key = (row["run_id"], row["element_id"])
                if key in adjudication:
                    return gate(f"duplicate adjudication row for {key}")
                if row["final_rating"] not in RATE_VALUES and row["final_rating"] not in CHALLENGE_VALUES:
                    return gate(f"invalid adjudicated rating {row['final_rating']!r}")
                if not (row.get("reviewer_id") or "").strip() or not (row.get("date") or "").strip():
                    return gate(f"adjudication row missing reviewer/date for {key}")
                adjudication[key] = row

    report = {"missing_assessments": missing_assessments,
              "pending_adjudications": []}
    if incomplete_runs:
        report["incomplete_execution_runs"] = incomplete_runs
        return blocked(report, ["incomplete execution: scheduled run records missing"])
    if missing_assessments:
        return blocked(report, ["incomplete evaluation: required ratings missing"])

    # ---- resolve ratings deterministically (unanimous or adjudicated) ----
    # element votes: (run_id, element_id) -> {rater: rating}
    element_votes = defaultdict(dict)
    flag_votes = defaultdict(dict)
    for rid, rows in ratings_by_run.items():
        for row in rows:
            element_votes[(rid, row["element_id"])][row["rater_id"]] = row["rating"]
            for fl in ("fabrication_flag", "contradiction_flag", "refusal_flag"):
                flag_votes[(rid, "_flag_" + fl)][row["rater_id"]] = \
                    (row.get(fl) or "").strip().lower()

    def elem_rating(rid, eid):
        return resolve_element(rid, eid, element_votes, adjudication, report)

    def flag_value(rid, fl):
        return resolve_flag(rid, fl, flag_votes, report)

    # ---- task_success (deterministic, no auto-consensus) ----
    def task_success(task_id: str, run_id: str, threshold: float) -> dict:
        task = tasks[task_id]
        if task.get("challenge_kind"):
            rating, ok = elem_rating(run_id, "challenge")
            if not ok:
                return {"challenge": True, "resolved": False}
            return {"challenge": True, "resolved": True, "challenge_outcome": rating}
        elements = task.get("required_answer_elements", [])
        total = len(elements)
        supported = 0
        by_el = {}
        resolved = True
        for e in elements:
            rating, ok = elem_rating(run_id, e["element_id"])
            if not ok:
                resolved = False
                by_el[e["element_id"]] = "unadjudicated"
                continue
            if rating == "supported_and_correctly_cited":
                # bibliographic existence != support: raters must have verified
                verified = all(
                    (v.get("ref_verified") or "").strip() == "yes"
                    for v in ratings_by_run[run_id]
                    if v["element_id"] == e["element_id"] and v["rating"] == rating)
                if not verified:
                    rating = "supported_but_miscited"
            by_el[e["element_id"]] = rating
            if rating == "supported_and_correctly_cited":
                supported += 1
        fab, ok1 = flag_value(run_id, "fabrication_flag")
        contra, ok2 = flag_value(run_id, "contradiction_flag")
        refusal, ok3 = flag_value(run_id, "refusal_flag")
        resolved = resolved and ok1 and ok2 and ok3
        if not resolved:
            return {"challenge": False, "resolved": False, "by_element": by_el}
        frac = supported / total if total else 0.0
        success = (frac >= threshold) and fab == "no" and contra == "no" and refusal == "no"
        return {"challenge": False, "resolved": True, "success": bool(success),
                "frac": frac, "total": total, "supported": supported,
                "fabrication": fab, "contradiction": contra,
                "refusal": refusal, "by_element": by_el}

    # ---- primary outcomes per family per arm (end-to-end estimand) ----
    primary_run = {}
    for (fam, arm), reps in primary_flags.items():
        rep = reps[0]
        row = next(r for r in schedule
                   if r["family_id"] == fam and r["arm"] == arm and r["repetition"] == rep)
        primary_run[(fam, arm)] = row

    families = sorted({(row["family_id"]) for row in schedule})
    answerable = [f for f in families
                  if not tasks[next(r for r in schedule if r["family_id"] == f)["task_id"]].get("challenge_kind")]
    challenges = [f for f in families if f not in answerable]

    fam_results = {}
    for fam in answerable:
        fam_results[fam] = {}
        for arm in ("A", "B"):
            row = primary_run[(fam, arm)]
            rid = f"{row['task_id']}__{row['arm']}__r{row['repetition']}"
            run = run_by_id[rid]
            st = run.get("status")
            if st == "done":
                res = task_success(row["task_id"], rid, THRESHOLD)
                if not res.get("resolved"):
                    fam_results[fam][arm] = {"delivery": "assessed",
                                             "resolution": "unadjudicated"}
                else:
                    fam_results[fam][arm] = {"delivery": "assessed",
                                             "resolution": "resolved",
                                             "success": res["success"],
                                             "frac": res["frac"],
                                             "by_element": res["by_element"],
                                             "fabrication": res["fabrication"],
                                             "contradiction": res["contradiction"],
                                             "refusal": res["refusal"]}
            elif st == "run_failed":
                fam_results[fam][arm] = {"delivery": "technical_failure",
                                         "resolution": "resolved", "success": False}
            elif st == "refused_insufficient_evidence":
                fam_results[fam][arm] = {"delivery": "pipeline_refusal",
                                         "resolution": "resolved", "success": False}

    if report["pending_adjudications"]:
        return blocked(report, ["unadjudicated rating disagreements remain"])

    # ---- primary 2x2 + inference ----
    table = []
    for fam in answerable:
        sa = bool(fam_results[fam]["A"].get("success"))
        sb = bool(fam_results[fam]["B"].get("success"))
        table.append({"family": fam, "arm_a_success": sa, "arm_b_success": sb,
                      "arm_a_delivery": fam_results[fam]["A"]["delivery"],
                      "arm_b_delivery": fam_results[fam]["B"]["delivery"]})
    n = len(table)
    if n == 0 and not challenges:
        return blocked(report, ["no answerable families and no challenge families scheduled"])
    inference = None
    if n > 0:
        both = sum(1 for t in table if t["arm_a_success"] and t["arm_b_success"])
        a_only = sum(1 for t in table if t["arm_a_success"] and not t["arm_b_success"])
        b_only = sum(1 for t in table if not t["arm_a_success"] and t["arm_b_success"])
        neither = n - both - a_only - b_only
        p_a = (both + a_only) / n
        p_b = (both + b_only) / n
        ci = score_paired_diff_ci(a_only, b_only, n)
        mcn = exact_mcnemar(a_only, b_only)
        try:
            boot = cluster_bootstrap_paired_diff(
                [(t["arm_a_success"], t["arm_b_success"]) for t in table])
        except ValueError:
            boot = None
        inference = {
            "contingency_2x2": {"both_succeed": both, "a_only": a_only,
                                "b_only": b_only, "neither": neither},
            "arm_a_rate": p_a, "arm_b_rate": p_b, "diff": p_a - p_b,
            "paired_diff_ci_method": ("score interval for the paired difference of proportions "
                                      "(Tango 1998, Stat Med 17(8):891-908; Newcombe 1998 Method 10, "
                                      "Stat Med 17(22):2635-50); uses the full 2x2 table"),
            "paired_diff_ci": [ci["lo"], ci["hi"]],
            "degenerate_zero_discordance": ci["degenerate_zero_discordance"],
            "mcnemar_exact_p": mcn,
            "mcnemar_status": "prespecified paired hypothesis test (alpha=0.05 two-sided); status not outcome-dependent",
            "bootstrap": boot,
        }

    # sensitivity across thresholds (resolved families only; skipped when n == 0)
    sens = {}
    if n > 0:
        for th in SENSITIVITIES:
            succ = {}
            for fam in answerable:
                succ[fam] = {}
                for arm in ("A", "B"):
                    row = primary_run[(fam, arm)]
                    rid = f"{row['task_id']}__{row['arm']}__r{row['repetition']}"
                    run = run_by_id[rid]
                    if run.get("status") == "done":
                        res = task_success(row["task_id"], rid, th)
                        succ[fam][arm] = bool(res.get("success"))
                    else:
                        succ[fam][arm] = False
            sens[str(th)] = {
                "arm_a_rate": sum(1 for f in answerable if succ[f]["A"]) / n,
                "arm_b_rate": sum(1 for f in answerable if succ[f]["B"]) / n,
            }

    # repetition summary (family-preserving; no substitution)
    repetition_summary = {}
    for fam in answerable:
        for arm in ("A", "B"):
            outcomes = []
            for row in schedule:
                if row["family_id"] == fam and row["arm"] == arm:
                    rid = f"{row['task_id']}__{row['arm']}__r{row['repetition']}"
                    run = run_by_id[rid]
                    if run.get("status") == "done":
                        res = task_success(row["task_id"], rid, THRESHOLD)
                        outcomes.append({"repetition": row["repetition"],
                                         "success": bool(res.get("success"))
                                         if res.get("resolved") else None,
                                         "primary": row["is_primary"]})
                    else:
                        outcomes.append({"repetition": row["repetition"],
                                         "success": False,
                                         "primary": row["is_primary"],
                                         "status": run.get("status")})
            vals = [o["success"] for o in outcomes if o.get("success") is not None]
            agree = None
            if len(vals) >= 2:
                agree = 1.0 if all(v == vals[0] for v in vals) else 0.0
            repetition_summary[f"{fam}:{arm}"] = {"outcomes": outcomes,
                                                  "n": len(vals),
                                                  "all_agree": agree}

    # challenge results (separate; scheduled runs accounted)
    challenge_results = {}
    for fam in challenges:
        for arm in ("A", "B"):
            rows = [r for r in schedule if r["family_id"] == fam and r["arm"] == arm]
            for row in rows:
                rid = f"{row['task_id']}__{row['arm']}__r{row['repetition']}"
                run = run_by_id[rid]
                if run.get("status") == "run_failed":
                    outcome = {"delivery": "technical_failure",
                               "abstention_correct": False,
                               "note": "technical failure is NOT appropriate abstention"}
                elif run.get("status") == "refused_insufficient_evidence":
                    res = task_success(row["task_id"], rid, THRESHOLD)
                    outcome = {"delivery": "pipeline_refusal_rated",
                               "challenge_outcome": res.get("challenge_outcome") if res.get("resolved") else "unadjudicated",
                               "note": "pipeline refusal requires HUMAN rating; absence of answer is not automatically correct"}
                else:
                    res = task_success(row["task_id"], rid, THRESHOLD)
                    outcome = {"delivery": "assessed",
                               "challenge_outcome": res.get("challenge_outcome") if res.get("resolved") else "unadjudicated"}
                challenge_results[f"{rid}"] = {"family": fam, "arm": arm,
                                               "repetition": row["repetition"],
                                               "primary": row["is_primary"],
                                               "challenge_kind": row.get("challenge_kind"),
                                               **outcome}

    # run accounting (all scheduled runs, both answerable + challenge)
    run_accounting = {"A": {"scheduled": 0, "done": 0, "run_failed": 0,
                            "refused_insufficient_evidence": 0},
                      "B": {"scheduled": 0, "done": 0, "run_failed": 0,
                            "refused_insufficient_evidence": 0}}
    for row in schedule:
        run_accounting[row["arm"]]["scheduled"] += 1
        rid = f"{row['task_id']}__{row['arm']}__r{row['repetition']}"
        st = run_by_id[rid]["status"]
        if st in ("done", "run_failed", "refused_insufficient_evidence"):
            run_accounting[row["arm"]][st] += 1

    out = {
        "estimand": "end-to-end delivery of a grounded answer in the prespecified primary run per arm per answerable task family",
        "n_families": n,
        "delivery_rule_note": ("terminal failure or refusal on an answerable task counts as "
                               "unsuccessful; status preserved; no repetition substitution"),
        "threshold": THRESHOLD,
        "paired_table": table,
        "inference": inference,
        "sensitivity_by_threshold": sens,
        "repetition_summary": repetition_summary,
        "challenge_results_separate": challenge_results,
        "run_accounting": run_accounting,
        "assessment_completeness": {"missing_assessments": len(missing_assessments),
                                    "adjudications_used": len(adjudication)},
    }
    print(json.dumps(out, indent=1, ensure_ascii=False))
    if args.out_dir:
        p = Path(args.out_dir)
        p.mkdir(parents=True, exist_ok=True)
        (p / "analysis_primary.json").write_text(
            json.dumps(out, indent=1, ensure_ascii=False))
        print("saved:", p / "analysis_primary.json")
    return OK


if __name__ == "__main__":
    sys.exit(main())
