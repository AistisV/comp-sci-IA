"""
graph.py — Module 2: Graph Logic

Implements the Topic and Graph classes from the UML class diagram
(Criterion C, Figure 3). The Graph stores the syllabus as a Directed
Acyclic Graph (DAG) using a custom adjacency list (Python dict), plus
a reverse adjacency list so parent look-ups are also O(1) rather than
requiring a full scan.

Algorithms implemented here (all DFS-based, per Criterion A/B):
  - detect_cycles      : Figure 8  (SC1  - ingestion validation)
  - can_start_quiz      : Topic Gatekeeper (SC4)
  - apply_lock          : Figure 10 (SC8 - recursive status lock)
  - evaluate_unlock     : Figure 11 (SC9 - status overwrite / unlock)
  - cascade_pass_upward : ancestor auto-pass on success (design extension,
                          see README / Criterion A addendum)
  - find_gap            : Figure 9  (SC6 - knowledge gap diagnosis)
  - get_subgraph        : Subgraph Extractor (SC3)

Design note (deviation from the original Figure 5 sketch): Figure 5's
flowchart shows topic *selection* itself being gated by is_available().
Success Criterion 4 as written is narrower than that — it only requires
the "Start Quiz" button to be disabled when a prerequisite is "Failed"
or "Locked". This implementation follows SC4: every topic can always be
selected and viewed (so its subgraph and status are visible at any
time), and gatekeeping applies only to whether the quiz can be started.
An "Untested" prerequisite does not block starting a quiz -- only a
"Failed" or "Locked" one does.

Design note (evaluate_unlock, deviation from the original Figure 11
sketch): Figure 11 releases a Locked child only once ALL of its
parents are "Passed" again. Combined with apply_lock() only ever
locking DESCENDANTS (never the failed topic itself, which is instead
explicitly set to "Failed" by the caller), a topic higher up that gets
reset to "Untested" by some other unlock elsewhere in the graph would
never satisfy "all parents Passed" -- so its Locked children could
stay locked forever even though nothing is actively broken about them
any more. To stay consistent with the SC4 gatekeeping rule above,
evaluate_unlock() here releases a Locked child as soon as NONE of its
parents are "Failed" or "Locked" (an "Untested" or "Passed" parent is
both fine), and recurses down the subtree so a whole locked branch is
re-evaluated in one pass rather than only the direct children.
"""

from __future__ import annotations


class Topic:
    """A single syllabus node. Mirrors the UML 'Topic' class exactly."""

    STATUS_UNTESTED = "Untested"
    STATUS_PASSED = "Passed"
    STATUS_FAILED = "Failed"
    STATUS_LOCKED = "Locked"

    def __init__(self, id: str, name: str, status: str = STATUS_UNTESTED):
        self.id = id
        self.name = name
        self.status = status

    def update_status(self, s: str) -> None:
        self.status = s

    def __repr__(self) -> str:
        return f"Topic({self.id!r}, status={self.status!r})"


