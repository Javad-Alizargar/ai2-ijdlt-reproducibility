#!/usr/bin/env python3
"""
run_benchmark.py — frozen-pipeline benchmark orchestrator (Round 2).

Runs development/evaluation tasks across comparison arms with repetitions.
Arm A: frozen AI2 pipeline (retrieval via pipeline_bridge.js -> answer model
call -> supervisor model call -> citation audit via bridge).
Arm B: same answer model without retrieval (baseline prompt, research config).

Usage:
  python3 code/benchmark/run_benchmark.py \
    --tasks-dir tasks/dev --run-dir results/benchmark \
    --arms A,B --repetitions 1 --set dev \
    [--dry-run] [--max-requests 24] [--ceiling-usd 5.0]

Features: dry-run (zero paid requests), append-only run log, resumable,
run-id uniqueness, hash provenance, budget ceiling enforcement.
Secrets come only from environment (OPENAI_API_KEY; NCBI_KEY_FILE for the
Node bridge) and are never logged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from provider_adapter import BudgetLedger, ProviderError, call  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PROMPTS_PATH = ROOT / "data" / "processed" / "prompts_frozen.json"
BRIDGE = ROOT / "code" / "benchmark" / "pipeline_bridge.js"
MODEL = "gpt-4.1-mini"
ANSWER_TEMP = 0.15
ANSWER_MAX_TOKENS = 1700
SUPERVISOR_TEMP = 0.0
SUPERVISOR_MAX_TOKENS = 1800

BASELINE_SYSTEM_PROMPT = (
    "You are an academic research assistant answering scholarly questions for an "
    "educational-technology evaluation. Answer the question as a careful scholar: "
    "do not invent references; if you rely on published evidence, describe it "
    "precisely (authors, year, journal, title, DOI when known); state uncertainty "
    "explicitly; if you cannot support a claim, say so. End with an Evidence "
    "quality line: High / Moderate / Low / Insufficient."
)


def sha256(data) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_node(args, cwd=None) -> dict:
    proc = subprocess.run(["node", str(BRIDGE), *args], capture_output=True, text=True, cwd=cwd or ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"bridge failed: {proc.stderr.strip()[:400]}")
    last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    return json.loads(last)


def load_prompts() -> dict:
    with open(PROMPTS_PATH) as f:
        return json.load(f)


def config_hash() -> str:
    return sha256(json.dumps({
        "model": MODEL, "answer_temp": ANSWER_TEMP, "answer_max_tokens": ANSWER_MAX_TOKENS,
        "supervisor_temp": SUPERVISOR_TEMP, "supervisor_max_tokens": SUPERVISOR_MAX_TOKENS,
        "prompts_sha256": sha256_file(PROMPTS_PATH),
        "baseline_prompt": BASELINE_SYSTEM_PROMPT,
        "bridge": sha256_file(BRIDGE),
    }, sort_keys=True))


def shared_config_hash() -> str:
    """Common settings that MUST match across arms (model + generation)."""
    return sha256(json.dumps({
        "model": MODEL, "answer_temp": ANSWER_TEMP, "answer_max_tokens": ANSWER_MAX_TOKENS,
    }, sort_keys=True))


def arm_config_hash(arm: str) -> str:
    """Arm-specific frozen specification (verified per arm, not cross-arm)."""
    if arm == "A":
        return sha256(json.dumps({
            "arm": "A", "pipeline_prompts_sha256": sha256_file(PROMPTS_PATH),
            "bridge_sha256": sha256_file(BRIDGE),
            "supervisor_temp": SUPERVISOR_TEMP,
            "supervisor_max_tokens": SUPERVISOR_MAX_TOKENS,
            "pipeline_settings": {"paper_count": 12, "year_range": "last5",
                                  "prefer_recent": True, "use_journal_rank": False},
        }, sort_keys=True))
    return sha256(json.dumps({
        "arm": "B", "baseline_prompt": BASELINE_SYSTEM_PROMPT,
        "answer_temp": ANSWER_TEMP, "answer_max_tokens": ANSWER_MAX_TOKENS,
    }, sort_keys=True))


def load_task(tasks_dir: Path, task_id: str) -> dict:
    p = tasks_dir / f"{task_id}.json"
    if not p.exists():
        raise FileNotFoundError(str(p))
    with open(p) as f:
        return json.load(f)


def build_answer_messages(prompts: dict, task: dict, evidence: list | None, queries: list) -> tuple[list, list]:
    """Return (messages, search_queries_used) faithful to production."""
    payload_user = {
        "task": "Answer the user question from the supplied evidence only.",
        "user_context": {
            "role": task["role"], "mode": task["mode"], "specialty": task["specialty"],
            "question": task["question"],
            "response_language": task.get("response_language", "en"),
            "requested_papers": task.get("paper_count", 12),
        },
        "search_queries_used": queries,
        "evidence": [
            {
                "number": i + 1, "source": e.get("source"), "query_label": e.get("query_label"),
                "title": e.get("title"), "year": e.get("year"), "journal": e.get("journal"),
                "authors": e.get("authors"), "abstract": e.get("abstract"),
                "url": e.get("url"), "doi": e.get("doi"), "pmid": e.get("pmid"),
                "journal_rank_percentile": e.get("journal_rank_percentile"),
            }
            for i, e in enumerate(evidence or [])
        ],
    }
    messages = [
        {"role": "system", "content": prompts["answer_system_prompt"]},
        {"role": "user", "content": json.dumps(payload_user, ensure_ascii=False)},
    ]
    return messages, payload_user["search_queries_used"]


def build_supervisor_messages(prompts: dict, task: dict, draft: str, evidence: list) -> list:
    user = {
        "user_context": {
            "role": task["role"], "mode": task["mode"], "specialty": task["specialty"],
            "question": task["question"], "response_language": task.get("response_language", "en"),
        },
        "draft_answer": draft,
        "evidence": [
            {"number": i + 1, "title": e.get("title"), "year": e.get("year"),
             "journal": e.get("journal"), "abstract": e.get("abstract"),
             "url": e.get("url"), "pmid": e.get("pmid"), "doi": e.get("doi")}
            for i, e in enumerate(evidence)
        ],
    }
    return [
        {"role": "system", "content": prompts["supervisor_system_prompt"]},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def build_baseline_messages(task: dict) -> list:
    lang = task.get("response_language", "en")
    lang_instruction = ("Write the entire answer in Traditional Chinese. Keep scientific terms precise; "
                        "include English abbreviations in parentheses when clinically useful."
                        if lang in ("zh", "zh-hant", "traditional_chinese")
                        else "Write the entire answer in polished academic English.")
    user = (f"Role: {task['role']}; Use case: {task['mode']}; "
            f"Specialty: {task['specialty']}.\nQuestion: {task['question']}\n"
            f"{lang_instruction}")
    return [
        {"role": "system", "content": BASELINE_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def arm_a_run(task: dict, run_id: str, run_dir: Path, cache_dir: Path, prompts: dict,
              api_key: str, dry_run: bool, ledger: BudgetLedger, raw_dir: Path) -> dict:
    stages = []
    rec = {"arm": "A", "run_id": run_id, "task_id": task["task_id"],
           "family_id": task.get("family_id"), "set": task.get("set"),
           "response_language": task.get("response_language", "en"),
           "config_hash": config_hash(),
           "shared_config_hash": shared_config_hash(),
           "arm_config_hash": arm_config_hash("A"),
           "dry_run": dry_run}

    t0 = time.time()
    tmp = run_dir / "tmp" / run_id
    tmp.mkdir(parents=True, exist_ok=True)
    retrieval_out = tmp / "retrieval.json"
    run_node(["retrieval", "--task", str(task.get("_path", "")),
              "--out", str(retrieval_out), "--retrieval-cache", str(cache_dir)], cwd=ROOT)
    with open(retrieval_out) as f:
        snap = json.load(f)
    stages.append({"stage": "retrieval", "latency_s": round(time.time() - t0, 2),
                   "evidence_count": len(snap.get("evidence", [])),
                   "cache_key": snap.get("cache_key"),
                   "stage_errors": snap.get("stage_errors", [])})
    evidence = snap.get("evidence", [])
    rec["retrieval_snapshot_sha256"] = sha256_file(retrieval_out)

    if not evidence:
        rec["status"] = "refused_insufficient_evidence"
        rec["stages"] = stages
        rec["answer_text"] = ""
        rec["supervisor_audit"] = {"model_used": False}
        rec["duration_s"] = round(time.time() - t0, 2)
        return rec

    msgs, queries = build_answer_messages(prompts, task, evidence, snap.get("queries", []))
    t1 = time.time()
    ans = call("openai", MODEL, msgs, max_output_tokens=ANSWER_MAX_TOKENS, api_key=api_key,
               dry_run=dry_run, raw_dir=raw_dir, temperature=ANSWER_TEMP,
               ledger=ledger, run_id=run_id, purpose="answer")
    stages.append({"stage": "answer", "latency_s": round(time.time() - t1, 2),
                   "usage": ans.usage, "cost_usd": round(ans.cost_usd, 6), "attempts": ans.attempts})
    draft = ans.content or ""
    rec["answer_usage"] = ans.usage
    rec["answer_cost_usd"] = round(ans.cost_usd, 6)

    # supervisor
    sup_msgs = build_supervisor_messages(prompts, task, draft, evidence)
    t2 = time.time()
    sup = call("openai", MODEL, sup_msgs, max_output_tokens=SUPERVISOR_MAX_TOKENS, api_key=api_key,
               dry_run=dry_run, raw_dir=raw_dir, temperature=SUPERVISOR_TEMP,
               ledger=ledger, run_id=run_id, purpose="supervisor")
    stages.append({"stage": "supervisor", "latency_s": round(time.time() - t2, 2),
                   "usage": sup.usage, "cost_usd": round(sup.cost_usd, 6), "attempts": sup.attempts})
    parsed = {}
    try:
        parsed = json.loads(sup.content or "{}")
    except Exception:
        parsed = {}
    corrected = str(parsed.get("corrected_answer") or "").strip()
    chosen = corrected or draft

    draft_path = tmp / "draft.txt"
    draft_path.write_text(chosen)
    audit_out = tmp / "audit.json"
    run_node(["audit", "--draft", str(draft_path), "--evidence", str(retrieval_out),
              "--out", str(audit_out)], cwd=ROOT)
    with open(audit_out) as f:
        audit = json.load(f)
    rec["answer_text"] = audit["cleaned_answer"]
    rec["answer_sha256"] = sha256(rec["answer_text"])
    rec["supervisor_audit"] = {
        "model_used": bool(sup.content), "parsed_pass": bool(parsed.get("pass")),
        "problems": parsed.get("problems", []), "unsupported_citations": parsed.get("unsupported_citations", []),
        "local_audit": audit["local_audit"], "used_corrected": bool(corrected),
    }
    rec["status"] = "done"
    rec["stages"] = stages
    rec["duration_s"] = round(time.time() - t0, 2)
    rec["search_queries_used"] = queries
    return rec


def arm_b_run(task: dict, run_id: str, run_dir: Path, api_key: str,
              dry_run: bool, ledger: BudgetLedger, raw_dir: Path) -> dict:
    rec = {"arm": "B", "run_id": run_id, "task_id": task["task_id"],
           "family_id": task.get("family_id"), "set": task.get("set"),
           "response_language": task.get("response_language", "en"),
           "config_hash": config_hash(),
           "shared_config_hash": shared_config_hash(),
           "arm_config_hash": arm_config_hash("B"),
           "dry_run": dry_run}
    t0 = time.time()
    msgs = build_baseline_messages(task)
    ans = call("openai", MODEL, msgs, max_output_tokens=ANSWER_MAX_TOKENS, api_key=api_key,
               dry_run=dry_run, raw_dir=raw_dir, temperature=ANSWER_TEMP,
               ledger=ledger, run_id=run_id, purpose="baseline_answer")
    rec["answer_text"] = (ans.content or "").strip()
    rec["answer_sha256"] = sha256(rec["answer_text"])
    rec["answer_usage"] = ans.usage
    rec["answer_cost_usd"] = round(ans.cost_usd, 6)
    rec["status"] = "done"
    rec["duration_s"] = round(time.time() - t0, 2)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks-dir", required=True)
    ap.add_argument("--run-dir", default=str(ROOT / "results" / "benchmark"))
    ap.add_argument("--arms", default="A,B")
    ap.add_argument("--repetitions", type=int, default=1)
    ap.add_argument("--set", default="dev")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-requests", type=int, default=24)
    ap.add_argument("--ceiling-usd", type=float, default=5.0)
    ap.add_argument("--task-ids", default="", help="comma list; default all tasks in dir")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = run_dir / "retrieval_cache"
    raw_dir = run_dir / "raw_responses"
    log_path = run_dir / "run_log.jsonl"
    ledger_path = run_dir / "budget_ledger.jsonl"
    ledger = BudgetLedger(ledger_path, args.ceiling_usd, args.max_requests)

    tasks_dir = Path(args.tasks_dir)
    prompts = load_prompts()
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key and not args.dry_run:
        print("ERROR: OPENAI_API_KEY not set and not in dry-run mode")
        return 2

    ids = [t.strip() for t in args.task_ids.split(",") if t.strip()] if args.task_ids else [
        p.stem for p in sorted(tasks_dir.glob("*.json")) if not p.name.startswith("_")]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    existing = set()
    if log_path.exists():
        with open(log_path) as f:
            for line in f:
                try:
                    existing.add(json.loads(line)["run_id"])
                except Exception:
                    pass

    for task_id in ids:
        task = load_task(tasks_dir, task_id)
        task["_path"] = str(tasks_dir / f"{task_id}.json")
        for arm in arms:
            for rep in range(1, args.repetitions + 1):
                run_id = f"{task_id}__{arm}__r{rep}"
                if run_id in existing:
                    print(f"skip (exists): {run_id}")
                    continue
                n, c = ledger.totals()
                if not args.dry_run and (n >= args.max_requests or c >= args.ceiling_usd):
                    print(f"BUDGET REACHED ({n} requests, ${c:.4f}); stopping. Remaining runs not executed.")
                    return 3
                try:
                    if arm == "A":
                        rec = arm_a_run(task, run_id, run_dir, cache_dir, prompts,
                                        api_key, args.dry_run, ledger, raw_dir)
                    else:
                        rec = arm_b_run(task, run_id, run_dir, api_key,
                                        args.dry_run, ledger, raw_dir)
                except ProviderError as e:
                    rec = {"arm": arm, "run_id": run_id, "task_id": task_id,
                           "family_id": task.get("family_id"), "set": task.get("set"),
                           "status": "run_failed", "stage_error": "provider_hard_error",
                           "message": str(e)[:300], "dry_run": args.dry_run}
                    print(f"HARD PROVIDER ERROR at {run_id}: {str(e)[:160]}")
                except Exception as e:
                    rec = {"arm": arm, "run_id": run_id, "task_id": task_id,
                           "family_id": task.get("family_id"), "set": task.get("set"),
                           "status": "run_failed", "stage_error": "harness_error",
                           "message": str(e)[:300], "dry_run": args.dry_run}
                    print(f"RUN FAILED {run_id}: {str(e)[:160]}")
                with open(log_path, "a") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n2, c2 = ledger.totals()
                print(f"{run_id} -> {rec.get('status')} (requests={n2}, cost=${c2:.4f})")

    n3, c3 = ledger.totals()
    print(f"FINISHED. total requests={n3}/{args.max_requests}, cost=${c3:.4f}/{args.ceiling_usd:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
