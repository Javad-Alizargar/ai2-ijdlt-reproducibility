#!/usr/bin/env python3
"""
Synthetic fixture tests for the benchmark harness gates.

These are SOFTWARE TESTS using labeled synthetic fixtures; they are NOT
research findings. Each test builds tiny synthetic run logs/ratings and
asserts the gates in analyze_ratings.py behave as specified.

Run: python3 tests/test_harness.py
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYZE = ROOT / "code" / "benchmark" / "analyze_ratings.py"
FIXTURES = ROOT / "tests" / "fixtures"
CFG = "config_hash_test_value"

ELEMENT_IDS = ["E1", "E2", "E3", "E4", "E5"]


def make_task(task_id, family_id, challenge=False, run_slot=1):
    t = {
        "task_id": task_id, "family_id": family_id, "intended_inquiry_skill": "evidence_finding",
        "language": "en", "question": f"synthetic question for {task_id}",
        "role": "professor", "mode": "Research question appraisal", "specialty": "test",
        "response_language": "en",
        "public_source_provenance": {
            "title": "Synthetic source (fixture)", "publisher": "tests",
            "stable_url_or_doi": "https://example.org/fixture",
            "version_or_access_date": "2026-10-01"},
        "evidence_cutoff": "2026-09", "paper_count": 12, "year_range": "last5",
        "prefer_recent": True, "use_journal_rank": False, "set": "dev",
        "run_slot": run_slot, "fixture": True,
    }
    if challenge:
        t["challenge_kind"] = "false_premise"
        t["challenge_scoring"] = "abstention_correct"
    else:
        t["required_answer_elements"] = [
            {"element_id": eid, "description": f"synthetic element {eid}",
             "supporting_sections": "fixture section 1.1"}
            for eid in ELEMENT_IDS]
        t["acceptable_alternative_sources"] = ["https://example.org/alt"]
        t["scoring_rubric"] = {"E1": "supported_and_correctly_cited"}
    return t


def make_run(run_id, task_id, arm, family_id, status="done", cfg=CFG,
             run_slot=1, fixture=False):
    return {"run_id": run_id, "task_id": task_id, "arm": arm,
            "family_id": family_id, "status": status, "config_hash": cfg,
            "run_slot": run_slot, "answer_text": "synthetic answer",
            **({"fixture": True} if fixture else {})}


def make_rating(rating_id, rater_id, run_id, task_id, family_id, element_id,
                rating="supported_and_correctly_cited", ref_verified="yes",
                notes="", fabrication="no", contradiction="no", refusal="no"):
    return {"rating_id": rating_id, "rater_id": rater_id, "run_id": run_id,
            "task_id": task_id, "family_id": family_id, "element_id": element_id,
            "rating": rating, "notes": notes, "ref_verified": ref_verified,
            "fabrication_flag": fabrication, "contradiction_flag": contradiction,
            "refusal_flag": refusal}


def write_csv(path, rows):
    fields = ["rating_id", "rater_id", "run_id", "task_id", "family_id",
              "element_id", "rating", "notes", "ref_verified",
              "fabrication_flag", "contradiction_flag", "refusal_flag"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def run_analyze(log_path, ratings_path, tasks_dir):
    return subprocess.run(
        [sys.executable, str(ANALYZE), "--run-log", str(log_path),
         "--ratings", str(ratings_path), "--tasks-dir", str(tasks_dir)],
        capture_output=True, text=True)


class HarnessGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.tasks = self.dir / "tasks"
        self.tasks.mkdir()
        for name, t in {
            "fam1": make_task("fam1", "fam1"),
            "fam2": make_task("fam2", "fam2"),
            "chal1": make_task("chal1", "chal1", challenge=True),
        }.items():
            (self.tasks / f"{name}.json").write_text(json.dumps(t))

    def tearDown(self):
        self.tmp.cleanup()

    def test_blank_ratings_prevent_scored_results(self):
        log = [make_run("fam1__A__r1", "fam1", "A", "fam1"),
               make_run("fam1__B__r1", "fam1", "B", "fam1")]
        ratings = [make_rating("R1", "r1", "fam1__A__r1", "fam1", "fam1", "E1"),
                   make_rating("R2", "r1", "fam1__A__r1", "fam1", "fam1", "E2", rating=""),
                   make_rating("R3", "r1", "fam1__A__r1", "fam1", "fam1", "E3"),
                   make_rating("R4", "r1", "fam1__A__r1", "fam1", "fam1", "E4"),
                   make_rating("R5", "r1", "fam1__A__r1", "fam1", "fam1", "E5")]
        logp = self.dir / "log.jsonl"
        logp.write_text("\n".join(json.dumps(r) for r in log))
        ratp = self.dir / "ratings.csv"
        write_csv(ratp, ratings)
        proc = run_analyze(logp, ratp, self.tasks)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("blank rating", proc.stdout)

    def test_fixture_runs_cannot_enter_empirical_tables(self):
        log = [make_run("fam1__A__r1", "fam1", "A", "fam1", fixture=True),
               make_run("fam1__B__r1", "fam1", "B", "fam1")]
        logp = self.dir / "log.jsonl"
        logp.write_text("\n".join(json.dumps(r) for r in log))
        ratp = self.dir / "ratings.csv"
        write_csv(ratp, [])
        proc = run_analyze(logp, ratp, self.tasks)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("fixture", proc.stdout)

    def test_repetitions_do_not_inflate_task_count(self):
        log = []
        for arm in ("A", "B"):
            for rep in (1, 2, 3):
                log.append(make_run(f"fam1__{arm}__r{rep}", "fam1", arm, "fam1",
                                    run_slot=rep))
                log.append(make_run(f"fam2__{arm}__r{rep}", "fam2", arm, "fam2",
                                    run_slot=rep))
        ratings = []
        i = 1
        for rid in [r["run_id"] for r in log]:
            for eid in ELEMENT_IDS:
                ratings.append(make_rating(f"R{i}", "r1", rid,
                                           "fam1" if rid.startswith("fam1") else "fam2",
                                           "fam1" if rid.startswith("fam1") else "fam2",
                                           eid))
                i += 1
        logp = self.dir / "log.jsonl"
        logp.write_text("\n".join(json.dumps(r) for r in log))
        ratp = self.dir / "ratings.csv"
        write_csv(ratp, ratings)
        proc = run_analyze(logp, ratp, self.tasks)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["n_families"], 2)  # families, not runs
        self.assertIn("stability", out)

    def test_missing_arm_detected(self):
        log = [make_run("fam1__A__r1", "fam1", "A", "fam1")]
        logp = self.dir / "log.jsonl"
        logp.write_text("\n".join(json.dumps(r) for r in log))
        ratp = self.dir / "ratings.csv"
        write_csv(ratp, [])
        proc = run_analyze(logp, ratp, self.tasks)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing an arm", proc.stdout)

    def test_duplicate_arm_run_slot_detected(self):
        log = [make_run("fam1__A__r1", "fam1", "A", "fam1", run_slot=1),
               make_run("fam1__A__r2", "fam1", "A", "fam1", run_slot=1),
               make_run("fam1__B__r1", "fam1", "B", "fam1", run_slot=1)]
        logp = self.dir / "log.jsonl"
        logp.write_text("\n".join(json.dumps(r) for r in log))
        ratp = self.dir / "ratings.csv"
        write_csv(ratp, [])
        proc = run_analyze(logp, ratp, self.tasks)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("duplicate run_slot", proc.stdout)

    def test_config_mismatch_across_arms_detected(self):
        log = [make_run("fam1__A__r1", "fam1", "A", "fam1", cfg="cfg_A"),
               make_run("fam1__B__r1", "fam1", "B", "fam1", cfg="cfg_B")]
        logp = self.dir / "log.jsonl"
        logp.write_text("\n".join(json.dumps(r) for r in log))
        ratp = self.dir / "ratings.csv"
        write_csv(ratp, [])
        proc = run_analyze(logp, ratp, self.tasks)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("config_hash differs", proc.stdout)

    def test_failed_request_not_silently_removed(self):
        log = [make_run("fam1__A__r1", "fam1", "A", "fam1"),
               make_run("fam1__B__r1", "fam1", "B", "fam1"),
               make_run("fam2__A__r1", "fam2", "A", "fam2", status="run_failed"),
               make_run("fam2__B__r1", "fam2", "B", "fam2")]
        ratings = []
        i = 1
        for rid, fam in [("fam1__A__r1", "fam1"), ("fam1__B__r1", "fam1"),
                         ("fam2__B__r1", "fam2")]:
            for eid in ELEMENT_IDS:
                ratings.append(make_rating(f"R{i}", "r1", rid, fam, fam, eid))
                i += 1
        logp = self.dir / "log.jsonl"
        logp.write_text("\n".join(json.dumps(r) for r in log))
        ratp = self.dir / "ratings.csv"
        write_csv(ratp, ratings)
        proc = run_analyze(logp, ratp, self.tasks)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["run_accounting"]["A"]["run_failed"], 1)
        # the failed arm must be excluded-with-reason, not silently scored
        self.assertTrue(any(e["family"] == "fam2" for e in out["excluded_families"]))
        self.assertEqual(out["n_families"], 1)

    def test_valid_doi_attached_to_wrong_claim_does_not_pass(self):
        log = [make_run("fam1__A__r1", "fam1", "A", "fam1"),
               make_run("fam1__B__r1", "fam1", "B", "fam1")]
        ratings = []
        i = 1
        for rid, fam in [("fam1__A__r1", "fam1"), ("fam1__B__r1", "fam1")]:
            for eid in ELEMENT_IDS:
                # supported rating but rater did NOT verify the citation supports it
                ratings.append(make_rating(f"R{i}", "r1", rid, fam, fam, eid,
                                           ref_verified=""))
                i += 1
        logp = self.dir / "log.jsonl"
        logp.write_text("\n".join(json.dumps(r) for r in log))
        ratp = self.dir / "ratings.csv"
        write_csv(ratp, ratings)
        proc = run_analyze(logp, ratp, self.tasks)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["arm_a_rate"], 0.0)
        self.assertEqual(out["arm_b_rate"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
