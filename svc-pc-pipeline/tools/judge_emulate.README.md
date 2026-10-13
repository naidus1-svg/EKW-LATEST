# judge_emulate.py - scoring arithmetic

For a Fable reviewer checking this against a real DataOS `reward-details.json`.
Everything below is rewardkit 0.2.0's own arithmetic (see
`/root/venv/lib/python3.13/site-packages/rewardkit/{reward,runner,judges,models}.py`);
`judge_emulate.py` does not recompute any of it by hand - it builds rewardkit's
own `Reward`/`_RewardGroup`/`_RewardLayout` objects via
`rewardkit.runner._discover_layout` and then calls rewardkit's own
`_score_layout` / `_layout_details` / `aggregate_scores` on them. The only
thing this script substitutes is the judge call itself: a `claude -p`
subprocess (Max-plan CLI, no API key) in place of rewardkit's litellm call to
a hosted model.

## 1. Per-criterion score

For a single criterion `c` with judge response `{"score": raw, "reasoning": ...}`:

```
value = c.output_format.normalize(raw)      # models.py Binary/Likert/Numeric
if c.negate:
    value = 1.0 - value
```

- `Binary.normalize`: "yes"/true/1 -> 1.0, else 0.0.
- `Likert.normalize(points=N)`: `(raw - 1) / (N - 1)`, clamped to [0, 1].
- `Numeric.normalize(min, max)`: `(raw - min) / (max - min)`, clamped to [0, 1].

