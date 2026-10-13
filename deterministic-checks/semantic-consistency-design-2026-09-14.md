# semantic_consistency_check.py: design (2026-09-14)

**Status: DESIGN ONLY. Nothing below is built.** This document specifies an LLM-assisted,
dual-format (SVC-PC `judge.toml` + EKW `verifier.json`) check for the one confirmed,
unowned defect class in `COVERAGE-MATRIX.md` Part 4: a criterion whose required answer
contradicts what the task instruction's own stated logic would produce. It follows this
folder's conventions: every claim is tagged by how it was established, limits are disclosed
rather than hidden, and the prompt, schema, and validation bar are written down so the
build cannot drift from the design.

Evidence tags used throughout:

- **RAN**: executed this session, output quoted. Section 12 lists every command.
- **READ**: read from a file this session, path and line cited.
- **PROPOSED**: a design decision. Not evidence of anything.
- **OPEN**: a question this session could not settle; named as such, with what would settle it.

## 0. Summary

The check reads `instruction.md` and the task's full rubric, extracts the instruction's
stated logic (allowed outcomes, priority and conflict rules, sizing bases, formulas, scope
rules, freedom statements) into a quoted ledger, then asks, per criterion, whether the
expected answer follows from that logic, contradicts it, is ambiguous under it, is contested,
or is not addressed by it. `contested` and `ambiguous_instruction` are first-class verdicts,
not failure modes. The golden is never shown in the main pass, because the rubric was
authored from the golden and showing it would test the wrong thing.

