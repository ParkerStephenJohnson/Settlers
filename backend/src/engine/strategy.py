"""A fully assigned bot: every kind of decision has a policy, none is left to chance.

A StrategyBot has one policy per behavior:

    opening   where to place the two starting settlements and roads
    spend     what to buy, in which order
    build     where to put it
    dev       when and how to play development cards
    propose   which trades to offer other players
    bank      when to trade with the bank or a harbour
    trade     how to answer offers and counter-offers, and whom to embargo
    robber    where to move the robber and whom to rob
    discard   which cards to give up on a 7

STANDARD is the reference bot. An experiment changes one behavior in one seat
and plays it against STANDARD in the other seats. Randomness is used only to
break exact ties.
"""
from .behaviors import (
    ROBBING,
    TRADING,
    TradePolicy,
    _embargo_close,
    _embargo_leader,
    _fair_counter,
    _gain,
    _proposer_leads,
    _weakest,
)
from .bots import ADAPTIVE_OPENING_PARAMS, OPENINGS, spot_value
from .game import (
    A_BUY,
    A_CITY,
    A_EMBARGO,
    A_END,
    A_KNIGHT,
    A_LIFT,
    A_MONOPOLY,
    A_ROAD,
    A_ROAD_BUILDING,
    A_SETTLE,
    A_TRADE,
    A_YEAR_OF_PLENTY,
    DISCARD,
    FREE_ROAD,
    MAIN,
    ROBBER,
    ROLL,
    SETUP_ROAD,
    TRADE_COUNTER,
    TRADE_PICK,
    TRADE_RESPONSE,
)
from .topology import EDGE_NODES, HEX_NODES, NODE_NEIGHBORS

COSTS = {
    "city": (0, 0, 3, 2, 0),
    "settlement": (1, 1, 0, 1, 1),
    "dev": (0, 0, 1, 1, 1),
    "road": (1, 1, 0, 0, 0),
}
_KIND = {"city": A_CITY, "settlement": A_SETTLE, "dev": A_BUY, "road": A_ROAD}


def _kind(a):
    return (a >> 8) & 255


def _best(game, options, score):
    """The highest-scoring option, ties broken at random."""
    best = []
    best_score = None
    for option in options:
        s = score(option)
        if best_score is None or s > best_score:
            best, best_score = [option], s
        elif s == best_score:
            best.append(option)
    return best[game.rng.randrange(len(best))]


def _needs_road(game, p):
    """A road is the only way forward: settlements remain but there is nowhere to put one."""
    return bool(game.settlements_left[p] and game.roads_left[p] and not game.settlement_spots(p))


def next_purchase(game, p, order):
    """What p is working toward: the first thing in its spending order it could build."""
    for item in order:
        if item == "city":
            if game.cities_left[p] and game.settlements[p]:
                return item
        elif item == "settlement":
            if game.settlements_left[p]:
                if game.settlement_spots(p):
                    return item
                if game.roads_left[p]:
                    return "road"  # nowhere to settle yet, so a road comes first
        elif item == "dev":
            if game.dev_deck:
                return item
    return None


def _missing(hand, cost):
    return [max(0, cost[r] - hand[r]) for r in range(5)]


def _spare(hand, cost):
    return [max(0, hand[r] - cost[r]) for r in range(5)]


# ------------------------------------------------------------------ spend

_CITY_FIRST = ("city", "settlement", "dev")
_SETTLE_FIRST = ("settlement", "city", "dev")


def _order_nearest(game, p):
    """Go for whichever of a city and a settlement needs fewer cards right now."""
    hand = game.res[p]
    city = sum(_missing(hand, COSTS["city"])) if game.cities_left[p] and game.settlements[p] else 99
    settle = 99
    if game.settlements_left[p] and game.settlement_spots(p):
        settle = sum(_missing(hand, COSTS["settlement"]))
    return _SETTLE_FIRST if settle < city else _CITY_FIRST


