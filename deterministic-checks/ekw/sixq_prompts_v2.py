"""Prompt version 2 for the F1 to F3 AI reader: same questions, tighter reporting rules.

Design change made after the first backtest (work/sixq/bt): version 1 flagged most tasks whether
TFRL had rejected them or approved them. Version 2 asks for at most three rules per question,
each with a concrete other form or reading that the rule text, as written, would reject, and an
explicit instruction to stay silent when the instruction or the rule already settles the point.
Frozen (sha256 recorded) before the version-2 run. Select with environment SIXQ_PROMPT_VERSION=v2.
"""

TIGHT = """

Reporting rules (strict):
- Report at most 3 rules, the 3 you are most certain about, most certain first. Report none if
  none meets the bar.
- Report a rule only if you can state a concrete alternative that a careful expert would really
  produce, and the rule text as written would reject it. If the rule already says it accepts that
  alternative, or the instruction already settles the point, do not report it.
- Do not report a rule just because a different answer is conceivable.
- Do not report a rule that only restates a number the solver must compute from the inputs."""

from sixq_prompts import F1 as _F1, F2 as _F2, F3 as _F3

PROMPTS = {"F1": _F1 + TIGHT, "F2": _F2 + TIGHT, "F3": _F3 + TIGHT}
