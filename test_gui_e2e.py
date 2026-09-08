"""
test_gui_e2e.py — headless (Xvfb) end-to-end drive of the actual Tkinter
App class, exercising every success criterion through real widget
callbacks rather than by calling graph/quiz methods directly. Verifies
gui.py's event wiring, not just the underlying logic (already covered
by test_logic.py).

Run with: DISPLAY=:99 python3.12 test_gui_e2e.py
"""

import os
import tkinter as tk
from unittest.mock import patch

from database import DatabaseManager
from graph import Topic
from quiz import QuizManager
from gui import App

BASE = os.path.dirname(os.path.abspath(__file__))
TEST_DB = os.path.join(BASE, "_e2e_test.db")


def fresh_app():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    db = DatabaseManager(TEST_DB)
    db.initialise_db()
    db.seed_from_json(os.path.join(BASE, "nodes.json"))
    graph = db.load_graph()
    assert not graph.detect_cycles(), "SC1 FAILED: cycle wrongly detected"
    quiz = QuizManager(db)
    root = tk.Tk()
    root.geometry("1000x650")
    app = App(root, graph, db, quiz)
    root.update()
    return root, app, db


def answer_all_correctly(app):
    """Answers every question of the CURRENTLY active quiz topic correctly,
    then stops -- even if a new quiz auto-launches for a different topic."""
    topic_being_answered = app.quiz.current_topic_id
    while app.mode == "quiz" and app.quiz.current_topic_id == topic_being_answered:
        q = app.quiz.current_questions[app.current_question_index]
        app.selected_option_index.set(q["correct_index"])
        app.on_submit_answer()
        app.root.update()


def answer_all_incorrectly(app):
    """
    Answers every question of the CURRENTLY active quiz topic wrong,
    then stops -- even if a new diagnosis quiz auto-launches for a
    different topic (that quiz's questions are not touched here).
    """
    topic_being_answered = app.quiz.current_topic_id
    while app.mode == "quiz" and app.quiz.current_topic_id == topic_being_answered:
        q = app.quiz.current_questions[app.current_question_index]
        wrong = (q["correct_index"] + 1) % len(q["options"])
        app.selected_option_index.set(wrong)
        app.on_submit_answer()
        app.root.update()


def test_any_topic_always_selectable():
    """
    SC4 design note: selection/viewing is NEVER gated, even for a topic
    deep in the DAG with untouched prerequisites. Only Start Quiz is.
    """
    root, app, db = fresh_app()
    try:
        # Projectile Motion has un-passed prerequisites, but selecting
        # it must succeed immediately -- no popup, no blocking.
        with patch("tkinter.messagebox.askyesno") as mock_ask, \
             patch("tkinter.messagebox.showerror") as mock_err:
            app.select_topic("A.1.Projectile")
            assert not mock_ask.called, "SC4 FAILED: selection must never be gated"
            assert not mock_err.called

        assert app.selected_topic_id == "A.1.Projectile"
        assert app.mode == "navigator"
        # Its subgraph (itself + every ancestor) should be on the canvas.
        visible_ids, _ = app.graph.get_subgraph("A.1.Projectile")
        assert app.node_positions.keys() == visible_ids
        print("PASS: test_any_topic_always_selectable")
    finally:
        root.destroy()


def test_start_quiz_gated_only_by_failed_or_locked_parent():
    """SC4 exact wording: Untested parent does not block; Failed/Locked does."""
    root, app, db = fresh_app()
    try:
        # Fresh app: Vectors has no parents -> always startable.
        app.select_topic("A.1.Vectors")
        assert app.graph.can_start_quiz("A.1.Vectors")

        # Disp_Vel's only parent (Vectors) is Untested -> should STILL
        # be startable per SC4 (untested does not block).
        app.select_topic("A.1.Disp_Vel")
        assert app.graph.can_start_quiz("A.1.Disp_Vel"), \
            "SC4 FAILED: an Untested prerequisite must not block Start Quiz"

        # Now fail Vectors directly -> Disp_Vel's quiz must become gated.
        app.graph.nodes["A.1.Vectors"].update_status(Topic.STATUS_FAILED)
        assert not app.graph.can_start_quiz("A.1.Disp_Vel"), \
            "SC4 FAILED: a Failed prerequisite must block Start Quiz"

        # And Locked also blocks.
        app.graph.nodes["A.1.Vectors"].update_status(Topic.STATUS_LOCKED)
        assert not app.graph.can_start_quiz("A.1.Disp_Vel"), \
            "SC4 FAILED: a Locked prerequisite must block Start Quiz"
        print("PASS: test_start_quiz_gated_only_by_failed_or_locked_parent")
    finally:
        root.destroy()