Recommended shape: a Python harness with three interchangeable LLM backends behind one
prompt, one schema, and one validator. The `prompt-file` backend (a Claude Code session or
subagent reads a prompt file and writes a response file) works today and is the path for the
four-case validation. The `cli` backend (`claude -p` through `tools/llm_backend.py`) is the
scale path, but it does not work on this machine until the user completes one
authentication step: the CLI reports `loggedIn: false` from every subprocess (RAN, section
5.1). The `http` backend (the user's GLM proxy) responds, but its model identity is
contradicted by its own self-report (RAN, section 5.5) and must be confirmed by the proxy
owner before it is used for anything.

Per-task cost cannot be measured in dollars or seconds today because the only Max-plan path
is not logged in. Token cost is estimated from measured corpus sizes (section 6): roughly
6.6K input and 5.2K output tokens per SVC-PC task per run at the mean, two calls per task.

## 1. What this check targets, and what it does not

### 1.1 Definition

**Verdict-flipping** (the manifest's term, `ekw/svc-pc-check-verification-manifest-2026-09-14.md`
line 56): a criterion "rewards the wrong answer per the instruction's own stated logic." A
solver who does exactly what the instruction says produces answer A; the criterion pays only
for answer B. The judge cannot notice, because it never reads the instruction (1.3). The
defect lives in the criterion text, the instruction text, or the gap between them, and is
detectable from those two texts alone.

### 1.2 Not the same as run-to-run criterion flipping

Two project memories use "flip" for a different phenomenon: a criterion returning different
verdicts on byte-identical content across two oracle runs
(`memory/compound-expected-values-flip-between-runs.md`,
`memory/three-causes-of-svc-criterion-flipping.md`, READ). That is judge nondeterminism on a
compound `Expected:`. This check is not about that. The two interact in one place only: the
detector itself is an LLM and will be nondeterministic, so its own verdicts get a stability
run (3.5), which is the same lesson those memories teach applied to this tool.

### 1.3 Root mechanism: the judge never sees instruction.md

READ, `ekw/svc-oracle177-rootcause-phase0-synthesis-2026-09-14.md` lines 113-120: a grep of
the grading package for `task_prompt|instruction` returned zero hits, and the judge system
prompt is one line, "Evaluate the provided file contents against the following criteria."
A converter-written `tests/task_prompt.txt` exists but nothing reads it. This check is the
instruction-consistency read the grading pipeline structurally cannot perform.

### 1.4 Why no deterministic check catches it, and what the six DataOS gates cover

Every script in this folder matches keywords, structure, filenames, weights, or file
contents. None reads the instruction for a rule and tests a value against it; the manifest
(line 50-60) and `COVERAGE-MATRIX.md` line 89 both record this as an open gap. The synthesis
doc (lines 82-85) says the six DataOS LLM gates make this script unnecessary. I read the gate
definitions to check that claim (`automation/tp-fp-classification/batch-scan-gates.md`, READ
in full; the path the synthesis cites under `C:\ekwqc\repo\automation\` does not exist, RAN
glob, the file lives under `EKW_QC_pipeline/automation/`):

| Gate | Inputs (from its yaml header) | What it tests | Covers verdict-flipping? |
|---|---|---|---|
| 1 `rubric_scope_excludes_required_sources` | rubric, source filenames | judge file-scope breadth | No (different mechanism) |
| 2 `rubric_self_contradicts_stated_freedom` | `[verifier_or_judge_toml]` only (line 167) | one criterion grants latitude, another hardcodes | No: it never reads the instruction. 92-0-0's freedom statement ("do not assume one") is in the instruction, not the rubric |
| 3 `rubric_requires_unsupported_content` | instruction, rubric, sources, golden | closed-world prompt + fact absent from every source | No (absence of support, not contradiction of a rule) |
| 4 `rubric_hardcodes_undisclosed_specific_requirement` | instruction, rubric, source excerpts | prompt generic, criterion specific, no source signal | Nearest neighbour. It tests the ABSENCE of narrowing; this check tests the PRESENCE of a rule that yields a different answer. The fixes differ: Gate 4's natural fix is "disclose the requirement in the prompt"; for 92-0-0 r01 that fix would itself contradict "do not assume one" |
| 5 `rubric_rejects_golden_reference` | rubric, golden, oracle reward | golden fails its own rubric | No (blind to the instruction by construction) |
| 6 `rubric_requires_unstated_technical_convention` | instruction, rubric, golden | unstated structural convention | No |

Two further facts about the gates, READ from the synthesis doc lines 61-81: their raw output
never leaves reviewers' machines, and on 92-0-0 a human overrode a true-positive as
false-positive on circular reasoning. Which of the six gates produced 92-0-0's r01 hit is not
recorded in any document read this session (OPEN). So this design proceeds on the gate
prompts as written: none takes the instruction's affirmative logic as its test, and the
nearest one frames the defect and its fix differently. The disagreement with the synthesis
doc's "do not rebuild" line is stated here plainly rather than papered over.

## 2. Ground truth, read from disk this session

All four packages live under `C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready\`. Quotes
below are verbatim except that em dashes and non-ASCII arrows/minus signs in the source
text are normalized to ASCII, because this repo bans em dashes in every file.

### 2.1 SVC-PC-92-0-0, r01 (manifest line 149)

Instruction (`instruction.md` line 6): "A searchable knowledge base, document-control tool,
checklist system, or no new tool may be the conclusion; do not assume one."

Criterion (`tests/deliverables/judge.toml` lines 7-10): "States the recommendation to adopt a
lightweight register-based lifecycle model and defer new tooling pending documented failure.
Expected: Register first." Weight 0.15, the largest in the rubric. Not must-pass.

Reading: the instruction enumerates four permitted conclusions and forbids presuming one;
r01 pays only for one of the four. A solver who recommends a checklist system with a
defensible evidence trail has complied and loses 15% of the reward. Clean contradiction;
shape: allowed-outcome enumeration.

### 2.2 SVC-PC-42-1-0, c05, with c12 and c13 downstream (manifest line 197)

Instruction (`instruction.md` line 7): "Define the downside as a coherent, severe-but-plausible
revenue miss and size it from the company's own evidence - historical monthly and channel
volatility, the largest quarter-over-quarter swings on record, and the assumptions narrative
- and state that basis explicitly rather than adopting a round number."

Criterion (`tests/deliverables_01/judge.toml` lines 31-34): "Downside magnitude is sourced from
the company's own records. Expected: Revenue haircut = -27.3%, equal to the largest
single-month FY2021 revenue decline (Jul->Aug and Nov->Dec); a round-number haircut (e.g.
-25%/-30%/-50%) without this basis fails.. This is a must-pass criterion." Weight 0.08.

c12 (lines 73-76) pins "Downside revenue = $875,962 (=$1,204,900 x 0.727) ... tolerance
+/-$1,000" and c13 (`deliverables_02` lines 7-10) pins the downside OI from the same 27.3%.
Both inherit c05's number, so a solver on any other compliant basis fails three criteria,
one of them must-pass.

Reading: the instruction offers a menu of bases and tells the solver to define and state
one. Monthly volatility is on the menu, so -27.3% is A compliant answer; c05 makes it THE
compliant answer. The manifest's own recomputation (line 197, READ, not re-derived by me)
adds that the quarter-over-quarter basis the instruction names yields no decline in FY2021 at
all, so a solver who follows that named basis cannot land on -27.3%. Shape: sizing basis or
method. c12/c13 are dependents, not separate findings.

### 2.3 SVC-PC-80-7-0, f2 (manifest line 187 names it only as "a must-pass criterion")

Instruction (`instruction.md` line 1): "define the remediation-backlog structure and its
prioritization method (severity x dollar exposure x effort) so every finding can be scored
the same way."

Criterion (`tests/deliverables_04/judge.toml` lines 61-64): "Prioritization method matches the
required formula Expected: Severity x Dollar exposure x Effort. This is a must-pass
criterion." Weight 0.02.

Reading: the criterion matches the instruction's literal text. There is no contradiction
between the two documents. The defect is that the instruction's formula is directionally
ambiguous: read literally, higher effort raises priority; read as any practitioner would,
effort is a cost and divides or inverts. Both real models took the second reading and failed
a must-pass gate (manifest line 187, READ). This is a different category from 2.1 and 2.2
and needs its own verdict, because the fix lands in the instruction (state the direction) or
in the criterion (accept a stated, internally consistent direction), not in the expected
value.

### 2.4 SVC-PC-88-0-0, obj-01, contested (manifest lines 158 and 164-178)

Instruction (`instruction.md` line 2): "a register-to-GL payroll reconciliation to residual
zero with correcting entries"; line 3: "Do not re-derive the specialist figures from scratch
and do not introduce amounts that are not supported by the specialist packages or the source
records; carry each package's headline figures forward"; line 4: "the register-to-GL
reconciliation to residual zero and correcting entries".

Criterion (`tests/deliverables_01/judge.toml` lines 49-52): "Cited register-to-GL residual
after items Expected: approx. -$0.01 (residual-to-zero). This is a must-pass criterion."
Weight 0.06.

Two instruction rules pull in different directions. Rule A (the description of the package,
stated twice): the reconciliation goes "to residual zero." Rule B: carry the package's own
headline figure forward and do not re-derive. If the specialist package states -$0.01, rule B
makes -$0.01 the compliant answer and "zero" is the instruction's own loose wording; if it
states zero, or if no package exists, rule A is all a solver has. The manifest's from-scratch
recomputation reproduces -$0.01 off the raw registers (lines 164-170, READ), which says
-$0.01 is arithmetically real, and says nothing about which reading the instruction licenses.

A new fact this session (RAN, four globs over `SVC-PC-88-0-0/environment/`): no file at the
top of `initial_workspace/`, no file at the root of `_corpus_subtree/`, and zero matches for
`*Workday*`, `*941*`, `*utover*`. The seven specialist packages the instruction calls
"attached as files alongside the company's FY2021 business records" are not in the shipped
environment. The corpus holds raw `Payroll_Register_2021-MM.xlsx` files and bank/AR/AP
reconciliations only. So rule B has nothing to carry forward, the only route to -$0.01 is the
re-derivation rule B forbids, and a solver reporting "zero" was following the only text
available. This sharpens the case rather than settling it: the criterion is correct against
real data and wrong against the instruction as shipped, and the environment gap is a
separate defect (`environment_input_check.py` territory, structural-audit pattern 1; the
manifest's obj-04 row already records the missing Workday export).

This is the pressure test for the output design. The right output is not a verdict on who is
right. It is: both readings, quoted; the single fact that would settle it (what residual the
specialist reconciliation package states); where that fact lives (a package the instruction
names and the environment does not contain); and a note that the must-pass weight makes the
consequence severe whichever way it resolves.

### 2.5 The sub-shape taxonomy this ground truth forces

Two orthogonal axes, so the three sub-shapes the task brief names are not flattened:

- **Verdict** (relationship between criterion and instruction): `follows`, `contradicts`,
  `ambiguous_instruction`, `contested`, `not_addressed`.
- **Shape** (the kind of stated logic involved): `allowed_outcome_enumeration`,
  `priority_or_conflict_rule`, `sizing_basis_or_method`, `formula`,
  `explicit_scope_or_prohibition`, `freedom_statement`, `other`, `none`.

Mapping: r01 = contradicts x allowed_outcome_enumeration; c05 = contradicts x
sizing_basis_or_method; f2 = ambiguous_instruction x formula; obj-01 = contested x
priority_or_conflict_rule. The manifest's untestable 92-1-0 c11 (audited FY21 over GL over
inventory-of-record, line 138) would be contradicts x priority_or_conflict_rule; it is
excluded from validation (2.6) but the shape exists in the taxonomy because the manifest
documents it.

### 2.6 Exclusion

SVC-PC-92-1-0 is excluded from every validation set here, for the manifest's reason (lines
102-128): the on-disk package no longer contains the content the findings describe.

## 3. Detection model

### 3.1 Two stages: a quoted ledger, then per-criterion entailment

**Stage 1, ledger.** Input: the full `instruction.md`. Output: every sentence that states
logic a compliant solver must apply, quoted verbatim, typed by shape, with what it governs;
plus any file the instruction names as carrying rules (a policy excerpt, terms, an
agreement). Output is small, human-readable, and reused by both stability runs and by every
Stage 2 chunk. A human can correct it before Stage 2 runs.

**Stage 2, entailment.** Input: the full instruction again, the Stage 1 ledger, the
environment file NAMES (not contents), and a chunk of criteria with name, description,
weight, must-pass flag, graded files, and for EKW the `why_justification`,
`how_justification`, and `importance` fields. Output: one entry per criterion (4.3).

Why two stages rather than one call: the ledger is the part a reviewer needs to eyeball, the
part that should be identical across runs, and the part that lets the harness validate every
Stage 2 quote mechanically against a fixed set. It also keeps Stage 2 output focused on
entailment instead of rediscovering the rules per chunk.

### 3.2 Verdict vocabulary

| Verdict | Meaning | Evidence the harness requires |
|---|---|---|
| `follows` | A solver applying the ledger's rules produces the required answer | ledger rule id(s) |
| `contradicts` | Applying a quoted rule yields a different answer than the criterion pays for | instruction quote, criterion quote, and one sentence stating what a compliant solver produces instead. Missing any: downgraded to `contested` |
| `ambiguous_instruction` | The instruction's wording admits two or more reasonable readings with different answers; the criterion pays for one; the criterion is consistent with at least one reading | two or more readings listed, each marked consistent/inconsistent with the criterion |
| `contested` | Textual support for both `follows` and `contradicts`; not settleable from instruction plus rubric | both readings, plus `resolving_evidence` = {question, where} |
| `not_addressed` | The instruction states no logic bearing on this expected value | none. Sub-flag `not_requested: true` when the criterion requires content the instruction never asks for (Gap 2 candidate; reported, not validated, see 10) |

`contested` is where uncertainty goes on purpose. It is also the mechanical destination for
any `contradicts` that fails the quote check, for `low` confidence, and for run-to-run
disagreement (3.5). A task with only `contested`/`ambiguous_instruction` findings is
reported as `attention`, distinct from `flagged` (any final `contradicts`) and from `clean`.

### 3.3 What the model sees, and deliberately does not see

- **Full `instruction.md`, never excerpted.** Logic sentences are scattered (92-0-0's is
  sentence 3 of a paragraph; 88-0-0's two rules are 1,500 characters apart). Excerpting is
  the failure mode. Size is not a constraint: SVC-PC max 15,080 chars, EKW max 23,398 (RAN,
  6.1), under 6K tokens.
- **All criteria of the task**, in chunks of at most 40 with the same ledger, so cross-criterion
  dependencies (c12/c13 on c05) are visible within a chunk and named via `depends_on`. Chunk
  boundaries follow `judge.toml` file boundaries where possible.
- **Environment file names only.** Enough for the model to say where resolving evidence
  lives; contents are out of scope for the main pass.
- **Never the golden, never `Reasoning.docx`, in Stages 1-2.** Synthesis item 11 (READ):
  rubrics are authored from the golden. Showing the golden would make the model check
  "does the criterion match the golden" (content-audit pattern 2, Gate 5's job) instead of
  "does it follow from the instruction."
- **Optional Stage 3, off by default (`--resolve-contested`).** For `contested` entries whose
  `resolving_evidence.where` names a file present under `environment/` or `solution/`, extract
  that file's text (reuse `answer_key_content_leak_check.read_docx_text`, line 582, for docx;
  openpyxl values for xlsx) and ask one narrow question. For 88-0-0 this stage returns
  "named file not in environment," which is the finding.

### 3.4 Chunking rule

One Stage 2 call when the task has at most 40 criteria (covers the SVC-PC median of 40 and the
EKW p90 of 26); otherwise ceil(n/40) calls, splitting on judge.toml boundaries. The
142-criteria task (RAN max) takes 4 chunks. Every chunk carries the full instruction and the
full ledger.

### 3.5 Stability: two runs, agreement, downgrade

Run Stage 2 twice with identical prompt bytes. Per criterion, record `stability:
agree|disagree`. Any verdict disagreement downgrades the final verdict to `contested` with
flag `unstable`. Report per-task and corpus agreement rates. At scale, run 2 covers every
task with at least one non-`follows` verdict in run 1 plus a 10% random sample of run-1-clean
tasks as a control; the sample is what proves "clean" is stable, not just "flagged" is.

### 3.6 Deterministic pre-scan, a calibration aid rather than a gate

A keyword scan of `instruction.md` for logic hooks ("may be the conclusion", "do not assume",
"rely on", "controlling over", "authority", "size it from", "largest", "x " between nouns,
"do not re-derive", "where ... conflict") produces a `hook_count`. It is recorded next to the
Stage 1 ledger so a task where the LLM found no rules but the scan found hooks (or the
reverse) is surfaced for a human. It gates nothing. All four ground-truth instructions
contain such hooks (READ); whether the scan has signal beyond them is measured, not assumed
(memory: probe before building a detector).

## 4. Prompt templates and schemas

### 4.1 Stage 1 (ledger)

System prompt:

```
You are auditing a benchmark task's solver-facing instruction. Your only job in this step is
to extract every sentence in the instruction that states LOGIC a compliant solver must
apply: which outcomes are allowed, which source wins when sources conflict, what basis or
method sizes a number, what formula to use, what is in or out of scope, and where the
instruction explicitly leaves a decision open to the solver. Quote each verbatim. Do not
evaluate the task, do not propose answers, do not read into the instruction anything it does
not say. If the instruction states no such logic, say so.
```

User prompt:

```
TASK: {task_id}
INSTRUCTION (verbatim, solver-facing):
<<<
{instruction_md}
>>>
Return JSON matching the schema. For each rule give: id (L1, L2, ...), kind, the verbatim
quote (an exact substring of the text above, no paraphrase inside the quote), a one-sentence
paraphrase, and the decision or value it governs. Under rule_documents list, by filename,
any file the instruction names as carrying rules the solver must follow (a policy excerpt,
terms, an agreement, a rate card). Set no_rules_found only if the rules list is empty.
```

Stage 1 output schema (passed as `--json-schema` on the cli backend, enforced by the harness
validator on every backend):

```json
{
  "type": "object",
  "properties": {
    "task_id": {"type": "string"},
    "rules": {"type": "array", "items": {"type": "object", "properties": {
      "id": {"type": "string"},
      "kind": {"enum": ["allowed_outcome_enumeration", "priority_or_conflict_rule",
               "sizing_basis_or_method", "formula", "explicit_scope_or_prohibition",
               "freedom_statement", "other"]},
      "quote": {"type": "string"},
      "paraphrase": {"type": "string"},
      "governs": {"type": "string"}},
      "required": ["id", "kind", "quote", "paraphrase", "governs"]}},
    "rule_documents": {"type": "array", "items": {"type": "string"}},
    "no_rules_found": {"type": "boolean"}
  },
  "required": ["task_id", "rules", "rule_documents", "no_rules_found"]
}
```

### 4.2 Stage 2 (entailment)

System prompt:

```
You are auditing whether grading criteria agree with the instruction they grade against.
The grader that applies these criteria never sees the instruction; this audit is the only
place the two texts meet. For each criterion, decide whether the answer it requires is what
a solver who follows the instruction's stated logic would produce.

Rules:
1. Judge entailment, not truth. Do not decide whether the expected value is factually
   correct. Decide whether it FOLLOWS from the instruction's stated logic (the ledger plus
   the instruction text), CONTRADICTS it, or is NOT ADDRESSED by it.
2. A "contradicts" verdict needs three things: the instruction sentence quoted verbatim, the
   criterion's requirement quoted verbatim, and one sentence stating what a compliant solver
   would produce instead. Without all three, do not answer "contradicts".
3. If the instruction's own wording admits two or more reasonable readings that lead to
   different answers, and the criterion pays for only one, answer "ambiguous_instruction"
   and list the readings. A formula whose literal direction a practitioner would call
   backwards counts: say which reading is literal and which is the practical one.
4. If you find textual support for both "follows" and "contradicts" and the instruction plus
   the criteria cannot settle it, answer "contested", list both readings, and name the one
   fact that would settle it and where it lives (a named corpus file, the golden, or
   nowhere). Do not force a side.
5. If a criterion inherits its expected value from another criterion's assumption (a
   downstream figure computed from an upstream haircut or rate), name that criterion in
   depends_on and do not re-argue the upstream point.
