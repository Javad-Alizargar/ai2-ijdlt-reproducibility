# Rater Instructions — AI2 Benchmark Human Review

Round 2, 2026-10-01. Development-pilot version (calibration on the dev set).

## 1. Your job

For each blinded answer packet, judge whether the answer satisfies each
REQUIRED element of the task's rubric, using ONLY the public reference source
provided for that element. You are not judging style, grammar, or whether the
answer "sounds good". You are judging:

(a) does the answer state the required content (completeness),
(b) is the stated content correct relative to the reference source (accuracy),
(c) is the citation attached to the claim a real, findable source that
    actually supports it (support), and
(d) are there fabricated references or material contradictions (fatal flags).

## 2. Element ratings (one per required element)

- supported_and_correctly_cited — content present AND correct AND the cited
  source is real, findable, and supports the statement (you verified this;
  record ref_verified = yes).
- supported_but_miscited — content present and correct, but the citation does
  not actually support it (wrong source, or real source that does not contain
  the claim), or you could not verify support. A VALID DOI attached to the
  WRONG claim is this category, not pass.
- unsupported — the answer asserts the element without any usable source.
- omitted — the element is missing entirely.
- refusal — the answer explicitly declines/abstains on this element with a
  reason (counts against completeness, not as support).
- not_ratable — the answer is empty, truncated, or otherwise cannot be judged.

## 3. Fatal flags (per run, not per element)

- fabrication_flag = yes if any cited reference does not exist (DOI/PMID
  resolves to nothing, or title/authors/journal combination is not findable).
- contradiction_flag = yes if the answer contains a material statement that
  contradicts the reference source or a prespecified task constraint
  (population, setting, time).
- refusal_flag = yes if the answer as a whole refuses/abstains.

Distinctions you must keep:
- Unverifiable ≠ fabricated: if you simply cannot resolve a reference (e.g.,
  no DOI, ambiguous title), do NOT mark fabricated; note "unverifiable" in
  notes and rate support as not verified (supported_but_miscited unless you
  independently verified the content from another cited source).
- Existence ≠ support: a real paper cited for a claim it does not make is
  support failure.
- Negative ratings are legitimate; do not soften them.

## 4. Calibration workflow (dev set)

1. Read the task rubric and its reference source sections first.
2. Rate the packet independently. Do not discuss ratings before recording.
3. Fill evaluation/calibration_packet/blinded_rating_template.csv (one row
   per element; rater_id = your assigned pseudonym).
4. After both raters record, meet to reconcile disagreements; document the
   decision in the notes column of the agreed row. Report disagreement as well
   as agreement in the study.

## 5. Blinding

Answer packets are identified by blind IDs (B001...). The answer-to-arm
mapping is kept OUTSIDE this packet (admin/restricted/). Blinding is
IMPERFECT: answers with citation lists versus prose with no citations can
reveal the arm. Do not try to identify the arm; just rate content.

## 6. What NOT to do

- Do not use another LLM to generate ratings or to "verify" references.
  Ratings must be your own; reference verification uses the public sources.
- Do not fill in ratings for packets you did not read.
- Do not mark ref_verified = yes unless you actually checked the source.

## 7. Who verifies each rubric

The rubric's reference elements were drafted by the study team from public
documents (each element lists exact sections). Before the held-out freeze, a
second reviewer (not a workshop participant) independently checks every
element against its source and signs the rubric review sheet
(evaluation/rubric_review.csv). LLM drafts are NOT a reference standard.
