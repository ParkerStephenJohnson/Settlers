"""A league of whole strategies.

The rounds test one behavior at a time. The league tests complete bots with
different characters against each other, a different one in every seat, to
see whether one dominates or they beat each other in a cycle.

    uv run python -m src.engine.league --games 60000 --workers 16
"""
import argparse
import math
import os
import random
import time
from multiprocessing import Pool

from .plans import _TUNED, Planner
from .simulate import run_game
from .strategy import StrategyBot

# Each entry is the standard bot with a few choices changed.
STRATEGIES = {
    # The reference bot.
    "standard": {},
    # The standard bot without a plan.
    "no_plan": {"plan": "none"},
    # Spread out: settlements first, expansion valued far above cities.
    "expansion": {"spend": "settle_first", "plan": Planner(**dict(_TUNED, city_value=1.0))},
    # Build up: ore and grain from the start, cities first.
    "cities": {"opening": "ore_grain", "spend": "points_first", "plan": Planner(**dict(_TUNED, city_value=4.0))},
    # Development cards and Largest Army.
    "cards": {"opening": "ore_grain", "spend": "dev_first",
              "plan": Planner(**dict(_TUNED, dev_value=14.0, army_value=20.0))},
    # Roads and Longest Road.
    "roads": {"opening": "brick_lumber", "plan": Planner(**dict(_TUNED, road_value=30.0, road_reach=3))},
    # Play against the table: block spots, embargo and rob whoever is ahead.
    "spoiler": {"plan": Planner(**dict(_TUNED, contest=0.5, block=0.3)), "trade": "goal_embargo_close",
                "robber": "leader_block"},
}


def _batch(args):
    names, seeds, num_players = args
    plays = {n: 0 for n in names}
    wins = {n: 0 for n in names}
    points = {n: 0 for n in names}
    turns = 0
    games = 0
    for seed in seeds:
        lineup = random.Random(seed * 7919 + 1).sample(names, num_players)
        game = run_game([StrategyBot(**STRATEGIES[n]) for n in lineup], seed)
        if game.winner < 0:
            continue
        games += 1
        turns += game.turn
        for seat, n in enumerate(lineup):
            plays[n] += 1
            points[n] += game.victory_points(seat)
        wins[lineup[game.winner]] += 1
    return plays, wins, points, turns, games


def play(games, names=None, num_players=4, workers=1, seed=0):
    """{strategy: (wins, games played, total points)} and the average game length."""
    names = list(names or STRATEGIES)
    if len(names) < num_players:
        raise ValueError(f"need at least {num_players} strategies")
    seeds = range(seed, seed + games)
    size = max(1, games // (max(workers, 1) * 2))
    jobs = [(names, seeds[i:i + size], num_players) for i in range(0, games, size)]
    if workers > 1:
        with Pool(workers) as pool:
            results = pool.map(_batch, jobs)
    else:
        results = list(map(_batch, jobs))
    totals = {n: [0, 0, 0] for n in names}
    turns = finished = 0
    for plays, wins, points, t, g in results:
        turns += t
        finished += g
        for n in names:
            totals[n][0] += wins[n]
            totals[n][1] += plays[n]
            totals[n][2] += points[n]
    return {n: tuple(v) for n, v in totals.items()}, (turns / finished if finished else 0.0)


def main():
    parser = argparse.ArgumentParser(description="Play whole strategies against each other")
    parser.add_argument("--games", type=int, default=10000)
    parser.add_argument("--workers", type=int, default=1, help=f"processes to use (this machine has {os.cpu_count()})")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    start = time.perf_counter()
    totals, turns = play(args.games, workers=args.workers, seed=args.seed)
    elapsed = time.perf_counter() - start
    print(f"League: {args.games} games, a different strategy in every seat, {args.games / elapsed:,.0f} games/s")
    print(f"  average game {turns:.0f} turns; an even share is 25%\n")
    print(f"  {'strategy':<12}{'games':>8}{'win rate':>10}{'+/-':>7}{'avg points':>12}")
    for name in sorted(totals, key=lambda n: -totals[n][0] / max(1, totals[n][1])):
        wins, played, points = totals[name]
        rate = wins / played
        margin = 1.96 * math.sqrt(rate * (1 - rate) / played)
        print(f"  {name:<12}{played:>8}{rate:>10.1%}{margin:>7.1%}{points / played:>12.2f}")


if __name__ == "__main__":
    main()
