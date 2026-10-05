"""Plans: a target several steps away that every behavior then works toward.

Without a plan, a bot decides each purchase on its own: it settles only where
its roads already reach and builds a road only when it has nowhere to settle.
A Planner looks further. It weighs every city it could build, every spot it
could reach within a few roads, a development card, and a run at Longest Road,
and commits to the one with the best return for the cards still missing. The
plan then tells the rest of the bot what to do:

    step     what to build next ("road", "settlement", "city" or "dev")
    action   the exact move, such as the next road along the route
    cost     every card the whole plan still needs, roads included

Trading, discards, development cards and the robber all read ``cost``, so they
serve the plan too. The cost is published on ``game.goals`` for that purpose.
"""
from .bots import ADAPTIVE_V2_OPENING_PARAMS, spot_value
from .game import A_BUY, A_CITY, A_ROAD, A_SETTLE, KNIGHT
from .topology import EDGE_NODES, NODE_EDGES

CITY = (0, 0, 3, 2, 0)
SETTLEMENT = (1, 1, 0, 1, 1)
DEV = (0, 0, 1, 1, 1)


class Plan:
    __slots__ = ("step", "action", "cost", "target", "roads", "kind")

    def __init__(self, step, action, cost, target=-1, roads=0, kind=""):
        self.step = step
        self.action = action
        self.cost = cost
        self.target = target  # node of the settlement or city, -1 otherwise
        self.roads = roads  # roads still to build before the target
        self.kind = kind or step  # what the plan is for: city, settlement, dev, longest_road


