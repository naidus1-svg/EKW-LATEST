"""Answer-key rubric leak check: does a criterion's grading text (its Expected:
description or rubric prompt) near-verbatim-copy the task's own golden/reference
answer content, rather than independently describing the checkable property?

Why this exists as its own check (not folded into the two existing answer-key
checks in this folder): those two check two DIFFERENT leak surfaces.
`answer_key_leakage_check.py` scans the solver-facing PROMPT (instruction.md)
for GOLDEN-named filenames and internal pipeline jargon (structural-audit
pattern 4). `answer_key_content_leak_check.py` checks whether the rubric's
literal EXPECTED VALUES (numbers, dates, dollar amounts) appear verbatim in
solver-visible ENVIRONMENT files (the inputs the solver is handed). Neither
of them checks what THIS script checks: whether the rubric's own PROSE -- the
sentences, reasoning, and explanatory wording a criterion uses to describe what
to verify -- copies the golden answer's own prose rather than restating the
check independently. That is Andrew Ma's pattern 6 ("Reference copies the
answer key or leaks the rubric," 7/19 tasks, zero deterministic coverage before
this check). A rubric that quotes the golden's own wording is a different
mechanism from a rubric that names a golden file (leakage_check) or one whose
expected numeric values appear in a solver-visible file (content_leak_check):
it is TEXT OVERLAP between the rubric and the golden solution content, not a
naming tell or a value match.

What it checks, mechanistically: for each grading criterion (SVC-PC
judge.toml's [[criterion]].description, EKW verifier.json's
assertion.rubric.prompt), tokenize the full criterion text into lowercase
word-tokens. Separately, extract every text-bearing golden file under the
task's solution directory (SVC-PC: solution/files/; EKW:
solution/golden_outputs/) and tokenize each file the same way. Find maximal
runs of consecutive matching word-tokens between the rubric text and each
golden file's tokens. A run long enough and content-dense enough to be
unlikely coincidental (calibrated below) is flagged.

Calibration against the real corpus (required before this script was
finalized; see the report at
ekw/pipeline-mirror/results/round12-item1-answer-key-leak-2026-09-15.md for
the full calibration log):

  The available mirrored corpora with BOTH rubric and golden content are:
    - svc-task-samples-27-full/ : 27 SVC-PC tasks, each with
      tests/deliverables*/judge.toml AND solution/files/ golden files
    - ekw-task-samples/task_*-full-for-verifier-execution/ : 4 EKW tasks, each
      with tests/verifier.json AND solution/golden_outputs/
  The svc-task-samples-56/ corpus (56 tasks) has judge.toml but NO solution/
  directory, so there is no golden to compare against; those tasks report
  skip. The full 600-task SVC-PC and 274-task EKW corpora referenced by the
  existing checks' calibration sections live at C:/ekwqc/... paths not present
  on this build machine; this check runs against whatever --root it is given.

  Real positive example found and used to calibrate the threshold:
    SVC-PC-14-6-0 criterion c07: the rubric says "sole finance/accounting role
    is Jessica Liu, FP&A Analyst (hired 2021-08-09, reports to Sarah Kim,
    COO)" and the golden Cirrus_FY2021_Control_Gap_Register.xlsx says "The
    only finance/accounting role is Jessica Liu, FP&A Analyst (hired
    2021-08-09, reporting to Sarah Kim, COO)." The rubric copies the golden's
    own wording verbatim (11 consecutive matching word-tokens, 8 content
    words). This is a genuine pattern-6 instance: the rubric quotes the
    golden's prose rather than independently describing what to check.

  Real negative examples confirmed as NOT flagged (not leaks):
    - SVC-PC-7-2-0 str-03: rubric says "Cash is a live formula (prior cash +
      net income +/- WC adjustment)" and the golden says "Cash is a formula =
      prior cash + net income + WC adjustment every period." Both describe the
      same mathematical formula using the same labels. The matching run is
      7 tokens / 7 content words, which falls below the candidate threshold
      (run >= 8). This is natural overlap, not copying.
    - SVC-PC-7-4-0 o5: rubric states expected values "NovaTex $782,769; Sierra
      $338,011; Apex $244,800; ..." which also appear in the golden. The
      matching run is 12 tokens but 50% pure-numeric (vendor-name + dollar
      amount pairs), so the numeric-ratio filter (> 0.4) excludes it. This is
      expected-value matching, which a rubric is supposed to do.

  Threshold chosen from this calibration:
    - CANDIDATE (warn, human-review): run >= 8 consecutive matching
      word-tokens, >= 6 content words (non-stopword, non-numeric), and <= 40%
      pure-numeric tokens. Below the flagged bar but worth a human glance.
    - FLAGGED (fail): run >= 9 consecutive matching word-tokens, >= 7 content
      words, and <= 40% pure-numeric tokens. At this level, the matching text
      is long enough and prose-dense enough that independent restatement in
      the same words is implausible for anything but a copy.

  Why the numeric-ratio filter exists: a rubric legitimately states expected
  values (SVC-PC's "Expected:" clause, EKW's "the correct value is $25.93"),
  and those values appear in the golden. A matching run that is mostly
  dollar amounts and percentages (like the vendor spend list) is
  expected-value matching, not prose copying. Excluding runs where > 40% of
  tokens are pure-numeric removes this class of false positive while keeping
  prose runs that happen to contain an occasional number (like "jessica liu,
  fp&a analyst hired 2021-08-09" which is 1 numeric token out of 11, ratio
  0.09).

  2026-09-15 update -- the expected-value clause filter (generalizing the
  numeric-ratio filter to non-numeric expected values):

  A read of 218 findings across 56 real SVC-PC tasks (the round-12 triage)
  reported zero real leaks and 218 false positives, all of one shape: the
  numeric-ratio filter has no equivalent for a non-numeric expected value.
  The corpus-wide convention is "<rationale>. Expected: <exact required
  fact>.", and the numeric filter only recognizes the "<exact required
  fact>" part as legitimate when that fact happens to be a number. When it
  is a name, an entity list, a categorical/enum field, a verdict sentence,
  or a locked/given source quote, the OLD filter had no carve-out and the
  "Expected:" clause matched the golden it is quoting on purpose -- which
  is exactly what a rubric is supposed to do.

  CORRECTION (2026-09-15, after this filter shipped): the round-12 triage's
  "zero exceptions" claim above does not hold. A full re-validation -- the
  fix below actually applied and re-run against the same 56 tasks, not a
  re-read of the same findings -- resolved only 27 of the 56 tasks (146 of
  218 findings) cleanly. The other 29 tasks (72 findings, 28 flagged + 1
  candidate) are a DIFFERENT, still-unresolved shape: near-verbatim overlap
  between a criterion's own RATIONALE SENTENCE (the text BEFORE "Expected:",
  never covered by the clause_ratio exemption below) and the golden's prose.
  Whether those 29 hold real leaks is not yet determined.

  SECOND CORRECTION (2026-09-15, later the same evening -- an adversarial
  verifier caught this before merge, PR #42 is unmerged and flagged DO NOT
  MERGE pending a real fix): the first correction above wrongly cited
  SVC-PC-14-6-0 c07 as an example of the 29-task before-the-label shape. Run
  the actual code against it and the citation is backwards: c07's leaked
  text sits AFTER "Expected:" and clause_ratio=1.0 -- it IS covered by the
  exemption, meaning the exemption wrongly clears this file's own documented
  genuine-positive calibration example to zero findings. A second confirmed
  real leak, SVC-PC-67-1-0 r011, is wrongly cleared the same way: a long,
  discursive "Expected:" clause (rubric-authoring meta-commentary plus a
  near-verbatim data-quality finding lifted from the golden's reasoning
  trace) gets exempted in full because SOME of it is legitimate. This is the
  exact residual risk this docstring already disclosed as a hypothetical
  two paragraphs below ("nothing stops a future criterion from writing the
  golden's entire reasoning paragraph as its clause content") -- except it
  is real, in the 56-task sample, not hypothetical. The position-based
  design (trust everything after the label) is not a safe filter on its own
  when the labeled clause is long/discursive rather than a terse declared
  fact; it needs either a length/density cap or a different signal entirely.
  Not yet fixed as of this docstring edit. Full detail, including which 6 of
  a 9-task spot-check DID resolve correctly: turing-genai-apps/EKW_QC_pipeline#42.

  THIRD CORRECTION (2026-09-15, the fix for the regression the SECOND
  CORRECTION above disclosed but did not yet resolve): the bug was the
  clause_ratio exemption trusting the ENTIRE labeled "Expected:" clause once
  found, with no signal distinguishing "this clause IS the terse declared
  answer" from "this clause is long/discursive and a real leak is embedded
  inside it." A length or token-count cap on the clause -- the first fix
  tried -- was measured against the real examples and discarded: SVC-PC-93-5-0
  rc-17's Expected: clause (51 tokens, correctly stays exempt) is the SAME
  length as SVC-PC-14-6-0 c07's (51 tokens, must be flagged). No cap value
  separates these two real clauses; the signal cannot live on the clause's
  own length.

  What does separate them, checked against all eight real examples in this
  section plus two more confirmed patterns below (SVC-PC-10-5-0 c01's quoted
  field assignment, SVC-PC-11-4-0 r008's locked quote): whether the MATCHED
  RUN ITSELF -- not the whole clause, just the specific span of tokens that
  overlaps the golden -- contains a copula (is/are/was/were/be/been/being;
  COPULA_TOKENS) outside a quoted span. c07's run ("...role is Jessica Liu,
  FP&A Analyst...") and SVC-PC-67-1-0 r011's run ("...line 1 is empty in all
  6,000 master rows and every address field...is...") both assert a fact in
  subject-is-predicate form. None of the six confirmed-correct runs do (they
  are bare enumerations: two name lists, a column-schema list, a control-ID
  checklist, a numeric range table) -- rc-17's own matched run is just "Drift
  Ventures, Oakmont Capital, J. Whitfield, and P. Saito," the name list
  alone, even though the SENTENCES around it in the full clause are
  narrative ("a distinct investor notice is released only after..."). The
  signal has to live on the run, not the clause, because the same clause can
  carry both a legitimate list and narrative scaffolding around it, and only
  the run's own content says which one actually matched the golden.

  A plain verb check (not restricted to copulas) was tried and rejected on
  the same evidence: SVC-PC-26-4-0 r5's correctly-exempted run contains
  "exceeds" ("WC build...exceeds $120K allowance") and SVC-PC-8-7-0 b2's
  correctly-exempted run (the locked vision quote) contains "sleeps" and
  "made." Both would be wrongly un-exempted by a general verb rule. A copula
  is categorically different: it is the grammatical core of an
  identity/state assertion and is never itself a value or a list item, so
  restricting to COPULA_TOKENS catches both confirmed leaks while leaving
  both of these correctly-exempted verb-bearing runs alone.

  The quote-span carve-out (QUOTE_SPAN_RE, find_quoted_token_mask) exists
  because a copula CAN legitimately appear inside a locked value: SVC-PC-10-
  5-0 c01's Expected: results.board_conclusion.conclusion="The approved
  desired committed build is affordable without financing..." quotes the
  golden's own conclusion sentence verbatim, copula included, exactly the
  way SVC-PC-8-7-0's vision quote does. Verified directly: without the
  carve-out, the copula rule alone would wrongly flag this confirmed-correct
  example (its longest matched run, 36 tokens, contains both "is" and "would
  be"); with the carve-out, that run's has_unquoted_copula is False because
  every copula in it sits inside the quoted field value.

  Full validation, all re-run against the actual fixed code (not assumed):
  both confirmed leaks (SVC-PC-14-6-0 c07, SVC-PC-67-1-0 r011) flip from
  clause_ratio-exempted (tier=None) to flagged. All six confirmed-correct
  resolutions (SVC-PC-16-1-0 r010/r011, SVC-PC-93-5-0 rc-03/rc-17,
  SVC-PC-8-7-0 b2, SVC-PC-75-6-0 d1, SVC-PC-9-4-0 z05, SVC-PC-26-4-0 r5) and
  the two extra confirmed-pattern examples (SVC-PC-10-5-0 c01, SVC-PC-11-4-0
  r008) stay exempt. The borderline case, SVC-PC-71-0-0 c19 ("no orphan
  headline" vs. the golden's "no orphan figures"), has no copula in its
  matched run and stays exempt under the fix -- a considered call, not just
  the mechanical answer: "orphan" here is standard data-lineage vocabulary
  both texts use to describe the same checkable property (a complete trace
  with no unmapped items), the same shape as the very first v1 calibration
  negative (SVC-PC-7-2-0 str-03 above, "both describe the same mathematical
  formula using the same labels"), not a narrative finding lifted from the
  golden's reasoning.

  Full corpus re-run, same 600-task root as the v2 calibration
  (C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready), before vs. after
  this fix: 470->453 clean, 32->38 candidate, 97->108 flagged, 1->1 skip, 0
  errors either run. 18 tasks change status, all 18 strictly TOWARD more
  scrutiny (clean->candidate, clean->flagged, or candidate->flagged) and
  zero the other direction -- expected, since the fix only narrows an
  existing exemption (adds an AND clause to it) and cannot re-exempt
  anything the old code already scored. n_criteria, n_golden_files, errors,
  and parse_errors are byte-identical between the two runs across all 600
  tasks, confirming the change is isolated to finding classification and
  touches nothing else. 161 individual findings newly surface across those
  18 tasks; spot-checked against their live judge.toml text (not just the
  matched-token snippet), several are clear, previously-uncaught genuine
  leaks of exactly the shape this correction targets -- e.g. SVC-PC-56-0-0
  r054's Expected: clause is the MSA's actual contract language
  ("Manufacturer represents that it holds and shall maintain in good
  standing the certifications required for the Products, including GOTS...
  Loss of any such certification shall be a material breach") copied in
  place of a description of that clause, and SVC-PC-13-4-0 o02's Expected:
  clause is a full copied analytical argument for why a blended COGS figure
  would misrepresent mismatched bases. Neither was caught before this fix;
  both should have been.

  Confirmed real examples (each pulled from a live judge.toml under
  C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready, not invented):
    - named-entity checklist: "Expected: Sarah Kim, Marcus Rivera, Jessica
      Liu, Tom Baker, Alice Chen, Michelle Adams, James Okafor, David
      Nguyen, Priya Patel." (SVC-PC-16-0-0)
    - structured field assignment: "Expected: results.board_conclusion.
      conclusion=\"The approved desired committed build is affordable
      without financing...\"" (SVC-PC-10-5-0, one of the 56)
    - locked/given source quote: "Expected: 'ran lean in Year 1' why-now; no
      hype/superlatives." (SVC-PC-11-4-0)

  A corpus-wide scan (2026-09-15, all 23,220 SVC-PC criterion descriptions
  under the same root) confirms this is THE labeling convention, not one of
  several: 23,202 (99.9%) contain "Expected:"; zero contain "Threshold:" or
  a literal "must-pass:" as a VALUE LABEL without "Expected:" earlier in the
  same description (Threshold: is always a scoring-band continuation of the
  same Expected: clause -- "Expected: 35,000+. Threshold:3/3 = full 4;
  2/3 = 2 pts; ..." -- never a standalone value label; "this is a must-pass
  criterion" is always a trailing boilerplate SENTENCE, never a "must-pass:"
  label). The remaining 18 descriptions (0.1%) genuinely have no single
  stated fact to label (process/qualitative criteria like "A
  hosted-versus-managed recommendation is given per platform layer, each
  with a stated rationale...") -- a real absence of the convention, not a
  missed spelling of it.

  The fix (find_expected_clause_token_start(), plumbed through
  find_matching_runs() as rubric_clause_start and read by classify_run() as
  clause_ratio): locate the character offset of the first "Expected:" label
  in the criterion's own description text, convert it to a token index, and
  for every matching run record what fraction of THAT RUN's own tokens sit
  at or after that index. A run that is >= --min-clause-ratio (default 0.6)
  covered by the labeled clause is exempted at any tier, the same way a run
  that is > --max-numeric-ratio numeric is exempted -- two independent
  signals for the same underlying fact (this text is the rubric's own
  declared answer, not copied prose), either one sufficient on its own. This
  generalizes the numeric filter's intent rather than special-casing string
  types: the next non-numeric expected-value shape needs a new example in
  EXPECTED_VALUE_LABEL_PATTERNS, not a new special case in classify_run().

  UPDATED by the THIRD CORRECTION below: "either one sufficient on its own"
  is no longer quite true for the clause_ratio side by itself. As shipped
  that same day, clause_ratio >= --min-clause-ratio cleared a run
  regardless of what was actually inside it, which is the regression the
  THIRD CORRECTION fixes. Read clause_ratio's exemption as "clause_ratio >=
  --min-clause-ratio AND the run contains no unquoted copula" from that
  point on; the numeric-ratio exemption is untouched and still stands alone.

  Deliberately NOT done: no separate label was added for "Threshold:" or
  "must-pass:" because the corpus scan found neither ever stands alone
  (see above) -- adding one would be guessing at a shape with zero real
  instances to calibrate against. No EKW-specific label (e.g. the
  "Verify (via <comparison> at <path>): <expected>" shape
  ekw_verifier_json.py's _describe_verifier() can synthesize for
  assertion.type == "deterministic") was added either: no live EKW verifier
  corpus was available on this machine to confirm that shape against a real
  verifier.json, only against the source that generates it, which is a
  hypothesis, not a confirmed example. EKW tasks whose rubric.prompt text
  happens to use "Expected:" already benefit from this filter unchanged;
  EKW tasks that do not are scored exactly as before (rubric_clause_start is
  None, clause_ratio is always 0.0, no behavior change).

  Residual risk, disclosed rather than silently accepted: this filter, like
  the numeric one it generalizes, trusts the ENTIRE labeled clause once it
  finds the label, with no upper bound on the clause's own length or prose
  density. The real corpus does not exhibit this (the "Expected:" clause is
  short: median 48 characters, mean 91, across all 23,202 real instances;
  the single outlier at 2,183 characters is still a dense enumerated list of
  actual expected values, not copied golden narrative). But nothing stops a
  future criterion from writing "Expected: <the golden's entire reasoning
  paragraph, pasted verbatim>" as its clause content -- that would be
  exempted in full, the same way a rubric that pasted the golden's entire
  numeric table after "Expected:" was already exempted in full by the
  original numeric filter. This check still catches a leak placed in the
  RATIONALE portion of a description (before the "Expected:" label): that
  text is never covered by clause_ratio, so it is scored exactly as before,
  unexempted.

  FOURTH CORRECTION (2026-09-15, later still -- a genuine false positive the
  clause_ratio/copula fix above cannot reach, because it sits in the
  RATIONALE portion the THIRD CORRECTION explicitly disclaims as unaffected):
  Khiem's 202-task subset had 3 answer_key_rubric_leak fails remaining after
  the THIRD CORRECTION: 2 were the file's own confirmed genuine leaks
  (SVC-PC-14-6-0 c07, SVC-PC-67-1-0 r011, fixed at the task level by
  paraphrasing the leaking judge.toml text, not by touching this script) and
  1 was a real check false positive, SVC-PC-56-1-0 criteria r029/r031/r032/
  r038. Read directly from the live judge.toml (tests/deliverables_03/
  judge.toml, tests/deliverables_04/judge.toml): r029/r038's matched text is
  "OEKO-TEX Standard 100 is named on the internal FAQ, pre-launch creative
  brief, Q1 catalog and holiday gift guide" and r031/r032's is "the internal
  FAQ and refund decision tree state a sleep trial length [/a warranty
  period]" -- both name WHICH source documents carry a claim or category of
  fact, never the claim's actual value (the certification status, the
  trial-length figure, the warranty period), in the matched span. This is a
  citation of sources, the rubric's own legitimate job, not a copy of the
  golden's reasoning -- structurally the same underlying fact pattern the v2
  clause filter generalized for (a rubric stating its own declared answer
  is not a leak regardless of whether that answer is a number, a name, an
  enum, or -- this correction's addition -- a citation of which sources
  assert something), but these four runs sit in the criterion's RATIONALE
  sentence, before its own "Expected:" label, so clause_ratio is 0.0 for all
  four and the existing exemption can never reach them no matter how it is
  tuned. This needs an exemption that is independent of clause position.

  The other 7 criteria flagged in the same task (r004, r005, r010, r023,
  r024, r026, r039) were read the same way and are NOT exempted by this
  fix, deliberately: r004/r023 are methodology/scope caveats about the
  register's own construction (no document citation at all); r005/r010/r024/
  r026 make a substantive role/availability determination about a named
  artifact ("the brand guidelines ARE intent, not customer-facing claims";
  "the care card... ARE described by other surfaces but not available as
  standalone") rather than citing which source states something; and r039
  ("Elena's cold email template SAYS the pillow shell is sewn in NC but the
  fill is from SF, and she dropped the Asheville claim pending confirmation")
  is the clearest near-miss deliberately left flagged -- it uses a
  citation-flavored verb ("says") to introduce the actual finding, not just
  to name a source, which is exactly the trap this fix has to not fall into.
  None of these 7 were confirmed as false positives, so none are touched;
  whether they hold real leaks is not yet determined.

  The fix (CITATION_PREDICATE_RE, find_citation_predicate_spans(),
  find_citation_predicate_token_mask(), plumbed through find_matching_runs()
  as rubric_citation_mask and read by classify_run() as is_source_citation):
  a closed, hand-curated list of citation/attribution predicates -- "named
  on/in", "state(s)", "cited in", "cites", "documented in", "referenced in",
  "mentioned in", "listed in", "appears/appear in", "found in" -- the same
  design as EXPECTED_VALUE_LABEL_PATTERNS and COPULA_TOKENS. A run is exempt
  if it contains one of these AND contains no unquoted copula OUTSIDE the
  predicate span itself (the "is" inside "is named on" does not count
  against it, reusing the same quote-span-carve-out shape as the THIRD
  CORRECTION's copula check, just against a citation span instead of a
  quoted span). This exemption is a THIRD, fully independent axis alongside
  numeric-ratio and clause-ratio -- checked directly in classify_run(),
  never gated on clause_ratio or clause position -- because the confirmed
  real examples all sit before the "Expected:" label.

  "state(s)" tail check (found and fixed the same evening this correction
  was written, by actually re-running the fix against the FULL 600-task
  corpus rather than trusting the 202-task subset it was scoped to):
  "named on/in", "cited in", "documented in", "referenced in", "mentioned
  in", "listed in", and "found in" are all structurally passive/
  prepositional -- "X is named ON/IN Y" -- so Y is grammatically a location/
  source reference. "X states Y" has no such constraint; Y can be any
  clause, including the graded substance itself. Without a further guard,
  this exemption wrongly cleared real corpus findings OUTSIDE Khiem's
  202-task subset: SVC-PC-62-1-0 c01 ("terms state a 100-night trial with
  stated refund and U.S. return-shipping conditions"), SVC-PC-60-0-0 c11
  ("policy states new hires complete security onboarding within five
  business days and annual refresher training on the anniversary"), and
  others across SVC-PC-6-7-0, SVC-PC-60-2-0/3-0/4-0/5-0/6-0, SVC-PC-62-2-0/
  3-0/4-0 -- all of these state the graded substance itself (a trial length,
  a policy's actual terms), not just which source states something, unlike
  the two confirmed-safe examples (r031/r032) whose matched runs happen to
  stop at the bare category label ("...length" / "...period") wherever the
  golden's own wording diverges from the rubric's right after it. The fix
  (STATE_TAIL_MAX_TOKENS, _state_tail_is_safe()): a run containing a bare
  "state"/"states" token is only citation-exempt if everything after that
  token, WITHIN THE SAME RUN, is at most 4 tokens and none of those tokens
  contains a digit character -- calibrated exactly to r031's tail ("a sleep
  trial length", 4 tokens, no digit) and r032's ("a warranty period", 3
  tokens, no digit). This checks the RUN's own tail, not the criterion
  description's tail, because the run's extent is a property of mutual
  token overlap with the golden (bounded by find_matching_runs()'s own
  extension loop), not of where the rubric's sentence happens to end. Other
  citation-predicate alternatives keep no such cap: the real corpus-wide
  exemptions they actually trigger (r029/r038's "named on" list, and
  SVC-PC-60-0-0 c21's "is named in the assigned source") were individually
  inspected and are all short, source-shaped citations; nothing analogous to
  the state(s) risk was found for them, though this is an empirical
  observation about the current corpus, not a structural guarantee the way
  the passive-voice argument is.

  Full 202-task re-run (Khiem's subset, the population this fix was scoped
  to), before vs. after this fix plus the two task-level paraphrase fixes
  together: 31->29 fail, 13->13 candidate (byte-identical finding sets), 158
  ->160 clean, 0 skip/error either run. Exactly 2 task-level status flips
  (SVC-PC-14-6-0, SVC-PC-67-1-0, both flagged->clean, from the task-level
  paraphrase, not from this script change alone) and one task
  (SVC-PC-56-1-0) whose flagged-criteria set shrinks from 11 to 7 while its
  task-level status stays "flagged" (the other 7 criteria, none confirmed as
  false positives, correctly keep the task flagged). Zero tasks moved toward
  MORE scrutiny; n_criteria/n_golden_files/parse_errors/errors byte-identical
  across all 202 tasks before and after.

  Full 600-task corpus re-run (C:/ekwqc/repo/pipeline/data/svc_pc_qc/
  03_dataos_ready, this script's change only, task-level judge.toml content
  held constant): before vs. after, task-level rollup is UNCHANGED at
  104 fail / 39 candidate / 456 clean / 1 skip -- this fix, by itself, never
  flips a task's overall status anywhere in the full corpus, because every
  task it touches has at least one OTHER flagged or candidate finding
  untouched by this fix, so it only narrows the finding SET within an
  already-flagged task, never a task's own verdict. Zero tasks moved toward
  more scrutiny; structural counts byte-identical.

  This re-run is also what caught and fixed two real bugs in the first
  version of this fix, neither visible from the 202-task subset alone:
  (1) the copula-prefix gap ("named on" without the preceding "is" folded
  into the same span, so r029/r038 stayed wrongly flagged) and (2) the
  "state(s)" tail check's own token-matching bug (exact string comparison
  missed "state," / "state." with punctuation glued on by TOKEN_RE, so
  SVC-PC-60-2-0 c23's "...completion STATE, owner, due point..." -- "state"
  used as a noun, with a 12-token non-numeric tail -- was briefly wrongly
  exempted). Both are fixed in the shipped code (see CITATION_PREDICATE_RE's
  and _state_tail_is_safe()'s own comments); this section reports the FINAL
  numbers, after both fixes, not the intermediate ones that motivated them.

  Final count: 7 tasks touched, none re-triaged as thoroughly as
  SVC-PC-56-1-0 -- SVC-PC-3-7-0 (candidate-only), SVC-PC-56-1-0 (r029/r031/
  r032/r038, the confirmed target), SVC-PC-60-0-0 (c19, c21), SVC-PC-60-2-0
  (c17), SVC-PC-60-3-0 (c19), SVC-PC-60-5-0 (c15), SVC-PC-60-6-0 (c09, c17).
  Spot-checking the SVC-PC-60-*-0 criteria (not exhaustively triaged the way
  SVC-PC-56-1-0's 11 were, since that would be a substantially larger review
  outside what this fix was asked to cover) surfaced a SECOND legitimate-
  looking pattern this fix also happens to clear, distinct from the citation
  shape it was designed for: that task family's own authoring convention is
  "Finding - <label>: Reports '<locked, verbatim-required finding sentence>'
  with status '<status>' and trace '<trace>'. Expected: ." -- an EMPTY
  "Expected:" clause, with the entire substantive content inside a REQUIRED
  QUOTE (e.g. SVC-PC-60-0-0 c19: "Reports 'Incident log records a December
  2021 1Password vault-sharing misconfiguration...the log states no
  exfiltration.' with status 'Confirmed'..."). This is the SAME
  "locked/given source quote" shape the docstring already treats as safe
  elsewhere (SVC-PC-8-7-0 b2, SVC-PC-10-5-0 c01, SVC-PC-11-4-0), just
  reached by a coincidental route here: the quote happens to contain a word
  this fix's predicate list matches ("states", "named in", "appears in"),
  and the quote sits in the rationale before an empty "Expected:" label, the
  same clause-position gap SVC-PC-56-1-0's confirmed cases sit in. This
  fix's exemption is therefore doing double duty for this task family: it is
  NOT a purpose-built fix for the locked-quote-before-an-empty-label shape
  (that would properly extend the EXISTING quote-span carve-out to work
  regardless of clause position, a more general fix this correction did not
  attempt), and a future criterion in this same family whose locked quote
  happens to contain NONE of CITATION_PREDICATE_RE's words would still be
  wrongly flagged. A reviewer relying on this exemption for a task outside
  SVC-PC-56-1-0 should re-derive why it applies, not assume this docstring's
  citation-shape reasoning is the actual reason in every case.

  FIFTH CORRECTION (2026-09-15, a new false positive on a DIFFERENT axis from
  the four above -- this one is not a classify_run() exemption at all):
  SVC-PC-75-1-0 criterion r22 was flagged against its own golden workbook,
  FPA_Zero_Based_Cost_Baseline_and_Classification.xlsx. The matched run ("All
  reconciliation checks PASS; the only non-tie (inventory_flows $221,185 vs
  GL COGS $423,359, diff $202,174) is flagged informational, not an error")
  sits inside r22's own "Expected:" clause (clause_ratio 1.0) but contains an
  unquoted copula ("is flagged"), so the THIRD CORRECTION's copula check
  correctly treats it as a narrative assertion and does not exempt it via
  clause_ratio -- the existing exemptions were working exactly as designed.
  The actual defect is upstream of classify_run() entirely: this workbook
  contains a tenth sheet, "Rubric_Self_Check" (header: "Rubric Self-Check --
  response vs. its own grading rubric"; columns ID | Category | Expected
  value / check (self-contained) | Points | Must-pass? | Met? | Evidence in
  this workbook), whose entire PURPOSE is letting the solution author verify
  the workbook against this same rubric before submission. It deliberately
  restates each criterion's own "Expected:" text verbatim so the author can
  check it off -- confirmed directly by searching the workbook for the
  matched figures ($221,185 / $423,359): that exact phrasing exists ONLY in
  this sheet. The workbook's real "Checks" sheet also discusses the same two
  figures, but in unrelated, non-matching wording ("Check 16 (DIFF):
  inventory_flows.csv cogs_value ... represents SKU-level product COGS
  only ..."), so the copy direction is rubric-into-self-check-tab, not
  golden-reasoning-into-rubric -- the opposite of a real leak, and a
  DIFFERENT sheet in the SAME workbook holding genuinely independent text
  about the same fact is exactly why this is fixed by excluding one sheet,
  not by loosening classify_run() itself (which would also have widened the
  numeric-ratio/clause-ratio/is_source_citation exemptions for every OTHER
  golden file in the corpus, not just this one sheet's content).

  A corpus-wide scan (2026-09-15, every sheet name in every golden .xlsx/
  .xlsm under all 609 tasks at C:/ekwqc/repo/pipeline/data/svc_pc_qc/
  03_dataos_ready, not guessed from the one task that surfaced this) found
  five more real instances of the same convention: SVC-PC-1-2-0 and
  SVC-PC-7-1-0 (both sheet-named "Rubric Self-Check"), SVC-PC-7-2-0
  ("Rubric_SelfCheck"), SVC-PC-7-4-0 ("Rubric_Self_Check"), and SVC-PC-3-7-0
  ("Rubric Coverage" -- a sheet NAME that contains neither "self" nor "check",
  caught only because its header row reads "Final response self-check:
  explicit answers and evidence for every scored criterion"). That sixth
  example is why the fix checks header text as well as sheet name: a
  name-only check would have missed it.

  The fix (is_self_check_sheet(), is_self_check_sheet_name(),
  is_self_check_sheet_header(), SELF_CHECK_SHEET_NAME_SUBSTRINGS,
  SELF_CHECK_HEADER_RUBRIC_RE, SELF_CHECK_HEADER_SELFTERM_RE, wired into
  read_xlsx_text()): a sheet is excluded from the golden text this check
  compares rubric criteria against if EITHER its own name (normalized,
  substring match against "selfcheck" / "selfaudit" / "rubriccheck") or its
  own header text (first 5 rows) co-occurs "rubric" with a self-check/
  self-assessment term. This acts at extraction time, on the GOLDEN side, not
  at classify_run() on the rubric side like the three exemptions above -- the
  same kind of decision as SUPPORTED_EXTENSIONS already makes (some content
  never enters the golden token stream at all), just at sheet granularity
  instead of file granularity. Deliberately narrow on the name side (no bare
  "rubric" substring, since a sheet can be rubric-adjacent without being a
  self-check tab -- "Rubric Coverage" is exactly this, caught by the header
  check instead) and deliberately requires co-occurrence on the header side
  (not "rubric" or a self-term alone), because a finance-scenario golden's
  real business sheets (revenue schedules, control registers, vendor plans,
  cap tables) have no occasion to use the word "rubric" at all.

  Verified directly, not assumed: with the fix, SVC-PC-75-1-0 goes from 1
  flagged (r22) to clean, and a direct re-check of the workbook confirms the
  "Checks" sheet's own differently-worded text about the same two figures
  does not itself form a run long enough to be found -- the fix removes the
  false positive without creating a new one from the sheet it was originally
  confused with. Full before/after counts across Khiem's 202-task subset and
  the full corpus are in this repo's commit history for this change, not
  restated here to avoid this docstring going stale the next time either
  corpus is re-run for an unrelated reason.

  SIXTH CORRECTION (2026-09-16, a second false-positive mechanism diagnosed
  alongside the FIFTH but deliberately left unfixed pending its own dedicated
  task -- see tracker row 20 in ekw/svc-dataos-failure-mode-tracker-2026-09-15.md
  for the original diagnosis): after the v6 SCALE_SUFFIX_TOKENS fix below,
  Khiem's 202-task subset still had 25 fail-tier tasks. All 25 were read
  exhaustively against real judge.toml text, not sampled: 19 confirmed
  genuine, 6 a real false positive of a shape none of the first three
  exemptions can reach -- a bare schema/field/section-name enumeration
  sitting in the criterion's own RATIONALE, before its "Expected:" label,
  that names WHICH fields, tabs, or sections a criterion concerns rather than
  stating a fact about them. It evades numeric-ratio (most of these runs are
  not numeric at all), clause_ratio (they sit before the label, not after),
  and is_source_citation (they don't cite which document states something --
  they ARE the field/section list itself).

  Confirmed real examples, each individually verified against its live
  judge.toml and reconstructed back to its own literal character span (not
  just its stripped tokens -- see is_schema_enumeration below): SVC-PC-10-5-0
  c06's "cash_in/ending_cash/incremental_margin_cash_payment/..." (a
  parenthetical, slash-and-underscore-joined list of ten snake_case field
  names copied from the golden's own JSON result schema); SVC-PC-17-2-0
  r041's "FY2021 COGS -- P&L line (Year_1_Annual_PnL)" (a cell/tab-address
  citation -- the parenthesized text is the golden workbook's own sheet
  name); SVC-PC-22-2-0 r050's "Mix drift (accessory/insert/gift-set share in
  promo windows)" (a metric NAME's own definition, not its value, which
  appears separately); SVC-PC-46-3-0 r17's "the new priority, displaced
  item(s), and new target sprint" (a required-fields list for a change-log
  entry); SVC-PC-88-0-0 jdg-05's "Alice Chen (CEO acting as CFO); Cirrus
  Sleep FY2021" (a cast/scope declaration naming who and which fiscal year a
  deliverable must be about, the same shape as row 17's negative-scope-
  constraint work); SVC-PC-91-8-0 a1's "integration scope & architecture;
  build effort & timeline; one-time & ongoing cost; technical risks" (a
  required-section list that literally names the golden workbook's own
  tabs). All six have numeric_ratio 0.0-0.111 (not exempted by the numeric
  filter), clause_ratio 0.0 (entirely before "Expected:", not exempted by the
  clause filter), and no unquoted copula.

  The fix (STRUCTURAL_LIST_DELIM_RE, STRUCTURAL_LIST_MIN_DELIMS,
  is_schema_enumeration -- see both constants and find_matching_runs() /
  classify_run() above): a run is exempt as a schema enumeration if (a) it
  sits entirely before the criterion's own "Expected:" label (clause_ratio ==
  0.0 -- deliberately narrower than the clause_ratio exemption, which covers
  the opposite side of the label; no confirmed real example needed this
  exemption to reach past the label, so it is not extended there), (b)
  contains no unquoted copula (same defensive shape as every exemption
  above), AND (c) its own literal span in the ORIGINAL rubric text contains
  at least 2 characters from the closed set "/", ";", "&", "_", "(", ")" --
  punctuation TOKEN_RE strips out of the token stream entirely, so this is
  computed from the RAW text span (rubric_text + rubric_token_spans, newly
  threaded through find_matching_runs()), not from the tokens classify_run()
  already had. Comma is deliberately excluded from the delimiter set despite
  reading as a list-separator too: it is far too common in ordinary narrative
  prose to serve as a structural signal alone -- confirmed real risk, not a
  hypothetical, since SVC-PC-56-1-0 r005's own confirmed-GENUINE leak ("...not
  customer-facing claims, and are included for reference...") contains two
  commas, which would tie it with the least-delimited real target case if
  comma counted. The minimum-2 threshold (not 1) is a real, measured margin:
  every currently-flagged finding in Khiem's 202-task subset was checked for
  its own raw-span delimiter count, and the worst incidental case among
  confirmed-genuine, no-copula findings is exactly 1 (SVC-PC-17-4-0 r014's
  stray ")", SVC-PC-12-6-0 r021's stray "/" in "order/customer data",
  SVC-PC-29-2-0 r003's stray "_" in "Business_Title"), while the least-
  delimited of the six real targets is 2 (SVC-PC-46-3-0). The one genuine
  finding with 4 delimiters, SVC-PC-53-3-0 r006, is already excluded by the
  copula check (it contains "cannot be") independent of this threshold. A
  fourth condition, (d), was added after the FIRST full-600-task pass (see
  the verification paragraph below and SENTENCE_BREAK_RE's own comment): the
  run's raw span must contain no INTERNAL sentence break (a "." or ":"
  immediately followed by whitespace -- never true of a decimal point or a
  filename extension like "Policy.docx", which TOKEN_RE itself does not
  split on and which is never followed by a space). A bare enumeration is one
  phrase-level list by definition; a run spanning two or more complete
  sentences is prose no matter how many delimiter characters it contains.

  Verified directly against the real corpus, not assumed, in TWO passes --
  the second because the file's own history (the copula-prefix and
  state-tail bugs in the FOURTH CORRECTION, three more scale-suffix instances
  in v6) is that a 202-task-scoped fix is not proven safe until it has run
  against the full corpus. FIRST PASS, conditions (a)-(c) only: Khiem's
  202-task subset, before (C:/ekwqc/_step2_full_202_v2/answer_key_rubric_leak.json)
  vs. after -- task-level flagged 25->19, candidate 13->13 (unchanged), clean
  164->170, 0 skip/error either run, structural fields byte-identical across
  all 202 tasks, exactly 6 status changes (all flagged->clean, all 6 the
  confirmed targets), and all 19 confirmed-genuine tasks re-verified
  INDIVIDUALLY, not by aggregate count alone (this file's own "46.20-credits"
  lesson): every one of their 42 flagged findings present, byte-for-byte
  identical, in both runs. One additional, fully explained effect at this
  scale: SVC-PC-12-6-0's r019 CANDIDATE-tier finding ("$1M occurrence / $2M
  aggregate) plus warehouse legal liability", numeric_ratio exactly 0.400 --
  sitting ON, not above, the v6 fix's own ">0.4" boundary) also clears; not a
  new false-positive class, since this IS the same bare insurance-limits
  citation shape v6 was built for, on the very same r019 criterion whose
  larger flagged-tier match v6 already cleared, and SVC-PC-12-6-0 stays
  flagged overall regardless (r020/r021 remain genuine, untouched). Full
  600-task re-run at this stage (conditions (a)-(c) only): flagged 99->86,
  candidate 36->35, clean 464->478, 0 tasks moved toward MORE scrutiny
  anywhere in the 600 (verified computationally, not by inspection: every
  task's status was ranked clean<candidate<flagged and checked pairwise).
  9 more tasks cleared beyond the 6 originally diagnosed, all independently
  read against live judge.toml before trusting them, the same real-example
  discipline as the six above (e.g. SVC-PC-1-6-0's "CSAT/NPS by quarter
  correct (explicit 'by quarter' deliverable)" -- a parenthetical clarifying
  what a metric decomposition covers; SVC-PC-39-6-0's five-required-fields
  list; SVC-PC-82-0-0's required-elements-of-a-change-record list). This pass
  ALSO surfaced the family of "Finding - <label>: Reports '<locked quote>'
  with status '...' and trace '...'. Expected: ." criteria in the
  SVC-PC-60-*-0/62-*-0 task group -- the module docstring's own FOURTH
  CORRECTION had already predicted this exact gap ("a future criterion in
  this same family whose locked quote happens to contain NONE of
  CITATION_PREDICATE_RE's words would still be wrongly flagged"), so most of
  these clears are a welcome, anticipated generalization, not a surprise. But
  one of them, SVC-PC-62-6-0 c04 ("Policies describe consumer
  commitments...execution. Cookie policy says no heat-mapping tools while
  licence inventory lists Hotjar, without timing or deployment evidence."),
  is a genuine two-sentence analytical finding (a policy-vs-inventory
  discrepancy) that crossed STRUCTURAL_LIST_MIN_DELIMS only by coincidence
  (one incidental semicolon, one incidental slash in "consent/preference") --
  condition (d) above was added specifically to exclude it, verified directly
  (it now stays flagged) without narrowing any of the six original targets
  (none contain an internal sentence break) or SVC-PC-62-6-0 c01 (a
  single-sentence source-conflict statement, correctly still clears).

  SECOND PASS, all four conditions: Khiem's 202-task subset unchanged from
  the first pass (25->19 fail, all 19 genuine individually re-verified again,
  byte-identical). Full 600-task re-run, real before/after
  (C:/ekwqc/_rubric_leak_fix_verify_b/before_full600.json vs
  after_full600.json, before independently cross-checked against the
  202-scoped baseline first: 0 status mismatches across all 202 shared task
  IDs): flagged 99->87, candidate 36->35, clean 464->477, skip 1->1, error
  0->0. 569/600 tasks byte-identical (status AND every finding). 0 tasks
  moved toward MORE scrutiny anywhere in the 600, verified computationally
  (every task's status ranked clean<candidate<flagged and checked pairwise,
  not eyeballed). 14 status changes total: the 6 original confirmed targets
  plus 8 more found only by the full-corpus re-run and individually verified
  against live judge.toml before trusting them (SVC-PC-24-2-0, SVC-PC-53-2-0,
  SVC-PC-71-2-0, SVC-PC-71-6-0, SVC-PC-81-6-0, SVC-PC-81-7-0, SVC-PC-82-0-0 to
  clean; SVC-PC-50-0-0 flagged->candidate, a partial clear that still leaves
  a real candidate finding for review). Adding condition (d) removed exactly
  one status change relative to the first pass's 15 (SVC-PC-62-6-0 c04 no
  longer clears; c01 in the same task still does) and left everything else
  identical, confirming the guard is precisely targeted, not a blunt
  narrowing. structural fields (n_criteria/n_golden_files/parse_errors/
  errors) byte-identical across all 600 tasks in both passes.

  Known limit, disclosed rather than silently accepted: this exemption is
  gated to runs sitting entirely before the "Expected:" label because that is
  where every confirmed real example lives, not because a post-label schema
  list is structurally impossible -- a future criterion whose enumeration
  sits mostly after the label with clause_ratio between 0 and 0.6 (too little
  to trip the existing clause_ratio exemption) would still be invisible to
  both exemptions. Not observed in the 600-task corpus at the time of this
  fix; left unaddressed rather than guessed at, the same discipline as every
  prior correction in this file.

Usage:
    python answer_key_rubric_leak_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python answer_key_rubric_leak_check.py --all --root <path> --out report.json
    python answer_key_rubric_leak_check.py --all --root <path> --id-prefix MYBENCH- --out report.json

    --min-run N           minimum consecutive matching word-tokens to consider
                          a run at all (default 7; below this, even a candidate
                          is not surfaced, because shorter runs are dominated
                          by coincidental common-phrase overlap)
    --candidate-run N     run length that triggers a CANDIDATE finding (default
                          8; >= --min-run)
    --candidate-cw N      content-word count for a CANDIDATE finding (default 6)
    --flagged-run N       run length that triggers a FLAGGED finding (default 9)
    --flagged-cw N        content-word count for a FLAGGED finding (default 7)
    --max-numeric-ratio R  maximum fraction of pure-numeric tokens in a run for
                          it to be flagged at all (default 0.4; a run that is
                          > 40% numbers is expected-value matching, not prose)
    --min-clause-ratio R  minimum fraction of a run's own tokens that must sit
                          inside the criterion's own labeled "Expected:" clause
                          for it to be exempted at all (default 0.6; see the
                          2026-09-15 update above). This exemption additionally
                          requires the run to contain no unquoted copula
                          (is/are/was/were/...) -- see the THIRD CORRECTION;
                          not independently tunable via a CLI flag, since it
                          is a structural presence check, not a ratio.

    A THIRD, fully independent exemption -- is_source_citation, see the FOURTH
    CORRECTION above -- clears a run that names WHICH source document(s)
    carry or assert a claim (e.g. "is named on the internal FAQ, pre-launch
    creative brief..."), not the claim's own substance. Like the copula
    check above, this is a closed vocabulary (CITATION_PREDICATE_RE), not a
    ratio, so it has no CLI flag either.

    A FOURTH exemption, is_self_check_sheet -- see the FIFTH CORRECTION above
    -- excludes an entire golden-workbook SHEET from the comparison (rather
    than exempting one matched run) when that sheet's own name or header text
    marks it as a self-check/self-audit tab: a solution author's own mapping
    of the workbook against the rubric, not independent golden reasoning. This
    is not a classify_run() exemption and has no CLI flag either: it is a
    closed vocabulary (SELF_CHECK_SHEET_NAME_SUBSTRINGS,
    SELF_CHECK_HEADER_RUBRIC_RE, SELF_CHECK_HEADER_SELFTERM_RE), the same
    design as the copula and citation-predicate lists, applied at golden-text
    extraction time instead.

    A FIFTH exemption, is_schema_enumeration -- see the SIXTH CORRECTION above
    -- clears a run that is a bare schema/field/section-name enumeration
    (e.g. "cash_in/ending_cash/...", "integration scope & architecture; build
    effort & timeline...") sitting entirely before the criterion's own
    "Expected:" label, rather than narrative prose. Like is_source_citation,
    this is a closed, structural signal (STRUCTURAL_LIST_DELIM_RE, a fixed
    2-character minimum) computed from the run's own literal span in the
    ORIGINAL rubric text, not a ratio, so it has no CLI flag either.

Status: v7 (2026-09-16), the STRUCTURAL_LIST_DELIM_RE schema-enumeration fix
(see is_schema_enumeration in find_matching_runs()/classify_run() above --
full detail in the calibration section's SIXTH CORRECTION): closes the
second of the two false-positive mechanisms found in the 2026-09-16 26-task
fail-tier review of Khiem's 202-task subset (the first, scale-suffix
tokenization, was v6, immediately below). v6 (2026-09-16), the
SCALE_SUFFIX_TOKENS numeric-ratio fix (see
count_numeric()/count_content_words()/_numeric_token_mask() above): a
scale-suffixed dollar figure ("$2M", "$150K", "$1.2B") was undercounted as
numeric because TOKEN_RE splits it into two tokens ("$2" then "m"), so its
unit letter inflated content_words and deflated numeric_ratio below the 0.4
exemption threshold for what is still a bare value citation. Found during a
2026-09-16 real-corpus review of all 26 fail-tier findings on Khiem's
202-task subset (C:/ekwqc/_step2_full_202/answer_key_rubric_leak.json):
SVC-PC-25-6-0 c10 and SVC-PC-12-6-0 r019, both hand-verified against their
real golden files (Cirrus_FY2021_Contractual_Risk_Transfer_and_Certificate_
Review.xlsx, Compliance_Memo.docx) as bare insurance-limits citations, the
same shape SVC-PC-7-4-0 o5 already established as safe. Fixed by treating a
bare k/m/b/mm/bn/mn token as numeric ONLY when it immediately follows a
numeric/currency token in the same run (narrow, positional, same design as
STATE_TAIL_MAX_TOKENS). Full 600-task corpus re-run, real before/after
(C:/ekwqc/_rubric_leak_fix_verify/before_full600.json vs after_full600.json):
task-level flagged 100->99, candidate 39->36, exactly 4 status changes
(SVC-PC-25-6-0 flagged->clean; SVC-PC-45-0-0, SVC-PC-81-3-0, SVC-PC-81-8-0
candidate->clean, three MORE real instances of the identical scale-suffix
shape found only by the full-corpus re-run, not the original 2), zero tasks
moved toward more scrutiny anywhere in the 600. SVC-PC-12-6-0's task-level
status stays flagged (r020/r021 are separate, confirmed-genuine narrative
copies from the same Compliance_Memo.docx, untouched by this fix) but its
r019 finding is individually gone from flagged_findings, confirmed at the
finding level, not just the task level. v5 added the is_self_check_sheet
exclusion (SELF_CHECK_SHEET_NAME_SUBSTRINGS, SELF_CHECK_HEADER_RUBRIC_RE,
SELF_CHECK_HEADER_SELFTERM_RE) for a false positive on a golden workbook's
own self-verification tab -- see the FIFTH CORRECTION in the calibration
section above. v4 added the is_source_citation exemption
(CITATION_PREDICATE_RE, STATE_TAIL_MAX_TOKENS) for a false positive the THIRD
CORRECTION's fix could not reach -- see the FOURTH CORRECTION. v1 was built
and calibrated in one pass against the 27-task SVC-PC and 4-task EKW mirrored
corpora referenced there (not the full 600+274, which were not on that build
machine); v2 through v5 were each calibrated against the full SVC-PC corpus at
C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready (600 tasks through v4,
609 as of v5). Two tiers: FLAGGED (fail, strong evidence of copying) and
CANDIDATE (warn, worth human review). The CANDIDATE tier is a disclosure, not
a gate: its findings are real overlapping text a reviewer should look at, but
the overlap may turn out to be shared standard terminology rather than a copy.

Known limits, disclosed rather than silently dropped:
    - This is a word-level n-gram match. A paraphrased leak (the rubric
      restates the golden's point in different words) is invisible to this
      check. Pattern 6 encompasses paraphrase too, but mechanizing paraphrase
      detection is an LLM task, not a deterministic one; this check catches
      the verbatim-and-near-verbatim shape only.
    - Tokenization is case-insensitive and punctuation-stripped. A leak that
      changes capitalization or swaps a comma for a semicolon still matches;
      a leak that reorders words or inserts a filler word between two halves
      of a copied phrase breaks the run at the insertion point.
    - The stopword list is English-only and hand-tuned. A matching run that
      is entirely stopwords and numbers ("the total of the $1,204,900 for the
      year") would have low content-word count and not fire. This is by design
      (it is expected-value prose, not distinctive copying) but means a very
      stopword-heavy copied sentence could slip through if its content words
      are spaced far enough apart.
    - Only golden files with supported extensions (.txt .md .csv .json .xlsx
      .xlsm .docx .pptx) are scanned. A golden answer in an unsupported
      format (.pdf, .xls, .html, ...) is invisible. .pdf is the biggest gap on
      the EKW side (the plurality format in EKW environment/data/), though
      golden_outputs in the mirrored samples are .xlsx/.docx/.pptx only.
    - The solution/ directory must exist and contain text-bearing files. A
      task with no solution/ (like the 56-task SVC-PC mirror) reports skip,
      not clean: "no golden content to compare against" is a real coverage
      gap, not a confirmed-safe result.
    - Matching is per-golden-file. A run that spans two golden files (the
      rubric copies sentence A from file 1 and sentence B from file 2, joined
      by a word that happens to bridge them) would be found as two separate
      runs, not one. This is fine for the leak shape this check targets.
    - EKW's Reasoning.docx (a golden reasoning trace) is included in the
      golden text. If the rubric copies the Reasoning.docx's prose, that IS a
      pattern-6 instance (the rubric is copying golden reasoning), and this
      check will flag it. Whether Reasoning.docx should count as "golden
      answer content" is a judgment call; the task description says "the task's
      own golden/reference answer content," and Reasoning.docx is part of the
      golden solution package.
    - The expected-value clause filter (v2, 2026-09-15) originally trusted the
      entire labeled "Expected:" clause once found, with no signal
      distinguishing a terse declared value from long/discursive narrative --
      this was a real regression, not just a disclosed risk (see the THIRD
      CORRECTION in the calibration section above), fixed the same day by
      checking the matched RUN itself (not the whole clause) for an unquoted
      copula. The residual gap after that fix: a leak expressed with only
      non-copula action verbs ("the team shipped X and reviewed Y," no
      is/are/was/were anywhere in the matched span) is still invisible to
      this check and would still be exempted if it also sits mostly after the
      label. This is now a narrower, disclosed gap, not the wide-open one the
      v2 filter shipped with. A leak placed before the "Expected:" label (in
      the criterion's rationale sentence) is unaffected either way and still
      scored exactly as before.
    - The is_source_citation exemption (v4, 2026-09-15 -- see the FOURTH
      CORRECTION) is a closed, hand-curated predicate list, calibrated
      against four confirmed real examples in one task (SVC-PC-56-1-0) plus
      a full-600-task-corpus re-run used only to catch regressions, not to
      individually triage every task it touches. Confirmed via that
      corpus-wide re-run: it also narrows (never widens) findings in 7 other
      tasks (SVC-PC-3-7-0, SVC-PC-56-1-0 already counted, SVC-PC-60-0-0/2-0/
      3-0/4-0/5-0/6-0) without flipping any task's overall status, and each
      one was spot-checked, not exhaustively triaged the way SVC-PC-56-1-0's
      11 criteria were. The "state(s)" alternative specifically required an
      extra guard (STATE_TAIL_MAX_TOKENS, _state_tail_is_safe()) because
      unlike the other predicates it is not structurally passive/
      prepositional, and even with that guard, "state(s)" is checked by
      exact word match after stripping glued trailing punctuation, not by
      any semantic understanding -- a rubric using "state" as a NOUN
      ("completion state") rather than a verb gets the same tail-length/
      no-digit treatment as the verb, which is stricter than necessary but
      never wrongly permissive (confirmed real near-miss caught by the full
      corpus re-run: SVC-PC-60-2-0 c23's "...document category, completion
      STATE, owner, due point..." was briefly, wrongly exempted before this
      guard existed, purely because "state," with a comma glued on by
      TOKEN_RE did not string-match "state" exactly). A citation-predicate
      verb this list does not cover (e.g. "says", deliberately excluded --
      see CITATION_PREDICATE_RE's own comment and SVC-PC-56-1-0 r039) is
      invisible to this exemption and scored exactly as before it existed.
    - The is_self_check_sheet exclusion (v5, 2026-09-15 -- see the FIFTH
      CORRECTION) is a closed, hand-curated name/header vocabulary, calibrated
      against six confirmed real examples across five tasks found by a
      corpus-wide sheet-name scan, not exhaustively triaged one by one the way
      SVC-PC-75-1-0 (the confirmed target) was. A self-check tab that uses
      neither "rubric" in its header nor any of "self check"/"self-check"/
      "self_check"/"selfcheck"/"self audit"/"rubric check" in its name is
      invisible to this exclusion and scored exactly as before it existed --
      e.g. a hypothetical tab named just "QA" or "Verification" with no
      "rubric" mention anywhere in its own header would still be compared as
      ordinary golden content. This exclusion also differs from the other
      three in what it risks getting wrong: because it drops an entire SHEET's
      text rather than exempting one matched run, a self-check tab that ALSO
      happened to contain a genuinely independent leaked sentence (not just
      the rubric's own restated criteria) would have that sentence excluded
      too, silently. Not observed in any of the six confirmed real examples
      (each one's content is a criterion-by-criterion mapping table, not
      free-form prose), but a future self-check tab that mixes in narrative
      commentary would need a within-sheet check, not just a whole-sheet one,
      which this fix does not attempt.
    - The is_schema_enumeration exemption (v7, 2026-09-16 -- see the SIXTH
      CORRECTION) is gated to runs sitting entirely before the "Expected:"
      label (clause_ratio == 0.0) because every confirmed real example lives
      there; a schema/field-name list embedded in a long labeled clause with
      clause_ratio between 0 and min_clause_ratio (too little to trip the
      existing clause_ratio exemption) is invisible to both exemptions and
      scored exactly as before either existed. It is also a fixed 2-character
      minimum over a closed 6-character delimiter set, not a semantic
      understanding of "is this a list": a genuine schema-list run that
      happens to overlap the golden starting or ending mid-list could see
      fewer than 2 delimiters within its own matched span even though the
      full clause is clearly a list, the same "the signal lives on the run,
      not the clause" trade-off every other run-level exemption in this file
      already accepts. Not observed in the 600-task corpus at ship time. The
      sentence-break guard (SENTENCE_BREAK_RE, condition (d)) is a real,
      corpus-found precision fix (SVC-PC-62-6-0 c04, see the SIXTH
      CORRECTION), not just a hypothetical hardening -- but it is also
      conservative in the other direction: a legitimate locked-quote value
      introduced by a colon ("next action: 'Resolve hierarchy through
      HR/Legal; do not select one term.'", SVC-PC-60-5-0 c18) is treated the
      same as a genuine sentence break and stays unexempted, even though its
      own content is safe by the same "locked quote" reasoning the FOURTH
      CORRECTION already established elsewhere. Accepted rather than chased
      further: it only widens the set of findings a human still has to
      glance at, never the other direction, and the task those findings
      belong to is never solely gated on this one criterion.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ekw_verifier_json import has_ekw_config, load_ekw_criteria

# Windows console defaults to cp1252, which cannot encode every character in real
# rubric/golden text (curly quotes, currency symbols, non-Latin paths). Force
# UTF-8 with replacement so a non-cp1252 character never crashes a batch run.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import openpyxl
except ImportError:  # pragma: no cover
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "openpyxl", "--quiet"], check=True
    )
    import openpyxl

try:
    import docx as _python_docx

    HAVE_PYTHON_DOCX = True
except ImportError:  # pragma: no cover
    HAVE_PYTHON_DOCX = False


# ---------------------------------------------------------------------------
# tokenization and overlap detection
# ---------------------------------------------------------------------------

# Hand-tuned English stopword list. A "content word" for this check is any
# word-token that is NOT in this list and NOT purely numeric/punctuation. The
# content-word count is the primary precision signal: a long run of matching
# stopwords and numbers is common business boilerplate, not a distinctive copy.
# "own" is included because in "the desk's own review" it functions as a
# determiner, but in other contexts it could be content. This is a disclosed
# trade-off: including it errs toward fewer false positives at the cost of
# missing a stopword-heavy copied sentence that uses "own" as a content word.
STOPWORDS = set(
    (
        "a an the of to in on at by for with from is are was were be been being "
        "and or not no nor but if then else when while as that this these those it its "
        "their there here which who whom whose what where why how all any each every "
        "some none both either neither more most less least much many few several "
        "into out up down over under again further once will would should could may "
        "might must can shall do does did doing have has had having i you he she we "
        "they them his her our your my me him us also than so very too just only own "
        "same other such about above below off upon onto am pm per via vs etc"
    ).split()
)

# Matches a word-token: starts with an alphanumeric character, may contain
# $ % . , ' - inside it. Also matches a $-amount ($1,204,900). Pure
# punctuation (+, =, /, ;) does not match, so formula notation breaks runs at
# those points (this is why "prior cash + net income" produces a shorter run
# than "prior cash net income" would).
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9$%.,'-]*|\$\d[\d,.-]*", re.IGNORECASE)

# A token that is entirely numeric, currency, percentage, or punctuation.
# Used to count "numeric tokens" for the numeric-ratio filter.
NUMERIC_RE = re.compile(r"[\d$%.,'-]+")

# Labels the SVC-PC criterion-authoring convention uses to introduce a
# criterion's own explicit statement of the correct answer ("<rationale>.
# Expected: <exact required fact>."). Confirmed against a full scan of the
# real corpus (2026-09-15, all 23,220 SVC-PC criterion descriptions under
# C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready -- see the module
# docstring's 2026-09-15 update for the counts). This is a list, not a single
# pattern, on purpose: the next confirmed non-numeric expected-value label is
# a one-line addition here, not a rewrite of find_expected_clause_token_start
# or classify_run.
EXPECTED_VALUE_LABEL_PATTERNS = [
    re.compile(r"\bexpected\s*:", re.IGNORECASE),
]

# Copula word-forms ("X IS Y" / "X ARE Y" declarative-identity structure).
# Used by the has_unquoted_copula check in find_matching_runs() / classify_run()
# -- see the module docstring's THIRD CORRECTION (2026-09-15) section. A
# matching run that contains one of these tokens, outside a quoted span (see
# QUOTE_SPAN_RE below), reads as a sentence ASSERTING a fact ("the finance
# role IS Jessica Liu...", "address line 1 IS empty...") rather than a bare
# enumeration/value of the kind the corpus's "Expected:" convention states.
# This is deliberately a small, closed, unambiguous class rather than a
# general verb list: the real corpus's own legitimate Expected: clauses use
# ordinary verbs too ("WC build...EXCEEDS $120K allowance" SVC-PC-26-4-0 r5;
# the locked vision quote "a world that SLEEPS better...MADE honestly"
# SVC-PC-8-7-0 b2), and a verb-presence rule would wrongly un-exempt both. A
# copula is different in kind: it is never itself a value or a list item, so
# it cannot appear in a genuinely value-shaped clause without that clause
# also containing a subject-is-predicate assertion. Contracted negated forms
# are included for completeness -- same concept, not a new category, so no
# separate corpus calibration was needed for them.
COPULA_TOKENS = {
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "isn't",
    "aren't",
    "wasn't",
    "weren't",
}

# A quoted span inside a criterion's description: text delimited by a pair of
# straight or curly quote marks. Used to keep a copula that is part of a
# LOCKED VALUE the rubric is required to quote verbatim from counting as
# narrative copying -- see find_quoted_token_mask() and the module
# docstring's THIRD CORRECTION section. Two confirmed real examples wrap a
# full sentence (copula included) in quote marks on purpose: SVC-PC-8-7-0
# b2's vision quote ("Expected: \"A world that sleeps better...\"") and
# SVC-PC-10-5-0 c01's structured field assignment
# (results.board_conclusion.conclusion="The approved...build IS
# affordable..."). Both must stay exempt; neither is a leak.
#
# The single-quote alternative requires at least one internal whitespace
# character and forbids an alphanumeric character immediately before the
# opening mark, so "Oakmont's" (a possessive) and "don't" (a contraction) --
# both a single unpaired apostrophe, not a quote pair -- never open a span.
# The corpus's real locked-quote examples ('ran lean in Year 1',
# SVC-PC-11-4-0) are always multi-word, so this loses no real case while
# avoiding a false span stretching across two unrelated possessives
# elsewhere in the same description.
QUOTE_SPAN_RE = re.compile(
    r'"[^"]*"' r"|“[^”]*”" r"|(?<![A-Za-z0-9])'[^']*\s[^']*'" r"|‘[^’]*\s[^’]*’"
)

# Citation/attribution predicate: phrases the SVC-PC rubric-authoring convention
# uses to state WHICH source document(s) name, assert, or carry a claim -- as
# distinct from stating the claim's own substance. Used by
# find_citation_predicate_token_mask() / find_matching_runs() / classify_run()
# for the source-citation exemption -- see the module docstring's FOURTH
# CORRECTION (2026-09-15). Confirmed real examples (SVC-PC-56-1-0, all under
# C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready): r029/r038's "OEKO-TEX
# Standard 100 is named on the internal FAQ, pre-launch creative brief, Q1
# catalog and holiday gift guide" and r031/r032's "the internal FAQ and refund
# decision tree state a sleep trial length [/warranty period]" -- both name
# WHICH documents carry a claim or a category of fact without stating the
# claim's actual value (the certification status, the trial-length figure, the
# warranty period) anywhere in the matched span.
#
# This is a closed, hand-curated list, the same design as
# EXPECTED_VALUE_LABEL_PATTERNS and COPULA_TOKENS, and deliberately narrow: a
# citation-shaped verb that ALSO commonly introduces the substance of a claim
# ("says", "reports", "claims", "shows", "describes", "notes") is excluded on
# purpose, because it is not safely distinguishable from a real leak using this
# pattern alone. The confirmed real counter-example proving why, from the same
# task: SVC-PC-56-1-0 r039's "Elena's cold email template SAYS the pillow shell
# is sewn in NC but the fill is from SF, and she dropped the Asheville claim
# pending confirmation" uses exactly this citation-flavored shape ("X says Y")
# to smuggle the actual finding (the fill-location discrepancy), not just to
# name a source -- and correctly does NOT match this pattern, so it stays
# flagged. "state(s)" is kept in the list despite being a similar reporting
# verb because the two confirmed r031/r032 examples both use it to introduce
# only a category label (a "sleep trial length", a "warranty period"), never
# the value itself, within the matched span; a future example where "state(s)"
# is used to smuggle an actual value would need this list narrowed again, the
# same way the THIRD CORRECTION narrowed the clause_ratio exemption below.

# A leading copula (is/are/was/were/be/been/being) is folded INTO several
# alternatives below (the ones naturally used in passive voice: "IS named on",
# "IS cited in", "IS documented in", "IS referenced in", "IS mentioned in",
# "IS listed in", "IS found in") so the copula's own character span is part of
# the citation-predicate match, not left dangling just before it -- otherwise
# find_citation_predicate_token_mask() would mark "named on" as a citation span
# but leave the "is" immediately before it unmasked, and that unmasked "is"
# would itself trip has_unquoted_copula_outside_citation and defeat the
# exemption for exactly the shape it exists to cover (confirmed real bug,
# caught by actually running this against SVC-PC-56-1-0 r029/r038 before
# trusting the fix: the first version of this pattern, without the folded-in
# copula, left both still flagged). "state(s)", "cites", and "appears/appear
# in" are active-voice verbs that are not naturally preceded by a copula
# ("is states", "is cites" are not English) so they take no such prefix.
_COPULA_PREFIX = r"(?:is|are|was|were|be|been|being)\s+"
CITATION_PREDICATE_RE = re.compile(
    rf"\b(?:{_COPULA_PREFIX})?named\s+(?:on|in)\b"
    r"|\bstates?\b"
    rf"|\b(?:{_COPULA_PREFIX})?cited\s+in\b"
    r"|\bcites\b"
    rf"|\b(?:{_COPULA_PREFIX})?documented\s+in\b"
    rf"|\b(?:{_COPULA_PREFIX})?referenced\s+in\b"
    rf"|\b(?:{_COPULA_PREFIX})?mentioned\s+in\b"
    rf"|\b(?:{_COPULA_PREFIX})?listed\s+in\b"
    r"|\bappears?\s+in\b"
    rf"|\b(?:{_COPULA_PREFIX})?found\s+in\b",
    re.IGNORECASE,
)


def tokenize_with_spans(text: str) -> list[tuple[str, int, int]]:
    """Like tokenize() below, but keeps each token's (start, end) character
    offset into the ORIGINAL text alongside the lowercased token string.
    Needed only to map a character position (an "Expected:" label match) to a
    token index -- see find_expected_clause_token_start(). str.lower() is
    length-preserving for the plain-English/business-prose text this check
    processes, so offsets taken from the original text stay valid against the
    lowercased tokens."""
    return [
        (m.group(0).lower(), m.start(), m.end()) for m in TOKEN_RE.finditer(text or "")
    ]


def tokenize(text: str) -> list[str]:
    """Lowercase word-tokens from text. Punctuation-only sequences are not
    tokens (they break runs, which is correct: "cash + net income" should not
    match "cash = net income" as a 4-token run when the operator differs)."""
    return [tok for tok, _start, _end in tokenize_with_spans(text)]


def find_expected_clause_token_start(text: str) -> int | None:
    """Token index (into tokenize(text)) where the criterion's own labeled
    expected-value clause begins, per EXPECTED_VALUE_LABEL_PATTERNS -- or
    None if the description carries no such label (confirmed real: 18 of
    23,220 SVC-PC criteria, all genuinely process/qualitative criteria with
    no single fact to label; see the module docstring). Uses the EARLIEST
    label match when more than one pattern or occurrence matches (in the real
    corpus, 23,201 of the 23,202 labeled descriptions have exactly one
    "Expected:"; the remaining one has two adjacent occurrences with nothing
    of substance between them, so earliest vs. latest makes no difference
    there either).

    This is the position-based counterpart to the numeric-ratio filter: it
    marks where the rubric switches from independently describing what to
    check to reciting its own declared answer, generalizing the numeric
    filter's intent to non-numeric expected values (names, enum/categorical
    fields, locked source quotes, structured field assignments -- see the
    module docstring's 2026-09-15 update for real examples of each)."""
    text = text or ""
    char_starts = []
    for pattern in EXPECTED_VALUE_LABEL_PATTERNS:
        match = pattern.search(text)
        if match:
            char_starts.append(match.start())
    if not char_starts:
        return None
    char_start = min(char_starts)
    for idx, (_tok, tok_start, _tok_end) in enumerate(tokenize_with_spans(text)):
        if tok_start >= char_start:
            return idx
    return None  # label matched, but no token begins at/after it (defensive; not seen in the real corpus)


