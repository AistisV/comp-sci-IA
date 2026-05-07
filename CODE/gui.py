"""
gui.py
------
Graphical User Interface for the IB Physics Knowledge Navigator.

Layout
------
  ┌──────────────────────────────────┬──────────────────┐
  │  Graph Canvas (tkinter Canvas)   │  Sidebar Panel   │
  │  – draws DAG with colour-coded   │  (Navigator OR   │
  │    nodes and directed edges       │   Quiz view)     │
  │  – click a node to select it     │                  │
  └──────────────────────────────────┴──────────────────┘

Sidebar states
--------------
  NAVIGATOR  – scrollable topic list; shown on startup and after Back
  DETAIL     – info + Start Quiz button for the selected topic
  QUIZ       – question text and radio-button options
  RESULT     – score, correct answers, and next action

All graph algorithms are delegated to PhysicsGraph; all DB writes go
through database.py.  The GUI only orchestrates the flow.
"""

import tkinter as tk
from tkinter import messagebox
import math

from graph  import PhysicsGraph
from quiz   import QuizSession
from database import get_all_progress, set_status, reset_all_progress

# ── Visual constants ───────────────────────────────────────────────────────────

PALETTE = {
    # node fill colours by status
    "fill_available": "#EEF0FF",
    "fill_passed":    "#D4EDDA",
    "fill_failed":    "#F8D7DA",
    "fill_locked":    "#E9ECEF",
    # node border colours by status
    "border_available": "#6C63FF",
    "border_passed":    "#28A745",
    "border_failed":    "#DC3545",
    "border_locked":    "#ADB5BD",
    # selection highlight (overrides border)
    "border_selected":  "#FFD700",
    # backgrounds
    "canvas_bg":  "#0F1117",
    "sidebar_bg": "#1C1C2E",
    "win_bg":     "#13131F",
    # text
    "text_main":  "#F0F0FF",
    "text_dim":   "#9090BB",
    "text_node":  "#1A1A2E",
    # accents
    "accent":     "#6C63FF",
    "orange":     "#FFA040",
    "edge":       "#3A3A5A",
}

NODE_R      = 38    # node circle radius in pixels
CANVAS_PAD  = 60    # minimum padding from canvas edge to node centre
SIDEBAR_W   = 310   # fixed sidebar width in pixels


