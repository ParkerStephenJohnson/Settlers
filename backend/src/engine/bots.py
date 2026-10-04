"""Computer players. A bot is anything with ``choose(game, actions) -> action``."""
from .game import (
    A_BUY,
    A_CITY,
    A_KNIGHT,
    A_MONOPOLY,
    A_ROAD,
    A_ROAD_BUILDING,
    A_SETTLE,
    A_TRADE,
    A_YEAR_OF_PLENTY,
    DISCARD,
    MAIN,
    PIPS,
    ROBBER,
    ROLL,
    SETUP_ROAD,
    SETUP_SETTLE,
    TRADE_PICK,
    TRADE_RESPONSE,

)
from .topology import EDGE_NODES, HEX_NODES, NODE_HEXES, NODE_NEIGHBORS

_CITY_COST = (0, 0, 3, 2, 0)
_SETTLEMENT_COST = (1, 1, 0, 1, 1)
_DEV_COST = (0, 0, 1, 1, 1)


class RandomBot:
    """Pure chance: every decision is a uniform random pick among what the rules allow.

    On its turn it treats "propose a trade" as one more option alongside its
    other legal actions. A proposal is a random bundle of its own cards for a
    random bundle of one opponent's cards, of any size. It accepts or refuses
    other players' offers on a coin flip.
    """

    lists_offers = False  # it builds its own offers

    def choose(self, game, actions):
        rng = game.rng
        count = len(actions)
        if game.phase == MAIN and game.offers_left and game.player_trading:
            pick = rng.randrange(count + 1)
            if pick < count:
                return actions[pick]
            offer = self._random_offer(game, rng)
            if offer:
                return offer
        return actions[rng.randrange(count)]

    @staticmethod
    def _random_offer(game, rng):
        p = game.current
        hand = game.res[p]
        if not any(hand):
            return 0
        others = [q for q in range(game.n) if q != p and any(game.res[q])]
        if not others:
            return 0
        theirs = game.res[others[rng.randrange(len(others))]]

        give = [rng.randrange(hand[r] + 1) for r in range(5)]
        if not any(give):
            held = [r for r in range(5) if hand[r]]
            give[held[rng.randrange(len(held))]] = 1
        get = [0 if give[r] else rng.randrange(theirs[r] + 1) for r in range(5)]
        if not any(get):
            wanted = [r for r in range(5) if not give[r] and theirs[r]]
            if not wanted:
                return 0
            get[wanted[rng.randrange(len(wanted))]] = 1
        return game.try_offer(give, get)


