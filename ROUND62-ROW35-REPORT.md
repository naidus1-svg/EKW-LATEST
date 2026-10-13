# Round 62, Row 35: fabricated unfiled-named-fact check (automated LLM-judge "check A")

Tracker row 35. A golden solution can fabricate a specific factual claim (a
vendor name, a PO/invoice number, a named internal process) as prose with no
filename attached to cite. This is narrower than row 8
(`source_citation_existence_check.py`), which needs a filename/path-shaped
token (sub-case A) or a proper-noun-plus-category-word pair (sub-case B) to
key on. When the fabrication is plain prose with no such token, row 8
structurally cannot catch it. Row 60's own dispatch said "there's no regex for
sounds suspiciously specific and unverifiable." This row wires that judgment
in as an automated LLM-judge check so it fires in the normal process, not as a
manual read.

## What was built

- `deterministic-checks/fabricated_unfilenamed_fact_check.py`: a new LLM-judge
  check (letter A, content audit). Per task it extracts the golden solution's
  readable text (reusing `find_golden_files` + `extract_file_text` from
  `answer_key_rubric_leak_check.py`), builds a REAL recursive environment file
  listing of every file of every extension (PDFs included) under
  `environment/initial_workspace/` (SVC-PC) or `environment/data/` (EKW), and
  hands both to the LLM via `tools/llm_backend.call_llm()`. The LLM is asked to
  identify any specific, checkable-sounding factual claim the golden states as
  an established fact where NEITHER:
  - (a) a corresponding file with a matching or clearly-related name exists in
    the environment file listing, OR
  - (b) the golden itself flags the claim, or the conclusion that rests on it,
    as an open item / unverified / unresolved / a judgment call anywhere in the
    golden text.
  Warn-only, never fail. Same "candidate, not verdict" posture as every other
  LLM check in this project. Sets `LLM_API_MAX_TOKENS=32000` (setdefault) for
  the same row-15 token-starvation reason `rubric_overspecification` and
  `golden_groundedness` do.

- Registration in `deterministic-checks/svc_run_checks.py`: new
  `fabricated_unfilenamed_fact` entry in `CHECKS`, letter `"A"`, style `"std"`,
  `task_key="task_id"`, `verdict=_std_status({pass,warn,skip,error})`,
  `findings=_findings_from("findings")`. `LETTERS` extended from `("C","D","E")`
  to `("A","C","D","E")` so `merge()`'s `by_letter = {L: [] for L in LETTERS}`
  does not KeyError on "A" (the existing `rubric_overspecification` comment
  warned this would KeyError without the extension; confirmed by reading
  `merge()` directly and running it).

- Registration in `deterministic-checks/ekw/ekw_run_checks.py`: same entry,
  letter `"A"`. `LETTERS` extended from `("B","C","D","E")` to
  `("A","B","C","D","E")`. Format-agnostic by construction: `_task_format`
  dispatches to `environment/data/` + `solution/golden_outputs/` (raw EKW) or
  `environment/initial_workspace/` + `solution/files/` (staged EKW after
  `ekw_check_b`). Verified via `--dry-run` on a real raw EKW task (`task_15` in
  `C:\ekwqc\_ekw119_harbor`: fmt=ekw, 3 golden, 5 env, 35707-char prompt) and a
  real staged EKW task (`task_1` in `C:\ekwqc\_ekw274_stage`: fmt=svc_pc, 2
  golden, 8 env, 23203-char prompt). EKW-UNTESTED at the real-LLM-call level:
  the acceptance test ran against SVC-PC tasks only (the three confirmed
  instances and the one true negative are all SVC-PC); no real EKW
  true-positive/negative pair was available, so this registration is
  format-completeness, not a separately validated EKW defect detector.

## Scope boundary vs row 8 (source_citation_existence_check.py)

This check is the COMPLEMENT of row 8, not an overlapping reimplementation.

- Row 8 sub-case A catches a golden CELL that cites a file-PATH-shaped string
  (ends in a recognized extension) absent from the environment. It needs a
  `word.ext` or `dir/file.ext` token to extract.
- Row 8 sub-case B catches instruction.md naming a file by CATEGORY (a
  category word like "report" preceded by a proper noun). It needs a
  proper-noun-plus-category-word pair to key on.