def find_quoted_spans(text: str) -> list[tuple[int, int]]:
    """Character (start, end) spans of every quoted region in text, per
    QUOTE_SPAN_RE. Non-overlapping by construction (regex alternation scans
    left to right, consuming each match before looking for the next); a
    span's own quote characters are included in the range, which is harmless
    since a quote character is never itself a word-token."""
    return [(m.start(), m.end()) for m in QUOTE_SPAN_RE.finditer(text or "")]


def find_quoted_token_mask(text: str) -> list[bool]:
    """Per-token boolean mask, same length and order as tokenize(text): True
    if that token's start offset falls inside a quoted span (find_quoted_spans
    above). Used by find_matching_runs() to tell a copula that is part of a
    locked/quoted value (not narrative copying, e.g. SVC-PC-8-7-0 b2's vision
    quote or SVC-PC-10-5-0 c01's quoted field-assignment value) from a copula
    that sits in unquoted rubric prose -- see COPULA_TOKENS and the module
    docstring's THIRD CORRECTION section."""
    spans = find_quoted_spans(text)
    tokens_with_spans = tokenize_with_spans(text)
    if not spans:
        return [False] * len(tokens_with_spans)
    return [
        any(s <= tok_start < e for s, e in spans)
        for _tok, tok_start, _tok_end in tokens_with_spans
    ]


