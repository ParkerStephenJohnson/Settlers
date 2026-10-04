import pytest

from src.engine import Game, rounds
from src.engine.game import (
    A_BUY,
    A_CITY,
    A_DISCARD,
    A_END,
    A_KNIGHT,
    A_OFFER,
    A_ROAD,
    A_SETTLE,
    A_TRADE,
    DISCARD,
    KNIGHT,
    MAIN,
    SETUP_ROAD,
    SETUP_SETTLE,
    decode_offer,
    kind_of,
)
from src.engine.simulate import run_game
from src.engine.strategy import CATEGORIES, COSTS, STANDARD, StrategyBot, next_purchase


def cards(**counts):
    names = ("brick", "lumber", "ore", "grain", "wool")
    return [counts.get(name, 0) for name in names]


EMPTY = cards()


def in_main(hands, seed=0, **bot):
    game = Game(4, seed=seed)
    setup = StrategyBot()
    while game.phase in (SETUP_SETTLE, SETUP_ROAD):
        game.apply(setup.choose(game, game.legal_actions(False)))
    for r in range(5):
        game.bank[r] = 19 - sum(hand[r] for hand in hands)
    game.res = [list(hand) for hand in hands]
    game.phase = MAIN
    return game


def move(game, **choices):
    return StrategyBot(**choices).choose(game, game.legal_actions(False))


def test_standard_names_a_real_policy_for_every_behavior():
    for category, policies in CATEGORIES.items():
        assert STANDARD[category] in policies
        assert len(policies) >= 2  # something to test against


def test_no_policy_is_left_to_chance():
    for policies in CATEGORIES.values():
        assert "random" not in policies


@pytest.mark.parametrize("category", sorted(CATEGORIES))
def test_every_variant_finishes_games_against_the_standard(category):
    for name in CATEGORIES[category]:
        bots = [StrategyBot(**{category: name})] + [StrategyBot() for _ in range(3)]
        game = run_game(bots, seed=2)
        assert game.done and game.winner >= 0, (category, name)
        for r in range(5):
            assert game.bank[r] + sum(hand[r] for hand in game.res) == 19


def test_standard_bots_always_finish():
    for seed in range(25):
        game = run_game([StrategyBot() for _ in range(4)], seed)
        assert game.winner >= 0


def test_spending_order_decides_the_first_purchase():
    rich = cards(brick=4, lumber=4, ore=4, grain=4, wool=4)
    game = in_main([rich, EMPTY, EMPTY, EMPTY])
    assert kind_of(move(game, spend="points_first")) == A_CITY
    assert kind_of(move(game, spend="dev_first")) == A_BUY
    can_settle = any(kind_of(a) == A_SETTLE for a in game.legal_actions(False))
    assert kind_of(move(game, spend="settle_first")) == (A_SETTLE if can_settle else A_CITY)


def test_city_goes_on_the_most_productive_settlement():
    game = in_main([cards(ore=3, grain=2), EMPTY, EMPTY, EMPTY])
    choice = move(game)
    assert kind_of(choice) == A_CITY
    assert game.node_pips[choice & 255] == max(game.node_pips[n] for n in game.settlements[0])


def test_it_ends_the_turn_when_there_is_nothing_useful_to_do():
    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    assert kind_of(move(game)) == A_END


def test_it_offers_a_spare_card_for_one_it_is_missing():
    # Saving for a city (3 ore, 2 grain) with spare brick and an opponent holding ore.
    game = in_main([cards(ore=2, grain=2, brick=2), cards(ore=2), EMPTY, EMPTY])
    assert next_purchase(game, 0, ("city", "settlement", "dev")) == "city"
    choice = move(game, propose="even")
    assert kind_of(choice) == A_OFFER
    assert decode_offer(choice) == (cards(brick=1), cards(ore=1))
    generous = move(game, propose="generous")
    assert decode_offer(generous) == (cards(brick=2), cards(ore=1))
    assert kind_of(move(game, propose="none")) != A_OFFER


def test_bank_policy_trades_only_spare_cards_toward_the_purchase():
    game = in_main([cards(ore=2, grain=2, brick=4), EMPTY, EMPTY, EMPTY])
    choice = move(game, propose="none", bank="goal")
    assert kind_of(choice) == A_TRADE
    give, get = divmod(choice & 255, 5)
    assert (give, get) == (0, 2)  # brick for ore
    assert kind_of(move(game, propose="none", bank="never")) == A_END


