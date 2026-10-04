"""Catan rules engine built for running many games quickly.

State lives in flat lists of ints indexed by player, hex, node and edge. Actions
are ints: ``(kind << 8) | argument``. The loop is::

    game = Game(seed=1)
    while not game.done:
        actions = game.legal_actions()
        game.apply(bot.choose(game, actions))

Rules covered: setup draft, production with bank shortages, the robber and
discards, roads, settlements, cities, development cards, ports and bank trades,
trades between players, longest road, largest army, and winning at 10 points.

Trades between players are offers of any bundle of cards for any other bundle,
built with ``offer_action(give, get)``. Everyone holding the requested cards
answers in seat order; if several accept, the proposer picks. There is no limit
on the number of offers in a turn, but an offer that was just turned down
cannot be repeated until a trade goes through or the turn ends.

Two table conventions are modelled as well. A responder may answer an offer
with a counter-offer (``try_counter``), which the proposer accepts or refuses.
A player may declare an embargo on another player on its own turn; while either
side embargoes the other, the two cannot trade.

Rules follow the official CATAN base game rulebook and almanac (2020 edition).
"""
import random

from .topology import (
    EDGE_NODES,
    HEX_NEIGHBORS,
    HEX_NODES,
    NODE_EDGES,
    NODE_HEXES,
    NODE_NEIGHBORS,
    NUM_EDGES,
    NUM_HEXES,
    NUM_NODES,
    PORT_EDGES,
)

# Resources
BRICK, LUMBER, ORE, GRAIN, WOOL = range(5)
RESOURCE_NAMES = ("brick", "lumber", "ore", "grain", "wool")
DESERT = -1

# Development cards
KNIGHT, VICTORY_POINT, ROAD_BUILDING, YEAR_OF_PLENTY, MONOPOLY = range(5)

# Phases
(SETUP_SETTLE, SETUP_ROAD, ROLL, MAIN, ROBBER, DISCARD, FREE_ROAD, TRADE_RESPONSE, TRADE_PICK,
 TRADE_COUNTER) = range(10)

# Action kinds
(
    A_ROLL,
    A_END,
    A_SETTLE,
    A_ROAD,
    A_CITY,
    A_BUY,
    A_KNIGHT,
    A_ROAD_BUILDING,
    A_YEAR_OF_PLENTY,
    A_MONOPOLY,
    A_TRADE,
    A_ROBBER,
    A_DISCARD,
    A_OFFER,
    A_ACCEPT,
    A_REJECT,
    A_CONFIRM,
    A_COUNTER,
    A_EMBARGO,
    A_LIFT,
) = range(20)

GENERIC_PORT = 5
WIN_POINTS = 10

_HEX_RESOURCES = [BRICK] * 3 + [LUMBER] * 4 + [ORE] * 3 + [GRAIN] * 4 + [WOOL] * 4 + [DESERT]
_NUMBERS = [2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12]
_DEV_DECK = [KNIGHT] * 14 + [VICTORY_POINT] * 5 + [ROAD_BUILDING] * 2 + [YEAR_OF_PLENTY] * 2 + [MONOPOLY] * 2
_PORTS = [GENERIC_PORT] * 4 + [BRICK, LUMBER, ORE, GRAIN, WOOL]
PIPS = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 8: 5, 9: 4, 10: 3, 11: 2, 12: 1}


def action(kind, arg=0):
    return (kind << 8) | arg


def kind_of(act):
    """The action kind. Use this rather than ``act >> 8`` when offers may be present."""
    return (act >> 8) & 255


def offer_action(give, get):
    """An offer of ``give`` for ``get``, each a list of five card counts by resource."""
    return (
        (
            give[0] | give[1] << 5 | give[2] << 10 | give[3] << 15 | give[4] << 20
            | get[0] << 25 | get[1] << 30 | get[2] << 35 | get[3] << 40 | get[4] << 45
        ) << 16
    ) | (A_OFFER << 8)


def counter_action(give, get):
    """A counter-offer: the proposer would give ``give`` and receive ``get``."""
    return offer_action(give, get) ^ (A_OFFER << 8) | (A_COUNTER << 8)


def decode_offer(act):
    """The (give, get) card counts of an offer or counter-offer action."""
    payload = act >> 16
    return (
        [(payload >> (5 * r)) & 31 for r in range(5)],
        [(payload >> (25 + 5 * r)) & 31 for r in range(5)],
    )