def find_citation_predicate_spans(text: str) -> list[tuple[int, int]]:
    """Character (start, end) spans of every citation/attribution predicate
    match in text, per CITATION_PREDICATE_RE. Same construction as
    find_quoted_spans() above."""
    return [(m.start(), m.end()) for m in CITATION_PREDICATE_RE.finditer(text or "")]


def find_citation_predicate_token_mask(text: str) -> list[bool]:
    """Per-token boolean mask, same length and order as tokenize(text): True if
    that token's start offset falls inside a citation-predicate span
    (find_citation_predicate_spans above). Used by find_matching_runs() to
    identify a run that cites WHICH source names/states a claim (see
    CITATION_PREDICATE_RE) as distinct from a run that states the claim's own
    substance -- see the module docstring's FOURTH CORRECTION section."""
    spans = find_citation_predicate_spans(text)
    tokens_with_spans = tokenize_with_spans(text)
    if not spans:
        return [False] * len(tokens_with_spans)
    return [
        any(s <= tok_start < e for s, e in spans)
        for _tok, tok_start, _tok_end in tokens_with_spans
    ]


def is_content_word(token: str) -> bool:
    """True if the token is NOT a stopword and NOT purely numeric/punctuation."""
    return token not in STOPWORDS and not NUMERIC_RE.fullmatch(token)


