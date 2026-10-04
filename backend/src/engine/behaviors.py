"""Single behaviors layered on top of random play.

A BehaviorBot plays at random except where it has been given a policy:

- ``spend``: what to buy on its turn, and whether to pass
- ``trade``: whether to accept, refuse or counter an offer, whom to trade
  with, and whom to embargo
- ``robber``: where to move the robber and whom to rob

Every policy here changes one kind of decision and leaves the rest to chance,
so its effect can be measured on its own.

"Leader" and rankings use public points: settlements, cities, Longest Road and
Largest Army. Hidden victory point cards are not counted.
"""
from .bots import OPENINGS, RandomBot
from .game import (
    A_BUY,
    A_CITY,
    A_EMBARGO,
    A_LIFT,
    A_ROAD,
    A_ROAD_BUILDING,
    A_SETTLE,
    MAIN,
    PIPS,
    ROBBER,
    SETUP_ROAD,
    TRADE_COUNTER,
    TRADE_PICK,
    TRADE_RESPONSE,
)
from .topology import HEX_NODES


def _pick(game, actions):
    return actions[game.rng.randrange(len(actions))]


def _kind(a):
    return (a >> 8) & 255


def _leader(game, exclude):
    """The opponent of ``exclude`` with the most public points."""
    best = -1
    best_points = -1
    for q in range(game.n):
        if q != exclude:
            points = game.public_points(q)
            if points > best_points:
                best, best_points = q, points
    return best


# ------------------------------------------------------------------ spending
#
# A spending policy sees the legal actions in the main phase and returns either
# one action to take, a shorter list to choose from at random, or None to
# choose at random from everything.


def _of_kind(actions, kind):
    return [a for a in actions if _kind(a) == kind]


def spend_never_pass(game, actions):
    """Build a settlement or city whenever one is affordable; otherwise random."""
    points = [a for a in actions if _kind(a) in (A_CITY, A_SETTLE)]
    return _pick(game, points) if points else None


def _priority(*kinds):
    def policy(game, actions):
        for kind in kinds:
            options = _of_kind(actions, kind)
            if options:
                return _pick(game, options)
        return None

    return policy


def spend_no_wasted_roads(game, actions):
    """Random, but only build a road when there is nowhere left to settle."""
    p = game.current
    if game.settlements_left[p] and not game.settlement_spots(p):
        return None
    kept = [a for a in actions if _kind(a) not in (A_ROAD, A_ROAD_BUILDING)]
    return kept or None


def spend_disciplined(game, actions):
    """City, settlement, then development card; never a wasted road."""
    choice = SPENDING["points_first"](game, actions)
    return choice if choice is not None else spend_no_wasted_roads(game, actions)


SPENDING = {
    "random": None,
    "never_pass": spend_never_pass,
    # City, then settlement, then development card.
    "points_first": _priority(A_CITY, A_SETTLE, A_BUY),
    # Settlement, then city, then development card.
    "settle_first": _priority(A_SETTLE, A_CITY, A_BUY),
    # Development card, then city, then settlement.
    "dev_first": _priority(A_BUY, A_CITY, A_SETTLE),
    "no_wasted_roads": spend_no_wasted_roads,
    "disciplined": spend_disciplined,
}


# ------------------------------------------------------------------ trading
#
# A TradePolicy answers four questions. Any left as None stays random.
#
#   respond(game, me)     accept the offer on the table?
#   counter(game, me)     if not, counter with which (give, get) terms, or None
#   on_counter(game)      as proposer, accept the counter-offer on the table?
#   pick(game, acceptors) as proposer, whom to trade with when several accept
#   embargo(game, me)     the set of players to hold under embargo right now
#
# A bot with a TradePolicy never changes embargoes at random; it holds exactly
# the set its policy asks for, which is empty when the policy has none.


class TradePolicy:
    def __init__(self, respond, counter=None, on_counter=None, pick=None, embargo=None):
        self.respond = respond
        self.counter = counter
        self.on_counter = on_counter
        self.pick = pick
        self.embargo = embargo


def _gain(game):
    """Cards the responder would receive minus cards it would give."""
    give, get = game.offer
    return sum(give) - sum(get)


def _proposer_gain(game):
    """Cards the proposer would receive minus cards it would give."""
    return -_gain(game)


