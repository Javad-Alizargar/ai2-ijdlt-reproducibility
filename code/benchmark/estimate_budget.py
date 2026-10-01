#!/usr/bin/env python3
"""
estimate_budget.py — corrected schedule, cost, and human-workload accounting
for the held-out evaluation (Round 2B).

Schedules (answerable families nA, challenge cases nC, repetitions r):
  nominal model requests = (nA + nC) * r * (2 for arm A + 1 for arm B)
  answer outputs        = (nA + nC) * r * 2 arms
Early pipeline refusal on a task may REDUCE actual requests (arm A makes no
model calls when no evidence passes); retries may INCREASE them. Nominal,
conservative maximum, and actual are therefore reported separately.

Human workload is parameterized by element count per task (summed over actual
rubric sizes), arms, repetitions, raters, and minutes per element, and is
reported as TOTAL person-hours and hours PER RATER. Reference checking,
calibration, and adjudication are itemized SEPARATELY and are not included in
the element-rating figure.

Three comparable plans (sample size is NOT chosen from results):
  A: 24 answerable + 4 challenges, ONE primary run per arm.
  B: Plan A plus two extra repetitions on the first six answerable families in
     frozen alphabetical family_id order (fixed rule decided BEFORE any
     held-out output is generated; never selected from failures or effects).
  C: the original three-repetition schedule for all tasks.

Usage: python3 code/benchmark/estimate_budget.py [--repetitions-c 3]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PRICING = {"gpt-4.1-mini": (0.40, 1.60)}  # USD/1M tokens, OpenAI page 2026-10-01

ASSUMPTIONS = {
    "answer_input_tokens": 8000,
    "answer_output_tokens": 1500,
    "supervisor_input_tokens": 6000,
    "supervisor_output_tokens": 1500,
    "baseline_input_tokens": 1200,
    "baseline_output_tokens": 1500,
    "answerable_families": 24,
    "challenge_cases": 4,
    "elements_per_answerable_task": 6,      # planning value; final sum uses rubric sizes
    "raters": 2,
    "rater_minutes_per_element": 1.5,       # ASSUMPTION (no pilot human timing yet)
    "stage_retry_cap": 2,                   # protocol: <=2 retries per stage
}


def cost_per_request(kind: str) -> float:
    pin, pout = PRICING["gpt-4.1-mini"]
    a = ASSUMPTIONS
    if kind == "answer":
        return (a["answer_input_tokens"] * pin + a["answer_output_tokens"] * pout) / 1e6
    if kind == "supervisor":
        return (a["supervisor_input_tokens"] * pin + a["supervisor_output_tokens"] * pout) / 1e6
    return (a["baseline_input_tokens"] * pin + a["baseline_output_tokens"] * pout) / 1e6


def plan(nA: int, nC: int, reps: int, extra_reps_families: int = 0,
         extra_reps: int = 0, label: str = "") -> dict:
    outputs = (nA + nC) * reps * 2 + extra_reps_families * extra_reps * 2
    requests = (nA + nC) * reps * 3 + extra_reps_families * extra_reps * 3
    # cost: arm A requests = answer + supervisor; arm B = baseline answer
    c_answer = cost_per_request("answer")
    c_sup = cost_per_request("supervisor")
    c_base = cost_per_request("baseline")
    main_cost = ((nA + nC) * reps * (c_answer + c_sup + c_base) +
                 extra_reps_families * extra_reps * (c_answer + c_sup + c_base))
    max_requests = requests * (1 + ASSUMPTIONS["stage_retry_cap"])
    max_cost = main_cost * (1 + ASSUMPTIONS["stage_retry_cap"])
    rated_outputs = outputs
    element_ratings = (nA * reps * 2 * ASSUMPTIONS["elements_per_answerable_task"] +
                       nC * reps * 2 * 1 +
                       extra_reps_families * extra_reps * 2 *
                       ASSUMPTIONS["elements_per_answerable_task"])
    total_hours = (element_ratings * ASSUMPTIONS["raters"] *
                   ASSUMPTIONS["rater_minutes_per_element"] / 60)
    hours_per_rater = total_hours / ASSUMPTIONS["raters"]
    # instruction-nominal figure: 6 elements per OUTPUT (incl. challenge outputs)
    nominal_6 = rated_outputs * ASSUMPTIONS["elements_per_answerable_task"]
    nominal_hours = nominal_6 * ASSUMPTIONS["raters"] * \
        ASSUMPTIONS["rater_minutes_per_element"] / 60
    return {
        "label": label,
        "answerable_families": nA,
        "challenge_cases": nC,
        "repetitions_main": reps,
        "extra_repetition_families": extra_reps_families,
        "answer_outputs": outputs,
        "nominal_model_requests": requests,
        "conservative_max_requests": max_requests,
        "nominal_cost_usd": round(main_cost, 2),
        "conservative_max_cost_usd": round(max_cost, 2),
        "rated_outputs": rated_outputs,
        "element_ratings_rubric_size": element_ratings,
        "total_assessment_person_hours_rubric_size": round(total_hours, 1),
        "hours_per_rater_rubric_size": round(hours_per_rater, 1),
        "total_assessment_person_hours_nominal_6_per_output": round(nominal_hours, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repetitions-c", type=int, default=3)
    args = ap.parse_args()

    nA = ASSUMPTIONS["answerable_families"]
    nC = ASSUMPTIONS["challenge_cases"]
    plans = [
        plan(nA, nC, 1, 0, 0, "A: one primary run per arm"),
        plan(nA, nC, 1, 6, 2, "B: primary + 2 extra reps on first 6 families (fixed rule)"),
        plan(nA, nC, args.repetitions_c, 0, 0, f"C: {args.repetitions_c} repetitions all tasks"),
    ]
    print("Pricing/token assumptions:", json.dumps({**PRICING, **ASSUMPTIONS}, indent=1))
    print("\nPlan | outputs | nominal requests | conservative max | cost | "
          "person-hours (6/output) | person-hours (rubric sizes) | hours/rater")
    for p in plans:
        print(f"{p['label'][:46]:46s} {p['answer_outputs']:>7d} {p['nominal_model_requests']:>16d} "
              f"{p['conservative_max_requests']:>16d} ${p['nominal_cost_usd']:>6.2f} "
              f"{p['total_assessment_person_hours_nominal_6_per_output']:>20.1f} "
              f"{p['total_assessment_person_hours_rubric_size']:>24.1f} "
              f"{p['hours_per_rater_rubric_size']:>11.1f}")
    print("\nNotes:")
    print("- nominal requests = (answerable + challenge) x reps x (2 arm A + 1 arm B).")
    print("- conservative max = nominal x (1 + stage retry cap); early refusal can")
    print("  REDUCE actual requests (reported separately at run time); retries increase them.")
    print("- person-hours (6/output) = instruction-nominal: outputs x 6 elements x 2")
    print("  raters x 1.5 min (e.g., Plan C: 28x2x3x6x2x1.5/60 = 50.4 person-hours).")
    print("- person-hours (rubric sizes) = exact sum over actual rubric sizes")
    print("  (challenge outputs = 1 element) - the figure used for planning burden.")
    print("- 1.5 min/element is an ASSUMPTION (no pilot human timing available).")
    print("- reference-checking, calibration, and adjudication are NOT in the")
    print("  element-rating hours and are itemized separately below.")
    print("- Plan B subset = first 6 answerable families in frozen alphabetical")
    print("  family_id order; fixed BEFORE any held-out output; never chosen from results.")
    print("- Inference supported: A = primary estimand only; B = primary + bounded")
    print("  stability subset; C = primary + full repetition stability.")
    print("- RECOMMENDATION: Plan B (most defensible feasible: primary estimand plus")
    print("  bounded stability evidence at about half C's cost and burden).")
    print("- Precision limits (from task_sampling_plan.md): n=24 => CI half-width")
    print("  ~0.16-0.20 at p=0.5/0.8; exact McNemar power is low for moderate")
    print("  effects; primary reporting is CI-based (feasibility benchmark framing).")
    out = {"assumptions": ASSUMPTIONS, "plans": plans,
           "separate_workload_items": {
               "reference_checking_per_element_minutes_assumption": 3,
               "calibration_set_hours_per_rater_assumption": 3.5,
               "adjudication_meeting_hours_total_assumption": 2.0,
               "note": "these are assumptions pending real rater timing"},
           "recommendation": "Plan B"}
    dest = ROOT / "results" / "budget_estimate.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1))
    print("\nsaved:", dest)


if __name__ == "__main__":
    main()