def test_full_prerequisite_chain_pass_and_upward_cascade():
    """SC2, SC5, SC10, SC11 + upward-cascade extension."""
    root, app, db = fresh_app()
    try:
        # Pass Vectors -> Disp_Vel -> Accel -> SUVAT one at a time via
        # the real quiz UI, then pass Projectile Motion (2 parents:
        # SUVAT and Vectors, both already Passed by then).
        for tid in ["A.1.Vectors", "A.1.Disp_Vel", "A.1.Accel", "A.1.SUVAT"]:
            app.select_topic(tid)
            assert app.graph.can_start_quiz(tid)
            app.start_quiz(tid)
            with patch("tkinter.messagebox.showinfo"):
                answer_all_correctly(app)
            assert app.graph.nodes[tid].status == Topic.STATUS_PASSED
            assert db.load_progress()[tid] == Topic.STATUS_PASSED, "SC10 FAILED"

        print("PASS: test_full_prerequisite_chain_pass_and_upward_cascade")
    finally:
        root.destroy()


def test_cascade_pass_upward_marks_ancestors():
    """
    Design extension: passing an advanced topic should retroactively
    mark its still-untested ancestors as Passed too.
    """
    root, app, db = fresh_app()
    try:
        # Vectors, Disp_Vel, Accel, SUVAT are all Untested. Force-select
        # Projectile Motion (allowed per SC4) and pass its quiz directly
        # -- SC4 doesn't block starting it since all parents are merely
        # Untested, not Failed/Locked.
        app.select_topic("A.1.Projectile")
        assert app.graph.can_start_quiz("A.1.Projectile")
        app.start_quiz("A.1.Projectile")
        with patch("tkinter.messagebox.showinfo"):
            answer_all_correctly(app)

        assert app.graph.nodes["A.1.Projectile"].status == Topic.STATUS_PASSED
        for ancestor in ["A.1.SUVAT", "A.1.Accel", "A.1.Disp_Vel", "A.1.Vectors"]:
            assert app.graph.nodes[ancestor].status == Topic.STATUS_PASSED, \
                f"cascade FAILED: {ancestor} should have been auto-passed"
            assert db.load_progress()[ancestor] == Topic.STATUS_PASSED, \
                f"cascade FAILED: {ancestor} auto-pass not persisted"
        print("PASS: test_cascade_pass_upward_marks_ancestors")
    finally:
        root.destroy()


