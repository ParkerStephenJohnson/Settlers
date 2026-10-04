"""Compare opening policies.

Everyone plays at random after the opening, so differences in win rate come
from where the first two settlements and roads were placed.

Head to head (the default): every seat in a game uses a different opening, so
the policies compete for the same spots. Line-ups and seats are shuffled.

Against random (``--vs-random``): one seat uses the opening under test and the
other three open at random.

    uv run python -m src.engine.openings --games 100000 --workers 16 --diff --plot ../docs
"""
import argparse
import math
import os
import random
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


def _tournament_batch(args):
    openings, seeds, num_players = args
    plays = {name: 0 for name in openings}
    wins = {name: 0 for name in openings}
    points = {name: 0 for name in openings}
    for seed in seeds:
        # A different opening in every seat, drawn and ordered by the seed.
        lineup = random.Random(seed * 7919 + 1).sample(openings, num_players)
        game = run_game([PhasedBot(name) for name in lineup], seed)
        if game.winner < 0:
            continue
        for seat, name in enumerate(lineup):
            plays[name] += 1
            points[name] += game.victory_points(seat)
        wins[lineup[game.winner]] += 1
    return plays, wins, points


def tournament(openings, games, num_players=4, workers=1, seed=0):
    """Play openings against each other, a different one in every seat.

    Returns {opening: (wins, games played, total points)}.
    """
    openings = list(openings)
    if len(openings) < num_players:
        raise ValueError(f"need at least {num_players} openings to fill every seat")
    seeds = range(seed, seed + games)
    chunk = max(1, games // (max(workers, 1) * 4))
    jobs = [(openings, seeds[i:i + chunk], num_players) for i in range(0, games, chunk)]
    totals = {name: [0, 0, 0] for name in openings}
    if workers <= 1:
        results = list(map(_tournament_batch, jobs))
    else:
        with Pool(workers) as pool:
            results = pool.map(_tournament_batch, jobs)
    for plays, wins, points in results:
        for name in openings:
            totals[name][0] += wins[name]
            totals[name][1] += plays[name]
            totals[name][2] += points[name]
    return {name: tuple(v) for name, v in totals.items()}


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
    for opening, total in totals.items():
        wins, n = total[0], total[1]
        rate = wins / n
        margin = 1.96 * math.sqrt(rate * (1 - rate) / n)
        rows.append((opening, rate, margin, rate - even))
    return sorted(rows, key=lambda row: -row[1])


def plot(rows, num_players, path, title, xlabel):
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
    ax.set_xlabel(xlabel, color=_MUTED, fontsize=9)
    ax.set_title(title, loc="left", color=_INK, fontsize=11, fontweight="bold", pad=16)
    fig.tight_layout()
    fig.savefig(path, facecolor=_SURFACE)
    plt.close(fig)


def main():
    competitors = sorted(name for name in OPENINGS if name != "random")
    parser = argparse.ArgumentParser(description="Compare opening policies")
    parser.add_argument("--games", type=int, default=5000,
                        help="games in the tournament, or games per opening with --vs-random")
    parser.add_argument("--players", type=int, default=4, choices=(2, 3, 4))
    parser.add_argument("--workers", type=int, default=1, help=f"processes to use (this machine has {os.cpu_count()})")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--openings", nargs="*", default=competitors, choices=sorted(OPENINGS))
    parser.add_argument("--vs-random", action="store_true",
                        help="test each opening alone against three random openings instead")
    parser.add_argument("--diff", action="store_true",
                        help="after the tournament, also run --vs-random and show both side by side")
    parser.add_argument("--plot", metavar="DIR", help="save a chart here (needs matplotlib)")
    args = parser.parse_args()
    even = 1 / args.players
    after = "random play after the opening"

    if args.vs_random:
        start = time.perf_counter()
        rows = summarize(compare(args.openings, args.games, args.players, args.workers, args.seed), args.players)
        elapsed = time.perf_counter() - start
        print(f"Against random openings: {args.games} games per opening, {args.workers} worker(s), {elapsed:.1f} s")
        print()
        print(f"  {'opening':<14}{'win rate':>10}{'+/-':>8}{'vs even':>10}")
        for opening, rate, margin, lift in rows:
            print(f"  {opening:<14}{rate:>10.1%}{margin:>8.1%}{lift:>+10.1%}")
        if args.plot:
            os.makedirs(args.plot, exist_ok=True)
            path = os.path.join(args.plot, "openings_vs_random.png")
            plot(rows, args.players, path, f"Win rate against random openings: {args.games:,} games each, {after}",
                 "Win rate of the seat using the opening (bars show the 95% interval)")
            print()
            print(f"  chart   {path}")
        return

    start = time.perf_counter()
    totals = tournament(args.openings, args.games, args.players, args.workers, args.seed)
    elapsed = time.perf_counter() - start
    rows = summarize(totals, args.players)
    print(f"Head to head: {args.games} games, a different opening in every seat, {args.workers} worker(s)")
    print(f"  time    {elapsed:.1f} s   ({args.games / elapsed:,.0f} games/s)")
    print()
    print(f"  {'opening':<14}{'games':>8}{'win rate':>10}{'+/-':>8}{'vs even':>10}{'avg points':>12}")
    for opening, rate, margin, lift in rows:
        wins, played, points = totals[opening]
        print(f"  {opening:<14}{played:>8}{rate:>10.1%}{margin:>8.1%}{lift:>+10.1%}{points / played:>12.2f}")

    if args.plot:
        os.makedirs(args.plot, exist_ok=True)
        path = os.path.join(args.plot, "openings.png")
        plot(rows, args.players, path, f"Openings head to head: {args.games:,} games, {after}",
             "Win rate when every seat uses a different opening (bars show the 95% interval)")
        print()
        print(f"  chart   {path}")

    if args.diff:
        per_opening = max(1, args.games // len(args.openings))
        solo = {r[0]: r for r in summarize(
            compare(args.openings, per_opening, args.players, args.workers, args.seed), args.players)}
        print()
        print(f"Head to head, next to each opening alone against three random openings ({per_opening} games each)")
        print(f"  {'opening':<14}{'head to head':>14}{'rank':>6}{'vs random':>12}{'rank':>6}")
        solo_rank = {name: i + 1 for i, name in enumerate(sorted(solo, key=lambda n: -solo[n][1]))}
        for i, (opening, rate, _, lift) in enumerate(rows):
            print(f"  {opening:<14}{rate:>14.1%}{i + 1:>6}{solo[opening][1]:>12.1%}{solo_rank[opening]:>6}")


if __name__ == "__main__":
    main()