def _sole_leader(game):
    """The player alone in first place on public points, or -1."""
    points = [game.public_points(q) for q in range(game.n)]
    top = max(points)
    return points.index(top) if points.count(top) == 1 else -1


def _proposer_leads(game):
    return _sole_leader(game) == game.current


def _weakest(game, acceptors):
    return min(acceptors, key=game.public_points)


def _trimmed_ask(extra):
    """Counter by asking the responder for fewer cards.

    The proposer still gives what it offered; the responder gives only as many
    cards as it receives, plus ``extra`` (0 for an even swap, -1 to come out a
    card ahead). Returns None when there is nothing left to give.
    """

    def counter(game, me):
        give, get = game.offer
        size = sum(give) + extra
        if size < 1 or size >= sum(get):
            return None
        ask = list(get)
        while sum(ask) > size:
            ask[max(range(5), key=lambda r: ask[r])] -= 1
        return give, ask

    return counter


def _embargo_leader(game, me):
    leader = _sole_leader(game)
    return {leader} if leader >= 0 and leader != me else set()


def _embargo_close(game, me):
    return {q for q in range(game.n) if q != me and game.public_points(q) >= 7}


def _fair(game, me):
    return _gain(game) >= 0


def _profit(game, me):
    return _gain(game) > 0


def _fair_counter(game):
    return _proposer_gain(game) >= 0


TRADING = {
    "random": None,
    # Refuse everything, including counters.
    "never": TradePolicy(lambda game, me: False, on_counter=lambda game: False),
    # Accept everything, including counters.
    "always": TradePolicy(lambda game, me: True, on_counter=lambda game: True),
    # Accept when it receives at least as many cards as it gives.
    "fair": TradePolicy(_fair, on_counter=_fair_counter),
    # Accept only when it receives more cards than it gives.
    "profit": TradePolicy(_profit, on_counter=lambda game: _proposer_gain(game) > 0),
    # Coin flip, but never with the player in the lead.
    "no_leader": TradePolicy(lambda game, me: not _proposer_leads(game) and game.rng.randrange(2) == 1, pick=_weakest),
    # Fair trades only, and never with the player in the lead.
    "fair_no_leader": TradePolicy(lambda game, me: not _proposer_leads(game) and _fair(game, me),
                                  on_counter=_fair_counter, pick=_weakest),
    # Fair trades only, and only with players ranked below it.
    "fair_behind_only": TradePolicy(
        lambda game, me: _fair(game, me) and game.public_points(game.current) < game.public_points(me),
        on_counter=_fair_counter, pick=_weakest),
    # Fair, and it counters an unfair offer with an even swap.
    "counter_even": TradePolicy(_fair, counter=_trimmed_ask(0), on_counter=_fair_counter),
    # Takes only winning trades, and counters everything else to come out a card ahead.
    "counter_ahead": TradePolicy(_profit, counter=_trimmed_ask(-1), on_counter=_fair_counter),
    # Fair, and it holds an embargo on whoever is alone in first place.
    "embargo_leader": TradePolicy(_fair, on_counter=_fair_counter, pick=_weakest, embargo=_embargo_leader),
    # Fair, and it embargoes anyone within three points of winning.
    "embargo_close": TradePolicy(_fair, on_counter=_fair_counter, pick=_weakest, embargo=_embargo_close),
    # Counters unfair offers with an even swap and embargoes the leader.
    "counter_embargo": TradePolicy(_fair, counter=_trimmed_ask(0), on_counter=_fair_counter, pick=_weakest,
                                   embargo=_embargo_leader),
}


# ------------------------------------------------------------------ robber
#
# A robber policy scores each legal robber move; the highest score wins and
# ties are broken at random. A move is (hex, victim), victim -1 for nobody.


def _decode_robber(a):
    arg = a & 255
    return arg >> 3, (arg & 7) - 1


def _on_own_hex(game, h):
    p = game.current
    return any(game.node_owner[n] == p for n in HEX_NODES[h])


def _blocked(game, h, only=None):
    """Production the robber would stop on hex h, for one player or all opponents."""
    p = game.current
    pips = PIPS.get(game.hex_num[h], 0)
    total = 0
    for n in HEX_NODES[h]:
        o = game.node_owner[n]
        if o >= 0 and o != p and (only is None or o == only):
            total += pips * game.node_level[n]
    return total


