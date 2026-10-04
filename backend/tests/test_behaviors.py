import pytest

from src.engine import Game
from src.engine import experiments
from src.engine.behaviors import CATEGORIES, ROBBING, SPENDING, TRADING, BehaviorBot
from src.engine.game import (
    A_ACCEPT,
    A_BUY,
    A_CITY,
    A_REJECT,
    A_ROAD,
    A_ROBBER,
    A_SETTLE,
    MAIN,
    ROBBER,
    SETUP_ROAD,
    SETUP_SETTLE,
    action,
    kind_of,
    offer_action,
)
from src.engine.simulate import run_game
from src.engine.topology import HEX_NODES


def cards(**counts):
    names = ("brick", "lumber", "ore", "grain", "wool")
    return [counts.get(name, 0) for name in names]


def after_setup(seed=0, players=4):
    game = Game(players, seed=seed)
    bot = BehaviorBot()
    while game.phase in (SETUP_SETTLE, SETUP_ROAD):
        game.apply(bot.choose(game, game.legal_actions()))
    return game


def in_main(hands, seed=0):
    game = after_setup(seed)
    for r in range(5):
        game.bank[r] = 19 - sum(hand[r] for hand in hands)
    game.res = [list(hand) for hand in hands]
    game.phase = MAIN
    return game


EMPTY = cards()
RICH = cards(brick=4, lumber=4, ore=4, grain=4, wool=4)


def test_every_behavior_plays_full_legal_games():
    for category, policies in CATEGORIES.items():
        for name in policies:
            bots = [BehaviorBot(**{category: name}) for _ in range(4)]
            game = run_game(bots, seed=1)
            assert game.done, (category, name)


# ---------------------------------------------------------------- spending


def test_points_first_builds_a_city_before_anything_else():
    game = in_main([RICH, EMPTY, EMPTY, EMPTY])
    for _ in range(20):
        choice = BehaviorBot(spend="points_first").choose(game, game.legal_actions(False))
        assert kind_of(choice) == A_CITY


def test_dev_first_buys_a_development_card_first():
    game = in_main([RICH, EMPTY, EMPTY, EMPTY])
    choice = BehaviorBot(spend="dev_first").choose(game, game.legal_actions(False))
    assert kind_of(choice) == A_BUY


def test_settle_first_prefers_a_settlement_when_one_is_possible():
    game = in_main([RICH, EMPTY, EMPTY, EMPTY])
    can_settle = any(kind_of(a) == A_SETTLE for a in game.legal_actions(False))
    choice = BehaviorBot(spend="settle_first").choose(game, game.legal_actions(False))
    assert kind_of(choice) == (A_SETTLE if can_settle else A_CITY)


def test_never_pass_takes_points_but_leaves_other_choices_random():
    game = in_main([RICH, EMPTY, EMPTY, EMPTY])
    choice = BehaviorBot(spend="never_pass").choose(game, game.legal_actions(False))
    assert kind_of(choice) in (A_CITY, A_SETTLE)
    poor = in_main([cards(brick=1, lumber=1), EMPTY, EMPTY, EMPTY])
    kinds = {kind_of(BehaviorBot(spend="never_pass").choose(poor, poor.legal_actions(False))) for _ in range(60)}
    assert len(kinds) > 1


def test_no_wasted_roads_only_builds_roads_when_it_has_nowhere_to_settle():
    game = in_main([cards(brick=5, lumber=5), EMPTY, EMPTY, EMPTY])
    p = game.current
    bot = BehaviorBot(spend="no_wasted_roads")
    has_spot = bool(game.settlement_spots(p))
    kinds = {kind_of(bot.choose(game, game.legal_actions(False))) for _ in range(80)}
    assert (A_ROAD not in kinds) == has_spot


# ---------------------------------------------------------------- trading


def offered(give, get, hands):
    """A game where player 0 has just offered ``give`` for ``get``; player 1 must answer."""
    game = in_main(hands)
    game.apply(offer_action(give, get))
    assert game.to_move == 1
    return game


def answer(game, policy):
    return kind_of(BehaviorBot(trade=policy).choose(game, game.legal_actions(False)))


