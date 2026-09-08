"""
test_logic.py — verification tests for graph.py, database.py, quiz.py
against the 11 success criteria (Criterion A). Not part of the IA
deliverable itself; used here to verify correctness before handing off.
"""

import os
import tempfile
import unittest

from graph import Graph, Topic
from database import DatabaseManager


NODES_JSON = os.path.join(os.path.dirname(__file__), "nodes.json")


class TestCycleDetection(unittest.TestCase):
    def test_acyclic_graph_from_json(self):
        db = DatabaseManager(":memory:")
        db.initialise_db()
        db.seed_from_json(NODES_JSON)
        g = db.load_graph()
        self.assertFalse(g.detect_cycles())

    def test_simple_cycle_detected(self):
        g = Graph()
        g.add_topic(Topic("A", "A"))
        g.add_topic(Topic("B", "B"))
        g.add_topic(Topic("C", "C"))
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("C", "A")  # cycle
        self.assertTrue(g.detect_cycles())

    def test_no_false_positive_on_diamond(self):
        # A -> B -> D, A -> C -> D  (multiple parents, no cycle)
        g = Graph()
        for tid in "ABCD":
            g.add_topic(Topic(tid, tid))
        g.add_edge("A", "B")
        g.add_edge("A", "C")
        g.add_edge("B", "D")
        g.add_edge("C", "D")
        self.assertFalse(g.detect_cycles())


class TestGatekeeping(unittest.TestCase):
    """
    SC4 (exact wording): Start Quiz is disabled only if a direct
    prerequisite is "Failed" or "Locked". "Untested" prerequisites do
    NOT block starting the quiz.
    """

    def setUp(self):
        self.g = Graph()
        self.g.add_topic(Topic("root", "root", Topic.STATUS_UNTESTED))
        self.g.add_topic(Topic("child", "child", Topic.STATUS_UNTESTED))
        self.g.add_edge("root", "child")

    def test_untested_parent_does_not_block_quiz(self):
        # Root hasn't been attempted yet -> child should still be startable.
        self.assertTrue(self.g.can_start_quiz("child"))

    def test_failed_parent_blocks_quiz(self):
        self.g.nodes["root"].update_status(Topic.STATUS_FAILED)
        self.assertFalse(self.g.can_start_quiz("child"))

    def test_locked_parent_blocks_quiz(self):
        self.g.nodes["root"].update_status(Topic.STATUS_LOCKED)
        self.assertFalse(self.g.can_start_quiz("child"))

    def test_passed_parent_allows_quiz(self):
        self.g.nodes["root"].update_status(Topic.STATUS_PASSED)
        self.assertTrue(self.g.can_start_quiz("child"))

    def test_root_always_startable(self):
        self.assertTrue(self.g.can_start_quiz("root"))

    def test_multiple_parents_any_failed_or_locked_blocks(self):
        self.g.add_topic(Topic("root2", "root2", Topic.STATUS_UNTESTED))
        self.g.add_edge("root2", "child")
        # Both untested -> fine.
        self.assertTrue(self.g.can_start_quiz("child"))
        self.g.nodes["root"].update_status(Topic.STATUS_FAILED)
        self.assertFalse(self.g.can_start_quiz("child"))


