# judge_emulate.py - scoring arithmetic review (GATE-V2 3.1)

Reviewer: Fable, session Z. Date: 2026-09-18. Scope: arithmetic and logic only, not judge quality. Nothing under /root/qc or the corpus was changed; all edge cases ran on temp copies under the session scratchpad.

## Verdict: ARITHMETIC-SOUND for the corpus's live case, with 2 latent reporting defects and 3 README corrections

Approved for the first live oracle run, on the condition that the run uses the rubric revision DataOS graded (see "Config mismatch" below). The scoring math is entirely rewardkit 0.2.0's own code; the emulator hand-computes no mean, weight or normalization. The defects found are in the emulator's output-labelling layer and cannot change `total_reward` on any task in either corpus copy today (every one of 40 stage tasks and 202 `03_dataos_ready` tasks is `[[reward]] name = "reward"`, `weighted_mean` at both levels, `type = "binary"`, no `mode`, `negate`, `optional` or criterion-level `files`).

## The two totals compared

Source of truth: `/root/qc/in/dataos-cr-batch1-returns/SVC-PC-29-2-0__v69265__opus5__reject.json` and the `gpt56sol` twin. Neither JSON carries a structured `reward-details` block. Both are Comprehensive Review records (`schema.type = COMPREHENSIVE_REVIEW`) whose only per-criterion and total figures are inside the reviewer's prose (`turns[0].output.response`). The task premise "carry per-criterion results and a total" holds only in that weaker sense. What the prose states, and what the emulator's scoring path (rewardkit functions, judge stubbed) returns for the same verdicts against the rev_1 rubric at `/root/qc/stage/SVC-PC-29-2-0/tests`:

| Scenario | JSON (prose) | Emulator path | Independent hand formula |
|---|---|---|---|
| Oracle, all 47 pass (eval_471883, eval_471920) | 1.0, "47/47" | **1.0** | 1.000000 |
| eval_471921, the 12 fails both reviews name (r007 r009 r030 r031 r036 r037 r040 r041 r047 r048 r049 r050) | 0.744 | **0.7676** | 0.767600 |
| eval_471921, 12 named + one unnamed deliverables_01 fail at 0.0236 | 0.744 | **0.744** | 0.744000 |
| Six 1.4 criteria only (review: "worth 0.1071") | 1 - 0.1071 = 0.8929 | 0.8929 | 0.892900 |
| r030/r036/r040 only (review: "costing it 0.068") | 0.932 | 0.932 | 0.932000 |

The oracle total matches exactly. The eval_471921 total is off by exactly 0.0236, which is the weight of every deliverables_01 criterion except r001 (0.0245) and r012 (0.0218); the reviews' fail lists are not exhaustive (the gpt56 list omits r030/r036/r040/r031 that the opus5 review names), so one further deliverables_01 fail that neither review mentions closes the gap to 0.744 exactly. The reviewer's own partial sums (0.1071, 0.068, "~0.851 without these" = 0.744 + 0.1071) all reproduce to 4 dp through the emulator's path, which is the stronger evidence: the additive "total = 1 - sum of failed weights" structure the DataOS grader exhibits is exactly what rewardkit's two-level weighted mean produces when each judge.toml's criterion weights sum to its reward.toml group weight (true for all 5 groups here: 0.2823 / 0.258 / 0.24 / 0.1931 / 0.0266). Hand formula and rewardkit agreed to 4 dp in every scenario; rewardkit rounds each group to 4 dp before combining, so a last-digit difference is possible in principle and did not occur here.

## Config mismatch (blocks a naive comparison, not the arithmetic)

Five local copies of the rubric exist and they are not the same rubric:

| Copy | Criteria | Ids | deliverables_02 weights | Matches DataOS rev_1? |
|---|---|---|---|---|
| `/root/qc/stage/SVC-PC-29-2-0/tests` | 47 | skips r024, r025, r035 | 10 x 0.0238 + 0.02 | **yes** (reviews cite r015 = .0238, r034 = .024, "47 remaining", ids skip r024/r025/r035) |
| `/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready/SVC-PC-29-2-0/tests` (emulator `--corpus-root` default, and what the README §6 dry-run used) | 50 | contiguous r001-r050 | 10 x 0.0218 + 2 x 0.02 | no |
| `/root/qc/batch-01/_before/SVC-PC-29-2-0/tests` | 50 | same as above | same | no |
| `/root/qc/batch-01/SVC-PC-29-2-0/tests` | 29 | many dropped | group weights 0.55/0.188/0.126/0.106/0.03 | no (post-rework) |
| `00_fetched` | xlsx rubric only, no TOML | | | n/a |