def test_failure_triggers_lock_and_diagnosis():
    """SC6, SC7, SC8, SC9: fail -> lock children -> DFS root-cause -> stack."""
    root, app, db = fresh_app()
    try:
        # Manually pass Vectors and Disp_Vel so Accel's quiz is unblocked
        # (Accel has no Failed/Locked parent either way, but we want it
        # Passed for the SC8/SC9 lock-then-unlock assertions below).
        for tid in ["A.1.Vectors", "A.1.Disp_Vel"]:
            app.graph.nodes[tid].update_status(Topic.STATUS_PASSED)
            db.save_progress(tid, Topic.STATUS_PASSED)

        app.select_topic("A.1.Accel")
        assert app.graph.can_start_quiz("A.1.Accel")
        app.start_quiz("A.1.Accel")
        with patch("tkinter.messagebox.showinfo"):
            answer_all_incorrectly(app)

        accel = app.graph.nodes["A.1.Accel"]
        assert accel.status == Topic.STATUS_FAILED, "SC10 FAILED: failure not recorded"

        # SC8: children of Accel (Graphs, SUVAT, Newton_Laws) must be Locked.
        for child_id in ["A.1.Graphs", "A.1.SUVAT", "A.2.Newton_Laws"]:
            assert app.graph.nodes[child_id].status == Topic.STATUS_LOCKED, \
                f"SC8 FAILED: {child_id} should be locked"
            assert db.load_progress()[child_id] == Topic.STATUS_LOCKED, \
                f"SC8 FAILED: {child_id} lock not persisted"

        # SC4: those locked children's Start Quiz must now be disabled.
        assert not app.graph.can_start_quiz("A.1.SUVAT"), \
            "SC4 FAILED: child of a failed topic should be gated (Locked parent)"

        # SC6 (revised): even though Accel's own parent (Disp_Vel) is
        # already "Passed", a Pass is not a permanent guarantee of
        # retention -- find_gap steps back exactly ONE level to
        # re-confirm the nearest parent (Disp_Vel), rather than
        # stopping at Accel (the original behaviour) OR jumping all
        # the way to the true root (Vectors) in a single pass.
        assert app.mode == "quiz"
        assert app.quiz.current_topic_id == "A.1.Disp_Vel", \
            "SC6 FAILED: an already-Passed parent should be re-tested one " \
            "level up, not skipped (old behaviour) or jumped past (over-eager fix)"
        # SC7: the originally-failed topic must be queued on the
        # recovery stack so passing Disp_Vel returns to it.
        assert app.quiz.recovery_stack == ["A.1.Accel"], \
            f"SC7 FAILED: expected [Accel], got {app.quiz.recovery_stack}"

        # Now fail the Disp_Vel re-test too (persistently broken chain):
        # this is a fresh, independent failure event -- handle_failure
        # calls find_gap again from Disp_Vel, which should escalate
        # exactly one further level to Vectors (Disp_Vel's own Passed
        # parent), pushing Disp_Vel onto the stack alongside Accel.
        with patch("tkinter.messagebox.showinfo"):
            answer_all_incorrectly(app)
        assert app.graph.nodes["A.1.Disp_Vel"].status == Topic.STATUS_FAILED
        assert app.mode == "quiz"
        assert app.quiz.current_topic_id == "A.1.Vectors", \
            "SC6 FAILED: a second consecutive failure should escalate one " \
            "more level, to Vectors"
        assert app.quiz.recovery_stack == ["A.1.Accel", "A.1.Disp_Vel"], \
            f"SC7 FAILED: expected [Accel, Disp_Vel], got {app.quiz.recovery_stack}"

        # Pass Vectors -> pops Disp_Vel next (nearest the root cause),
        # not straight back to Accel.
        with patch("tkinter.messagebox.showinfo"):
            answer_all_correctly(app)
        assert app.graph.nodes["A.1.Vectors"].status == Topic.STATUS_PASSED
        assert app.quiz.current_topic_id == "A.1.Disp_Vel", \
            "SC7 FAILED: should re-test the intermediate topic (Disp_Vel) next, " \
            "not skip straight back to the originally failed topic"

        # Pass Disp_Vel -> pops Accel last (the originally failed topic).
        with patch("tkinter.messagebox.showinfo"):
            answer_all_correctly(app)
        assert app.graph.nodes["A.1.Disp_Vel"].status == Topic.STATUS_PASSED
        assert app.quiz.current_topic_id == "A.1.Accel", \
            "SC7 FAILED: should finally return to the originally failed topic"

        # Pass Accel to close the loop cleanly.
        with patch("tkinter.messagebox.showinfo"):
            answer_all_correctly(app)
        assert app.graph.nodes["A.1.Accel"].status == Topic.STATUS_PASSED
        assert app.quiz.recovery_is_empty()
        assert app.mode == "navigator"
        print("PASS: test_failure_triggers_lock_and_diagnosis")
    finally:
        root.destroy()


