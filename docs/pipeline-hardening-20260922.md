# Pipeline hardening proposal — lessons from the 30-task fix session (2026-09-22)

Derived from fixing 30 tasks in one session (19 from the QCR CSV batch, 11 from the v6/v7 rework
drop). Every claim below is measured against real artifacts in this repo, not inferred.

---

## 1. Headline finding: the gap is wiring, not coverage

| Tier | Count |
|---|---|
| Deterministic checks that exist in `deterministic-checks/` | **~90** |
| Checks wired into `run_all.py` | **~17** |
| Checks the fix skill (`skills/ekw/fix-task-from-review/SKILL.md`) actually mandates | **3** |

The fix skill is the workflow that ran 30 times this session. It mandates `harbor_rubric_gate.py`,
`reward_signal_gate.py`, and `container_build_check.py` (plus `oracle_golden_check.py`). Everything
else in the folder — including checks purpose-built for the exact defects that shipped — was never
invoked by any of the 30 fix runs.

**This is the single highest-leverage thing to change.** We do not primarily need new checks; we
need the ones we have to run, and to not silently skip.

---

## 2. The proof: a purpose-built check skipped 35% of the corpus

`verifier_requirements_pin_mismatch_check.py` exists specifically to catch drift between
`environment/verifier-requirements.txt` and the vendored `requirements.txt`. Its own docstring
names the exact drift — `litellm 1.83.7 vs 1.93.0`, `pypdf 6.4.2 vs 6.15.0` — **that shipped in
task_LGL-168, failed dependency install, and scored reward 0.0 on every agent run.**

It missed it because of one line:

```python
FILE_B_CANDIDATES = ("tests/__verifier_lib/requirements.txt",)   # double-underscore only
```

28 of the 79 shipped v7 tasks (**35%**) — the entire LGL legal batch plus task_78/79/81/86/97/98 —
ship the *single*-underscore `tests/verifier_lib/`. For all 28, the check reported `skip`, not
`fail`. `container_build_check.py` had the identical blind spot in its `genre()` function: it
returned `"unknown"`, skipped every native-genre build assertion, and printed **`pass`** on a
package that could not build at all.

### Measured blast radius (after fixing both, full 79-task sweep)

**12 of 79 shipped tasks fail the build gate right now:**

| Failure | Tasks | Consequence |
|---|---|---|
| Requirements drift | task_97, task_98, task_LGL-168, task_LGL-181 | Dependency install fails → **reward 0.0**, `total_verifiers: 0` |
| `verifier-requirements.txt` missing + no `VERIFIER_VENV_DIR` | task_108, task_12, task_130, task_133, task_136, task_155, task_2, task_94 | DataOS build error before grading starts |

task_133 and task_LGL-168 were fixed in this session's rework batch. **The other 10 are live and
unfixed.** A reward-0.0 run is invisible in an aggregate score report — it looks like a hard task,
not a broken one.

**Both blind spots are fixed** (`container_build_check.py`, `verifier_requirements_pin_mismatch_check.py`);
all 131 existing tests still pass, and no double-underscore or rewardkit task regressed.

---

## 3. Defect taxonomy from the 30 tasks, by frequency

| # | Class | Tasks | Deterministic? |
|---|---|---|---|
| 1 | **`check_formula_provenance.py` defects** — band collisions with unrelated values, cell-vs-figure counting, hop-limit caps, disguised constants, unstated requirements | 9/30: 559, 218, 574, 462, 470, 390, 388, 348, 145 | **Yes** |
| 2 | **Golden fails its own rubric** (definitionally major) | 8/30: 101, LGL-155, LGL-150, LGL-140, LGL-161, 1, 120, LGL-168 | **Yes** (oracle already reports it) |
| 3 | **Infrastructure zero / build break** | 5+: LGL-168, 133, 559, 549, 390 + 10 live | **Yes** |
| 4 | **Extraction truncation** — judge grades a cut-off document | 4/30: 139, LGL-126, LGL-150, 48 | **Yes** |
| 5 | **Non-reproducible oracle** — same bytes, different reward | 4/30: 120, LGL-168, LGL-161, LGL-131 | **Yes** (2-run diff) |
| 6 | **Source-blindness (G1)** — judge asked to verify a file it never got | 3/30: 157, LGL-131, 101 | **Mostly** |
| 7 | **Mutually inconsistent siblings (G4)** | 4/30: LGL-161, 390, LGL-168, 139 | Partly |
| 8 | **False credit** — fabricated/empty work scores at or above golden | 3/30: LGL-155 ($75k fabrication scored **1.0, above the golden**), 462, 388 | Partly |
| 9 | **Compound cascade** — one miss fails N criteria | 1/30: 538 (1 miss → 8 criteria, all 5 runs identical 0.6195) | **Yes** (score-identity signal) |
| 10 | **Packaging defects** | 13/30 | **Yes** |