def _unit(r, count=1):
    cards = [0] * 5
    cards[r] = count
    return cards


# One-for-one and two-for-one offers, listed by legal_actions for bots that do
# not build their own: _SIMPLE_OFFERS[give][get] = (one-for-one, two-for-one).
_SIMPLE_OFFERS = [
    [
        (offer_action(_unit(i), _unit(j)), offer_action(_unit(i, 2), _unit(j))) if i != j else None
        for j in range(5)
    ]
    for i in range(5)
]


class Game:
    __slots__ = (
        "n", "rng", "max_turns", "dev_before_roll", "player_trading", "max_offers",
        "offers_left", "offers_made", "offer", "player_trades", "embargo", "countered", "countered_offer", "responders", "responder_index", "responder", "acceptors",
        "hex_res", "hex_num", "hexes_by_roll", "robber", "node_pips", "port_of_node",
        "node_owner", "node_level", "edge_owner",
        "res", "bank", "rates",
        "dev_deck", "dev_hand", "dev_new", "dev_played", "knights", "vp_cards",
        "settlements_left", "cities_left", "roads_left",
        "settlements", "cities", "edges", "touch",
        "road_len", "longest_road", "largest_army",
        "current", "phase", "turn", "winner", "done",
        "setup_order", "setup_index", "last_settle",
        "after_robber", "after_free", "free_roads", "pending_discard", "discarder",
    )

    def __init__(self, num_players=4, seed=None, max_turns=2000, dev_before_roll=True,
                 player_trading=True, max_offers=None):
        self.n = n = num_players
        self.rng = rng = random.Random(seed)
        self.max_turns = max_turns
        # Official rule: a development card may be played before the roll.
        # Pass False for the house rule that cards wait until after it.
        self.dev_before_roll = dev_before_roll
        # Rulebook: on your turn you may trade with any player; the others may
        # only trade with you. max_offers optionally caps proposals per turn;
        # None means no limit.
        self.player_trading = player_trading
        self.max_offers = max_offers
        self.offers_left = -1 if max_offers is None else max_offers
        self.offers_made = set()  # offers turned down since the last trade
        self.offer = None  # (give counts, get counts)
        self.player_trades = 0
        self.embargo = [0] * n  # embargo[p] has bit q set while p refuses to trade with q
        self.countered = 0  # counter-offers the proposer accepted
        self.countered_offer = None  # the original offer while a counter is considered
        self.responders = []
        self.responder_index = 0
        self.responder = -1
        self.acceptors = []

        # Board
        self.hex_res = hex_res = _HEX_RESOURCES[:]
        rng.shuffle(hex_res)
        self.robber = hex_res.index(DESERT)
        numbers = _NUMBERS[:]
        # Rulebook: in a random set-up the red numbers (6 and 8) must not be
        # next to each other. Reshuffle until that holds.
        while True:
            rng.shuffle(numbers)
            hex_num = [0] * NUM_HEXES
            i = 0
            for h in range(NUM_HEXES):
                if hex_res[h] != DESERT:
                    hex_num[h] = numbers[i]
                    i += 1
            if not any(
                hex_num[h] in (6, 8) and hex_num[other] in (6, 8)
                for h in range(NUM_HEXES)
                for other in HEX_NEIGHBORS[h]
            ):
                break
        self.hex_num = hex_num
        self.hexes_by_roll = by_roll = [[] for _ in range(13)]
        for h in range(NUM_HEXES):
            if hex_num[h]:
                by_roll[hex_num[h]].append(h)
        self.node_pips = [sum(PIPS.get(hex_num[h], 0) for h in NODE_HEXES[node]) for node in range(NUM_NODES)]

        ports = _PORTS[:]
        rng.shuffle(ports)
        self.port_of_node = port_of_node = [-1] * NUM_NODES
        for e, port in zip(PORT_EDGES, ports):
            a, b = EDGE_NODES[e]
            port_of_node[a] = port_of_node[b] = port

        # Pieces
        self.node_owner = [-1] * NUM_NODES
        self.node_level = [0] * NUM_NODES  # 1 settlement, 2 city
        self.edge_owner = [-1] * NUM_EDGES

        # Cards
        self.res = [[0] * 5 for _ in range(n)]
        self.bank = [19] * 5
        self.rates = [[4] * 5 for _ in range(n)]
        self.dev_deck = _DEV_DECK[:]
        rng.shuffle(self.dev_deck)
        self.dev_hand = [[0] * 5 for _ in range(n)]  # playable
        self.dev_new = [[0] * 5 for _ in range(n)]  # bought this turn
        self.dev_played = False
        self.knights = [0] * n
        self.vp_cards = [0] * n

        # Per-player piece tracking
        self.settlements_left = [5] * n
        self.cities_left = [4] * n
        self.roads_left = [15] * n
        self.settlements = [[] for _ in range(n)]
        self.cities = [[] for _ in range(n)]
        self.edges = [[] for _ in range(n)]
        self.touch = [set() for _ in range(n)]  # nodes at the ends of own roads
        self.road_len = [0] * n
        self.longest_road = -1
        self.largest_army = -1

        # Turn state
        self.setup_order = list(range(n)) + list(range(n - 1, -1, -1))
        self.setup_index = 0
        self.current = 0
        self.phase = SETUP_SETTLE
        self.turn = 0
        self.winner = -1
        self.done = False
        self.last_settle = -1
        self.after_robber = MAIN
        self.after_free = MAIN
        self.free_roads = 0
        self.pending_discard = [0] * n
        self.discarder = -1

    # ------------------------------------------------------------------ queries

    @property
    def to_move(self):
        if self.phase == DISCARD:
            return self.discarder
        if self.phase == TRADE_RESPONSE:
            return self.responder
        return self.current

    def embargoed(self, a, b):
        """Whether a and b cannot trade because either has embargoed the other."""
        embargo = self.embargo
        return bool((embargo[a] >> b) & 1 or (embargo[b] >> a) & 1)

    def try_counter(self, give, get):
        """The counter-offer action if the responder may make it now, else 0.

        ``give`` is what the proposer would hand over and ``get`` what the
        proposer would receive. The terms must differ from the offer on the
        table, both sides must give something, and both must hold the cards.
        """
        if self.phase != TRADE_RESPONSE:
            return 0
        proposer = self.res[self.current]
        responder = self.res[self.responder]
        giving = getting = 0
        for r in range(5):
            g, t = give[r], get[r]
            if g > proposer[r] or t > responder[r] or (g and t):
                return 0
            giving += g
            getting += t
        if not giving or not getting or [list(give), list(get)] == [list(x) for x in self.offer]:
            return 0
        return counter_action(give, get)

    def victory_points(self, p):
        return (
            (5 - self.settlements_left[p])
            + 2 * (4 - self.cities_left[p])
            + self.vp_cards[p]
            + (2 if self.longest_road == p else 0)
            + (2 if self.largest_army == p else 0)
        )

    def public_points(self, p):
        """Points everyone can see: victory points without hidden victory point cards."""
        return self.victory_points(p) - self.vp_cards[p]

    def _free_spot(self, node):
        owner = self.node_owner
        if owner[node] >= 0:
            return False
        for m in NODE_NEIGHBORS[node]:
            if owner[m] >= 0:
                return False
        return True

    def road_spots(self, p):
        node_owner = self.node_owner
        edge_owner = self.edge_owner
        spots = set()
        for node in self.touch[p]:
            if node_owner[node] >= 0 and node_owner[node] != p:
                continue  # an opponent's building blocks building through it
            for e, _ in NODE_EDGES[node]:
                if edge_owner[e] < 0:
                    spots.add(e)
        return spots

    def settlement_spots(self, p):
        return [node for node in self.touch[p] if self._free_spot(node)]

    def can_offer(self, give, get):
        """Whether the current player may offer the cards ``give`` for the cards ``get``.

        Both sides must hand over at least one card (no gifts), no resource may
        appear on both sides, and someone must hold everything asked for.
        """
        return bool(self.try_offer(give, get))

    def try_offer(self, give, get):
        """The offer action for ``give`` and ``get`` if it is legal now, else 0."""
        if not (self.offers_left and self.player_trading) or self.phase != MAIN:
            return 0
        p = self.current
        hand = self.res[p]
        giving = getting = 0
        for r in range(5):
            g, t = give[r], get[r]
            if g > hand[r] or (g and t):
                return 0
            giving += g
            getting += t
        if not giving or not getting:
            return 0
        act = offer_action(give, get)
        if act in self.offers_made:
            return 0
        res = self.res
        embargo = self.embargo
        mine = embargo[p]
        for q in range(self.n):
            if q != p and not (mine >> q) & 1 and not (embargo[q] >> p) & 1:
                other = res[q]
                if (other[0] >= get[0] and other[1] >= get[1] and other[2] >= get[2]
                        and other[3] >= get[3] and other[4] >= get[4]):
                    return act
        return 0

    def legal_actions(self, offers=True):
        """Every legal action for the player to move.

        Trade offers are unbounded, so only one-for-one and two-for-one
        offers are listed. Build anything else with ``offer_action`` after
        checking ``can_offer``. Pass ``offers=False`` to list none.
        """
        phase = self.phase
        p = self.current
        if phase == MAIN:
            return self._main_actions(p, offers)
        if phase == ROLL:
            # Rulebook: one development card may be played at any time during
            # your turn, "even before you roll the dice".
            acts = [A_ROLL << 8]
            if self.dev_before_roll and not self.dev_played:
                self._dev_actions(p, acts)
            return acts
        if phase == ROBBER:
            return self._robber_actions(p)
        if phase == DISCARD:
            hand = self.res[self.discarder]
            return [(A_DISCARD << 8) | r for r in range(5) if hand[r]]
        if phase == TRADE_RESPONSE or phase == TRADE_COUNTER:
            # A responder can also counter; build that with try_counter.
            return [A_ACCEPT << 8, A_REJECT << 8]
        if phase == TRADE_PICK:
            acts = [(A_CONFIRM << 8) | q for q in self.acceptors]
            acts.append(A_REJECT << 8)
            return acts
        if phase == FREE_ROAD:
            return [(A_ROAD << 8) | e for e in self.road_spots(p)]
        if phase == SETUP_SETTLE:
            return [(A_SETTLE << 8) | node for node in range(NUM_NODES) if self._free_spot(node)]
        # SETUP_ROAD
        edge_owner = self.edge_owner
        return [(A_ROAD << 8) | e for e, _ in NODE_EDGES[self.last_settle] if edge_owner[e] < 0]

    def _main_actions(self, p, offers=True):
        hand = self.res[p]
        brick, lumber, ore, grain, wool = hand
        acts = []

        if brick and lumber and self.roads_left[p]:
            for e in self.road_spots(p):
                acts.append((A_ROAD << 8) | e)
        if brick and lumber and grain and wool and self.settlements_left[p]:
            for node in self.touch[p]:
                if self._free_spot(node):
                    acts.append((A_SETTLE << 8) | node)
        if ore >= 3 and grain >= 2 and self.cities_left[p]:
            for node in self.settlements[p]:
                acts.append((A_CITY << 8) | node)
        if ore and grain and wool and self.dev_deck:
            acts.append(A_BUY << 8)

        if not self.dev_played:
            self._dev_actions(p, acts)

        rates = self.rates[p]
        bank = self.bank
        for i in range(5):
            if hand[i] >= rates[i]:
                for j in range(5):
                    if j != i and bank[j]:
                        acts.append((A_TRADE << 8) | (i * 5 + j))

        if offers and self.offers_left and self.player_trading:
            res = self.res
            made = self.offers_made
            partners = [q for q in range(self.n) if q != p and not self.embargoed(p, q)]
            wanted = [any(res[q][j] for q in partners) for j in range(5)]
            for i in range(5):
                have = hand[i]
                if have:
                    row = _SIMPLE_OFFERS[i]
                    for j in range(5):
                        if j != i and wanted[j]:
                            one, two = row[j]
                            if one not in made:
                                acts.append(one)
                            if have >= 2 and two not in made:
                                acts.append(two)

        if offers and self.player_trading:
            mine = self.embargo[p]
            for q in range(self.n):
                if q != p:
                    acts.append(((A_LIFT if (mine >> q) & 1 else A_EMBARGO) << 8) | q)

        acts.append(A_END << 8)
        return acts

    def _dev_actions(self, p, acts):
        dev = self.dev_hand[p]
        if dev[KNIGHT]:
            acts.append(A_KNIGHT << 8)
        if dev[ROAD_BUILDING] and self.roads_left[p] and self.road_spots(p):
            acts.append(A_ROAD_BUILDING << 8)
        if dev[YEAR_OF_PLENTY]:
            bank = self.bank
            for i in range(5):
                if bank[i]:
                    for j in range(i, 5):
                        if bank[j] and (i != j or bank[i] >= 2):
                            acts.append((A_YEAR_OF_PLENTY << 8) | (i * 5 + j))
        if dev[MONOPOLY]:
            for r in range(5):
                acts.append((A_MONOPOLY << 8) | r)

    def _robber_actions(self, p):
        node_owner = self.node_owner
        res = self.res
        acts = []
        for h in range(NUM_HEXES):
            if h == self.robber:
                continue
            victims = set()
            for node in HEX_NODES[h]:
                o = node_owner[node]
                if o >= 0 and o != p and any(res[o]):
                    victims.add(o)
            if victims:
                for v in victims:
                    acts.append((A_ROBBER << 8) | (h * 8 + v + 1))
            else:
                acts.append((A_ROBBER << 8) | (h * 8))
        return acts

    # ------------------------------------------------------------------ actions

    def apply(self, act):
        kind = (act >> 8) & 255
        arg = act & 255
        p = self.current

        if kind == A_ROLL:
            self._roll()
        elif kind == A_END:
            self._end_turn(p)
        elif kind == A_ROAD:
            self._build_road(p, arg)
        elif kind == A_SETTLE:
            self._build_settlement(p, arg)
        elif kind == A_CITY:
            self._pay(p, 0, 0, 3, 2, 0)
            self.node_level[arg] = 2
            self.settlements[p].remove(arg)
            self.cities[p].append(arg)
            self.settlements_left[p] += 1
            self.cities_left[p] -= 1
        elif kind == A_BUY:
            self._pay(p, 0, 0, 1, 1, 1)
            card = self.dev_deck.pop()
            if card == VICTORY_POINT:
                self.vp_cards[p] += 1
            else:
                self.dev_new[p][card] += 1
        elif kind == A_TRADE:
            give, get = divmod(arg, 5)
            rate = self.rates[p][give]
            self.res[p][give] -= rate
            self.bank[give] += rate
            self.res[p][get] += 1
            self.bank[get] -= 1
        elif kind == A_OFFER:
            self._offer(p, act)
        elif kind == A_ACCEPT:
            if self.phase == TRADE_COUNTER:
                # The proposer takes the counter-offer; the original offer ends.
                self._swap(p, self.responder)
                self.countered += 1
                self.responder = -1
                self.phase = MAIN
            else:
                self.acceptors.append(self.responder)
                self._next_responder(p)
        elif kind == A_REJECT:
            if self.phase == TRADE_RESPONSE:
                self._next_responder(p)
            elif self.phase == TRADE_COUNTER:
                # Counter refused: the original offer goes on to the next player.
                self.offer = self.countered_offer
                self.phase = TRADE_RESPONSE
                self._next_responder(p)
            else:  # the proposer backs out of TRADE_PICK
                self.phase = MAIN
        elif kind == A_COUNTER:
            self.countered_offer = self.offer
            self.offer = decode_offer(act)
            self.phase = TRADE_COUNTER
        elif kind == A_EMBARGO:
            self.embargo[p] |= 1 << arg
        elif kind == A_LIFT:
            self.embargo[p] &= ~(1 << arg)
        elif kind == A_CONFIRM:
            self._swap(p, arg)
            self.phase = MAIN
        elif kind == A_ROBBER:
            self._move_robber(p, arg >> 3, (arg & 7) - 1)
        elif kind == A_DISCARD:
            self._discard(arg)
        elif kind == A_KNIGHT:
            self.dev_hand[p][KNIGHT] -= 1
            self.dev_played = True
            self.knights[p] += 1
            holder = self.largest_army
            if self.knights[p] >= 3 and (holder < 0 or self.knights[p] > self.knights[holder]):
                self.largest_army = p
            self.after_robber = self.phase
            self.phase = ROBBER
        elif kind == A_ROAD_BUILDING:
            self.dev_hand[p][ROAD_BUILDING] -= 1
            self.dev_played = True
            self.free_roads = min(2, self.roads_left[p])
            self.after_free = self.phase
            self.phase = FREE_ROAD
        elif kind == A_YEAR_OF_PLENTY:
            self.dev_hand[p][YEAR_OF_PLENTY] -= 1
            self.dev_played = True
            for r in divmod(arg, 5):
                self.res[p][r] += 1
                self.bank[r] -= 1
        elif kind == A_MONOPOLY:
            self.dev_hand[p][MONOPOLY] -= 1
            self.dev_played = True
            res = self.res
            for q in range(self.n):
                if q != p:
                    res[p][arg] += res[q][arg]
                    res[q][arg] = 0
        else:
            raise ValueError(f"unknown action {act}")

        if self.phase > SETUP_ROAD and not self.done and self.victory_points(self.current) >= WIN_POINTS:
            self.winner = self.current
            self.done = True

    def _pay(self, p, brick, lumber, ore, grain, wool):
        hand = self.res[p]
        bank = self.bank
        hand[0] -= brick
        hand[1] -= lumber
        hand[2] -= ore
        hand[3] -= grain
        hand[4] -= wool
        bank[0] += brick
        bank[1] += lumber
        bank[2] += ore
        bank[3] += grain
        bank[4] += wool

    def _offer(self, p, act):
        give, get = decode_offer(act)
        if self.offers_left > 0:
            self.offers_left -= 1
        self.offers_made.add(act)
        self.offer = (give, get)
        res = self.res
        n = self.n
        # Only players holding everything asked for are asked, in seat order.
        g0, g1, g2, g3, g4 = get
        responders = []
        embargo = self.embargo
        mine = embargo[p]
        for k in range(1, n):
            q = (p + k) % n
            if (mine >> q) & 1 or (embargo[q] >> p) & 1:
                continue
            other = res[q]
            if other[0] >= g0 and other[1] >= g1 and other[2] >= g2 and other[3] >= g3 and other[4] >= g4:
                responders.append(q)
        self.responders = responders
        self.acceptors = []
        self.responder_index = 0
        self.responder = self.responders[0]
        self.phase = TRADE_RESPONSE

    def _next_responder(self, p):
        self.responder_index += 1
        if self.responder_index < len(self.responders):
            self.responder = self.responders[self.responder_index]
            return
        self.responder = -1
        if not self.acceptors:
            self.phase = MAIN
        elif len(self.acceptors) == 1:
            self._swap(p, self.acceptors[0])
            self.phase = MAIN
        else:
            self.phase = TRADE_PICK

    def _swap(self, p, q):
        give, get = self.offer
        mine = self.res[p]
        theirs = self.res[q]
        for r in range(5):
            mine[r] += get[r] - give[r]
            theirs[r] += give[r] - get[r]
        self.player_trades += 1
        self.offers_made.clear()  # hands changed, so earlier offers may be worth repeating

    def _roll(self):
        rng = self.rng
        roll = rng.randrange(1, 7) + rng.randrange(1, 7)
        if roll == 7:
            pending = self.pending_discard
            first = -1
            for q in range(self.n):
                total = sum(self.res[q])
                if total > 7:
                    pending[q] = total // 2
                    if first < 0:
                        first = q
            self.after_robber = MAIN
            if first >= 0:
                self.discarder = first
                self.phase = DISCARD
            else:
                self.phase = ROBBER
            return

        self.phase = MAIN
        hexes = self.hexes_by_roll[roll]
        if not hexes:
            return
        n = self.n
        node_owner = self.node_owner
        node_level = self.node_level
        owed = [[0] * 5 for _ in range(n)]
        for h in hexes:
            if h == self.robber:
                continue
            r = self.hex_res[h]
            for node in HEX_NODES[h]:
                o = node_owner[node]
                if o >= 0:
                    owed[o][r] += node_level[node]
        bank = self.bank
        res = self.res
        for r in range(5):
            total = 0
            receivers = 0
            for q in range(n):
                if owed[q][r]:
                    total += owed[q][r]
                    receivers += 1
            if not total:
                continue
            if total <= bank[r]:
                for q in range(n):
                    res[q][r] += owed[q][r]
                bank[r] -= total
            elif receivers == 1:
                # Only one player is owed: they take what the bank has left.
                for q in range(n):
                    if owed[q][r]:
                        res[q][r] += bank[r]
                        bank[r] = 0
                        break
            # Otherwise the bank cannot pay everyone, so nobody gets this resource.

    def _discard(self, r):
        q = self.discarder
        self.res[q][r] -= 1
        self.bank[r] += 1
        pending = self.pending_discard
        pending[q] -= 1
        if pending[q]:
            return
        for nxt in range(q + 1, self.n):
            if pending[nxt]:
                self.discarder = nxt
                return
        self.discarder = -1
        self.phase = ROBBER

    def _move_robber(self, p, h, victim):
        self.robber = h
        if victim >= 0:
            hand = self.res[victim]
            pick = self.rng.randrange(sum(hand))
            for r in range(5):
                pick -= hand[r]
                if pick < 0:
                    hand[r] -= 1
                    self.res[p][r] += 1
                    break
        self.phase = self.after_robber

    def _build_road(self, p, e):
        phase = self.phase
        if phase == MAIN:
            self._pay(p, 1, 1, 0, 0, 0)
        self.edge_owner[e] = p
        self.roads_left[p] -= 1
        self.edges[p].append(e)
        a, b = EDGE_NODES[e]
        self.touch[p].add(a)
        self.touch[p].add(b)

        if phase == SETUP_ROAD:
            self.setup_index += 1
            if self.setup_index == len(self.setup_order):
                self.current = 0
                self.phase = ROLL
            else:
                self.current = self.setup_order[self.setup_index]
                self.phase = SETUP_SETTLE
            return

        length = self._longest_path(p)
        if length != self.road_len[p]:
            self.road_len[p] = length
            self._award_longest_road()

        if phase == FREE_ROAD:
            self.free_roads -= 1
            if not self.free_roads or not self.roads_left[p] or not self.road_spots(p):
                self.free_roads = 0
                self.phase = self.after_free

    def _build_settlement(self, p, node):
        setup = self.phase == SETUP_SETTLE
        if not setup:
            self._pay(p, 1, 1, 0, 1, 1)
        self.node_owner[node] = p
        self.node_level[node] = 1
        self.settlements_left[p] -= 1
        self.settlements[p].append(node)
        port = self.port_of_node[node]
        if port >= 0:
            rates = self.rates[p]
            if port == GENERIC_PORT:
                for r in range(5):
                    if rates[r] > 3:
                        rates[r] = 3
            else:
                rates[port] = 2

        if setup:
            self.last_settle = node
            if self.setup_index >= self.n:
                # The second settlement pays out one card per adjacent hex.
                for h in NODE_HEXES[node]:
                    r = self.hex_res[h]
                    if r >= 0:
                        self.res[p][r] += 1
                        self.bank[r] -= 1
            self.phase = SETUP_ROAD
            return

        # A new settlement can cut an opponent's road in two.
        changed = False
        edge_owner = self.edge_owner
        seen = set()
        for e, _ in NODE_EDGES[node]:
            q = edge_owner[e]
            if q >= 0 and q != p and q not in seen:
                seen.add(q)
                length = self._longest_path(q)
                if length != self.road_len[q]:
                    self.road_len[q] = length
                    changed = True
        if changed:
            self._award_longest_road()

    def _end_turn(self, p):
        hand = self.dev_hand[p]
        new = self.dev_new[p]
        for card in range(5):
            if new[card]:
                hand[card] += new[card]
                new[card] = 0
        self.dev_played = False
        self.offers_left = -1 if self.max_offers is None else self.max_offers
        self.offers_made.clear()
        self.current = (p + 1) % self.n
        self.phase = ROLL
        self.turn += 1
        if self.turn >= self.max_turns:
            self.done = True

    # ------------------------------------------------------------------ longest road

    def _longest_path(self, p):
        """Length of p's longest continuous road, in edges."""
        edge_owner = self.edge_owner
        node_owner = self.node_owner
        used = set()
        best = 0

        def walk(node, length):
            nonlocal best
            if length > best:
                best = length
            for e, nxt in NODE_EDGES[node]:
                if edge_owner[e] == p and e not in used:
                    used.add(e)
                    o = node_owner[nxt]
                    if o >= 0 and o != p:
                        # An opponent's building ends the road here.
                        if length + 1 > best:
                            best = length + 1
                    else:
                        walk(nxt, length + 1)
                    used.discard(e)

        for start in self.touch[p]:
            walk(start, 0)
        return best

    def _award_longest_road(self):
        lengths = self.road_len
        top = max(lengths)
        if top < 5:
            self.longest_road = -1
            return
        leaders = [q for q in range(self.n) if lengths[q] == top]
        if self.longest_road in leaders:
            return  # the holder keeps it on a tie
        self.longest_road = leaders[0] if len(leaders) == 1 else -1
