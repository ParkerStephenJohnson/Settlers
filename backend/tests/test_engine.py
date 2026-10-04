import pytest

from src.engine import Game, GreedyBot, RandomBot
from src.engine.game import (
    A_KNIGHT,
    A_MONOPOLY,
    A_ROAD,
    A_ROAD_BUILDING,
    A_ROLL,
    A_SETTLE,
    FREE_ROAD,
    KNIGHT,
    MAIN,
    MONOPOLY,
    ROAD_BUILDING,
    ROLL,
    SETUP_ROAD,
    SETUP_SETTLE,
    WIN_POINTS,
    action,
)
from src.engine.simulate import play_game, play_game_stats, simulate, summarize
from src.engine.topology import (
    COASTAL_EDGES,
    HEX_NEIGHBORS,
    EDGE_NODES,
    HEX_NODES,
    NODE_EDGES,
    NODE_NEIGHBORS,
    PORT_EDGES,
)


def check_invariants(game):
    # Every resource card is either in the bank or in a hand.
    for r in range(5):
        assert game.bank[r] >= 0
        assert game.bank[r] + sum(hand[r] for hand in game.res) == 19
    for p in range(game.n):
        assert all(count >= 0 for count in game.res[p])
        assert len(game.settlements[p]) == 5 - game.settlements_left[p]
        assert len(game.cities[p]) == 4 - game.cities_left[p]
        assert len(game.edges[p]) == 15 - game.roads_left[p]
        assert 0 <= game.settlements_left[p] <= 5
        assert 0 <= game.cities_left[p] <= 4
        assert 0 <= game.roads_left[p] <= 15
    # Distance rule: no two buildings on neighbouring nodes.
    for node, owner in enumerate(game.node_owner):
        if owner >= 0:
            assert all(game.node_owner[m] < 0 for m in NODE_NEIGHBORS[node])
    # 25 development cards, wherever they are.
    held = sum(sum(h) for h in game.dev_hand) + sum(sum(h) for h in game.dev_new)
    played = sum(game.knights)
    assert len(game.dev_deck) + held + sum(game.vp_cards) + played <= 25


def test_topology_matches_the_classic_board():
    assert len(HEX_NODES) == 19
    assert len(NODE_EDGES) == 54
    assert len(EDGE_NODES) == 72
    assert len(COASTAL_EDGES) == 30
    assert {len(n) for n in NODE_NEIGHBORS} == {2, 3}


def test_nine_ports_share_no_nodes():
    nodes = [n for e in PORT_EDGES for n in EDGE_NODES[e]]
    assert len(PORT_EDGES) == 9
    assert len(set(nodes)) == 18


def test_setup_places_two_settlements_and_two_roads_each():
    game = Game(4, seed=1)
    bot = GreedyBot()
    while game.phase in (SETUP_SETTLE, SETUP_ROAD):
        game.apply(bot.choose(game, game.legal_actions()))
    for p in range(4):
        assert len(game.settlements[p]) == 2
        assert len(game.edges[p]) == 2
        assert 1 <= sum(game.res[p]) <= 3  # one card per hex next to the second settlement
    check_invariants(game)


@pytest.mark.parametrize("seed", range(20))
def test_greedy_games_finish_with_a_winner_and_keep_invariants(seed):
    game = Game(4, seed=seed)
    bot = GreedyBot()
    steps = 0
    while not game.done:
        actions = game.legal_actions()
        assert actions, f"no legal actions in phase {game.phase}"
        game.apply(bot.choose(game, actions))
        steps += 1
        if steps % 25 == 0:
            check_invariants(game)
    check_invariants(game)
    assert game.winner >= 0
    assert game.victory_points(game.winner) >= WIN_POINTS


@pytest.mark.parametrize("seed", range(5))
def test_random_games_keep_invariants(seed):
    game = Game(4, seed=seed, max_turns=300)
    bot = RandomBot()
    while not game.done:
        actions = game.legal_actions()
        assert actions
        game.apply(bot.choose(game, actions))
        check_invariants(game)


@pytest.mark.parametrize("players", [2, 3, 4])
def test_supports_two_to_four_players(players):
    winner, turns, points = play_game(seed=3, num_players=players)
    assert 0 <= winner < players
    assert len(points) == players


def test_same_seed_gives_the_same_game():
    assert play_game(seed=42) == play_game(seed=42)
    assert simulate(20, seed=7) == simulate(20, seed=7)


def _game_with_roads(owner_edges):
    """A game past setup with the given roads placed, for longest-road checks."""
    game = Game(2, seed=0)
    bot = GreedyBot()
    while game.phase in (SETUP_SETTLE, SETUP_ROAD):
        game.apply(bot.choose(game, game.legal_actions()))
    for p in range(2):
        for e in game.edges[p]:
            game.edge_owner[e] = -1
        game.edges[p] = []
        game.touch[p] = set()
    for p, edges in owner_edges.items():
        for e in edges:
            game.edge_owner[e] = p
            game.edges[p].append(e)
            game.touch[p].update(EDGE_NODES[e])
    return game


