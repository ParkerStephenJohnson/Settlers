from src.engine import Game, plan_search
from src.engine.game import A_BUY, A_CITY, A_ROAD, A_SETTLE, MAIN, SETUP_ROAD, SETUP_SETTLE, kind_of
from src.engine.plans import CITY, PLAN, Planner
from src.engine.simulate import run_game
from src.engine.strategy import STANDARD, StrategyBot
from src.engine.topology import EDGE_NODES


def cards(**counts):
    names = ("brick", "lumber", "ore", "grain", "wool")
    return [counts.get(name, 0) for name in names]


EMPTY = cards()


def in_main(hands, seed=0):
    game = Game(4, seed=seed)
    setup = StrategyBot()
    while game.phase in (SETUP_SETTLE, SETUP_ROAD):
        game.apply(setup.choose(game, game.legal_actions(False)))
    for r in range(5):
        game.bank[r] = 19 - sum(hand[r] for hand in hands)
    game.res = [list(hand) for hand in hands]
    game.phase = MAIN
    return game


def test_reachable_counts_roads_and_names_the_first_one():
    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    reach = Planner._reachable(game, 0, 3)
    for node, (roads, first) in reach.items():
        assert 0 <= roads <= 3
        if roads == 0:
            assert node in game.touch[0] and first == -1
        else:
            assert game.edge_owner[first] < 0
            assert set(EDGE_NODES[first]) & game.touch[0]  # the first road joins the network
    assert max(roads for roads, _ in reach.values()) == 3
    assert len(Planner._reachable(game, 0, 1)) < len(reach)


def test_an_opponent_building_blocks_the_route():
    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    reach = Planner._reachable(game, 0, 3)
    for node in reach:
        assert game.node_owner[node] in (-1, 0)


def test_a_plan_for_a_distant_spot_asks_for_the_roads_too():
    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    game.cities_left[0] = 0  # leave only settlements and cards to plan for
    game.dev_deck.clear()
    plan = Planner(reach=3).plan(game, 0)
    assert plan.step in ("road", "settlement")
    assert plan.cost == (1 + plan.roads, 1 + plan.roads, 0, 1, 1)
    assert kind_of(plan.action) == (A_ROAD if plan.roads else A_SETTLE)
    assert game._free_spot(plan.target)


def test_city_value_shifts_the_plan_between_cities_and_expansion():
    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    assert Planner(reach=2, city_value=50.0).plan(game, 0).step == "city"
    assert Planner(reach=2, city_value=0.01, dev_value=0.0).plan(game, 0).step in ("road", "settlement")
    assert Planner(reach=2, city_value=0.01, dev_value=500.0).plan(game, 0).action == A_BUY << 8


def test_the_bot_takes_the_plans_step_when_it_can_afford_it():
    game = in_main([cards(ore=3, grain=2), EMPTY, EMPTY, EMPTY])
    bot = StrategyBot(plan=Planner(reach=2, city_value=50.0))
    choice = bot.choose(game, game.legal_actions(False))
    assert kind_of(choice) == A_CITY
    assert game.goals[0] == CITY  # the plan is published for the other behaviors


def test_a_planning_bot_builds_the_road_its_plan_names():
    game = in_main([cards(brick=1, lumber=1), EMPTY, EMPTY, EMPTY])
    planner = Planner(reach=3, city_value=0.01, dev_value=0.0)
    plan = planner.plan(game, 0)
    choice = StrategyBot(plan=planner).choose(game, game.legal_actions(False))
    if plan.step == "road":
        assert choice == plan.action
    else:
        assert kind_of(choice) != A_ROAD or choice == plan.action


def test_trade_answers_follow_the_published_plan():
    from src.engine.game import A_ACCEPT, A_REJECT, offer_action

    # Player 1 plans a city, so ore helps and a brick-for-wool swap does not.
    planner = Planner(reach=2, city_value=50.0)
    game = in_main([cards(ore=1, brick=1), cards(ore=2, grain=2, wool=2), EMPTY, EMPTY])
    game.apply(offer_action(cards(ore=1), cards(wool=1)))
    assert kind_of(StrategyBot(plan=planner).choose(game, game.legal_actions(False))) == A_ACCEPT
    assert game.goals[1] == CITY

    game = in_main([cards(ore=1, brick=1), cards(ore=2, grain=2, wool=2), EMPTY, EMPTY])
    game.apply(offer_action(cards(brick=1), cards(wool=1)))
    assert kind_of(StrategyBot(plan=planner).choose(game, game.legal_actions(False))) == A_REJECT