def test_fair_and_profit_look_at_the_card_count():
    hands = [cards(brick=3), cards(ore=3), EMPTY, EMPTY]
    even = offered(cards(brick=1), cards(ore=1), hands)
    assert answer(even, "fair") == A_ACCEPT
    assert answer(even, "profit") == A_REJECT
    good = offered(cards(brick=2), cards(ore=1), hands)
    assert answer(good, "profit") == A_ACCEPT
    bad = offered(cards(brick=1), cards(ore=2), hands)
    assert answer(bad, "fair") == A_REJECT
    assert answer(bad, "always") == A_ACCEPT
    assert answer(good, "never") == A_REJECT


def test_leader_aware_policies_refuse_the_player_in_first_place():
    hands = [cards(brick=3), cards(ore=3), EMPTY, EMPTY]
    game = offered(cards(brick=2), cards(ore=1), hands)
    assert answer(game, "fair_no_leader") == A_ACCEPT  # everyone is level, so nobody leads
    game.longest_road = 0  # the proposer now leads by two points
    assert game.public_points(0) > game.public_points(1)
    assert answer(game, "fair_no_leader") == A_REJECT
    assert all(answer(game, "no_leader") == A_REJECT for _ in range(20))
    assert answer(game, "fair") == A_ACCEPT


def test_behind_only_trades_down_the_rankings():
    hands = [cards(brick=3), cards(ore=3), EMPTY, EMPTY]
    game = offered(cards(brick=2), cards(ore=1), hands)
    assert answer(game, "fair_behind_only") == A_REJECT  # level is not behind
    game.longest_road = 1  # the responder now leads the proposer
    assert answer(game, "fair_behind_only") == A_ACCEPT


def test_leader_aware_proposer_trades_with_the_weakest_acceptor():
    hands = [cards(brick=1), cards(ore=1), cards(ore=1), EMPTY]
    game = in_main(hands)
    game.apply(offer_action(cards(brick=1), cards(ore=1)))
    game.apply(action(A_ACCEPT))
    game.apply(action(A_ACCEPT))
    game.largest_army = 1  # player 1 is ahead of player 2
    choice = BehaviorBot(trade="fair_no_leader").choose(game, game.legal_actions(False))
    assert choice & 255 == 2


def test_public_points_hide_victory_point_cards():
    game = after_setup()
    game.vp_cards[0] = 3
    assert game.victory_points(0) == game.public_points(0) + 3


# ---------------------------------------------------------------- robber


def robber_game(seed=3):
    game = after_setup(seed)
    game.res = [cards(brick=1), cards(ore=3), cards(grain=1), cards(wool=6)]
    for r in range(5):
        game.bank[r] = 19 - sum(hand[r] for hand in game.res)
    game.phase = ROBBER
    return game


def robber_move(game, policy):
    a = BehaviorBot(robber=policy).choose(game, game.legal_actions(False))
    assert kind_of(a) == A_ROBBER
    arg = a & 255
    return arg >> 3, (arg & 7) - 1


def own_hexes(game):
    return {h for h in range(19) if any(game.node_owner[n] == game.current for n in HEX_NODES[h])}


@pytest.mark.parametrize("policy", ["no_self", "max_block", "leader_block", "richest", "rank_weighted"])
def test_robber_policies_never_block_their_own_hex(policy):
    game = robber_game()
    for _ in range(25):
        h, _ = robber_move(game, policy)
        assert h not in own_hexes(game)


def test_leader_policy_robs_the_player_in_the_lead():
    game = robber_game()
    game.longest_road = 2
    for _ in range(25):
        assert robber_move(game, "leader")[1] == 2
        assert robber_move(game, "leader_block")[1] == 2


def test_richest_policy_robs_the_biggest_hand():
    game = robber_game()
    assert robber_move(game, "richest")[1] == 3