6. If a criterion requires content the instruction never asks the solver to produce, set
   not_requested to true. That is reported separately; it is not a contradiction.
7. Do not assume the criterion author is right. Do not assume the instruction is right. Do
   not use outside knowledge of what the answer should be.
8. Every quote must be an exact substring of text you were given in this message. The
   harness rejects any quote it cannot find and downgrades the verdict.
9. Grade every criterion in the chunk, in the order given, one entry each.
```

User prompt:

```
TASK: {task_id}    FORMAT: {svc-pc | ekw}    CHUNK: {i} of {n}
INSTRUCTION (verbatim):
<<<
{instruction_md}
>>>
STATED-LOGIC LEDGER (from step 1, JSON):
{stage1_json}
ENVIRONMENT FILE NAMES (names only; contents not shown; truncated to {k} entries):
{file_names}
CRITERIA:
- name: {name} | file: {rel_path} | weight: {w} | must_pass: {bool} | graded files: {files}
  description: '''{description}'''
  {ekw only:} why_justification: '''{why}''' | how_justification: '''{how}''' | importance: {imp}
...
Return JSON matching the schema.
```

### 4.3 Stage 2 output schema

```json
{
  "type": "object",
  "properties": {
    "task_id": {"type": "string"},
    "chunk": {"type": "integer"},
    "criteria": {"type": "array", "items": {"type": "object", "properties": {
      "criterion": {"type": "string"},
      "verdict": {"enum": ["follows", "contradicts", "ambiguous_instruction",
                  "contested", "not_addressed"]},
      "shape": {"enum": ["allowed_outcome_enumeration", "priority_or_conflict_rule",
                "sizing_basis_or_method", "formula", "explicit_scope_or_prohibition",
                "freedom_statement", "other", "none"]},
      "confidence": {"enum": ["high", "medium", "low"]},
      "ledger_rule_ids": {"type": "array", "items": {"type": "string"}},
      "instruction_quote": {"type": ["string", "null"]},
      "criterion_quote": {"type": ["string", "null"]},
      "compliant_solver_would_produce": {"type": ["string", "null"]},
      "readings": {"type": "array", "items": {"type": "object", "properties": {
        "reading": {"type": "string"},
        "consistent_with_criterion": {"type": "boolean"}},
        "required": ["reading", "consistent_with_criterion"]}},
      "resolving_evidence": {"type": ["object", "null"], "properties": {
        "question": {"type": "string"}, "where": {"type": "string"}},
        "required": ["question", "where"]},
      "depends_on": {"type": "array", "items": {"type": "string"}},
      "not_requested": {"type": "boolean"},
      "justification_misquotes_instruction": {"type": ["boolean", "null"]},
      "fix_target": {"enum": ["criterion", "instruction", "both", "none", "unknown"]},
      "reasoning": {"type": "string"}},
      "required": ["criterion", "verdict", "shape", "confidence", "ledger_rule_ids",
                   "instruction_quote", "criterion_quote", "compliant_solver_would_produce",
                   "readings", "resolving_evidence", "depends_on", "not_requested",
                   "fix_target", "reasoning"]}}
  },
  "required": ["task_id", "chunk", "criteria"]
}
```

The harness adds, per criterion, from its own reading of the config: `file`, `weight`,
`must_pass`, `quote_check` (`ok | instruction_quote_not_found | criterion_quote_not_found |
missing`), `stability`, and `verdict_final` after the downgrade rules in 3.2 and 3.5. It adds
per task: `status` (`flagged | attention | clean | not_applicable | error`), the ledger, the
pre-scan `hook_count`, and the cost block (6.4). `must_pass` is parsed from the SVC-PC
description sentence "This is a must-pass criterion." with the same match
`certification_gate_check.py` uses (not re-read this session; import it rather than
re-implement), and from EKW metadata (8.2).

Mapping to the TP/FP taxonomy (`automation/tp-fp-classification/SKILL.md` lines 323-357,
READ) so downstream adjudication can consume findings without translation: a final
`contradicts` is a `content_substance` candidate; `contested` maps to `inconclusive`;
`ambiguous_instruction` is `content_substance` with `fix_target: instruction`.

### 4.4 Expected outputs for the four ground-truth cases

These are the validation targets (7.1, 7.2), written before any run so the run cannot
redefine them.

```
92-0-0 r01:  verdict=contradicts  shape=allowed_outcome_enumeration  confidence=high
  instruction_quote must contain: "do not assume one"  (or "or no new tool may be the conclusion")
  criterion_quote must contain: "Register first"  (or "defer new tooling")
  compliant_solver_would_produce: any of the four named conclusions with evidence
  fix_target: criterion