# Bare scale-unit suffix that TOKEN_RE splits off from its own preceding
# numeric/currency token: TOKEN_RE's `\$\d[\d,.-]*` alternative stops at the
# first non-digit character, so "$2M" tokenizes as TWO tokens, "$2" then "m"
# (confirmed: `\$\d[\d,.-]*` matches "$2" and halts at "M", which then matches
# the alphanumeric alternative on its own). Without this, a scale-suffixed
# dollar figure ("$2M", "$150K", "$1.2B") has its unit letter counted as a
# "content word" by count_content_words() and NOT counted as numeric by
# count_numeric(), deflating numeric_ratio for what is still a bare
# value-citation. Confirmed real false positive from the 2026-09-16 26-task
# fail-tier review of the real 202-task corpus (C:/ekwqc/_step2_full_202/
# answer_key_rubric_leak.json): SVC-PC-25-6-0 c10 ("CGL $2M/occ & $5M
# aggregate; Product Liability $5M", golden token-level match confirmed
# verbatim in Cirrus_FY2021_Contractual_Risk_Transfer_and_Certificate_
# Review.xlsx's own "critical gap" list) and SVC-PC-12-6-0 r019 (same shape,
# "$1M occurrence / $2M aggregate ... legal liability", confirmed verbatim in
# Compliance_Memo.docx) -- both hand-verified against the real golden file
# text, not inferred: the matched run in both is a bare insurance-limits
# citation, the same "expected value legitimately appears in golden" shape
# SVC-PC-7-4-0 o5 (this file's own original numeric-ratio calibration
# negative, "NovaTex $782,769; Sierra $338,011; ...") already established as
# safe, defeated here only by TOKEN_RE splitting the unit letter off the
# figure it belongs to. Deliberately requires IMMEDIATE adjacency to a
# numeric token (not a bare "m"/"k"/"b" anywhere in the run) -- the same
# narrow, positional design as STATE_TAIL_MAX_TOKENS and the citation-predicate
# copula carve-out, so a token that happens to be a bare "k" or "b" for an
# unrelated reason (not observed in this corpus, but not ruled out) is never
# reclassified unless it directly follows the number it scales.
SCALE_SUFFIX_TOKENS = {"k", "m", "b", "mm", "bn", "mn"}


