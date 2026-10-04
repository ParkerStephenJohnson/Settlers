"""Compare opening policies.

One seat uses the opening under test; the other three open at random. Everyone
plays at random after the opening, so any change in that seat's win rate comes
from where it placed its first two settlements and roads.

    uv run python -m src.engine.openings --games 20000 --workers 16 --plot ../docs
"""
import argparse
import math
import os
import time
from multiprocessing import Pool

from .bots import OPENINGS, PhasedBot
from .simulate import _MUTED, _BLUE, _INK, _SURFACE, _pyplot, _style, run_game


def _play_batch(args):
    opening, seeds, num_players = args
    wins = finished = 0
    for seed in seeds:
        seat = seed % num_players  # rotate the seat so position cancels out
        bots = [PhasedBot("random") for _ in range(num_players)]
        bots[seat] = PhasedBot(opening)
        game = run_game(bots, seed)
        if game.winner >= 0:
            finished += 1
            wins += game.winner == seat
    return opening, wins, finished


def compare(openings, games, num_players=4, workers=1, seed=0):
    """Win counts per opening. Every opening is tested on the same seeds.

    Returns {opening: (wins, finished games)}.
    """
    seeds = range(seed, seed + games)
    chunk = max(1, games // (max(workers, 1) * 4))
    jobs = [
        (opening, seeds[i:i + chunk], num_players)
        for opening in openings
        for i in range(0, games, chunk)
    ]
    totals = {opening: [0, 0] for opening in openings}
    if workers <= 1:
        results = map(_play_batch, jobs)
    else:
        pool = Pool(workers)
        results = pool.imap_unordered(_play_batch, jobs)
    for opening, wins, finished in results:
        totals[opening][0] += wins
        totals[opening][1] += finished
    if workers > 1:
        pool.close()
        pool.join()
    return {opening: tuple(v) for opening, v in totals.items()}


def summarize(totals, num_players):
    """Rows of (opening, win rate, 95% margin, lift over an even share), best first."""
    even = 1 / num_players
    rows = []
    for opening, (wins, n) in totals.items():
        rate = wins / n
        margin = 1.96 * math.sqrt(rate * (1 - rate) / n)
        rows.append((opening, rate, margin, rate - even))
    return sorted(rows, key=lambda row: -row[1])


def plot(rows, num_players, games, path):
    """Save a bar chart of win rate by opening, with 95% intervals."""
    plt = _pyplot()
    rows = rows[::-1]
    labels = [r[0] for r in rows]
    rates = [100 * r[1] for r in rows]
    margins = [100 * r[2] for r in rows]
    even = 100 / num_players

    fig, ax = plt.subplots(figsize=(8, 0.6 * len(rows) + 1.8), dpi=160, facecolor=_SURFACE)
    _style(ax, "x")
    bars = ax.barh(labels, rates, height=0.5, color=_BLUE, zorder=3)
    ax.errorbar(rates, range(len(rows)), xerr=margins, fmt="none", ecolor=_INK, elinewidth=1, capsize=3, zorder=4)
    ax.axvline(even, color=_MUTED, linewidth=1, zorder=2)
    ax.annotate(f"Even share {even:.0f}%", xy=(even, 1), xycoords=("data", "axes fraction"), xytext=(4, 2),
                textcoords="offset points", color=_MUTED, fontsize=8, va="bottom")
    for bar, rate, margin in zip(bars, rates, margins):
        ax.annotate(f"{rate:.1f}%", xy=(rate + margin, bar.get_y() + bar.get_height() / 2), xytext=(6, 0),
                    textcoords="offset points", va="center", color=_INK, fontsize=9, fontweight="bold")
    ax.set_xlim(0, max(r + m for r, m in zip(rates, margins)) * 1.15)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.set_xlabel("Win rate of the seat using the opening (bars show the 95% interval)", color=_MUTED, fontsize=9)
    ax.set_title(f"Win rate by opening: {games:,} games each, random play after the opening",
                 loc="left", color=_INK, fontsize=11, fontweight="bold", pad=16)
    fig.tight_layout()
    fig.savefig(path, facecolor=_SURFACE)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Compare opening policies")
    parser.add_argument("--games", type=int, default=5000, help="games per opening")
    parser.add_argument("--players", type=int, default=4, choices=(2, 3, 4))
    parser.add_argument("--workers", type=int, default=1, help=f"processes to use (this machine has {os.cpu_count()})")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--openings", nargs="*", default=sorted(OPENINGS), choices=sorted(OPENINGS))
    parser.add_argument("--plot", metavar="DIR", help="save openings.png here (needs matplotlib)")
    args = parser.parse_args()

    start = time.perf_counter()
    totals = compare(args.openings, args.games, args.players, args.workers, args.seed)
    elapsed = time.perf_counter() - start
    rows = summarize(totals, args.players)
    played = args.games * len(args.openings)

    print(f"{args.games} games per opening, {args.players} players, {args.workers} worker(s)")
    print(f"  time    {elapsed:.1f} s   ({played / elapsed:,.0f} games/s)")
    print(f"\n  {'opening':<14}{'win rate':>10}{'+/-':>8}{'vs even':>10}")
    for opening, rate, margin, lift in rows:
        print(f"  {opening:<14}{rate:>10.1%}{margin:>8.1%}{lift:>+10.1%}")

    if args.plot:
        os.makedirs(args.plot, exist_ok=True)
        path = os.path.join(args.plot, "openings.png")
        plot(rows, args.players, args.games, path)
        print(f"\n  chart   {path}")


if __name__ == "__main__":
    main()
