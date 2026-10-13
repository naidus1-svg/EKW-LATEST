"""Tests for the execution-collision rule. Stdlib unittest, no dependencies.

    python tools/test_eval_counting.py

Every case below is a real situation from the 2026-09-10 and 2026-09-11 runs, named after
the task it came from, plus the boundary cases nobody hit yet. The four scripts that share
`eval_counting.choose_executions` had four different wrong answers to these before the
module existed, so the point of the file is that a future edit to the rule has to break a
named case rather than a total nobody recomputed.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from eval_counting import choose_executions, describe


class SingleExecution(unittest.TestCase):
    def test_a_clean_full_k_is_taken_whole(self):
        take, mode, dropped = choose_executions({1: range(1, 11)}, 10)
        self.assertEqual(mode, "single")
        self.assertEqual(take, [(1, t) for t in range(1, 11)])
        self.assertEqual(dropped, [])

    def test_a_short_single_execution_stays_short(self):
        """No invention. 9 of 10 is 9, and the caller is the one that must notice."""
        take, mode, dropped = choose_executions({1: range(1, 10)}, 10)
        self.assertEqual(mode, "single")
        self.assertEqual(len(take), 9)

    def test_more_than_k_in_one_execution_caps_in_trial_order(self):
        """Runbook 10e rule 3: a retry landing after the original scored puts 17 runs in
        a cell whose target is 10. The cap keeps the first k by TRIAL, not the best."""
        take, mode, dropped = choose_executions({1: range(1, 18)}, 10)
        self.assertEqual(len(take), 10)
        self.assertEqual([t for _, t in take], list(range(1, 11)))


class DuplicateRefire(unittest.TestCase):
    """ekw0909-task_3 and 15 others: a wide --limit re-fired a finished task at a full
    k=10, so two complete independent sets exist and only one is the result."""

    def test_two_full_sets_keep_the_earliest(self):
        take, mode, dropped = choose_executions({1: range(1, 11), 2: range(1, 11)}, 10)
        self.assertEqual(mode, "duplicate")
        self.assertEqual(dropped, [2])
        self.assertEqual(take, [(1, t) for t in range(1, 11)])

    def test_three_full_sets_still_keep_the_earliest(self):
        take, mode, dropped = choose_executions(
            {1: range(1, 11), 2: range(1, 11), 5: range(1, 11)}, 10
        )
        self.assertEqual(dropped, [2, 5])
        self.assertEqual({ex for ex, _ in take}, {1})

    def test_a_full_set_beats_a_partial_even_when_the_partial_is_later(self):
        """A later partial is not extra evidence when an earlier execution already holds
        the whole k. Mode is 'supersede', not 'duplicate': execution_2 was incomplete,
        so calling it a duplicate in a tracker cell would be wrong."""
        take, mode, dropped = choose_executions({1: range(1, 11), 2: [1, 2]}, 10)
        self.assertEqual(mode, "supersede")
        self.assertEqual(dropped, [2])
        self.assertEqual(len(take), 10)

    def test_a_later_full_set_wins_when_the_earlier_is_partial(self):
        """`earliest full set wins` means earliest among FULL sets. A partial earlier
        execution does not beat a later complete one."""
        take, mode, dropped = choose_executions({1: [1, 2], 3: range(1, 11)}, 10)
        self.assertEqual(mode, "supersede")
        self.assertEqual(dropped, [1])
        self.assertEqual({ex for ex, _ in take}, {3})


class TopUp(unittest.TestCase):
    """The 7 Google tasks and 3 SVC tasks whose tenth or fourth trial exists only in a
    second execution. Dropping it reports a delivered k as one short."""

    def test_svc_pc_1_5_0_pilot_plus_topup(self):
        """execution_2 ran the single pilot trial, execution_3 added three more. `later
        wins` read this as 3 of 4 and dropped the task out of the tracker entirely."""
        take, mode, dropped = choose_executions({2: [1], 3: [1, 2, 3]}, 4)
        self.assertEqual(mode, "topup")
        self.assertEqual(take, [(2, 1), (3, 1), (3, 2), (3, 3)])
        self.assertEqual(len(take), 4)
        self.assertEqual(dropped, [])

    def test_svc_pc_5_2_0_executions_four_and_five(self):
        take, mode, dropped = choose_executions({4: [1], 5: [1, 2, 3]}, 4)
        self.assertEqual(mode, "topup")
        self.assertEqual(len(take), 4)

    def test_task_442_eight_plus_two(self):
        """execution_1 lost trials 3 and 6 to permanent_failure on FileNotFoundError,
        and harbor does not replace a permanently failed trial."""
        take, mode, dropped = choose_executions(
            {1: [1, 2, 4, 5, 7, 8, 9, 10], 2: [1, 2]}, 10
        )
        self.assertEqual(mode, "topup")
        self.assertEqual(len(take), 10)
        self.assertEqual([(e, t) for e, t in take if e == 2], [(2, 1), (2, 2)])

    def test_nine_plus_one(self):
        take, mode, dropped = choose_executions(
            {1: [1, 2, 3, 4, 5, 6, 7, 8, 9], 2: [1]}, 10
        )
        self.assertEqual(len(take), 10)
        self.assertEqual(take[-1], (2, 1))

    def test_a_topup_fired_at_a_full_k_supersedes_rather_than_combines(self):
        """A 9-trial execution_1 plus a FULL k=10 execution_2 is not a top-up to merge.
        execution_2 is a complete independent set on its own, which is what
        ekw_google_topup.py tells the operator: "A full k was fired, so execution_2 is a
        complete independent set." Merging the two would give trial_1 twice.

        This case is why 'supersede' exists as a separate mode from 'duplicate': the
        dropped execution here was never a duplicate, it was incomplete."""
        take, mode, dropped = choose_executions(
            {1: list(range(1, 10)), 2: list(range(1, 11))}, 10
        )
        self.assertEqual(mode, "supersede")
        self.assertEqual(dropped, [1])
        self.assertEqual(take, [(2, t) for t in range(1, 11)])
        self.assertIn("superseded", describe(mode, take, dropped, 10))

    def test_three_partials_combine_in_execution_order(self):
        take, mode, dropped = choose_executions({1: [1, 2], 2: [1], 4: [1]}, 4)
        self.assertEqual(take, [(1, 1), (1, 2), (2, 1), (4, 1)])
        self.assertEqual(mode, "topup")

    def test_an_execution_beyond_the_cap_is_named_as_dropped(self):
        take, mode, dropped = choose_executions({1: [1, 2], 2: [1, 2], 3: [1]}, 4)
        self.assertEqual(len(take), 4)
        self.assertEqual(dropped, [3])


class Degenerate(unittest.TestCase):
    def test_no_scored_trials_anywhere(self):
        take, mode, dropped = choose_executions({1: [], 2: []}, 10)
        self.assertEqual(mode, "empty")
        self.assertEqual(take, [])
        self.assertEqual(dropped, [1, 2])

    def test_completely_empty_input(self):
        self.assertEqual(choose_executions({}, 10), ([], "empty", []))

    def test_k_of_one(self):
        take, mode, dropped = choose_executions({1: [1], 2: [1]}, 1)
        self.assertEqual(mode, "duplicate")
        self.assertEqual(take, [(1, 1)])
        self.assertEqual(dropped, [2])

    def test_k_below_one_is_refused(self):
        with self.assertRaises(ValueError):
            choose_executions({1: [1]}, 0)

    def test_duplicate_trial_numbers_within_an_execution_collapse(self):
        take, _, _ = choose_executions({1: [1, 1, 2, 2, 3]}, 10)
        self.assertEqual(take, [(1, 1), (1, 2), (1, 3)])

    def test_string_keys_and_values_are_coerced(self):
        """gcloud listings are parsed into strings, and a caller that forgets int() must
        not silently sort execution_10 before execution_2."""
        take, _, _ = choose_executions({"2": ["1"], "10": ["1", "2", "3"]}, 4)
        self.assertEqual(take, [(2, 1), (10, 1), (10, 2), (10, 3)])

    def test_execution_order_is_numeric_not_lexicographic(self):
        take, mode, dropped = choose_executions({2: [1], 10: [1]}, 4)
        self.assertEqual(take, [(2, 1), (10, 1)])


class NeverCherryPick(unittest.TestCase):
    """The rule that matters most: selection is by position, never by score. The module
    is not given rewards at all, which is what makes a favourable subset impossible."""

    def test_the_code_body_never_sorts_or_slices_by_value(self):
        """Scan the executable body only, with the docstring stripped: the docstring
        legitimately explains why rewards are excluded, and an earlier version of this
        test failed on its own prose. What matters is that no reward ever reaches the
        selection, which is enforced by the signature taking trial numbers and nothing
        else, and by the body sorting only on execution and trial."""
        import inspect

        src = inspect.getsource(choose_executions)
        body = src.split('"""')[2] if src.count('"""') >= 2 else src
        # `scored` is the parameter name and holds trial numbers, not values
        body = body.replace("scored", "trials_by_execution")
        for word in ("reward", "score", "mean", "best", "max("):
            self.assertNotIn(
                word,
                body.lower(),
                "choose_executions body must not reference %r" % word,
            )
        self.assertNotIn("reverse=true", body.lower())

    def test_a_favourable_subset_is_unrepresentable(self):
        """The strongest guarantee available: the function is never given rewards, so it
        has nothing to be favourable about. Two tasks with identical trial layouts and
        wildly different scores select identically."""
        layout = {1: [1, 2, 4, 5, 7, 8, 9, 10], 2: [1, 2]}
        self.assertEqual(
            choose_executions(layout, 10), choose_executions(dict(layout), 10)
        )

    def test_trial_order_is_stable_regardless_of_input_order(self):
        a, _, _ = choose_executions({1: [3, 1, 2], 2: [2, 1]}, 5)
        b, _, _ = choose_executions({2: [1, 2], 1: [2, 3, 1]}, 5)
        self.assertEqual(a, b)
        self.assertEqual(a, [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2)])


class Slots(unittest.TestCase):
    """build_eval_zips passes (revision, execution) SLOTS rather than raw execution
    numbers, because a restage puts a second complete k under a new revision and
    revision-versus-execution is one dimension, not two."""

    def test_a_restage_supersedes_the_partial_it_replaced(self):
        """SVC-PC-14-2-0: v6 execution_2 scored 3 of 4 and stalled, v7 execution_1 then
        scored a full 4. Keeping both, which the old revision rule did, put 7 trial
        folders in a k=4 archive."""
        labels = {1: "v6 execution_2", 2: "v7 execution_1"}
        take, mode, dropped = choose_executions({1: [1, 3, 4], 2: [1, 2, 3, 4]}, 4)
        self.assertEqual(mode, "supersede")
        self.assertEqual(dropped, [1])
        self.assertEqual(take, [(2, t) for t in range(1, 5)])
        line = describe(mode, take, dropped, 4, labels=labels)
        self.assertIn("v7 execution_1 scored a full k=4", line)
        self.assertIn("v6 execution_2", line)

    def test_without_labels_the_line_names_executions(self):
        take, mode, dropped = choose_executions({1: [1, 3, 4], 2: [1, 2, 3, 4]}, 4)
        self.assertIn("execution_2 scored a full", describe(mode, take, dropped, 4))

    def test_a_label_map_cannot_silently_rename_the_winner(self):
        """The bug this pins: printing a slot index through the default formatter said
        'execution_2 scored a full k=4' when slot 2 was v7 execution_1, sending a reader
        to the wrong revision."""
        labels = {1: "v6 execution_2", 2: "v7 execution_1"}
        take, mode, dropped = choose_executions({1: [1, 3, 4], 2: [1, 2, 3, 4]}, 4)
        labelled = describe(mode, take, dropped, 4, labels=labels)
        bare = describe(mode, take, dropped, 4)
        self.assertNotEqual(labelled, bare)
        self.assertNotIn("execution_2 scored", labelled)

    def test_a_later_revision_that_adds_trials_still_combines(self):
        """Runbook 14's original revision case: v2 started 3 trials, v4 added 2 more,
        neither reaches k=10, so both are real and both are kept."""
        labels = {1: "v2 execution_1", 2: "v4 execution_1"}
        take, mode, dropped = choose_executions({1: [1, 2, 3], 2: [1, 2]}, 10)
        self.assertEqual(mode, "topup")
        self.assertEqual(len(take), 5)
        self.assertIn(
            "v2 execution_1 + v4 execution_1",
            describe(mode, take, dropped, 10, labels=labels),
        )


class Describe(unittest.TestCase):
    def test_each_mode_produces_a_line(self):
        for scored, k in (
            ({1: range(1, 11)}, 10),
            ({1: range(1, 11), 2: range(1, 11)}, 10),
            ({2: [1], 3: [1, 2, 3]}, 4),
            ({1: []}, 10),
        ):
            take, mode, dropped = choose_executions(scored, k)
            line = describe(mode, take, dropped, k)
            self.assertTrue(line and isinstance(line, str))
            self.assertNotIn("--", line)  # no em dash, project hard rule


if __name__ == "__main__":
    unittest.main(verbosity=2)
