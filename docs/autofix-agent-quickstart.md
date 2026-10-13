# Auto-fix agent quickstart

Last checked: 2026-10-02 against main at `ad9511f`. Back to the [start page](../README.md) or the [doc index](README.md).

For engineers building an auto-fix agent for tasks that an outside QC reviewer rejected. Sections 1 to 3 explain the loop. Sections 4 and 5 show commands that were run on a fresh clone (Windows, Python 3.12, Git Bash) and what they printed. Anything not run is marked "not verified".

## 1. What it does, in six steps

A rejected task is a folder (prompt, source files, golden answer, rubric). A Claude agent edits the rubric, golden and prompt in that folder to close each finding. Local checks, not the agent, decide when it is done. The lane runner [`svc_v7_lane_runner.sh`](../svc-pc-pipeline/sandbox_root/svc_v7_lane_runner.sh) is the loop. A lane is one worker with its own Claude Max login that fixes one task at a time (section 6).

1. **Collect feedback.** Save the DataOS return zip. [`svc_build_directed_briefs.py`](../svc-pc-pipeline/tools/svc_build_directed_briefs.py) writes one brief per task with every finding from every round.
2. **Fix.** `claude -p` runs inside the task folder with the brief plus the [fix rules](../svc-pc-pipeline/tools/svc_fix_method_rules.md).
3. **Oracle.** The golden answer is scored against the new rubric by [`judge_emulate.py`](../svc-pc-pipeline/tools/judge_emulate.py). It must score 1.0, twice.
4. **Re-grade.** [`svc_eval_regrade.py`](../svc-pc-pipeline/tools/svc_eval_regrade.py) re-scores the real solver answers DataOS saved. A correct answer that lost points must now pass; a hollow answer that passed must now fail.
5. **Verify.** A second agent audits every criterion and ends with `VERDICT: READY-TO-RESUBMIT` or `NOT-READY`. [`svc_coverage_trace.py`](../svc-pc-pipeline/tools/svc_coverage_trace.py) checks that every instruction requirement maps to a criterion. Any failure goes back to step 2 with the exact finding, up to 10 attempts.
6. **Ship.** [`svc_build_upload_zip.py`](../svc-pc-pipeline/tools/svc_build_upload_zip.py) builds the gated zip, DataOS grades it, [`svc_record_return.py`](../svc-pc-pipeline/tools/svc_record_return.py) records the result. A task passes when all four Answer Check reviews of the pipeline report no major finding (SOP section 6b).

A separate no-LLM layer, `svc_autofix_scan.py` / `svc_autofix_apply.py` / `svc_autofix_report.py`, applies mechanical fixes only (section 5).

## 2. Inputs and outputs

**Input A, DataOS return zip** (the Dataset with runs download, `<bundle>_with_runs.zip`). Per task: four Answer Check review JSONs (SOP section 6b), each a list of findings with a check id (1.1 golden wrong, 1.3 ambiguous prompt, 1.4 rubric too strict, 1.5 requirement nothing grades, 1.6 leak, 1.7 inconsistency, 1.8 packaging), a severity (a major blocks), a justification and a suggested fix. The zip also holds each solver answer with its per-criterion scores. There is no written schema; the parsers read the JSON out of the review text.

**Input B, human QC feedback.** The [TP/FP skill](../automation/tp-fp-classification/SKILL.md) (TP/FP: true positive or false positive, that is, whether a QC finding is a real task defect) turns it into one workbook per task, `task_<id>_qc_validation.xlsx`, with columns `QC Issues Task ID`, `Defect Class`, `Auto-Verdict`, `Fix Title`, `Issue Description`, `Evidence Reference (path)`. `format_convention` and `pipeline_packaging` are auto-applied; `content_substance` and `design_intent` become a proposed diff for a human; `dataos_format_artifact` and `agent_capability` need no action.

**Output, a fixed task package** that must have:
- `instruction.md` and `tests/task_prompt.txt`, identical, with no expected values in them;
- `environment/initial_workspace/` (sources) and `solution/` (golden);
- `tests/deliverables*/judge.toml` with the rubric, at most 15 criteria per folder, expected values only here;
- LF line endings; a golden that scores 1.0; difficulty not lowered.