Group weights in reward.toml are identical across stage, 03_dataos_ready and _before; only the per-criterion set and weights differ. Any comparison of an emulator total against a DataOS number for this task must run against `stage/` (pass `--corpus-root /root/qc/stage`). The emulator's default corpus root would silently grade a different rubric.

## Checks requested, with what was RUN vs READ

1. **Delegation to rewardkit (READ, then RAN).** `judge_emulate.py` calls `rk_runner._discover_layout` (line 525), `_score_layout` (547), `_layout_details` (548), `_group_aggregation` (431), and reads `layout.specs[*].weights` (421-425). Per-criterion values come from `parse_judge_response` (308), which applies `c.output_format.normalize` and `negate` (judges.py 272-274). `Reward.score` -> `aggregate_scores` -> `_weighted_mean` (reward.py 41-69, 258-260) does every mean. `_score_group` / `_score_layout` (runner.py 614-660) do the group and root combination. The only Score objects the emulator constructs itself are `_synthetic_error_scores` (236-252): value 0.0, weight copied from the TOML weights list, used for dry-run, budget-exhausted, CLI error, parse error and AgentJudge. No hand-rolled arithmetic anywhere in the 602 lines. `passed = s.value > 0` (443) matches rewardkit's own all_pass / required_pass test (reward.py 54, 65).

2. **Reproduction (RAN).** `_scratch_repro.py` monkeypatches `judge_emulate.call_llm` with a stub that returns rewardkit-shaped JSON verdicts and runs `judge_emulate.main()` end to end (discovery, bucketing, path remap, MarkItDown extraction of the golden xlsx, parse, aggregation, output). Five stubbed calls per run, 12/11/10/12/2 criteria, all 47 parsed with no error. Results in the table above. A separate pure-python formula reading the TOML files directly (no rewardkit import) agreed in every case.

3. **Group weights and must-pass (RAN).** Emulator `groups[*].weight` equals reward.toml's five weights (asserted True); every `criteria[*].weight` equals its judge.toml row (0 mismatches over 47). Weighted mean over per-criterion TOML weights is what `aggregate_scores` applies (reward.py 45), normalised by the sum of weights, so within-group scale does not matter (E12: x10 weights, identical scores). The `[judge] weight` field in judge.toml is consumed as `reward_weight` (runner.py 177) but cancels out in a single-reward group, and a group missing from reward.toml's `weights` defaults to 1.0 in both rewardkit (runner.py 651) and the emulator (425); E8 confirmed both agree (0.7466). Class-H flag: fires on r001/r003/r012, r015/r018/r023, r033/r034, r042/r043 for this task (202 must-pass-prose criteria across the 40 stage tasks), all correctly "unenforced" because every judge.toml is weighted_mean. See I1 for where the check reads the wrong level.

4. **Edge cases (RAN, on temp copies).** E1 all_pass gate -> group 0.0, total 0.9734. E2 negate: "no" -> 1.0, "yes" -> 0.0. E3 required_pass with optional criterion -> 1.0 / 0.0 as expected. E4 `mode = "individual"` + criterion-level `files` -> two buckets, one per file scope, score 0.5, total 0.9867 (README's "flagged, not verified" gap is now verified for arithmetic; prompt shape still differs from rewardkit's one-criterion-per-call fan-out, which cannot change the numbers). E5 batched + criterion-level files -> rewardkit itself raises ValueError at discovery (runner.py 156-165), so the emulator cannot mis-score it. E6 AgentJudge (`judge = "claude-code"`) -> group 0.0 with warning, other groups untouched, total 0.9734. E7 likert 3/5 -> 0.5. E9 `--max-criteria 5` -> one call, 35 skipped at 0.0, total 0.2823. E10 dry-run -> 0.0, zero calls. E11 unparseable response -> whole bucket 0.0 with `parse error`, no crash. E14 flat layout -> total = the single group's score.

5. **Normalization (READ).** Binary yes/true/1 -> 1.0 else 0.0 (models.py 57-62), Likert `(raw-1)/(points-1)` clamped, Numeric `(raw-min)/span` clamped; `negate` flips after normalize (judges.py 273); `optional` only matters under required_pass (reward.py 58). All reached through `parse_judge_response`, never reimplemented. Confirmed by E2 and E7 at run time.

## Issues