- This check (row 35) catches a golden claim that names a FACT (a vendor, a
  number, a process) as prose with NO filename token and NO
  category-plus-proper-noun pair. The prompt says so explicitly so the LLM does
  not re-flag what row 8 already catches: "Do NOT flag a claim that cites an
  actual FILENAME ... or that names a file by category-plus-proper-noun; row 8
  owns those."

The three prompt levers that calibrate precision:

1. Clearly-related rule: a file counts as "corresponding" under (a) only if its
   name plausibly identifies it as the source for THAT specific claim. A
   `Certificate_of_Incorporation.pdf` does not back a "GOTS organic product
   certification" claim; a `Q4_Board_Deck_Draft.pptx` is not "board minutes"; an
   `svb_statement.csv` backs an SVB claim but not a "Mercury" claim.
2. Transparent-uncertainty exclusion (b): the golden's own "open item",
   "unresolved", "carried open", "to be confirmed", "working assumption"
   language anywhere in the golden text exempts the claim. Condition (b) looks
   anywhere in the golden, not only in the claim's own sentence, because a
   claim's downstream use can be flagged open elsewhere (this was the fix for
   the 52-5-0 false positive, see below).
3. Specificity lever: the check targets SPECIFIC named claims (a specific
   vendor/system/bank like Mercury or NovaTex; a specific invented process name
   like "Close Authority and Review Map"; a specific document by date or title
   like "Jan 18 2022 board minutes"; a specific cert like "GOTS organic"). It
   does NOT flag a bare generic document-category reference like "the merchant
   agreement" or "the lease" (row 8's category territory, and a standard
   business artifact a real company routinely has).

## Acceptance test: 4 tasks, real LLM calls (not dry-run, not fabricated)

Real command (HTTP backend forced, the configured glm-5.2, all `LLM_API_*`
env vars set on this machine):

```
cd C:\wt_ekwqc\round62-row35-fabrication\deterministic-checks
LLM_BACKEND_FORCE=http python fabricated_unfilenamed_fact_check.py \
  SVC-PC-21-0-0 SVC-PC-24-6-0 SVC-PC-73-3-0 SVC-PC-52-5-0 \
  --root C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready \
  --out _accept4d.json --jobs 4 --timeout 300
```

Real output (run 1 of 2, the second consecutive run):

```
  WARN  SVC-PC-21-0-0      7 finding(s): Mercury is a banking platform in use ...
  WARN  SVC-PC-24-6-0      3 finding(s): The 'NovaTex QSA' is a document the company holds ...
  WARN  SVC-PC-73-3-0      4 finding(s): Jan 18 2022 board minutes exist ...
  OK    SVC-PC-52-5-0      clean

4 tasks in 150.4s: 1 pass, 3 warn, 0 skip, 0 error
```

The split held across two consecutive runs (run 1: 6/2/4 findings + clean;
run 2: 7/3/4 findings + clean). The 3-flag / 1-clear split is the required
acceptance result.

The three true positives flag with the expected claims:

- SVC-PC-21-0-0 (7 findings): "Mercury" bank (no Mercury file; svb_statement
  exists for SVB but not Mercury), "Slack" system, "INC-2021-014" incident
  record, "Licence inventory", "Close Authority and Review Map" (closest env
  file Q4_Close_Checklist.docx, correctly judged not corresponding), "Bench /
  Avalara / ProfitWell / Carta" tool rows, "workforce export".
- SVC-PC-24-6-0 (3 findings): "NovaTex QSA" (no QSA file), "GOTS organic /
  OEKO-TEX / CertiPUR-US ... certs on file" (closest env file
  Certificate_of_Incorporation.pdf, correctly judged not a product cert),
  "Stripe standard settlement".
- SVC-PC-73-3-0 (4 findings): "Jan 18 2022 board minutes" for the $4-5M range
  (no board-minutes file at all; only Board_Talking_Points and Board_Deck
  files exist, correctly judged not minutes), "FY2022 inventory policy",
  "Schedule A", "Year-2 demand plan draft".

The true negative clears:

