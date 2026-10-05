"""Plans: a target several steps away that every behavior then works toward.

Without a plan, a bot decides each purchase on its own: it settles only where
its roads already reach and builds a road only when it has nowhere to settle.
A Planner looks further. It weighs every city it could build, every spot it
could reach within a few roads, and a development card, and commits to the one
with the best return for the cards still missing. The plan then tells the rest
of the bot what to do:

    step     what to build next ("road", "settlement", "city" or "dev")
    action   the exact move, such as the next road along the route
    cost     every card the whole plan still needs, roads included

Trading, discards and development cards all read ``cost``, so they serve the
plan too. The cost is published on ``game.goals`` for that purpose.
"""
from .bots import ADAPTIVE_V2_OPENING_PARAMS, spot_value
from .game import A_BUY, A_CITY, A_ROAD, A_SETTLE
from .topology import NODE_EDGES

CITY = (0, 0, 3, 2, 0)
SETTLEMENT = (1, 1, 0, 1, 1)
DEV = (0, 0, 1, 1, 1)


class Plan:
    __slots__ = ("step", "action", "cost", "target", "roads")

    def __init__(self, step, action, cost, target=-1, roads=0):
        self.step = step
        self.action = action
        self.cost = cost
        self.target = target  # node of the settlement or city, -1 for a card
        self.roads = roads  # roads still to build before the target


class Planner:
    """Chooses the target with the best value for the cards still missing.

    reach       how many roads away a settlement spot may be
    city_value  worth of a city, per dice pip of the settlement it replaces
    dev_value   worth of a development card
    patience    cards of slack: higher favours bigger, slower targets
    strict      save for the plan and nothing else. By default a bot that
                cannot afford the plan's next step still buys whatever else
                it can afford, as a bot without a plan would
    """

    def __init__(self, reach=2, city_value=3.0, dev_value=8.0, patience=2.0, strict=False):
        self.strict = strict
        self.reach = reach
        self.city_value = city_value
        self.dev_value = dev_value
        self.patience = patience

    def plan(self, game, p):
        hand = game.res[p]
        patience = self.patience
        best = None
        best_score = -1.0

        def consider(gain, cost, step, action, target=-1, roads=0):
            nonlocal best, best_score
            missing = 0
            for r in range(5):
                if cost[r] > hand[r]:
                    missing += cost[r] - hand[r]
            score = gain / (missing + patience)
            if score > best_score:
                best_score = score
                best = Plan(step, action, cost, target, roads)

        if game.cities_left[p]:
            pips = game.node_pips
            for node in game.settlements[p]:
                consider(self.city_value * pips[node], CITY, "city", (A_CITY << 8) | node, node)

        if game.settlements_left[p]:
            value = spot_value(game, ADAPTIVE_V2_OPENING_PARAMS, p)
            free = game._free_spot
            for node, (roads, first_edge) in self._reachable(game, p).items():
                if not free(node):
                    continue
                if roads == 0:
                    consider(value(node), SETTLEMENT, "settlement", (A_SETTLE << 8) | node, node)
                else:
                    cost = (1 + roads, 1 + roads, 0, 1, 1)
                    consider(value(node), cost, "road", (A_ROAD << 8) | first_edge, node, roads)

        if game.dev_deck:
            consider(self.dev_value, DEV, "dev", A_BUY << 8)

        return best

    def _reachable(self, game, p):
        """{node: (roads needed, first road on the way)} within reach of p's network."""
        node_owner = game.node_owner
        edge_owner = game.edge_owner
        limit = min(self.reach, game.roads_left[p])
        seen = {}
        frontier = []
        for node in game.touch[p]:
            if node_owner[node] in (-1, p):  # an opponent's building blocks the way
                seen[node] = (0, -1)
                frontier.append(node)
        for depth in range(1, limit + 1):
            following = []
            for node in frontier:
                first = seen[node][1]
                for e, nxt in NODE_EDGES[node]:
                    if edge_owner[e] < 0 and nxt not in seen and node_owner[nxt] in (-1, p):
                        seen[nxt] = (depth, e if depth == 1 else first)
                        following.append(nxt)
            frontier = following
        return seen


PLAN = {
    # No plan: buy in the spending order, build roads only when stuck.
    "none": None,
    # Plan toward spots up to one, two or three roads away.
    "reach1": Planner(reach=1),
    "reach2": Planner(reach=2),
    "reach3": Planner(reach=3),
    # Two roads of reach, leaning toward cities or toward expansion.
    "reach2_cities": Planner(reach=2, city_value=4.5),
    "reach2_expand": Planner(reach=2, city_value=2.0),
    # Two roads of reach, willing to wait longer for a bigger target.
    "reach2_patient": Planner(reach=2, patience=4.0),
    # Two roads of reach, valuing development cards more.
    "reach2_cards": Planner(reach=2, dev_value=14.0),
    # Two roads of reach, saving for the plan and buying nothing else.
    "reach2_strict": Planner(reach=2, strict=True),
    # Found by src.engine.plan_search (8 generations, 24 candidates, 3,000
    # games each): reach three roads and value expansion well above cities.
    # Re-tested on 40,000 fresh games it won 28.5% from one seat.
    "tuned": Planner(reach=3, city_value=1.75, dev_value=0.3, patience=2.0),
}
