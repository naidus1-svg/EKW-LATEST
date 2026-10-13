You are a manager reviewing a benchmark task before it is sent to the external QC team. Apply the manager's version 2 rules to the task package in your current directory and decide APPROVE or DENY. You have no solver runs and no AI review results, only the package: instruction.md (the prompt the AI solver gets), the input files (environment/ or initial_workspace/), the golden answer (solution/), and the grader (tests/: verifier.json with criteria and weights, or tests/deliverables_NN/judge.toml files, plus scripts). A criterion is one pass/fail line of the grader.

Call a defect Major only if a prompt-following answer loses credit because of it, or a wrong or empty answer gains credit because of it. Everything else is Minor.

Tier A: correctness and fairness. These can DENY (when Major):
A1. The answer key has a factual error, or contradicts the source files, or contradicts itself across checks. Apply only after reading the source text.
A2. A check requires something that neither the prompt nor the sources ask for.
A3. A judge must check facts against files it is not given, and the check text does not carry the values it needs.
A4. The grading script can crash and give no score.
A5. Graders gave different results on the same answer in runs. NOT CHECKABLE from the package: do not deny on it.
A6. A major issue in an AI review that is not fixed. NOT CHECKABLE from the package: do not deny on it.
A7. A correct answer written differently fails: an exact filename or exact wording is required, or a band excludes a valid alternative the prompt leaves open.

Tier B: rubric hygiene. Report these as optional fixes; they do NOT cause a DENY:
B1. One check grades many separate facts at once.
B2. The same fact is graded in two checks with no note saying which one owns it.
B3. Wording a judge could read two ways.

Verdict: DENY if any Tier A rule fires on a Major defect; otherwise APPROVE (and list Tier B findings).

Method: read instruction.md and list its requirements; read every criterion in the grader in full (every file under tests/); for each criterion find the instruction sentence that justifies it; read the golden and inputs when a criterion depends on a value. Quote at most 15 words from any file. Do not modify any file. Every finding needs the rule, the criterion id and weight, and the evidence.

Final answer: one JSON object only, in a fenced block:
{"verdict": "APPROVE" or "DENY", "tier_a": [{"rule": "A2", "criteria": ["id"], "weight": <share or null>, "evidence": "instruction: ... | criterion: ... | source: ..."}], "tier_b": [{"rule": "B1", "criteria": ["id"], "evidence": "..."}]}
