"""
graph.py
--------
In-memory graph representation and all graph algorithms for the
IB Physics Knowledge Navigator.

The graph is a Directed Acyclic Graph (DAG) stored as two adjacency
lists (children and parents), loaded once from the database at startup.

Algorithms implemented here:
  1. DFS cycle detection     – validates the loaded graph
  2. get_ancestors           – subgraph extraction (SC3)
  3. get_descendants         – recursive locking (SC8)
  4. lock_descendants        – mark child chain as locked (SC8)
  5. unlock_available_children – propagate unlock after a topic passes
  6. find_root_cause_path    – knowledge-gap DFS diagnosis (SC6, SC7)
  7. topological_sort        – Kahn's algorithm for layer ordering
  8. compute_layout          – assigns (layer, y-offset) for drawing
"""

from collections import defaultdict, deque
from database import get_all_topics, get_all_edges, set_status


class PhysicsGraph:
    """
    Adjacency-list representation of the syllabus DAG.

    Attributes
    ----------
    topics   : dict[str, str]          topic_id → display name
    children : dict[str, list[str]]    topic_id → [child_ids]   (forward)
    parents  : dict[str, list[str]]    topic_id → [parent_ids]  (backward)
    """

    def __init__(self) -> None:
        self.topics:   dict[str, str]        = {}
        self.children: dict[str, list[str]]  = defaultdict(list)
        self.parents:  dict[str, list[str]]  = defaultdict(list)
        self._load()

    # ── Loading ────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Populate adjacency lists from the database."""
        for row in get_all_topics():
            tid = row["id"]
            self.topics[tid]   = row["name"]
            self.children[tid] = self.children[tid]   # ensure key exists
            self.parents[tid]  = self.parents[tid]

        for (from_id, to_id) in get_all_edges():
            self.children[from_id].append(to_id)
            self.parents[to_id].append(from_id)

    def get_edges(self) -> list[tuple[str, str]]:
        """Return every directed edge as (from_id, to_id)."""
        return [
            (from_id, child)
            for from_id, children in self.children.items()
            for child in children
        ]

    # ── Algorithm 1: DFS Cycle Detection ─────────────────────────────────────
    # Used during startup (SC1) to guarantee the loaded graph is a valid DAG.
    # Uses three-colour DFS:
    #   WHITE (0) = not yet visited
    #   GREY  (1) = currently on the recursion stack
    #   BLACK (2) = fully processed
    # A back edge (reaching a GREY node) proves a cycle exists.

    def dfs_cycle_detect(self) -> bool:
        """
        Return True if the graph contains at least one cycle.
        A well-formed syllabus file should always return False.
        """
        WHITE, GREY, BLACK = 0, 1, 2
        colour = {tid: WHITE for tid in self.topics}

        def _visit(node: str) -> bool:
            colour[node] = GREY                        # mark as in-stack
            for child in self.children[node]:
                if colour[child] == GREY:
                    return True                        # back edge → cycle
                if colour[child] == WHITE and _visit(child):
                    return True
            colour[node] = BLACK                       # fully explored
            return False

        for tid in self.topics:
            if colour[tid] == WHITE:
                if _visit(tid):
                    return True
        return False

    # ── Algorithm 2: Ancestor Traversal (Subgraph Extraction) ─────────────────
    # Drives SC3: when a topic is selected, only show it and its prerequisites.

    def get_ancestors(self, topic_id: str) -> set[str]:
        """
        Return the set of all ancestors of topic_id (inclusive).
        DFS upward through parent links.
        """
        visited: set[str] = set()

        def _dfs(tid: str) -> None:
            if tid in visited:
                return
            visited.add(tid)
            for parent in self.parents[tid]:
                _dfs(parent)

        _dfs(topic_id)
        return visited

    # ── Algorithm 3 & 4: Descendant Traversal & Recursive Locking ─────────────
    # Drives SC8: failing a topic recursively marks all dependent children
    # as 'locked', preventing them from being quizzed.

    def get_descendants(self, topic_id: str) -> set[str]:
        """
        Return all descendants of topic_id (not including itself).
        DFS downward through child links.
        """
        visited: set[str] = set()

        def _dfs(tid: str) -> None:
            for child in self.children[tid]:
                if child not in visited:
                    visited.add(child)
                    _dfs(child)

        _dfs(topic_id)
        return visited

    def lock_descendants(self, topic_id: str) -> None:
        """
        Mark every descendant of topic_id as 'locked' in the database.
        Called immediately after a quiz failure (SC8).
        """
        for desc in self.get_descendants(topic_id):
            set_status(desc, "locked")

    # ── Algorithm 5: Propagate Unlock ─────────────────────────────────────────
    # When a topic is passed, its direct children may become available again
    # IF all of their other prerequisites are also passed.

    def unlock_available_children(
        self, topic_id: str, statuses: dict[str, dict]
    ) -> None:
        """
        For each direct child of topic_id that is currently 'locked',
        check whether all of its parents are now 'passed'.
        If so, promote it back to 'available'.
        """
        for child in self.children[topic_id]:
            if statuses.get(child, {}).get("status") == "locked":
                all_parents_passed = all(
                    statuses.get(p, {}).get("status") == "passed"
                    for p in self.parents[child]
                )
                if all_parents_passed:
                    set_status(child, "available")

    # ── Algorithm 6: Knowledge-Gap DFS (Root-Cause Diagnosis) ─────────────────
    # Drives SC6 & SC7.
    #
    # When a topic is failed, this DFS traverses *upward* through parents,
    # following the first branch that contains a non-passed node, until it
    # reaches a node with no unresolved ancestors.  That deepest node is the
    # root cause.  The return value is the full remediation path:
    #   [root_cause, ..., originally_failed_topic]

    def find_root_cause_path(
        self, topic_id: str, statuses: dict[str, dict]
    ) -> list[str]:
        """
        DFS upward from topic_id to find the earliest unresolved prerequisite.

        Parameters
        ----------
        topic_id : str
            The topic the student just failed.
        statuses : dict
            Current progress snapshot from the database.

        Returns
        -------
        list[str]
            Ordered remediation path: path[0] is the root cause,
            path[-1] is topic_id (the originally failed topic).
        """
        path:    list[str] = []
        visited: set[str]  = set()

        def _dfs(tid: str) -> bool:
            """
            Recursively search parents for an unresolved root.
            Returns True once the root is found and the path is built.
            """
            if tid in visited:
                return False
            visited.add(tid)

            # Try each unresolved parent before claiming this node is root.
            for parent in self.parents[tid]:
                parent_status = statuses.get(parent, {}).get("status", "available")
                if parent_status != "passed":       # unresolved prerequisite
                    if _dfs(parent):
                        path.append(tid)            # append on the way back up
                        return True

            # No unresolved parents found → this node is the root cause.
            path.append(tid)
            return True

        _dfs(topic_id)
        return path   # path[0] = root cause, path[-1] = original topic

    # ── Algorithm 7: Topological Sort (Kahn's Algorithm) ──────────────────────
    # Used both for the layered layout and for ordering the navigator list.

    def topological_sort(self) -> list[str]:
        """
        Return a topologically ordered list of all topic IDs using
        Kahn's algorithm (BFS on in-degree).
        """
        in_degree: dict[str, int] = {tid: 0 for tid in self.topics}
        for tid in self.topics:
            for child in self.children[tid]:
                in_degree[child] += 1

        queue = deque(tid for tid in self.topics if in_degree[tid] == 0)
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for child in self.children[node]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        return order

    # ── Algorithm 8: Layered Layout ───────────────────────────────────────────
    # Assigns a (layer, y_offset) pair to each node for the canvas renderer.
    # Layer = longest prerequisite chain length from any root.

    def compute_layout(
        self, subgraph_ids: set[str] | None = None
    ) -> dict[str, tuple[float, float]]:
        """
        Compute relative (x, y) positions for graph drawing.

        x corresponds to the topological layer (prerequisite depth).
        y is the vertical position within that layer.

        Parameters
        ----------
        subgraph_ids : set[str] or None
            If provided, only lay out these nodes (subgraph mode).
            Edges between nodes outside the set are ignored.

        Returns
        -------
        dict mapping topic_id → (x, y) in abstract units
        """
        nodes = subgraph_ids if subgraph_ids else set(self.topics.keys())

        # Assign each node a layer = max depth from any root in the subgraph.
        layer: dict[str, int] = {tid: 0 for tid in nodes}
        for tid in self.topological_sort():
            if tid not in nodes:
                continue
            for child in self.children[tid]:
                if child in nodes:
                    layer[child] = max(layer[child], layer[tid] + 1)

        # Group nodes by layer.
        by_layer: dict[int, list[str]] = defaultdict(list)
        for tid in nodes:
            by_layer[layer[tid]].append(tid)

        # Sort within each layer for a deterministic, readable layout.
        for lyr in by_layer:
            by_layer[lyr].sort()

        # Convert to (x, y) with y centred within each column.
        positions: dict[str, tuple[float, float]] = {}
        for lyr, tids in by_layer.items():
            count = len(tids)
            for i, tid in enumerate(tids):
                x = float(lyr)
                y = float(i) - (count - 1) / 2.0
                positions[tid] = (x, y)

        return positions

    # ── Gatekeeping helpers ────────────────────────────────────────────────────

    def any_parent_failed_or_locked(
        self, topic_id: str, statuses: dict[str, dict]
    ) -> bool:
        """
        Return True if any direct prerequisite is 'failed' or 'locked'.
        Used for topic gatekeeping (SC4).
        """
        for parent in self.parents[topic_id]:
            s = statuses.get(parent, {}).get("status", "available")
            if s in ("failed", "locked"):
                return True
        return False
