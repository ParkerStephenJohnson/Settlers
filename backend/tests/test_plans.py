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
    reach = Planner(reach=3)._reachable(game, 0)
    for node, (roads, first) in reach.items():
        assert 0 <= roads <= 3
        if roads == 0:
            assert node in game.touch[0] and first == -1
        else:
            assert game.edge_owner[first] < 0
            assert set(EDGE_NODES[first]) & game.touch[0]  # the first road joins the network
    assert max(roads for roads, _ in reach.values()) == 3
    assert len(Planner(reach=1)._reachable(game, 0)) < len(reach)


def test_an_opponent_building_blocks_the_route():
    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    reach = Planner(reach=3)._reachable(game, 0)
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