def test_every_plan_variant_finishes_games():
    for name in PLAN:
        game = run_game([StrategyBot(plan=name)] + [StrategyBot() for _ in range(3)], seed=3)
        assert game.winner >= 0, name
    assert STANDARD["plan"] in PLAN


def test_plan_search_stays_in_range_and_repeats():
    import random

    rng = random.Random(2)
    params = plan_search.random_params(rng)
    for _ in range(40):
        params = plan_search.mutate(params, rng, strength=1.0)
        assert all(low <= params[name] <= high for name, (low, high) in plan_search.RANGES.items())
    assert 1 <= plan_search.make(params).reach <= 4
    quiet = {"generations": 2, "population": 5, "games": 8, "survivors": 2, "seed": 1, "log": lambda *_: None}
    assert plan_search.search(**quiet) == plan_search.search(**quiet)


def test_contest_discounts_a_spot_an_opponent_reaches_first():
    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    game.cities_left[0] = 0
    game.dev_deck.clear()
    plain = Planner(reach=3).plan(game, 0)
    rivals = Planner(reach=3)._rival_distance(game, 0)
    wary = Planner(reach=3, contest=0.99).plan(game, 0)
    theirs = rivals.get(wary.target, 99)
    assert theirs >= wary.roads or wary.target == plain.target  # it avoids races it would lose
    assert all(roads >= 0 for roads in rivals.values())


def test_army_value_makes_a_card_worth_more_as_largest_army_gets_close():
    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    keen = Planner(reach=2, city_value=0.01, dev_value=0.0, army_value=5000.0)
    assert keen.plan(game, 0).action == A_BUY << 8
    game.largest_army = 0  # already holding it, so no extra pull toward cards
    assert keen.plan(game, 0).action != A_BUY << 8


def test_longest_road_plan_names_a_road_that_lengthens_the_road():
    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    need = 5 - game.road_len[0]  # nobody holds Longest Road yet, so five roads take it
    plan = Planner(reach=2, city_value=0.01, dev_value=0.0, road_value=5000.0, road_reach=5).plan(game, 0)
    assert plan.kind == "longest_road" and plan.roads == need
    assert plan.cost == (need, need, 0, 0, 0)
    edge = plan.action & 255
    before = game._longest_path(0)
    game.edge_owner[edge] = 0
    game.touch[0].update(EDGE_NODES[edge])
    assert game._longest_path(0) > before


def test_plan_aware_robber_prefers_a_victim_who_produces_what_the_plan_lacks():
    from src.engine.game import A_ROBBER, ROBBER

    game = in_main([EMPTY, cards(ore=1), cards(ore=1), cards(ore=1)])
    game.goals[0] = CITY
    game.phase = ROBBER
    choice = StrategyBot(robber="plan_aware").choose(game, game.legal_actions(False))
    assert kind_of(choice) == A_ROBBER
    own = {h for h in range(19) if any(game.node_owner[n] == 0 for n in __import__(
        "src.engine.topology", fromlist=["HEX_NODES"]).HEX_NODES[h])}
    assert ((choice & 255) >> 3) not in own


def test_league_counts_one_winner_per_game_and_repeats():
    from src.engine import league

    totals, turns = league.play(games=30, seed=2)
    assert sum(wins for wins, _, _ in totals.values()) == 30
    assert sum(played for _, played, _ in totals.values()) == 120
    assert turns > 0
    assert (totals, turns) == league.play(games=30, seed=2)


def test_reusing_plans_gives_exactly_the_same_games():
    def play():
        return [(g.winner, g.turn) for g in (run_game([StrategyBot() for _ in range(4)], seed) for seed in range(12))]

    cached = play()
    original = StrategyBot._plan
    StrategyBot._plan = lambda self, game, p: self.planner.plan(game, p)
    try:
        assert play() == cached
    finally:
        StrategyBot._plan = original