def _numeric_token_mask(tokens: list[str]) -> list[bool]:
    """Per-token boolean mask, same length/order as tokens: True if the token
    itself is purely numeric/currency/punctuation (NUMERIC_RE), OR it is a
    bare SCALE_SUFFIX_TOKENS token immediately following a token that is --
    see SCALE_SUFFIX_TOKENS above. Shared by count_content_words() and
    count_numeric() so a token is never counted as both a "content word" and
    "numeric" at once."""
    mask = []
    prev_numeric = False
    for t in tokens:
        if NUMERIC_RE.fullmatch(t):
            mask.append(True)
            prev_numeric = True
        elif prev_numeric and t in SCALE_SUFFIX_TOKENS:
            mask.append(True)
            prev_numeric = False  # one suffix per number; "m aggregate" doesn't chain
        else:
            mask.append(False)
            prev_numeric = False
    return mask


def count_content_words(tokens: list[str]) -> int:
    mask = _numeric_token_mask(tokens)
    return sum(
        1 for t, is_num in zip(tokens, mask) if not is_num and t not in STOPWORDS
    )


def count_numeric(tokens: list[str]) -> int:
    """Tokens that are purely numeric/currency/punctuation, plus a scale-unit
    suffix immediately following one of those -- see SCALE_SUFFIX_TOKENS and
    _numeric_token_mask(). Used for the numeric-ratio filter."""
    return sum(_numeric_token_mask(tokens))


# Calibrated against the two confirmed-safe real examples (SVC-PC-56-1-0
# r031/r032: tails "a sleep trial length" = 4 tokens, "a warranty period" = 3
# tokens, neither containing a digit) -- see _state_tail_is_safe() below and
# the module docstring's FOURTH CORRECTION, "state(s) tail check" subsection.
STATE_TAIL_MAX_TOKENS = 4