42-1-0 c05:  verdict=contradicts  shape=sizing_basis_or_method  confidence=medium|high
  instruction_quote must contain: "largest quarter-over-quarter swings"  or  "state that basis explicitly"
  criterion_quote must contain: "-27.3%"
  compliant_solver_would_produce: a stated basis from the instruction's menu; not necessarily -27.3%
  c12, c13: depends_on must include "c05"; their own verdict may be follows-given-c05 or contradicts

80-7-0 f2:   verdict=ambiguous_instruction  shape=formula
  readings: at least two, one marked consistent_with_criterion=true (literal product),
            one false (effort as divisor / inverse)
  fix_target: instruction or both
  A verdict of contradicts here is a FAIL of the validation: the criterion matches the text.

88-0-0 obj-01:  verdict=contested  (ambiguous_instruction also accepted)  shape=priority_or_conflict_rule
  readings: two, one citing "residual zero", one citing "carry each package's headline figures forward"
            or "Do not re-derive"
  resolving_evidence.question names the residual the specialist reconciliation package states
  resolving_evidence.where names that package (and may note it is absent from the environment)
  A high-confidence contradicts OR a high-confidence follows is a FAIL of the validation.
```

## 5. Invocation mechanism

### 5.1 The constraint, and what was run today

Hard constraint: no paid Anthropic API usage; no `ANTHROPIC_API_KEY`, no direct
`anthropic.Anthropic()` call, ever. The only Max-plan compute paths are a Claude Code session
(interactive, subagents, skills) and the `claude` CLI in print mode under the same login.

RAN this session, on this machine:

| Probe | Result |
|---|---|
| `claude` on PATH | not found (Git Bash and PowerShell). Binary exists at `%APPDATA%\Claude\claude-code\2.1.270\claude.exe` (desktop bundle; `tools/llm_backend.py` `_find_claude_cli` already handles this location) |
| `claude.exe --version` | `2.1.270 (Claude Code)` |
| `claude.exe auth status` | `{"loggedIn": false, "authMethod": "none", "apiProvider": "firstParty", ...}`; no `~/.claude/.credentials.json` |
| `claude.exe -p "..." --output-format json --model haiku` (as-is env, `CLAUDECODE=1`) | exit 1, `"is_error": true`, `"result": "Not logged in \u00b7 Please run /login"`, `duration_ms` 1881, process elapsed 6,906 ms |
| same with `CLAUDECODE` removed, plus `--tools "" --no-session-persistence` | identical failure, `duration_ms` 2505, elapsed 7,318 ms. Nesting is not the cause |
| `--max-turns 1` | accepted without an unknown-option error, but absent from `--help`. Do not rely on it; use `--tools ""` (documented) to force a single completion |

So the CLI path exists, parses these flags, emits the JSON envelope the harness needs, and is
blocked on one user-only step: `claude /login` in a normal terminal, or `claude setup-token`
("Set up a long-lived authentication token (requires Claude subscription)", from `--help`).
Both are the user's to run; this session cannot and did not. Whether a subscription login
made in the desktop app becomes visible to the bundled CLI without that step is OPEN; today
it is not.

Two flags must never be passed: `--bare` (its help text says "Anthropic auth is strictly
ANTHROPIC_API_KEY or apiKeyHelper ... OAuth and keychain are never read", which is the paid
path by construction) and anything that sets `ANTHROPIC_API_KEY`.

### 5.2 Three backends, one prompt, one schema, one validator

The harness owns prompt construction, schema validation, quote checking, downgrade rules,
stability, and reporting. The LLM call is a pluggable backend:

1. **`prompt-file`** (works today). The harness writes `<out-dir>/<task>/stage1.prompt.md`
   and later `stage2.<chunk>.prompt.md`, then waits for (or is re-invoked after) the matching
   `*.response.json`. A Claude Code session, or a Sonnet subagent batched five tasks at a time
   as `tp-fp-classification/SKILL.md` line 498 recommends, reads each prompt file and writes
   the response file. Same prompt bytes as the other backends, so results transfer.
2. **`cli`** (scale path, blocked on login). `tools/llm_backend.call_llm` extended to pass
   `--json-schema`, `--tools ""`, `--no-session-persistence`, `--permission-prompts none`,
   `--model`, `--effort`, and to feed the prompt via stdin instead of argv (Windows
   `CreateProcess` caps the command line at 32,767 characters; the largest SVC-PC rubric is
   61,381 characters). `_call_claude_cli` currently puts the prompt in argv (lines 129-131,
   READ), so this is a required change, marked PROPOSED until run.
3. **`http`** (the user's configured non-Anthropic proxy through `llm_backend`'s existing
   backend 2). See 5.5 before using it.

A thin `semantic-consistency/SKILL.md` is still written, but it says "run the harness in
`prompt-file` mode and fill responses as follows"; it does not carry a second copy of the
prompt. The tp-fp skill's own history (SKILL.md lines 33-38) records what duplicated prompt
text does over time.

### 5.3 Exact `cli` invocation

```
<claude.exe> -p --output-format json --json-schema <stage schema, JSON string>
  --model sonnet --effort max --tools "" --no-session-persistence
  --permission-prompts none --system-prompt <stage system prompt>
  < <prompt file on stdin>
