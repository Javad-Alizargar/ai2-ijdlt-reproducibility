#!/usr/bin/env python3
"""
Adversarial regression tests for the benchmark analysis gates (Round 2B).

These tests challenge SCIENTIFIC failure modes (denominator handling,
substitution, incomplete execution/evaluation, adjudication blocking, hash
enforcement, invalid data, determinism, paired-CI behavior, challenge
scoring), not merely happy-path function behavior. All inputs are labeled
synthetic fixtures — these are software tests, NOT research findings.

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
sys.path.insert(0, str(ROOT / "code" / "benchmark"))
from paired_proportions import score_paired_diff_ci  # noqa: E402

SHARED = "shared-cfg-test"
ARM_A = "arm-a-cfg-test"
ARM_B = "arm-b-cfg-test"
RUBRIC = "rubric-hash-test"
ELEMENT_IDS = ["E1", "E2", "E3", "E4", "E5"]


def make_task(task_id, family_id, challenge=False, rubric_hash=RUBRIC):
    t = {
        "task_id": task_id, "family_id": family_id,
        "intended_inquiry_skill": "evidence_finding",
        "language": "en", "question": f"synthetic question for {task_id}",
        "role": "professor", "mode": "Research question appraisal",
        "specialty": "test", "response_language": "en",
        "public_source_provenance": {
            "title": "Synthetic source (fixture)", "publisher": "tests",
            "stable_url_or_doi": "https://example.org/fixture",
            "version_or_access_date": "2026-10-01"},
        "evidence_cutoff": "2026-09", "paper_count": 12, "year_range": "last5",
        "prefer_recent": True, "use_journal_rank": False, "set": "heldout",
        "rubric_hash": rubric_hash,
    }
    if challenge:
        t["challenge_kind"] = "false_premise"
        t["challenge_scoring"] = "abstention_correct"
    else:
        t["required_answer_elements"] = [
            {"element_id": eid, "description": f"synthetic element {eid}",
             "supporting_sections": "fixture §1"}
            for eid in ELEMENT_IDS]
        t["acceptable_alternative_sources"] = ["https://example.org/alt"]
    return t


def make_manifest(schedule_rows, expected_raters=("R1", "R2"), rubric_hash=RUBRIC,
                  shared=SHARED, arm_hashes=(ARM_A, ARM_B), reps=None):
    arms = sorted({r["arm"] for r in schedule_rows})
    if reps is None:
        reps = max(r["repetition"] for r in schedule_rows)
    return {
        "manifest_id": "test-manifest", "created_utc": "2026-10-01T00:00:00Z",
        "set": "heldout", "arms": arms,
        "config": {
            "shared_config_hash": shared,
            "arm_config_hash": {"A": arm_hashes[0], "B": arm_hashes[1]},
            "arm_config_required": True,
            "rubric_hash": rubric_hash,
            "expected_raters": list(expected_raters),
            "repetitions": reps,
        },
        "schedule": schedule_rows,
    }


def sched(task_id, family_id, arm, rep, primary, challenge=False, lang="en"):
    return {"task_id": task_id, "family_id": family_id, "variant_language": lang,
            "arm": arm, "repetition": rep, "is_primary": primary,
            "rubric_hash": RUBRIC, "challenge_kind": "false_premise" if challenge else None}


def make_run(run_id, task_id, arm, family_id, status="done",
             shared=SHARED, arm_hash=None, set_="heldout", fixture=False):
    return {"run_id": run_id, "task_id": task_id, "arm": arm,
            "family_id": family_id, "status": status,
            "shared_config_hash": shared,
            "arm_config_hash": arm_hash or (ARM_A if arm == "A" else ARM_B),
            "set": set_, "answer_text": "synthetic answer",
            **({"fixture": True} if fixture else {})}


def make_rating(rating_id, rater_id, run_id, task_id, family_id, element_id,
                rating="supported_and_correctly_cited", ref_verified="yes",
                fabrication="no", contradiction="no", refusal="no"):
    return {"rating_id": rating_id, "rater_id": rater_id, "run_id": run_id,
            "task_id": task_id, "family_id": family_id, "element_id": element_id,
            "rating": rating, "notes": "", "ref_verified": ref_verified,
            "fabrication_flag": fabrication, "contradiction_flag": contradiction,
            "refusal_flag": refusal}


def write_csv(path, rows, fields=None):
    fields = fields or ["rating_id", "rater_id", "run_id", "task_id", "family_id",
                        "element_id", "rating", "notes", "ref_verified",
                        "fabrication_flag", "contradiction_flag", "refusal_flag"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def rate_run(rid, task_id, family_id, raters=("R1", "R2"), elements=ELEMENT_IDS,
             rating="supported_and_correctly_cited", ref="yes"):
    rows = []
    i = 0
    for rater in raters:
        for eid in elements:
            rows.append(make_rating(f"{rid}-{rater}-{eid}", rater, rid, task_id,
                                    family_id, eid, rating=rating, ref_verified=ref))
            i += 1
    return rows


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.tasks = self.dir / "tasks"
        self.tasks.mkdir()
        for name, t in {"fam1": make_task("fam1", "fam1"),
                        "fam2": make_task("fam2", "fam2"),
                        "chal1": make_task("chal1", "chal1", challenge=True)}.items():
            (self.tasks / f"{name}.json").write_text(json.dumps(t))
        self.log = self.dir / "log.jsonl"
        self.ratings = self.dir / "ratings.csv"
        self.manifest = self.dir / "manifest.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_analyze(self, env=None):
        cmd = [sys.executable, str(ANALYZE), "--run-log", str(self.log),
               "--ratings", str(self.ratings), "--tasks-dir", str(self.tasks),
               "--manifest", str(self.manifest)]
        e = dict(os.environ)
        if env:
            e.update(env)
        return subprocess.run(cmd, capture_output=True, text=True, env=e)

    def write_log(self, runs):
        self.log.write_text("\n".join(json.dumps(r) for r in runs))

    def write_ratings(self, rows):
        write_csv(self.ratings, rows)

    def write_manifest(self, rows, **kw):
        self.manifest.write_text(json.dumps(make_manifest(rows, **kw)))

    # ---------- scientific failure modes ----------

    def test_arm_failure_keeps_family_in_denominator(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1", status="run_failed"),
                        make_run("fam1__B__r1", "fam1", "B", "fam1")])
        self.write_ratings(rate_run("fam1__B__r1", "fam1", "fam1"))
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["n_families"], 1)
        inf = out["inference"]
        self.assertEqual(inf["contingency_2x2"]["both_succeed"], 0)
        self.assertEqual(inf["contingency_2x2"]["b_only"], 1)
        self.assertEqual(inf["arm_a_rate"], 0.0)
        self.assertEqual(out["paired_table"][0]["arm_a_delivery"], "technical_failure")

    def test_no_substitution_of_later_rep_for_failed_primary(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "A", 2, False),
                sched("fam1", "fam1", "B", 1, True),
                sched("fam1", "fam1", "B", 2, False)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1", status="run_failed"),
                        make_run("fam1__A__r2", "fam1", "A", "fam1"),
                        make_run("fam1__B__r1", "fam1", "B", "fam1"),
                        make_run("fam1__B__r2", "fam1", "B", "fam1")])
        ratings = rate_run("fam1__A__r2", "fam1", "fam1") + \
            rate_run("fam1__B__r1", "fam1", "fam1") + rate_run("fam1__B__r2", "fam1", "fam1")
        self.write_ratings(ratings)
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        out = json.loads(proc.stdout)
        self.assertFalse(out["paired_table"][0]["arm_a_success"])
        rep = out["repetition_summary"]["fam1:A"]
        self.assertFalse([o for o in rep["outcomes"] if o["primary"]][0]["success"])
        self.assertTrue([o for o in rep["outcomes"] if not o["primary"]][0]["success"])

    def test_missing_scheduled_run_blocks_as_incomplete_execution(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1")])
        self.write_ratings(rate_run("fam1__A__r1", "fam1", "fam1"))
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 3, proc.stdout)
        out = json.loads(proc.stdout)
        self.assertTrue(out["blocked"])
        self.assertIn("incomplete execution", out["blocked_reasons"][0])

    def test_missing_whole_task_blocked(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True),
                sched("fam2", "fam2", "A", 1, True),
                sched("fam2", "fam2", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1"),
                        make_run("fam1__B__r1", "fam1", "B", "fam1")])
        self.write_ratings(rate_run("fam1__A__r1", "fam1", "fam1") +
                           rate_run("fam1__B__r1", "fam1", "fam1"))
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(len(json.loads(proc.stdout)["incomplete_execution_runs"]), 2)

    def test_one_missing_rating_element_blocks_scoring(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1"),
                        make_run("fam1__B__r1", "fam1", "B", "fam1")])
        rows_ok = rate_run("fam1__B__r1", "fam1", "fam1")
        rows_a = rate_run("fam1__A__r1", "fam1", "fam1", elements=["E1", "E2", "E3", "E4"])
        self.write_ratings(rows_ok + rows_a)
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 3)
        out = json.loads(proc.stdout)
        self.assertEqual(len(out["missing_assessments"]), 2)  # R1+E5, R2+E5

    def test_duplicate_rater_element_row_rejected(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1"),
                        make_run("fam1__B__r1", "fam1", "B", "fam1")])
        base = rate_run("fam1__A__r1", "fam1", "fam1") + rate_run("fam1__B__r1", "fam1", "fam1")
        base.append(make_rating("dup", "R1", "fam1__A__r1", "fam1", "fam1", "E1"))
        self.write_ratings(base)
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("duplicate rater/element", proc.stdout)

    def test_disagreement_without_adjudication_blocks(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1"),
                        make_run("fam1__B__r1", "fam1", "B", "fam1")])
        ratings = rate_run("fam1__B__r1", "fam1", "fam1")
        a_rows = rate_run("fam1__A__r1", "fam1", "fam1")
        for r in a_rows:
            if r["rater_id"] == "R2" and r["element_id"] == "E1":
                r["rating"] = "unsupported"
        self.write_ratings(ratings + a_rows)
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 3)
        out = json.loads(proc.stdout)
        self.assertTrue(any(p["element_id"] == "E1" for p in out["pending_adjudications"]))

    def test_changed_rubric_hash_detected(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1"),
                        make_run("fam1__B__r1", "fam1", "B", "fam1")])
        self.write_ratings(rate_run("fam1__A__r1", "fam1", "fam1") +
                           rate_run("fam1__B__r1", "fam1", "fam1"))
        # tamper task rubric hash on disk
        p = self.tasks / "fam1.json"
        t = json.loads(p.read_text())
        t["rubric_hash"] = "tampered"
        p.write_text(json.dumps(t))
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("rubric_hash", proc.stdout)

    def test_invalid_rating_rejected(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1"),
                        make_run("fam1__B__r1", "fam1", "B", "fam1")])
        ratings = rate_run("fam1__B__r1", "fam1", "fam1")
        a = rate_run("fam1__A__r1", "fam1", "fam1")
        a[0]["rating"] = "excellent_work"
        self.write_ratings(ratings + a)
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("invalid rating", proc.stdout)

    def test_malformed_flag_rejected(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1"),
                        make_run("fam1__B__r1", "fam1", "B", "fam1")])
        ratings = rate_run("fam1__B__r1", "fam1", "fam1")
        a = rate_run("fam1__A__r1", "fam1", "fam1")
        a[0]["fabrication_flag"] = "maybe"
        self.write_ratings(ratings + a)
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("malformed flag", proc.stdout)

    def test_determinism_across_pythonhashseed(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1"),
                        make_run("fam1__B__r1", "fam1", "B", "fam1")])
        ratings = rate_run("fam1__A__r1", "fam1", "fam1") + rate_run("fam1__B__r1", "fam1", "fam1")
        # make arm B fail so there is a real discordance
        for r in ratings:
            if r["run_id"] == "fam1__B__r1":
                r["rating"] = "unsupported"
        self.write_ratings(ratings)
        p1 = self.run_analyze(env={"PYTHONHASHSEED": "0"})
        p2 = self.run_analyze(env={"PYTHONHASHSEED": "424242"})
        self.assertEqual(p1.returncode, 0)
        self.assertEqual(p1.stdout, p2.stdout)

    def test_fixture_run_rejected_from_empirical_tables(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1", fixture=True),
                        make_run("fam1__B__r1", "fam1", "B", "fam1")])
        self.write_ratings(rate_run("fam1__A__r1", "fam1", "fam1") +
                           rate_run("fam1__B__r1", "fam1", "fam1"))
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("fixture", proc.stdout)

    def test_empty_run_log_gates(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([])
        self.write_ratings([])
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("empty run log", proc.stdout)

    def test_all_failed_produces_documented_result(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True),
                sched("fam2", "fam2", "A", 1, True),
                sched("fam2", "fam2", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1", status="run_failed"),
                        make_run("fam1__B__r1", "fam1", "B", "fam1", status="run_failed"),
                        make_run("fam2__A__r1", "fam2", "A", "fam2", status="run_failed"),
                        make_run("fam2__B__r1", "fam2", "B", "fam2", status="run_failed")])
        self.write_ratings([])
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        out = json.loads(proc.stdout)
        inf = out["inference"]
        self.assertEqual(inf["arm_a_rate"], 0.0)
        self.assertEqual(inf["arm_b_rate"], 0.0)
        self.assertEqual(inf["contingency_2x2"]["neither"], 2)
        self.assertTrue(inf["degenerate_zero_discordance"])
        self.assertEqual(inf["mcnemar_exact_p"], 1.0)

    def test_challenge_refusal_vs_technical_failure(self):
        rows = [sched("chal1", "chal1", "A", 1, True, challenge=True),
                sched("chal1", "chal1", "B", 1, True, challenge=True)]
        self.write_manifest(rows)
        self.write_log([
            make_run("chal1__A__r1", "chal1", "A", "chal1",
                     status="refused_insufficient_evidence"),
            make_run("chal1__B__r1", "chal1", "B", "chal1", status="run_failed")])
        self.write_ratings([
            make_rating("c1", "R1", "chal1__A__r1", "chal1", "chal1", "challenge",
                        rating="appropriate_abstention"),
            make_rating("c2", "R2", "chal1__A__r1", "chal1", "chal1", "challenge",
                        rating="appropriate_abstention")])
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        out = json.loads(proc.stdout)
        ch = out["challenge_results_separate"]
        self.assertEqual(ch["chal1__A__r1"]["delivery"], "pipeline_refusal_rated")
        self.assertEqual(ch["chal1__A__r1"]["challenge_outcome"], "appropriate_abstention")
        self.assertEqual(ch["chal1__B__r1"]["delivery"], "technical_failure")
        self.assertFalse(ch["chal1__B__r1"]["abstention_correct"])

    def test_challenge_accounts_all_scheduled_runs(self):
        rows = [sched("chal1", "chal1", "A", 1, True, challenge=True),
                sched("chal1", "chal1", "A", 2, False, challenge=True),
                sched("chal1", "chal1", "B", 1, True, challenge=True),
                sched("chal1", "chal1", "B", 2, False, challenge=True)]
        self.write_manifest(rows)
        self.write_log([
            make_run("chal1__A__r1", "chal1", "A", "chal1"),
            make_run("chal1__A__r2", "chal1", "A", "chal1"),
            make_run("chal1__B__r1", "chal1", "B", "chal1"),
            make_run("chal1__B__r2", "chal1", "B", "chal1")])
        self.write_ratings([])
        for rid in ("chal1__A__r1", "chal1__A__r2", "chal1__B__r1", "chal1__B__r2"):
            pass
        ratings = []
        for rid in ("chal1__A__r1", "chal1__A__r2", "chal1__B__r1", "chal1__B__r2"):
            for rater in ("R1", "R2"):
                ratings.append(make_rating(f"{rid}-{rater}", rater, rid, "chal1", "chal1",
                                           "challenge", rating="appropriate_abstention"))
        self.write_ratings(ratings)
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(len(out["challenge_results_separate"]), 4)
        self.assertEqual(out["run_accounting"]["A"]["scheduled"], 2)
        self.assertEqual(out["run_accounting"]["A"]["done"], 2)

    def test_arm_config_mismatch_detected_per_arm(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1", arm_hash="WRONG"),
                        make_run("fam1__B__r1", "fam1", "B", "fam1")])
        self.write_ratings(rate_run("fam1__A__r1", "fam1", "fam1") +
                           rate_run("fam1__B__r1", "fam1", "fam1"))
        proc = self.run_analyze()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("arm_config_hash mismatch", proc.stdout)

    def test_adjudication_resolves_disagreement(self):
        rows = [sched("fam1", "fam1", "A", 1, True),
                sched("fam1", "fam1", "B", 1, True)]
        self.write_manifest(rows)
        self.write_log([make_run("fam1__A__r1", "fam1", "A", "fam1"),
                        make_run("fam1__B__r1", "fam1", "B", "fam1")])
        ratings = rate_run("fam1__B__r1", "fam1", "fam1")
        a_rows = rate_run("fam1__A__r1", "fam1", "fam1")
        for r in a_rows:
            if r["rater_id"] == "R2" and r["element_id"] == "E1":
                r["rating"] = "unsupported"
        self.write_ratings(ratings + a_rows)
        adj = self.dir / "adj.csv"
        with open(adj, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["run_id", "task_id", "family_id",
                                              "element_id", "final_rating",
                                              "reviewer_id", "date", "rationale"])
            w.writeheader()
            w.writerow({"run_id": "fam1__A__r1", "task_id": "fam1", "family_id": "fam1",
                        "element_id": "E1", "final_rating": "supported_and_correctly_cited",
                        "reviewer_id": "ADJ1", "date": "2026-10-01",
                        "rationale": "synthetic adjudication"})
        cmd = [sys.executable, str(ANALYZE), "--run-log", str(self.log),
               "--ratings", str(self.ratings), "--tasks-dir", str(self.tasks),
               "--manifest", str(self.manifest), "--adjudication", str(adj)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out["paired_table"][0]["arm_a_success"])


class PairedCITests(unittest.TestCase):
    def test_reference_cases_reflect_discordance(self):
        # identical marginals (50% vs 50%), different discordance
        ci1 = score_paired_diff_ci(b=5, c=5, n=40)
        ci2 = score_paired_diff_ci(b=15, c=15, n=40)
        self.assertAlmostEqual(ci1["delta"], 0.0)
        self.assertAlmostEqual(ci2["delta"], 0.0)
        self.assertGreater(abs(ci2["hi"] - ci2["lo"]), abs(ci1["hi"] - ci1["lo"]))
        self.assertGreater(ci2["psi"], ci1["psi"])

    def test_zero_discordance_flagged_degenerate(self):
        ci = score_paired_diff_ci(b=0, c=0, n=10)
        self.assertTrue(ci["degenerate_zero_discordance"])
        self.assertEqual(ci["lo"], 0.0)
        self.assertEqual(ci["hi"], 0.0)

    def test_directional_ci(self):
        ci = score_paired_diff_ci(b=50, c=2, n=200)
        self.assertGreater(ci["delta"], 0)
        self.assertGreater(ci["lo"], 0)  # strong advantage => positive lower bound

    def test_invalid_inputs_raise(self):
        with self.assertRaises(ValueError):
            score_paired_diff_ci(1, 1, 0)
        with self.assertRaises(ValueError):
            score_paired_diff_ci(-1, 0, 10)
        with self.assertRaises(ValueError):
            score_paired_diff_ci(6, 6, 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