**I1 (logic, latent here): class-H flag and `aggregation` field read the group level, not the judge.toml `[scoring]` level.** `build_group_output` line 431 calls `rk_runner._group_aggregation(group)`, which returns `group.spec.aggregation` and `group.spec` is None for every `deliverables_NN` directory (no reward.toml inside it), so it is always `"weighted_mean"` regardless of what judge.toml's `[scoring] aggregation` says. E1 shows the consequence: with a real `aggregation = "all_pass"` gate in judge.toml, the output still reports `"aggregation": "weighted_mean"` and still lists a must-pass-prose criterion under `must_pass_prose_but_unenforced` (line 435-436) even though the gate is enforced. Arithmetic is unaffected because rewardkit scores the Reward with its own `reward.aggregation`. Fix: at line 435 test `reward.aggregation == "weighted_mean"` (the `Reward` object carries the judge.toml value, runner.py 187) and report `reward.aggregation` per criterion set, keeping `_group_aggregation(group)` as a separate `group_aggregation` field.

**I2 (logic, latent here): `total_reward` is looked up under the literal key `"reward"`.** Line 550 `main_scores.get("reward")` assumes the root `[[reward]]` is named `reward`. E13 (spec renamed `total`) yields `total_reward: None` and the warning "no named [[reward]] table ... more than one top-level group" while `rewardkit_native.main` plainly contains `'total': 0.9867`. Fix: read the name from `layout.specs` (`spec.name for spec in layout.specs if spec.name`), fall back to the single-group case only when `layout.specs` is empty. Zero impact today: all 242 reward.toml files across both copies use `name = "reward"`.

**I3 (README, wrong numbers): §2 example.** "If it fails r006 (weight 0.0236) and passes the rest, group score = (1.0 - 0.0236) = 0.9764" is wrong. Run: deliverables_01 group score is 0.9164 = (0.2823 - 0.0236) / 0.2823; the total is 0.9764. The same paragraph says the 12 weights are "summing to 1.0 within that group"; they sum to 0.2823, the group's reward.toml weight. §6 repeats the group-weight sum (correct, 1.0000) but the §2 within-group claim is what a reader will use. Fix: replace the example with the two numbers above and state that within-group weights sum to the group weight, which is why each failed criterion subtracts exactly its own weight from the total.

**I4 (README, stale):** §5 says individual mode is "flagged, not verified"; E4 verifies the arithmetic. §6's dry-run was run on the 50-criterion `03_dataos_ready` copy, not the graded rev_1; the README should name which rubric revision a comparison against DataOS must use.

**I5 (environment caveat, not an emulator bug):** `tests/test.sh` runs `pip install --quiet 'harbor-rewardkit[all]'` unpinned. Local venv has 0.2.0; PyPI's latest is 0.2.1 (`pip index versions`, run 2026-09-18). DataOS's next verify will use 0.2.1. This review checked 0.2.0's arithmetic only; diff `reward.py` / `runner.py` between 0.2.0 and 0.2.1 before treating emulator totals as bit-identical to a future DataOS run.

## Integrity block

RAN: `_scratch_repro.py` (6 scenarios through `judge_emulate.main()` with `call_llm` stubbed, plus the independent TOML hand formula) and `_scratch_edges.py` (E1-E14 on temp copies under the scratchpad `edge_corpus/`), both with `/root/venv/bin/python3`; TOML tabulation of all five local rubric copies; corpus-wide greps of reward.toml names, aggregations, criterion types and non-default fields across 40 stage and 202 `03_dataos_ready` tasks; `pip index versions harbor-rewardkit`; structure walk and keyword extraction of both DataOS JSONs.
READ: `judge_emulate.py` (all 602 lines), `judge_emulate.README.md`, rewardkit 0.2.0 `reward.py` (all), `runner.py` 59-220 / 338-533 / 594-705, `judges.py` 239-449 and `_build_criteria_block` / `build_prompt`, `models.py` 16-172, `tests/test.sh`, both review prose texts (23,141 and 10,324 chars).
NOT DONE: no live `claude -p` call was made; every judge verdict in this review was a stub. Live-call parseability is still the next budget-gated step per GATE-V2 3.0. The 0.744 figure was not reproduced from a complete per-criterion record because none exists in the JSONs; it was reproduced to within one unnamed 0.0236 criterion, and the reviewer's three partial sums were reproduced exactly.
Scratch files: `/tmp/claude-0/-root/ca00b531-7932-403e-b99f-4b46c8da02d2/scratchpad/_scratch_repro.py`, `_scratch_edges.py`, `edge_corpus/`, `opus5_response.md`, `gpt56_response.md`.
