"""Fixed geometry of the classic 19-hex board, computed once at import.

Hexes, nodes (corners) and edges are plain integer ids so the game state can
live in flat lists. Hex ids follow the same order as ``src.board``.
"""
import math

# (row, hex count, starting column) for the 3-4-5-4-3 layout, as in src.board
_ROWS = [(0, 3, 1), (1, 4, 0), (2, 5, 0), (3, 4, 0), (4, 3, 1)]

NUM_HEXES = 19
NUM_NODES = 54
NUM_EDGES = 72


def _build():
    centers = []
    for row, count, start in _ROWS:
        for col in range(start, start + count):
            q = col - (row - (row & 1)) // 2
            centers.append((math.sqrt(3) * (q + row / 2), 1.5 * row))

    node_ids = {}
    node_xy = []
    edge_ids = {}
    edge_nodes = []
    edge_hex_count = []
    hex_nodes = []

    for cx, cy in centers:
        corners = []
        for i in range(6):
            angle = math.pi / 3 * i - math.pi / 2
            x, y = cx + math.cos(angle), cy + math.sin(angle)
            key = (round(x, 3), round(y, 3))
            if key not in node_ids:
                node_ids[key] = len(node_ids)
                node_xy.append((x, y))
            corners.append(node_ids[key])
        hex_nodes.append(tuple(corners))
        for i in range(6):
            a, b = corners[i], corners[(i + 1) % 6]
            key = (min(a, b), max(a, b))
            if key not in edge_ids:
                edge_ids[key] = len(edge_ids)
                edge_nodes.append(key)
                edge_hex_count.append(0)
            edge_hex_count[edge_ids[key]] += 1

    n_nodes = len(node_ids)
    node_edges = [[] for _ in range(n_nodes)]
    node_neighbors = [[] for _ in range(n_nodes)]
    for e, (a, b) in enumerate(edge_nodes):
        node_edges[a].append((e, b))
        node_edges[b].append((e, a))
        node_neighbors[a].append(b)
        node_neighbors[b].append(a)

    node_hexes = [[] for _ in range(n_nodes)]
    for h, nodes in enumerate(hex_nodes):
        for n in nodes:
            node_hexes[n].append(h)

    # Coastal edges border exactly one hex. Walk them in order around the
    # board and place the nine ports with the 3-3-4 spacing of the real board.
    mid_x = sum(x for x, _ in centers) / len(centers)
    mid_y = sum(y for _, y in centers) / len(centers)

    def angle_of(e):
        a, b = edge_nodes[e]
        x = (node_xy[a][0] + node_xy[b][0]) / 2 - mid_x
        y = (node_xy[a][1] + node_xy[b][1]) / 2 - mid_y
        return math.atan2(y, x)

    coastal = sorted((e for e, c in enumerate(edge_hex_count) if c == 1), key=angle_of)
    port_edges = tuple(coastal[i] for i in (0, 3, 6, 10, 13, 16, 20, 23, 26))

    return (
        tuple(hex_nodes),
        tuple(edge_nodes),
        tuple(tuple(x) for x in node_edges),
        tuple(tuple(x) for x in node_neighbors),
        tuple(tuple(x) for x in node_hexes),
        tuple(coastal),
        port_edges,
    )


(HEX_NODES, EDGE_NODES, NODE_EDGES, NODE_NEIGHBORS, NODE_HEXES, COASTAL_EDGES, PORT_EDGES) = _build()

assert len(HEX_NODES) == NUM_HEXES
assert len(NODE_EDGES) == NUM_NODES
assert len(EDGE_NODES) == NUM_EDGES
