"""A/B test behaviors.

Every seat uses the same opening and plays at random except for the behavior
under test, so a change in win rate comes from that behavior alone.

Two tests per category:

- Against random: one seat has the behavior, the other three do not.
- Head to head: every seat has a different behavior from the category.

    uv run python -m src.engine.experiments --games 8000 --workers 16 --plot ../docs
"""
import argparse
import math
import os
import random
import time
from multiprocessing import Pool

from .behaviors import CATEGORIES, BehaviorBot
from .simulate import _BLUE, _INK, _MUTED, _SURFACE, _pyplot, _style, run_game


def _bot(category, name, opening):
    return BehaviorBot(opening=opening, **{category: name})


def _solo_batch(args):
    category, name, opening, seeds, num_players = args
    wins = finished = turns = 0
    for seed in seeds:
        seat = seed % num_players
        bots = [_bot(category, "random", opening) for _ in range(num_players)]
        bots[seat] = _bot(category, name, opening)
        game = run_game(bots, seed)
        if game.winner >= 0:
            finished += 1
            wins += game.winner == seat
            turns += game.turn
    return name, wins, finished, turns


def _tournament_batch(args):
    category, names, opening, seeds, num_players = args
    plays = {n: 0 for n in names}
    wins = {n: 0 for n in names}
    for seed in seeds:
        lineup = random.Random(seed * 7919 + 1).sample(names, num_players)
        game = run_game([_bot(category, n, opening) for n in lineup], seed)
        if game.winner < 0:
            continue
        for n in lineup:
            plays[n] += 1
        wins[lineup[game.winner]] += 1
    return plays, wins


