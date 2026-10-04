"""Run many games and report speed and results.

    uv run python -m src.engine.simulate --games 10000 --workers 8
"""
import argparse
import os
import time
from multiprocessing import Pool

from .bots import BOTS
from .game import Game


def play_game(seed, num_players=4, bot="greedy", max_turns=2000):
    """Play one full game. Returns (winner, turns, final points per player)."""
    game = Game(num_players, seed, max_turns)
    choose = BOTS[bot]().choose
    legal_actions = game.legal_actions
    apply = game.apply
    while not game.done:
        apply(choose(game, legal_actions()))
    return game.winner, game.turn, [game.victory_points(p) for p in range(num_players)]


def _play_batch(args):
    seeds, num_players, bot, max_turns = args
    return [play_game(seed, num_players, bot, max_turns)[:2] for seed in seeds]


def simulate(games, num_players=4, bot="greedy", workers=1, seed=0, max_turns=2000):
    """Play ``games`` games. Returns a list of (winner, turns)."""
    seeds = range(seed, seed + games)
    if workers <= 1:
        return _play_batch((seeds, num_players, bot, max_turns))
    chunk = max(1, games // (workers * 4))
    batches = [(seeds[i:i + chunk], num_players, bot, max_turns) for i in range(0, games, chunk)]
    with Pool(workers) as pool:
        results = []
        for batch in pool.imap_unordered(_play_batch, batches):
            results.extend(batch)
    return results


def main():
    parser = argparse.ArgumentParser(description="Simulate Catan games")
    parser.add_argument("--games", type=int, default=1000)
    parser.add_argument("--players", type=int, default=4, choices=(2, 3, 4))
    parser.add_argument("--bot", default="greedy", choices=sorted(BOTS))
    parser.add_argument("--workers", type=int, default=1, help=f"processes to use (this machine has {os.cpu_count()})")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-turns", type=int, default=2000)
    args = parser.parse_args()

    start = time.perf_counter()
    results = simulate(args.games, args.players, args.bot, args.workers, args.seed, args.max_turns)
    elapsed = time.perf_counter() - start

    finished = [(w, t) for w, t in results if w >= 0]
    print(f"{args.games} games, {args.players} {args.bot} bots, {args.workers} worker(s)")
    print(f"  time           {elapsed:.2f} s")
    print(f"  speed          {args.games / elapsed:,.0f} games/s")
    print(f"  finished       {len(finished)} ({len(finished) / args.games:.1%})")
    if finished:
        print(f"  avg turns      {sum(t for _, t in finished) / len(finished):.0f}")
        wins = [0] * args.players
        for w, _ in finished:
            wins[w] += 1
        print("  wins by seat   " + "  ".join(f"{i}: {wins[i] / len(finished):.1%}" for i in range(args.players)))


if __name__ == "__main__":
    main()