def test_endgame_takes_the_cheapest_points_once_close_to_winning():
    # One card short of a settlement on a poor spot, three short of a city on a rich one.
    game = in_main([cards(brick=1, lumber=1, grain=1), EMPTY, EMPTY, EMPTY])
    game.dev_deck.clear()
    patient = Planner(reach=0, city_value=500.0)
    closer = Planner(reach=0, city_value=500.0, endgame_at=1)
    assert patient.plan(game, 0).step == "city"
    if any(game._free_spot(n) for n in game.touch[0]):
        assert closer.plan(game, 0).step == "settlement"
    assert Planner(reach=0, city_value=500.0, endgame_at=9).plan(game, 0).step == "city"  # not close yet


def test_counting_cards_picks_the_monopoly_resource_opponents_actually_hold():
    from src.engine.game import A_MONOPOLY, MONOPOLY

    # Saving for a city: missing 3 ore and 2 grain. Opponents hold grain but no ore.
    hands = [EMPTY, cards(grain=3), cards(grain=2), EMPTY]
    game = in_main(hands)
    game.dev_hand[0][MONOPOLY] = 1
    city = Planner(reach=0, city_value=500.0)
    counting = StrategyBot(plan=city, count="on", propose="none", bank="never")
    choice = counting.choose(game, game.legal_actions(False))
    assert (kind_of(choice), choice & 255) == (A_MONOPOLY, 3)  # grain
    blind = StrategyBot(plan=city, count="off", propose="none", bank="never")
    choice = blind.choose(game, game.legal_actions(False))
    assert (kind_of(choice), choice & 255) == (A_MONOPOLY, 2)  # ore, which nobody has


def test_card_counting_robber_goes_for_the_hand_most_likely_to_help():
    from src.engine.behaviors import _score_rank_weighted
    from src.engine.strategy import _score_count_cards

    game = in_main([EMPTY, cards(ore=4), cards(wool=4), EMPTY])
    game.goals[0] = CITY
    for h in range(19):
        assert _score_count_cards(game, h, 1) == _score_rank_weighted(game, h, 1) + 30.0  # all ore: certain to help
        assert _score_count_cards(game, h, 2) == _score_rank_weighted(game, h, 2)  # all wool: no help


# ---------------------------------------------------------------- perfect knowledge


def test_cutoff_goes_for_a_spot_a_rival_most_wants():
    from src.engine.bots import ADAPTIVE_V2_OPENING_PARAMS, spot_value

    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    game.cities_left[0] = 0
    game.dev_deck.clear()
    mine = {n for n in Planner._reachable(game, 0, 3) if game._free_spot(n)}
    coveted = set()
    for q in (1, 2, 3):  # each rival's best spot within two roads, judged from the board
        value = spot_value(game, ADAPTIVE_V2_OPENING_PARAMS, q)
        spots = [n for n in Planner._reachable(game, q, 2) if game._free_spot(n)]
        if spots:
            coveted.add(max(spots, key=value))
    if coveted & mine:
        assert Planner(reach=3, cutoff=5000.0).plan(game, 0).target in coveted


def test_road_breaks_finds_the_spot_that_costs_the_holder_longest_road():
    from src.engine.topology import HEX_NODES

    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    for node in range(54):  # an empty board, so only the road below matters
        game.node_owner[node] = -1
    for q in range(4):
        for e in game.edges[q]:
            game.edge_owner[e] = -1
        game.edges[q] = []
        game.touch[q] = set()
    edge_of = {nodes: e for e, nodes in enumerate(EDGE_NODES)}
    corners = HEX_NODES[9]
    ring = []
    for i in range(5):  # five roads round one hex, held by player 1
        a, b = corners[i], corners[i + 1]
        e = edge_of[(min(a, b), max(a, b))]
        ring.append(e)
        game.edge_owner[e] = 1
        game.edges[1].append(e)
        game.touch[1].update((a, b))
    game.road_len = [0, 5, 0, 0]
    game.longest_road = 1
    breaks = Planner._road_breaks(game, 0)
    assert set(breaks) == {corners[1], corners[2], corners[3], corners[4]}  # every inner corner cuts it
    assert all(swing == 2.0 for swing in breaks.values())
    assert Planner._road_breaks(game, 1) == {}  # the holder has nothing to break


def test_deny_robber_prefers_the_victim_whose_plan_loses_most():
    from src.engine.strategy import _score_count_cards, _score_deny

    game = in_main([EMPTY, cards(ore=3, grain=2), cards(wool=5), EMPTY])
    game.goals[1] = CITY  # every card player 1 holds is one their city needs
    game.goals[2] = CITY  # player 2 holds nothing their city needs
    points = game.victory_points(1) / 10.0
    for h in range(19):
        assert _score_deny(game, h, 1) == _score_count_cards(game, h, 1) + 30.0 * points
        assert _score_deny(game, h, 2) == _score_count_cards(game, h, 2)