```

`--model sonnet` follows the user's model split (judgment work is Sonnet); `--effort max`
follows the standing rule that effort is never lowered to save money. `--system-prompt-file`
is referenced in `--bare`'s help text and, if present in 2.1.270, is preferable to argv for
the system prompt; verify on the first authenticated run. `--max-budget-usd` exists and is a
harmless extra guard even when nothing is billed.

Envelope fields the harness records from the JSON result (observed on the error path, RAN):
`duration_ms`, `duration_api_ms`, `total_cost_usd`, `usage.input_tokens`,
`usage.output_tokens`, `usage.cache_read_input_tokens`, `usage.cache_creation_input_tokens`,
`modelUsage`, `num_turns`, `is_error`, `api_error_status`, `terminal_reason`, `session_id`,
`result`. Where structured output lands when `--json-schema` is given (a `structured_output`
field, or the JSON inside `result`) could not be observed without a login (OPEN); the parser
accepts either.

### 5.4 Recommendation

**Build the harness as a script with the `prompt-file` backend as the day-one path and the
`cli` backend as the scale path.** Not a bare skill. Reasons:

- The manifest's PASS bar (lines 21-46) needs machine-checkable output: named criteria,
  verbatim quotes, a per-defect-class recall and a stated false-positive rate. A skill applied
  freehand by a session produces prose, not a validated JSON with a quote check.
- Stability (3.5) is only meaningful with identical prompt bytes across runs. Only a harness
  guarantees that.
- The "flag real per-task cost" ask needs the CLI envelope or an equivalent per-call record;
  a session has only the transcript-level `/cost` view.
- Hundreds of tasks twice over (6.3) is unattended work; the CLI is the only unattended
  Max-plan path, and it is one login away.
- Until that login exists, `prompt-file` mode driven by subagents is exactly how this repo has
  already run its LLM-assisted audits (content-audit's 50-task sample, the manifest's
  primary-source agents), so the validation in section 7 is not blocked on anything.

### 5.5 The `http` backend: two conflicting signals, OPEN

User-scope environment on this machine (RAN, values other than the key printed):
`LLM_API_PROVIDER=openai`, `LLM_API_BASE_URL=http://34.41.10.8:4000/v1`, `LLM_API_MODEL=glm-5.2`,
`LLM_API_KEY` set (length 25), all per `ekw/svc-qc-glm-key-setup-2026-09-14.md`. Not present in
this session's process environment (set after the session started).