class TestKnowledgeGapDiagnosis(unittest.TestCase):
    def setUp(self):
        # A -> B -> C  (linear chain)
        self.g = Graph()
        for tid in "ABC":
            self.g.add_topic(Topic(tid, tid, Topic.STATUS_PASSED))
        self.g.add_edge("A", "B")
        self.g.add_edge("B", "C")

    def test_finds_root_cause_at_earliest_topic(self):
        # Both A and B secretly unlearned; failing C should trace to A,
        # diving through the whole genuinely-unpassed chain in one pass
        # (unaffected by the Passed-parent extension below).
        self.g.nodes["A"].update_status(Topic.STATUS_FAILED)
        self.g.nodes["B"].update_status(Topic.STATUS_FAILED)
        node, depth = self.g.find_gap("C")
        self.assertEqual(node, "A")
        self.assertEqual(depth, 2)

    def test_stops_at_the_nearest_genuinely_broken_parent(self):
        """
        B is genuinely Failed (a real, already-known gap) -- diagnosis
        should stop there and test B first, NOT reach past it into its
        own Passed parent A within the same pass. Escalating to A only
        happens later, via a fresh find_gap call, if B is retested and
        fails again (see gui.App.handle_failure).
        """
        self.g.nodes["B"].update_status(Topic.STATUS_FAILED)
        node, depth = self.g.find_gap("C")
        self.assertEqual(node, "B")
        self.assertEqual(depth, 1)

    def test_all_parents_passed_steps_back_exactly_one_level(self):
        """
        Design extension (see graph.py's find_gap docstring): a Pass is
        a past result, not a permanent guarantee of retention, so when
        every direct parent of the ORIGINALLY failed topic is already
        "Passed", diagnosis still steps back ONE level to re-confirm the
        nearest one -- it does NOT jump straight to the true root in a
        single pass. Escalating further only happens if that re-test
        itself fails, via a separate, later find_gap call.
        """
        node, depth = self.g.find_gap("C")
        self.assertEqual(node, "B")
        self.assertEqual(depth, 1)

    def test_escalates_one_more_level_on_a_fresh_call_if_the_stepped_back_topic_also_has_only_passed_parents(self):
        """
        Simulates the SECOND failure event in a persistently broken
        chain: B (re-tested per the previous case) also fails, and B's
        own parent A is Passed too -- diagnosing fresh from B should
        step back one further level to A, never further than that in
        this one call.
        """
        node, depth = self.g.find_gap("B")
        self.assertEqual(node, "A")
        self.assertEqual(depth, 1)

    def test_diamond_picks_deepest_branch(self):
        # root -> left -> mid -> target
        # root -> right -> target   (right branch shorter)
        g = Graph()
        for tid in ["root", "left", "mid", "right", "target"]:
            g.add_topic(Topic(tid, tid, Topic.STATUS_PASSED))
        g.add_edge("root", "left")
        g.add_edge("left", "mid")
        g.add_edge("mid", "target")
        g.add_edge("root", "right")
        g.add_edge("right", "target")

        g.nodes["root"].update_status(Topic.STATUS_FAILED)
        g.nodes["left"].update_status(Topic.STATUS_FAILED)
        g.nodes["mid"].update_status(Topic.STATUS_FAILED)
        g.nodes["right"].update_status(Topic.STATUS_FAILED)

        node, depth = g.find_gap("target")
        self.assertEqual(node, "root")
        self.assertEqual(depth, 3)

    def test_base_case_topic_with_no_parents_is_its_own_root_cause(self):
        """A topic with no prerequisites at all is trivially its own root cause."""
        g = Graph()
        g.add_topic(Topic("solo", "solo", Topic.STATUS_FAILED))
        node, depth = g.find_gap("solo")
        self.assertEqual(node, "solo")
        self.assertEqual(depth, 0)