def test_goal_deny_spots_the_trade_that_finishes_a_leaders_plan():
    from src.engine.game import offer_action
    from src.engine.strategy import TRADE, _completes_their_plan

    def completes(leader, give, get):
        # Player 0 is one ore short of a city, which is what the board says they are saving for.
        game = in_main([cards(ore=2, grain=2, brick=2), cards(ore=4, wool=2), EMPTY, EMPTY])
        if leader:  # seven points anyone can see: two settlements plus both prizes and a third settlement
            game.longest_road = game.largest_army = 0
            game.settlements_left[0] = 2
        game.apply(offer_action(give, get))
        return _completes_their_plan(game)

    assert completes(True, cards(brick=1), cards(ore=1))  # a leader gets the last card
    assert not completes(False, cards(brick=1), cards(ore=1))  # not close to winning
    assert not completes(True, cards(brick=1), cards(wool=1))  # the trade does not finish the plan
    assert "goal_deny" in TRADE


# ---------------------------------------------------------------- what can be inferred from play


def steal_game(hands, thief=0, victim=1):
    """Player ``thief`` robs ``victim``; returns the game and the card that moved."""
    from src.engine.game import A_ROBBER, ROBBER, action
    from src.engine.topology import HEX_NODES

    game = in_main(hands, seed=2)
    game.current = thief
    game.phase = ROBBER
    h = next(x for x in range(19) if x != game.robber and any(game.node_owner[n] == victim for n in HEX_NODES[x]))
    before = list(game.res[victim])
    game.apply(action(A_ROBBER, h * 8 + victim + 1))
    card = next(r for r in range(5) if game.res[victim][r] != before[r])
    return game, card


def test_estimates_are_exact_until_a_steal_someone_did_not_see():
    game = in_main([cards(brick=2), cards(ore=3, wool=1), cards(grain=2), EMPTY])
    for observer in range(4):
        for q in range(4):
            assert game.estimate(observer, q) == [float(x) for x in game.res[q]]


def test_thief_and_victim_know_the_stolen_card_and_others_only_the_odds():
    game, card = steal_game([EMPTY, cards(ore=3, wool=1), EMPTY, EMPTY])
    assert game.estimate(0, 1) == [float(x) for x in game.res[1]]  # the thief saw it
    assert game.estimate(1, 0) == [float(x) for x in game.res[0]]  # so did the victim
    for watcher in (2, 3):
        victim = game.estimate(watcher, 1)
        thief = game.estimate(watcher, 0)
        assert abs(sum(victim) - 3) < 1e-9 and abs(sum(thief) - 1) < 1e-9  # hand sizes are public
        assert abs(victim[2] - 2.25) < 1e-9 and abs(victim[4] - 0.75) < 1e-9  # 3 ore and 1 wool, less a quarter each
        assert abs(thief[2] - 0.75) < 1e-9 and abs(thief[4] - 0.25) < 1e-9


def test_a_public_spend_corrects_a_wrong_guess():
    game, card = steal_game([EMPTY, cards(ore=1, wool=1), EMPTY, EMPTY])
    left = 4 if card == 2 else 2  # the card the victim still holds
    assert abs(game.estimate(2, 1)[left] - 0.5) < 1e-9  # a watcher cannot tell which one is left
    game.res[1][left] -= 1  # the victim spends it in public
    game.bank[left] += 1
    assert game.estimate(2, 1) == [0.0] * 5  # an empty hand is known exactly
    assert game.belief_err[2][1] == [0.0] * 5


def test_strategy_bots_never_read_an_opponents_hand_directly():
    import inspect

    from src.engine import behaviors, plans, strategy

    for module in (strategy, plans):
        source = inspect.getsource(module)
        for hidden in ("game.res[q]", "game.res[victim]", "game.res[proposer]", "game.res[game.current]",
                       "game.vp_cards[q]", "victory_points(q)", "victory_points(victim)", "victory_points(proposer)"):
            assert hidden not in source, (module.__name__, hidden)
    assert "game.res[victim]" in inspect.getsource(behaviors)  # only to count the cards, which is public

