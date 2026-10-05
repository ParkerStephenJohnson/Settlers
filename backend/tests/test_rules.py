"""Rule-by-rule tests for areas the whole-game tests only cover indirectly.

Each test cites the rule it checks, from the CATAN base game rules and almanac
(2020 edition).
"""
import pytest

from src.engine import Game, RandomBot
from src.engine.game import (
    A_DISCARD,
    A_ROBBER,
    A_ROLL,
    A_SETTLE,
    A_TRADE,
    DISCARD,
    GENERIC_PORT,
    MAIN,
    ROBBER,
    ROLL,
    SETUP_ROAD,
    SETUP_SETTLE,
    action,
    kind_of,
)
from src.engine.topology import EDGE_NODES, HEX_NODES, PORT_EDGES


def cards(**counts):
    names = ("brick", "lumber", "ore", "grain", "wool")
    return [counts.get(name, 0) for name in names]


EMPTY = cards()
BRICK, LUMBER, ORE, GRAIN, WOOL = range(5)


def after_setup(seed=0, players=4):
    game = Game(players, seed=seed)
    bot = RandomBot()
    while game.phase in (SETUP_SETTLE, SETUP_ROAD):
        game.apply(bot.choose(game, game.legal_actions()))
    return game


def with_hands(game, hands):
    game.res = [list(h) for h in hands]
    for r in range(5):
        game.bank[r] = 19 - sum(h[r] for h in hands)
    return game


class Dice:
    """Stands in for the game's random source so a test can fix the next roll."""

    def __init__(self, *values):
        self.values = list(values)

    def randrange(self, *args):
        return self.values.pop(0)


def roll(game, total):
    """Roll exactly ``total`` on the current player's turn."""
    real = game.rng
    game.rng = Dice(1, total - 1)
    game.phase = ROLL
    game.apply(action(A_ROLL))
    game.rng = real


def bank_trades(game):
    return {divmod(a & 255, 5) for a in game.legal_actions(False) if kind_of(a) == A_TRADE}


# ---------------------------------------------------------------- maritime trade
# "You can always trade at 4:1 ... If you have a settlement or city on a
# harbor, you can trade with the bank more favorably: at either a 3:1 ratio or,
# in certain harbors, at 2:1 (trading the resource type shown)."


def test_bank_trade_is_four_for_one_without_a_harbour():
    game = with_hands(after_setup(), [cards(brick=4, wool=3), EMPTY, EMPTY, EMPTY])
    game.rates[0] = [4] * 5
    game.phase = MAIN
    assert {give for give, _ in bank_trades(game)} == {BRICK}  # three wool is not enough
    game.apply(action(A_TRADE, BRICK * 5 + ORE))
    assert game.res[0] == cards(wool=3, ore=1)
    assert game.bank[BRICK] == 19 and game.bank[ORE] == 18


def test_nine_harbours_four_generic_and_one_per_resource():
    game = Game(4, seed=1)
    ports = []
    for e in PORT_EDGES:
        a, b = EDGE_NODES[e]
        assert game.port_of_node[a] == game.port_of_node[b] >= 0
        ports.append(game.port_of_node[a])
    assert sorted(ports) == [0, 1, 2, 3, 4, 5, 5, 5, 5]
    assert sum(1 for p in game.port_of_node if p >= 0) == 18


def test_settling_on_a_harbour_sets_the_rate():
    game = Game(4, seed=1)
    generic = next(n for n, p in enumerate(game.port_of_node) if p == GENERIC_PORT)
    game.apply(action(A_SETTLE, generic))
    assert game.rates[0] == [3] * 5

    game = Game(4, seed=1)
    wool = next(n for n, p in enumerate(game.port_of_node) if p == WOOL)
    game.apply(action(A_SETTLE, wool))
    assert game.rates[0] == [4, 4, 4, 4, 2]


def test_a_two_for_one_harbour_trades_only_its_own_resource():
    game = with_hands(after_setup(), [cards(wool=2, brick=2), EMPTY, EMPTY, EMPTY])
    game.rates[0] = [4, 4, 4, 4, 2]
    game.phase = MAIN
    assert {give for give, _ in bank_trades(game)} == {WOOL}
    game.apply(action(A_TRADE, WOOL * 5 + ORE))
    assert game.res[0] == cards(brick=2, ore=1)


def test_the_bank_cannot_give_a_card_it_does_not_have():
    game = with_hands(after_setup(), [cards(brick=4), cards(ore=19), EMPTY, EMPTY])
    game.rates[0] = [4] * 5
    game.phase = MAIN
    assert game.bank[ORE] == 0
    assert ORE not in {get for _, get in bank_trades(game)}


