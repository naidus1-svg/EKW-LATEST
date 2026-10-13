"""Fixed prompts for the F1, F2 and F3 AI-reader parts of sixq_checks.py.

Frozen: the sha256 of this file is recorded before any model call. Do not edit without
re-hashing. The prompts see the instruction (numbered lines) and the grading rules only.
"""

COMMON = """You are checking a benchmark task before it is submitted. A task has an instruction
(written for an AI solver) and grading rules (each rule is a pass/fail test worth a weight).
You are given the instruction with line numbers and the rules with ids.
Answer ONLY with one JSON object, no prose before or after it.
Quote at most 15 words from any text. Use the rule ids exactly as given."""

F1 = COMMON + """

Question: does any rule fail an answer that is correct? Think of a careful expert's correct
answer in another valid form: different rounding or units, different ordering, different sheet
or file naming, different spelling or wording, a different but valid method. For each rule that
would lose such an answer, give the rule id, the other valid form in one sentence, and the part
of the rule text that causes it. Report only rules where you can name a concrete other form.

JSON: {"flags": [{"rule": "<id>", "other_form": "<one sentence>", "rule_quote": "<=15 words"}]}
Empty list if none."""

F2 = COMMON + """

Question: does any rule ask for something the instruction never requested? For each rule, find
the instruction sentence that asks for what the rule requires (a word limit, a count of fields,
a layout, a threshold, an extra scenario, a name, a format). If there is no such sentence, report
the rule. Do not report a rule whose required value is a result the solver must compute from
the inputs, as long as the instruction asks for that result.

JSON: {"flags": [{"rule": "<id>", "unrequested": "<what the rule requires that the instruction does not ask, one sentence>", "nearest_instruction_line": <line number or null>}]}
Empty list if none."""

F3 = COMMON + """

Question: can a careful reader take an instruction sentence another way, so that a rule would
then fail a correct answer? For each heavy rule, find the instruction sentence it depends on,
write the other reading a careful expert could take (period, scope, definition, which file,
which rounding), and say whether an answer following that reading would still earn the rule.
Report only the rules that would lose it.

JSON: {"flags": [{"rule": "<id>", "instruction_line": <line number>, "other_reading": "<one sentence>", "loses_rule": true}]}
Empty list if none."""

PROMPTS = {"F1": F1, "F2": F2, "F3": F3}