class Planner:
    """Chooses the target with the best value for the cards still missing.

    reach       how many roads away a settlement spot may be
    city_value  worth of a city, per dice pip of the settlement it replaces
    dev_value   worth of a development card
    patience    cards of slack: higher favours bigger, slower targets
    strict      save for the plan and nothing else. By default a bot that
                cannot afford the plan's next step still buys whatever else
                it can afford, as a bot without a plan would

    Reading the opponents:
    contest     how much to discount a spot an opponent can reach first (0 to 1)
    block       bonus for a spot an opponent is about to reach, as a share of its value

    Multi-turn prizes:
    army_value  extra worth of a development card when Largest Army is close
    road_value  worth of taking Longest Road
    road_reach  how many roads short of Longest Road it may be and still go for it
    """

    def __init__(self, reach=2, city_value=3.0, dev_value=8.0, patience=2.0, strict=False,
                 contest=0.0, block=0.0, army_value=0.0, road_value=0.0, road_reach=2):
        self.strict = strict
        self.reach = reach
        self.city_value = city_value
        self.dev_value = dev_value
        self.patience = patience
        self.contest = contest
        self.block = block
        self.army_value = army_value
        self.road_value = road_value
        self.road_reach = road_reach

    def plan(self, game, p):
        hand = game.res[p]
        patience = self.patience
        best = None
        best_score = -1.0

        def consider(gain, cost, step, action, target=-1, roads=0, kind=""):
            nonlocal best, best_score
            missing = 0
            for r in range(5):
                if cost[r] > hand[r]:
                    missing += cost[r] - hand[r]
            score = gain / (missing + patience)
            if score > best_score:
                best_score = score
                best = Plan(step, action, cost, target, roads, kind)

        if game.cities_left[p]:
            pips = game.node_pips
            for node in game.settlements[p]:
                consider(self.city_value * pips[node], CITY, "city", (A_CITY << 8) | node, node)

        if game.settlements_left[p]:
            value = spot_value(game, ADAPTIVE_V2_OPENING_PARAMS, p)
            free = game._free_spot
            contest = self.contest
            block = self.block
            rivals = self._rival_distance(game, p) if (contest or block) else None
            for node, (roads, first_edge) in self._reachable(game, p, self.reach).items():
                if not free(node):
                    continue
                gain = value(node)
                if rivals is not None:
                    theirs = rivals.get(node)
                    if theirs is not None:
                        if theirs < roads:
                            gain *= 1.0 - contest  # they will probably get there first
                        elif theirs <= roads + 1:
                            gain *= 1.0 + block  # take it before they can
                if roads == 0:
                    consider(gain, SETTLEMENT, "settlement", (A_SETTLE << 8) | node, node)
                else:
                    cost = (1 + roads, 1 + roads, 0, 1, 1)
                    consider(gain, cost, "road", (A_ROAD << 8) | first_edge, node, roads, "settlement")

        if game.dev_deck:
            gain = self.dev_value
            if self.army_value and game.largest_army != p:
                holder = game.largest_army
                target = max(3, game.knights[holder] + 1) if holder >= 0 else 3
                held = game.dev_hand[p][KNIGHT] + game.dev_new[p][KNIGHT]
                need = target - game.knights[p] - held
                if need > 0:
                    gain += self.army_value / need
            consider(gain, DEV, "dev", A_BUY << 8)

        if self.road_value and game.longest_road != p and game.roads_left[p]:
            holder = game.longest_road
            target = max(5, game.road_len[holder] + 1) if holder >= 0 else 5
            need = target - game.road_len[p]
            if 0 < need <= self.road_reach and need <= game.roads_left[p]:
                edge = self._road_extension(game, p)
                if edge >= 0:
                    consider(self.road_value, (need, need, 0, 0, 0), "road", (A_ROAD << 8) | edge,
                             roads=need, kind="longest_road")

        return best

    @staticmethod
    def _reachable(game, p, reach):
        """{node: (roads needed, first road on the way)} within reach of p's network."""
        node_owner = game.node_owner
        edge_owner = game.edge_owner
        limit = min(reach, game.roads_left[p])
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

    def _rival_distance(self, game, p):
        """{node: fewest roads any opponent needs to reach it}, looking one road past our reach."""
        nearest = {}
        for q in range(game.n):
            if q != p:
                for node, (roads, _) in self._reachable(game, q, self.reach + 1).items():
                    if roads < nearest.get(node, 99):
                        nearest[node] = roads
        return nearest

    @staticmethod
    def _road_extension(game, p):
        """The road that lengthens p's longest road the most, or -1 if none does."""
        edge_owner = game.edge_owner
        touch = game.touch[p]
        best_edge = -1
        best_length = game.road_len[p]
        for e in game.road_spots(p):
            a, b = EDGE_NODES[e]
            added = [n for n in (a, b) if n not in touch]
            edge_owner[e] = p
            touch.update(added)
            length = game._longest_path(p)
            edge_owner[e] = -1
            touch.difference_update(added)
            if length > best_length:
                best_length, best_edge = length, e
        return best_edge


# Found by src.engine.plan_search (8 generations, 24 candidates, 3,000 games
# each): reach three roads and value expansion well above cities. Re-tested on
# 40,000 fresh games it won 28.5% from one seat against bots without a plan.
_TUNED = {"reach": 3, "city_value": 1.75, "dev_value": 0.3, "patience": 2.0}

PLAN = {
    # No plan: buy in the spending order, build roads only when stuck.
    "none": None,
    "tuned": Planner(**_TUNED),
    # Shorter and longer sight.
    "reach2": Planner(**dict(_TUNED, reach=2)),
    "reach4": Planner(**dict(_TUNED, reach=4)),
    # Saving for the plan and buying nothing else.
    "strict": Planner(**dict(_TUNED, strict=True)),
    # Reading the opponents: avoid races it would lose, or grab spots rivals are near.
    "contest": Planner(**dict(_TUNED, contest=0.5)),
    "block": Planner(**dict(_TUNED, block=0.3)),
    "contest_block": Planner(**dict(_TUNED, contest=0.5, block=0.3)),
    # Multi-turn prizes: Largest Army, Longest Road, or both.
    "army": Planner(**dict(_TUNED, army_value=20.0)),
    "road": Planner(**dict(_TUNED, road_value=30.0)),
    "prizes": Planner(**dict(_TUNED, army_value=20.0, road_value=30.0)),
}
