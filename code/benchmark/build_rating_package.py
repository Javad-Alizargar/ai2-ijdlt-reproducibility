#!/usr/bin/env python3
"""
build_rating_package.py — assemble blinded human-review materials from run
outputs. The answer-to-arm mapping is written ONLY to admin/restricted/ and is
never included in the rating packet.

Usage:
  python3 code/benchmark/build_rating_package.py \
    --run-log results/benchmark/run_log.jsonl --tasks-dir tasks/dev \
    --out-dir evaluation/calibration_packet
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAPPING_DIR = ROOT / "admin" / "restricted"
RATING_COLS = ["rating_id", "rater_id", "run_id", "task_id", "family_id",
               "element_id", "rating", "notes", "ref_verified", "fabrication_flag",
               "contradiction_flag", "refusal_flag"]


def load_runs(run_log: Path) -> list[dict]:
    runs = []
    with open(run_log) as f:
        for line in f:
            if line.strip():
                runs.append(json.loads(line))
    return runs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-log", required=True)
    ap.add_argument("--tasks-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    runs = load_runs(Path(args.run_log))
    tasks = {p.stem: json.loads(p.read_text())
             for p in Path(args.tasks_dir).glob("*.json") if not p.name.startswith("_")}

    # stable blinding ids: random permutation seeded by the package build time
    # stored ONLY in the restricted mapping.
    ids = sorted({r["run_id"] for r in runs})
    seed = str(random.randrange(10 ** 12))
    random.seed(seed)
    shuffled = ids[:]
    random.shuffle(shuffled)
    blind = {rid: f"B{i + 1:03d}" for i, rid in enumerate(shuffled)}
    MAPPING_DIR.mkdir(parents=True, exist_ok=True)
    with open(MAPPING_DIR / "arm_mapping_restricted.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["blind_id", "run_id", "arm", "task_id", "seed"])
        for rid, bid in blind.items():
            rec = next(r for r in runs if r["run_id"] == rid)
            w.writerow([bid, rid, rec.get("arm"), rec.get("task_id"), seed])
    (MAPPING_DIR / "arm_mapping_restricted.csv").chmod(0o600)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    packet_dir = out / "packet"
    packet_dir.mkdir(exist_ok=True)

    rows = []
    n = 0
    for run in runs:
        task = tasks.get(run.get("task_id"))
        if task is None:
            continue
        bid = blind[run["run_id"]]
        task_packet = {
            "blind_id": bid,
            "task_id": task["task_id"],
            "family_id": task.get("family_id"),
            "question": task["question"],
            "role": task.get("role"),
            "mode": task.get("mode"),
            "specialty": task.get("specialty"),
            "response_language": task.get("response_language"),
            "intended_inquiry_skill": task.get("intended_inquiry_skill"),
            "challenge_kind": task.get("challenge_kind"),
            "public_source_provenance": task.get("public_source_provenance"),
            "evidence_cutoff": task.get("evidence_cutoff"),
            "answer_text": run.get("answer_text", ""),
            "run_status": run.get("status"),
        }
        with open(packet_dir / f"{bid}.json", "w") as f:
            json.dump(task_packet, f, ensure_ascii=False, indent=1)
        if task.get("challenge_kind"):
            row = {"rating_id": f"R{n + 1:05d}", "rater_id": "", "run_id": run["run_id"],
                   "task_id": task["task_id"], "family_id": task.get("family_id"),
                   "element_id": "challenge", "rating": "", "notes": "",
                   "ref_verified": "", "fabrication_flag": "", "contradiction_flag": "",
                   "refusal_flag": ""}
            rows.append(row)
            n += 1
        else:
            for e in task.get("required_answer_elements", []):
                rows.append({"rating_id": f"R{n + 1:05d}", "rater_id": "", "run_id": run["run_id"],
                             "task_id": task["task_id"], "family_id": task.get("family_id"),
                             "element_id": e["element_id"], "rating": "", "notes": "",
                             "ref_verified": "", "fabrication_flag": "", "contradiction_flag": "",
                             "refusal_flag": ""})
                n += 1

    tpl = out / "blinded_rating_template.csv"
    with open(tpl, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RATING_COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"packet written: {len(list(packet_dir.glob('*.json')))} answer files; "
          f"template rows: {n}")
    print(f"arm mapping (RESTRICTED): {MAPPING_DIR / 'arm_mapping_restricted.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