class TestRecursiveLockAndUnlock(unittest.TestCase):
    def setUp(self):
        # A -> B -> C  and A -> D
        self.g = Graph()
        for tid in "ABCD":
            self.g.add_topic(Topic(tid, tid, Topic.STATUS_PASSED))
        self.g.add_edge("A", "B")
        self.g.add_edge("B", "C")
        self.g.add_edge("A", "D")

    def test_apply_lock_cascades_to_all_descendants(self):
        locked = self.g.apply_lock("A", set())
        self.assertEqual(locked, {"B", "C", "D"})
        self.assertEqual(self.g.nodes["B"].status, Topic.STATUS_LOCKED)
        self.assertEqual(self.g.nodes["C"].status, Topic.STATUS_LOCKED)
        self.assertEqual(self.g.nodes["D"].status, Topic.STATUS_LOCKED)

    def test_apply_lock_never_overwrites_an_already_failed_descendant(self):
        """
        Regression test: B already Failed (a genuine, specific attempt
        result -- e.g. it is mid-diagnosis, sitting on the recovery
        stack awaiting a re-test) when some unrelated ancestor (A) also
        fails. A's apply_lock must not silently demote B's Failed
        status to the generic Locked -- that would discard the record
        that B was actually attempted, exactly like an already-Locked
        descendant is left alone. B's own children (C) were already
        locked when B itself failed, so C is unaffected either way.
        """
        self.g.nodes["B"].update_status(Topic.STATUS_FAILED)
        self.g.nodes["C"].update_status(Topic.STATUS_LOCKED)  # from B's own earlier failure

        locked = self.g.apply_lock("A", set())

        self.assertEqual(self.g.nodes["B"].status, Topic.STATUS_FAILED,
                          "B's genuine Failed result must not be overwritten to Locked")
        self.assertNotIn("B", locked, "B was already Failed, not newly locked")
        self.assertEqual(self.g.nodes["D"].status, Topic.STATUS_LOCKED,
                          "D has no such conflict and should still be locked normally")
        self.assertIn("D", locked)

    def test_evaluate_unlock_releases_as_soon_as_no_parent_failed_or_locked(self):
        """
        Matches the SC4 gatekeeping rule: a Locked child releases once
        NONE of its parents are Failed/Locked -- an Untested parent is
        enough, it does not need to be Passed.
        """
        g = Graph()
        for tid in ["P1", "P2", "child"]:
            g.add_topic(Topic(tid, tid, Topic.STATUS_UNTESTED))
        g.add_edge("P1", "child")
        g.add_edge("P2", "child")
        g.nodes["child"].update_status(Topic.STATUS_LOCKED)

        # Both parents are merely Untested (never Failed/Locked) -> the
        # lock should already be releasable.
        unlocked = g.evaluate_unlock("P1")
        self.assertEqual(unlocked, ["child"])
        self.assertEqual(g.nodes["child"].status, Topic.STATUS_UNTESTED)

    def test_evaluate_unlock_stays_locked_while_a_parent_is_failed(self):
        g = Graph()
        for tid in ["P1", "P2", "child"]:
            g.add_topic(Topic(tid, tid, Topic.STATUS_UNTESTED))
        g.add_edge("P1", "child")
        g.add_edge("P2", "child")
        g.nodes["child"].update_status(Topic.STATUS_LOCKED)
        g.nodes["P2"].update_status(Topic.STATUS_FAILED)

        unlocked = g.evaluate_unlock("P1")
        self.assertEqual(unlocked, [])  # P2 is Failed -> still blocked
        self.assertEqual(g.nodes["child"].status, Topic.STATUS_LOCKED)

        g.nodes["P2"].update_status(Topic.STATUS_UNTESTED)
        unlocked = g.evaluate_unlock("P2")
        self.assertEqual(unlocked, ["child"])
        self.assertEqual(g.nodes["child"].status, Topic.STATUS_UNTESTED)

    def test_evaluate_unlock_recurses_down_the_whole_locked_subtree(self):
        """
        Regression test for the exact bug reported: A -> B -> C, all
        Locked. Once A itself is no longer Failed/Locked, releasing B
        must cascade to also release C, in one call.
        """
        g = Graph()
        g.add_topic(Topic("A", "A", Topic.STATUS_UNTESTED))
        g.add_topic(Topic("B", "B", Topic.STATUS_LOCKED))
        g.add_topic(Topic("C", "C", Topic.STATUS_LOCKED))
        g.add_edge("A", "B")
        g.add_edge("B", "C")

        unlocked = g.evaluate_unlock("A")
        self.assertEqual(unlocked, ["B", "C"])
        self.assertEqual(g.nodes["B"].status, Topic.STATUS_UNTESTED)
        self.assertEqual(g.nodes["C"].status, Topic.STATUS_UNTESTED)

    def test_evaluate_unlock_never_touches_passed_or_failed_children(self):
        g = Graph()
        g.add_topic(Topic("A", "A", Topic.STATUS_UNTESTED))
        g.add_topic(Topic("passed_child", "passed_child", Topic.STATUS_PASSED))
        g.add_topic(Topic("failed_child", "failed_child", Topic.STATUS_FAILED))
        g.add_edge("A", "passed_child")
        g.add_edge("A", "failed_child")

        unlocked = g.evaluate_unlock("A")
        self.assertEqual(unlocked, [])
        self.assertEqual(g.nodes["passed_child"].status, Topic.STATUS_PASSED)
        self.assertEqual(g.nodes["failed_child"].status, Topic.STATUS_FAILED)