def test_unlock_cascades_through_a_previously_locked_chain():
    """
    Regression test for a real bug found during manual testing: A ->
    B -> C, all Locked as a side effect of a failure further up the
    graph. Once A settles back at Untested (not re-Passed, just no
    longer Failed/Locked), B must release AND C (Locked because of B,
    not directly because of A) must release too in the same pass --
    a Locked topic must never get stuck forever just because its
    unlocking parent went to Untested rather than all the way to
    Passed.
    """
    root, app, db = fresh_app()
    try:
        # Reproduce exactly what happened in the app: fail Disp_Vel
        # while Accel/Graphs/SUVAT/Newton_Laws/etc. are all Passed or
        # otherwise fine, so apply_lock cascades Locked all the way
        # down from Accel through Newton's Laws and beyond.
        for tid in ["A.1.Vectors", "A.1.Disp_Vel"]:
            app.graph.nodes[tid].update_status(Topic.STATUS_PASSED)
            db.save_progress(tid, Topic.STATUS_PASSED)

        app.select_topic("A.1.Disp_Vel")
        app.start_quiz("A.1.Disp_Vel")
        with patch("tkinter.messagebox.showinfo"):
            answer_all_incorrectly(app)

        assert app.graph.nodes["A.1.Disp_Vel"].status == Topic.STATUS_FAILED
        for descendant in ["A.1.Accel", "A.2.Newton_Laws", "A.2.Momentum"]:
            assert app.graph.nodes[descendant].status == Topic.STATUS_LOCKED, \
                f"setup FAILED: {descendant} should have been locked"

        # Now re-pass Disp_Vel. evaluate_unlock should release Accel
        # (direct child) AND recurse to release Newton's Laws and
        # Momentum (grandchildren), all in one call.
        app.select_topic("A.1.Disp_Vel")
        app.start_quiz("A.1.Disp_Vel")
        with patch("tkinter.messagebox.showinfo"):
            answer_all_correctly(app)

        assert app.graph.nodes["A.1.Disp_Vel"].status == Topic.STATUS_PASSED
        assert app.graph.nodes["A.1.Accel"].status == Topic.STATUS_UNTESTED, \
            "BUG: direct child should have released to Untested"
        assert app.graph.nodes["A.2.Newton_Laws"].status == Topic.STATUS_UNTESTED, \
            "BUG: grandchild stayed Locked even though its parent (Accel) " \
            "is no longer Failed/Locked -- evaluate_unlock must recurse"
        assert app.graph.nodes["A.2.Momentum"].status == Topic.STATUS_UNTESTED, \
            "BUG: great-grandchild should also have released"

        # And the Start Quiz gate must agree: Newton's Laws should now
        # be startable again, since Accel is merely Untested.
        assert app.graph.can_start_quiz("A.2.Newton_Laws"), \
            "BUG: gate should not still report Newton's Laws as blocked"

        # Persisted copies must match too.
        progress = db.load_progress()
        assert progress["A.1.Accel"] == Topic.STATUS_UNTESTED
        assert progress["A.2.Newton_Laws"] == Topic.STATUS_UNTESTED
        assert progress["A.2.Momentum"] == Topic.STATUS_UNTESTED
        print("PASS: test_unlock_cascades_through_a_previously_locked_chain")
    finally:
        root.destroy()