def _ring_edges(count, hex_id=9):
    """The first ``count`` edges walking around one hex, in order."""
    edge_of = {nodes: e for e, nodes in enumerate(EDGE_NODES)}
    corners = HEX_NODES[hex_id]
    ring = []
    for i in range(count):
        a, b = corners[i], corners[(i + 1) % 6]
        ring.append(edge_of[(min(a, b), max(a, b))])
    return ring


def _clear_buildings(game):
    for node in range(54):
        game.node_owner[node] = -1


def test_longest_road_counts_a_simple_path():
    game = _game_with_roads({0: _ring_edges(5)})
    _clear_buildings(game)
    assert game._longest_path(0) == 5


def test_longest_road_counts_a_closed_loop():
    game = _game_with_roads({0: _ring_edges(6)})
    _clear_buildings(game)
    assert game._longest_path(0) == 6


def test_opponent_settlement_breaks_a_road():
    edges = _ring_edges(5)
    game = _game_with_roads({0: edges})
    _clear_buildings(game)
    # Put an opponent building on the node between the 3rd and 4th road.
    shared = set(EDGE_NODES[edges[2]]) & set(EDGE_NODES[edges[3]])
    game.node_owner[shared.pop()] = 1
    assert game._longest_path(0) == 3


def test_longest_road_needs_five_and_holder_keeps_ties():
    game = _game_with_roads({})
    game.road_len = [4, 0]
    game._award_longest_road()
    assert game.longest_road == -1
    game.road_len = [5, 0]
    game._award_longest_road()
    assert game.longest_road == 0
    game.road_len = [5, 5]
    game._award_longest_road()
    assert game.longest_road == 0
    game.road_len = [5, 6]
    game._award_longest_road()
    assert game.longest_road == 1


def test_illegal_looking_actions_are_never_offered():
    game = Game(4, seed=5)
    bot = GreedyBot()
    while not game.done:
        actions = game.legal_actions()
        p = game.current
        if game.phase == MAIN:
            for a in actions:
                kind, arg = a >> 8, a & 255
                if kind == A_ROAD:
                    assert game.edge_owner[arg] < 0
                    assert game.res[p][0] >= 1 and game.res[p][1] >= 1
                elif kind == A_SETTLE:
                    assert game.node_owner[arg] < 0
        game.apply(bot.choose(game, actions))
    assert action(A_ROAD, 3) >> 8 == A_ROAD


def _after_setup(seed=0, **kwargs):
    game = Game(4, seed=seed, **kwargs)
    bot = GreedyBot()
    while game.phase in (SETUP_SETTLE, SETUP_ROAD):
        game.apply(bot.choose(game, game.legal_actions()))
    assert game.phase == ROLL
    return game


@pytest.mark.parametrize("seed", range(50))
def test_red_numbers_are_never_adjacent(seed):
    # Rulebook, variable set-up: "the tokens with the red numbers must not be next to each other."
    game = Game(4, seed=seed)
    for h, number in enumerate(game.hex_num):
        if number in (6, 8):
            assert all(game.hex_num[other] not in (6, 8) for other in HEX_NEIGHBORS[h])
    assert sorted(n for n in game.hex_num if n) == [2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12]


def test_any_development_card_can_be_played_before_the_roll():
    # Rulebook: "You can play the card at any time, even before you roll the dice."
    game = _after_setup()
    p = game.current
    game.dev_hand[p][KNIGHT] = 1
    game.dev_hand[p][MONOPOLY] = 1
    game.dev_hand[p][ROAD_BUILDING] = 1
    kinds = {a >> 8 for a in game.legal_actions()}
    assert {A_ROLL, A_KNIGHT, A_MONOPOLY, A_ROAD_BUILDING} <= kinds


def test_only_one_development_card_per_turn():
    game = _after_setup()
    p = game.current
    game.dev_hand[p][MONOPOLY] = 2
    game.apply(action(A_MONOPOLY, 0))
    assert game.phase == ROLL
    assert {a >> 8 for a in game.legal_actions()} == {A_ROLL}


def test_road_building_before_the_roll_returns_to_the_roll():
    game = _after_setup()
    p = game.current
    game.dev_hand[p][ROAD_BUILDING] = 1
    game.apply(action(A_ROAD_BUILDING))
    assert game.phase == FREE_ROAD
    game.apply(game.legal_actions()[0])
    game.apply(game.legal_actions()[0])
    assert game.phase == ROLL
    assert len(game.edges[p]) == 4


def test_house_rule_can_forbid_cards_before_the_roll():
    game = _after_setup(dev_before_roll=False)
    game.dev_hand[game.current][KNIGHT] = 1
    assert {a >> 8 for a in game.legal_actions()} == {A_ROLL}


def test_a_card_bought_this_turn_cannot_be_played_until_the_next():
    game = _after_setup()
    p = game.current
    game.dev_new[p][KNIGHT] = 1
    assert A_KNIGHT not in {a >> 8 for a in game.legal_actions()}


def test_win_statistics_add_up():
    results = simulate(200, seed=11)
    summary = summarize(results, 4)
    assert summary["finished"] == sum(summary["wins"])
    assert sum(count for _, count in summary["winning_moves"]) == summary["finished"]
    for winner, turns, move, points in results:
        if winner >= 0:
            assert sum(points) >= WIN_POINTS
    assert play_game_stats(5) == play_game_stats(5)
