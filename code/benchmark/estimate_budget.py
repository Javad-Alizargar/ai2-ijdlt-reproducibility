#!/usr/bin/env python3
"""
estimate_budget.py — precision, power, cost, and rating-burden estimates for
the held-out evaluation at n = 24 / 40 / 60 independent task families.

All assumptions stated. Nothing here is chosen based on pilot results; this
script exists to feed the pre-registered sample-size decision
(protocols/task_sampling_plan.md).

Usage: python3 code/benchmark/estimate_budget.py
"""
from __future__ import annotations

import json
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PRICING = {"gpt-4.1-mini": (0.40, 1.60)}  # USD per 1M tokens, OpenAI page 2026-10-01

ASSUMPTIONS = {
    "answer_input_tokens": 8000,      # system prompt + user JSON with ~12 evidence abstracts
    "answer_output_tokens": 1500,     # max 1700 in production
    "supervisor_input_tokens": 6000,  # system + draft + evidence
    "supervisor_output_tokens": 1500,  # max 1800
    "baseline_input_tokens": 1200,
    "baseline_output_tokens": 1500,
    "repetitions": 3,
    "required_elements_per_task": 6,
    "raters": 2,
    "rater_minutes_per_element": 1.5,
    "challenge_tasks": 4,
}


def mc_nemar_power(n_pairs: int, alpha: float, discordant_rate: float, q: float):
    """Exact power of two-sided McNemar test.
    n_pairs families; discordant_rate = expected proportion of families that
    are discordant; q = probability a discordant family favors arm A.
    Under H0 the split is Bin(discordant, 0.5)."""
    power = 0.0
    for d in range(n_pairs + 1):
        prob_d = comb(n_pairs, d) * (discordant_rate ** d) * ((1 - discordant_rate) ** (n_pairs - d))
        if d == 0:
            continue
        # critical values of b under Bin(d, 0.5) two-sided
        rej = 0.0
        for b in range(d + 1):
            pval = 2 * sum(comb(d, i) for i in range(0, min(b, d - b) + 1)) * 0.5 ** d
            pval = min(1.0, pval)
            if pval <= alpha:
                rej += comb(d, b) * (q ** b) * ((1 - q) ** (d - b))
        power += prob_d * rej
    return power


def ci_halfwidth(p: float, n: int, z: float = 1.96) -> float:
    if p <= 0:
        return 0.0
    return z * ((p * (1 - p) / n) ** 0.5)


def cost_per_family():
    pin, pout = PRICING["gpt-4.1-mini"]
    a = ASSUMPTIONS
    arm_a_one_run = ((a["answer_input_tokens"] * pin + a["answer_output_tokens"] * pout) +
                     (a["supervisor_input_tokens"] * pin + a["supervisor_output_tokens"] * pout)) / 1e6
    arm_b_one_run = (a["baseline_input_tokens"] * pin + a["baseline_output_tokens"] * pout) / 1e6
    return 3 * arm_a_one_run, 3 * arm_b_one_run


def main() -> None:
    a = ASSUMPTIONS
    print("Assumptions:", json.dumps(a, indent=1))
    arm_a, arm_b = cost_per_family()
    print(f"\nper-family cost (3 reps): arm A ${arm_a:.4f}, arm B ${arm_b:.4f}")
    print(f"model calls per family: arm A {3*2} (answer+supervisor), arm B {3}")
    print(f"{'n':>4} {'CI hw p=0.5':>12} {'CI hw p=0.8':>12} "
          f"{'pow(d=.3,q=.75)':>15} {'pow(d=.4,q=.85)':>15} {'cost USD':>10} "
          f"{'calls':>7} {'rating hours':>13}")
    for n in (24, 40, 60):
        cost = n * (arm_a + arm_b)
        calls = n * (3 * 2 + 3)
        ratings = (n + a["challenge_tasks"]) * a["required_elements_per_task"] * a["raters"]
        hours = ratings * a["rater_minutes_per_element"] / 60
        pw_a = mc_nemar_power(n, 0.05, 0.3, 0.75)
        pw_b = mc_nemar_power(n, 0.05, 0.4, 0.85)
        print(f"{n:>4} {ci_halfwidth(0.5, n):>12.3f} {ci_halfwidth(0.8, n):>12.3f} "
              f"{pw_a:>15.2f} {pw_b:>15.2f} {cost:>10.2f} {calls:>7d} {hours:>13.1f}")
    print("\nNotes:")
    print("- power = exact two-sided McNemar (alpha=0.05) with assumed")
    print("  discordant-family rate d and split q favoring arm A.")
    print("- Primary reporting is CI-based; McNemar is confirmatory only if")
    print("  discordant counts suffice; otherwise feasibility benchmark.")
    out = {"assumptions": a, "per_family_cost": {"arm_a": arm_a, "arm_b": arm_b},
           "rows": []}
    for n in (24, 40, 60):
        out["rows"].append({
            "n_families": n,
            "ci_halfwidth_p50": ci_halfwidth(0.5, n),
            "ci_halfwidth_p80": ci_halfwidth(0.8, n),
            "power_d030_q075": mc_nemar_power(n, 0.05, 0.3, 0.75),
            "power_d040_q085": mc_nemar_power(n, 0.05, 0.4, 0.85),
            "cost_usd": n * (arm_a + arm_b),
            "model_calls": n * 9,
            "rating_hours": (n + 4) * 6 * 2 * 1.5 / 60,
        })
    dest = ROOT / "results" / "budget_estimate.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1))
    print("saved:", dest)


if __name__ == "__main__":
    main()