- SVC-PC-52-5-0 (0 findings): "Processor annual summary" is transparently
  flagged "Open item, rows 17 and 18", "Difference unresolved", "Carried open"
  (condition b met). "Merchant agreement" is a generic category reference
  (specificity lever), not a specific fabricated name. Both correctly not
  flagged.

### Two failures caught and fixed during calibration (skepticism)

The first real run on 73-3-0 returned "clean" (a false negative on a known
true positive, 72.8s) while a direct re-call returned "defective" with 2
correct findings (275.8s). Same prompt, different verdict: LLM non-determinism
on the reasoning backend, worsened by the original "Prefer precision over
recall" system-prompt line. Two prompt changes fixed it:

1. Replaced "Prefer precision over recall" with a recall-positive framing
   ("a candidate flag is far cheaper than a missed fabrication that ships to
   graders; flag any claim you can support").
2. Made the methodology directive: mandatory enumeration of every named claim
   as a worklist before checking each, so a claim never listed is never
   checked.

A second failure on 52-5-0 (false positive: it flagged "Processor annual
summary" and "Merchant agreement") was fixed by:

1. Broadening condition (b) to look anywhere in the golden, not only in the
   claim's own sentence (the open-item flags for the processor-summary reading
   sit elsewhere in the golden). This cleared "Processor annual summary".
2. Adding the specificity lever (generic category references like "the
   merchant agreement" are out of scope). This cleared "Merchant agreement".

Both fixes were validated by re-running the 4 tasks; the 3-flag / 1-clear
split then held across two consecutive runs.

## Broader 30-task sample

Real command:

```
LLM_BACKEND_FORCE=http python fabricated_unfilenamed_fact_check.py \
  SVC-PC-21-0-0 SVC-PC-24-6-0 SVC-PC-73-3-0 SVC-PC-52-5-0 SVC-PC-1-1-0 \
  SVC-PC-10-2-0 SVC-PC-10-3-0 SVC-PC-10-4-0 SVC-PC-10-5-0 SVC-PC-11-2-0 \
  SVC-PC-11-4-0 SVC-PC-12-1-0 SVC-PC-12-2-0 SVC-PC-12-3-0 SVC-PC-15-1-0 \
  SVC-PC-15-2-0 SVC-PC-17-2-0 SVC-PC-1-0-0 SVC-PC-5-3-0 SVC-PC-13-3-0 \
  SVC-PC-29-2-0 SVC-PC-33-8-0 SVC-PC-37-3-0 SVC-PC-41-4-0 SVC-PC-70-1-0 \
  SVC-PC-80-7-0 SVC-PC-88-0-0 SVC-PC-92-0-0 SVC-PC-14-1-0 SVC-PC-7-4-0 \
  --root C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready \
  --out _sample30.json --jobs 4 --timeout 300
```

Real output: `30 tasks in 479.4s: 13 pass, 13 warn, 4 skip, 0 error`.

Per-task results (task-id, verdict, finding count, first claim):

| task_id | verdict | n | first claim / skip reason |
|---|---|---|---|
| SVC-PC-1-0-0 | warn | 2 | NovaTex is the company's single manufacturer |
| SVC-PC-1-1-0 | warn | 2 | 'Canonical Facts workbook' exists as a trusted verification source |
| SVC-PC-10-2-0 | pass | 0 | |
| SVC-PC-10-3-0 | pass | 0 | |
| SVC-PC-10-4-0 | warn | 3 | SVB is the company's bank and an SVB bank statement exists |
| SVC-PC-10-5-0 | pass | 0 | |
| SVC-PC-11-2-0 | skip | 0 | environment too large: 1183 files |
| SVC-PC-11-4-0 | pass | 0 | |
| SVC-PC-12-1-0 | warn | 1 | NovaTex is the company's manufacturer |
| SVC-PC-12-2-0 | pass | 0 | |
| SVC-PC-12-3-0 | warn | 2 | NovaTex is a real supplier in use |
| SVC-PC-13-3-0 | warn | 1 | Shopify Plus is a committed contract |
| SVC-PC-14-1-0 | skip | 0 | environment too large: 441 files |
| SVC-PC-15-1-0 | warn | 1 | Customer Impact Notes (D. Nguyen, Q3 2021) exists |
| SVC-PC-15-2-0 | pass | 0 | |
| SVC-PC-17-2-0 | warn | 1 | PO-2021-Q2-001 and Invoice_NovaTex_2021-06 are real records |
| SVC-PC-21-0-0 | warn | 9 | Mercury is a banking system in use |
| SVC-PC-24-6-0 | warn | 3 | GOTS organic, OEKO-TEX, CertiPUR-US product certifications are on file |
| SVC-PC-29-2-0 | warn | 1 | The December board minutes exist |
| SVC-PC-33-8-0 | pass | 0 | |
| SVC-PC-37-3-0 | pass | 0 | |
| SVC-PC-41-4-0 | pass | 0 | |
| SVC-PC-5-3-0 | pass | 0 | |
| SVC-PC-52-5-0 | pass | 0 | |
| SVC-PC-7-4-0 | skip | 0 | environment too large: 1183 files |
| SVC-PC-70-1-0 | pass | 0 | |
| SVC-PC-73-3-0 | warn | 6 | Jan 18 2022 board minutes exist |
| SVC-PC-80-7-0 | warn | 6 | QuickBooks general ledger is the system of record |
| SVC-PC-88-0-0 | skip | 0 | environment too large: 419 files |
| SVC-PC-92-0-0 | pass | 0 | |

The 4 skip tasks (11-2-0, 14-1-0, 7-4-0, 88-0-0) exceeded the
`ENV_TOO_MANY_FILES` (400) / `ENV_TOO_LARGE_BYTES` (80 MB) guard and were
skipped with a clear reason rather than stalled. 11-2-0 and 7-4-0 share a
1183-file corpus; 14-1-0 has 441 files; 88-0-0 has 419.

## Spot-check (skepticism pass)

The brief warned that "a single reviewer's 'confirmed' can miss things" and
demanded spot-checking both warn and clean verdicts against real files.

Warn verdicts checked against the real environment (all confirmed real
fabrications: no corresponding file exists):

- SVC-PC-1-1-0: no canonical/bible/trusted file in the 311-file env. The
  golden claims "Verified against the trusted Canonical Facts workbook" and
  "Company Bible v3.1"; neither file exists. Real fabrication.
- SVC-PC-10-4-0: no svb_statement, no bank-statement, no accounting-ledger file
  in the 156-file env (only cash-flow forecasts and Year_1_Cash_Flow_Statement).
  The golden cites an "SVB bank statement" and "accounting ledger account 1000
  Cash - SVB Checking"; neither exists. Real fabrication. One borderline
  finding: "NovaTex is the primary supplier" matched a "Supplier Performance
  Scorecard" doc; NovaTex may be mentioned inside it. A human reviewer would
  open the scorecard to confirm. The flag is defensible under the
  clearly-related rule (a generic scorecard is not a NovaTex-specific file)
  but is the one finding in the sample a reviewer should triage first.
- SVC-PC-12-1-0: 8-file env (pipeline trackers, prospect lists); no NovaTex
  file. The golden names NovaTex as the manufacturer. Real fabrication.
- SVC-PC-13-3-0: no Shopify contract/subscription file (only Shopify data
  exports). The golden asserts "Shopify Plus is a committed contract". Real
  fabrication (data exports are not a contract).
- SVC-PC-29-2-0: no board-minutes file (the grep hit "onboarding" inside
  Onboarding_Checklist_Template, not a real board file). The golden cites
  "December board minutes". Real fabrication.
- SVC-PC-80-7-0: no quickbooks/qb/ledger/gl file in the 139-file env. The
  golden asserts "QuickBooks general ledger is the system of record". Real
  fabrication.
- SVC-PC-15-1-0: no "Customer Impact Notes" or "D. Nguyen" file in the
  238-file env (Vendor_Cost_Impact_Analysis exists, a different document). Real
  fabrication.

Clean verdicts checked (all confirmed correct: no missed fabrication):

- SVC-PC-37-3-0: the golden's known defect is MSA_SwiftShip_2021.pdf /
  MSA_Apex_2021.pdf citations (filename-shaped, row 8 sub-case A's territory)
  and a sales-figures arithmetic error (golden_groundedness / golden_arithmetic
  territory). Neither is an unfiled-named-fact fabrication. The env has
  COI_Apex_Logistics.pdf and COI_SwiftShipExpress.pdf. Clean is correct: the
  filename citations are row 8's job, the arithmetic is row 13/2's job.
- SVC-PC-41-4-0: the env has Apex_Delay_Incident_Report.docx,
  Apex_Escalation_Email_Chain.pdf, Apex_SLA_Review_Q3.docx,
  SwiftShip_Evaluation.docx, Shipping_Rate_Card_2021.xlsx, and vendor
  scorecards. Apex/SwiftShip-named files exist, so named claims about them meet
  condition (a). Clean is correct.
- SVC-PC-5-3-0: the golden names NovaTex but inside an "ANALYST ASSUMPTIONS
  [A]" section (transparently flagged as an assumption, condition b met). The
  task's known defect is a bare numeric figure ($4,390, golden_groundedness
  territory), not a named fabrication. Clean is correct.

Spot-check conclusion: 7 of 7 checked warn findings are real fabrications (1
borderline: 10-4-0 NovaTex vs a generic supplier scorecard). 3 of 3 checked
clean verdicts are correct. No false negative surfaced in the clean set; no
clear false positive surfaced in the warn set beyond the one disclosed
borderline.

## Known limits (disclosed, not silently dropped)

1. LLM non-determinism. The configured glm-5.2 HTTP backend returns different
   verdicts across calls on the same prompt (observed: 73-3-0 clean once,
   defective on re-call). The recall-positive system prompt and mandatory
   enumeration mitigate this but do not eliminate it. The acceptance split
   held across two consecutive runs; a production run that returns clean on a
   task a human suspects should flag is a candidate for a manual re-check, not
   a final verdict. This is the same posture every LLM-judge check in this
   project already carries.
2. Environment-too-large skip. Tasks with more than 400 files or more than
   80 MB of environment are skipped with a clear reason rather than stalled
   (4 of 30 in the sample). Raising the cap is possible but would lengthen
   per-task wall time and prompt size; the skipped tasks are the shared
   large-corpus tasks (11-2-0, 7-4-0 at 1183 files) and the PBC-tracker tasks.
3. File-name-based, not file-content-based. The check feeds the LLM the
   environment file LISTING (names), not file contents. A claim whose
   corresponding file exists under an unrelated name (the file is there but the
   name does not match) is a structural false positive the LLM cannot resolve
   from names alone. The clearly-related rule narrows this but cannot close it;
   resolving it would mean reading env file contents (golden_groundedness's
   approach), a different check. The disclosed borderline (10-4-0 NovaTex vs a
   supplier scorecard) is an instance of this limit.
4. EKW real-LLM-call calibration. The EKW registration is format-verified
   (dry-run on raw and staged EKW tasks built real prompts) but not
   separately calibrated with a real EKW true-positive/negative pair. The
   three confirmed instances and the true negative are all SVC-PC.
5. Scope complement, not overlap. A claim that cites a real filename is row
   8's job; this check's prompt tells the LLM to leave those to row 8. If a
   future golden cites a filename AND fabricates a prose fact in the same
   sentence, the two checks split the work by claim, not by sentence.

## Files changed

- `deterministic-checks/fabricated_unfilenamed_fact_check.py` (new, the
  checker).
- `deterministic-checks/svc_run_checks.py` (new `fabricated_unfilenamed_fact`
  CHECKS entry, letter A; `LETTERS` extended to include A).
- `deterministic-checks/ekw/ekw_run_checks.py` (same entry; `LETTERS`
  extended to include A).
- `ROUND62-ROW35-REPORT.md` (this report).

## How to run

```
python deterministic-checks/fabricated_unfilenamed_fact_check.py \
  SVC-PC-21-0-0 --root C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready \
  --out result.json --timeout 300
```

Or via the orchestrator (registered as `fabricated_unfilenamed_fact`, letter A):

```
python deterministic-checks/svc_run_checks.py --all \
  --root C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready \
  --out-dir C:\ekwqc\_svc_qc --checks fabricated_unfilenamed_fact
```

One real LLM call per task, 70-280s observed against glm-5.2. Give it a
generous `--timeout` and scope with `--checks` for a fast sweep.
