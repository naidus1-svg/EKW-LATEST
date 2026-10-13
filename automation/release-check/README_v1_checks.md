# Release check: the three checks, one row per task, for the manager

Written 2026-10-08 (US Eastern), job B12_RELEASECHECK. New folder; every other file under final/ is unchanged.

## What it is, in plain words

A script that runs on the sandbox AFTER DataOS has finished the evaluation runs (oracle = the reference answer, Codex and Terminus = the AI solvers, empty-answer run = a submission with nothing in it) and the four answer-check-v11 reviews (the review prompt that is DataOS saved prompt id 557; see README.md in this folder). It reads the DataOS export of the batch and prints one row per task. Nothing is stored on GitHub in step 1. It is the table a manager reads before the batch goes to TFRL (the outside QC team).

The three checks (they are the three of "Rule A", final/v13_proposal/RULES_BY_HAND.md):

| check | question | yes means |
|---|---|---|
| 1, c_fail | Is there a grading rule that every valid solver attempt loses while the reference answer earns it? | The rule, or the reference answer, may be wrong. Author fixes one and says which. Rule: reward-details value 1.0 in the oracle run and 0.0 in every valid attempt (same rule as work/EXECTRUTH/exectruth.py). |
| 2, answer-check-v11 | Does the answer-check-v11 review, after the verifier checked each item, say REJECT? | final/step2/pass_rule_v11.py: the empty answer earned reward above 0, or a verifier-CONFIRMED item is material (EKW: 0.05 or more of total weight; SVC: one of the 3 heaviest criteria). |
| 3, manager gate | Does final/step3/gate.py say SEND? | yes = HOLD. CANT_JUDGE is not a yes: it means an input is missing and it is named. |

Overall value per task: **HOLD** if any check is yes. **NEEDS INPUT** if no check is yes and at least one is not computable. **RELEASE** if all three are computed and none is yes. No cutoff is applied; the manager reads the counts.

One difference from Rule A: Rule A counts CANT_JUDGE as a hold. Here CANT_JUDGE becomes NEEDS INPUT, because the V11B1213 run shows it fires on missing files, not on defects (18 of 22 tasks). Use `check3_gate` if you want Rule A's reading.

## Does answer-check-v11 replace the current review?

The script does not decide that. It runs the answer-check-v11 review as check 2, beside check 1 and the gate. The gate still reads the review run row (major counts, fix items, empty-answer reward) from `review.csv`; that file comes from the DataOS run-history export. Check 2 reads the review text itself (`results.jsonl`) and adds the verifier. Both look at the empty-answer reward, so a task can show it in check 2 and in check 3 (rule R3).

## How an operator runs it for a new batch

1. In DataOS, let the batch finish: the oracle, Codex, Terminus and empty-answer runs, then the four reviews written with the review prompt answer-check-v11 (DataOS saved prompt id 557). Export the folder in the layout of work/V11B1213: `results.jsonl`, `runs.csv`, `nop.csv`, `map.csv` (only when reviews ran on QC copies), `newruns/` (index.csv plus `<run_id>.json` and `<run_id>.reward-details.json` per run). Put older runs' per-criterion files in `runs/` or give `--runs-dir`. Put `tasks.csv` (task_id,name,tab) beside them so the sheet name and tab show.
2. Add the step 3 inputs if you have them: `preflight.csv` and `step1.csv` (from final/step1), `review.csv` (the DataOS run-history export), and optionally `history.csv`, `fixcheck.csv`, `tracker.csv`. Column lists are in the header of final/step3/gate.py. Put them in the export folder or give `--gate-inputs <dir>`.
3. Run, on the sandbox, from any folder:
```
python3 -I /root/pq/b12/final/releasecheck_v1/release_check.py <EXPORT_DIR> /root/pq/b12/pkgs:/root/pq/b12/pkgs_b1213:/root/pq/b12/pkgs_dev <OUT_DIR> --spec 557 --run-verifier
```
   `--run-verifier` starts the frozen verifier (one `claude -p` call per task workspace, serial; each call has a 30 minute limit). It is resumable: rerun the same command and finished tasks are skipped. For a batch of 100 tasks start it detached (`setsid nohup ... &`) and read `<OUT_DIR>/step2/verifier_out/done.log`. To reuse earlier verdicts give `--verifier-out <dir>` instead. Without either option check 2 reads NOT COMPUTABLE for every task, on purpose: answer-check-v11 verdicts without the verifier must not be shipped.
   `--spec` and `--version` are your statement of which DataOS review run spec and version the gate should require; the export does not carry them.
4. Read `<OUT_DIR>/release_check.csv`. What to do with each overall value:
   - **HOLD**: return the task to the author with the `message` column (it names the rule ids and weights behind each yes).
   - **NEEDS INPUT**: produce the input named in the `*_reason` and `check3_missing_inputs` columns, rerun, then decide. Do not release on a NEEDS INPUT row without a manager's written reason.
   - **RELEASE**: all three computed, none fired. This is not a statement that the task is sound; see "What it cannot do".
5. Paste into the consolidated sheet as a new tab named `Release check`: open `release_check_tab.csv` (columns task_id, sheet_name, tab, check1_c_fail, check2_v11, check3_gate, overall, message) and paste it at A1. The full file `release_check.csv` has the reasons.

Other outputs in OUT_DIR: `check1_detail.csv` (every rule behind a check 1 yes, with its weight and the runs used), `step2/` (verdicts.csv, fixlist.csv, the verifier workspaces), `gate/` (the staged step 3 inputs and the generated review.csv).

## What it costs

- DataOS credit: none. It reads an export; the evaluation runs and reviews are paid for before it starts (out/COSTMAP.md: about 232 to 316 USD per 100 tasks for four reviews, 208 to 294 for two solver attempts).
- Model calls on the Max plan: only the verifier in check 2, about 1.6 calls per task (final/step2/README.md line 53: 62 calls for 40 tasks), about 160 per 100 tasks. Checks 1 and 3 call no model.
- Time: checks 1 and 3 take seconds. The verifier runs one call after another, up to 30 minutes each.

## What it cannot do yet

- Check 1 with only two attempts is weaker: a rule can lose in both by chance. The backtest behind Rule A (EXECTRUTH) required 3 or more. The script defaults to 2 (`--min-attempts 3` restores the backtest rule) and says "only 2 attempts" in the reason.
- Check 1 needs per-criterion results for the oracle run and the attempts. The V11B1213 export carries them only in `newruns/`; the 108 runs the reviews targeted come as run ids and agent names only (runs.csv). Without those files check 1 is NOT COMPUTABLE. Cost to produce: one reward-details download per run (no DataOS credit measured; not priced in out/COSTMAP.md), plus a third attempt per task at +104 to +147 USD per 100 tasks if you want 3 attempts.
- Check 2 needs the task package folder; a task without one is NOT COMPUTABLE.
- Check 3 is CANT_JUDGE until `preflight.csv`, `step1.csv` and a review run row with its finish and last-edit times exist. Step 1 scripts cost no DataOS credit and no model call; step 1B readers are about 6 Max-plan calls per task (out/COSTMAP.md section 1).
- No check measures prompt ambiguity as TFRL rates it, and none has a measured effect on approval of returned tasks (final/v13_proposal/RULES_BY_HAND.md, "What this does NOT show").

## Test

`python3 -m unittest discover -s /root/pq/b12/final/releasecheck_v1/tests -v`: synthetic fixtures in the export layout plus one end-to-end run on work/V11B1213 without the verifier.