class App:
    """
    Root application class.  Creates the window, graph, and all panels.
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("IB Physics Knowledge Navigator")
        self.root.geometry("1200x720")
        self.root.minsize(900, 600)
        self.root.configure(bg=PALETTE["win_bg"])

        # Core data
        self.graph    = PhysicsGraph()
        self.statuses = get_all_progress()   # live mirror of progress table

        # Selection state
        self.selected_topic: str | None      = None
        self.subgraph_ids:   set[str] | None = None
        self.node_positions: dict[str, tuple[float, float]] = {}

        # Quiz / remediation state
        self.quiz_session:            QuizSession | None = None
        self.in_remediation:          bool               = False
        self.remediation_path:        list[str]          = []
        self.remediation_index:       int                = 0
        self.original_failed_topic:   str | None         = None

        self._build_window()

        # Draw after layout has been committed (prevents winfo_width = 1)
        self.root.after(80, lambda: self._draw_graph(self.subgraph_ids))
        self._show_navigator()

    # ══════════════════════════════════════════════════════════════════════════
    # Window construction
    # ══════════════════════════════════════════════════════════════════════════

    def _build_window(self) -> None:
        """Construct the two-pane layout."""
        outer = tk.Frame(self.root, bg=PALETTE["win_bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # ── Left pane: graph canvas ──────────────────────────────────────────
        left = tk.Frame(outer, bg=PALETTE["win_bg"])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(
            left, text="Knowledge Graph",
            bg=PALETTE["win_bg"], fg=PALETTE["text_main"],
            font=("Helvetica", 13, "bold")
        ).pack(anchor=tk.W, pady=(0, 4))

        self.canvas = tk.Canvas(
            left, bg=PALETTE["canvas_bg"],
            highlightthickness=1, highlightbackground="#333355"
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>",
                         lambda e: self._draw_graph(self.subgraph_ids))
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        self._build_legend(left)

        # ── Right pane: sidebar ──────────────────────────────────────────────
        self.sidebar = tk.Frame(
            outer, bg=PALETTE["sidebar_bg"],
            width=SIDEBAR_W, padx=16, pady=14
        )
        self.sidebar.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        self.sidebar.pack_propagate(False)

    def _build_legend(self, parent: tk.Frame) -> None:
        """Render the four-colour status legend below the canvas."""
        row = tk.Frame(parent, bg=PALETTE["win_bg"])
        row.pack(anchor=tk.W, pady=(5, 0))

        items = [
            ("Available", "fill_available", "border_available"),
            ("Passed",    "fill_passed",    "border_passed"),
            ("Failed",    "fill_failed",    "border_failed"),
            ("Locked",    "fill_locked",    "border_locked"),
        ]
        for label, fill_key, border_key in items:
            cell = tk.Frame(row, bg=PALETTE["win_bg"])
            cell.pack(side=tk.LEFT, padx=8)
            tk.Canvas(
                cell, width=13, height=13,
                bg=PALETTE[fill_key],
                highlightthickness=1,
                highlightbackground=PALETTE[border_key]
            ).pack(side=tk.LEFT, padx=(0, 3))
            tk.Label(
                cell, text=label,
                bg=PALETTE["win_bg"], fg=PALETTE["text_dim"],
                font=("Helvetica", 8)
            ).pack(side=tk.LEFT)

    # ══════════════════════════════════════════════════════════════════════════
    # Graph drawing
    # ══════════════════════════════════════════════════════════════════════════

    def _pixel_positions(
        self, node_ids: set[str]
    ) -> dict[str, tuple[float, float]]:
        """
        Map abstract (layer, y-offset) coordinates from compute_layout()
        into canvas pixel positions, scaled to the current canvas size.
        """
        rel = self.graph.compute_layout(node_ids)
        if not rel:
            return {}

        w = self.canvas.winfo_width()  or 800
        h = self.canvas.winfo_height() or 560

        xs = [p[0] for p in rel.values()]
        ys = [p[1] for p in rel.values()]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        x_span = x_max - x_min or 1
        y_span = y_max - y_min or 1

        pad  = CANVAS_PAD + NODE_R
        av_w = w - 2 * pad
        av_h = h - 2 * pad

        pixel: dict[str, tuple[float, float]] = {}
        for tid, (rx, ry) in rel.items():
            px = pad + (rx - x_min) / x_span * av_w if x_span > 0 else w / 2
            py = pad + (ry - y_min) / y_span * av_h if y_span > 0 else h / 2
            pixel[tid] = (px, py)
        return pixel

    def _draw_graph(self, subgraph_ids: set[str] | None = None) -> None:
        """
        Clear and redraw the entire graph canvas.
        If subgraph_ids is provided, only those nodes (and edges between
        them) are drawn — implements Subgraph Extraction (SC3).
        """
        self.canvas.delete("all")

        nodes = subgraph_ids if subgraph_ids else set(self.graph.topics.keys())
        self.node_positions = self._pixel_positions(nodes)

        if not self.node_positions:
            return

        # Draw edges first so nodes render on top.
        for (from_id, to_id) in self.graph.get_edges():
            if from_id in self.node_positions and to_id in self.node_positions:
                self._draw_edge(from_id, to_id)

        # Draw nodes.
        for tid in self.node_positions:
            self._draw_node(tid)

    def _draw_edge(self, from_id: str, to_id: str) -> None:
        """Draw a directed arrow between two nodes."""
        x1, y1 = self.node_positions[from_id]
        x2, y2 = self.node_positions[to_id]

        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy)
        if dist == 0:
            return

        # Pull start/end back by NODE_R so the arrow tip rests on the border.
        ux, uy = dx / dist, dy / dist
        sx = x1 + ux * (NODE_R + 3)
        sy = y1 + uy * (NODE_R + 3)
        ex = x2 - ux * (NODE_R + 3)
        ey = y2 - uy * (NODE_R + 3)

        self.canvas.create_line(
            sx, sy, ex, ey,
            fill=PALETTE["edge"], width=1.5,
            arrow=tk.LAST, arrowshape=(9, 11, 4)
        )

    def _draw_node(self, topic_id: str) -> None:
        """Draw one node circle with its label and status icon."""
        cx, cy = self.node_positions[topic_id]
        status  = self.statuses.get(topic_id, {}).get("status", "available")

        fill   = PALETTE[f"fill_{status}"]
        border = (
            PALETTE["border_selected"]
            if topic_id == self.selected_topic
            else PALETTE[f"border_{status}"]
        )
        bwidth = 3 if topic_id == self.selected_topic else 2

        r = NODE_R
        self.canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            fill=fill, outline=border, width=bwidth,
            tags=("node", f"node_{topic_id}")
        )

        # Wrap long names across two lines inside the circle.
        name  = self.graph.topics[topic_id]
        words = name.split()
        if len(words) <= 2:
            self.canvas.create_text(
                cx, cy, text=name,
                fill=PALETTE["text_node"],
                font=("Helvetica", 7, "bold"),
                width=r * 1.7,
                tags=(f"node_{topic_id}",)
            )
        else:
            mid  = (len(words) + 1) // 2
            top  = " ".join(words[:mid])
            bot  = " ".join(words[mid:])
            self.canvas.create_text(
                cx, cy - 7, text=top,
                fill=PALETTE["text_node"],
                font=("Helvetica", 7, "bold"),
                width=r * 1.7,
                tags=(f"node_{topic_id}",)
            )
            self.canvas.create_text(
                cx, cy + 7, text=bot,
                fill=PALETTE["text_node"],
                font=("Helvetica", 7, "bold"),
                width=r * 1.7,
                tags=(f"node_{topic_id}",)
            )

        # Small status icon in top-right corner of the circle.
        icons = {"passed": "✓", "failed": "✗", "locked": "⊘"}
        if status in icons:
            self.canvas.create_text(
                cx + r - 7, cy - r + 9,
                text=icons[status],
                font=("Helvetica", 8, "bold"),
                fill=border,
                tags=(f"node_{topic_id}",)
            )

    # ══════════════════════════════════════════════════════════════════════════
    # Canvas interaction
    # ══════════════════════════════════════════════════════════════════════════

    def _on_canvas_click(self, event: tk.Event) -> None:
        """Detect which node (if any) was clicked by hit-testing every circle."""
        for tid, (cx, cy) in self.node_positions.items():
            if math.hypot(event.x - cx, event.y - cy) <= NODE_R:
                self._select_topic(tid)
                return
        # Clicked empty space: deselect and return to full graph.
        self.selected_topic = None
        self.subgraph_ids   = None
        self._draw_graph()
        self._show_navigator()

    def _select_topic(self, topic_id: str) -> None:
        """
        Select a topic: perform subgraph extraction and show its detail panel.
        Subgraph extraction (SC3): compute ancestor set and redraw with only
        those nodes visible to focus attention on the prerequisite chain.
        """
        self.selected_topic = topic_id
        ancestors = self.graph.get_ancestors(topic_id)
        self.subgraph_ids = ancestors
        self._draw_graph(ancestors)
        self._show_topic_detail(topic_id)

    # ══════════════════════════════════════════════════════════════════════════
    # Sidebar helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _clear_sidebar(self) -> None:
        for w in self.sidebar.winfo_children():
            w.destroy()

    def _label(self, text: str, **kw) -> tk.Label:
        """Convenience: create a Label in the sidebar with common defaults."""
        defaults = dict(
            bg=PALETTE["sidebar_bg"], fg=PALETTE["text_main"],
            font=("Helvetica", 9), wraplength=270, justify=tk.LEFT
        )
        defaults.update(kw)
        lbl = tk.Label(self.sidebar, text=text, **defaults)
        lbl.pack(anchor=tk.W, pady=1)
        return lbl

    def _divider(self) -> None:
        tk.Frame(self.sidebar, bg="#333355", height=1).pack(
            fill=tk.X, pady=10
        )

    def _btn(self, text: str, command, bg: str = None, fg: str = "white") -> tk.Button:
        """Convenience: create a full-width button in the sidebar."""
        b = tk.Button(
            self.sidebar, text=text, command=command,
            bg=bg or PALETTE["accent"], fg=fg,
            font=("Helvetica", 10, "bold"),
            relief=tk.FLAT, cursor="hand2",
            activebackground="#8880FF", activeforeground="white",
            pady=7
        )
        b.pack(fill=tk.X, pady=(4, 0))
        return b

    # ══════════════════════════════════════════════════════════════════════════
    # Navigator panel
    # ══════════════════════════════════════════════════════════════════════════

    def _show_navigator(self) -> None:
        """Render the topic-list navigator in the sidebar."""
        self._clear_sidebar()

        tk.Label(
            self.sidebar, text="Topic Navigator",
            bg=PALETTE["sidebar_bg"], fg=PALETTE["text_main"],
            font=("Helvetica", 13, "bold")
        ).pack(anchor=tk.W, pady=(0, 4))

        tk.Label(
            self.sidebar,
            text="Click a topic or select one below to view its "
                 "prerequisite chain and start a quiz.",
            bg=PALETTE["sidebar_bg"], fg=PALETTE["text_dim"],
            font=("Helvetica", 8), wraplength=270, justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 10))

        # ── Scrollable list ──────────────────────────────────────────────────
        list_frame = tk.Frame(self.sidebar, bg=PALETTE["sidebar_bg"])
        list_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(list_frame, bg=PALETTE["sidebar_bg"])
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        lb = tk.Listbox(
            list_frame,
            bg="#12121E", fg=PALETTE["text_main"],
            font=("Helvetica", 9),
            selectbackground=PALETTE["accent"],
            borderwidth=0, relief=tk.FLAT,
            yscrollcommand=scrollbar.set,
            cursor="hand2", activestyle="none"
        )
        lb.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=lb.yview)

        topo = self.graph.topological_sort()
        self._nav_topo = topo   # store for selection handler

        status_icons = {
            "available": "○",
            "passed":    "✓",
            "failed":    "✗",
            "locked":    "⊘",
        }
        for tid in topo:
            s    = self.statuses.get(tid, {}).get("status", "available")
            icon = status_icons.get(s, "○")
            name = self.graph.topics[tid]
            lb.insert(tk.END, f"  {icon}  {name}")

        def _on_select(event):
            sel = lb.curselection()
            if sel:
                self._select_topic(topo[sel[0]])

        lb.bind("<<ListboxSelect>>", _on_select)

        # ── Reset button ─────────────────────────────────────────────────────
        self._divider()
        self._btn(
            "Reset All Progress",
            command=self._reset_progress,
            bg="#5C1010"
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Topic detail panel
    # ══════════════════════════════════════════════════════════════════════════

    def _show_topic_detail(self, topic_id: str) -> None:
        """
        Show topic name, status, prerequisite list, and the Start Quiz button.
        Implements topic gatekeeping (SC4): button is hidden if any parent
        is currently 'failed' or 'locked'.
        """
        self._clear_sidebar()
        status = self.statuses.get(topic_id, {}).get("status", "available")
        name   = self.graph.topics[topic_id]

        # Back link
        tk.Button(
            self.sidebar, text="← Navigator",
            bg=PALETTE["sidebar_bg"], fg=PALETTE["text_dim"],
            font=("Helvetica", 8), relief=tk.FLAT, cursor="hand2",
            command=self._go_to_navigator
        ).pack(anchor=tk.W, pady=(0, 8))

        # Topic title
        tk.Label(
            self.sidebar, text=name,
            bg=PALETTE["sidebar_bg"], fg=PALETTE["text_main"],
            font=("Helvetica", 13, "bold"), wraplength=270, justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 6))

        # Status badge
        badge_colours = {
            "available": (PALETTE["accent"],    "Available"),
            "passed":    ("#28A745",             "Passed ✓"),
            "failed":    ("#DC3545",             "Failed ✗"),
            "locked":    ("#6C757D",             "Locked ⊘"),
        }
        bg_col, label_txt = badge_colours.get(
            status, (PALETTE["accent"], status.capitalize())
        )
        tk.Label(
            self.sidebar, text=f"  {label_txt}  ",
            bg=bg_col, fg="white",
            font=("Helvetica", 8, "bold"), padx=4, pady=2
        ).pack(anchor=tk.W, pady=(0, 12))

        # Prerequisite list
        parents = self.graph.parents.get(topic_id, [])
        if parents:
            tk.Label(
                self.sidebar, text="Prerequisites:",
                bg=PALETTE["sidebar_bg"], fg=PALETTE["text_dim"],
                font=("Helvetica", 8, "bold")
            ).pack(anchor=tk.W, pady=(0, 3))
            for pid in parents:
                ps   = self.statuses.get(pid, {}).get("status", "available")
                icon = {"passed": "✓", "failed": "✗", "locked": "⊘"}.get(ps, "○")
                col  = {
                    "passed": "#28A745", "failed": "#DC3545",
                    "locked": "#6C757D", "available": PALETTE["text_dim"]
                }.get(ps, PALETTE["text_dim"])
                tk.Label(
                    self.sidebar,
                    text=f"  {icon}  {self.graph.topics[pid]}",
                    bg=PALETTE["sidebar_bg"], fg=col,
                    font=("Helvetica", 8)
                ).pack(anchor=tk.W)
        else:
            tk.Label(
                self.sidebar, text="No prerequisites (foundation topic)",
                bg=PALETTE["sidebar_bg"], fg=PALETTE["text_dim"],
                font=("Helvetica", 8)
            ).pack(anchor=tk.W)

        self._divider()

        # ── Action area ──────────────────────────────────────────────────────
        if status == "locked":
            tk.Label(
                self.sidebar,
                text="⊘  This topic is locked because a prerequisite has "
                     "failed. Resolve the knowledge gap first.",
                bg=PALETTE["sidebar_bg"], fg="#ADB5BD",
                font=("Helvetica", 8), wraplength=270, justify=tk.LEFT
            ).pack(anchor=tk.W)
            return

        blocked = self.graph.any_parent_failed_or_locked(topic_id, self.statuses)
        if blocked:
            tk.Label(
                self.sidebar,
                text="✗  A prerequisite has failed. Resolve it before "
                     "attempting this topic.",
                bg=PALETTE["sidebar_bg"], fg="#DC3545",
                font=("Helvetica", 8), wraplength=270, justify=tk.LEFT
            ).pack(anchor=tk.W)
            return

        btn_text = "Retake Quiz" if status in ("passed", "failed") else "Start Quiz →"
        self._btn(btn_text, command=lambda: self._start_quiz(topic_id))

    def _go_to_navigator(self) -> None:
        """Deselect topic, show full graph, and return to navigator panel."""
        self.selected_topic = None
        self.subgraph_ids   = None
        self._draw_graph()
        self._show_navigator()

    # ══════════════════════════════════════════════════════════════════════════
    # Quiz flow
    # ══════════════════════════════════════════════════════════════════════════

    def _start_quiz(self, topic_id: str, remediation: bool = False) -> None:
        """Initialise a new QuizSession and show the first question."""
        self.quiz_session  = QuizSession(topic_id, self.graph.topics[topic_id])
        self.in_remediation = remediation
        self._show_question()

    def _show_question(self) -> None:
        """
        Render the current question with radio-button answer options.
        Implements the randomised question picker (SC5).
        """
        self._clear_sidebar()

        if self.quiz_session is None or self.quiz_session.is_finished():
            self._handle_quiz_complete()
            return

        q = self.quiz_session.current_question()

        # Header
        tk.Label(
            self.sidebar, text=self.quiz_session.topic_name,
            bg=PALETTE["sidebar_bg"], fg=PALETTE["text_main"],
            font=("Helvetica", 11, "bold"), wraplength=270
        ).pack(anchor=tk.W, pady=(0, 2))

        tk.Label(
            self.sidebar, text=self.quiz_session.progress_label(),
            bg=PALETTE["sidebar_bg"], fg=PALETTE["text_dim"],
            font=("Helvetica", 8)
        ).pack(anchor=tk.W, pady=(0, 10))

        # Question text
        tk.Label(
            self.sidebar, text=q["text"],
            bg=PALETTE["sidebar_bg"], fg=PALETTE["text_main"],
            font=("Helvetica", 9), wraplength=270, justify=tk.LEFT
        ).pack(anchor=tk.W, pady=(0, 10))

        # Answer options
        self._answer_var = tk.IntVar(value=-1)
        for i, option_text in enumerate(q["options"]):
            tk.Radiobutton(
                self.sidebar, text=option_text,
                variable=self._answer_var, value=i,
                bg=PALETTE["sidebar_bg"], fg=PALETTE["text_main"],
                selectcolor="#2A2A4E",
                font=("Helvetica", 9),
                wraplength=255, justify=tk.LEFT,
                anchor=tk.W, cursor="hand2",
                activebackground=PALETTE["sidebar_bg"]
            ).pack(anchor=tk.W, padx=4, pady=2)

        self._divider()

        self._btn("Submit Answer →", command=self._submit_answer)

        # Remediation context label
        if self.in_remediation:
            remaining = len(self.remediation_path) - self.remediation_index
            tk.Label(
                self.sidebar,
                text=f"Remediation – {remaining} topic(s) remaining",
                bg=PALETTE["sidebar_bg"], fg=PALETTE["orange"],
                font=("Helvetica", 7)
            ).pack(anchor=tk.W, pady=(6, 0))

    def _submit_answer(self) -> None:
        """Validate that an option was chosen, then record the answer."""
        if self._answer_var.get() == -1:
            messagebox.showwarning(
                "No Selection",
                "Please select an answer before submitting.",
                parent=self.root
            )
            return

        self.quiz_session.submit_answer(self._answer_var.get())

        if self.quiz_session.is_finished():
            self._handle_quiz_complete()
        else:
            self._show_question()

    # ── Quiz completion logic ─────────────────────────────────────────────────

    def _handle_quiz_complete(self) -> None:
        """
        Called when the last question of a quiz has been answered.
        Persists the result and branches into pass or fail handling.
        """
        session   = self.quiz_session
        topic_id  = session.topic_id
        passed    = session.passed()

        if passed:
            set_status(topic_id, "passed")
            self.statuses = get_all_progress()

            # Propagate unlock to children whose parents are now all passed.
            self.graph.unlock_available_children(topic_id, self.statuses)
            self.statuses = get_all_progress()

            if self.in_remediation:
                self._remediation_step_passed()
            else:
                self._show_result()

        else:
            set_status(topic_id, "failed")
            self.statuses = get_all_progress()

            if self.in_remediation:
                # Failed during remediation – must retry this step.
                self._show_result(remediation_retry=True)
            else:
                # First failure: lock descendants (SC8), diagnose root cause (SC6).
                self.graph.lock_descendants(topic_id)
                self.statuses = get_all_progress()
                self.original_failed_topic = topic_id
                self._diagnose_and_show_result()

        self._draw_graph(self.subgraph_ids)

    def _diagnose_and_show_result(self) -> None:
        """
        Run the knowledge-gap DFS to build the remediation path, then
        display the result panel with the diagnosis (SC6).
        """
        path = self.graph.find_root_cause_path(
            self.quiz_session.topic_id, self.statuses
        )
        self.remediation_path  = path
        self.remediation_index = 0
        self._show_result(show_diagnosis=True, diagnosis_path=path)

    # ── Remediation loop ──────────────────────────────────────────────────────

    def _begin_remediation(self) -> None:
        """
        Start the quiz loop by quizzing the root-cause topic (SC7).
        Unlocks the root-cause node so it is quizzable.
        """
        if not self.remediation_path:
            self._go_to_navigator()
            return
        root = self.remediation_path[0]
        self.remediation_index = 0
        # The root may currently be 'available' or 'failed'; ensure quizzable.
        current_status = self.statuses.get(root, {}).get("status")
        if current_status not in ("available", "failed"):
            set_status(root, "available")
            self.statuses = get_all_progress()
        self._draw_graph(self.subgraph_ids)
        self._start_quiz(root, remediation=True)

    def _remediation_step_passed(self) -> None:
        """
        Advance to the next topic in the remediation path after a pass.
        Implements SC7: guide the student back up the chain one topic at a time.
        """
        self.remediation_index += 1

        if self.remediation_index >= len(self.remediation_path):
            # Entire chain resolved.
            self.in_remediation = False
            self._show_result(remediation_complete=True)
            return

        next_topic = self.remediation_path[self.remediation_index]
        # Unlock the next topic before quizzing it.
        set_status(next_topic, "available")
        self.statuses = get_all_progress()
        self._draw_graph(self.subgraph_ids)
        self._start_quiz(next_topic, remediation=True)

    # ── Result panel ──────────────────────────────────────────────────────────

    def _show_result(
        self,
        show_diagnosis:     bool      = False,
        diagnosis_path:     list[str] = None,
        remediation_retry:  bool      = False,
        remediation_complete: bool    = False,
    ) -> None:
        """
        Render the quiz result panel.  Covers four outcome states:
          1. Normal pass
          2. Normal fail with diagnosis shown
          3. Fail during remediation (retry same topic)
          4. Full remediation chain completed
        """
        self._clear_sidebar()
        session = self.quiz_session
        correct, total = session.score()
        passed  = session.passed()

        res_col  = "#28A745" if passed else "#DC3545"
        res_text = "Quiz Passed!" if passed else "Quiz Failed"
        res_icon = "✓" if passed else "✗"

        tk.Label(
            self.sidebar, text=f"{res_icon}  {res_text}",
            bg=PALETTE["sidebar_bg"], fg=res_col,
            font=("Helvetica", 13, "bold")
        ).pack(anchor=tk.W, pady=(0, 2))

        tk.Label(
            self.sidebar, text=session.topic_name,
            bg=PALETTE["sidebar_bg"], fg=PALETTE["text_main"],
            font=("Helvetica", 10)
        ).pack(anchor=tk.W, pady=(0, 2))

        tk.Label(
            self.sidebar, text=f"Score: {correct} / {total}",
            bg=PALETTE["sidebar_bg"], fg=PALETTE["text_dim"],
            font=("Helvetica", 9)
        ).pack(anchor=tk.W, pady=(0, 10))

        # Per-question answer summary
        for i, (sel, corr, ok) in enumerate(session.answers):
            colour   = "#28A745" if ok else "#DC3545"
            icon_ans = "✓" if ok else "✗"
            q_short  = (session.questions[i]["text"][:45] + "…"
                        if len(session.questions[i]["text"]) > 45
                        else session.questions[i]["text"])
            tk.Label(
                self.sidebar, text=f"{icon_ans}  Q{i+1}: {q_short}",
                bg=PALETTE["sidebar_bg"], fg=colour,
                font=("Helvetica", 7), wraplength=270, justify=tk.LEFT
            ).pack(anchor=tk.W)
            if not ok:
                correct_text = session.questions[i]["options"][corr]
                tk.Label(
                    self.sidebar,
                    text=f"     Correct: {correct_text}",
                    bg=PALETTE["sidebar_bg"], fg="#28A745",
                    font=("Helvetica", 7), wraplength=270
                ).pack(anchor=tk.W)

        self._divider()

        # ── Branch on outcome ────────────────────────────────────────────────

        if remediation_complete:
            # SC7 loop fully satisfied.
            tk.Label(
                self.sidebar,
                text="🎉  All knowledge gaps resolved! You have completed "
                     "the full remediation chain.",
                bg=PALETTE["sidebar_bg"], fg="#28A745",
                font=("Helvetica", 9, "bold"), wraplength=270, justify=tk.LEFT
            ).pack(anchor=tk.W, pady=(0, 10))
            self._btn("Back to Navigator", command=self._go_to_navigator)

        elif show_diagnosis and diagnosis_path:
            # SC6: present the identified root cause.
            root_name = self.graph.topics[diagnosis_path[0]]
            tk.Label(
                self.sidebar,
                text="🔍  Knowledge gap identified:",
                bg=PALETTE["sidebar_bg"], fg=PALETTE["orange"],
                font=("Helvetica", 9, "bold")
            ).pack(anchor=tk.W)
            tk.Label(
                self.sidebar,
                text=f'Root cause: "{root_name}"',
                bg=PALETTE["sidebar_bg"], fg=PALETTE["orange"],
                font=("Helvetica", 8), wraplength=270
            ).pack(anchor=tk.W, pady=(1, 4))

            path_str = " → ".join(
                self.graph.topics[tid] for tid in diagnosis_path
            )
            tk.Label(
                self.sidebar,
                text=f"Remediation path:\n{path_str}",
                bg=PALETTE["sidebar_bg"], fg=PALETTE["text_dim"],
                font=("Helvetica", 7), wraplength=270, justify=tk.LEFT
            ).pack(anchor=tk.W, pady=(0, 8))

            self._btn(
                "Start Remediation →",
                command=self._begin_remediation,
                bg=PALETTE["orange"], fg="#1A1A2E"
            )

        elif remediation_retry:
            # Student failed during remediation – must retry.
            tk.Label(
                self.sidebar,
                text="You must pass this topic to continue. Please try again.",
                bg=PALETTE["sidebar_bg"], fg="#DC3545",
                font=("Helvetica", 8), wraplength=270
            ).pack(anchor=tk.W, pady=(0, 8))
            self._btn(
                "Retry Quiz →",
                command=lambda: self._start_quiz(
                    session.topic_id, remediation=True
                )
            )

        elif passed:
            # Normal pass – return to navigator.
            self._btn("Back to Navigator", command=self._go_to_navigator)

        else:
            # Fallback: failure outside of remediation with no path found.
            self._btn("Back to Navigator", command=self._go_to_navigator)

    # ══════════════════════════════════════════════════════════════════════════
    # Utility
    # ══════════════════════════════════════════════════════════════════════════

    def _reset_progress(self) -> None:
        """Wipe all progress after user confirmation."""
        if messagebox.askyesno(
            "Reset Progress",
            "Reset all progress to 'available'?\nThis cannot be undone.",
            parent=self.root
        ):
            reset_all_progress()
            self.statuses       = get_all_progress()
            self.selected_topic = None
            self.subgraph_ids   = None
            self._draw_graph()
            self._show_navigator()