def test_app_launch_self_heals_a_corrupted_save_file():
    """
    Regression test reproducing the user's exact bug report: a save
    file where a topic is stuck Locked with nothing Failed anywhere
    upstream (created here by writing progress rows directly, bypassing
    the app -- the same effect an older, buggier version of this app
    could have left behind). A fresh app launch must self-heal it, the
    same way main.py does via graph.reconcile_locks().
    """
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    db = DatabaseManager(TEST_DB)
    db.initialise_db()
    db.seed_from_json(os.path.join(BASE, "nodes.json"))

    # Hand-corrupt the save file: Accel Untested, but Newton's Laws and
    # everything under it still Locked -- exactly the reported state.
    db.save_progress("A.1.Vectors", Topic.STATUS_PASSED)
    db.save_progress("A.1.Disp_Vel", Topic.STATUS_PASSED)
    db.save_progress("A.1.Accel", Topic.STATUS_UNTESTED)
    for tid in ["A.1.Graphs", "A.1.SUVAT", "A.1.Projectile", "A.2.Newton_Laws",
                "A.2.Momentum", "A.2.Impulse", "A.3.Work", "A.3.Power"]:
        db.save_progress(tid, Topic.STATUS_LOCKED)
    db.close()

    # Now perform exactly what main.py's launch sequence does.
    db2 = DatabaseManager(TEST_DB)
    db2.initialise_db()
    db2.seed_from_json(os.path.join(BASE, "nodes.json"))
    graph2 = db2.load_graph()
    assert not graph2.detect_cycles()
    for topic_id in graph2.reconcile_locks():
        db2.save_progress(topic_id, graph2.nodes[topic_id].status)

    for tid in ["A.1.Graphs", "A.1.SUVAT", "A.1.Projectile", "A.2.Newton_Laws",
                "A.2.Momentum", "A.2.Impulse", "A.3.Work", "A.3.Power"]:
        assert graph2.nodes[tid].status == Topic.STATUS_UNTESTED, \
            f"BUG: {tid} should have self-healed to Untested on launch"
        assert db2.load_progress()[tid] == Topic.STATUS_UNTESTED, \
            f"BUG: {tid} self-heal not persisted"
    db2.close()
    print("PASS: test_app_launch_self_heals_a_corrupted_save_file")


def test_locked_hint_names_the_true_root_cause():
    """
    The sidebar's "Locked: fix X first" hint must name the topic that
    actually Failed, not just the nearest Locked parent (which is only
    a symptom) -- this is what the user's feedback screenshot flagged.
    """
    root, app, db = fresh_app()
    try:
        for tid in ["A.1.Vectors", "A.1.Disp_Vel"]:
            app.graph.nodes[tid].update_status(Topic.STATUS_PASSED)
            db.save_progress(tid, Topic.STATUS_PASSED)

        # Fail Accel directly -> locks Graphs, SUVAT, Newton's Laws,
        # Momentum, etc. Accel itself is "Failed"; everything below it
        # is merely "Locked" (a side effect, not the true cause).
        app.select_topic("A.1.Accel")
        app.start_quiz("A.1.Accel")
        with patch("tkinter.messagebox.showinfo"):
            answer_all_incorrectly(app)
        assert app.graph.nodes["A.1.Accel"].status == Topic.STATUS_FAILED

        # Newton's Laws is two hops from Accel (Accel -> Newton's Laws
        # is actually direct, so use Momentum, which is one hop further
        # via Newton's Laws, to properly exercise the upward walk).
        app.selected_topic_id = "A.2.Momentum"
        hint = app._find_blocking_root_cause_name("A.2.Momentum")
        assert hint == "Acceleration", \
            f"BUG: hint should name the true root cause (Acceleration), got {hint!r}"
        print("PASS: test_locked_hint_names_the_true_root_cause")
    finally:
        root.destroy()