One-line probe through `llm_backend.call_llm` with `LLM_BACKEND_FORCE=http` (RAN, scratch
script, key never printed): reply in 1.3 s, `{"ok": true, "model_family": "Claude"}`.
`GET /v1/models` on the same proxy (RAN): exactly one model, `glm-5.2`, `owned_by: openai`.

The route is labelled GLM; the model says it is Claude. Model self-identification is one
weak datapoint and open models routinely claim to be Claude, but if the proxy actually
fronts an Anthropic model, every call through it is metered Anthropic usage billed to the
proxy's owner, which is against the spirit of the no-spend rule even though it is not the
user's key. This is not resolvable from here. Ask the proxy owner what `glm-5.2` routes to
before using this backend for anything beyond a smoke test, and record the answer in this
file. If it is a non-Anthropic model, it becomes a third leg whose judgment quality is
validated the same way as any other (section 7), not assumed.

## 6. Scale, cost, latency

### 6.1 Measured corpus sizes (RAN, one PowerShell pass over every task directory)

| Corpus | n | instruction.md chars (mean / p50 / p90 / max) | rubric chars per task (mean / p50 / p90 / max) | criteria per task (mean / p50 / p90 / max) |
|---|---|---|---|---|
| SVC-PC, `03_dataos_ready` | 600 | 2,312 / 1,865 / 4,071 / 15,080 | judge.toml total 9,897 / 8,751 / 17,994 / 61,381 | 39 / 40 / 54 / 142 (4 judge.toml files per task at p50, max 12) |
| EKW, `_merged274/files` | 274 | 3,051 / 2,582 / 5,157 / 23,398 | verifier.json 34,330 / 32,442 / 44,635 / 81,828 (JSON scaffolding included; rubric prompt text is a fraction) | 20 / 20 / 26 / 52 |

### 6.2 Token and call estimates per task (PROPOSED, chars/4 heuristic on the measured sizes)

SVC-PC at the mean: Stage 1 about 1.5K in / 0.5K out; Stage 2 about 5.1K in (system 1.2K,
instruction 0.6K, ledger 0.5K, criteria 2.5K, file names 0.3K) / about 4.7K out at 120 output
tokens per criterion. Per task per run: about 6.6K in / 5.2K out, two calls. p90: about 9.5K /
6.5K. The 142-criteria task: 4 chunks, about 30K in / 17K out. One run over 600 tasks: about
4.0M input and 3.1M output tokens.

EKW at the mean: rubric prompt text taken as 40% of verifier.json (about 3.4K tokens; the
2-sample observation is that prompts dominate the JSON but scaffolding is real), plus
`why`/`how` justifications: about 7.5K in / 2.8K out per task. One run over 274 tasks: about
2.1M input and 0.8M output tokens.

Two full runs double these; the 3.5 policy (run 2 on flagged tasks plus a 10% clean sample)
makes run 2 a minority of run 1's volume.

### 6.3 Wall-clock at scale, and the rate-limit unknown

Measured: about 5 s of CLI process overhead per call (elapsed 6.9 s and 7.3 s against
`duration_ms` 1.9 s and 2.5 s, RAN, error path). Unmeasured, because no authenticated call
was possible: generation time. Planning figure, stated as such: if Stage 2 output averages 5K
tokens and the model generates at 40 to 80 tokens per second, Stage 2 takes 60 to 125 s and a
task takes 1.5 to 2.5 minutes; 600 SVC-PC tasks serial is 15 to 25 hours; four-way parallel
is 4 to 6 hours. Max-plan rate limits are unmeasured and are the real ceiling; the envelope's
`api_error_status` will show 429s. First authenticated run: 20 tasks, record throughput and
any 429, then extrapolate. Do not extrapolate from this paragraph.

No dollar figures appear here on purpose. Under Max-plan authentication the marginal cost is
$0; the envelope's `total_cost_usd` is the measurement of the equivalent, and whether it
reports 0 or a list-price equivalent under OAuth is OPEN (the error-path envelope showed
`"total_cost_usd": 0`).

### 6.4 How the harness surfaces cost

Per task, a `cost` block: `backend`, `model`, `calls`, `input_tokens`, `output_tokens`,
`cache_read_tokens`, `cache_creation_tokens`, `duration_ms_total`, `equivalent_cost_usd`
(sum of envelope `total_cost_usd`), `billed` (`false` under subscription auth, `unknown` for
`http`, `true` only if an API key path were ever used, which it is not). Per run: a summary
line per task on stderr in the folder's `[i/n] TASK ...` style, and an aggregate with p50/p90
per-task tokens and seconds, matching the `--out` JSON convention of every other check here.
Guards: `--max-tasks`, `--token-budget` (stop when the running input+output total crosses
it), and `--max-budget-usd` passed through to the CLI.

## 7. Validation plan

The harness is not trusted on the broader corpus until every step below has run and its
numbers are written into this file. The bar is the manifest's (lines 21-46): named, not
generic; recall per defect class; precision stated; scope honest.

### 7.1 Recall on the three clean-ish cases

Run the four tasks in `prompt-file` mode (session or Sonnet subagents), both stages. PASS per
case is the exact expectation in 4.4: the right criterion named, the right verdict, the right
shape, and quotes containing the anchor substrings listed there. A hit on a different
criterion in the same task, or the right criterion with a reason that does not match the
mechanism (r01 flagged for "undisclosed terminology" instead of the four-outcome rule), is
PARTIAL, not CONFIRMED, per the manifest's rule 1. c12/c13 must carry `depends_on: ["c05"]`.