def _order_contrarian(game, p):
    """Do the opposite of the table: settle when opponents are upgrading, upgrade when they settle."""
    cities = settlements = 0
    for q in range(game.n):
        if q != p:
            cities += len(game.cities[q])
            settlements += len(game.settlements[q]) + len(game.cities[q]) - 2
    return _SETTLE_FIRST if cities >= settlements else _CITY_FIRST


# A spending order is a tuple, or a function (game, player) -> tuple that can
# change its mind during the game.
SPEND = {
    "points_first": _CITY_FIRST,
    "settle_first": _SETTLE_FIRST,
    "dev_first": ("dev", "city", "settlement"),
    "city_settle_only": ("city", "settlement"),
    "nearest": _order_nearest,
    "contrarian": _order_contrarian,
}


# ------------------------------------------------------------------ build


def _pips_value(game, p):
    return lambda node: game.node_pips[node]


def _adaptive_value(game, p):
    return spot_value(game, ADAPTIVE_OPENING_PARAMS, p)


def _build_with(value_factory):
    def choose(game, p, kind, options):
        if kind == A_CITY:
            return _best(game, options, lambda a: game.node_pips[a & 255])
        value = value_factory(game, p)
        if kind == A_SETTLE:
            return _best(game, options, lambda a: value(a & 255))

        # A road is worth the best free spot it reaches or points at.
        touch = game.touch[p]
        free = game._free_spot

        def road_score(a):
            x, y = EDGE_NODES[a & 255]
            best = -1.0
            for end in (x, y):
                if end in touch:
                    continue
                if free(end):
                    best = max(best, value(end) + 1000)  # opens a spot right away
                for n in NODE_NEIGHBORS[end]:
                    if n not in touch and free(n):
                        best = max(best, value(n))
            return best

        return _best(game, options, road_score)

    return choose


BUILD = {
    # Score spots the way the adaptive opening does.
    "value": _build_with(_adaptive_value),
    # Score spots by dice pips alone.
    "pips": _build_with(_pips_value),
}


# ------------------------------------------------------------------ development cards
#
# A dev policy answers one question: play a knight now? The other cards are
# played the same way by every policy, when they help the next purchase.


def _robbed(game, p):
    return any(game.node_owner[n] == p for n in HEX_NODES[game.robber])


def _army_within_reach(game, p):
    holder = game.largest_army
    if holder == p:
        return False
    after = game.knights[p] + 1
    return after >= 3 and (holder < 0 or after > game.knights[holder])


DEV = {
    # Play a knight as soon as it is in hand.
    "eager": lambda game, p: True,
    # Keep knights until robbed, or until one more would take Largest Army.
    "hold_knights": lambda game, p: _robbed(game, p) or _army_within_reach(game, p),
    # Only ever use a knight to move the robber off its own hex.
    "defensive": _robbed,
    # Never play development cards at all.
    "never": None,
}


# ------------------------------------------------------------------ propose


def _propose_none(game, hand, cost, missing, spare):
    return 0


def _singles(ratio):
    def propose(game, hand, cost, missing, spare):
        for g in sorted(range(5), key=lambda r: -spare[r]):
            if spare[g] >= ratio:
                give = [0] * 5
                give[g] = ratio
                for t in range(5):
                    if missing[t]:
                        get = [0] * 5
                        get[t] = 1
                        offer = game.try_offer(give, get)
                        if offer:
                            return offer
        return 0

    return propose


def _propose_bundle(game, hand, cost, missing, spare):
    need = sum(missing)
    if need >= 2 and sum(spare) >= need:
        give = [0] * 5
        left = need
        for r in sorted(range(5), key=lambda r: -spare[r]):
            take = min(spare[r], left)
            give[r] = take
            left -= take
        offer = game.try_offer(give, missing)
        if offer:
            return offer
    return _singles(1)(game, hand, cost, missing, spare)


def _propose_escalate(game, hand, cost, missing, spare):
    return _singles(1)(game, hand, cost, missing, spare) or _singles(2)(game, hand, cost, missing, spare)