class GreedyBot:
    """Builds the most valuable thing it can afford each turn.

    Priority: city, settlement, knight, road (only when it has nowhere to
    settle), development card, then trades toward its next purchase: first
    with other players, then with the bank.

    Its offers follow no fixed order. Each time, it picks at random among the
    offers it would be happy with: some or all of what it is missing, for up to
    twice as many of its spare cards.

    It accepts a trade that moves it closer to its own next purchase, or that
    leaves it no further away with more cards in hand, unless the proposer is
    two points from winning.
    """

    lists_offers = False  # it builds its own offers with Game.can_offer

    def choose(self, game, actions):
        if len(actions) == 1:
            return actions[0]
        phase = game.phase
        if phase == MAIN:
            return self._main(game, actions)
        if phase == ROLL:
            return self._roll(game, actions)
        if phase == ROBBER:
            return self._robber(game, actions)
        if phase == DISCARD:
            hand = game.res[game.discarder]
            return max(actions, key=lambda a: hand[a & 255])
        if phase == TRADE_RESPONSE:
            return self._respond(game, actions)
        if phase == TRADE_PICK:
            # Trade with whoever is furthest from winning; the last action cancels.
            return min(actions[:-1], key=lambda a: game.victory_points(a & 255))
        if phase == SETUP_SETTLE:
            return max(actions, key=lambda a: self._node_value(game, a & 255))
        # SETUP_ROAD and FREE_ROAD
        return actions[game.rng.randrange(len(actions))]

    @staticmethod
    def _node_value(game, node):
        resources = {game.hex_res[h] for h in NODE_HEXES[node] if game.hex_res[h] >= 0}
        return game.node_pips[node] + 0.5 * len(resources)

    @staticmethod
    def _goal(game, p):
        """The cost of what p is saving for, or None."""
        if game.cities_left[p] and game.settlements[p]:
            return _CITY_COST
        if game.settlements_left[p] and game.settlement_spots(p):
            return _SETTLEMENT_COST
        if game.dev_deck:
            return _DEV_COST
        return None

    def _respond(self, game, actions):
        accept, reject = actions
        proposer = game.current
        if game.victory_points(proposer) >= 8:
            return reject
        me = game.responder
        goal = self._goal(game, me)
        if goal is None:
            return reject
        give, get = game.offer  # the proposer gives `give` and wants `get`
        hand = game.res[me]
        before = after = gained = 0
        for r in range(5):
            have = hand[r]
            then = have + give[r] - get[r]
            if goal[r] > have:
                before += goal[r] - have
            if goal[r] > then:
                after += goal[r] - then
            gained += give[r] - get[r]
        if after < before:
            return accept
        if after == before and gained > 0 and sum(hand) + gained <= 7:
            return accept
        return reject

    @staticmethod
    def _next_offer(game, hand, goal, missing):
        """The best offer not yet turned down this turn, or None."""
        spare = [max(0, hand[r] - goal[r]) for r in range(5)]
        total_spare = sum(spare)
        if not total_spare:
            return None
        rng = game.rng
        try_offer = game.try_offer
        spare_types = [r for r in range(5) if spare[r]]
        missing_types = [r for r in range(5) if missing[r]]
        for _ in range(4):  # a few tries at an offer that has not been turned down
            get = [0] * 5
            if rng.randrange(2):
                get = missing[:]
            else:
                t = missing_types[rng.randrange(len(missing_types))]
                get[t] = 1 + rng.randrange(missing[t])
            asked = sum(get)
            size = min(total_spare, asked + rng.randrange(asked + 1))
            give = [0] * 5
            left = size
            while left:
                r = spare_types[rng.randrange(len(spare_types))]
                if give[r] < spare[r] and not get[r]:
                    give[r] += 1
                    left -= 1
                elif all(give[x] >= spare[x] or get[x] for x in spare_types):
                    break
            offer = try_offer(give, get)
            if offer:
                return offer
        return None

    def _roll(self, game, actions):
        # Play a knight before rolling only to move the robber off our own hex.
        p = game.current
        for node in HEX_NODES[game.robber]:
            if game.node_owner[node] == p:
                for a in actions:
                    if a >> 8 == A_KNIGHT:
                        return a
                break
        return actions[0]

    def _robber(self, game, actions):
        p = game.current
        node_owner = game.node_owner
        node_level = game.node_level
        hex_num = game.hex_num
        best = actions[0]
        best_score = -1e9
        for a in actions:
            arg = a & 255
            h = arg >> 3
            victim = (arg & 7) - 1
            score = 0.0
            pips = PIPS.get(hex_num[h], 0)
            for node in HEX_NODES[h]:
                o = node_owner[node]
                if o == p:
                    score -= 100
                elif o >= 0:
                    score += pips * node_level[node]
            if victim >= 0:
                score += 2 + game.victory_points(victim)
            if score > best_score:
                best_score = score
                best = a
        return best

    def _main(self, game, actions):
        p = game.current
        cities = []
        settles = []
        roads = []
        trades = []
        plenty = []
        monopoly = []
        buy = knight = road_building = None
        for a in actions:
            kind = a >> 8
            if kind == A_ROAD:
                roads.append(a)
            elif kind == A_TRADE:
                trades.append(a)
            elif kind == A_CITY:
                cities.append(a)
            elif kind == A_SETTLE:
                settles.append(a)
            elif kind == A_YEAR_OF_PLENTY:
                plenty.append(a)
            elif kind == A_MONOPOLY:
                monopoly.append(a)
            elif kind == A_BUY:
                buy = a
            elif kind == A_KNIGHT:
                knight = a
            elif kind == A_ROAD_BUILDING:
                road_building = a

        pips = game.node_pips
        if cities:
            return max(cities, key=lambda a: pips[a & 255])
        if settles:
            return max(settles, key=lambda a: self._node_value(game, a & 255))
        if knight is not None:
            return knight

        can_settle = bool(game.settlements_left[p]) and bool(game.settlement_spots(p))
        wants_road = bool(game.settlements_left[p]) and not can_settle
        if wants_road:
            if road_building is not None:
                return road_building
            if roads:
                return roads[game.rng.randrange(len(roads))]

        hand = game.res[p]
        if game.cities_left[p] and game.settlements[p]:
            goal = _CITY_COST
        elif can_settle:
            goal = _SETTLEMENT_COST
        elif game.dev_deck:
            goal = _DEV_COST
        else:
            goal = None

        if goal is not None:
            missing = [max(0, goal[r] - hand[r]) for r in range(5)]
            if plenty or monopoly:
                wanted = max(range(5), key=lambda r: missing[r])
                if missing[wanted]:
                    for a in plenty:
                        i, j = divmod(a & 255, 5)
                        if missing[i] and missing[j] and (i != j or missing[i] >= 2):
                            return a
                    for a in plenty:
                        if missing[(a & 255) // 5] or missing[(a & 255) % 5]:
                            return a
                    for a in monopoly:
                        if (a & 255) == wanted:
                            return a
            # Other players are cheaper than the bank, so ask them first.
            if game.offers_left and game.player_trading and any(missing):
                offer = self._next_offer(game, hand, goal, missing)
                if offer is not None:
                    return offer
            rates = game.rates[p]
            for a in trades:
                give, get = divmod(a & 255, 5)
                if missing[get] and hand[give] - rates[give] >= goal[give]:
                    return a

        if buy is not None and (goal is _DEV_COST or sum(hand) > 7):
            return buy
        return actions[-1]  # end turn


# ---------------------------------------------------------------- opening policies
#
# An opening policy chooses the two starting settlements and roads. It is a
# function (game, actions) -> action, called only in the two set-up phases.

_BRICK, _LUMBER, _ORE, _GRAIN, _WOOL = range(5)


def _weighted_pips(game, node, weights):
    total = 0.0
    for h in NODE_HEXES[node]:
        r = game.hex_res[h]
        if r >= 0:
            total += PIPS[game.hex_num[h]] * weights[r]
    return total


def _road_toward(game, actions, value):
    """Point the road at the best spot that is still free to settle later."""
    settled = game.last_settle
    best = []
    best_score = None
    for a in actions:
        e = a & 255
        x, y = EDGE_NODES[e]
        far = y if x == settled else x
        score = max(
            (value(game, n) for n in NODE_NEIGHBORS[far] if n != settled and game._free_spot(n)),
            default=-1.0,
        )
        if best_score is None or score > best_score:
            best, best_score = [a], score
        elif score == best_score:
            best.append(a)
    return best[game.rng.randrange(len(best))]


def _best(game, actions, value):
    """The highest-valued settlement spot, breaking ties at random."""
    best = []
    best_score = None
    for a in actions:
        score = value(game, a & 255)
        if best_score is None or score > best_score:
            best, best_score = [a], score
        elif score == best_score:
            best.append(a)
    return best[game.rng.randrange(len(best))]


def _opening(value):
    def policy(game, actions):
        if game.phase == SETUP_SETTLE:
            return _best(game, actions, value)
        return _road_toward(game, actions, value)

    return policy


def opening_random(game, actions):
    """Any legal spot, any legal road."""
    return actions[game.rng.randrange(len(actions))]


def _pips(game, node):
    return game.node_pips[node]


def _balanced(game, node):
    resources = {game.hex_res[h] for h in NODE_HEXES[node] if game.hex_res[h] >= 0}
    return game.node_pips[node] + 2.0 * len(resources)


def _ore_grain(game, node):
    return _weighted_pips(game, node, (0.5, 0.5, 1.5, 1.5, 1.0))


def _brick_lumber(game, node):
    return _weighted_pips(game, node, (1.5, 1.5, 0.5, 1.0, 1.0))


def _port(game, node):
    return game.node_pips[node] + (3.0 if game.port_of_node[node] >= 0 else 0.0)


OPENINGS = {
    "random": opening_random,
    # Most dice pips: the spots that produce most often.
    "pips": _opening(_pips),
    # Pips plus a bonus for each different resource touched.
    "balanced": _opening(_balanced),
    # Favour ore and grain, the city and development card resources.
    "ore_grain": _opening(_ore_grain),
    # Favour brick and lumber, the road and settlement resources.
    "brick_lumber": _opening(_brick_lumber),
    # Pips plus a bonus for sitting on a harbour.
    "port": _opening(_port),
}


class PhasedBot:
    """A bot assembled from one policy per phase of the game.

    ``opening`` places the two starting settlements and roads. ``play`` makes
    every decision after that; it defaults to pure chance, so differences in
    results come from the opening alone.
    """

    def __init__(self, opening="random", play=None):
        self.opening_name = opening
        self.opening = OPENINGS[opening]
        self.play = play or RandomBot()
        self.lists_offers = self.play.lists_offers

    def choose(self, game, actions):
        if game.phase <= SETUP_ROAD:
            return self.opening(game, actions)
        return self.play.choose(game, actions)


BOTS = {"greedy": GreedyBot, "random": RandomBot}
