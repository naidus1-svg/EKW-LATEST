"""The execution-collision rule, in one place, because it was wrong in four.

On 2026-09-11 four scripts each carried their own copy of "which trials count for this
task", and every copy was wrong in a different way. They had all been written when the
only second executions in either bucket were accidental re-fires, and a top-up inverts
the rule. `tools/test_eval_counting.py` pins the behaviour; runbook 10e rule 5 states it
in prose.

Harbor's unit of work is an execution: fire a task, get `execution_N` holding up to k
trials. Strip the execution segment for delivery and trial numbers collide, and three
different situations produce that collision.

  DUPLICATE  an execution scored a full k by itself, so it is a complete independent set
             and any other execution is the accidental re-fire. The EARLIEST full set
             wins: the later one is the accident, and the tracker rows and delivered zips
             already reference the first.
  TOP-UP     no execution reaches k alone, so a later partial was fired to add the trials
             the first never got to. Every scored trial counts, in trial order.
  RETRY      one trial number scored in one execution and died in another. Falls out of
             the two rules above, because only the scored one is ever offered here.

Trial order, never reward order. `tools/google_acceptance_report.py` held
`sorted(rewards, reverse=True)[:K]`, which selects a task's best k rather than its
result. It could not bite while no task had more than k trials in one execution, and
combining executions is what made it reachable.
"""


def choose_executions(scored, k):
    """Decide which (execution, trial) pairs count for one task.

    scored: {execution number: iterable of trial numbers that scored}. Only SCORED
            trials belong in here. A trial with no reward is not a result, and passing
            one in would let a dead trial fill a slot in the delivered k.
    k:      trials the run asked for, per task.

    Returns (take, mode, dropped):
      take     ordered [(execution, trial)], at most k, executions ascending and trials
               ascending within an execution
      mode     'empty'      nothing scored anywhere
               'single'     one execution, nothing to choose between
               'duplicate'  two or more executions each hold a full k, so the later ones
                            are the accidental re-fire
               'supersede'  one execution holds a full k and the others are partial, so
                            the partials are superseded rather than duplicated. This is
                            what a top-up fired at a FULL k produces, and
                            ekw_google_topup.py says so in its own guidance: "A full k
                            was fired, so execution_2 is a complete independent set."
               'topup'      no execution reaches k alone, so they combine
      dropped  execution numbers contributing nothing, ascending

    An execution holding MORE than k scored trials is capped at k in trial order, which
    is runbook 10e rule 3: 19 of 240 SVC cells held more scored runs than their target
    because a retry landed after the original scored.
    """
    if k < 1:
        raise ValueError("k must be at least 1, got %r" % (k,))
    clean = {
        int(ex): sorted(set(int(t) for t in trials)) for ex, trials in scored.items()
    }
    clean = {ex: trials for ex, trials in clean.items() if trials}
    if not clean:
        return [], "empty", sorted(int(e) for e in scored)

    full = sorted(ex for ex, trials in clean.items() if len(trials) >= k)
    if full:
        win = full[0]
        take = [(win, t) for t in clean[win]][:k]
        if len(full) > 1:
            mode = "duplicate"
        elif len(clean) > 1:
            mode = "supersede"
        else:
            mode = "single"
        dropped = sorted(ex for ex in clean if ex != win)
        return take, mode, dropped

    take = []
    for ex in sorted(clean):
        for t in clean[ex]:
            take.append((ex, t))
    take = take[:k]
    used = {ex for ex, _ in take}
    mode = "topup" if len(clean) > 1 else "single"
    return take, mode, sorted(ex for ex in clean if ex not in used)


def describe(mode, take, dropped, k, labels=None):
    """One human-readable line for a log or a tracker cell.

    `labels` maps a key to what it actually is, for callers that pass something other
    than a raw execution number. build_eval_zips passes (revision, execution) SLOTS,
    and without labels this printed "execution_2 scored a full k=4" for a win that was
    really v7 execution_1, which is a note that sends a reader to the wrong revision.
    """
    name = (lambda key: labels[key]) if labels else (lambda key: "execution_%d" % key)
    execs = sorted({ex for ex, _ in take})
    if mode == "empty":
        return "no scored trial anywhere"
    if mode == "single":
        return "%s, %d of k=%d" % (name(execs[0]), len(take), k)
    others = ", ".join(name(e) for e in dropped)
    # These lines land in the tracker's "revisions counted" column, so the verb has to
    # agree with the count: "v6 execution_2 are partial" reached a shared sheet.
    is_are = "is" if len(dropped) == 1 else "are"
    if mode == "duplicate":
        refire = (
            "is an accidental re-fire"
            if len(dropped) == 1
            else "are accidental re-fires"
        )
        return (
            "%s scored a full k=%d on its own so it is the canonical set; %s %s of a "
            "finished task" % (name(execs[0]), k, others, refire)
        )
    if mode == "supersede":
        return (
            "%s scored a full k=%d on its own so it is the canonical set; %s %s partial "
            "and superseded, not counted alongside it"
            % (name(execs[0]), k, others, is_are)
        )
    return "%s combined, %d of k=%d, because none reaches k alone" % (
        " + ".join(name(e) for e in execs),
        len(take),
        k,
    )
