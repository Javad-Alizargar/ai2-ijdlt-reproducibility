#!/usr/bin/env python3
"""
paired_proportions.py — documented inference for paired binary outcomes.

The primary estimand (protocols/benchmark_plan_v2.md, Round 2B revision):
for each scheduled answerable task family, whether each arm delivered a
successful grounded answer in its prespecified primary run under the fixed
retry policy. Each family contributes ONE paired binary observation
(arm A outcome, arm B outcome), summarized by the 2x2 table:

    B success      B not success
A success   n11              n12   (= b, "A only")
A not succ  n21 (= c)        n22

Methods (all exactly as documented here):
1. exact two-sided McNemar test on discordant pairs (b, c) — the
   prespecified paired hypothesis test (alpha fixed a priori; its a-priori
   power characteristics are reported in the sampling plan; test status is
   NOT reclassified based on observed discordant counts).
2. Score confidence interval for the paired difference of proportions
   (Tango 1998, Stat Med 17(8):891-908; Newcombe 1998, Stat Med 17(22):
   2635-50 Method 10), solving the score equation
   (delta - delta_hat)^2 = z^2 * (psi - delta^2)/n with the variance
   identity var(delta_hat) = (psi - delta^2)/n; see the function docstring
   for the explicit quadratic and boundary handling.
3. Family-cluster bootstrap for the paired difference: families are the
   resampling units; runs are nested within families and never resampled
   independently. Fixed seed; percentile interval.

This module contains NO adjudication and NO automated consensus: it consumes
already-determined per-family binary outcomes.
"""
from __future__ import annotations

import math
import random
from math import comb

Z95 = 1.959963984540054


def exact_mcnemar(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value on discordant pairs.
    Rejects when the smaller tail is <= alpha/2 under Bin(d, 0.5)."""
    d = b + c
    if d == 0:
        return 1.0
    lo = min(b, c)
    p = 0.0
    for i in range(lo + 1):
        p += comb(d, i)
    p *= 2.0 * (0.5 ** d)
    return min(1.0, p)


def wilson_proportion(p: float, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a single proportion. Requires n >= 1."""
    if n < 1:
        raise ValueError("wilson_proportion requires n >= 1")
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return center - half, center + half


def score_paired_diff_ci(b: int, c: int, n: int, z: float = Z95) -> dict:
    """Score confidence interval for the paired difference of proportions.

    Construction (Tango T. Equivalence test and confidence interval for the
    difference in proportions for the paired-sample design. Stat Med
    1998;17(8):891-908; the identical score interval appears as Newcombe RG.
    Improved confidence intervals for the difference between binomial
    proportions based on paired data. Stat Med 1998;17(22):2635-50, Method 10):

      delta_hat = (b - c)/n
      psi       = (b + c)/n        (discordant proportion)
      variance identity: var(delta_hat) = (psi - delta^2)/n

    Solve the score equation (delta - delta_hat)^2 = z^2 * (psi - delta^2)/n,
    i.e. the quadratic  A*delta^2 + B*delta + C = 0  with
      A = n + z^2,  B = -2*n*delta_hat,  C = n*delta_hat^2 - z^2*psi.

    b = families where arm A succeeds and arm B does not;
    c = families where arm B succeeds and arm A does not;
    n = total paired families.

    Boundaries (explicit):
    - n < 1 raises ValueError (caller must gate empty inputs).
    - Zero discordance (b = c = 0): degenerate interval (0, 0) returned with
      degenerate_zero_discordance=True; downstream reporting must surface the
      flag rather than implying zero uncertainty.
    - The discriminant is analytically non-negative for all valid b, c, n
      ((b-c)^2 <= n*(b+c)); a floor at 0 guards floating-point noise."""
    if n < 1:
        raise ValueError("n must be >= 1")
    if b < 0 or c < 0 or b + c > n:
        raise ValueError("invalid discordant counts")
    d_hat = (b - c) / n
    psi = (b + c) / n
    if b + c == 0:
        return {"delta": 0.0, "lo": 0.0, "hi": 0.0,
                "degenerate_zero_discordance": True, "psi": 0.0}
    A = n + z * z
    B = -2.0 * n * d_hat
    C = n * d_hat * d_hat - z * z * psi
    disc = max(0.0, B * B - 4.0 * A * C)
    lo = (-B - math.sqrt(disc)) / (2.0 * A)
    hi = (-B + math.sqrt(disc)) / (2.0 * A)
    return {"delta": d_hat, "lo": lo, "hi": hi,
            "degenerate_zero_discordance": False, "psi": psi}


def cluster_bootstrap_paired_diff(family_outcomes: list[tuple[bool, bool]],
                                  seed: int = 20261001, B: int = 4000) -> dict:
    """Family-cluster bootstrap percentile interval for the paired difference.

    family_outcomes: list of (arm_a_success, arm_b_success) per family.
    Families are resampled with replacement; runs are NEVER resampled."""
    n = len(family_outcomes)
    if n < 2:
        raise ValueError("bootstrap requires >= 2 families")
    rng = random.Random(seed)
    stats = []
    for _ in range(B):
        idx = [rng.randrange(n) for _ in range(n)]
        d = sum(1.0 for i in idx if family_outcomes[i][0]) / n \
            - sum(1.0 for i in idx if family_outcomes[i][1]) / n
        stats.append(d)
    stats.sort()
    lo = stats[int(0.025 * (B - 1))]
    hi = stats[int(0.975 * (B - 1))]
    mean = sum(stats) / B
    return {"bootstrap_lo": lo, "bootstrap_hi": hi, "bootstrap_mean": mean,
            "B": B, "seed": seed, "n_families": n,
            "method": "family-cluster percentile bootstrap (runs nested, never resampled)"}