def test_knight_policies_differ_on_when_to_play():
    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    game.dev_hand[0][KNIGHT] = 1
    for h in range(19):  # put the robber somewhere player 0 has no building
        if all(game.node_owner[n] != 0 for n in __import__("src.engine.topology", fromlist=["HEX_NODES"]).HEX_NODES[h]):
            game.robber = h
            break
    assert kind_of(move(game, dev="eager")) == A_KNIGHT
    assert kind_of(move(game, dev="defensive")) != A_KNIGHT
    assert kind_of(move(game, dev="never")) != A_KNIGHT
    game.knights[0] = 2  # one more knight takes Largest Army
    assert kind_of(move(game, dev="hold_knights")) == A_KNIGHT


def test_discard_keeps_what_the_next_purchase_needs():
    game = in_main([cards(ore=3, grain=2, wool=4), EMPTY, EMPTY, EMPTY])
    game.phase = DISCARD
    game.discarder = 0
    game.pending_discard[0] = 4
    choice = move(game, discard="keep_goal")
    assert (kind_of(choice), choice & 255) == (A_DISCARD, 4)  # wool, not city cards
    assert COSTS["city"] == (0, 0, 3, 2, 0)


def test_roads_are_built_only_when_there_is_nowhere_to_settle():
    game = in_main([cards(brick=1, lumber=1), EMPTY, EMPTY, EMPTY])
    choice = move(game)
    has_spot = bool(game.settlement_spots(0))
    assert (kind_of(choice) == A_ROAD) == (not has_spot)


def test_ab_test_is_repeatable_and_the_standard_sits_near_an_even_share():
    first = rounds.ab_test(["discard"], games=40, seed=3)
    assert first == rounds.ab_test(["discard"], games=40, seed=3)
    wins, finished, _ = first["discard"][STANDARD["discard"]]
    assert finished == 40 and 0 <= wins <= 40
    assert rounds.winners({"discard": {"keep_goal": (10, 40, 0), "most": (30, 40, 0)}}, STANDARD, 4) == {"discard": "most"}
    assert rounds.winners({"discard": {"keep_goal": (10, 40, 0), "most": (11, 40, 0)}}, STANDARD, 4) == {}


def test_nearest_goes_for_whichever_purchase_needs_fewer_cards():
    from src.engine.strategy import SPEND

    game = in_main([cards(ore=3, grain=1), EMPTY, EMPTY, EMPTY])
    assert SPEND["nearest"](game, 0)[0] == "city"  # one card short of a city
    game.res[0] = cards(brick=1, lumber=1, grain=1)
    if game.settlement_spots(0):
        assert SPEND["nearest"](game, 0)[0] == "settlement"  # one card short of a settlement


def test_contrarian_does_the_opposite_of_the_table():
    from src.engine.strategy import SPEND

    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    assert SPEND["contrarian"](game, 0)[0] == "settlement"  # nobody has built anything yet
    game.settlements[1].append(53)  # an opponent has expanded
    assert SPEND["contrarian"](game, 0)[0] == "city"


def test_goal_trading_refuses_leaders_only_in_the_variants_that_say_so():
    from src.engine.game import A_ACCEPT, A_REJECT, offer_action

    def answer(policy, lead):
        game = in_main([cards(brick=2), cards(ore=2, grain=2, wool=2), EMPTY, EMPTY])
        if lead:
            game.longest_road = 0
        # Player 0 offers brick for wool; player 1 is saving for a city and can spare wool.
        game.res[1] = cards(ore=2, grain=2, wool=2, lumber=0)
        game.apply(offer_action(cards(brick=2), cards(wool=1)))
        return kind_of(StrategyBot(trade=policy).choose(game, game.legal_actions(False)))

    assert answer("goal", lead=False) == A_ACCEPT  # more cards for a spare one
    assert answer("goal", lead=True) == A_ACCEPT
    assert answer("goal_no_leader", lead=False) == A_ACCEPT
    assert answer("goal_no_leader", lead=True) == A_REJECT
    assert answer("goal_behind_only", lead=False) == A_REJECT  # level is not behind


def test_goal_counter_asks_for_a_card_it_needs():
    from src.engine.game import A_COUNTER, offer_action

    # Player 1 needs ore for a city. Player 0 offers brick for wool but also holds ore.
    game = in_main([cards(brick=2, ore=1), cards(ore=2, grain=2, wool=2), EMPTY, EMPTY])
    game.apply(offer_action(cards(brick=1), cards(wool=2)))
    choice = StrategyBot(trade="goal_counter").choose(game, game.legal_actions(False))
    assert kind_of(choice) == A_COUNTER
    assert decode_offer(choice) == (cards(ore=1), cards(wool=2))


def test_mixed_field_tournament_counts_one_winner_per_game():
    totals = rounds.tournament("spend", games=40, seed=6)
    assert sum(wins for wins, _ in totals.values()) == 40
    assert sum(played for _, played in totals.values()) == 160
    with pytest.raises(ValueError):
        rounds.tournament("build", games=1)