def _chunks(seeds, workers):
    size = max(1, len(seeds) // (max(workers, 1) * 4))
    return [seeds[i:i + size] for i in range(0, len(seeds), size)]


def against_random(category, names, games, opening="adaptive", num_players=4, seed=0, pool=None, workers=1):
    """{name: (wins, finished, total turns)} with one seat using each behavior."""
    seeds = range(seed, seed + games)
    jobs = [(category, n, opening, c, num_players) for n in names for c in _chunks(seeds, workers)]
    totals = {n: [0, 0, 0] for n in names}
    for name, wins, finished, turns in (pool.imap_unordered(_solo_batch, jobs) if pool else map(_solo_batch, jobs)):
        totals[name][0] += wins
        totals[name][1] += finished
        totals[name][2] += turns
    return {n: tuple(v) for n, v in totals.items()}


def head_to_head(category, names, games, opening="adaptive", num_players=4, seed=0, pool=None, workers=1):
    """{name: (wins, games played)} with a different behavior in every seat."""
    names = list(names)
    seeds = range(seed, seed + games)
    jobs = [(category, names, opening, c, num_players) for c in _chunks(seeds, workers)]
    totals = {n: [0, 0] for n in names}
    for plays, wins in (pool.imap_unordered(_tournament_batch, jobs) if pool else map(_tournament_batch, jobs)):
        for n in names:
            totals[n][0] += wins[n]
            totals[n][1] += plays[n]
    return {n: tuple(v) for n, v in totals.items()}


def _rate(wins, n):
    rate = wins / n if n else 0.0
    return rate, 1.96 * math.sqrt(rate * (1 - rate) / n) if n else 0.0


def plot(results, num_players, games, path):
    """One panel per category: win rate of one seat using each behavior."""
    plt = _pyplot()
    even = 100 / num_players
    rows = sum(len(r) for r in results.values())
    fig, axes = plt.subplots(len(results), 1, figsize=(8.5, 0.42 * rows + 1.5 * len(results) + 0.6), dpi=160,
                             facecolor=_SURFACE, gridspec_kw={"height_ratios": [len(r) for r in results.values()]})
    if len(results) == 1:
        axes = [axes]
    titles = {"spend": "Spending", "trade": "Accepting trades", "robber": "Robber"}
    limit = 0
    for ax, (category, solo) in zip(axes, results.items()):
        ranked = sorted(solo.items(), key=lambda kv: kv[1][0] / kv[1][1])
        labels = [name for name, _ in ranked]
        stats = [_rate(v[0], v[1]) for _, v in ranked]
        rates = [100 * r for r, _ in stats]
        margins = [100 * m for _, m in stats]
        _style(ax, "x")
        bars = ax.barh(labels, rates, height=0.55, color=_BLUE, zorder=3)
        ax.errorbar(rates, range(len(labels)), xerr=margins, fmt="none", ecolor=_INK, elinewidth=1, capsize=3,
                    zorder=4)
        ax.axvline(even, color=_MUTED, linewidth=1, zorder=2)
        for bar, rate, margin in zip(bars, rates, margins):
            ax.annotate(f"{rate:.1f}%", xy=(rate + margin, bar.get_y() + bar.get_height() / 2), xytext=(6, 0),
                        textcoords="offset points", va="center", color=_INK, fontsize=9, fontweight="bold")
        ax.set_title(titles.get(category, category), loc="left", color=_INK, fontsize=11, fontweight="bold", pad=8)
        ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
        limit = max(limit, max(r + m for r, m in zip(rates, margins)))
    for ax in axes:
        ax.set_xlim(0, limit * 1.12)
    axes[-1].set_xlabel(f"Win rate of one seat using the behavior; the line marks an even {even:.0f}% share",
                        color=_MUTED, fontsize=9)
    fig.suptitle(f"One behavior at a time against random play: {games:,} games each", x=0.01, ha="left",
                 color=_INK, fontsize=12, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(path, facecolor=_SURFACE)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="A/B test behaviors on top of random play")
    parser.add_argument("--categories", nargs="*", default=list(CATEGORIES), choices=list(CATEGORIES))
    parser.add_argument("--games", type=int, default=4000, help="games per behavior against random")
    parser.add_argument("--tournament-games", type=int, default=None,
                        help="games in each head-to-head tournament (default: 5 x --games)")
    parser.add_argument("--opening", default="adaptive")
    parser.add_argument("--players", type=int, default=4, choices=(2, 3, 4))
    parser.add_argument("--workers", type=int, default=1, help=f"processes to use (this machine has {os.cpu_count()})")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--plot", metavar="DIR", help="save behaviors.png here (needs matplotlib)")
    args = parser.parse_args()
    tournament_games = args.tournament_games or 5 * args.games
    even = 1 / args.players

    pool = Pool(args.workers) if args.workers > 1 else None
    results = {}
    try:
        for category in args.categories:
            names = list(CATEGORIES[category])
            start = time.perf_counter()
            solo = against_random(category, names, args.games, args.opening, args.players, args.seed, pool,
                                  args.workers)
            duel = head_to_head(category, names, tournament_games, args.opening, args.players, args.seed + 10**8,
                                pool, args.workers)
            elapsed = time.perf_counter() - start
            results[category] = solo

            base_turns = solo["random"][2] / solo["random"][1]
            print(f"\n{category.upper()}  ({elapsed:.0f} s)")
            print(f"  {'behavior':<18}{'vs random':>10}{'+/-':>7}{'vs even':>9}{'turns':>7}{'head to head':>14}{'+/-':>7}")
            for name in sorted(names, key=lambda n: -solo[n][0] / solo[n][1]):
                wins, n, turns = solo[name]
                rate, margin = _rate(wins, n)
                h_rate, h_margin = _rate(*duel[name])
                print(f"  {name:<18}{rate:>10.1%}{margin:>7.1%}{rate - even:>+9.1%}{turns / n:>7.0f}"
                      f"{h_rate:>14.1%}{h_margin:>7.1%}")
            print(f"  (random baseline games average {base_turns:.0f} turns)")
    finally:
        if pool is not None:
            pool.close()
            pool.join()

    if args.plot:
        os.makedirs(args.plot, exist_ok=True)
        path = os.path.join(args.plot, "behaviors.png")
        plot(results, args.players, args.games, path)
        print(f"\nchart   {path}")


if __name__ == "__main__":
    main()
