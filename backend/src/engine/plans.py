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

    Reading the opponents' intentions from the board:
    cutoff      bonus for taking the best spot within a rival's reach, as a share
                of the spot's value, scaled by how many points the rival shows
    cut_road    worth of settling where it breaks the Longest Road holder's road
                and costs them the card

    Closing out the game:
    endgame_at  from this many victory points on, stop weighing long-term value
                and take whatever gets to ten points with the fewest cards
                (0 switches this off)
    """

    def __init__(self, reach=2, city_value=3.0, dev_value=8.0, patience=2.0, strict=False,
                 contest=0.0, block=0.0, army_value=0.0, road_value=0.0, road_reach=2, endgame_at=0,
                 cutoff=0.0, cut_road=0.0):
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
        self.endgame_at = endgame_at
        self.cutoff = cutoff
        self.cut_road = cut_road

    def plan(self, game, p):
        hand = game.res[p]
        patience = self.patience
        best = None
        best_score = -1.0
        rush = bool(self.endgame_at) and game.victory_points(p) >= self.endgame_at

        def consider(gain, cost, step, action, target=-1, roads=0, kind="", points=1.0):
            nonlocal best, best_score
            missing = 0
            for r in range(5):
                if cost[r] > hand[r]:
                    missing += cost[r] - hand[r]
            # Near the end only points count, and the cheapest points count most.
            score = points / (missing + 0.5) if rush else gain / (missing + patience)
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
            cutoff = self.cutoff
            wanted = {}
            if cutoff:
                # The spot each opponent would most want next, judged from the
                # board as they see it, weighted by the points they show.
                for q in range(game.n):
                    if q != p and game.settlements_left[q]:
                        theirs = spot_value(game, ADAPTIVE_V2_OPENING_PARAMS, q)
                        spots = [n for n in self._reachable(game, q, 2) if free(n)]
                        if spots:
                            target = max(spots, key=theirs)
                            wanted[target] = max(wanted.get(target, 0.0), game.public_points(q) / 5.0)
            breaks = self._road_breaks(game, p) if self.cut_road else {}
            for node, (roads, first_edge) in self._reachable(game, p, self.reach).items():
                if not free(node):
                    continue
                gain = value(node)
                if node in wanted:
                    gain *= 1.0 + cutoff * wanted[node]
                if node in breaks:
                    gain += self.cut_road * breaks[node]
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
            consider(gain, DEV, "dev", A_BUY << 8, points=0.2)  # 5 of the 25 cards are a point

        if self.road_value and game.longest_road != p and game.roads_left[p]:
            holder = game.longest_road
            target = max(5, game.road_len[holder] + 1) if holder >= 0 else 5
            need = target - game.road_len[p]
            if 0 < need <= self.road_reach and need <= game.roads_left[p]:
                edge = self._road_extension(game, p)
                if edge >= 0:
                    consider(self.road_value, (need, need, 0, 0, 0), "road", (A_ROAD << 8) | edge,
                             roads=need, kind="longest_road", points=2.0)

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
    def _road_breaks(game, p):
        """{node: points swing} for spots where settling costs the holder Longest Road.

        The swing is 2 when the holder loses the card and 4 when p takes it over.
        """
        holder = game.longest_road
        if holder < 0 or holder == p:
            return {}
        node_owner = game.node_owner
        edge_owner = game.edge_owner
        lengths = game.road_len
        rest = max(lengths[q] for q in range(game.n) if q != holder)
        breaks = {}
        for node in game.touch[holder]:
            if node_owner[node] >= 0:
                continue
            if sum(1 for e, _ in NODE_EDGES[node] if edge_owner[e] == holder) < 2:
                continue  # the end of a road, so a building here cuts nothing
            node_owner[node] = p
            after = game._longest_path(holder)
            node_owner[node] = -1
            if after < 5 or after < rest:
                breaks[node] = 4.0 if (lengths[p] >= 5 and lengths[p] == rest and lengths[p] > after) else 2.0
        return breaks

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

_PRIZES_V2 = {"reach": 3, "city_value": 3.36, "dev_value": 3.0, "patience": 0.9, "army_value": 35.7,
              "road_value": 20.7, "road_reach": 2, "contest": 0.54, "block": 0.16}

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
    # Found by plan_search over all nine settings against three "prizes" bots
    # (6 generations, 20 candidates, 2,500 games each). Re-tested on 30,000
    # fresh games it won 29.5% from one seat. Against "prizes" it values
    # cities and Largest Army more, waits less, and avoids races it would lose.
    "prizes_v2": Planner(**_PRIZES_V2),
    # As prizes_v2, but from 7 or 8 points on it takes the cheapest route to ten.
    "endgame7": Planner(**dict(_PRIZES_V2, endgame_at=7)),
    "endgame8": Planner(**dict(_PRIZES_V2, endgame_at=8)),
    # Cutting opponents off: take the spot a rival most wants, break the
    # Longest Road holder's road, or both.
    "cutoff": Planner(**dict(_PRIZES_V2, cutoff=0.5)),
    "cut_road": Planner(**dict(_PRIZES_V2, cut_road=15.0)),
    "cutthroat": Planner(**dict(_PRIZES_V2, cutoff=0.5, cut_road=15.0)),
    # The two round 8 gains together; not yet tested as a pair.
    "endgame7_cutoff": Planner(**dict(_PRIZES_V2, endgame_at=7, cutoff=0.5)),
    # Found by plan_search over all twelve settings against a mixed table of
    # endgame7, prizes_v2, prizes and cutoff (6 generations, 20 candidates,
    # 2,000 games each). Re-tested on 20,000 fresh games it won 30.6% from one
    # seat. Not yet compared with the named plans on the same games, so it is
    # not the standard.
    "mixed_table": Planner(reach=3, city_value=2.11, dev_value=0.0, patience=0.94, army_value=30.75,
                           road_value=15.32, road_reach=3, contest=0.45, block=0.1, endgame_at=8,
                           cutoff=0.02, cut_road=5.32),
}