# ---------------------------------------------------------------- rolling a 7
# "Any player with more than 7 resource cards (i.e., 8 or more) must choose and
# discard half of them ... If you hold an odd number of cards, round down."


def test_seven_cards_are_safe_and_eight_must_discard_half():
    game = with_hands(after_setup(), [cards(brick=7), cards(ore=8), cards(grain=9), EMPTY])
    roll(game, 7)
    assert game.pending_discard == [0, 4, 4, 0]
    assert game.phase == DISCARD and game.to_move == 1


def test_discards_go_back_to_the_bank_and_then_the_robber_moves():
    game = with_hands(after_setup(), [EMPTY, cards(ore=8), cards(grain=9), EMPTY])
    roll(game, 7)
    for _ in range(4):
        assert game.to_move == 1
        game.apply(action(A_DISCARD, ORE))
    for _ in range(4):
        assert game.to_move == 2
        game.apply(action(A_DISCARD, GRAIN))
    assert game.res[1] == cards(ore=4) and game.res[2] == cards(grain=5)
    assert game.bank[ORE] == 15 and game.bank[GRAIN] == 14
    assert game.phase == ROBBER and game.to_move == game.current


def test_a_player_can_only_discard_cards_it_holds():
    game = with_hands(after_setup(), [EMPTY, cards(ore=5, wool=3), EMPTY, EMPTY])
    roll(game, 7)
    assert {a & 255 for a in game.legal_actions()} == {ORE, WOOL}


def test_no_resources_are_produced_on_a_seven():
    game = with_hands(after_setup(), [EMPTY, EMPTY, EMPTY, EMPTY])
    roll(game, 7)
    assert all(hand == EMPTY for hand in game.res)
    assert game.phase == ROBBER


# ---------------------------------------------------------------- the robber
# "You must move the robber immediately to the number token of any other
# terrain hex or to the desert hex. Then you steal 1 (random) resource card
# from an opponent who has a settlement or city adjacent to the target hex."


def robber_moves(game):
    return [((a & 255) >> 3, ((a & 255) & 7) - 1) for a in game.legal_actions() if kind_of(a) == A_ROBBER]


def test_the_robber_must_move_to_a_different_hex():
    game = with_hands(after_setup(), [EMPTY, cards(ore=1), cards(ore=1), cards(ore=1)])
    game.phase = ROBBER
    hexes = {h for h, _ in robber_moves(game)}
    assert game.robber not in hexes
    assert len(hexes) == 18


def test_victims_must_be_opponents_on_the_hex_holding_cards():
    game = with_hands(after_setup(seed=2), [cards(brick=2), cards(ore=1), EMPTY, cards(wool=1)])
    game.phase = ROBBER
    for h, victim in robber_moves(game):
        owners = {game.node_owner[n] for n in HEX_NODES[h]} - {-1, game.current}
        with_cards = {o for o in owners if any(game.res[o])}
        if victim >= 0:
            assert victim in with_cards
        else:
            assert not with_cards  # nobody to rob there, so the move robs nobody


def test_stealing_moves_exactly_one_card_between_the_two_players():
    game = with_hands(after_setup(seed=2), [EMPTY, cards(ore=3), EMPTY, EMPTY])
    game.phase = ROBBER
    h, victim = next(m for m in robber_moves(game) if m[1] == 1)
    game.apply(action(A_ROBBER, h * 8 + victim + 1))
    assert game.robber == h
    assert game.res[0] == cards(ore=1) and game.res[1] == cards(ore=2)
    assert game.bank[ORE] == 16
    assert game.phase == MAIN


def test_the_stolen_card_is_drawn_at_random_from_the_whole_hand():
    taken = set()
    for seed in range(40):
        game = with_hands(after_setup(seed=2), [EMPTY, cards(ore=1, wool=1, grain=1), EMPTY, EMPTY])
        game.rng.seed(seed)
        game.phase = ROBBER
        h, victim = next(m for m in robber_moves(game) if m[1] == 1)
        game.apply(action(A_ROBBER, h * 8 + victim + 1))
        taken.add(game.res[0].index(1))
    assert taken == {ORE, GRAIN, WOOL}