### 7.2 The contested case, and what pass looks like

obj-01 passes when the final verdict is `contested` (or `ambiguous_instruction`), both
readings are present with their instruction quotes, and `resolving_evidence` names the
residual the specialist reconciliation package states. It also passes if the model answers
`contradicts` at medium confidence and the harness downgrades it to `contested` on the
stability run, because the downgrade is the design working. It FAILS on a high-confidence
`contradicts` or a high-confidence `follows`, because either one forces a side the texts do
not settle. Correctly flagging obj-01 as contested IS the correct behaviour, and the check is
not required to resolve it.

### 7.3 Precision

The four tasks carry 103 criteria (10 + 24 + 50 + 19). Excluding the 4 targets and the 2
dependents leaves 97 non-target criteria. Every final `contradicts` among them is adjudicated
by a human against the manifest's bar and recorded as true or false positive; the measured
rate goes into this file. Provisional bar: at most 2 false `contradicts` across the 97, and
every `contested` among them must carry a real resolving question (a `contested` with an
empty or generic question is a false positive of a milder kind and is counted separately).
Then run a random 20-task SVC-PC sample and the 44 EKW tasks content-audit called clean
(`content-audit/SKILL.md` lines 44-54; task-level only, no per-criterion labels there) and
adjudicate every `flagged` task. Report precision per corpus, not pooled.

### 7.4 Stability

Two Stage 2 runs on all four tasks. Report per-criterion verdict agreement; bar 90% on
non-targets, and every target verdict must be identical across runs or the downgrade rule
fires and the case is re-examined. Quote check: 100% of quotes must be verbatim substrings;
any miss is a prompt defect to fix before the corpus run.

### 7.5 Mechanical checks before the LLM run

Before any LLM call: the harness must parse all 600 + 274 tasks with zero crashes (same
dispatch as `extraction_groundedness_check.analyze_task`, judge.toml precedence), chunk the
142-criteria task into 4, chunk the 12-file task on file boundaries, and refuse an
`--out-dir` inside `--root` (section 9). Run `python tools/test_eval_counting.py`-style
named tests for the downgrade rules with hand-written fake responses: a `contradicts` with a
fabricated quote becomes `contested`; a run-1/run-2 disagreement becomes `contested`; a
`no_rules_found` task becomes `not_applicable`.

### 7.6 What a clean result does not establish

A task with every criterion `follows` or `not_addressed` says nothing about corpus
groundedness (`criterion_groundedness_check`), judge file scope (Gap 6), golden correctness
(Gate 5, content-audit pattern 2), must-pass gating (`certification_gate_check`), near-duplicate
criteria (Gap 3), or run-to-run judge flips. It says: no criterion's expected answer
contradicts a rule the instruction states. Write that sentence into every report header.

## 8. Dual-format: SVC-PC vs EKW

### 8.1 Loader reuse

Dispatch and loading are `extraction_groundedness_check.py`'s: `_has_svc_pc_config` then
`has_ekw_config`; `rubric_text_lint.load_judge_files` for SVC-PC (path, files, criteria with
name and description); `ekw_verifier_json.load_ekw_criteria` for EKW (group, name,
description = `assertion.rubric.prompt`, weight, type, files, commands). No new parsing.

### 8.2 What differs in EKW, from two real packages (task_142, task_17) plus the loader docstring

1. **Rules are often delegated to attached documents.** task_142's instruction says "overhead
   absorbed on machine hours per the policy" and "Keep it strictly to the attached files";
   the policy is `environment/data/mis_costing_policy_excerpt.docx`, and v2's rubric tests
   "rolled at the FROZEN annual standard price ... not the latest-PO/replacement quote"
   (verifier.json line 63), a rule the instruction never states in its own words. With
   instruction-only Stage 1, most EKW numeric criteria will land in `not_addressed`. That is
   honest and low-yield. The design therefore makes Stage 1's `rule_documents` list the input
   to an EKW-specific Stage 1b: extract the named rule documents' text (same helpers as
   Stage 3) and extend the ledger with quoted rules from them, marked `source: <filename>`.
   Off by default for SVC-PC, on by default for EKW once 7.3 shows it is worth the tokens.
2. **Priority rules do appear inline** in EKW instructions too: task_17 line 5, "Treat final
   rights and permissions terms as controlling over informal assumptions, promotional
   language, or draft schedules." Shape `priority_or_conflict_rule` applies unchanged.
