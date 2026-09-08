"""
layout.py — layered graph layout for the canvas, fitted to the visible
area (no scrolling) and centred both horizontally and vertically, so
the rendering matches the single-screen mockups (Figures 12-16).

Not part of the UML (it's a rendering helper for App.render_graph),
kept separate so gui.py stays focused on widgets/events. Positions
each topic by its longest-path depth from a root (topological
layering), then spaces nodes evenly within each layer.
"""

from __future__ import annotations

MARGIN_Y = 55
# Horizontal margin must clear half a node's width (see gui.NODE_W) so
# the leftmost/rightmost ovals are never clipped by the canvas edge.
MARGIN_X = 100
# Minimum centre-to-centre gap between nodes in the same layer, wide
# enough that a node's oval (gui.NODE_W) never touches its neighbour's,
# and diagonal edges from other layers pass clearly between them
# rather than clipping through a label.
MIN_NODE_GAP_X = 190


def calculate_layout(node_ids, graph, canvas_w=800, canvas_h=600):
    """
    Returns {topic_id: (x, y)} for every id in node_ids, arranged in
    layers by longest-path depth (so a topic always sits below every
    one of its prerequisites), scaled and centred to fit exactly
    within (canvas_w, canvas_h).
    """
    node_ids = list(node_ids)
    if not node_ids:
        return {}

    depth: dict[str, int] = {}

    def compute_depth(node):
        if node in depth:
            return depth[node]
        parents = [p for p in graph.get_parents(node) if p in node_ids]
        if not parents:
            depth[node] = 0
        else:
            depth[node] = 1 + max(compute_depth(p) for p in parents)
        return depth[node]

    for n in node_ids:
        compute_depth(n)

    layers: dict[int, list[str]] = {}
    for n in node_ids:
        layers.setdefault(depth[n], []).append(n)
    for ids in layers.values():
        ids.sort()

    num_layers = max(layers.keys()) + 1
    usable_w = max(canvas_w - 2 * MARGIN_X, 100)
    usable_h = max(canvas_h - 2 * MARGIN_Y, 100)

    # Vertical spacing: evenly distribute layers within usable height.
    if num_layers == 1:
        layer_y = {0: canvas_h / 2}
    else:
        step_y = usable_h / (num_layers - 1)
        layer_y = {d: MARGIN_Y + d * step_y for d in range(num_layers)}

    positions = {}
    for d, ids in layers.items():
        n = len(ids)
        if n == 1:
            xs = [canvas_w / 2]
        else:
            # Prefer even spacing across the usable width, but never
            # closer than MIN_NODE_GAP_X -- if that would overflow the
            # canvas, the row simply grows wider than canvas_w rather
            # than letting nodes crowd/overlap (the row is then
            # re-centred on canvas_w, so it grows equally on both sides).
            step_x = max(usable_w / (n - 1), MIN_NODE_GAP_X)
            row_width = step_x * (n - 1)
            row_start = (canvas_w - row_width) / 2
            xs = [row_start + i * step_x for i in range(n)]
        for node_id, x in zip(ids, xs):
            positions[node_id] = (x, layer_y[d])

    return positions