def test_a_robbed_hex_produces_nothing():
    game = with_hands(after_setup(seed=3), [EMPTY, EMPTY, EMPTY, EMPTY])
    number = next(n for n in (6, 8, 5, 9, 4, 10) if any(
        game.node_owner[node] >= 0 for h in game.hexes_by_roll[n] for node in HEX_NODES[h]))
    producing = [h for h in game.hexes_by_roll[number] if any(game.node_owner[n] >= 0 for n in HEX_NODES[h])]
    for h in producing:
        blocked = with_hands(after_setup(seed=3), [EMPTY, EMPTY, EMPTY, EMPTY])
        blocked.robber = h
        roll(blocked, number)
        open_game = with_hands(after_setup(seed=3), [EMPTY, EMPTY, EMPTY, EMPTY])
        open_game.robber = next(x for x in range(19) if x not in blocked.hexes_by_roll[number])
        roll(open_game, number)
        assert sum(map(sum, blocked.res)) < sum(map(sum, open_game.res))


# ---------------------------------------------------------------- production
# "You receive 1 resource card for each settlement ... 2 resource cards for
# each city." and, on shortages: "no player receives any of that resource that
# turn. Exception: If the shortage only affects a single player, give that
# player as many of these resources as are left."


def production_setup(seed=3):
    game = with_hands(after_setup(seed=seed), [EMPTY, EMPTY, EMPTY, EMPTY])
    for number in (6, 8, 5, 9, 4, 10, 3, 11):
        for h in game.hexes_by_roll[number]:
            owners = [game.node_owner[n] for n in HEX_NODES[h] if game.node_owner[n] >= 0]
            if owners and h != game.robber and len(game.hexes_by_roll[number]) >= 1:
                return game, number
    pytest.skip("no producing hex on this board")


def test_a_city_produces_two_cards_where_a_settlement_produces_one():
    game, number = production_setup()
    roll(game, number)
    as_settlements = [sum(hand) for hand in game.res]

    game, number = production_setup()
    for node, owner in enumerate(game.node_owner):
        if owner >= 0:
            game.node_level[node] = 2
    roll(game, number)
    assert [sum(hand) for hand in game.res] == [2 * n for n in as_settlements]


def shortage_case(shared, cities=False):
    """A board, roll and resource owed to several players (shared) or to exactly one."""
    for seed in range(200):
        game = with_hands(after_setup(seed=seed), [EMPTY, EMPTY, EMPTY, EMPTY])
        if cities:
            for node, owner in enumerate(game.node_owner):
                if owner >= 0:
                    game.node_level[node] = 2
        for number in (6, 8, 5, 9, 4, 10, 3, 11, 2, 12):
            owed = {}
            for h in game.hexes_by_roll[number]:
                if h == game.robber:
                    continue
                for n in HEX_NODES[h]:
                    o = game.node_owner[n]
                    if o >= 0:
                        owed.setdefault(game.hex_res[h], set()).add(o)
            for r, owners in owed.items():
                if (len(owners) >= 2) == shared:
                    return game, number, r, owners
    raise AssertionError("no suitable board found")


def test_a_shortage_affecting_several_players_pays_nobody():
    game, number, r, owners = shortage_case(shared=True)
    game.bank[r] = 1  # not enough for everyone
    roll(game, number)
    assert all(hand[r] == 0 for hand in game.res)
    assert game.bank[r] == 1


def test_a_shortage_affecting_one_player_pays_what_is_left():
    game, number, r, owners = shortage_case(shared=False, cities=True)  # a city is owed two
    player = next(iter(owners))
    game.bank[r] = 1
    roll(game, number)
    assert game.res[player][r] == 1
    assert game.bank[r] == 0


def test_harbours_sit_on_the_official_frame_slots():
    # (land hex as axial coordinates from the centre, side of that hex facing the sea)
    official = [((2, 0), "E"), ((1, 1), "SE"), ((-1, 2), "SE"), ((-2, 2), "SW"), ((-2, 1), "W"),
                ((-1, -1), "W"), ((0, -2), "NW"), ((1, -2), "NE"), ((2, -1), "NE")]
    side = {"NE": 0, "E": 1, "SE": 2, "SW": 3, "W": 4, "NW": 5}
    axial = []
    for row, count, start in [(0, 3, 1), (1, 4, 0), (2, 5, 0), (3, 4, 0), (4, 3, 1)]:
        for col in range(start, start + count):
            axial.append((col - (row - (row & 1)) // 2 - 1, row - 2))
    edge_of = {nodes: e for e, nodes in enumerate(EDGE_NODES)}
    expected = set()
    for coords, name in official:
        corners = HEX_NODES[axial.index(coords)]
        a, b = corners[side[name]], corners[(side[name] + 1) % 6]
        expected.add(edge_of[(min(a, b), max(a, b))])
    assert set(PORT_EDGES) == expected
