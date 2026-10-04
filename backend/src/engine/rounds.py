"""A/B test one behavior at a time against the standard bot.

No seat plays at random. Three seats use STANDARD; the fourth changes exactly
one behavior. The seat rotates and every variant sees the same seeds, so a win
rate above an even share means the change beats the standard choice.

    uv run python -m src.engine.rounds --games 10000 --workers 16 --plot ../docs
"""
import argparse
import math
import os
import time
from multiprocessing import Pool

from .simulate import _BLUE, _INK, _MUTED, _SURFACE, _pyplot, _style, run_game
from .strategy import CATEGORIES, STANDARD, StrategyBot


def _batch(args):
    category, name, base, seeds, num_players = args
    wins = finished = turns = 0
    for seed in seeds:
        seat = seed % num_players
        bots = [StrategyBot(**base) for _ in range(num_players)]
        bots[seat] = StrategyBot(**dict(base, **{category: name}))
        game = run_game(bots, seed)
        if game.winner >= 0:
            finished += 1
            wins += game.winner == seat
            turns += game.turn
    return category, name, wins, finished, turns


def ab_test(categories, games, base=None, num_players=4, workers=1, seed=0):
    """{category: {variant: (wins, finished, total turns)}} for every variant of each category."""
    base = dict(base or STANDARD)
    seeds = range(seed, seed + games)
    size = max(1, games // (max(workers, 1) * 2))
    jobs = [
        (category, name, base, seeds[i:i + size], num_players)
        for category in categories
        for name in CATEGORIES[category]
        for i in range(0, games, size)
    ]
    totals = {c: {n: [0, 0, 0] for n in CATEGORIES[c]} for c in categories}
    if workers > 1:
        with Pool(workers) as pool:
            results = pool.map(_batch, jobs)
    else:
        results = map(_batch, jobs)
    for category, name, wins, finished, turns in results:
        t = totals[category][name]
        t[0] += wins
        t[1] += finished
        t[2] += turns
    return {c: {n: tuple(v) for n, v in rows.items()} for c, rows in totals.items()}


def rate(wins, n):
    r = wins / n if n else 0.0
    return r, (1.96 * math.sqrt(r * (1 - r) / n) if n else 0.0)


def winners(results, base, num_players):
    """Variants that beat the standard choice by more than the margin of error."""
    even = 1 / num_players
    better = {}
    for category, rows in results.items():
        best = max(rows, key=lambda n: rows[n][0] / rows[n][1])
        r, margin = rate(rows[best][0], rows[best][1])
        if best != base[category] and r - margin > even:
            better[category] = best
    return better


def plot(results, base, num_players, games, path, title):
    plt = _pyplot()
    even = 100 / num_players
    count = sum(len(r) for r in results.values())
    fig, axes = plt.subplots(len(results), 1, figsize=(8.5, 0.36 * count + 0.75 * len(results) + 1.0), dpi=160,
                             facecolor=_SURFACE, gridspec_kw={"height_ratios": [len(r) + 0.6 for r in results.values()]})
    if len(results) == 1:
        axes = [axes]
    limit = 0
    for ax, (category, rows) in zip(axes, results.items()):
        ranked = sorted(rows.items(), key=lambda kv: kv[1][0] / kv[1][1])
        labels = [f"{name} (standard)" if name == base[category] else name for name, _ in ranked]
        stats = [rate(v[0], v[1]) for _, v in ranked]
        rates = [100 * r for r, _ in stats]
        margins = [100 * m for _, m in stats]
        _style(ax, "x")
        bars = ax.barh(labels, rates, height=0.6, color=_BLUE, zorder=3)
        ax.errorbar(rates, range(len(labels)), xerr=margins, fmt="none", ecolor=_INK, elinewidth=1, capsize=2.5,
                    zorder=4)
        ax.axvline(even, color=_MUTED, linewidth=1, zorder=2)
        for bar, r, m in zip(bars, rates, margins):
            ax.annotate(f"{r:.1f}%", xy=(r + m, bar.get_y() + bar.get_height() / 2), xytext=(5, 0),
                        textcoords="offset points", va="center", color=_INK, fontsize=8, fontweight="bold")
        ax.set_title(category.capitalize(), loc="left", color=_INK, fontsize=10, fontweight="bold", pad=5)
        ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
        ax.tick_params(labelsize=8)
        limit = max(limit, max(r + m for r, m in zip(rates, margins)))
    for ax in axes:
        ax.set_xlim(0, limit * 1.12)
    axes[-1].set_xlabel(f"Win rate of the one seat that differs; the line marks an even {even:.0f}% share",
                        color=_MUTED, fontsize=9)
    fig.suptitle(title, x=0.01, ha="left", color=_INK, fontsize=12, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.975))
    fig.savefig(path, facecolor=_SURFACE)
    plt.close(fig)


def report(results, base, num_players):
    even = 1 / num_players
    for category, rows in results.items():
        print(f"\n{category.upper()}   (standard: {base[category]})")
        print(f"  {'variant':<20}{'win rate':>9}{'+/-':>7}{'vs even':>9}{'turns':>7}")
        for name in sorted(rows, key=lambda n: -rows[n][0] / rows[n][1]):
            wins, n, turns = rows[name]
            r, margin = rate(wins, n)
            mark = "  <- standard" if name == base[category] else ""
            print(f"  {name:<20}{r:>9.1%}{margin:>7.1%}{r - even:>+9.1%}{turns / n:>7.0f}{mark}")


def main():
    parser = argparse.ArgumentParser(description="A/B test behaviors against the standard bot")
    parser.add_argument("--categories", nargs="*", default=list(CATEGORIES), choices=list(CATEGORIES))
    parser.add_argument("--games", type=int, default=4000, help="games per variant")
    parser.add_argument("--rounds", type=int, default=1,
                        help="after each round, adopt the clear winners as the new standard and test again")
    parser.add_argument("--players", type=int, default=4, choices=(2, 3, 4))
    parser.add_argument("--workers", type=int, default=1, help=f"processes to use (this machine has {os.cpu_count()})")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--plot", metavar="DIR", help="save rounds_N.png here (needs matplotlib)")
    args = parser.parse_args()

    base = dict(STANDARD)
    for number in range(1, args.rounds + 1):
        start = time.perf_counter()
        results = ab_test(args.categories, args.games, base, args.players, args.workers,
                          args.seed + 10_000_000 * number)
        elapsed = time.perf_counter() - start
        played = args.games * sum(len(CATEGORIES[c]) for c in args.categories)
        print(f"\n===== ROUND {number}: {args.games} games per variant, {played / elapsed:,.0f} games/s, {elapsed:.0f} s")
        report(results, base, args.players)
        if args.plot:
            os.makedirs(args.plot, exist_ok=True)
            path = os.path.join(args.plot, f"rounds_{number}.png")
            plot(results, base, args.players, args.games, path,
                 f"Round {number}: one behavior changed in one seat, against three standard bots")
            print(f"\nchart   {path}")
        better = winners(results, base, args.players)
        if better:
            print("\nadopted into the standard: " + ", ".join(f"{c}={n}" for c, n in better.items()))
            base.update(better)
        else:
            print("\nno variant clearly beat the standard")
            break
    print("\nstandard after the last round:")
    for key, value in base.items():
        print(f"  {key:<9}{value}")


if __name__ == "__main__":
    main()
