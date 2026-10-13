# judge_emulate.py - GATE-V2 4.1 arithmetic review

Reviewer: Fable (arithmetic only, not judge quality). Date: 2026-09-18.
Subject: `/root/qc/tools/judge_emulate.py` (Z / Sonnet), `_qc_common.py`, `judge_emulate.README.md`.

## Verdict: APPROVED

The script does no scoring arithmetic of its own. It fills `Reward.scores` and hands
the layout to rewardkit 0.2.0's `_score_layout` / `_layout_details` (judge_emulate.py:547-548).
Every number in `total_reward`, `groups[].score`, `groups[].weight` and
`groups[].criteria[].weight` traces to rewardkit's own code. Verified by reading
rewardkit `reward.py` (`_weighted_mean`, `aggregate_scores`) and `runner.py`
(`_group_weights`, `_score_group`, `_score_layout`), then by RUNNING the script
end to end with `call_llm` monkeypatched to return fixed yes/no vectors and
comparing against an independent hand computation
(`/tmp/claude-0/-root/c91c88ed-8d62-4716-84df-63e0387de43b/scratchpad/_scratch_vector_harness.py`).
Seven vectors run; judge_emulate equalled the hand computation on all seven.

One correction to the gate's own premise (item 1) and one scope limit on item 5,
neither a defect in the script. Details below.

## Deciding numbers

| Run (RAN) | Build | Fail vector | judge_emulate | hand calc | note |
|---|---|---|---|---|---|
| 1 | 03_dataos_ready (50 crit) | r007 r009 r037 r041 r047 r048 r049 r050 | 0.8596 | 0.8596 | match |
| 2 | 03_dataos_ready (50 crit) | + r030 r036 r040 | 0.7996 | 0.7996 | match |
| 3 | stage (47 crit, the graded build) | same 11 | 0.7916 | 0.7916 | 0.744 target: 0.0476 unattributed |
| 4 | stage | 11 minus the review's six | 0.8987 | 0.8987 | delta 0.1071 = review's "0.744 -> ~0.851" |
| 5 | stage copy, d05 = all_pass | r050 | 0.9734 | 0.9734 | group zeroed to 0.0 |
| 6 | stage copy, d05 = all_pass | none | 1.0 | 1.0 | |
| 7 | stage copy | r001 (must-pass prose, weighted_mean) | 0.9755 | 0.9755 | not zeroed, correct |

Runs 1-4 are `oracle` mode with the judge replaced; runs 5-7 use a scratch copy of
the stage task with `deliverables_05/judge.toml [scoring] aggregation` switched to
`all_pass`. Echo vs oracle: two `--dry-run` outputs diffed, 50/50 criteria with
identical weights and aggregation, 5 buckets each (12/12/12/12/2).

## Per check

### (1) per-criterion weight and group weights

Group weights in `tests/reward.toml`: 0.2823 + 0.258 + 0.24 + 0.1931 + 0.0266 = 1.0000
(both the 50-criterion corpus copy and the 47-criterion stage copy). The script reads them
through `group_weight_in_total()` (judge_emulate.py:421-425), the same
`spec.weights.get(name, 1.0)` lookup as `runner._score_layout`.

The premise as written ("per-criterion weight = criterion weight x group weight") is not
rewardkit's formula. rewardkit's group score is `sum(w_c * v_c) / sum(w_c)` over the
group's criteria (reward.py `_weighted_mean`), rounded to 4 dp per group
(runner.py `_score_group`), then `sum(g_score * gw) / sum(gw)` at the root, rounded to 4 dp.
So a criterion's effective share of the total is `(w_c / sum_w_group) * gw`. The script
does not multiply anything: `criteria[].weight` is the raw `[[criterion]] weight` and
`groups[].weight` is the raw `[[reward]] weight`, reported side by side (README section 2
states this correctly). For SVC-PC-29-2-0 the two formulas coincide because every group's
criterion weights sum exactly to that group's weight (0.2823 / 0.258 / 0.24 / 0.1931 /
0.0266, checked on both builds), so `total = sum(w_c * v_c)` up to the 4-dp group rounding.
That equality is a property of this task's authoring, not a guarantee; on a task where
a group's criterion weights do not sum to its group weight, rewardkit renormalises and
the script will follow rewardkit, which is the correct behaviour.

### (2) total = sum of weight x {1 if yes else 0}

Holds through rewardkit: `Binary.normalize` maps yes -> 1.0 else 0.0
(`parse_judge_response`, judges.py:239-289), `negate` flips it, and
`aggregate_scores` does the weighted mean. Runs 1-4 confirm numerically: run 3's
lost weight 0.2084 gives 1 - 0.2084 = 0.7916, which is what the script printed.

### (3) all_pass and must-pass gating

