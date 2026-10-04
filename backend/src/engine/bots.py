"""Computer players. A bot is anything with ``choose(game, actions) -> action``."""
from .game import (
    A_BUY,
    A_CITY,
    A_KNIGHT,
    A_MONOPOLY,
    A_OFFER,
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
    SETUP_SETTLE,
    TRADE_PICK,
    TRADE_RESPONSE,
)
from .topology import HEX_NODES, NODE_HEXES

_CITY_COST = (0, 0, 3, 2, 0)
_SETTLEMENT_COST = (1, 1, 0, 1, 1)
_DEV_COST = (0, 0, 1, 1, 1)


class RandomBot:
    """Picks uniformly among legal actions. Games are long; useful as a baseline."""

    lists_offers = True

    def choose(self, game, actions):
        return actions[game.rng.randrange(len(actions))]


class GreedyBot:
    """Builds the most valuable thing it can afford each turn.

    Priority: city, settlement, knight, road (only when it has nowhere to
    settle), development card, then trades toward its next purchase: first
    with other players, then with the bank.

    It accepts a trade when it needs the card on offer and can spare the card
    asked for, unless the proposer is two points from winning.
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
        give, _, get = game.offer  # the proposer gives `give` and wants `get`
        hand = game.res[me]
        if hand[give] < goal[give] and hand[get] - 1 >= goal[get]:
            return accept
        return reject

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
            # Other players are cheaper than the bank: offer one card first, then two.
            if game.offers_left and game.player_trading:
                for count in (1, 2):
                    for give in range(5):
                        if hand[give] - count >= goal[give]:
                            for get in range(5):
                                if missing[get] and game.can_offer(give, count, get):
                                    return (A_OFFER << 8) | (give * 5 + get + 25 * (count - 1))
            rates = game.rates[p]
            for a in trades:
                give, get = divmod(a & 255, 5)
                if missing[get] and hand[give] - rates[give] >= goal[give]:
                    return a

        if buy is not None and (goal is _DEV_COST or sum(hand) > 7):
            return buy
        return actions[-1]  # end turn


BOTS = {"greedy": GreedyBot, "random": RandomBot}