class TestReconcileLocks(unittest.TestCase):
    """
    Regression tests for the exact stale-save-file bug reported: a
    topic can be stuck Locked forever with NOTHING Failed anywhere
    upstream any more, because the specific evaluate_unlock() call that
    would have released it never happened (it depends on the app
    calling it from exactly the right node at exactly the right time).
    reconcile_locks() is the self-healing sweep that fixes this
    regardless of how the graph got into that state, and main.py runs
    it once on every launch.
    """

    def test_releases_a_locked_topic_whose_blocker_already_reset(self):
        # A -> B -> C. B is Locked, but A is Untested (not Failed) --
        # exactly the corrupted state from the bug report, where the
        # original failure was long since reset without a full re-sweep.
        g = Graph()
        g.add_topic(Topic("A", "A", Topic.STATUS_UNTESTED))
        g.add_topic(Topic("B", "B", Topic.STATUS_LOCKED))
        g.add_topic(Topic("C", "C", Topic.STATUS_LOCKED))
        g.add_edge("A", "B")
        g.add_edge("B", "C")

        unlocked = g.reconcile_locks()
        self.assertEqual(set(unlocked), {"B", "C"})
        self.assertEqual(g.nodes["B"].status, Topic.STATUS_UNTESTED)
        self.assertEqual(g.nodes["C"].status, Topic.STATUS_UNTESTED)

    def test_leaves_genuinely_blocked_topics_locked(self):
        g = Graph()
        g.add_topic(Topic("A", "A", Topic.STATUS_FAILED))
        g.add_topic(Topic("B", "B", Topic.STATUS_LOCKED))
        g.add_edge("A", "B")

        unlocked = g.reconcile_locks()
        self.assertEqual(unlocked, [])
        self.assertEqual(g.nodes["B"].status, Topic.STATUS_LOCKED)

    def test_idempotent_on_an_already_consistent_graph(self):
        g = Graph()
        for tid in "AB":
            g.add_topic(Topic(tid, tid, Topic.STATUS_PASSED))
        g.add_edge("A", "B")
        self.assertEqual(g.reconcile_locks(), [])

    def test_multi_layer_stale_lock_fully_clears_in_one_call(self):
        # Mirrors the reported scenario shape: Accel untested, with a
        # whole multi-level subtree (Newton_Laws -> Momentum -> Impulse)
        # still Locked underneath it.
        g = Graph()
        g.add_topic(Topic("Accel", "Accel", Topic.STATUS_UNTESTED))
        g.add_topic(Topic("Newton", "Newton", Topic.STATUS_LOCKED))
        g.add_topic(Topic("Momentum", "Momentum", Topic.STATUS_LOCKED))
        g.add_topic(Topic("Impulse", "Impulse", Topic.STATUS_LOCKED))
        g.add_edge("Accel", "Newton")
        g.add_edge("Newton", "Momentum")
        g.add_edge("Momentum", "Impulse")

        unlocked = g.reconcile_locks()
        self.assertEqual(set(unlocked), {"Newton", "Momentum", "Impulse"})
        for tid in ["Newton", "Momentum", "Impulse"]:
            self.assertEqual(g.nodes[tid].status, Topic.STATUS_UNTESTED)


class TestCascadePassUpward(unittest.TestCase):
    """Design extension: passing a topic auto-passes every ancestor."""

    def test_cascades_through_entire_chain(self):
        # A -> B -> C -> D  (linear chain, all untested)
        g = Graph()
        for tid in "ABCD":
            g.add_topic(Topic(tid, tid, Topic.STATUS_UNTESTED))
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("C", "D")

        newly_passed = g.cascade_pass_upward("D")
        self.assertEqual(set(newly_passed), {"A", "B", "C"})
        for tid in "ABC":
            self.assertEqual(g.nodes[tid].status, Topic.STATUS_PASSED)

    def test_diamond_all_ancestors_passed_once(self):
        # root -> left -> target, root -> right -> target
        g = Graph()
        for tid in ["root", "left", "right", "target"]:
            g.add_topic(Topic(tid, tid, Topic.STATUS_UNTESTED))
        g.add_edge("root", "left")
        g.add_edge("root", "right")
        g.add_edge("left", "target")
        g.add_edge("right", "target")

        newly_passed = g.cascade_pass_upward("target")
        self.assertEqual(set(newly_passed), {"root", "left", "right"})
        self.assertEqual(g.nodes["root"].status, Topic.STATUS_PASSED)

    def test_already_passed_ancestor_not_returned_again(self):
        g = Graph()
        for tid in "AB":
            g.add_topic(Topic(tid, tid, Topic.STATUS_PASSED))
        g.add_edge("A", "B")
        newly_passed = g.cascade_pass_upward("B")
        self.assertEqual(newly_passed, [])  # A already Passed

    def test_failed_ancestor_gets_overwritten_to_passed(self):
        g = Graph()
        g.add_topic(Topic("A", "A", Topic.STATUS_FAILED))
        g.add_topic(Topic("B", "B", Topic.STATUS_UNTESTED))
        g.add_edge("A", "B")
        newly_passed = g.cascade_pass_upward("B")
        self.assertEqual(newly_passed, ["A"])
        self.assertEqual(g.nodes["A"].status, Topic.STATUS_PASSED)