PROPOSE = {
    "none": _propose_none,
    # One spare card for one missing card.
    "even": _singles(1),
    # Two spare cards for one missing card.
    "generous": _singles(2),
    # One for one first, then two for one.
    "escalate": _propose_escalate,
    # Everything missing for the same number of spare cards, then singles.
    "bundle": _propose_bundle,
}


# ------------------------------------------------------------------ bank


def _bank_goal(game, p, actions, hand, cost, missing):
    rates = game.rates[p]
    for a in actions:
        if _kind(a) == A_TRADE:
            give, get = divmod(a & 255, 5)
            if missing[get] and hand[give] - rates[give] >= cost[give]:
                return a
    return 0


def _bank_dump(game, p, actions, hand, cost, missing):
    choice = _bank_goal(game, p, actions, hand, cost, missing)
    if choice or sum(hand) <= 7:
        return choice
    # Over seven cards: thin the biggest pile so a 7 costs less.
    rates = game.rates[p]
    trades = [a for a in actions if _kind(a) == A_TRADE and hand[(a & 255) // 5] - rates[(a & 255) // 5] >= cost[(a & 255) // 5]]
    if not trades:
        return 0
    return _best(game, trades, lambda a: (hand[(a & 255) // 5], -hand[(a & 255) % 5]))


BANK = {
    "never": lambda game, p, actions, hand, cost, missing: 0,
    # Trade spare cards for a card the next purchase needs.
    "goal": _bank_goal,
    # As goal, and also thin the hand when holding more than seven cards.
    "dump": _bank_dump,
}


# ------------------------------------------------------------------ discard


def _discard_most(game, p, actions, cost):
    hand = game.res[p]
    return _best(game, actions, lambda a: hand[a & 255])


def _discard_keep_goal(game, p, actions, cost):
    hand = game.res[p]
    spare = _spare(hand, cost) if cost else hand
    return _best(game, actions, lambda a: (spare[a & 255] > 0, hand[a & 255]))


DISCARDS = {
    # Give up whatever it has most of.
    "most": _discard_most,
    # Give up cards the next purchase does not need first.
    "keep_goal": _discard_keep_goal,
}


# ------------------------------------------------------------------ trade answers
#
# The count-based policies come from behaviors.TRADING. "goal" is new: it
# judges a trade by whether it brings the bot's own next purchase closer.


def _closer(game, me, order):
    cost = COSTS.get(next_purchase(game, me, order) or "", None)
    if cost is None:
        return _gain(game) > 0
    give, get = game.offer
    hand = game.res[me]
    before = sum(_missing(hand, cost))
    after = sum(max(0, cost[r] - (hand[r] + give[r] - get[r])) for r in range(5))
    return after < before or (after == before and _gain(game) > 0)


def _closer_proposer(game, order):
    p = game.current
    cost = COSTS.get(next_purchase(game, p, order) or "", None)
    give, get = game.offer
    if cost is None:
        return sum(get) > sum(give)
    hand = game.res[p]
    before = sum(_missing(hand, cost))
    after = sum(max(0, cost[r] - (hand[r] - give[r] + get[r])) for r in range(5))
    return after < before or (after == before and sum(get) > sum(give))


_ORDER = SPEND["points_first"]


def _goal(game, me):
    return _closer(game, me, _ORDER)


def _goal_proposer(game):
    return _closer_proposer(game, _ORDER)


def _goal_counter(game, me):
    """Turn an offer that does not help into one that does.

    Give the proposer what it asked for, provided that can be spared, and ask
    in return for one card this player is actually missing.
    """
    cost = COSTS.get(next_purchase(game, me, _ORDER) or "")
    if cost is None:
        return None
    _, get = game.offer
    hand = game.res[me]
    if any(get[r] and hand[r] - get[r] < cost[r] for r in range(5)):
        return None
    missing = _missing(hand, cost)
    theirs = game.res[game.current]
    for r in sorted(range(5), key=lambda r: -missing[r]):
        if missing[r] and theirs[r] and not get[r]:
            give = [0] * 5
            give[r] = 1
            return give, get
    return None


def _leads(game):
    return _proposer_leads(game)


def _close(game):
    return game.public_points(game.current) >= 7


def _goal_policy(refuse=None, counter=None, embargo=None):
    if refuse is None:
        respond = _goal
    else:
        def respond(game, me):
            return not refuse(game, me) and _goal(game, me)
    return TradePolicy(respond, counter=counter, on_counter=_goal_proposer, pick=_weakest, embargo=embargo)


# Every policy below except the three references judges a trade by whether it
# brings its own next purchase closer. They differ in whom they will deal with.
TRADE = {
    # References: refuse everything; card-counting rules from the first experiments.
    "never": TRADING["never"],
    "profit": TRADING["profit"],
    "counter_ahead": TRADING["counter_ahead"],
    # Accept what brings the next purchase closer.
    "goal": _goal_policy(),
    # As goal, and counter an unhelpful offer by asking for a card it needs.
    "goal_counter": _goal_policy(counter=_goal_counter),
    # As goal, but refuse the player alone in first place.
    "goal_no_leader": _goal_policy(refuse=lambda game, me: _leads(game)),
    # As goal, but refuse anyone within three points of winning.
    "goal_no_close": _goal_policy(refuse=lambda game, me: _close(game)),
    # As goal, but only with players who have fewer points than it does.
    "goal_behind_only": _goal_policy(
        refuse=lambda game, me: game.public_points(game.current) >= game.public_points(me)),
    # As goal, and hold an embargo on the player alone in first place.
    "goal_embargo_leader": _goal_policy(embargo=_embargo_leader),
    # As goal, and embargo anyone within three points of winning.
    "goal_embargo_close": _goal_policy(embargo=_embargo_close),
    # Counter, and embargo anyone within three points of winning.
    "goal_counter_embargo": _goal_policy(counter=_goal_counter, embargo=_embargo_close),
}
ROBBER_POLICIES = {name: policy for name, policy in ROBBING.items() if policy is not None}

OPENING = {name: policy for name, policy in OPENINGS.items() if name != "random"}

CATEGORIES = {
    "opening": OPENING,
    "spend": SPEND,
    "build": BUILD,
    "dev": DEV,
    "propose": PROPOSE,
    "bank": BANK,
    "trade": TRADE,
    "robber": ROBBER_POLICIES,
    "discard": DISCARDS,
}

# The reference bot, after five rounds of src.engine.rounds (10,000 games per
# variant). No single change to it wins more than an even share:
#   - spend: nearest and settle_first are level and nothing beats either
#   - trade: goal; refusing or embargoing leaders does not help
#   - opening: adaptive_v2, tuned with standard play; it beat adaptive
#     27.3% to 25.0% from one seat and won a mixed field of openings
STANDARD = {
    "opening": "adaptive_v2",
    "spend": "nearest",
    "build": "value",
    "dev": "eager",
    "propose": "escalate",
    "bank": "goal",
    "trade": "goal",
    "robber": "rank_weighted",
    "discard": "keep_goal",
}


class StrategyBot:
    """A bot with a policy for every decision. See the module docstring."""

    lists_offers = False

    def __init__(self, **choices):
        config = dict(STANDARD, **choices)
        self.config = config
        opening = config["opening"]
        self.opening = OPENINGS[opening] if isinstance(opening, str) else opening
        self._spend = SPEND[config["spend"]]
        self.build = BUILD[config["build"]]
        self.knight = DEV[config["dev"]]
        self.plays_cards = config["dev"] != "never"
        self.propose = PROPOSE[config["propose"]]
        self.bank = BANK[config["bank"]]
        self.trade = TRADE[config["trade"]]
        self.robber = ROBBER_POLICIES[config["robber"]]
        self.discard = DISCARDS[config["discard"]]

    def order(self, game, p):
        spend = self._spend
        return spend(game, p) if callable(spend) else spend

    # ---------------------------------------------------------------- dispatch

    def choose(self, game, actions):
        phase = game.phase
        if phase == MAIN:
            return self._main(game, actions)
        if phase == ROLL:
            return self._roll(game, actions)
        if phase <= SETUP_ROAD:
            return self.opening(game, actions)
        if phase == TRADE_RESPONSE:
            return self._respond(game, actions)
        if phase == TRADE_COUNTER:
            accept, reject = actions
            on_counter = self.trade.on_counter or _fair_counter
            return accept if on_counter(game) else reject
        if phase == TRADE_PICK:
            target = (self.trade.pick or _weakest)(game, game.acceptors)
            for a in actions[:-1]:
                if (a & 255) == target:
                    return a
            return actions[0]
        if phase == ROBBER:
            return self.robber(game, actions)
        if phase == DISCARD:
            p = game.discarder
            return self.discard(game, p, actions, COSTS.get(next_purchase(game, p, self.order(game, p)) or ""))
        if phase == FREE_ROAD:
            return self.build(game, game.current, A_ROAD, actions)
        return actions[0]

    def _roll(self, game, actions):
        p = game.current
        if self.plays_cards and len(actions) > 1 and _robbed(game, p):
            for a in actions:
                if _kind(a) == A_KNIGHT:
                    return a
        return actions[0]

    def _respond(self, game, actions):
        accept, reject = actions
        me = game.responder
        trade = self.trade
        if trade.respond(game, me):
            return accept
        if trade.counter is not None:
            terms = trade.counter(game, me)
            if terms:
                counter = game.try_counter(*terms)
                if counter:
                    return counter
        return reject

    # ---------------------------------------------------------------- the turn

    def _main(self, game, actions):
        p = game.current

        # 1. Embargoes follow the trade policy.
        if self.trade.embargo is not None:
            wanted = self.trade.embargo(game, p)
            held = game.embargo[p]
            for q in range(game.n):
                if q != p:
                    has = (held >> q) & 1
                    if q in wanted and not has:
                        return (A_EMBARGO << 8) | q
                    if has and q not in wanted:
                        return (A_LIFT << 8) | q

        by_kind = {}
        for a in actions:
            by_kind.setdefault(_kind(a), []).append(a)

        # 2. Buy the first thing in the spending order that is affordable.
        order = self.order(game, p)
        for item in order:
            options = by_kind.get(_KIND[item])
            if options:
                return options[0] if item == "dev" else self.build(game, p, _KIND[item], options)
        needs_road = _needs_road(game, p)
        if needs_road and A_ROAD in by_kind:
            return self.build(game, p, A_ROAD, by_kind[A_ROAD])

        target = next_purchase(game, p, order)
        hand = game.res[p]
        cost = COSTS.get(target or "")
        missing = _missing(hand, cost) if cost else [0] * 5

        # 3. Development cards.
        if self.plays_cards:
            if A_KNIGHT in by_kind and self.knight(game, p):
                return by_kind[A_KNIGHT][0]
            if needs_road and A_ROAD_BUILDING in by_kind:
                return by_kind[A_ROAD_BUILDING][0]
            if any(missing):
                for a in by_kind.get(A_YEAR_OF_PLENTY, ()):
                    i, j = divmod(a & 255, 5)
                    if missing[i] and missing[j] and (i != j or missing[i] >= 2):
                        return a
                for a in by_kind.get(A_YEAR_OF_PLENTY, ()):
                    if sum(missing) == 1 and (missing[(a & 255) // 5] or missing[(a & 255) % 5]):
                        return a
                if A_MONOPOLY in by_kind:
                    wanted = max(range(5), key=lambda r: missing[r])
                    for a in by_kind[A_MONOPOLY]:
                        if (a & 255) == wanted:
                            return a

        # 4. Trade toward the next purchase: players first, then the bank.
        if cost and any(missing):
            if game.offers_left and game.player_trading:
                offer = self.propose(game, hand, cost, missing, _spare(hand, cost))
                if offer:
                    return offer
            choice = self.bank(game, p, actions, hand, cost, missing)
            if choice:
                return choice
        elif cost is None:
            choice = self.bank(game, p, actions, hand, (0, 0, 0, 0, 0), missing)
            if choice:
                return choice

        return A_END << 8
