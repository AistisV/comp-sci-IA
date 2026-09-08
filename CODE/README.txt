DAG-Based Physics Revision System
==================================

Requirements
------------
  Python 3.10+  (tkinter must be available — usually bundled; on
  Debian/Ubuntu Linux install with: sudo apt install python3-tk)
  No third-party pip packages required — only the standard library
  (tkinter, sqlite3, json, random, unittest).

Running
-------
  python3 main.py

All files must stay together in the same folder. The SQLite database
(physics_tutor.db) is created automatically on first run from
nodes.json; do not delete it or all progress will be reset (deleting
it and restarting will simply re-seed a fresh copy from nodes.json).

Every launch also runs graph.reconcile_locks() once, which sweeps the
whole graph and releases any topic that is stuck "Locked" but no
longer has a Failed/Locked parent -- see design decision 4 below. This
makes an existing save file self-healing: if you have an older save
from before that fix, just relaunch and it corrects itself.

File overview (maps directly onto the Structure Chart, Criterion B)
---------------------------------------------------------------------
  main.py       – Entry point: DB init/seed, cycle check, GUI launch
                  (Figure 5's "App Launch" flow)
  database.py   – Module 1: DatabaseManager — schema, JSON seeding,
                  all CRUD for topics/edges/progress/questions/options
  graph.py      – Module 2: Topic + Graph classes — adjacency list,
                  reverse adjacency list, and every DFS algorithm
                  (detect_cycles, can_start_quiz, apply_lock,
                  evaluate_unlock, cascade_pass_upward, find_gap,
                  get_subgraph)
  quiz.py       – Module 3: QuizManager — randomised question order,
                  scoring, and the LIFO recovery stack
  layout.py     – Small helper used only by gui.py to position nodes
                  on the canvas (layered by prerequisite depth); not
                  part of the UML, purely a rendering concern
  gui.py        – Module 4: App — Tkinter split-screen interface,
                  sidebar mode switching, alert popups
  nodes.json    – Syllabus data (topics, prerequisite edges, MCQs)
                  supplied by the client (Mr. Poviliauskas)

Testing
-------
  test_logic.py    – 27 unit tests against graph.py/database.py/
                      quiz.py in isolation (no GUI)
  test_gui_e2e.py  – 8 end-to-end tests that drive the REAL Tkinter
                      App through its actual widget callbacks
                      (button clicks, radio selections) to verify the
                      full user flows from Figures 5-7, including the
                      knowledge-gap diagnosis + recovery-stack loop,
                      the upward-cascade extension, and the SC4
                      gatekeeping rule. Needs a display; on a headless
                      Linux machine run it under Xvfb, e.g.:
                          Xvfb :99 -screen 0 1024x768x24 &
                          DISPLAY=:99 python3 test_gui_e2e.py

  Run both with:
      python3 -m unittest test_logic -v
      python3 test_gui_e2e.py

Mapping to Success Criteria (Criterion A)
------------------------------------------
  SC1  Data import + cycle detection  -> database.seed_from_json,
                                          graph.detect_cycles
  SC2  Split-screen UI                -> gui.App._build_layout
  SC3  Scope filtering (subgraph)     -> graph.get_subgraph,
                                          gui.App.select_topic
  SC4  Topic gatekeeping              -> graph.can_start_quiz,
                                          gui.App._render_navigator_sidebar
  SC5  Randomised quiz builder        -> quiz.initialize_quiz
  SC6  Knowledge gap diagnosis        -> graph.find_gap
  SC7  Quiz loop / recovery stack     -> quiz.recovery_stack,
                                          gui.App.handle_failure/success
  SC8  Recursive status lock          -> graph.apply_lock
  SC9  Status overwrite / unlock      -> graph.evaluate_unlock
  SC10 Data persistence               -> database.save_progress(_batch),
                                          database.load_progress
  SC11 Visual feedback (colour-code)  -> gui.STATUS_COLORS,
                                          gui.App._draw_node

Design decisions worth documenting in the write-up
----------------------------------------------------
  1. Selection vs. gatekeeping (SC3 vs SC4): the original Figure 5
     sketch shows topic *selection* itself being blocked by
     is_available(). SC4's exact wording is narrower: only the "Start
     Quiz" button must be disabled, and only when a prerequisite is
     "Failed" or "Locked" (an "Untested" prerequisite does NOT block
     it). This build follows SC4: every topic can always be selected
     and viewed; only Start Quiz is conditionally disabled. See
     graph.py's module docstring and can_start_quiz() for the full
     rationale.
  2. Upward cascade on pass (extension beyond the original diagrams):
     passing a topic now also marks every one of its ancestors
     (direct and indirect prerequisites) as "Passed", on the
     reasoning that succeeding at an advanced topic demonstrates
     mastery of the material it depends on. This is implemented in
     graph.cascade_pass_upward() and wired into
     gui.App.handle_success(). It is a deliberate deviation from
     Figure 11 (evaluate_unlock), which only ever propagates
     downward — worth a sentence in Criterion A/E explaining the
     trade-off (a very easy final quiz could theoretically mark a
     long chain "Passed" without individually testing each one).
  3. Quiz pass threshold: a quiz is scored as a pass at >= 50%
     correct (quiz.evaluate_attempt). Not specified in the original
     documentation — flagged here as an assumption.
  4. Unlock condition (evaluate_unlock, deviation from Figure 11):
     Figure 11 releases a Locked child only once ALL of its parents
     are "Passed" again. Combined with apply_lock() only ever locking
     descendants of a failed topic (never the topic itself), a parent
     that settles back at "Untested" -- rather than being explicitly
     re-passed -- could never satisfy "all parents Passed", so its
     Locked children would stay Locked forever even though nothing is
     actively broken about them any more. To stay consistent with the
     SC4 gatekeeping rule, evaluate_unlock() here releases a Locked
     child as soon as NONE of its parents are "Failed" or "Locked" (an
     "Untested" or "Passed" parent both count as fine), and recurses
     down the whole subtree so a nested chain of locked topics clears
     in one pass rather than only the direct children. See
     graph.py's module docstring and evaluate_unlock() for the full
     rationale, and test_gui_e2e.py's
     test_unlock_cascades_through_a_previously_locked_chain for the
     regression test that caught this.
  5. Self-healing on launch (graph.reconcile_locks, main.py): even
     with (4) fixed going forward, a save file written before that fix
     could already contain a topic stuck "Locked" with nothing Failed
     anywhere upstream of it (the specific evaluate_unlock() call that
     would have released it never happened, because the topic that
     originally failed had already been reset by an older, buggier
     unlock by the time the fix landed). main.py now runs
     graph.reconcile_locks() once on every launch, which sweeps the
     whole graph and releases any such orphaned lock regardless of how
     it got there, repeating until a full pass makes no more changes.
     The gui.App._find_blocking_root_cause_name() sidebar hint also
     returns None (shows no message) rather than naming a merely-Locked
     parent when no genuinely Failed topic exists upstream, since that
     would otherwise claim something needs "fixing" when nothing is.
  6. find_gap no longer stops at a topic whose direct parents are all
     already "Passed" (deviation from Figure 9): the original sketch
     treated that as proof the failed topic itself was the root cause.
     A Pass is a record of a past result, not a permanent guarantee of
     retention -- a student can forget material they once passed. This
     build instead steps back exactly ONE level to re-confirm the
     nearest Passed parent, pushing the originally-failed topic onto
     the recovery stack (SC7) as before. If that re-test also fails,
     it triggers its own independent find_gap call, which may escalate
     one further level up the chain -- so a persistently broken chain
     unwinds one link at a time, matched exactly to how many times the
     student actually failed, rather than committing to a multi-level
     walk in a single pass. See graph.py's find_gap() docstring, and
     test_gui_e2e.py's test_failure_triggers_lock_and_diagnosis for
     the regression test covering both the single-step case and the
     escalate-on-a-second-failure case.
  7. apply_lock no longer overwrites an already-"Failed" descendant to
     "Locked" (companion fix to (6)): once find_gap can push several
     topics onto the recovery stack across separate failures, an
     earlier-failed topic can still be sitting there awaiting its
     re-test when some unrelated ancestor fails too. apply_lock already
     skipped descendants that were already "Locked" (their own
     descendants were locked when they first became Locked); it now
     extends that same rule to "Failed" descendants, since a Failed
     result is a specific, genuine attempt outcome that failing some
     other ancestor should not silently discard. See graph.py's
     apply_lock() docstring and test_logic.py's
     test_apply_lock_never_overwrites_an_already_failed_descendant.

Resetting progress
-------------------
  Delete physics_tutor.db and restart — it will be recreated and
  re-seeded from nodes.json with every topic set to "Untested".