3. **EKW rubric prompts carry their own method rationale and wrong-method decoys** ("FAIL if
   ... which indicates rework was costed as scrap", task_142 v1). This gives Stage 2 more to
   test and adds an EKW-only contradiction shape: the rubric's stated method against the
   instruction's or policy's stated method.
4. **`why_justification` paraphrases the instruction** ("The task requires treating final
   rights and permissions terms as controlling over informal approvals...", task_17 v3). That
   is a checkable claim about the instruction. The Stage 2 field
   `justification_misquotes_instruction` is set when the justification asserts a requirement
   the instruction does not contain. SVC-PC has no such field; the harness passes `null`.
   `load_ekw_criteria` does not surface `why_justification`, `how_justification`,
   `importance`, or `must_pass` today (its docstring says so, lines 18-20); add them the way
   `commands` was added for `extraction_groundedness_check`, additively.
5. **Must-pass lives in metadata, not text.** SVC-PC states it inside the description; EKW
   carries `metadata.importance` (`core`/`secondary`, observed in both samples) and, per
   `COVERAGE-MATRIX.md` line 58, a native `metadata.must_pass` that `certification_gate_check`
   reads but has not run. The harness records both and treats `must_pass` as authoritative
   when present.

Also: 4 of 274 EKW verifiers are `deterministic` with no rubric prompt (task_15,
`ekw_verifier_json.py` lines 292-306); the loader synthesizes a description, and Stage 2
grades the literal expected value against the ledger like any other. `Reasoning.docx` under
`solution/golden_outputs/` is excluded from Stages 1-2 for the same golden-bias reason as
the primary golden.

### 8.3 What stays the same

The two stages, the verdict and shape vocabularies, the schemas, the quote check, the
downgrade rules, the stability run, the cost block, and the report shape are identical for
both formats. Format-specific behaviour is confined to the loader fields shown in the
criteria block and to Stage 1b.

## 9. Answer-key safety and report placement

Prompt files and reports quote `Expected:` values by design. They are QC-internal, never
solver-facing, and must never land under a task directory: the harness refuses an `--out-dir`
that resolves inside `--root`, writes only under `_ekw_verification_reports/semantic_consistency/`
(or the given `--out-dir`), and the `*.prompt.md` files there are added to `.gitignore`
(current `.gitignore` covers only `__pycache__/`, `*.pyc`, `.venv/`, `*.orig`, READ). Any future
"copy findings into the package for the author" step must strip the quotes first; this is the
folder's standing rule and the same one content-audit pattern 5 exists for.

## 10. Relationship to existing checks and the coverage matrix

- `COVERAGE-MATRIX.md` Part 4 row 1 (verdict-flipping) moves from GAP to "designed, harness
  pending" on the strength of this file, and to VERIFIED only after section 7's numbers are
  written in. Row 2 (the DataOS-gate coverage claim) gets the 1.4 table as its independent
  read of the gate prompts.
- `not_requested: true` findings are Gap 2 candidates (criteria requiring content the
  instruction never requests; 80-7-0's 19 of 50 criteria, manifest line 184). They are emitted
  for audit visibility only, the way `extraction_groundedness_check` emits
  `extraction_blind_not_flagged`, and this check claims no recall on Gap 2 until someone
  validates that category separately against 80-7-0 a2-a10, c2-c6, d7-d9, e3-e4, e8.
- `certification_gate_check.py` should read this check's per-task JSON as one more input at
  certification time (PROPOSED), which is the process fix the synthesis doc names for the
  gates that already exist and are never consulted.
- The 88-0-0 environment finding in 2.4 (seven named specialist packages absent) belongs to
  `environment_input_check.py` and the structural-audit skill, not to this check; it is
  recorded here because it changes how obj-01 should be read.

## 11. Open questions for the user

1. Run `claude /login` (or `claude setup-token`) once in a normal terminal so the `cli` backend
   can be exercised; until then every scale estimate in section 6 is unmeasured.
2. **RESOLVED 2026-09-14 ~23:10 EDT.** User confirmed directly (AskUserQuestion, turing-context-ef
   session) that `glm-5.2` at `34.41.10.8:4000` is confirmed-safe for real SVC-PC/EKW task content
   tonight. `LLM_API_BASE_URL`/`LLM_API_MODEL`/`LLM_API_KEY` are set as Windows User-level env vars
   (verified via `[Environment]::GetEnvironmentVariable(...,'User')` - they don't propagate into
   already-running shell processes, check the registry directly rather than trusting an empty
   `$env:` read). The `http` backend can come off the "stays off" hold.
3. Confirm the validation set: the four cases in section 2 plus the 97 non-target criteria,
   with 92-1-0 excluded. If the manifest's other verdict-flipping rows (24-6-0, 93-0-0) are
   wanted as additional recall instances, their mechanism is closer to unreachable
   (sibling-task outputs never staged) than to a stated-logic contradiction, and adding them
   would blur the class this check claims.
4. Decide whether Stage 1b (rule documents) is in scope for the first build or deferred; it is
   the difference between a low-yield and a useful EKW run.
5. Model for the judge: Sonnet per the model split. Haiku for Stage 1 is a cost experiment
   only after Sonnet's ledger is the reference.

## 12. Evidence ledger

**RAN (this session, on this machine):**

- `claude.exe --version`, `claude.exe --help`, `claude.exe auth status`: outputs quoted in 5.1.
- `claude.exe -p ... --output-format json --model haiku --max-turns 1`, twice (with and
  without `CLAUDECODE`): both `is_error: true`, `Not logged in`, envelope fields listed in 5.3.
- PowerShell environment probe: `LLM_API_*` set at User scope, absent from the process
  environment; `CLAUDE_CODE_OAUTH_TOKEN` unset; no `~/.claude/.credentials.json`.
- `_scratch_llm_backend_probe.py` through `llm_backend.call_llm`, `LLM_BACKEND_FORCE=http`:
  1.3 s, `{"ok": true, "model_family": "Claude"}`.
- `_scratch_proxy_models.py`, `GET /v1/models`: one model, `glm-5.2`, `owned_by: openai`.
- Corpus size pass over 600 SVC-PC and 274 EKW task directories: table in 6.1.
- Globs over `SVC-PC-88-0-0/environment/`: no top-level files, no subtree-root files, zero
  matches for `*Workday*`, `*941*`, `*utover*`; `*econcil*` matches only bank/AR/AP and
  `Year_1_Actuals_Reconciliation.xlsx`; `*ayroll*` matches only the twelve monthly registers.
- Glob for `batch-scan-gates*` under `C:\ekwqc\repo\automation`: none; the file is under
  `EKW_QC_pipeline/automation/tp-fp-classification/`.

**READ (files, with the lines relied on):**

- `ekw/svc-pc-check-verification-manifest-2026-09-14.md`: lines 1-70, 132-201 (all four cases),
  164-178 (obj-01 nuance).
- `ekw/svc-oracle177-rootcause-phase0-synthesis-2026-09-14.md`: lines 52-120.
- `SVC-PC-92-0-0/instruction.md`, `tests/deliverables/judge.toml` (full).
- `SVC-PC-42-1-0/instruction.md`, `tests/deliverables_01..02/judge.toml` (full).
- `SVC-PC-80-7-0/instruction.md`, `tests/deliverables_01..05/judge.toml` (full).
- `SVC-PC-88-0-0/instruction.md`, `tests/deliverables_01..02/judge.toml` (full).
- `deterministic-checks/ekw_verifier_json.py`, `rubric_text_lint.py`,
  `extraction_groundedness_check.py`, `tools/llm_backend.py`, `content-audit/SKILL.md`,
  `structural-audit/SKILL.md`, `BUILD-CONTRACT.md`, `COVERAGE-MATRIX.md`, `README.md` (first
  110 lines), `CHANGELOG.md` lines 40-120, `.gitignore` (full).
- `automation/tp-fp-classification/batch-scan-gates.md` (full) and
  `C:\ekwqc\repo\automation\tp-fp-classification\SKILL.md` (full).
- `C:\ekwqc\_merged274\files\task_142\{instruction.md, tests/verifier.json}` (full),
  `task_17\instruction.md` (full), `task_17\tests\verifier.json` lines 1-160.
- Project memories `three-causes-of-svc-criterion-flipping.md`,
  `compound-expected-values-flip-between-runs.md`.
- `ekw/svc-qc-glm-key-setup-2026-09-14.md` (full), `ekw/svc-qc-sop-first-run-2026-09-14.md`
  lines 90-150.

**Not done, stated so it is not assumed:** no authenticated `claude -p` call; no Stage 1 or
Stage 2 prompt has been run against any task; no generation-time or rate-limit measurement;
no re-derivation of the manifest's numeric claims (the -27.3% basis, the -$0.01 residual);
no read of `certification_gate_check.py` or `criterion_groundedness_check.py`.