## 3. How the prompt is built, and where to change a rule

| Mode | Prompt is | Defined in |
|---|---|---|
| rebuild (first pass) | the task's brief + requirement walk + rules | `PROMPT=` in the runner |
| fix (targeted) | four steps (class, recompute, requirement walk, re-audit) + the failing finding + rules | `PROMPT=` in the runner |
| decide (stuck task) | per failing criterion choose REWRITE, DROP, KEEP or FIX-GOLDEN, with a cited source | `decide_prompt()` in the runner |
| verify | seven audit checks, ends in a verdict line | `VPROMPT=` in the runner |

**To change a rule, edit [`svc_fix_method_rules.md`](../svc-pc-pipeline/tools/svc_fix_method_rules.md) and bump `METHOD_VERSION` on line 1.** Every prompt embeds that file. The zip builder and the bundler refuse any task whose verify record was made under an older version, so old work is re-verified before it can ship. Runners already running keep the old text until restarted, and briefs must be rebuilt. To change how the agent is told to work, edit the prompts in the runner. In the code on main, the runner exists twice ([`tools/`](../svc-pc-pipeline/tools/svc_v7_lane_runner.sh) and [`sandbox_root/`](../svc-pc-pipeline/sandbox_root/svc_v7_lane_runner.sh)) and the copies differ.

## 4. How a fix is verified: commands that were run

From `svc-pc-pipeline/` unless noted. `test_svc_eval_regrade_gate.py` and `test_judge_emulate_error_scores.py` fail if run from `tools/`.

| Command | Result |
|---|---|
| `python tools/svc_autofix_apply.py --selftest` | `[selftest] OVERALL: PASS` (7 checks, including a planted answer-key leak that the guard refuses) |
| `python tools/test_eval_counting.py` | `Ran 29 tests ... OK` |
| `python tools/test_svc_bundle_upload.py` | `26/26 passed` |
| `python tools/test_svc_eval_regrade_gate.py` | `ALL PASS` |
| `python tools/test_judge_emulate_error_scores.py` | `ALL PASS` |
| `python tools/svc_coverage_trace.py list ../pipeline/data/sample_corpus/task_11` | printed 7 requirement units, exit 0 |
| From `deterministic-checks/`: `python run_all.py --all --root ../pipeline/data/sample_corpus --out-dir <dir>` | 23 checks in 12 s, exit 1 because `task_11` has 4 fails (`judge_panel_size`, `criterion_condition_count`, `invention_detection_input`, `compound_criterion`), 1 flag, 1 warn |
| `python tools/svc_prefilter.py ../pipeline/data/sample_corpus/task_11` | `FAIL: no tests/deliverables*/judge.toml found`. Expected: the only sample is the older `verifier.json` shape, not the `judge.toml` shape the loop works on. |

Not verified: the lane runner, the pool, the oracle (`judge_emulate.py oracle`, which needs a `judge.toml` package, `harbor-rewardkit` 0.1.7 and the `claude` CLI), `svc_eval_regrade.py regrade`, `svc_build_upload_zip.py`, the bundler and the DataOS upload. On Python 3.12, `tools/test_apply_plan_fake_fix.py` fails with `TypeError` (`Path.read_text(newline=)` needs 3.13, which the sandbox uses).

## 5. A minimal run you can repeat (verified)

This runs the no-LLM layer end to end on synthetic data and the one sample task in the repo. It writes only into a throwaway `_demo/` folder. Save this as `make_demo.py` and run it from `svc-pc-pipeline/`:

```python
import shutil, openpyxl
from pathlib import Path
D = Path("_demo").resolve()
shutil.rmtree(D, ignore_errors=True)
(D / "validation").mkdir(parents=True)
shutil.copytree("../pipeline/data/sample_corpus/task_11", D / "corpus" / "task_11")
wb = openpyxl.Workbook(); ws = wb.active
ws.append(["QC Issues Task ID", "Defect Class", "Auto-Verdict", "Fix Title", "Issue Description", "Evidence Reference (path)"])
ws.append(["task_11", "format_convention", "true_positive", "Resync prompt copy", "tests/task_prompt.txt differs from instruction.md", "instruction.md"])
ws.append(["task_11", "content_substance", "true_positive", "Criterion over-specified", "Pins one method the prompt leaves open", "tests/verifier.json"])
ws.append(["task_11", "agent_capability", "false_positive", "Solver ran out of turns", "Not a task defect", "evals/"])
wb.save(D / "validation" / "task_task_11_qc_validation.xlsx")
```

