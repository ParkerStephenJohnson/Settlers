"""Search for better settings of the board-aware opening.

A simple evolution strategy. Each candidate plays one seat against the current
best named openings, with random play after the opening. The best candidates
survive and are mutated to make the next generation. Every generation uses
fresh seeds and re-tests the survivors, so a lucky score does not stick.

    uv run python -m src.engine.opening_search --generations 6 --population 24 --games 2000 --workers 16
"""
import argparse
import json
import os
import random
import time
from multiprocessing import Pool

from .bots import (
    ADAPTIVE_OPENING_PARAMS,
    DEFAULT_OPENING_PARAMS,
    OPENING_PARAM_RANGES,
    PhasedBot,
    board_aware_opening,
)
from .simulate import run_game

DEFAULT_FIELD = ("adaptive", "balanced", "pips")


def _evaluate_batch(args):
    index, params, field, seeds, num_players = args
    wins = finished = 0
    candidate = board_aware_opening(params)
    for seed in seeds:
        rng = random.Random(seed * 104729 + 7)
        seat = rng.randrange(num_players)
        rivals = [field[rng.randrange(len(field))] for _ in range(num_players - 1)]
        bots = [PhasedBot(name) for name in rivals]
        bots.insert(seat, PhasedBot(candidate))
        game = run_game(bots, seed)
        if game.winner >= 0:
            finished += 1
            wins += game.winner == seat
    return index, wins, finished


def evaluate(candidates, games, field=DEFAULT_FIELD, workers=1, seed=0, num_players=4, pool=None):
    """Win rate of each candidate against the field. All candidates see the same seeds."""
    seeds = range(seed, seed + games)
    chunk = max(1, games // 4)
    jobs = [
        (i, params, tuple(field), seeds[j:j + chunk], num_players)
        for i, params in enumerate(candidates)
        for j in range(0, games, chunk)
    ]
    wins = [0] * len(candidates)
    finished = [0] * len(candidates)
    if pool is not None:
        results = pool.imap_unordered(_evaluate_batch, jobs)
    elif workers > 1:
        with Pool(workers) as own:
            results = own.map(_evaluate_batch, jobs)
    else:
        results = map(_evaluate_batch, jobs)
    for i, w, f in results:
        wins[i] += w
        finished[i] += f
    return [w / f if f else 0.0 for w, f in zip(wins, finished)]


def random_params(rng):
    params = {}
    for name, (low, high) in OPENING_PARAM_RANGES.items():
        if name == "weights":
            params[name] = [rng.uniform(low, high) for _ in range(5)]
        else:
            params[name] = rng.uniform(low, high)
    return params


def mutate(params, rng, strength=0.25):
    """A copy with every knob nudged by a fraction of its range."""
    child = {}
    for name, (low, high) in OPENING_PARAM_RANGES.items():
        span = (high - low) * strength
        if name == "weights":
            child[name] = [min(high, max(low, w + rng.gauss(0, span))) for w in params[name]]
        else:
            child[name] = min(high, max(low, params[name] + rng.gauss(0, span)))
    return child


def search(generations=6, population=24, games=2000, survivors=6, field=DEFAULT_FIELD, workers=1, seed=0,
           seeds_from=None, log=print):
    """Evolve opening settings. Returns survivors as (win rate, params), best first."""
    rng = random.Random(seed)
    # Start from known-reasonable points plus random ones.
    pips_only = dict(DEFAULT_OPENING_PARAMS)
    balanced = dict(DEFAULT_OPENING_PARAMS, variety=2.0)
    scarce = dict(DEFAULT_OPENING_PARAMS, variety=2.0, scarcity=1.0, new_resource=1.0)
    champion = {k: (v[:] if isinstance(v, list) else v) for k, v in ADAPTIVE_OPENING_PARAMS.items()}
    candidates = list(seeds_from or [champion, pips_only, balanced, scarce])
    while len(candidates) < population:
        candidates.append(random_params(rng))

    pool = Pool(workers) if workers > 1 else None
    try:
        ranked = []
        for generation in range(generations):
            start = time.perf_counter()
            rates = evaluate(candidates, games, field, seed=seed + 1_000_000 * (generation + 1), pool=pool)
            ranked = sorted(zip(rates, candidates), key=lambda x: -x[0])
            elapsed = time.perf_counter() - start
            top = ", ".join(f"{r:.1%}" for r, _ in ranked[:3])
            log(f"generation {generation + 1}/{generations}: best {top}  ({elapsed:.0f} s)")
            keep = [params for _, params in ranked[:survivors]]
            if generation == generations - 1:
                break
            strength = 0.25 * (1 - generation / generations)  # smaller steps as it converges
            candidates = keep[:]
            while len(candidates) < population:
                candidates.append(mutate(keep[rng.randrange(len(keep))], rng, strength))
        return ranked[:survivors]
    finally:
        if pool is not None:
            pool.close()
            pool.join()


def main():
    parser = argparse.ArgumentParser(description="Search for better opening settings")
    parser.add_argument("--generations", type=int, default=6)
    parser.add_argument("--population", type=int, default=24)
    parser.add_argument("--games", type=int, default=2000, help="games per candidate per generation")
    parser.add_argument("--survivors", type=int, default=6)
    parser.add_argument("--confirm-games", type=int, default=20000,
                        help="fresh games used to re-test the finalists, since search scores flatter the winner")
    parser.add_argument("--field", nargs="*", default=list(DEFAULT_FIELD))
    parser.add_argument("--workers", type=int, default=1, help=f"processes to use (this machine has {os.cpu_count()})")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--save", metavar="JSON", help="write the confirmed best settings here")
    args = parser.parse_args()

    print(f"field: {', '.join(args.field)}; {args.population} candidates x {args.games} games x "
          f"{args.generations} generations")
    finalists = search(args.generations, args.population, args.games, args.survivors, args.field, args.workers,
                       args.seed)

    top = [params for _, params in finalists[:3]]
    rates = evaluate(top, args.confirm_games, args.field, args.workers, seed=args.seed + 900_000_000)
    confirmed = sorted(zip(rates, top), key=lambda x: -x[0])
    print(f"\nconfirmed on {args.confirm_games} fresh games each (an even share is 25%):")
    for rate, _ in confirmed:
        print(f"  {rate:.1%}")
    best_rate, best = confirmed[0]
    print("\nbest settings:")
    print(json.dumps(best, indent=2))
    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump({"win_rate": best_rate, "field": args.field, "params": best}, f, indent=2)
        print(f"\nsaved to {args.save}")


if __name__ == "__main__":
    main()
