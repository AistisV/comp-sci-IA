"""
gui.py — Module 4: Graphical User Interface (App)

Implements the split-screen Tkinter interface from the UML (Figure 3)
and the mockups (Figures 12-16):
  - a canvas on the left showing the (sub)graph, colour-coded by status
  - a sidebar on the right that switches between two modes:
      "navigator" — the full topic list (Figure 12) or a selected
                    topic's subgraph + Start Quiz button (Figure 13)
      "quiz"      — the active multiple-choice quiz (Figure 14)
  - popup alerts for a gated quiz button and quiz results (Figure 16)

This module only handles presentation and event wiring; all DAG logic
lives in graph.py, all persistence in database.py, all quiz scoring in
quiz.py, exactly as separated in the structure chart (Figure 1).

Gatekeeping design note: every topic can always be selected and viewed
(clicking any node or sidebar row is never blocked). Only the "Start
Quiz" button is gated, per SC4's exact wording — see graph.py's
can_start_quiz() docstring for the full rationale.

All widget colours are set explicitly (fg AND bg on every label,
button and radiobutton) rather than left to the platform's Tk theme,
because the default theme differs across OSes -- on macOS in
particular, an unset foreground on a coloured background can render
as barely-visible light-grey-on-light-grey.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from graph import Topic
from layout import calculate_layout

# Colour-coding legend, matching Figure 12's legend bar.
# Text colour is chosen per-status for contrast (dark text on light
# fills, white text on the darker "Locked" grey).
STATUS_COLORS = {
    Topic.STATUS_PASSED: "#8FD98F",     # green
    Topic.STATUS_FAILED: "#F0A0A0",     # red
    Topic.STATUS_UNTESTED: "#F2F2F2",   # near-white
    Topic.STATUS_LOCKED: "#9A9A9A",     # grey
}
STATUS_TEXT_COLORS = {
    Topic.STATUS_PASSED: "#0B3D0B",
    Topic.STATUS_FAILED: "#5C0A0A",
    Topic.STATUS_UNTESTED: "#111111",
    Topic.STATUS_LOCKED: "#FFFFFF",
}
SELECTED_OUTLINE = "#2563EB"            # blue outline, Figure 12/13
DEFAULT_OUTLINE = "#444444"

SIDEBAR_BG = "#EDEDED"
BODY_TEXT = "#111111"
MUTED_TEXT = "#333333"

NODE_W, NODE_H = 150, 56


class App:
    """
    graph : Graph            — in-memory DAG (loaded once at launch)
    db    : DatabaseManager  — persistence
    quiz  : QuizManager      — active quiz session state
    """

    def __init__(self, root: tk.Tk, graph, db, quiz):
        self.root = root
        self.graph = graph
        self.db = db
        self.quiz = quiz

        self.root.title("DAG Revision System")
        self.root.geometry("1000x650")
        self.root.configure(bg="white")

        self.mode = "navigator"          # "navigator" | "quiz"
        self.selected_topic_id: str | None = None
        self.node_positions: dict[str, tuple[int, int]] = {}
        self.node_canvas_ids: dict[str, int] = {}
        self.current_question_index = 0
        self.selected_option_index: tk.IntVar | None = None

        self._build_layout()
        self.render_graph()
        self.switch_sidebar("navigator")

        self.canvas.bind("<Configure>", lambda e: self.render_graph())

    # ------------------------------------------------------------------
    # Static layout: split screen (canvas + sidebar) + legend
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        # No in-window header bar: the OS window titlebar already shows
        # "DAG Revision System" (set via root.title in __init__), so a
        # second app-drawn header here would just duplicate it.
        body = tk.Frame(self.root, bg="white")
        body.pack(side="top", fill="both", expand=True)

        # Left: graph canvas (always visible, per SC2). No scrollbars —
        # the layout algorithm fits every node inside the visible area
        # and re-centres whenever the window is resized.
        self.canvas = tk.Canvas(body, bg="white", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        # Right: sidebar, contents swapped by switch_sidebar().
        self.sidebar = tk.Frame(body, width=270, bg=SIDEBAR_BG)
        self.sidebar.pack(side="right", fill="y")
        self.sidebar.pack_propagate(False)

        # Legend bar along the bottom, matching Figure 12.
        legend = tk.Frame(self.root, bg="#FAFAFA")
        legend.pack(side="bottom", fill="x")
        for label, color in [
            ("Passed", STATUS_COLORS[Topic.STATUS_PASSED]),
            ("Failed", STATUS_COLORS[Topic.STATUS_FAILED]),
            ("Untested", STATUS_COLORS[Topic.STATUS_UNTESTED]),
            ("Locked", STATUS_COLORS[Topic.STATUS_LOCKED]),
            ("Selected", "white"),
        ]:
            swatch = tk.Canvas(legend, width=14, height=14, highlightthickness=1,
                                highlightbackground=SELECTED_OUTLINE if label == "Selected" else "#888")
            swatch.create_rectangle(0, 0, 14, 14, fill=color, outline="")
            swatch.pack(side="left", padx=(10, 3), pady=6)
            tk.Label(legend, text=label, bg="#FAFAFA", fg=BODY_TEXT,
                     font=("Helvetica", 9)).pack(side="left")

    # ------------------------------------------------------------------
    # Graph Canvas rendering (SC2, SC11)
    # ------------------------------------------------------------------

    def render_graph(self) -> None:
        """
        Renders either the full graph (no selection) or the subgraph
        for the selected topic (SC3), colour-coded by status (SC11).
        Always fits and centres within the current canvas size — no
        scrolling, matching the single-screen mockups.
        """
        self.canvas.delete("all")
        self.node_canvas_ids.clear()

        if self.selected_topic_id:
            visible_ids, edges = self.graph.get_subgraph(self.selected_topic_id)
        else:
            visible_ids = set(self.graph.nodes.keys())
            edges = {
                (p, c) for p, children in self.graph.adjacency_list.items()
                for c in children
            }

        canvas_w = max(self.canvas.winfo_width(), 400)
        canvas_h = max(self.canvas.winfo_height(), 300)
        self.node_positions = calculate_layout(visible_ids, self.graph, canvas_w, canvas_h)

        # Draw edges first so nodes render on top.
        for parent_id, child_id in edges:
            if parent_id not in self.node_positions or child_id not in self.node_positions:
                continue
            x1, y1 = self.node_positions[parent_id]
            x2, y2 = self.node_positions[child_id]
            self.canvas.create_line(
                x1, y1 + NODE_H // 2, x2, y2 - NODE_H // 2,
                arrow=tk.LAST, fill="#888888", width=1,
            )

        for topic_id, (x, y) in self.node_positions.items():
            self._draw_node(topic_id, x, y)

    def _draw_node(self, topic_id: str, x: int, y: int) -> None:
        topic = self.graph.nodes[topic_id]
        fill = STATUS_COLORS.get(topic.status, "#FFFFFF")
        text_color = STATUS_TEXT_COLORS.get(topic.status, "#111111")
        outline = SELECTED_OUTLINE if topic_id == self.selected_topic_id else DEFAULT_OUTLINE
        width = 3 if topic_id == self.selected_topic_id else 1

        oval_id = self.canvas.create_oval(
            x - NODE_W // 2, y - NODE_H // 2, x + NODE_W // 2, y + NODE_H // 2,
            fill=fill, outline=outline, width=width,
        )
        font_size = 9 if len(topic.name) <= 18 else 8
        text_id = self.canvas.create_text(
            x, y, text=topic.name, width=NODE_W - 24, font=("Helvetica", font_size, "bold"),
            fill=text_color, justify="center",
        )
        self.node_canvas_ids[topic_id] = oval_id

        for cid in (oval_id, text_id):
            self.canvas.tag_bind(cid, "<Button-1>", lambda e, tid=topic_id: self.on_node_click(tid))

    # ------------------------------------------------------------------
    # User flow: clicking a topic node or sidebar row.
    #
    # Per SC4 (see graph.py docstring), selection is NEVER gated — any
    # topic can be viewed at any time. Only the Start Quiz button is
    # conditionally disabled, inside _render_navigator_sidebar().
    # ------------------------------------------------------------------

    def on_node_click(self, topic_id: str) -> None:
        if self.mode == "quiz":
            return  # ignore canvas clicks while a quiz is active
        self.select_topic(topic_id)

    def select_topic(self, topic_id: str) -> None:
        """
        Selects topic_id, extracts its subgraph, and shows the navigator.
        Clicking the ALREADY-selected topic a second time toggles it back
        off, returning to the full-graph view (SC3) rather than needing a
        separate "deselect" control.
        """
        if self.selected_topic_id == topic_id:
            self.deselect_topic()
            return
        self.selected_topic_id = topic_id
        self.render_graph()
        self.switch_sidebar("navigator")

    def show_alert(self, msg: str) -> None:
        messagebox.showinfo("DAG Revision System", msg)

    # ------------------------------------------------------------------
    # Sidebar Mode Controller (SC2)
    # ------------------------------------------------------------------

    def switch_sidebar(self, mode: str) -> None:
        self.mode = mode
        for widget in self.sidebar.winfo_children():
            widget.destroy()

        if mode == "navigator":
            self._render_navigator_sidebar()
        elif mode == "quiz":
            self._render_quiz_sidebar()

    def _render_navigator_sidebar(self) -> None:
        tk.Label(self.sidebar, text="Topics", bg=SIDEBAR_BG, fg=BODY_TEXT,
                  font=("Helvetica", 11, "bold")).pack(pady=(10, 4))

        list_frame = tk.Frame(self.sidebar, bg=SIDEBAR_BG)
        list_frame.pack(fill="both", expand=False, padx=8)

        for topic_id, topic in sorted(self.graph.nodes.items(), key=lambda kv: kv[0]):
            is_selected = topic_id == self.selected_topic_id
            bg = STATUS_COLORS.get(topic.status, "white")
            fg = STATUS_TEXT_COLORS.get(topic.status, "#111111")
            row = tk.Label(
                list_frame, text=topic.name, bg=bg, fg=fg,
                anchor="w", padx=8, pady=6, font=("Helvetica", 10),
                relief="solid" if is_selected else "flat",
                borderwidth=2 if is_selected else 0,
                highlightbackground=SELECTED_OUTLINE,
            )
            row.pack(fill="x", pady=2)
            row.bind("<Button-1>", lambda e, tid=topic_id: self.select_topic(tid))

        if self.selected_topic_id:
            topic = self.graph.nodes[self.selected_topic_id]
            can_quiz = self.graph.can_start_quiz(self.selected_topic_id)

            if not can_quiz:
                root_cause_name = self._find_blocking_root_cause_name(self.selected_topic_id)
                if root_cause_name:
                    tk.Label(
                        self.sidebar,
                        text=f'Locked: fix "{root_cause_name}" first',
                        bg=SIDEBAR_BG, fg="#8A1F1F", font=("Helvetica", 9, "italic"),
                        wraplength=240, justify="left",
                    ).pack(fill="x", padx=8, pady=(6, 0))

            # A tk.Label styled as a button, not a real tk.Button:
            # native button chrome (macOS in particular) overrides
            # custom bg/fg colours with the platform's own theme, the
            # same class of rendering mismatch fixed earlier for node
            # text. A Label with a manual click binding renders its
            # colours exactly as set on every platform, matching the
            # already-working topic-row buttons above.
            self._make_button(
                self.sidebar,
                text="Start Quiz",
                bg="#2E8B3D" if can_quiz else "#B5B5B5",
                fg="white",
                command=(lambda: self.start_quiz(self.selected_topic_id)) if can_quiz else None,
            ).pack(fill="x", padx=8, pady=10)

    def _make_button(self, parent, text, bg, fg, command):
        """
        Builds a clickable, flat-styled tk.Label that behaves like a
        button but always renders with the exact colours given,
        regardless of platform button theming. Disabled (command=None)
        renders with a muted look and ignores clicks.
        """
        enabled = command is not None
        lbl = tk.Label(
            parent, text=text, bg=bg, fg=fg if enabled else "#EFEFEF",
            font=("Helvetica", 11, "bold"), pady=8, cursor="hand2" if enabled else "arrow",
            relief="flat",
        )
        if enabled:
            lbl.bind("<Button-1>", lambda e: command())
        return lbl

    def deselect_topic(self) -> None:
        """Clears the current selection and returns to the full-graph view."""
        self.selected_topic_id = None
        self.render_graph()
        self.switch_sidebar("navigator")

    def _find_blocking_root_cause_name(self, topic_id: str) -> str | None:
        """
        For the sidebar's "Locked: fix X first" hint. A topic's direct
        blocking parent is often itself only "Locked" (a side effect),
        not the topic that actually failed a quiz -- naming that direct
        parent is technically true but confusing (SC6 is precisely
        about finding the real root cause instead of the symptom).

        Walks upward through Failed/Locked parents until it reaches a
        topic that is actually "Failed" (the true root cause) rather
        than merely "Locked" (a downstream consequence), reusing the
        same DFS idea as graph.find_gap.

        Returns None if no Failed ancestor is found -- e.g. every
        upstream topic is merely "Locked" with no recorded failure
        anywhere. main.py's reconcile_locks() sweep on every launch is
        what should prevent this state from ever reaching the UI, so
        this is a defensive fallback: it deliberately does NOT name the
        nearest Locked parent instead, since that would claim a topic
        needs "fixing" when nothing is actually broken -- misleading in
        exactly the way that prompted this method to exist.
        """
        visited: set[str] = set()

        def _walk(node_id: str) -> str | None:
            for parent_id in self.graph.get_parents(node_id):
                if parent_id in visited:
                    continue
                visited.add(parent_id)
                status = self.graph.nodes[parent_id].status
                if status == Topic.STATUS_FAILED:
                    return parent_id
                if status == Topic.STATUS_LOCKED:
                    found = _walk(parent_id)
                    if found:
                        return found
            return None

        root_id = _walk(topic_id)
        return self.graph.nodes[root_id].name if root_id else None

    def start_quiz(self, topic_id: str) -> None:
        self.quiz.initialize_quiz(topic_id)
        self.current_question_index = 0
        self.switch_sidebar("quiz")
        self.render_graph()

    # ------------------------------------------------------------------
    # Quiz UI (Figure 6, Figure 14)
    # ------------------------------------------------------------------

    def _render_quiz_sidebar(self) -> None:
        topic = self.graph.nodes[self.quiz.current_topic_id]
        total = self.quiz.total_questions

        tk.Label(self.sidebar, text=topic.name, bg=SIDEBAR_BG, fg=BODY_TEXT,
                  font=("Helvetica", 12, "bold"), wraplength=240).pack(pady=(12, 0), padx=8)
        tk.Label(
            self.sidebar,
            text=f"Question {self.current_question_index + 1} of {total}",
            bg=SIDEBAR_BG, font=("Helvetica", 9), fg=MUTED_TEXT,
        ).pack(pady=(0, 8))

        question = self.quiz.current_questions[self.current_question_index]
        q_box = tk.Label(
            self.sidebar, text=question["text"], bg="white", fg=BODY_TEXT, wraplength=240,
            relief="solid", borderwidth=1, padx=10, pady=10, justify="left",
        )
        q_box.pack(fill="x", padx=8, pady=(0, 10))

        self.selected_option_index = tk.IntVar(value=-1)
        for i, option_text in enumerate(question["options"]):
            rb = tk.Radiobutton(
                self.sidebar, text=option_text, variable=self.selected_option_index,
                value=i, bg="white", fg=BODY_TEXT, anchor="w", wraplength=220,
                indicatoron=False, selectcolor="#BFDBFE",
                activebackground="#E5E7EB", activeforeground=BODY_TEXT,
                font=("Helvetica", 10), pady=6, relief="solid", borderwidth=1,
                highlightthickness=0,
            )
            rb.pack(fill="x", padx=8, pady=2)

        tk.Button(
            self.sidebar, text="Submit Answer", bg="#2563EB", fg="white",
            activebackground="#1D4ED8", activeforeground="white",
            font=("Helvetica", 10, "bold"), pady=6,
            command=self.on_submit_answer,
        ).pack(fill="x", padx=8, pady=14)

    def on_submit_answer(self) -> None:
        chosen = self.selected_option_index.get()
        if chosen == -1:
            self.show_alert("Please select an answer before submitting.")
            return

        self.quiz.submit_answer(self.current_question_index, chosen)

        if self.current_question_index + 1 < self.quiz.total_questions:
            self.current_question_index += 1
            self.switch_sidebar("quiz")
        else:
            self.finish_quiz()

    def finish_quiz(self) -> None:
        """Figure 6: calculate score, show pass/fail popup, then branch."""
        passed = self.quiz.evaluate_attempt()
        topic = self.graph.nodes[self.quiz.current_topic_id]
        self.show_quiz_result(self.quiz.score, self.quiz.total_questions, passed, topic.name)

        if passed:
            self.handle_success(self.quiz.current_topic_id)
        else:
            self.handle_failure(self.quiz.current_topic_id)

    def show_quiz_result(self, score: int, total: int, passed: bool, topic_name: str) -> None:
        """Figure 16: post-quiz result popup."""
        verdict = "Passed" if passed else "Failed"
        messagebox.showinfo(
            "Quiz Complete",
            f'{topic_name}\n{score} / {total} correct\n\n{verdict}',
        )

    # ------------------------------------------------------------------
    # Success branch (Figure 7, top half) + upward cascade extension
    # ------------------------------------------------------------------

    def handle_success(self, topic_id: str) -> None:
        self.graph.nodes[topic_id].update_status(Topic.STATUS_PASSED)
        self.db.save_progress(topic_id, Topic.STATUS_PASSED)

        # Design extension: passing a topic implies mastery of every
        # prerequisite behind it, so cascade "Passed" upward through
        # every ancestor that isn't already Passed (see graph.py).
        newly_passed_ancestors = self.graph.cascade_pass_upward(topic_id)
        for aid in newly_passed_ancestors:
            self.db.save_progress(aid, Topic.STATUS_PASSED)

        # Then propagate downward as usual: unlock any child whose
        # prerequisites are now fully satisfied (Figure 11 / SC9).
        for pid in [topic_id] + newly_passed_ancestors:
            unlocked = self.graph.evaluate_unlock(pid)
            for uid in unlocked:
                self.db.save_progress(uid, Topic.STATUS_UNTESTED)

        if self.quiz.recovery_is_empty():
            self.selected_topic_id = topic_id
            self.switch_sidebar("navigator")
        else:
            next_topic = self.quiz.pop_next_recovery_topic()
            self.selected_topic_id = next_topic
            self.start_quiz(next_topic)
            return

        self.render_graph()

    # ------------------------------------------------------------------
    # Failure branch (Figure 7, top half): knowledge-gap diagnosis loop
    # ------------------------------------------------------------------

    def handle_failure(self, topic_id: str) -> None:
        self.graph.nodes[topic_id].update_status(Topic.STATUS_FAILED)
        self.db.save_progress(topic_id, Topic.STATUS_FAILED)

        locked = self.graph.apply_lock(topic_id, set())
        if locked:
            self.db.save_progress_batch(list(locked), Topic.STATUS_LOCKED)

        root_cause_id, _ = self.graph.find_gap(topic_id)

        if root_cause_id == topic_id:
            # No parents at all: the failed topic itself is the root cause.
            self.show_alert(f'Root cause found: "{self.graph.nodes[topic_id].name}"')
            self.selected_topic_id = topic_id
            self.switch_sidebar("navigator")
            self.render_graph()
            return

        # Push the originally-failed topic so we return to it once the
        # diagnosis target is re-passed. find_gap only ever steps back
        # ONE level per failure (see its docstring) -- if THIS diagnosis
        # quiz also fails, that is a fresh, independent call into
        # handle_failure, which will call find_gap again from the new
        # topic and may escalate one level further up the chain, itself
        # pushing that new topic onto the stack. A multi-level chain
        # therefore unwinds one link at a time, exactly mirroring
        # however many times the student actually failed, rather than
        # committing to a whole multi-level walk up front.
        self.quiz.push_recovery(topic_id)

        self.show_alert(
            f'Launching diagnosis — testing: "{self.graph.nodes[root_cause_id].name}"'
        )
        self.selected_topic_id = root_cause_id
        self.start_quiz(root_cause_id)