Classes 1–5 and 9–10 are **fully deterministic** and account for the large majority of real defects.

---

## 4. Proposed implementations, ranked by (frequency x severity x determinism)

### P0 — wire what exists (no new code)

**P0.1 — Make the fix skill's Step 4 run the check registry, not 3 checks.**
Replace the three hardcoded invocations with `run_all.py --root <package>`, plus the three gates.
Add to `run_all.py` the checks that map to this session's defect classes and are currently
unwired: `source_truncation_check`, `xlsx_extraction_budget_check`,
`judge_scope_under_inclusion_check` (G1), `sibling_criterion_asymmetry_check` (G4),
`compound_criterion_check` (G7), `pinned_value_prescreen_check`, `oracle_reward_details_audit`,
`harness_fragility_check`, `verifier_requirements_pin_mismatch_check`, `weight_aggregation_check`.

**P0.2 — `skip` and `unknown` must never render as success.**
The task_LGL-168 ship happened because "I could not evaluate this" printed as `pass`. Any check
returning `skip`/`not_applicable` for a *structural* reason (genre unknown, expected file absent)
should surface as `warn` at minimum and block at ship time until explicitly dispositioned. This is
a reporting-convention change across the folder, cheap and high value.

**P0.3 — Run `eval_evidence_sweep.py` at the *start* of every fix, and feed it to the fixer.**
This tool already computes exactly what all 30 agents hand-rolled by reading `reward-details.json`
files one at a time: oracle criteria scoring <1.0 (class 2), criteria failing ≥N% of agent runs
(classes 1, 7), fatal whole-task zeros (class 3), and the platform QC/comprehensive-review verdicts.
The fix skill never mentions it. Making its output the mandatory Step 1 input would have front-run
most of this session's manual discovery and made every "confirmed finding" cite an artifact by
construction.

### P1 — new deterministic checks for the top cluster

**P1.1 — `formula_provenance_lint` (the single biggest win: 9/30 tasks).**
The per-task `check_formula_provenance.py` copies carry their bands as literal Python data. A
shared linter can read them statically and assert:
- **Band-collision scan**: for every band, scan all `environment/data/*` input values *and* the
  golden for any unrelated value falling inside it. task_348's report shows this was done by hand
  ("all 169 distinct input values scanned, none in band") — codify it. Directly catches 218, 559,
  462, 470.
