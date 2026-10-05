"""Does an embargo work when the whole table joins in?

One player embargoing the leader changes little, because the other two keep
trading with them. This study makes the embargo a table norm and asks two
questions:

1. Does it slow the front-runner? For each norm, four identical bots play.
   The front-runner is the first player to reach 7 public points. If the
   embargo works, front-runners should win less often and take longer to
   close out the game.

2. Is the norm stable? Three bots follow the norm and one ignores it. If the
   one who ignores it wins more than an even share, the norm does not hold.

    uv run python -m src.engine.embargo_study --games 20000 --workers 16
"""
import argparse
import math
import os
from multiprocessing import Pool

from .game import Game
from .strategy import STANDARD, StrategyBot

NORMS = ("goal", "goal_no_leader", "goal_embargo_leader", "goal_no_close", "goal_embargo_close")
FRONT_RUNNER_POINTS = 7


def _play(bots, seed):
    """Play one game. Returns (winner, turns, front-runner, turn they got there, trades)."""
    game = Game(len(bots), seed)
    legal_actions = game.legal_actions
    apply = game.apply
    public_points = game.public_points
    front = -1
    front_turn = 0
    while not game.done:
        bot = bots[game.to_move]
        apply(bot.choose(game, legal_actions(False)))
        if front < 0:
            p = game.current
            if public_points(p) >= FRONT_RUNNER_POINTS:
                front, front_turn = p, game.turn
    return game.winner, game.turn, front, front_turn, game.player_trades


def _norm_batch(args):
    norm, seeds, num_players = args
    games = front_wins = turns = closing = trades = 0
    for seed in seeds:
        bots = [StrategyBot(trade=norm) for _ in range(num_players)]
        winner, total, front, front_turn, traded = _play(bots, seed)
        if winner < 0 or front < 0:
            continue
        games += 1
        front_wins += winner == front
        turns += total
        closing += total - front_turn
        trades += traded
    return norm, games, front_wins, turns, closing, trades


def _deviation_batch(args):
    norm, deviant, seeds, num_players = args
    games = wins = 0
    for seed in seeds:
        seat = seed % num_players
        bots = [StrategyBot(trade=norm) for _ in range(num_players)]
        bots[seat] = StrategyBot(trade=deviant)
        winner = _play(bots, seed)[0]
        if winner >= 0:
            games += 1
            wins += winner == seat
    return norm, games, wins


def _chunks(seeds, workers):
    size = max(1, len(seeds) // (max(workers, 1) * 2))
    return [seeds[i:i + size] for i in range(0, len(seeds), size)]


def study(games, norms=NORMS, deviant=STANDARD["trade"], num_players=4, workers=1, seed=0):
    """Returns (norm results, deviation results) as dicts keyed by norm."""
    seeds = range(seed, seed + games)
    chunks = _chunks(seeds, workers)
    norm_jobs = [(n, c, num_players) for n in norms for c in chunks]
    deviation_jobs = [(n, deviant, c, num_players) for n in norms if n != deviant for c in chunks]
    if workers > 1:
        with Pool(workers) as pool:
            norm_out = pool.map(_norm_batch, norm_jobs)
            deviation_out = pool.map(_deviation_batch, deviation_jobs)
    else:
        norm_out = list(map(_norm_batch, norm_jobs))
        deviation_out = list(map(_deviation_batch, deviation_jobs))

    table = {n: [0, 0, 0, 0, 0] for n in norms}
    for norm, *values in norm_out:
        for i, v in enumerate(values):
            table[norm][i] += v
    deviation = {n: [0, 0] for n in norms if n != deviant}
    for norm, played, wins in deviation_out:
        deviation[norm][0] += played
        deviation[norm][1] += wins
    return table, deviation


def _margin(rate, n):
    return 1.96 * math.sqrt(rate * (1 - rate) / n) if n else 0.0


def main():
    parser = argparse.ArgumentParser(description="Test embargoes as a table-wide norm")
    parser.add_argument("--games", type=int, default=5000, help="games per norm")
    parser.add_argument("--workers", type=int, default=1, help=f"processes to use (this machine has {os.cpu_count()})")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    table, deviation = study(args.games, workers=args.workers, seed=args.seed)

    print(f"Whole table follows the norm ({args.games} games each)")
    print(f"  {'norm':<22}{'front-runner wins':>19}{'+/-':>7}{'turns':>7}{'turns to close':>16}{'trades':>8}")
    for norm, (games, front_wins, turns, closing, trades) in table.items():
        rate = front_wins / games
        print(f"  {norm:<22}{rate:>19.1%}{_margin(rate, games):>7.1%}{turns / games:>7.1f}"
              f"{closing / games:>16.1f}{trades / games:>8.1f}")

    print(f"\nOne player ignores the norm and plays {STANDARD['trade']!r} (an even share is 25%)")
    print(f"  {'norm':<22}{'deviant wins':>14}{'+/-':>7}")
    for norm, (games, wins) in deviation.items():
        rate = wins / games
        print(f"  {norm:<22}{rate:>14.1%}{_margin(rate, games):>7.1%}")


if __name__ == "__main__":
    main()
