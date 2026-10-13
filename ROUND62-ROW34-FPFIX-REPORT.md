# Round 62 Row 34 Fix Report: word_ban_false_trigger_check.py

## What changed

Two changes to `_detect_word_ban` in `deterministic-checks/word_ban_false_trigger_check.py`:

1. **Token-distance negation proximity** (replaces character-window): The old check used
   `NEGATION_WINDOW = 80` characters, which matched a negation cue anywhere within 80 chars
   of a ban-word cluster. The new check measures word-token distance between the negation
   cue and a ban word in the cluster. A gap of 0 tokens ("no scoring") always matches. A gap
   of 1-2 tokens matches only if every intervening token is an adjective or determiner
   ("no internal grading" matches; "never delivered a scorecard" does not, because
   "delivered" is a verb). Non-adjective/determiner tokens break the match regardless of
   token count.

2. **2+ unique ban words in cluster**: The old check required 2+ occurrences of any ban
   word (including the same word twice). The new check requires 2+ unique ban words. A
   content criterion mentioning "scorecard" twice is not a ban list; a word-ban criterion
   lists multiple different banned words ("scoring, grading, benchmark or model-name").

## 10-task verification (first commit)

Command: `python word_ban_false_trigger_check.py <corpus> --task <10 ids>`

### False positives: MUST STOP (all 4 now OK)

| Task | Criterion | Description excerpt | Why it stopped |
|---|---|---|---|
| SVC-PC-31-0-0 | r076 | "Declines to score items that were never planned" | 1 unique ban word (score x2); "never" not adjacent to "score" |
| SVC-PC-70-6-0 | tp03 | "never delivered a scorecard ... no scorecard all year" | 1 unique ban word (scorecard x2) |
| SVC-PC-15-3-0 | e11 | "SLA scorecard was never delivered" | 1 unique ban word (scorecard x2) |
| SVC-PC-58-0-0 | c08 | "weighted score with no inversions" | 1 unique ban word (score x2); "no" not adjacent to "score" |

### True positives: MUST KEEP (all 6 still FAIL)

| Task | Criterion | Description excerpt | Why it kept firing |
|---|---|---|---|
| SVC-PC-14-1-0 | r-23 | "NO internal grading, rubric, or self-scoring" | 3 unique; no->grading 1 adj token |
| SVC-PC-52-3-0 | f5 | "No scoring, grading, benchmark or model-name" | 4 unique; no->scoring 0 tokens |
| SVC-PC-52-5-0 | g7 | "No scoring, grading, benchmark or model-name" | 4 unique; no->scoring 0 tokens |
| SVC-PC-38-6-0 | g4 | "No scoring, rubric, benchmark or model-name" | 4 unique; no->scoring 0 tokens |
| SVC-PC-77-0-0 | c18 | "Neither artifact contains grading, rubric..." | 5 unique; No->rubric 0 tokens (Expected part) |
| SVC-PC-66-2-0 | e4 | "No scoring, rubric, benchmark or model-name" | 4 unique; no->scoring 0 tokens |

Result: 4/10 clean, 6 FAIL. Matches expected exactly.

## Full SVC-PC corpus run (second commit)

Command: `python word_ban_false_trigger_check.py C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready --json _full_svcpc_results.json`

### Summary

| Metric | Value |
|---|---|
| Total tasks | 600 |
| Clean (OK) | 543 |
| FAIL (hard findings) | 57 |
| Word-ban detected (INFO+hard) | 60 |
| Parse errors (no tests/) | 2 |
| reward_at_risk_upper_bound | 1.454517 |

### 4 target false positives confirmed absent from fail set

SVC-PC-31-0-0, SVC-PC-70-6-0, SVC-PC-15-3-0, SVC-PC-58-0-0: all OK (not in the 57 FAIL).

### 6 target true positives confirmed present in fail set

SVC-PC-14-1-0, SVC-PC-52-3-0, SVC-PC-52-5-0, SVC-PC-38-6-0, SVC-PC-77-0-0, SVC-PC-66-2-0:
all FAIL (in the 57).

### 15-task spot-check of new fail set

15 tasks not in the original 10 were checked by reading their real judge.toml criterion
descriptions. All 15 are genuine word-ban criteria: each has 2+ unique ban words with a
negation cue directly adjacent (0-1 adjective/determiner tokens).

| Task | Criterion | Description excerpt | Unique ban words | Negation adjacency |
|---|---|---|---|---|
| SVC-PC-14-2-0 | jdg-05 | "No internal grading, rubric, self-scoring..." | 3 | no->grading 1 adj |
| SVC-PC-14-5-0 | c15 | "No internal grading, evaluation standards..." | 3 (grading, score, grade) | no->grading 1 adj |
| SVC-PC-25-7-0 | c24 | "No internal grading/internal evaluation..." | 3 (grade, score, grading) | no->grading 1 adj |
| SVC-PC-38-0-0 | k6 | "No scoring, grading, benchmark, model-name" | 4 | no->scoring 0 tokens |
| SVC-PC-42-4-0 | c20 | "no internal grading content..." | 2 (grading, scoring) | no->grading 1 adj |
| SVC-PC-58-1-0 | c16 | "no internal grading/evaluation..." | 2 (grading, scoring) | no->grading 1 adj |
| SVC-PC-66-0-0 | a11 | "No scoring, grading, benchmark or model-name" | 4 | no->scoring 0 tokens |
| SVC-PC-71-0-0 | c26 | "No internal grading/rubric/self-scoring..." | 4 | no->grading 1 adj |
| SVC-PC-77-4-0 | c10 | "No grading/self-scoring content..." | 3 | no->grading 0 tokens |
| SVC-PC-88-0-0 | str-07 | "No grading / rubric / self-scoring..." | 4 | no->grading 0 tokens |
| SVC-PC-93-0-0 | r25 | "contains no grading, rubric, scoring..." | 5 | no->grading 0 tokens |
| SVC-PC-93-4-0 | c25 | "without grading material ... no rubric, score..." | 4 | without->grading 0 tokens |
| SVC-PC-71-5-0 | cfc-01 | "Contains no internal grading, rubric..." | 5 | no->grading 1 adj |
| SVC-PC-66-6-0 | h4 | "No scoring, grading, benchmark or model-name" | 4 | no->scoring 0 tokens |
| SVC-PC-77-5-0 | c11 | "no grading or self-scoring..." | 4 | no->grading 0 tokens |

No new false positives found in the spot-check.

### Parse errors (not findings-related)

- SVC-PC-5-3-0: no tests/deliverables*/judge.toml or tests/verifier.json found
- SVC-PC-94-7-0: no tests/deliverables*/judge.toml or tests/verifier.json found

These are missing-config tasks, not word-ban issues.

## EKW run

Not run: no verifier.json files found in this worktree. The EKW corpus
(C:/ekwqc/repo/ekw/) contains only a fetch manifest, no staged task packages.

## What was NOT done

- EKW corpus run (no EKW task packages staged in this worktree).
- Push (per instructions: do not push).