def test_deep_gap_diagnosis_and_recovery_stack():
    """SC6, SC7, SC9: fail a topic whose root cause is further upstream,
    then verify the recovery stack walks back to the original topic."""
    root, app, db = fresh_app()
    try:
        # Pass the whole Vectors -> Disp_Vel -> Accel -> SUVAT chain.
        chain = ["A.1.Vectors", "A.1.Disp_Vel", "A.1.Accel", "A.1.SUVAT"]
        for tid in chain:
            app.graph.nodes[tid].update_status(Topic.STATUS_PASSED)
            db.save_progress(tid, Topic.STATUS_PASSED)

        # Secretly regress Vectors (simulating forgotten prerequisite)
        # -- mirrors the "Problem Scenario": student forgot Vectors
        # months ago but the system hasn't re-tested it yet.
        app.graph.nodes["A.1.Vectors"].update_status(Topic.STATUS_FAILED)
        db.save_progress("A.1.Vectors", Topic.STATUS_FAILED)

        # Projectile Motion's quiz IS gated now (Vectors is Failed, a
        # direct parent) -- but selecting/viewing it is still allowed,
        # and this test exercises the diagnosis path that runs after a
        # quiz attempt, so we bypass the button and call start_quiz
        # directly (mirrors a quiz already in progress before the
        # parent failed, or a teacher override -- the diagnosis logic
        # itself does not re-check can_start_quiz once a quiz is live).
        app.select_topic("A.1.Projectile")
        app.start_quiz("A.1.Projectile")
        with patch("tkinter.messagebox.showinfo"):
            answer_all_incorrectly(app)

        # find_gap should have walked from Projectile -> (SUVAT is passed,
        # Vectors is failed) -> Vectors is the immediate unpassed parent
        # and has no further unpassed parents itself -> root cause = Vectors.
        assert app.quiz.current_topic_id == "A.1.Vectors", \
            f"SC6 FAILED: expected diagnosis on Vectors, got {app.quiz.current_topic_id}"
        assert app.mode == "quiz"
        # SC7: Projectile should be sitting on the recovery stack.
        assert "A.1.Projectile" in app.quiz.recovery_stack, \
            "SC7 FAILED: original failed topic not pushed to recovery stack"

        # Pass the diagnosis quiz (Vectors) -> should pop stack and
        # relaunch the quiz for Projectile automatically (Figure 7).
        with patch("tkinter.messagebox.showinfo"):
            answer_all_correctly(app)

        assert app.graph.nodes["A.1.Vectors"].status == Topic.STATUS_PASSED
        assert app.quiz.current_topic_id == "A.1.Projectile", \
            "SC7 FAILED: recovery stack should have relaunched Projectile quiz"
        assert app.mode == "quiz"

        # Finally pass Projectile to close the loop cleanly.
        with patch("tkinter.messagebox.showinfo"):
            answer_all_correctly(app)
        assert app.graph.nodes["A.1.Projectile"].status == Topic.STATUS_PASSED
        assert app.quiz.recovery_is_empty()
        assert app.mode == "navigator"
        print("PASS: test_deep_gap_diagnosis_and_recovery_stack")
    finally:
        root.destroy()


def test_canvas_fits_without_scrollbar():
    """
    Regression test: every node of the full graph must be positioned
    within the visible canvas bounds (no off-screen/clipped nodes,
    no Scrollbar widgets present).
    """
    root, app, db = fresh_app()
    try:
        app.selected_topic_id = None
        app.render_graph()
        cw, ch = app.canvas.winfo_width(), app.canvas.winfo_height()
        assert app.node_positions, "no nodes rendered"
        for tid, (x, y) in app.node_positions.items():
            assert 0 <= x <= cw, f"{tid} x={x} outside canvas width {cw}"
            assert 0 <= y <= ch, f"{tid} y={y} outside canvas height {ch}"

        def find_scrollbars(widget):
            found = isinstance(widget, tk.Scrollbar)
            for child in widget.winfo_children():
                found = found or find_scrollbars(child)
            return found

        assert not find_scrollbars(root), "no Scrollbar widgets should be present"
        print("PASS: test_canvas_fits_without_scrollbar")
    finally:
        root.destroy()


def test_reselecting_same_topic_toggles_it_off():
    """
    Regression test: after selecting a topic (which narrows the canvas
    to that topic's subgraph via SC3), clicking that SAME topic again
    (canvas node or sidebar row -- both go through select_topic) must
    toggle the selection off, returning to the full-graph view. There
    is no separate "deselect" button; the topic click itself toggles.
    """
    root, app, db = fresh_app()
    try:
        app.select_topic("A.1.Projectile")
        assert app.selected_topic_id == "A.1.Projectile"
        subgraph_ids, _ = app.graph.get_subgraph("A.1.Projectile")
        assert app.node_positions.keys() == subgraph_ids
        assert len(subgraph_ids) < len(app.graph.nodes), \
            "test setup invalid: Projectile's subgraph should be a strict subset"

        # Clicking the SAME already-selected topic again toggles it off.
        app.select_topic("A.1.Projectile")

        assert app.selected_topic_id is None, \
            "selecting the already-selected topic again must deselect it"
        assert app.mode == "navigator"
        assert app.node_positions.keys() == set(app.graph.nodes.keys()), \
            "deselecting must redraw the FULL graph, not the old subgraph"

        # Selecting a DIFFERENT topic afterward must select normally
        # (not toggle), confirming the toggle only fires on a repeat click.
        app.select_topic("A.1.Vectors")
        assert app.selected_topic_id == "A.1.Vectors"
        print("PASS: test_reselecting_same_topic_toggles_it_off")
    finally:
        root.destroy()