class Graph:
    """
    Custom adjacency-list DAG.

    nodes:                {topic_id: Topic}
    adjacency_list:        {topic_id: [child_id, ...]}   parent -> children
    reverse_adjacency_list: {topic_id: [parent_id, ...]}  child  -> parents

    Both adjacency lists are maintained together so that get_children()
    and get_parents() are both O(1) dictionary look-ups (Criterion A:
    "Data Structures... for O(1) neighbour lookups").
    """

    def __init__(self):
        self.nodes: dict[str, Topic] = {}
        self.adjacency_list: dict[str, list[str]] = {}
        self.reverse_adjacency_list: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def add_topic(self, t: Topic) -> None:
        """Registers a topic node and ensures it has adjacency entries."""
        self.nodes[t.id] = t
        self.adjacency_list.setdefault(t.id, [])
        self.reverse_adjacency_list.setdefault(t.id, [])

    def add_edge(self, parent_id: str, child_id: str) -> None:
        """Adds a directed edge parent -> child (prerequisite -> topic)."""
        self.adjacency_list.setdefault(parent_id, [])
        self.reverse_adjacency_list.setdefault(child_id, [])
        if child_id not in self.adjacency_list[parent_id]:
            self.adjacency_list[parent_id].append(child_id)
        if parent_id not in self.reverse_adjacency_list[child_id]:
            self.reverse_adjacency_list[child_id].append(parent_id)

    # ------------------------------------------------------------------
    # Basic accessors
    # ------------------------------------------------------------------

    def get_parents(self, id: str) -> list[str]:
        return list(self.reverse_adjacency_list.get(id, []))

    def get_children(self, id: str) -> list[str]:
        return list(self.adjacency_list.get(id, []))

    def can_start_quiz(self, id: str) -> bool:
        """
        Topic Gatekeeper (SC4, exact wording): the "Start Quiz" button
        must be disabled if ANY direct prerequisite currently has status
        "Failed" or "Locked". An "Untested" prerequisite does NOT block
        starting the quiz -- a student is free to attempt a topic ahead
        of schedule. A topic with no prerequisites can always be quizzed.

        Note: this only governs the quiz button. Selecting/viewing a
        topic on the canvas or sidebar is never blocked (see module
        docstring) -- that is handled entirely by select_topic() in
        gui.py, which never consults this method.
        """
        for parent_id in self.get_parents(id):
            status = self.nodes[parent_id].status
            if status in (Topic.STATUS_FAILED, Topic.STATUS_LOCKED):
                return False
        return True

    # ------------------------------------------------------------------
    # SC1: Cycle detection (Figure 8)
    # ------------------------------------------------------------------

    def detect_cycles(self) -> bool:
        """
        Recursive DFS cycle detection across the whole graph.

        Uses a visited_set (nodes fully explored) and a recursion_stack
        (nodes on the current DFS path) exactly as drawn in Figure 8.
        Returns True the moment a back-edge (a neighbour already on the
        recursion stack) is found — i.e. a cycle exists.
        """
        visited_set: set[str] = set()

        def _dfs(node: str, recursion_stack: set[str]) -> bool:
            visited_set.add(node)
            recursion_stack.add(node)

            for neighbour in self.adjacency_list.get(node, []):
                if neighbour in recursion_stack:
                    return True
                if neighbour not in visited_set:
                    if _dfs(neighbour, recursion_stack):
                        return True

            recursion_stack.discard(node)
            return False

        for node_id in self.nodes:
            if node_id not in visited_set:
                if _dfs(node_id, set()):
                    return True
        return False

    # ------------------------------------------------------------------
    # SC6: Knowledge gap diagnosis (Figure 9)
    # ------------------------------------------------------------------

    def find_gap(self, current_topic: str, current_depth: int = 0):
        """
        DFS that walks upward through parents to find the prerequisite
        that should be re-tested next.

        Mirrors Figure 9's original idea (dive through the chain of
        genuinely unpassed prerequisites to the earliest/deepest one),
        with one deliberate extension for the top-level call only (see
        the module docstring): if the ORIGINALLY failed topic's direct
        parents are all already "Passed", the original sketch treated
        the failed topic itself as the root cause and stopped there. A
        Pass is a record of a past result, not a permanent guarantee of
        retention, so this build instead treats the nearest Passed
        parent as worth re-confirming -- but only ONE level up per
        failure, not the whole chain in one jump. If that re-test also
        fails, gui.App.handle_failure calls find_gap again from that
        parent (a fresh, independent diagnosis), so a persistently
        broken chain is walked back one link at a time, only as far as
        each new failure warrants; a re-test that instead passes lets
        the recovery stack walk back down immediately without ever
        reaching further up the chain (see quiz.py's recovery stack /
        SC7).

        Behaviour, precisely:
          - no parents at all -> current_topic IS the root cause (base
            case: nothing further upstream exists)
          - some parent(s) genuinely unpassed (Failed/Locked/Untested)
            -> dive into the DEEPEST such chain exactly as Figure 9
            describes, ignoring any Passed sibling parents (a known,
            already-identified gap is chased to its own origin before
            anything merely-Passed is reconsidered)
          - every parent already "Passed", but this call is examining
            the ORIGINALLY failed topic (current_depth == 0) -> don't
            stop here; return one of its Passed parents as the next
            topic to re-confirm (depth + 1)
          - every parent already "Passed", but this call was reached
            by diving into an already-identified unpassed chain
            (current_depth > 0) -> that unpassed chain has bottomed
            out; current_topic itself is the diagnosis target -- do
            NOT reach further past it into Passed territory within
            this same pass (that already-found gap is the one worth
            fixing right now)

        Returns: (root_cause_id: str, depth: int)
        """
        parents = self.get_parents(current_topic)

        if not parents:
            return current_topic, current_depth

        unpassed_list = [
            p for p in parents if self.nodes[p].status != Topic.STATUS_PASSED
        ]

        if unpassed_list:
            max_depth = -1
            deepest_node = None
            for parent in unpassed_list:
                found_node, found_depth = self.find_gap(parent, current_depth + 1)
                if found_depth > max_depth:
                    max_depth = found_depth
                    deepest_node = found_node
            return deepest_node, max_depth

        if current_depth == 0:
            # Top-level call, every direct parent already Passed: don't
            # trust it forever -- re-confirm the nearest one, one level
            # only (see docstring above).
            return parents[0], current_depth + 1

        # Reached via a genuinely-unpassed chain that has now bottomed
        # out at a Passed parent set: stop here, this IS the gap.
        return current_topic, current_depth

    # ------------------------------------------------------------------
    # SC8: Recursive status lock (Figure 10)
    # ------------------------------------------------------------------

    def apply_lock(self, current_topic: str, locked_set: set, is_first_call: bool = True):
        """
        Recursively marks every descendant of current_topic as "Locked"
        (in memory), collecting affected ids into locked_set. On the
        top-level call only, performs a single batch write so that the
        database is touched once rather than once per node (Figure 10's
        note about optimising performance, SC8).

        A descendant that is already "Locked" is left alone, on the
        existing invariant that its own descendants were already locked
        whenever it first became Locked -- recursing into it again would
        be redundant. The same now applies to a descendant that is
        already "Failed": that status is a specific, genuine attempt
        result (more informative than the generic "Locked"), and by the
        same invariant, failing it already triggered its own apply_lock
        call that locked everything beneath it. Overwriting a Failed
        topic to Locked here would silently discard that attempt record
        -- for instance while it is still sitting on the recovery stack
        awaiting a re-test (SC7) -- purely because some unrelated
        ancestor also failed in the meantime, so both cases are skipped
        identically.

        Returns the locked_set of topic ids that were newly locked.
        """
        for child_id in self.get_children(current_topic):
            child = self.nodes[child_id]
            already_settled = child.status in (Topic.STATUS_LOCKED, Topic.STATUS_FAILED)
            if child_id not in locked_set and not already_settled:
                locked_set.add(child_id)
                child.update_status(Topic.STATUS_LOCKED)
                self.apply_lock(child_id, locked_set, is_first_call=False)

        if is_first_call and locked_set:
            # Caller (DatabaseManager) performs the batch SQL UPDATE.
            pass

        return locked_set

    # ------------------------------------------------------------------
    # SC9: Status overwrite / unlock (Figure 11)
    # ------------------------------------------------------------------

    def evaluate_unlock(self, topic_id: str) -> list[str]:
        """
        Called after topic_id's status changes (typically to Passed, but
        also correctly handles a topic settling at Untested). Walks its
        children and, for each Locked child whose parents are no longer
        Failed or Locked, resets that child to "Untested" -- then
        recurses into that child so a whole previously-locked branch is
        re-evaluated in one pass (see the module docstring's note on why
        this differs from the original Figure 11 sketch).

        A child that is already Passed, Failed, or Untested is left
        alone: this method only ever releases a Locked node, it never
        overwrites a genuine attempt result.

        Returns the list of topic ids that were unlocked, so the caller
        can persist each change and refresh the UI.
        """
        unlocked = []
        for child_id in self.get_children(topic_id):
            child = self.nodes[child_id]
            if child.status != Topic.STATUS_LOCKED:
                continue
            parent_ids = self.get_parents(child_id)
            still_blocked = any(
                self.nodes[p].status in (Topic.STATUS_FAILED, Topic.STATUS_LOCKED)
                for p in parent_ids
            )
            if not still_blocked:
                child.update_status(Topic.STATUS_UNTESTED)
                unlocked.append(child_id)
                unlocked.extend(self.evaluate_unlock(child_id))
        return unlocked

    def reconcile_locks(self) -> list[str]:
        """
        Self-healing sweep of the WHOLE graph: releases every Locked
        topic that no longer has a Failed/Locked parent, regardless of
        how it got into that state.

        This exists as a safety net alongside evaluate_unlock(). A save
        file created before the evaluate_unlock() fix described in the
        module docstring can have topics that are stuck "Locked" with
        no Failed topic anywhere upstream of them any more -- nothing
        in a normal running session would ever call evaluate_unlock()
        on exactly the right node to notice this, since the node that
        originally failed may have long since been reset to "Untested"
        by an earlier, buggier unlock. Calling this once after loading
        the graph (see main.py) guarantees the displayed state is
        always consistent with the current Failed/Locked topics, no
        matter what sequence of past events produced the save file.

        Runs evaluate_unlock() from every node in the graph -- not just
        ones that are themselves Failed/Locked, since evaluate_unlock's
        check is about a node's CHILDREN, so the node that needs
        sweeping from is the (possibly perfectly fine) parent of a
        stuck Locked child, not the stuck child itself. Repeats until a
        full pass makes no further changes, since releasing one topic
        can make its own children newly releasable.

        Returns the list of topic ids that were unlocked, so the
        caller can persist each change and refresh the UI.
        """
        unlocked_total: list[str] = []
        while True:
            unlocked_this_pass: list[str] = []
            for tid in list(self.nodes.keys()):
                unlocked_this_pass.extend(self.evaluate_unlock(tid))
            if not unlocked_this_pass:
                break
            unlocked_total.extend(unlocked_this_pass)
        return unlocked_total

    # ------------------------------------------------------------------
    # Design extension: upward cascade on pass
    # ------------------------------------------------------------------

    def cascade_pass_upward(self, passed_topic: str) -> list[str]:
        """
        When a topic is passed, every one of its ancestors (direct and
        indirect prerequisites) is also marked "Passed" if not already,
        on the reasoning that passing an advanced topic demonstrates
        mastery of everything it depends on. This is a deliberate
        extension beyond the original flowcharts (which only propagate
        status downward via apply_lock/evaluate_unlock) -- see the
        module docstring and README.

        Returns the list of ancestor topic ids that were newly marked
        Passed, so the caller can persist each one and refresh the UI.
        """
        newly_passed = []
        visited: set[str] = set()

        def _walk(node_id: str):
            for parent_id in self.get_parents(node_id):
                if parent_id in visited:
                    continue
                visited.add(parent_id)
                parent = self.nodes[parent_id]
                if parent.status != Topic.STATUS_PASSED:
                    parent.update_status(Topic.STATUS_PASSED)
                    newly_passed.append(parent_id)
                _walk(parent_id)

        _walk(passed_topic)
        return newly_passed

    # ------------------------------------------------------------------
    # SC3: Subgraph extraction
    # ------------------------------------------------------------------

    def get_subgraph(self, topic_id: str) -> tuple[set[str], set[tuple[str, str]]]:
        """
        Returns (node_ids, edges) containing topic_id and every one of
        its ancestors (direct and indirect prerequisites), plus the
        edges that connect them — used to render the filtered canvas
        view in Figure 13 when a topic is selected in the sidebar.
        """
        visited: set[str] = set()
        edges: set[tuple[str, str]] = set()

        def _walk(node: str):
            if node in visited:
                return
            visited.add(node)
            for parent_id in self.get_parents(node):
                edges.add((parent_id, node))
                _walk(parent_id)

        _walk(topic_id)
        return visited, edges