# TOKEN_RE lets trailing punctuation ($ % . , ' -) stick to the word it
# follows, so "state," or "state." is ONE token ("state," / "state."), not
# "state" plus a separate punctuation token. A plain `tok in ("state",
# "states")` check misses every "state"/"states" immediately followed by a
# comma or period -- extremely common in prose -- and silently skips the
# tail check below for exactly those, which is worse than not having the
# check at all (confirmed real bug, caught the same way the copula-prefix
# bug above was: by running this against the full corpus rather than
# trusting the 4 hand-picked calibration examples. SVC-PC-60-2-0 c23's
# "...document category, COMPLETION STATE, owner, due point, evidence
# locator, and escalation; do not copy personal document data..." was wrongly
# exempted this way: the token is "state," (comma glued on), so
# `tok in ("state", "states")` never matched it and its 12-token, non-numeric
# tail was never checked at all. This regex strips any such trailing
# punctuation before comparing, so "state," / "states." / "state.'" all
# still count as the bare word for this check.
_BARE_STATE_RE = re.compile(r"^states?[.,'-]*$")


def _state_tail_is_safe(run: list[str]) -> bool:
    """True unless the run contains a bare 'state'/'states' token (trailing
    punctuation glued on by TOKEN_RE ignored -- see _BARE_STATE_RE) whose
    tail (the tokens after it, within this SAME run) is either longer than
    STATE_TAIL_MAX_TOKENS or contains a digit character in any token.

    Why "state(s)" specifically needs this and the other CITATION_PREDICATE_RE
    alternatives (named on/in, cited in, cites, documented in, referenced in,
    mentioned in, listed in, appears/appear in, found in) do not: those are
    all structurally passive/prepositional -- "X is named ON/IN Y" -- so their
    object Y is grammatically a location/source reference. "X states Y" has
    no such constraint; Y can be any clause, including the graded substance
    itself. Confirmed real risk, found by re-running this fix against the
    FULL 600-task corpus (C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready)
    rather than trusting the 202-task subset this fix was scoped to: WITHOUT
    this guard, SVC-PC-62-1-0 c01's "terms state a 100-night trial with
    stated refund and U.S. return-shipping conditions" and SVC-PC-60-0-0
    c11's "policy states new hires complete security onboarding within five
    business days and annual refresher training on the anniversary" were
    both wrongly exempted -- both state the graded substance itself (a trial
    length, a policy's actual terms), not just which source states something.
    WITH this guard (checked directly against the real corpus, not assumed):
    both revert to their original classification, and the two confirmed-safe
    examples (SVC-PC-56-1-0 r031/r032) stay exempted, because their matched
    runs happen to stop at the bare category label ("length"/"period")
    wherever the golden's own wording diverges from the rubric's right after
    it -- a property of the run itself (bounded by mutual token overlap with
    the golden), not of the rubric's full sentence, which is why this checks
    the RUN's own tail rather than the criterion description's tail.
    """
    for idx, tok in enumerate(run):
        if _BARE_STATE_RE.match(tok):
            tail = run[idx + 1 :]
            if len(tail) > STATE_TAIL_MAX_TOKENS:
                return False
            if any(any(ch.isdigit() for ch in t) for t in tail):
                return False
    return True


# A closed set of punctuation characters that TOKEN_RE treats as hard token
# separators (never become part of a token themselves, unlike "-" which IS
# preserved inside a token -- see TOKEN_RE) and that this corpus's authoring
# convention uses specifically to join short field/tab/section-name items or
# set off a parenthetical schema/location reference, rather than to punctuate
# an ordinary sentence -- see is_schema_enumeration in find_matching_runs()
# below and the module docstring's SIXTH CORRECTION (2026-09-16). Confirmed
# against all six real target cases: "/" (SVC-PC-10-5-0's
# cash_in/ending_cash/..., SVC-PC-22-2-0's accessory/insert/gift-set), ";"
# (SVC-PC-91-8-0's "...architecture; build effort...", SVC-PC-88-0-0's
# "...CFO); Cirrus Sleep FY2021"), "&" (SVC-PC-91-8-0's "scope &
# architecture"), "_" (SVC-PC-10-5-0's snake_case field names, SVC-PC-17-2-0's
# "Year_1_Annual_PnL" sheet-tab reference), and "(" / ")" (the parenthetical
# wrapper in four of the six). Comma is deliberately EXCLUDED despite reading
# as a list-delimiter too: it is far too common in ordinary narrative prose to
# serve as a structural signal by itself -- confirmed real risk, not a
# hypothetical: SVC-PC-56-1-0 r005's confirmed-genuine leak ("...not
# customer-facing claims, and are included for reference...") itself contains
# two commas, which would tie it with the least-delimited real target case
# (SVC-PC-46-3-0, 2 delimiters from this closed set) if comma counted. Period
# and colon are excluded for the same reason (ordinary sentence punctuation).
STRUCTURAL_LIST_DELIM_RE = re.compile(r"[/;&_()]")

# Calibrated against all six confirmed real target cases (minimum 2
# delimiters from STRUCTURAL_LIST_DELIM_RE, SVC-PC-46-3-0's "displaced
# item(s), and new target sprint") and the confirmed-genuine population's own
# worst incidental case (maximum 1 delimiter among findings with no unquoted
# copula -- SVC-PC-17-4-0 r014's stray ")", SVC-PC-12-6-0 r021's stray "/" in
# "order/customer data", SVC-PC-29-2-0 r003's stray "_" in "Business_Title" --
# see the module docstring's SIXTH CORRECTION for the full verification). A
# real margin (1 vs. 2) found by checking every currently-flagged finding in
# Khiem's 202-task subset, not a threshold picked to exactly split one data
# point. The one genuine finding with 4 delimiters (SVC-PC-53-3-0 r006) is
# already excluded by the copula check above it, independent of this
# threshold.
STRUCTURAL_LIST_MIN_DELIMS = 2

# A period or colon immediately followed by whitespace -- a real sentence or
# clause boundary, as opposed to a decimal point or a filename extension
# ("Policy.docx", "$4.5M"), neither of which TOKEN_RE itself splits on and
# neither of which is ever followed by a space. Used by is_schema_enumeration
# above to reject a run that spans two or more complete sentences: a bare
# schema/field enumeration is one phrase-level list by definition, so a
# multi-sentence run is prose regardless of its delimiter count. Found during
# the SIXTH CORRECTION's full-600-task verification: SVC-PC-62-6-0 c04's run
# crosses STRUCTURAL_LIST_MIN_DELIMS on one incidental semicolon and one
# incidental slash while actually being two sentences describing a real
# policy-vs-inventory discrepancy -- see is_schema_enumeration's comment.
SENTENCE_BREAK_RE = re.compile(r"[.:]\s")


def find_matching_runs(
    rubric_tokens: list[str],
    golden_tokens: list[str],
    min_run: int = 7,
    rubric_clause_start: int | None = None,
    rubric_quoted_mask: list[bool] | None = None,
    rubric_citation_mask: list[bool] | None = None,
    rubric_text: str | None = None,
    rubric_token_spans: list[tuple[int, int]] | None = None,
) -> list[dict]:
    """Find all maximal runs of >= min_run consecutive matching word-tokens
    between the rubric and golden token sequences.

    Algorithm: build a position index of every golden min_run-gram (the set of
    starting positions for each distinct n-gram). Scan the rubric left to
    right; at each position, check if the min_run-gram starting there appears
    in the golden. If it does, extend forward from every matching golden
    position, keeping the longest extension. Record the maximal run and skip
    past it (no overlapping runs).

    rubric_clause_start, when given, is a token index into rubric_tokens (from
    find_expected_clause_token_start()) marking where the criterion's own
    labeled expected-value clause begins. Each returned run records what
    fraction of ITS OWN tokens fall at or after that index (clause_ratio) --
    see classify_run() for how that fraction is used. None means the
    description carried no such label, so every run gets clause_ratio 0.0.

    rubric_quoted_mask, when given, is a per-token boolean mask into
    rubric_tokens (from find_quoted_token_mask()) marking which tokens sit
    inside a quoted span. Each returned run records whether it contains a
    COPULA_TOKENS token that is NOT inside a quoted span
    (has_unquoted_copula) -- see classify_run() and the module docstring's
    THIRD CORRECTION section for why this blocks the clause_ratio exemption.
    None (no mask given) checks every token in the run against COPULA_TOKENS
    with no quote carve-out, which is the conservative choice: it can only
    make has_unquoted_copula MORE likely to be True, never less, so a caller
    that omits the mask never gets a leak silently re-exempted.

    rubric_citation_mask, when given, is a per-token boolean mask into
    rubric_tokens (from find_citation_predicate_token_mask()) marking which
    tokens sit inside a citation/attribution predicate match (see
    CITATION_PREDICATE_RE). Each returned run records has_citation_predicate
    (whether ANY of its own tokens fall inside such a span) and
    has_unquoted_copula_outside_citation (like has_unquoted_copula, but ALSO
    excluding a copula that sits inside a citation-predicate span, e.g. the
    "is" in "is named on") -- see classify_run() and the module docstring's
    FOURTH CORRECTION section for how these combine into the source-citation
    exemption. None (no mask given) sets has_citation_predicate False for
    every run (never exempts), the conservative default, matching
    rubric_quoted_mask's own None convention above.

    rubric_text and rubric_token_spans, when BOTH given, let each returned run
    recover its own literal character span in the ORIGINAL (untokenized)
    rubric text -- rubric_token_spans is tokenize_with_spans(rubric_text)'s
    own (start, end) offsets, one pair per rubric_tokens entry. Used only for
    is_schema_enumeration (see STRUCTURAL_LIST_DELIM_RE and the module
    docstring's SIXTH CORRECTION): TOKEN_RE strips the very delimiter
    punctuation ("/", ";", "&", "_", parens) that shape is recognized by, so
    the stripped token list alone cannot see it -- only the raw span can.
    Either argument missing (the default) sets is_schema_enumeration False for
    every run, the same conservative "cannot compute, never exempt" default
    the other two masks use.

    Returns a list of dicts: {run_length, content_words, numeric_count,
    numeric_ratio, clause_ratio, has_unquoted_copula, has_citation_predicate,
    is_source_citation, is_schema_enumeration, matched_text}. Sorted by first
    appearance in the rubric.
    """
    n = len(golden_tokens)
    r = len(rubric_tokens)
    if n < min_run or r < min_run:
        return []

    # Build index: golden n-gram -> list of starting positions in golden_tokens.
    # O(n * min_run) in time, O(n) entries.
    golden_positions: dict[tuple, list[int]] = defaultdict(list)
    for i in range(n - min_run + 1):
        gram = tuple(golden_tokens[i : i + min_run])
        golden_positions[gram].append(i)

    matches = []
    i = 0
    while i <= r - min_run:
        gram = tuple(rubric_tokens[i : i + min_run])
        positions = golden_positions.get(gram)
        if not positions:
            i += 1
            continue
        # Extend forward from every matching golden position, keep the longest.
        best_end = i + min_run
        for gpos in positions:
            j = i + min_run
            k = gpos + min_run
            while j < r and k < n and rubric_tokens[j] == golden_tokens[k]:
                j += 1
                k += 1
            if j > best_end:
                best_end = j
        run = rubric_tokens[i:best_end]
        cw = count_content_words(run)
        nc = count_numeric(run)
        ratio = nc / len(run) if run else 1.0
        if rubric_clause_start is None:
            clause_ratio = 0.0
        else:
            covered = max(0, best_end - max(i, rubric_clause_start))
            clause_ratio = covered / len(run) if run else 0.0
        if rubric_quoted_mask is None:
            has_unquoted_copula = any(tok in COPULA_TOKENS for tok in run)
        else:
            has_unquoted_copula = any(
                tok in COPULA_TOKENS
                and not (pos < len(rubric_quoted_mask) and rubric_quoted_mask[pos])
                for pos, tok in enumerate(run, start=i)
            )
        # Source-citation exemption (FOURTH CORRECTION, 2026-09-15) -- see
        # CITATION_PREDICATE_RE and find_citation_predicate_token_mask(). A run
        # that both (a) contains a citation-predicate token and (b) contains no
        # unquoted, non-citation copula is a candidate for the exemption in
        # classify_run(); (b) is the same defensive shape as has_unquoted_copula
        # above (a copula inside the citation predicate itself, e.g. the "is" in
        # "is named on", does not count against it, but any OTHER copula does).
        if rubric_citation_mask is None:
            has_citation_predicate = False
            has_unquoted_copula_outside_citation = has_unquoted_copula
        else:
            has_citation_predicate = any(
                rubric_citation_mask[pos]
                for pos in range(i, best_end)
                if pos < len(rubric_citation_mask)
            )
            has_unquoted_copula_outside_citation = any(
                tok in COPULA_TOKENS
                and not (
                    pos < len(rubric_quoted_mask or []) and rubric_quoted_mask[pos]
                )
                and not (pos < len(rubric_citation_mask) and rubric_citation_mask[pos])
                for pos, tok in enumerate(run, start=i)
            )
        is_source_citation = (
            has_citation_predicate
            and not has_unquoted_copula_outside_citation
            and _state_tail_is_safe(run)
        )
        # Schema/field-name-enumeration exemption (SIXTH CORRECTION,
        # 2026-09-16) -- see STRUCTURAL_LIST_DELIM_RE and the module
        # docstring. A run is a bare schema/field/section-name enumeration,
        # not narrative prose, if (a) it sits entirely BEFORE the criterion's
        # own "Expected:" label (clause_ratio == 0.0 -- deliberately narrower
        # than the clause_ratio exemption above, which covers the opposite
        # side of the label; every confirmed real example of THIS shape sits
        # in the rationale, none after the label, so this exemption is not
        # extended there without a real example to calibrate against), (b)
        # contains no unquoted copula (same defensive shape as every other
        # exemption above), (c) its own literal span in the ORIGINAL rubric
        # text -- not the stripped token list, which is blind to the very
        # punctuation this shape is recognized by -- contains at least
        # STRUCTURAL_LIST_MIN_DELIMS characters from STRUCTURAL_LIST_DELIM_RE,
        # AND (d) that same span contains no INTERNAL sentence break (a "."
        # or ":" immediately followed by whitespace, i.e. NOT a decimal point
        # or a filename extension like "Policy.docx", which never has a space
        # right after the period -- see SENTENCE_BREAK_RE). A bare
        # schema/field enumeration is, by definition, one phrase-level list;
        # a run spanning two or more complete sentences is prose, no matter
        # how many delimiter characters it happens to contain. Found during
        # the SIXTH CORRECTION's own full-600-task verification, not assumed
        # safe from the 202-task sample alone: SVC-PC-62-6-0 c04's run
        # ("Policies describe consumer commitments...execution. Cookie policy
        # says no heat-mapping tools while licence inventory lists Hotjar...")
        # spans two full sentences and reveals a specific analytical finding
        # (a policy-vs-inventory discrepancy), not a field list -- it must
        # stay flagged despite crossing the delimiter threshold on one
        # incidental semicolon and one incidental slash. Requiring (d) does
        # not narrow any of the six original confirmed targets (none contain
        # an internal sentence break in their own matched span).
        if rubric_text is None or rubric_token_spans is None:
            is_schema_enumeration = False
        else:
            raw_span = rubric_text[
                rubric_token_spans[i][0] : rubric_token_spans[best_end - 1][1]
            ]
            is_schema_enumeration = (
                clause_ratio == 0.0
                and not has_unquoted_copula
                and len(STRUCTURAL_LIST_DELIM_RE.findall(raw_span))
                >= STRUCTURAL_LIST_MIN_DELIMS
                and not SENTENCE_BREAK_RE.search(raw_span)
            )
        matches.append(
            {
                "run_length": len(run),
                "content_words": cw,
                "numeric_count": nc,
                "numeric_ratio": round(ratio, 3),
                "clause_ratio": round(clause_ratio, 3),
                "has_unquoted_copula": has_unquoted_copula,
                "has_citation_predicate": has_citation_predicate,
                "is_source_citation": is_source_citation,
                "is_schema_enumeration": is_schema_enumeration,
                "matched_text": " ".join(run),
            }
        )
        i = best_end
    return matches