`aggregate_scores` returns 0.0 for a group when any member has `value <= 0` under
`all_pass` (reward.py:52-53). The script reaches it unchanged via `Reward.score`
(judge_emulate.py:547 -> runner `_score_group`). Run 5 shows one failed member
zeroing its group (d05 -> 0.0, total 0.9734 = 1 - 0.0266).

"Must-pass" prose: `grep -rin "must.pass"` over rewardkit 0.2.0 and 0.2.1 source returns
zero hits. Neither version gates on it. The script does not either: it lists such
criteria under `must_pass_prose_but_unenforced` (judge_emulate.py:403-413, 435-436) and
otherwise scores them as ordinary weighted_mean members. Run 7: r001 (a must-pass-prose
criterion) failing gives 0.9755, not 0.0. Matches rewardkit.

### (4) echo vs oracle weighting

`bucket_criteria()` (judge_emulate.py:205-224) changes only the file scope in echo
mode; `grade_reward()` (352-353, 366) slices the same `reward.weights` list either way.
Dry-run diff: identical per-criterion weights, group weights and aggregation across
all 50 criteria.

### (5) reproducing a real reward-details number

Scope limit, not a script defect. The named file
`/root/qc/in/dataos-cr-batch1-returns/SVC-PC-29-2-0__v69265__opus5__reject.json` is a
COMPREHENSIVE_REVIEW record: `evaluations[]` carries only id / run_id / status / agent /
model, no `reward_details`, and no return file in that directory or in
`dataos-cr-2026-09-18/` carries a per-criterion vector (searched all 25 files for
`reward_details`, `reward-details`, `"criteria": [`; hits are prose mentions inside the
review text). The vector lives in DataOS's `verifier/reward-details.json`, which was not
returned.

What the review text does state, and what the script reproduces:

- eval_471921 reward 0.744; the review lists failed criteria r007, r009, r037, r041,
  r047-r050 (gpt56sol review) and r030/r036/r040 "costing it 0.068" (opus review).
  Run 3 on the graded build: 0.7916. Residual to 0.744 is 0.0476, consistent with two
  more unnamed failures (e.g. 2 x 0.0238 in deliverables_02, or 0.0236 + 0.024); the
  review does not name them, so the vector cannot be completed from the returned files.
- The review's two arithmetic claims are reproduced exactly: removing the six
  instruction-untraceable criteria moves the total by 0.1071 (run 4 minus run 3 =
  0.8987 - 0.7916 = 0.1071; review: "0.744 would be ~0.851"), and r030 + r036 + r040 =
  0.024 + 0.024 + 0.02 = 0.068 on the graded build.

Both runs 3 and 4 had `MATCH judge_emulate == hand: True`.

## Two things a session using this script must know (not arithmetic defects)

1. **Build mismatch.** The corpus copy the script defaults to
   (`/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready/SVC-PC-29-2-0`, 50 criteria,
   r013 = 0.0218) is NOT the build DataOS graded. The review cites 47 criteria, r024 /
   r025 / r035 absent, and weights 0.0238 / 0.024. `/root/qc/stage/SVC-PC-29-2-0` matches
   that (d02: 11 criteria at 0.0238 + r023 at 0.02; d03: 10 at 0.024). Any comparison to a
   DataOS number must pass the stage path as the task argument. `/root/qc/batch-01/` holds
   a third variant (d02: 8 criteria). The README's dry-run section names only the corpus
   copy.
2. **rewardkit version.** `tests/test.sh` installs `harbor-rewardkit[all]` unpinned; PyPI
   serves 0.2.1 today, local venv has 0.2.0. Diffed 0.2.1's `reward.py` / `runner.py`
   against 0.2.0: `aggregate_scores` weighted-mean, all-pass, any-pass, required-pass and
   threshold are unchanged (aggregation names normalised `_` -> `-`, `weighted-sum` added,
   finite / non-negative weight validation added); group and root aggregation still round
   to 4 dp (`_aggregate_named`, `_evaluate_node`); `[judge] weight` is still accepted
   (`JudgeConfig.weight`, default 1.0). No arithmetic drift for this corpus. `rewardkit_pin.py`
   already exists to pin it.

## Files read

- `/root/qc/tools/judge_emulate.py`, `/root/qc/tools/_qc_common.py`, `/root/qc/tools/judge_emulate.README.md`
- `/root/venv/lib/python3.*/site-packages/rewardkit/{reward,runner,judges,models}.py` (0.2.0)
- harbor-rewardkit 0.2.1 wheel, same four modules (downloaded to scratchpad)
- `/root/qc/in/dataos-cr-batch1-returns/SVC-PC-29-2-0__v69265__opus5__reject.json` and `__v69284__gpt56sol__reject.json`
- `/root/qc/tools/reports/_judge_emulate_dryrun_29-2-0.json`
- `tests/reward.toml` and five `judge.toml` for the corpus copy and the stage copy