Every criterion in this corpus's judge.toml files is `type = "binary"`
(confirmed by grep across SVC-PC-29-2-0's 5 judge.toml files), so in practice
`value` is 0.0 or 1.0 here. `passed` in this script's output is `value > 0`
(matches `aggregate_scores`'s own `all_pass`/`required_pass` test, which also
uses `> 0`, not `== 1.0` - a criterion cannot partially-pass and still count
as passing an all_pass gate).

`optional` and `negate` come straight off the TOML row (`[[criterion]]
negate = ...` or `annotations.type` containing "negative"; `optional` from
`annotations.importance` containing "optional") - none of SVC-PC-29-2-0's
criteria set either, so both are `false` throughout.

## 2. Criterion -> group (one `judge.toml` / one `Reward`)

A judge.toml is one `Reward`. Its group score is:

```
weighted_mean:   sum(value_i * weight_i) / sum(weight_i)     [reward.py _weighted_mean]
all_pass:        1.0 if every value_i > 0 else 0.0
any_pass:        1.0 if any value_i > 0 else 0.0
required_pass:   1.0 if every NON-optional value_i > 0 else 0.0
threshold:       1.0 if weighted_mean >= threshold else 0.0   (threshold default 0.5)
```

`weight_i` is each criterion's OWN weight from its `[[criterion]] weight =
...` row (default 1.0 if omitted). This is a within-group weight only - it
has no meaning across groups.

Example, `deliverables_01` (12 criteria, weights 0.0245/0.0236 x 10/0.0218,
summing to 1.0 within that group, `[scoring] aggregation = "weighted_mean"`):
if the golden passes all 12, group score = 1.0. If it fails `r006` (weight
0.0236) and passes the rest, group score = `(1.0 - 0.0236) = 0.9764` - i.e.
`sum(value_i * weight_i)` with `value_r006 = 0` zeroing out just that term,
divided by `sum(weight_i) = 1.0`.

## 3. Group -> total (`tests/reward.toml`'s `[[reward]]`)

```
[[reward]]
name = "reward"
aggregation = "weighted_mean"
weights = { deliverables_01 = 0.2823, deliverables_02 = 0.258,
            deliverables_03 = 0.24, deliverables_04 = 0.1931,
            deliverables_05 = 0.0266 }
```

Same `aggregate_scores` function, one level up: each GROUP's own score
(already computed per §2) becomes one `Score` with `value = group_score,
weight = spec.weights[group_name]` (runner.py `_score_layout`). The five
weights above sum to 1.0000, so:

```
total_reward = sum(group_score_i * group_weight_i)   [the five weights sum to 1.0]
             = 0.2823*score(deliverables_01) + 0.258*score(deliverables_02)
             + 0.24*score(deliverables_03) + 0.1931*score(deliverables_04)
             + 0.0266*score(deliverables_05)
```

A group not listed in `weights` gets `1.0` by default (`_group_weights`,
runner.py line ~608) - not observed in this task (all 5 groups are named),
but worth checking on a task with a differently-shaped `reward.toml`.

If `tests/reward.toml` has no `[[reward]]` table and there is exactly one
top-level group, `judge_emulate.py` falls back to that single group's own
score as `total_reward` (matches what `_score_layout` itself returns -
`result = dict(flat)` before any `[[reward]]` merge is applied). With no
`[[reward]]` AND more than one group, `total_reward` is left `None` and a
warning is emitted - rewardkit itself has no way to combine them into a
single number in that case either.

## 4. Where this script's output maps onto DataOS's `reward-details.json`

`rewardkit_native.main` in this script's output is exactly what
`rewardkit.runner._score_layout` returns for a real run: `{group_name:
score, ..., "reward": total}`. `rewardkit_native.details` is exactly
`_layout_details`'s output - the same nested `{"kind": "group"|..., "score":
..., "components": [...]}` / per-Reward `to_detail_dict` shape rewardkit
writes to a real `reward-details.json`. Diff those two sub-objects against a
real DataOS return for the same task to check this script isn't silently
drifting from rewardkit's own arithmetic.

The top-level `groups: [{name, weight, score, criteria: [...]}]` shape is
this script's own flattening of the same numbers, matching what GATE-V2 3.1
asked for (task/mode/total_reward/groups/criteria), for a human or a fixer
script to read without walking the nested `rewardkit_native.details` tree.

## 5. What is NOT rewardkit's real arithmetic (the honest gaps)

- **Judge identity.** DataOS's own judge.toml says `judge =
  "anthropic/claude-sonnet-4-6"`; this script always calls Opus via the
  Claude Code CLI regardless (GATE-V2 3.1's explicit instruction: "Opus
  model"). A different model can and will produce different yes/no verdicts
  on the same prompt - this changes `raw`/`value` inputs, never the
  arithmetic in §1-3 that turns them into a score.
- **No JSON-schema enforcement.** Real rewardkit sends
  `response_format={"type": "json_schema", ...}` to litellm/Anthropic,
  which constrains the model's output at the API level. The Claude Code CLI
  has no equivalent flag; this script relies on the SAME prompt text
  rewardkit builds (which already asks for the JSON shape in prose - see
  `judges._build_criteria_block`'s trailing "Respond with a JSON object.
  Example: ...") and then rewardkit's own `parse_judge_response` regex/brace
  extraction, which is also real rewardkit's fallback path when a provider
  doesn't support schema enforcement. Not identical reliability, same parser.
- **`mode = "individual"` fan-out.** Not exercised by this corpus (every
  judge.toml here is the default `mode = "batched"`); the bucketing logic in
  `bucket_criteria()` should reproduce it (criterion-level `files=[...]`
  overrides the judge-level list, one bucket per distinct file scope) but
  was never run against a task that actually sets `mode = "individual"`.
  **Flagged, not verified.**
- **`atif_trajectory` / agent judges / MCP servers / `judge.reference`.**
  Not implemented. An `AgentJudge`-backed group is detected and scored as an
  all-error 0.0 with a warning rather than silently mis-scored; a
  `judge.reference` field (rewardkit's "compare against a reference
  solution" mode) is silently ignored since it never appeared in the one
  task inspected (SVC-PC-29-2-0) - **not checked against the installed
  package's other capabilities**, flagged per the build instructions.
- **"Must-pass" is prose, not a TOML gate, in every task inspected so far.**
  `optional`/`required_pass`/`all_pass` are real rewardkit mechanisms this
  script fully honors; "This is a must-pass criterion." in a criterion's own
  description text is NOT one of them anywhere in rewardkit's source - it is
  never read as `optional=false` (that's already every criterion's default)
  or as an aggregation override. This script surfaces that gap explicitly as
  `must_pass_prose_but_unenforced` per group (GATE-V2 class H), rather than
  inventing an enforcement rewardkit itself does not have.

## 6. Dry-run validation performed (2026-09-18)

`SVC-PC-29-2-0 oracle --dry-run`: discovered all 5 `deliverables_NN` groups
with weights 0.2823/0.258/0.24/0.1931/0.0266 (sums to 1.0000, matches
`tests/reward.toml`), one bucket (= one CLI call) per group since every
criterion in every group shares the same single-file scope
(`/app/Workforce_Coverage_Read.xlsx`), remapped correctly onto
`solution/files/Workforce_Coverage_Read.xlsx` and extracted via rewardkit's
own MarkItDown xlsx path (confirmed: the assembled user-turn text is the
workbook's tabs as markdown tables - "Cover", "Findings", etc. - not raw
bytes, not an error). System prompt text matches
`judges._build_criteria_block`'s format exactly, including the trailing
"yes"/"no" score-format annotation per criterion. `--max-criteria 5` was
also exercised in dry-run: it correctly let the first 12-criterion bucket
through (criteria are batched per group, so the budget check happens between
buckets, not mid-bucket) and skipped every criterion in the remaining 4
groups with `error: "skipped: --max-criteria budget exhausted"`.

No live CLI call was made in this validation (`--dry-run` short-circuits
before the `claude -p` subprocess). Live-call correctness (does the CLI
actually return a parseable "yes"/"no" JSON body for this exact prompt
shape) is NOT yet verified - that is the next, budget-gated step per
GATE-V2 3.0, and should be a single real oracle run on one task before wider
use.