def classify_run(
    run: dict,
    candidate_run: int = 8,
    candidate_cw: int = 6,
    flagged_run: int = 9,
    flagged_cw: int = 7,
    max_numeric_ratio: float = 0.4,
    min_clause_ratio: float = 0.6,
):
    """Returns 'flagged', 'candidate', or None for one matching run.

    Four independent exemptions are checked before either tier; any one
    alone clears the run at any tier:
      - too numeric (> max_numeric_ratio): expected-value matching via
        digits/currency/percentages (the original v1 filter).
      - substantially inside the criterion's own labeled expected-value
        clause (clause_ratio >= min_clause_ratio -- see find_matching_runs()
        and find_expected_clause_token_start()) AND NOT has_unquoted_copula:
        expected-value matching via the corpus's "Expected:" convention
        regardless of whether the value is numeric, a name, an enum, or a
        locked quote (the v2, 2026-09-15 generalization -- see the module
        docstring), UNLESS the run itself contains an unquoted copula
        (is/are/was/were/...), in which case it reads as a narrative
        assertion copied from the golden's own prose rather than a declared
        value, and the clause_ratio exemption does not apply no matter how
        much of the labeled clause it covers (the THIRD CORRECTION,
        2026-09-15 -- see the module docstring; this is the fix for the
        clause_ratio regression: SVC-PC-14-6-0 c07 and SVC-PC-67-1-0 r011
        both have clause_ratio 1.0 and both contain an unquoted copula in
        the matched run, and both must be flagged, not exempted). A copula
        INSIDE a quoted span (find_quoted_token_mask()) does not count --
        SVC-PC-8-7-0 b2's vision quote and SVC-PC-10-5-0 c01's quoted field
        assignment both contain a copula inside quote marks and both must
        stay exempt.
      - is_source_citation (see find_matching_runs(), CITATION_PREDICATE_RE):
        the run names WHICH source document(s) carry or assert a claim (e.g.
        "OEKO-TEX Standard 100 is named on the internal FAQ, pre-launch
        creative brief..."), not the claim's own substance, AND contains no
        unquoted copula OUTSIDE the citation predicate itself (the FOURTH
        CORRECTION, 2026-09-15 -- see the module docstring; this exemption is
        independent of clause_ratio/clause position on purpose, since the
        confirmed real examples, SVC-PC-56-1-0 r029/r031/r032/r038, all sit in
        the criterion's RATIONALE sentence before its "Expected:" label,
        which the clause_ratio exemption never covers).
      - is_schema_enumeration (see find_matching_runs(),
        STRUCTURAL_LIST_DELIM_RE): the run is a bare schema/field/section-name
        enumeration -- e.g. "cash_in/ending_cash/...", "integration scope &
        architecture; build effort & timeline..." -- rather than narrative
        prose (the SIXTH CORRECTION, 2026-09-16 -- see the module docstring).
        Requires clause_ratio == 0.0 (entirely before the "Expected:" label;
        deliberately narrower than clause_ratio's own exemption, which covers
        the opposite side), no unquoted copula, at least
        STRUCTURAL_LIST_MIN_DELIMS characters from the closed
        STRUCTURAL_LIST_DELIM_RE set in the run's own ORIGINAL-text span (not
        its stripped tokens), AND no internal sentence break in that same
        span (SENTENCE_BREAK_RE -- a bare enumeration is one phrase-level
        list, never two or more complete sentences, however many delimiters
        it contains; added after a full-corpus pass found a real two-sentence
        analytical finding, SVC-PC-62-6-0 c04, that crossed the delimiter
        threshold only by coincidence). Independent of numeric_ratio/
        clause_ratio/is_source_citation on purpose, like is_source_citation is
        independent of clause_ratio -- the confirmed real examples are
        non-numeric, pre-label, and cite no source document, so none of the
        first three exemptions can reach them.
    A run clearing none of the four is scored by the two tiers, ordered:
    flagged (stronger) takes precedence over candidate (weaker). A run that
    meets neither threshold returns None.
    """
    if run["numeric_ratio"] > max_numeric_ratio:
        return None
    if run.get("clause_ratio", 0.0) >= min_clause_ratio and not run.get(
        "has_unquoted_copula", False
    ):
        return None
    if run.get("is_source_citation", False):
        return None
    if run.get("is_schema_enumeration", False):
        return None
    if run["run_length"] >= flagged_run and run["content_words"] >= flagged_cw:
        return "flagged"
    if run["run_length"] >= candidate_run and run["content_words"] >= candidate_cw:
        return "candidate"
    return None


# ---------------------------------------------------------------------------
# text extraction from golden files
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".xlsx",
    ".xlsm",
    ".docx",
    ".pptx",
}


def read_docx_text(path: Path) -> str:
    """python-docx if available; else zipfile + regex pull of every <w:t> text
    run out of word/document.xml. Same approach as
    answer_key_content_leak_check.py's read_docx_text."""
    if HAVE_PYTHON_DOCX:
        try:
            document = _python_docx.Document(str(path))
            parts = [p.text for p in document.paragraphs]
            for table in document.tables:
                for row in table.rows:
                    for cell in row.cells:
                        parts.append(cell.text)
            return "\n".join(parts)
        except Exception:
            pass  # fall through to the zipfile fallback
    with zipfile.ZipFile(path) as zf:
        if "word/document.xml" not in zf.namelist():
            return ""
        xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
        return " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))


def read_pptx_text(path: Path) -> str:
    """Extract text from every slide in a .pptx (a zip of XML slide files).
    Each <a:t> element in a slide XML is a text run. No python-pptx dependency:
    the zipfile approach is the same one used for .docx above and is sufficient
    for text extraction (python-pptx would add richer table/notes access, but
    the golden pptx files in the mirrored corpus are slide-text-only)."""
    texts = []
    with zipfile.ZipFile(path) as zf:
        for name in sorted(zf.namelist()):
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                try:
                    xml = zf.read(name).decode("utf-8", errors="replace")
                    texts.append(" ".join(re.findall(r"<a:t[^>]*>([^<]*)</a:t>", xml)))
                except Exception:
                    continue
    return "\n".join(texts)


# Self-check / self-audit tab exclusion (v5, 2026-09-15) -- see the module
# docstring's FIFTH CORRECTION. A golden SVC-PC workbook sometimes includes a
# sheet whose own declared purpose is letting the solution author verify the
# workbook against the grading rubric before submission. That sheet
# deliberately restates each rubric criterion's own "Expected"/"Requirement"
# text so the author can check it off -- the copy direction is
# rubric-into-self-check-tab, the OPPOSITE of a real leak
# (golden-reasoning-into-rubric). This is not a classify_run() exemption like
# the three above (numeric-ratio, clause-ratio, is_source_citation): it acts
# at golden-content EXTRACTION time, on the GOLDEN side, not the rubric side,
# the same kind of decision as SUPPORTED_EXTENSIONS (some content never enters
# the golden token stream at all) rather than a per-run classification signal.
#
# Confirmed real examples, all under
# C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready (found via a corpus-wide
# scan of every golden .xlsx/.xlsm sheet name, not guessed from one task):
#   SVC-PC-75-1-0 "Rubric_Self_Check" -- the task that surfaced this false
#     positive. Header: "Rubric Self-Check -- response vs. its own grading
#     rubric." Columns: ID | Category | Expected value / check
#     (self-contained) | Points | Must-pass? | Met? | Evidence in this
#     workbook. Criterion r22's "Expected:" clause ("All reconciliation checks
#     PASS; the only non-tie ... is flagged informational, not an error") is
#     copied verbatim into this sheet's row for r22 -- confirmed by direct
#     search of the workbook: that exact phrasing exists ONLY in this sheet.
#     The workbook's "Checks" sheet also discusses the same $221,185/$423,359
#     figures but in unrelated, non-matching wording ("Check 16 (DIFF):
#     inventory_flows.csv cogs_value ... represents SKU-level product COGS
#     only ..."), so excluding just this sheet resolves the false positive
#     without touching the genuinely different text elsewhere in the file.
#   SVC-PC-1-2-0 "Rubric Self-Check", SVC-PC-7-1-0 "Rubric Self-Check",
#     SVC-PC-7-2-0 "Rubric_SelfCheck", SVC-PC-7-4-0 "Rubric_Self_Check" -- four
#     more real instances, same convention, three different separator styles
#     in the sheet name (space, none, single underscore, double underscore)
#     and four different exact header wordings ("Rubric Self-Check (target ~
#     full marks)", "SELF-ASSESSMENT AGAINST L2-02 TASK 7 RUBRIC", "Self-check
#     against the saved L2-04 rubric. Expected score: 100/100 ...").
#   SVC-PC-3-7-0 "Rubric Coverage" -- confirms the header check is needed, not
#     just the sheet-name check: this sheet's NAME contains neither "self" nor
#     "check", but its header row reads "Final response self-check: explicit
#     answers and evidence for every scored criterion" -- the same convention
#     under a different sheet name. A name-only check misses this real
#     example; a header-only check would have caught it alone.
SELF_CHECK_SHEET_NAME_SUBSTRINGS = ("selfcheck", "selfaudit", "rubriccheck")

# Header-text signal: requires BOTH "rubric" and a self-referential term
# (self-check/self-assessment, any space/underscore/hyphen separator) to
# co-occur in the sheet's own first few rows. Calibrated against all six real
# examples above -- every one states its purpose as verifying the workbook
# AGAINST THE RUBRIC using self-check/self-assessment language, including
# "Rubric Coverage"'s "Final response self-check ...". Deliberately requires
# co-occurrence rather than either term alone: a real business worksheet in a
# finance-scenario golden (revenue schedules, control registers, vendor plans,
# cap tables) has no occasion to use the word "rubric" at all, so this could
# only clear a real leak if the leaking sheet's own header happened to also
# independently mention "rubric" AND self-check/self-assessment language --
# not observed anywhere in the corpus scan that found these six examples.
SELF_CHECK_HEADER_RUBRIC_RE = re.compile(r"\brubric", re.IGNORECASE)
SELF_CHECK_HEADER_SELFTERM_RE = re.compile(
    r"self[\s_-]*check|self[\s_-]*assess", re.IGNORECASE
)

# All six real examples state their purpose in row 1 or row 2 (1-indexed);
# reading a few extra rows costs nothing (read_only mode bounds the scan) and
# leaves headroom for a title spread across more lines.
SELF_CHECK_HEADER_MAX_ROWS = 5


def _normalize_sheet_identifier(text: str) -> str:
    """Lowercase with every run of whitespace/underscore/hyphen collapsed to
    nothing, so 'Rubric Self-Check', 'Rubric_SelfCheck', and 'Rubric_Self_Check'
    (three real sheet-naming variants confirmed in the corpus scan above) all
    normalize to the same string 'rubricselfcheck'."""
    return re.sub(r"[\s_-]+", "", text or "").lower()


def is_self_check_sheet_name(sheet_name: str) -> bool:
    """True if the sheet's own name (after _normalize_sheet_identifier) marks
    it as a self-check/self-audit tab on its own, per
    SELF_CHECK_SHEET_NAME_SUBSTRINGS. Deliberately narrow: nothing broader
    (e.g. bare "rubric") is included, because a sheet can legitimately be
    named something rubric-adjacent without being a self-check tab in the name
    alone -- SVC-PC-3-7-0's real "Rubric Coverage" example is exactly this
    case, and is_self_check_sheet_header() below is what catches it instead,
    from the sheet's own header text."""
    normalized = _normalize_sheet_identifier(sheet_name)
    return any(s in normalized for s in SELF_CHECK_SHEET_NAME_SUBSTRINGS)


def is_self_check_sheet_header(ws) -> bool:
    """Reads up to SELF_CHECK_HEADER_MAX_ROWS rows of ws (an openpyxl
    worksheet, read_only or not) and returns True if the combined text
    co-occurs "rubric" and a self-check/self-assessment term -- see
    SELF_CHECK_HEADER_RUBRIC_RE / SELF_CHECK_HEADER_SELFTERM_RE above. Reads
    only a handful of rows, not the full sheet, so this is cheap even on a
    large workbook; confirmed safe to call before a second, unbounded
    iter_rows() pass over the same read-only worksheet (read-only mode
    supports multiple independent iterations). Never raises: any read error
    is treated as "no header match" -- conservative, since a sheet this
    cannot read the header of is then scored exactly as before, not exempted."""
    try:
        header_text = " ".join(
            str(v)
            for row in ws.iter_rows(
                min_row=1, max_row=SELF_CHECK_HEADER_MAX_ROWS, values_only=True
            )
            for v in row
            if isinstance(v, str)
        )
    except Exception:
        return False
    return bool(
        SELF_CHECK_HEADER_RUBRIC_RE.search(header_text)
        and SELF_CHECK_HEADER_SELFTERM_RE.search(header_text)
    )


def is_self_check_sheet(ws) -> bool:
    """A sheet is excluded from golden-content extraction as a self-check/
    self-audit tab if EITHER its own name or its own header text (first few
    rows) matches the convention -- either signal alone is sufficient, the
    same OR design as the numeric-ratio/clause-ratio/is_source_citation
    exemptions, because the real corpus examples split across both signals:
    SVC-PC-3-7-0's "Rubric Coverage" is caught by header text alone (its name
    matches neither), and the other five real examples are caught by sheet
    name alone (their header wording varies too much per task to share one
    literal regex across all five, e.g. "Rubric Self-Check (target ~ full
    marks)" vs. "SELF-ASSESSMENT AGAINST L2-02 TASK 7 RUBRIC")."""
    return is_self_check_sheet_name(ws.title) or is_self_check_sheet_header(ws)


def read_xlsx_text(path: Path) -> str:
    """Every string cell and every numeric cell (as a string) from every
    sheet, EXCEPT a sheet identified as a self-check/self-audit tab
    (is_self_check_sheet() above, see the module docstring's FIFTH
    CORRECTION). Such a sheet's entire purpose is restating the rubric's own
    criteria back at itself for author verification, so its content is never
    treated as "golden answer content" for this check's comparison -- the
    same kind of decision as excluding an unsupported file extension, just at
    sheet granularity instead of file granularity. data_only=True,
    read_only=True for speed, matching answer_key_content_leak_check.py's
    scan_environment_file convention."""
    texts = []
    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    for ws in wb.worksheets:
        if is_self_check_sheet(ws):
            continue
        for row in ws.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, bool):
                    continue
                if isinstance(value, str):
                    if len(value.strip()) > 2:
                        texts.append(value)
                elif isinstance(value, (int, float)):
                    texts.append(str(value))
    wb.close()
    return "\n".join(texts)


def extract_file_text(path: Path) -> tuple[str, str | None]:
    """Returns (text, error). Never raises -- an unparseable file returns an
    error string and empty text rather than crashing the task."""
    suffix = path.suffix.lower()
    try:
        if suffix in (".txt", ".md", ".csv", ".json"):
            return path.read_text(encoding="utf-8", errors="replace"), None
        elif suffix in (".xlsx", ".xlsm"):
            return read_xlsx_text(path), None
        elif suffix == ".docx":
            return read_docx_text(path), None
        elif suffix == ".pptx":
            return read_pptx_text(path), None
    except Exception as exc:
        return "", str(exc)
    return "", f"unsupported extension: {suffix}"


# ---------------------------------------------------------------------------
# task format dispatch -- same pattern as answer_key_content_leak_check.py
# ---------------------------------------------------------------------------