```bash
D=$(python -c "from pathlib import Path;print(Path('_demo').resolve())")
python tools/svc_autofix_scan.py --validation-dir "$D/validation" --rollup "$D/none.json" --out "$D/scan.json"
python tools/svc_autofix_apply.py --scan "$D/scan.json" --search-root "$D/corpus" --out "$D/apply.json" --diff-dir "$D/diffs"
python tools/svc_autofix_report.py --scan "$D/scan.json" --apply "$D/apply.json" --out "$D/report.xlsx"
```

Results: scan buckets 1 mechanical, 1 content_review, 1 no_action. Apply: `1 applied` (it created `tests/task_prompt.txt` from `instruction.md` in the copy), and one proposed-diff file for the content finding. Report: `fixed: 1, flagged for human: 1`. The three paths must be absolute and inside `svc-pc-pipeline/`, or the scripts crash with `ValueError: ... is not in the subpath`.

## 6. What is specific to our setup, and what to build instead

| Ours (do not copy) | Portable idea |
|---|---|
| Paths `/root/qc`, `/root/ekwqc/...`, `/root/venv`, set at the top of each script | One config file or env vars for corpus, work dir and python |
| One Claude Max login per lane (`/root/.claude-<letter>`), a pool that polls a queue every 2 minutes | Any worker pool that runs one agent per task and releases the task on a rate limit |
| `claude -p --model opus --permission-mode dontAsk --allowedTools ...` | Any agent call that edits files in a task folder with a fixed tool list |
| A DataOS browser session to upload and download returns; no API | Whatever hands the agent the review findings and the solver answers |
| Tracker sheets and "freeze lists" so lanes skip other people's tasks | A claim table in your own store |
| The pass rule (all four Answer Check reviews at 0 majors) and the grader pin (`rewardkit` 0.1.7) | Keep both: they define "done" and what "scores 1.0" means |

## 7. The ten files to open first

| File | One line |
|---|---|
| [`svc_fix_method_rules.md`](../svc-pc-pipeline/tools/svc_fix_method_rules.md) | The fix and verify rules, R1 to R7, versioned |
| [`svc_v7_lane_runner.sh`](../svc-pc-pipeline/sandbox_root/svc_v7_lane_runner.sh) | The loop and every prompt |
| [`svc_build_directed_briefs.py`](../svc-pc-pipeline/tools/svc_build_directed_briefs.py) | Builds the per-task brief from DataOS returns |
| [`judge_emulate.py`](../svc-pc-pipeline/tools/judge_emulate.py) | Oracle: scores the golden against the rubric |
| [`svc_eval_regrade.py`](../svc-pc-pipeline/tools/svc_eval_regrade.py) | Re-scores real solver answers against the fixed rubric |
| [`svc_coverage_trace.py`](../svc-pc-pipeline/tools/svc_coverage_trace.py) | Requirement-to-criterion map check |
| [`svc_build_upload_zip.py`](../svc-pc-pipeline/tools/svc_build_upload_zip.py) | The gated zip |
| [`svc_autofix_apply.py`](../svc-pc-pipeline/tools/svc_autofix_apply.py) | Mechanical fix recipes plus the answer-key leak guard |
| [`svc-pc-pipeline/README.md`](../svc-pc-pipeline/README.md) | The pipeline step by step |
| [`QC-SOP-first-run.md`](QC-SOP-first-run.md) | The gate every task clears (section 6a) |

Open PRs change parts of this: [#78](https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/78) (fix rules to v8.2, runner `--first-grade`), [#80](https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/80) (faster re-grade, no false usage-limit releases), [#72](https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/72) and [#74](https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/74) (runner timeouts, judge-timeout handling). None is merged, so this page describes main.
