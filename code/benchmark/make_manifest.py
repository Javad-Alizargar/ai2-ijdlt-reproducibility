#!/usr/bin/env python3
"""
make_manifest.py — generate the expected-run manifest that freezes the
benchmark schedule. The manifest is the canonical expected population for
completeness validation; the analysis NEVER infers expectations from whatever
runs happen to exist.

Usage:
  python3 code/benchmark/make_manifest.py \
    --tasks-dir tasks/heldout --arms A,B --repetitions 3 \
    --set heldout --primary-repetition 1 \
    [--shared-config-hash <sha>] [--arm-config-hash-A <sha>] [--arm-config-hash-B <sha>] \
    [--rubric-hash <sha>] [--expected-raters R1,R2] \
    --out results/benchmark/expected_runs_manifest.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks-dir", required=True)
    ap.add_argument("--arms", default="A,B")
    ap.add_argument("--repetitions", type=int, required=True)
    ap.add_argument("--set", required=True)
    ap.add_argument("--primary-repetition", type=int, default=1)
    ap.add_argument("--shared-config-hash", default=None)
    ap.add_argument("--arm-config-hash-A", default=None)
    ap.add_argument("--arm-config-hash-B", default=None)
    ap.add_argument("--rubric-hash", default=None)
    ap.add_argument("--expected-raters", default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    tasks_dir = Path(args.tasks_dir)
    files = sorted(p for p in tasks_dir.glob("*.json") if not p.name.startswith("_"))
    if not files:
        print("no task files")
        return 1
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    schedule = []
    for p in files:
        t = json.loads(p.read_text())
        if t.get("fixture"):
            print("refusing fixture task:", p.name)
            return 1
        fam = t["family_id"]
        for arm in arms:
            for rep in range(1, args.repetitions + 1):
                schedule.append({
                    "task_id": t["task_id"],
                    "family_id": fam,
                    "variant_language": t.get("language"),
                    "arm": arm,
                    "repetition": rep,
                    "is_primary": (rep == args.primary_repetition),
                    "rubric_hash": args.rubric_hash,
                    "challenge_kind": t.get("challenge_kind"),
                })
    config = {
        "shared_config_hash": args.shared_config_hash,
        "arm_config_hash": {"A": args.arm_config_hash_A, "B": args.arm_config_hash_B},
        "arm_config_required": bool(args.shared_config_hash and
                                    args.arm_config_hash_A and args.arm_config_hash_B),
        "rubric_hash": args.rubric_hash,
        "expected_raters": [r.strip() for r in args.expected_raters.split(",") if r.strip()],
        "repetitions": args.repetitions,
    }
    manifest = {
        "manifest_id": f"manifest_{args.set}_{int(time.time())}",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "set": args.set,
        "primary_repetition": args.primary_repetition,
        "arms": arms,
        "config": config,
        "schedule": schedule,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=1))
    print(f"manifest written: {out} ({len(schedule)} scheduled runs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