def _task_format(task_dir: Path) -> str:
    """Which config shape this task uses ("svc_pc", "ekw", or "none"). SVC-PC
    detection (tests/deliverables*/judge.toml) takes precedence over EKW
    (tests/verifier.json), matching answer_key_content_leak_check.py's
    _task_format exactly."""
    tests_dir = task_dir / "tests"
    if tests_dir.is_dir() and (
        any(tests_dir.glob("deliverables/judge.toml"))
        or any(tests_dir.glob("deliverables_*/judge.toml"))
    ):
        return "svc_pc"
    if has_ekw_config(task_dir):
        return "ekw"
    return "none"


def find_task_dirs(root: Path, task_ids=None, id_prefix: str = "") -> list[Path]:
    if task_ids:
        dirs = []
        for tid in task_ids:
            p = root / tid
            if not p.is_dir():
                print(f"WARNING: task dir not found, skipping: {p}", file=sys.stderr)
                continue
            dirs.append(p)
        return dirs
    return sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix)
    )


# ---------------------------------------------------------------------------
# rubric criterion extraction
# ---------------------------------------------------------------------------


def load_svc_criteria(task_dir: Path) -> tuple[list[dict], list[str]]:
    """Every criterion across every tests/deliverables*/judge.toml for this
    task. Returns (criteria, parse_errors). Each criterion dict carries
    {name, description, judge_group}. Never raises."""
    criteria = []
    parse_errors = []
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return criteria, parse_errors
    judge_files = sorted(
        set(tests_dir.glob("deliverables/judge.toml"))
        | set(tests_dir.glob("deliverables_*/judge.toml"))
    )
    for jt in judge_files:
        try:
            data = tomllib.loads(jt.read_text(encoding="utf-8"))
        except Exception as exc:
            parse_errors.append(f"{jt.relative_to(task_dir)}: {exc}")
            continue
        group = jt.parent.name
        for c in data.get("criterion", []):
            criteria.append(
                {
                    "name": c.get("name", "?"),
                    "description": c.get("description") or "",
                    "judge_group": group,
                }
            )
    return criteria, parse_errors


def load_ekw_criteria_list(task_dir: Path) -> tuple[list[dict], list[str]]:
    """Every verifier criterion via ekw_verifier_json.load_ekw_criteria().
    Returns (criteria, parse_errors). Each criterion dict carries
    {name, description, judge_group}. Never raises."""
    criteria = []
    parse_errors = []
    for c in load_ekw_criteria(task_dir):
        if c["name"] == "__parse_error__":
            parse_errors.append(f"tests/verifier.json: {c['description']}")
            continue
        criteria.append(
            {
                "name": c["name"],
                "description": c["description"] or "",
                "judge_group": c["group"],
            }
        )
    return criteria, parse_errors


def load_criteria_for_task(task_dir: Path) -> tuple[list[dict], list[str], str]:
    """Format-dispatching wrapper. Returns (criteria, parse_errors, fmt)."""
    fmt = _task_format(task_dir)
    if fmt == "ekw":
        crit, errs = load_ekw_criteria_list(task_dir)
        return crit, errs, fmt
    crit, errs = load_svc_criteria(task_dir)
    return crit, errs, fmt


# ---------------------------------------------------------------------------
# golden file discovery and text extraction
# ---------------------------------------------------------------------------


def find_golden_files(task_dir: Path, fmt: str) -> list[Path]:
    """Golden/reference answer files for this task. SVC-PC: solution/files/.
    EKW: solution/golden_outputs/. Only text-bearing supported extensions.
    Returns sorted list of file paths. Empty list if the directory does not
    exist (a real coverage gap, not an error)."""
    if fmt == "svc_pc":
        golden_dir = task_dir / "solution" / "files"
    elif fmt == "ekw":
        golden_dir = task_dir / "solution" / "golden_outputs"
    else:
        # Try both paths for a task whose format was not detected.
        for candidate in (
            task_dir / "solution" / "files",
            task_dir / "solution" / "golden_outputs",
        ):
            if candidate.is_dir():
                golden_dir = candidate
                break
        else:
            return []
    if not golden_dir.is_dir():
        return []
    return sorted(
        p
        for p in golden_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(
    task_dir: Path,
    min_run: int = 7,
    candidate_run: int = 8,
    candidate_cw: int = 6,
    flagged_run: int = 9,
    flagged_cw: int = 7,
    max_numeric_ratio: float = 0.4,
    min_clause_ratio: float = 0.6,
):
    """Returns a result dict for one task. Never raises -- a missing config,
    unreadable golden file, or unparseable rubric is reported as a
    skip/error/empty finding, not a crash."""
    task_id = task_dir.name
    criteria, parse_errors, fmt = load_criteria_for_task(task_dir)
    golden_files = find_golden_files(task_dir, fmt)

    result = {
        "task_id": task_id,
        "task_format": fmt,
        "n_criteria": len(criteria),
        "n_golden_files": len(golden_files),
        "parse_errors": parse_errors,
        "flagged_findings": [],
        "candidate_findings": [],
        "errors": [],
    }

    if fmt == "none":
        result["status"] = "skip"
        result["errors"].append(
            "no tests/deliverables*/judge.toml or tests/verifier.json found "
            "-- not a recognized task format"
        )
        result["summary"] = {"n_flagged": 0, "n_candidate": 0}
        return result

    if not criteria:
        result["status"] = "skip"
        if parse_errors:
            result["errors"].append("all criteria failed to parse -- see parse_errors")
        else:
            result["errors"].append(
                "no criteria found in the config file -- nothing to check"
            )
        result["summary"] = {"n_flagged": 0, "n_candidate": 0}
        return result

    if not golden_files:
        result["status"] = "skip"
        result["errors"].append(
            "no golden/solution files found under "
            f"{'solution/files/' if fmt == 'svc_pc' else 'solution/golden_outputs/'}"
            " -- no golden content to compare against (this is a coverage gap, "
            "not a confirmed-safe result)"
        )
        result["summary"] = {"n_flagged": 0, "n_candidate": 0}
        return result

    # Extract golden text per file (once per task, reused for every criterion).
    golden_texts: list[tuple[str, list[str], str | None]] = []
    for gf in golden_files:
        text, err = extract_file_text(gf)
        if err and not text:
            result["errors"].append(
                f"{gf.relative_to(task_dir)}: could not extract text ({err})"
            )
            continue
        if err:
            result["errors"].append(
                f"{gf.relative_to(task_dir)}: partial extraction ({err})"
            )
        golden_texts.append((gf.name, tokenize(text), err))

    if not golden_texts:
        result["status"] = "skip"
        result["errors"].append(
            "no golden files produced extractable text -- nothing to compare against"
        )
        result["summary"] = {"n_flagged": 0, "n_candidate": 0}
        return result

    # Compare each criterion against each golden file.
    for crit in criteria:
        rubric_tokens_with_spans = tokenize_with_spans(crit["description"])
        rubric_tokens = [tok for tok, _s, _e in rubric_tokens_with_spans]
        if len(rubric_tokens) < min_run:
            continue
        # Computed once per criterion (each is a property of the description
        # text alone, not of any one golden file) and reused across every
        # golden file compared against this criterion.
        clause_start = find_expected_clause_token_start(crit["description"])
        quoted_mask = find_quoted_token_mask(crit["description"])
        citation_mask = find_citation_predicate_token_mask(crit["description"])
        rubric_token_spans = [(s, e) for _tok, s, e in rubric_tokens_with_spans]
        for golden_name, golden_tokens, _ in golden_texts:
            if len(golden_tokens) < min_run:
                continue
            runs = find_matching_runs(
                rubric_tokens,
                golden_tokens,
                min_run=min_run,
                rubric_clause_start=clause_start,
                rubric_quoted_mask=quoted_mask,
                rubric_citation_mask=citation_mask,
                rubric_text=crit["description"],
                rubric_token_spans=rubric_token_spans,
            )
            for run in runs:
                tier = classify_run(
                    run,
                    candidate_run=candidate_run,
                    candidate_cw=candidate_cw,
                    flagged_run=flagged_run,
                    flagged_cw=flagged_cw,
                    max_numeric_ratio=max_numeric_ratio,
                    min_clause_ratio=min_clause_ratio,
                )
                if tier is None:
                    continue
                clause_exemption_overridden = (
                    run["clause_ratio"] >= min_clause_ratio
                    and run["has_unquoted_copula"]
                )
                finding = {
                    "criterion": crit["name"],
                    "judge_group": crit["judge_group"],
                    "golden_file": golden_name,
                    "run_length": run["run_length"],
                    "content_words": run["content_words"],
                    "numeric_ratio": run["numeric_ratio"],
                    "clause_ratio": run["clause_ratio"],
                    "has_unquoted_copula": run["has_unquoted_copula"],
                    "has_citation_predicate": run["has_citation_predicate"],
                    "is_source_citation": run["is_source_citation"],
                    "is_schema_enumeration": run["is_schema_enumeration"],
                    "matched_text": run["matched_text"],
                    "confidence": tier,
                    "reason": (
                        f"{run['run_length']} consecutive matching word-tokens "
                        f"({run['content_words']} content words, "
                        f"{run['numeric_ratio']:.0%} numeric, "
                        f"{run['clause_ratio']:.0%} inside the criterion's own "
                        f"Expected: clause"
                        + (
                            ", but containing an unquoted copula (is/are/was/were/...) "
                            "so the Expected: clause exemption does not apply -- see "
                            "the module docstring's THIRD CORRECTION"
                            if clause_exemption_overridden
                            else ""
                        )
                        + f") between rubric criterion {crit['name']!r} and "
                        f"golden file {golden_name!r}"
                    ),
                }
                if tier == "flagged":
                    result["flagged_findings"].append(finding)
                else:
                    result["candidate_findings"].append(finding)

    result["status"] = (
        "flagged"
        if result["flagged_findings"]
        else "candidate" if result["candidate_findings"] else "clean"
    )
    result["summary"] = {
        "n_flagged": len(result["flagged_findings"]),
        "n_candidate": len(result["candidate_findings"]),
    }
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "task_ids",
        nargs="*",
        help="one or more task ids (directory names under --root)",
    )
    ap.add_argument(
        "--all", action="store_true", help="run every task directory found under --root"
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        required=False,
        help="root directory containing one subdirectory per task (REQUIRED -- no "
        "default, this must not silently assume a project-specific path)",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="when using --all, only treat subdirectories starting with this prefix "
        "as tasks",
    )
    ap.add_argument(
        "--min-run",
        type=int,
        default=7,
        help="minimum consecutive matching word-tokens to consider a run at all "
        "(default 7)",
    )
    ap.add_argument(
        "--candidate-run",
        type=int,
        default=8,
        help="run length for a CANDIDATE finding (default 8, must be >= --min-run)",
    )
    ap.add_argument(
        "--candidate-cw",
        type=int,
        default=6,
        help="content-word count for a CANDIDATE finding (default 6)",
    )
    ap.add_argument(
        "--flagged-run",
        type=int,
        default=9,
        help="run length for a FLAGGED finding (default 9)",
    )
    ap.add_argument(
        "--flagged-cw",
        type=int,
        default=7,
        help="content-word count for a FLAGGED finding (default 7)",
    )
    ap.add_argument(
        "--max-numeric-ratio",
        type=float,
        default=0.4,
        help="maximum fraction of pure-numeric tokens in a run for it to be flagged "
        "(default 0.4)",
    )
    ap.add_argument(
        "--min-clause-ratio",
        type=float,
        default=0.6,
        help="minimum fraction of a run's own tokens that must sit inside the "
        "criterion's own labeled 'Expected:' clause for it to be exempted at any "
        "tier (default 0.6; see the module docstring's 2026-09-15 update). The "
        "run must also contain no unquoted copula (is/are/was/were/...) -- see "
        "the docstring's THIRD CORRECTION; not itself a separate tunable flag",
    )
    ap.add_argument(
        "--out", type=Path, default=None, help="write the aggregate JSON report here"
    )
    args = ap.parse_args()

    if args.root is None:
        ap.error(
            "--root is required (point it at the directory containing your task folders)"
        )
    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")
    if not args.root.is_dir():
        sys.stderr.write(f"not a directory: {args.root}\n")
        return 2

    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        return 2

    print(
        "answer_key_rubric_leak_check.py: detects rubric text that near-verbatim-copies "
        "golden answer content (Andrew Ma pattern 6). FLAGGED = strong copying evidence, "
        "CANDIDATE = worth human review. See the module docstring's calibration section "
        "before trusting a 'clean' result or acting on a 'flagged' one.",
        file=sys.stderr,
    )

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
        try:
            r = analyze_task(
                task_dir,
                min_run=args.min_run,
                candidate_run=args.candidate_run,
                candidate_cw=args.candidate_cw,
                flagged_run=args.flagged_run,
                flagged_cw=args.flagged_cw,
                max_numeric_ratio=args.max_numeric_ratio,
                min_clause_ratio=args.min_clause_ratio,
            )
        except Exception as exc:
            r = {
                "task_id": task_dir.name,
                "status": "error",
                "errors": [f"unhandled exception analyzing this task: {exc}"],
                "flagged_findings": [],
                "candidate_findings": [],
                "summary": {"n_flagged": 0, "n_candidate": 0},
            }
        results.append(r)
        s = r.get("summary", {})
        print(
            f"    -> {r['status']}  ({s.get('n_flagged', 0)} flagged, "
            f"{s.get('n_candidate', 0)} candidate, {len(r.get('errors', []))} errors)",
            file=sys.stderr,
        )

    n_flagged = sum(1 for r in results if r["status"] == "flagged")
    n_candidate = sum(1 for r in results if r["status"] == "candidate")
    n_clean = sum(1 for r in results if r["status"] == "clean")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    n_error = sum(1 for r in results if r["status"] == "error")

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "options": {
            "min_run": args.min_run,
            "candidate_run": args.candidate_run,
            "candidate_cw": args.candidate_cw,
            "flagged_run": args.flagged_run,
            "flagged_cw": args.flagged_cw,
            "max_numeric_ratio": args.max_numeric_ratio,
            "min_clause_ratio": args.min_clause_ratio,
        },
        "n_tasks": len(results),
        "n_flagged": n_flagged,
        "n_candidate": n_candidate,
        "n_clean": n_clean,
        "n_skip": n_skip,
        "n_error": n_error,
        "results": results,
    }

    print(
        f"\n{n_clean}/{len(results)} clean, {n_candidate} candidate (human review, not gated), "
        f"{n_flagged} FLAGGED (strong copying evidence), {n_skip} skip (no golden), "
        f"{n_error} errored",
        file=sys.stderr,
    )
    for r in results:
        if r["status"] == "clean":
            continue
        print(f"  {r['task_id']}: {r['status']}")
        for f in r.get("flagged_findings", []):
            print(
                f"      FLAGGED: {f['criterion']} vs {f['golden_file']}: "
                f"run={f['run_length']} cw={f['content_words']} "
                f"num_ratio={f['numeric_ratio']}: {f['matched_text'][:120]}"
            )
        for c in r.get("candidate_findings", []):
            print(
                f"      candidate: {c['criterion']} vs {c['golden_file']}: "
                f"run={c['run_length']} cw={c['content_words']} "
                f"num_ratio={c['numeric_ratio']}: {c['matched_text'][:120]}"
            )
        for e in r.get("errors", []):
            print(f"      ! {e}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {args.out}")

    return 1 if (n_flagged or n_candidate) else 0


if __name__ == "__main__":
    raise SystemExit(main())