def test_max_block_picks_the_hex_with_the_most_opponent_production():
    game = robber_game()
    h, _ = robber_move(game, "max_block")

    def blocked(hex_id):
        pips = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 8: 5, 9: 4, 10: 3, 11: 2, 12: 1}.get(game.hex_num[hex_id], 0)
        return sum(pips * game.node_level[n] for n in HEX_NODES[hex_id] if game.node_owner[n] not in (-1, 0))

    candidates = [x for x in range(19) if x != game.robber and x not in own_hexes(game)]
    assert blocked(h) == max(blocked(x) for x in candidates)


# ---------------------------------------------------------------- experiments


def test_experiments_count_games_and_repeat_exactly():
    names = list(SPENDING)
    solo = experiments.against_random("spend", names, games=24, seed=5)
    assert set(solo) == set(names)
    assert all(0 <= wins <= finished <= 24 for wins, finished, _ in solo.values())
    assert solo == experiments.against_random("spend", names, games=24, seed=5)
    duel = experiments.head_to_head("robber", list(ROBBING), games=24, seed=5)
    assert sum(wins for wins, _ in duel.values()) <= 24
    assert sum(played for _, played in duel.values()) % 4 == 0
    assert len(TRADING) >= 4 and len(ROBBING) >= 4 and len(SPENDING) >= 4


# ---------------------------------------------------------------- counter-offers and embargoes

from src.engine.game import (  # noqa: E402
    A_COUNTER,
    A_EMBARGO,
    A_LIFT,
    TRADE_COUNTER,
    TRADE_RESPONSE,
    counter_action,
    decode_offer,
)
from src.engine.bots import RandomBot  # noqa: E402


def bank_total(game):
    return all(game.bank[r] + sum(h[r] for h in game.res) == 19 for r in range(5))


def test_a_counter_offer_the_proposer_accepts_trades_on_the_new_terms():
    game = offered(cards(brick=1), cards(ore=2), [cards(brick=3), cards(ore=3), EMPTY, EMPTY])
    counter = game.try_counter(cards(brick=2), cards(ore=1))
    assert kind_of(counter) == A_COUNTER
    game.apply(counter)
    assert game.phase == TRADE_COUNTER and game.to_move == 0
    game.apply(action(A_ACCEPT))
    assert game.phase == MAIN
    assert game.res[0] == cards(brick=1, ore=1)
    assert game.res[1] == cards(brick=2, ore=2)
    assert game.countered == 1 and game.player_trades == 1
    assert bank_total(game)


def test_a_refused_counter_passes_the_original_offer_to_the_next_player():
    game = offered(cards(brick=1), cards(ore=1), [cards(brick=3), cards(ore=3), cards(ore=1), EMPTY])
    game.apply(game.try_counter(cards(brick=2), cards(ore=1)))
    game.apply(action(A_REJECT))
    assert game.phase == TRADE_RESPONSE and game.to_move == 2
    assert game.offer == (cards(brick=1), cards(ore=1))  # the original terms are back on the table
    game.apply(action(A_ACCEPT))
    assert game.res[2] == cards(brick=1)
    assert game.res[1] == cards(ore=3)


def test_counters_must_be_new_terms_both_sides_can_pay():
    game = offered(cards(brick=1), cards(ore=1), [cards(brick=3), cards(ore=3), EMPTY, EMPTY])
    assert not game.try_counter(cards(brick=1), cards(ore=1))  # the same offer
    assert not game.try_counter(cards(brick=4), cards(ore=1))  # the proposer lacks the cards
    assert not game.try_counter(cards(brick=1), cards(ore=4))  # the responder lacks the cards
    assert not game.try_counter(cards(brick=1), EMPTY)  # a gift
    assert not game.try_counter(cards(brick=1, ore=1), cards(ore=1))  # same resource both ways
    assert decode_offer(counter_action(cards(brick=2), cards(ore=1))) == (cards(brick=2), cards(ore=1))


def test_an_embargo_blocks_trade_in_both_directions_until_lifted():
    hands = [cards(brick=3), cards(ore=3), EMPTY, EMPTY]
    game = in_main(hands)
    assert game.can_offer(cards(brick=1), cards(ore=1))
    game.apply(action(A_EMBARGO, 1))
    assert game.embargoed(0, 1) and game.embargoed(1, 0)
    assert not game.can_offer(cards(brick=1), cards(ore=1))  # player 1 was the only one with ore
    game.apply(action(A_LIFT, 1))
    assert not game.embargoed(0, 1)
    assert game.can_offer(cards(brick=1), cards(ore=1))


