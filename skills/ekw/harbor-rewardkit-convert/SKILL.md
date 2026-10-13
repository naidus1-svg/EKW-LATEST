---
name: harbor-rewardkit-convert
description: >-
  Convert an old-format harbor task (instruction.md, task.toml, environment/,
  solution/, tests/verifier.json + verifier_lib) into the strict reward-kit
  task format the Data OS platform requires (task.toml schema 1.1,
  solution/solve.sh + solution/files/, tests/test.sh + tests/deliverables/judge.toml,
  reward.toml). Works for both EKW and DermOTS source bundles — auto-detects
  which one it's looking at. Use when asked to convert a task "into this
  format", "into reward-kit format", or "into the strict platform format",
  or when a task fails upload/grading with a reward-kit schema/validation error.
---

# Harbor → reward-kit conversion

Converts an old-format harbor task directory into the reward-kit layout the
Data OS platform actually grades. One script, two genres (EKW / DermOTS),
auto-detected from the source.

## What "this format" means (locked decisions)

```
task_<slug>/
├── task.toml                    # schema_version = "1.1"; [metadata]=category+tags only
├── instruction.md                # workspace paths repointed to /app
├── environment/
│   ├── Dockerfile                 # colab-cli base
│   └── initial_workspace/         # source docs / world snapshot -> COPY'd to /app
├── solution/
│   ├── solve.sh                   # copies solution/files/* into /app — sanity-check only
│   ├── files/<deliverable(s)>     # ONLY the files the judge reads back — never expert-only extras
│   └── reasoning.docx             # (EKW only, if present) expert derivation — NOT in files/
└── tests/
    ├── test.sh                    # pip install harbor-rewardkit[all] && rewardkit /tests
    ├── task_prompt.txt
    ├── reward.toml                # [[reward]] name="reward" aggregation="weighted_mean"
    └── deliverables/judge.toml    # [judge] judge=..., files=[...]; [[criterion]]*N; [scoring]
```

Non-negotiable constraints that have broken uploads/grading before — the wrapper
script checks all of these automatically:
- Every `[[criterion]] name` must match `^[a-zA-Z0-9_-]{1,64}$` and be unique.
  (A tag/rubric-name over 64 chars silently crashed the verifier before
  `reward.json` was ever written → platform-side `RewardFileNotFoundError`.)
- Criterion weights must sum to ~1.0.
- `solve.sh` copies only graded deliverables — never expert-only files (e.g.
  `Reasoning.docx`) into `/app`, or a side-effect-aware judge criterion can
  penalize the unsolicited file.
- `benchmark_type` and `expert_time_estimate` are deliberately omitted (no
  fitting platform enum value / tracker-sourced field, not a harbor-core key).
- **Judge is Claude only.** `[verifier.env]` always declares `ANTHROPIC_API_KEY`,
  and the judge model is always forced to `anthropic/...` (`pick_judge()` in
  `to_rewardkit.py`), overriding whatever provider the source `verifier.json`
  named (EKW's source spec judge is `openai/gpt-5.4`). This is a locked policy,
  not an auto-detected default — task_74 broke on-platform with
  `litellm.InternalServerError: ... Missing credentials ... OPENAI_API_KEY`
  because `[verifier.env]` only provisions `ANTHROPIC_API_KEY`; a non-Anthropic
  judge model has no credentials to call with. Reproduced locally, confirmed
  fixed once judge + env were both forced to Anthropic (2026-07-24).

## How to run it

```bash
python3 scripts/rewardkit_convert.py <src_task_dir> [out_dir]
```

- `src_task_dir` — an old-format harbor task (must have `task.toml`,
  `instruction.md`, `environment/`, `solution/golden_outputs/`,
  `tests/verifier.json`).
- `out_dir` — optional; defaults to `<src_parent>/rewardkit/<slug>` where slug
  is derived from `task.toml`'s `task_id` (or the source folder name).
- Genre (`ekw` vs `dermots`) is auto-detected: `dermots` if `task.toml`
  metadata has `case_id`/`snapshot_key`, or `environment/data/` has
  `YYYY-MM-DD__E##`-style snapshot folders; otherwise `ekw`. Force it with
  `--prefix=ekw` or `--prefix=dermots` if detection is ever wrong.

The script prints the conversion summary (name, judge, criteria count, weight
sum, deliverables) then runs validation and **exits non-zero with a specific
reason** if anything is off — do not hand-wave past a validation failure.

## After conversion — smoke test before calling it done

Converting is necessary but not sufficient — actually grade something locally:

```bash
# from the repo root, with an API key for the judge model exported
uvx --python 3.12 --from 'harbor-rewardkit[all]' rewardkit <out_dir>/tests \
    --workspace <out_dir>/solution/files --output /tmp/reward.json
cat /tmp/reward.json   # expect {"deliverables": <score>, "reward": <score>}
```

If only an OpenAI key is available locally, swap the judge line in
`judge.toml` for the smoke test only — do not ship that swap; the real build
always judges with Claude (see below).

## Canonical source

`pipeline/tools/to_rewardkit.py` (the converter) and
`pipeline/tools/rewardkit_convert.py` (this wrapper) are the project's
canonical copies — this skill packages the same scripts for portability. If
you edit the conversion logic, patch both locations (or replace this skill's
copy with a fresh `cp` from `pipeline/tools/`) so they don't drift.