- **Hop limit** ≥ 8 when following presentation links (catches 390's 3-hop bug).
- **Distinct-figure counting**, not per-cell counting (catches 574).
- **Disguised-constant detection** (`=184627.68*1`) (catches 388).
- **Instruction grounding**: if the checker requires a construct (range aggregation, ≥N formulas)
  that appears nowhere in `instruction.md`, flag it (catches 559).

**P1.2 — `formula_provenance_conformance_suite`: a fixture corpus, not a lint.**
Ship ~8 synthetic workbooks (all-typed; all-formula; index-counter column; scenario-input grid with
adjacent consuming formula; presentation restatement of one derived figure; rubric-parroting
hardcoded answers; `=X*1` wrapper; legitimately-transcribed source figures) and assert each task's
checker gives the expected verdict on each. This is a unit-test suite for a file we currently
copy-paste per task and never test. Every one of the 9 defects in class 1 is a fixture that would
have failed.

**P1.3 — `oracle_reproducibility_check`.**
Run the oracle twice (or read the existing 3-sample votes) and diff per criterion. Any criterion
with a split vote or a cross-run delta is UNSTABLE. The v7 handoff already describes
`_oracle_merge.py` computing exactly this and calls the unstable list "the answer to why DataOS
fails at random" — it just isn't a gate. Catches class 5 (4/30) for near-zero marginal cost.

**P1.4 — `timeout_headroom_check`.**
`criteria x samples x est_seconds_per_call` vs `task.toml`'s `timeout_sec`. All 79 task.tomls carry
`timeout_sec = 3600.0` and the verifier judges serially; task_157 and task_LGL-160 both produced
rewardless `VerifierTimeoutError` runs. Trivial arithmetic, batch-wide defect.

**P1.5 — `golden_band_containment_check`.**
For every structured numeric band, assert the golden's own value falls inside it. task_120 shipped
a criterion whose passing band was 27–40% while the golden's own value was 24.1% — **no human
reviewer caught it**; it surfaced only from a full-rubric sweep. Fully deterministic wherever bands
are structured data.

**P1.6 — `package_shape_check` (ship gate).**
Assert: zip root is exactly one `task_<id>/`; `reports/<task>_{TRACE,DECISIONS}.json` present
*inside* the package; no `__pycache__`/`.DS_Store`/`.round*`; file list diffed against the working
round. In this session 11 of 19 round-1 zips shipped without their ledger, one shipped with no
wrapper folder, and two shipped with a `task_files/` root — all caught only by a manual pass.

### P2 — genre-aware and cheap

- **`legal_citation_consistency_check`** (LGL genre, ~1/3 of the corpus): TOA-vs-body set difference
  is pure set arithmetic (caught task_LGL-161's Whitman/Lujan/Sorenson mismatch); and a cited
  opinion whose year postdates the document's own date is a deterministic flag (caught
  task_LGL-160's April-2025 memo citing an August-2025 opinion).
- **`no_discrimination_check`**: criteria passing 100% across every run *and* the oracle carry no
  signal. task_462 and task_470 each had 33 and 18 LLM criteria at 100%, leaving a single 10%
  deterministic check as the only thing moving the score.
- **`score_identity_check`**: identical rewards across runs from different model families indicate a
  cascade, not calibration (task_538: all five runs at exactly 0.6195).

---

## 5. Process changes to the fix skill

1. **Research before escalating a specialized-domain finding.** This session ended with 3 tasks
   "needing legal input." On research, 2 resolved in minutes against primary sources (Md. CJP
   §4-402's two distinct thresholds; *Mount Vernon Properties v. BB&T*, 170 Md. App. 457 (2006)),
   and 1 revealed a genuine scope cascade. The skill should require a primary-source pass first,
   with the citation recorded in `DECISIONS.json`, and escalate only on genuine ambiguity.

2. **Add a scope-cascade test to Step 2.** task_LGL-140's narrow fix was clear, but correcting the
   damages figure moved the case under Maryland's $30,000 District Court ceiling — invalidating the
   forum, the jury demand, and the loss-of-exemption theory. Before editing a load-bearing figure,
   enumerate its dependents (grep the golden for the figure and everything derived from it). If the
   fix changes forum/jurisdiction/count structure, it is a rewrite, not a fix — stop and report.

3. **Findings must cite artifacts, not prose.** Every `confirmed` entry in `TRACE.json` should name
   a criterion **and** a specific run's verdict. This is mechanically checkable, and it is the rule
   that actually separates true from false positives — more reliably than reviewer identity. This
   session confirmed codex-only majors are frequently false (task_1 rejected 5; also 549, 574, 145,
   48, 322, LGL-135), **but also that claude-code was wrong twice on task_LGL-160**. Neither
   reviewer's verdict is evidence; the per-criterion run data is.

4. **Operational guardrails for fix agents.** Multiple agents burned resources spawning nested
   "wait for the Step 6 review" sub-agents and returned `"still waiting"` as a terminal state,
   requiring manual kills. The skill should forbid Agent-tool delegation for Steps 5/6 inside a
   per-task fixer and state that "waiting on a background job" is never a completion.

---

## 6. EXECUTED — what actually shipped (2026-09-22)

### Bug fixes to existing checks

| Fix | Effect |
|---|---|
| `container_build_check.py` — genre detection accepts both `tests/__verifier_lib/` and `tests/verifier_lib/`; drift message states the reward-0.0 consequence | Was printing `pass` on unbuildable packages for 35% of the corpus |
| `container_build_check.py` — an **unknown genre is now `fail`**, not a silent pass | "I could not evaluate this" no longer renders as success |
| `verifier_requirements_pin_mismatch_check.py` — `FILE_B_CANDIDATES` covers both spellings | Was reporting `skip` on the 28 tasks it was built to protect |
| `source_truncation_check.py` — uses the shared helper + `importlib`, so it imports each task's lib under its real package name | Was reporting `error`/`no_verifier_lib` on **all 47** double-underscore tasks; the extraction-truncation defect class (4/30 tasks) had never been checked on 59% of the corpus |
| `verifier_executability_check.py` — same treatment | gold_replay had never run on the double-underscore tasks |
| `ekw_verifier_json.py` — new shared `VERIFIER_LIB_DIR_NAMES` / `verifier_lib_dir()` / `verifier_lib_module_name()` | The same one-line assumption was found **three separate times** in one session, in both directions. Now there is one place to be right. |

**What the truncation fix immediately found**, now that it runs corpus-wide: 3 shipped tasks with
live truncation defects — **task_32 (21 criteria), task_157 (12), task_146 (5)**.

### New checks (each with tests, calibrated on real corpora)

- **`package_shape_check.py`** — 6 detectors; 29/29 hand-fixed zips pass; every detector proven
  to fire on a fixture. Sweep of the v7 batch: **79/79 packages lack the TRACE/DECISIONS ledger**
  (so the whole batch would fail G8 on re-verification), `task_120` ships `__pycache__`. Its
  opt-in drift mode reproduced both known stale-sibling reverts (task_133, task_139) and found
  **three more nobody had spotted: task_10, task_111, task_35**.
- **`timeout_headroom_check.py`** — `--seconds-per-call` derived from **87 real runs** (min 8.6 /
  median 23.7 / p90 46.0 / max 61.2), not assumed. Rediscovers task_157 (0.72x), task_LGL-168
  (0.79x), task_LGL-160 (1.19x). Confirms the 3600s cap is a batch-wide template issue.
- **`oracle_reproducibility_check.py`** — **rediscovers all four known non-reproducible criteria**
  unprompted (task_120 `v6c`, task_LGL-168 `v9`, task_LGL-161 `v14`, task_LGL-131 `v13`) and
  surfaces 13 more previously unnamed. Independently re-verified here: task_120 `v6c` with the
  exact `1T/2F` vs `3T/0F` signature. Gate-ready.
- **`formula_provenance_lint.py`** — the top cluster (9/30 tasks). Static `ast` parse plus a
  restricted replay of only the checker's CONFIG block, so bands built by comprehension resolve
  without ever executing the criterion body. **9/9 known-bad baselines flagged, 8 of them by
  their own mechanism.** Two gate-ready detectors (`band_collision`, `hop_limit_too_low`) and
  five report-only. Independently re-verified here: **0 gate-ready findings across all 79 shipped
  v7 packages** (the 42 `warn`s are all the report-only coverage-floor signal), and all four
  spot-checked pre-fix baselines fail with the expected detector mix. The agent reported one
  honest **miss** — task_388 — because that task's checker genuinely *does* carry the
  identity-wrapper guard, so the detector correctly stays silent rather than being tuned into a
  false catch; worth re-reading task_388's fix note.

### Wiring

- `run_all.py`: **17 → 23 checks**, with a second CLI shape (`POSITIONAL_ROOT_CHECKS`) added for
  `compound_criterion_check` / `pinned_value_prescreen_check`, each CLI confirmed by running
  `--help` rather than trusting the docstring.
- **Two checks deliberately excluded as LLM-backed** (`judge_scope_under_inclusion_check`,
  `sibling_criterion_asymmetry_check`) — they report `error` for every task without a backend,
  which would dilute the deterministic signal. Documented in `LLM_BACKED_NOT_RUN`.
- `fix-task-from-review/SKILL.md`: Step 1 now opens with `eval_evidence_sweep.py`; Step 4 gains
  **5b, run the whole registry**, with "a `skip` is not a pass"; Step 7 gains the
  `package_shape_check` ship gate; plus the artifact-citation rule, the research-before-escalate
  rule, the scope-cascade test, and the synchronous-Steps-5/6 guardrail.

### One claim retracted, on evidence

I initially reported that `verifier_executability_check`'s gold_replay deterministically
rediscovered the golden-fails-own-rubric defects. **That was wrong and is now documented in the
check's own docstring.** Run against a package directory it stages only
`solution/golden_outputs/`, so any criterion sourcing anything else fails as `required file
missing` — 69 of 79 packages "fail", with rewards as low as 0.48, none of it real. task_120's
flagged criterion is `v15 (required file missing)`, *not* the `v6c` the session actually found;
the matching counts were coincidence. gold_replay reliably catches the mechanical layer (crash,
bad import, unresolvable source) and nothing more. The real detectors for that class remain
`oracle_golden_check.py` and the new `oracle_reproducibility_check.py`.

**Test suite: 131 → 257 passing, zero regressions.**

## 7. Previously applied earlier in the session

- `container_build_check.py` — genre detection now recognises both `tests/__verifier_lib/` and
  `tests/verifier_lib/`; drift message states the reward-0.0 consequence.
- `verifier_requirements_pin_mismatch_check.py` — `FILE_B_CANDIDATES` covers both spellings.
- Verified: task_LGL-168's pre-fix baseline now correctly reports `fail` on both checks (was
  `pass` / `skip`); no regression on double-underscore or rewardkit tasks; 131/131 tests pass.

**Immediate follow-up:** 10 live tasks fail the corrected build gate and are unfixed —
task_97, task_98, task_LGL-181 (drift → reward 0.0) and task_108, task_12, task_130, task_136,
task_155, task_2, task_94 (missing requirements + `VERIFIER_VENV_DIR`).