def test_embargoed_players_are_not_asked():
    hands = [cards(brick=3), cards(ore=1), cards(ore=1), EMPTY]
    game = in_main(hands)
    game.embargo[1] = 1 << 0  # player 1 refuses to trade with player 0
    game.apply(offer_action(cards(brick=1), cards(ore=1)))
    assert game.responders == [2]


def test_counter_even_trims_an_unfair_ask_to_an_even_swap():
    game = offered(cards(brick=1), cards(ore=3), [cards(brick=3), cards(ore=3), EMPTY, EMPTY])
    choice = BehaviorBot(trade="counter_even").choose(game, game.legal_actions(False))
    assert kind_of(choice) == A_COUNTER
    assert decode_offer(choice) == (cards(brick=1), cards(ore=1))
    ahead = BehaviorBot(trade="counter_ahead")
    two = offered(cards(brick=2), cards(ore=3), [cards(brick=3), cards(ore=3), EMPTY, EMPTY])
    assert decode_offer(ahead.choose(two, two.legal_actions(False))) == (cards(brick=2), cards(ore=1))


def test_fair_proposer_takes_an_even_counter_and_refuses_a_losing_one():
    game = offered(cards(brick=1), cards(ore=3), [cards(brick=3), cards(ore=3), EMPTY, EMPTY])
    game.apply(game.try_counter(cards(brick=1), cards(ore=1)))
    assert kind_of(BehaviorBot(trade="fair").choose(game, game.legal_actions(False))) == A_ACCEPT
    losing = offered(cards(brick=1), cards(ore=3), [cards(brick=3), cards(ore=3), EMPTY, EMPTY])
    losing.apply(losing.try_counter(cards(brick=2), cards(ore=1)))
    assert kind_of(BehaviorBot(trade="fair").choose(losing, losing.legal_actions(False))) == A_REJECT


def test_embargo_leader_declares_and_lifts_as_the_lead_changes():
    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    bot = BehaviorBot(trade="embargo_leader")
    game.longest_road = 2  # player 2 is alone in first place
    choice = bot.choose(game, game.legal_actions(False))
    assert (kind_of(choice), choice & 255) == (A_EMBARGO, 2)
    game.apply(choice)
    assert game.embargoed(0, 2)
    assert kind_of(bot.choose(game, game.legal_actions(False))) not in (A_EMBARGO, A_LIFT)  # nothing more to change
    game.longest_road = -1  # nobody leads any more
    choice = bot.choose(game, game.legal_actions(False))
    assert (kind_of(choice), choice & 255) == (A_LIFT, 2)


def test_embargo_close_targets_anyone_near_ten_points():
    game = in_main([EMPTY, EMPTY, EMPTY, EMPTY])
    game.settlements_left[3] = 0  # five settlements on the board
    game.longest_road = 3
    assert game.public_points(3) >= 7
    choice = BehaviorBot(trade="embargo_close").choose(game, game.legal_actions(False))
    assert (kind_of(choice), choice & 255) == (A_EMBARGO, 3)


def test_a_bot_with_a_trade_policy_never_changes_embargoes_at_random():
    game = in_main([cards(brick=2), cards(ore=2), EMPTY, EMPTY])
    bot = BehaviorBot(trade="fair")
    kinds = {kind_of(bot.choose(game, game.legal_actions(False))) for _ in range(300)}
    assert A_EMBARGO not in kinds
    random_kinds = {kind_of(RandomBot().choose(game, game.legal_actions(False))) for _ in range(300)}
    assert A_EMBARGO in random_kinds


def test_random_games_with_counters_and_embargoes_stay_consistent():
    for seed in range(5):
        game = run_game([RandomBot() for _ in range(4)], seed)
        assert game.done and game.winner >= 0
        assert bank_total(game)
        assert all(count >= 0 for hand in game.res for count in hand)