def _robber_scored(score):
    def policy(game, actions):
        best = []
        best_score = None
        for a in actions:
            h, victim = _decode_robber(a)
            s = score(game, h, victim)
            if best_score is None or s > best_score:
                best, best_score = [a], s
            elif s == best_score:
                best.append(a)
        return _pick(game, best)

    return policy


def _score_no_self(game, h, victim):
    return 0 if _on_own_hex(game, h) else 1


def _score_max_block(game, h, victim):
    return -1000 if _on_own_hex(game, h) else _blocked(game, h)


def _score_leader(game, h, victim):
    return 1 if victim == _leader(game, game.current) else 0


def _score_leader_block(game, h, victim):
    if _on_own_hex(game, h):
        return -1000
    leader = _leader(game, game.current)
    return 10 * _blocked(game, h, leader) + (5 if victim == leader else 0)


def _score_richest(game, h, victim):
    if _on_own_hex(game, h):
        return -1000
    return sum(game.res[victim]) if victim >= 0 else 0


def _score_rank_weighted(game, h, victim):
    """Block production in proportion to how many points each owner has."""
    if _on_own_hex(game, h):
        return -1000
    p = game.current
    pips = PIPS.get(game.hex_num[h], 0)
    total = 0
    for n in HEX_NODES[h]:
        o = game.node_owner[n]
        if o >= 0 and o != p:
            total += pips * game.node_level[n] * game.public_points(o)
    return total + (game.public_points(victim) if victim >= 0 else 0)


ROBBING = {
    "random": None,
    # Never block its own hex.
    "no_self": _robber_scored(_score_no_self),
    # Block the most opponent production.
    "max_block": _robber_scored(_score_max_block),
    # Rob the player in the lead, wherever they are.
    "leader": _robber_scored(_score_leader),
    # Block the leader's best hex and rob them.
    "leader_block": _robber_scored(_score_leader_block),
    # Rob whoever holds the most cards.
    "richest": _robber_scored(_score_richest),
    # Block production weighted by each owner's points.
    "rank_weighted": _robber_scored(_score_rank_weighted),
}

CATEGORIES = {"spend": SPENDING, "trade": TRADING, "robber": ROBBING}


class BehaviorBot:
    """Random play with chosen behaviors switched on. Unset behaviors stay random."""

    lists_offers = False

    def __init__(self, opening="adaptive", spend="random", trade="random", robber="random"):
        self.opening = OPENINGS[opening]
        self.spend = SPENDING[spend]
        self.trade = TRADING[trade]
        self.robber = ROBBING[robber]
        # A bot with a trade policy manages its own embargoes.
        self.random = RandomBot(embargoes=self.trade is None)

    def choose(self, game, actions):
        phase = game.phase
        trade = self.trade
        if phase == MAIN:
            if trade is not None and trade.embargo is not None:
                change = self._embargo_change(game, trade.embargo(game, game.current))
                if change:
                    return change
            if self.spend is not None:
                choice = self.spend(game, actions)
                if isinstance(choice, list):
                    actions = choice
                elif choice is not None:
                    return choice
        elif phase <= SETUP_ROAD:
            return self.opening(game, actions)
        elif phase == TRADE_RESPONSE:
            if trade is not None:
                accept, reject = actions
                me = game.responder
                if trade.respond(game, me):
                    return accept
                if trade.counter is not None:
                    terms = trade.counter(game, me)
                    if terms:
                        counter = game.try_counter(*terms)
                        if counter:
                            return counter
                return reject
        elif phase == TRADE_COUNTER:
            if trade is not None and trade.on_counter is not None:
                accept, reject = actions
                return accept if trade.on_counter(game) else reject
        elif phase == TRADE_PICK:
            if trade is not None and trade.pick is not None:
                target = trade.pick(game, game.acceptors)
                for a in actions[:-1]:  # the last action backs out of the trade
                    if (a & 255) == target:
                        return a
        elif phase == ROBBER:
            if self.robber is not None:
                return self.robber(game, actions)
        return self.random.choose(game, actions)

    @staticmethod
    def _embargo_change(game, wanted):
        """One action that moves this player's embargoes toward ``wanted``, or 0."""
        p = game.current
        held = game.embargo[p]
        for q in range(game.n):
            if q != p:
                has = (held >> q) & 1
                if q in wanted and not has:
                    return (A_EMBARGO << 8) | q
                if has and q not in wanted:
                    return (A_LIFT << 8) | q
        return 0