class TestSubgraphExtraction(unittest.TestCase):
    def test_extracts_only_ancestors(self):
        g = Graph()
        for tid in "ABCDE":
            g.add_topic(Topic(tid, tid))
        g.add_edge("A", "B")
        g.add_edge("B", "C")
        g.add_edge("A", "D")
        g.add_edge("D", "E")  # unrelated branch

        nodes, edges = g.get_subgraph("C")
        self.assertEqual(nodes, {"A", "B", "C"})
        self.assertEqual(edges, {("A", "B"), ("B", "C")})


class TestDatabasePersistence(unittest.TestCase):
    def test_progress_persists_across_reconnect(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.db")

            db1 = DatabaseManager(path)
            db1.initialise_db()
            db1.seed_from_json(NODES_JSON)
            db1.save_progress("A.1.Vectors", Topic.STATUS_PASSED)
            db1.close()

            db2 = DatabaseManager(path)
            db2.initialise_db()
            db2.seed_from_json(NODES_JSON)  # should no-op, already seeded
            progress = db2.load_progress()
            self.assertEqual(progress["A.1.Vectors"], Topic.STATUS_PASSED)
            db2.close()

    def test_seed_from_json_creates_correct_edge_count(self):
        db = DatabaseManager(":memory:")
        db.initialise_db()
        db.seed_from_json(NODES_JSON)
        cur = db.connection.execute("SELECT COUNT(*) FROM edges;")
        # sum of len(parent_ids) across all topics in nodes.json = 15
        self.assertEqual(cur.fetchone()[0], 15)

    def test_questions_loaded_with_correct_answer(self):
        db = DatabaseManager(":memory:")
        db.initialise_db()
        db.seed_from_json(NODES_JSON)
        qs = db.get_questions("A.1.Vectors")
        self.assertEqual(len(qs), 2)
        for q in qs:
            self.assertTrue(0 <= q["correct_index"] < len(q["options"]))


class TestQuizManager(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager(":memory:")
        self.db.initialise_db()
        self.db.seed_from_json(NODES_JSON)

    def test_initialize_quiz_loads_all_questions(self):
        from quiz import QuizManager
        qm = QuizManager(self.db)
        qs = qm.initialize_quiz("A.1.Vectors")
        self.assertEqual(len(qs), 2)

    def test_scoring_and_pass_fail(self):
        from quiz import QuizManager
        qm = QuizManager(self.db)
        qm.initialize_quiz("A.1.Vectors")
        # answer both correctly
        for i, q in enumerate(qm.current_questions):
            qm.submit_answer(i, q["correct_index"])
        self.assertEqual(qm.score, 2)
        self.assertTrue(qm.evaluate_attempt())

    def test_fail_on_zero_correct(self):
        from quiz import QuizManager
        qm = QuizManager(self.db)
        qm.initialize_quiz("A.1.Vectors")
        for i, q in enumerate(qm.current_questions):
            wrong = (q["correct_index"] + 1) % len(q["options"])
            qm.submit_answer(i, wrong)
        self.assertFalse(qm.evaluate_attempt())

    def test_recovery_stack_lifo_order(self):
        from quiz import QuizManager
        qm = QuizManager(self.db)
        qm.push_recovery("topic1")
        qm.push_recovery("topic2")
        qm.push_recovery("topic3")
        self.assertEqual(qm.pop_next_recovery_topic(), "topic3")
        self.assertEqual(qm.pop_next_recovery_topic(), "topic2")
        self.assertEqual(qm.pop_next_recovery_topic(), "topic1")
        self.assertTrue(qm.recovery_is_empty())
        self.assertIsNone(qm.pop_next_recovery_topic())


if __name__ == "__main__":
    unittest.main(verbosity=2)
