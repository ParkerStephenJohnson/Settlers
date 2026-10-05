"""Search for better planner settings.

The same evolution strategy as opening_search. Each candidate planner plays one
seat against three standard bots; the best survive and are mutated. Every
generation uses fresh seeds, and the finalists are re-tested on unseen games.

    uv run python -m src.engine.plan_search --generations 8 --population 24 --games 3000 --workers 16
"""
import argparse
import json
import os
import random
import time
from multiprocessing import Pool

from .plans import Planner
from .simulate import run_game
from .strategy import STANDARD, StrategyBot

# name: (low, high). reach and road_reach are rounded to whole roads.
RANGES = {
    "reach": (1, 4),
    "city_value": (0.5, 5.0),
    "dev_value": (0.0, 25.0),
    "patience": (0.5, 8.0),
    "army_value": (0.0, 60.0),
    "road_value": (0.0, 80.0),
    "road_reach": (1, 4),
    "contest": (0.0, 0.9),
    "block": (0.0, 1.0),
}
_PRIZES = {"reach": 3, "city_value": 1.75, "dev_value": 0.3, "patience": 2.0, "army_value": 20.0,
           "road_value": 30.0, "road_reach": 2, "contest": 0.0, "block": 0.0}
START = [
    dict(_PRIZES),
    dict(_PRIZES, road_value=45.0, road_reach=3),
    dict(_PRIZES, army_value=35.0),
    dict(_PRIZES, block=0.3),
]


def make(params):
    return Planner(reach=int(round(params["reach"])), city_value=params["city_value"],
                   dev_value=params["dev_value"], patience=params["patience"],
                   army_value=params["army_value"], road_value=params["road_value"],
                   road_reach=int(round(params["road_reach"])), contest=params["contest"], block=params["block"])


def _batch(args):
    index, params, base, seeds, num_players = args
    wins = finished = 0
    planner = make(params)
    for seed in seeds:
        seat = seed % num_players
        bots = [StrategyBot(**base) for _ in range(num_players)]
        bots[seat] = StrategyBot(**dict(base, plan=planner))
        game = run_game(bots, seed)
        if game.winner >= 0:
            finished += 1
            wins += game.winner == seat
    return index, wins, finished


def evaluate(candidates, games, base=None, workers=1, seed=0, num_players=4, pool=None):
    """Win rate of each candidate from one seat against three bots using ``base``."""
    base = dict(base or STANDARD)
    seeds = range(seed, seed + games)
    chunk = max(1, games // 4)
    jobs = [(i, params, base, seeds[j:j + chunk], num_players)
            for i, params in enumerate(candidates) for j in range(0, games, chunk)]
    wins = [0] * len(candidates)
    finished = [0] * len(candidates)
    if pool is not None:
        results = pool.imap_unordered(_batch, jobs)
    elif workers > 1:
        with Pool(workers) as own:
            results = own.map(_batch, jobs)
    else:
        results = map(_batch, jobs)
    for i, w, f in results:
        wins[i] += w
        finished[i] += f
    return [w / f if f else 0.0 for w, f in zip(wins, finished)]


def random_params(rng):
    return {name: rng.uniform(low, high) for name, (low, high) in RANGES.items()}


def mutate(params, rng, strength=0.25):
    return {name: min(high, max(low, params[name] + rng.gauss(0, (high - low) * strength)))
            for name, (low, high) in RANGES.items()}


def search(generations=6, population=24, games=2000, survivors=6, base=None, workers=1, seed=0, log=print):
    """Evolve planner settings. Returns survivors as (win rate, params), best first."""
    rng = random.Random(seed)
    candidates = [dict(p) for p in START]
    while len(candidates) < population:
        candidates.append(random_params(rng))
    pool = Pool(workers) if workers > 1 else None
    try:
        ranked = []
        for generation in range(generations):
            start = time.perf_counter()
            rates = evaluate(candidates, games, base, seed=seed + 1_000_000 * (generation + 1), pool=pool)
            ranked = sorted(zip(rates, candidates), key=lambda x: -x[0])
            top = ", ".join(f"{r:.1%}" for r, _ in ranked[:3])
            log(f"generation {generation + 1}/{generations}: best {top}  ({time.perf_counter() - start:.0f} s)")
            keep = [params for _, params in ranked[:survivors]]
            if generation == generations - 1:
                break
            strength = 0.25 * (1 - generation / generations)
            candidates = keep[:]
            while len(candidates) < population:
                candidates.append(mutate(keep[rng.randrange(len(keep))], rng, strength))
        return ranked[:survivors]
    finally:
        if pool is not None:
            pool.close()
            pool.join()


def main():
    parser = argparse.ArgumentParser(description="Search for better planner settings")
    parser.add_argument("--generations", type=int, default=6)
    parser.add_argument("--population", type=int, default=24)
    parser.add_argument("--games", type=int, default=2000, help="games per candidate per generation")
    parser.add_argument("--survivors", type=int, default=6)
    parser.add_argument("--confirm-games", type=int, default=20000)
    parser.add_argument("--workers", type=int, default=1, help=f"processes to use (this machine has {os.cpu_count()})")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    print(f"{args.population} candidates x {args.games} games x {args.generations} generations, "
          f"each in one seat against three standard bots")
    finalists = search(args.generations, args.population, args.games, args.survivors, None, args.workers, args.seed)
    top = [params for _, params in finalists[:3]]
    rates = evaluate(top, args.confirm_games, None, args.workers, seed=args.seed + 900_000_000)
    confirmed = sorted(zip(rates, top), key=lambda x: -x[0])
    print(f"\nconfirmed on {args.confirm_games} fresh games each (an even share is 25%):")
    for rate, params in confirmed:
        print(f"  {rate:.1%}  " + json.dumps({k: round(v, 2) for k, v in params.items()}))


if __name__ == "__main__":
    main()
