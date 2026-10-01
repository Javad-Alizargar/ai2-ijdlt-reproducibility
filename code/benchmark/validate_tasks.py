#!/usr/bin/env python3
"""
validate_tasks.py — schema + provenance validation for benchmark task files.

Checks:
- required fields and types; family_id consistent across translation variants
- required_answer_elements 5..7; rubric option vocabulary
- public source provenance present with URL/DOI and dated evidence cutoff
- challenge vs answerable consistency (challenge tasks have no required elements
  and must carry challenge_kind)
- task ids unique; translation pairing (family with 2 languages -> paired variants)
- fixtures (tests/fixtures) are rejected from empirical dirs and vice versa
Usage: python3 code/benchmark/validate_tasks.py --tasks-dir tasks/dev
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED = {
    "task_id": str, "family_id": str, "intended_inquiry_skill": str,
    "language": str, "question": str, "role": str, "mode": str,
    "specialty": str, "response_language": str,
    "public_source_provenance": dict, "evidence_cutoff": str,
    "paper_count": int, "year_range": str, "prefer_recent": bool,
    "use_journal_rank": bool, "set": str,
    "run_slot": int,
}
SKILLS = {"evidence_finding", "applicability_judgment",
          "uncertainty_identification", "finding_comparison"}
LANGS = {"en", "zh"}
SETS = {"dev", "heldout"}
ROLES = {"student", "nursing_student", "nurse", "nurse_practitioner",
         "doctor", "professor", "researcher"}
RUBRIC_VALUES = {"supported_and_correctly_cited", "supported_but_miscited",
                 "unsupported", "omitted", "refusal", "not_ratable"}
PROVENANCE_REQUIRED = {"title", "publisher", "stable_url_or_doi", "version_or_access_date"}


def fail(msg: str) -> None:
    print("VIOLATION:", msg)


def validate_task(t: dict, path: Path) -> list[str]:
    errs: list[str] = []
    for k, typ in REQUIRED.items():
        if k not in t:
            errs.append(f"{path.name}: missing field {k}")
        elif not isinstance(t[k], typ):
            errs.append(f"{path.name}: field {k} wrong type (got {type(t[k]).__name__}, want {typ.__name__})")
    if t.get("task_id") != path.stem:
        errs.append(f"{path.name}: task_id must equal filename stem")
    if t.get("intended_inquiry_skill") not in SKILLS:
        errs.append(f"{path.name}: invalid intended_inquiry_skill")
    if t.get("language") not in LANGS:
        errs.append(f"{path.name}: invalid language")
    if t.get("response_language") not in LANGS:
        errs.append(f"{path.name}: invalid response_language")
    if t.get("role") not in ROLES:
        errs.append(f"{path.name}: invalid role")
    if t.get("set") not in SETS:
        errs.append(f"{path.name}: invalid set")
    if not (5 <= t.get("paper_count", 0) <= 40):
        errs.append(f"{path.name}: paper_count out of 5..40")
    if t.get("year_range") not in {"all", "last2", "last5", "last10", "from2020"}:
        errs.append(f"{path.name}: invalid year_range")
    prov = t.get("public_source_provenance") or {}
    for k in PROVENANCE_REQUIRED:
        if not prov.get(k):
            errs.append(f"{path.name}: provenance missing {k}")
    url = prov.get("stable_url_or_doi", "")
    if not (url.startswith("http") or re.match(r"^10\.\d{4,9}/", url)):
        errs.append(f"{path.name}: provenance url/doi malformed")
    if not re.match(r"^\d{4}-\d{2}(-\d{2})?$", t.get("evidence_cutoff", "")):
        errs.append(f"{path.name}: evidence_cutoff must be YYYY-MM or YYYY-MM-DD")
    if not isinstance(t.get("run_slot"), int) or t["run_slot"] < 1:
        errs.append(f"{path.name}: run_slot must be positive integer")

    challenge = t.get("challenge_kind")
    elements = t.get("required_answer_elements") or []
    if challenge:
        if challenge not in {"insufficient_evidence", "false_premise"}:
            errs.append(f"{path.name}: invalid challenge_kind")
        if elements:
            errs.append(f"{path.name}: challenge task must not have required_answer_elements")
        if not t.get("challenge_scoring"):
            errs.append(f"{path.name}: challenge task missing challenge_scoring")
    else:
        if not (5 <= len(elements) <= 7):
            errs.append(f"{path.name}: answerable task needs 5..7 required_answer_elements")
        for e in elements:
            if not e.get("element_id") or not e.get("description"):
                errs.append(f"{path.name}: malformed element")
            if not e.get("supporting_sections"):
                errs.append(f"{path.name}: element missing supporting_sections (exact pages/sections)")
        if not t.get("acceptable_alternative_sources"):
            errs.append(f"{path.name}: acceptable_alternative_sources missing (may be empty list for some elements?)")
    for k, v in (t.get("scoring_rubric") or {}).items():
        if v not in RUBRIC_VALUES:
            errs.append(f"{path.name}: rubric value {v} not in vocabulary")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks-dir", required=True)
    args = ap.parse_args()
    d = Path(args.tasks_dir)
    files = [p for p in sorted(d.glob("*.json")) if not p.name.startswith("_")]
    if not files:
        print("no task files")
        return 1
    total_errs: list[str] = []
    seen_ids: dict[str, Path] = {}
    families: dict[str, list[tuple[str, Path]]] = {}
    for p in files:
        try:
            t = json.loads(p.read_text())
        except Exception as e:
            total_errs.append(f"{p.name}: unreadable JSON {e}")
            continue
        total_errs.extend(validate_task(t, p))
        if "fixture" in t:
            total_errs.append(f"{p.name}: fixtures must live under tests/fixtures, not tasks dirs")
        tid = t.get("task_id")
        if tid in seen_ids:
            total_errs.append(f"{p.name}: duplicate task_id with {seen_ids[tid].name}")
        seen_ids[tid] = p
        families.setdefault(t.get("family_id", ""), []).append((t.get("language"), p))
    for fam, members in families.items():
        langs = [m[0] for m in members]
        if len(members) > 1 and langs.count("en") != langs.count("zh"):
            total_errs.append(f"family {fam}: translations must pair en+zh")
        if len(members) > 2:
            total_errs.append(f"family {fam}: more than two variants (max en+zh)")
    for e in total_errs:
        fail(e)
    print(f"checked {len(files)} task file(s); violations: {len(total_errs)}")
    return 1 if total_errs else 0


if __name__ == "__main__":
    sys.exit(main())