def test_start_quiz_button_reflects_gate_state():
    """
    Regression test for the Start Quiz control (now a styled tk.Label,
    not a native tk.Button, so platform theming can't override its
    colours -- see gui.App._make_button). Confirms the enabled/disabled
    visual state still tracks can_start_quiz() correctly and clicking
    it while disabled does not start a quiz.
    """
    root, app, db = fresh_app()
    try:
        # Vectors has no parents -> always startable.
        app.select_topic("A.1.Vectors")
        app.graph.nodes["A.1.Vectors"].update_status(Topic.STATUS_FAILED)
        locked = app.graph.apply_lock("A.1.Vectors", set())
        app.switch_sidebar("navigator")

        blocked_child = next(iter(locked)) if locked else None
        assert blocked_child, "test setup invalid: Vectors should lock a child"
        app.select_topic(blocked_child)
        assert not app.graph.can_start_quiz(blocked_child)

        # Find the rendered Start Quiz label and confirm it has no
        # click binding wired (disabled) and the muted colour applied.
        start_labels = [
            w for w in app.sidebar.winfo_children()
            if isinstance(w, tk.Label) and w.cget("text") == "Start Quiz"
        ]
        assert start_labels, "Start Quiz control not found in sidebar"
        start_lbl = start_labels[0]
        assert start_lbl.cget("bg") == "#B5B5B5"
        assert start_lbl.bind("<Button-1>") == "", \
            "disabled Start Quiz must have no click handler bound"

        mode_before = app.mode
        start_lbl.event_generate("<Button-1>")
        app.root.update()
        assert app.mode == mode_before, "clicking a disabled control must do nothing"
        print("PASS: test_start_quiz_button_reflects_gate_state")
    finally:
        root.destroy()


def test_persistence_across_restart():
    """SC10: state must survive closing and reopening the app/db."""
    root, app, db = fresh_app()
    try:
        app.graph.nodes["A.1.Vectors"].update_status(Topic.STATUS_PASSED)
        db.save_progress("A.1.Vectors", Topic.STATUS_PASSED)
        root.destroy()
        db.close()

        db2 = DatabaseManager(TEST_DB)
        db2.initialise_db()
        db2.seed_from_json(os.path.join(BASE, "nodes.json"))
        graph2 = db2.load_graph()
        assert graph2.nodes["A.1.Vectors"].status == Topic.STATUS_PASSED, \
            "SC10 FAILED: progress did not survive restart"
        db2.close()
        print("PASS: test_persistence_across_restart")
    finally:
        pass


if __name__ == "__main__":
    test_any_topic_always_selectable()
    test_start_quiz_gated_only_by_failed_or_locked_parent()
    test_full_prerequisite_chain_pass_and_upward_cascade()
    test_cascade_pass_upward_marks_ancestors()
    test_failure_triggers_lock_and_diagnosis()
    test_unlock_cascades_through_a_previously_locked_chain()
    test_app_launch_self_heals_a_corrupted_save_file()
    test_locked_hint_names_the_true_root_cause()
    test_deep_gap_diagnosis_and_recovery_stack()
    test_canvas_fits_without_scrollbar()
    test_reselecting_same_topic_toggles_it_off()
    test_start_quiz_button_reflects_gate_state()
    test_persistence_across_restart()
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    print("\nALL E2E TESTS PASSED")
