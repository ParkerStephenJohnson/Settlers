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


def plot_wins(wins, games, path, title):
    """Save a column chart of wins by seat (seat 1 moves first)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    surface, ink, muted, grid, blue = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1", "#2a78d6"
    seats = [f"Seat {i + 1}" for i in range(len(wins))]
    shares = [100 * w / games for w in wins]
    even = 100 / len(wins)

    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=160, facecolor=surface)
    ax.set_facecolor(surface)
    bars = ax.bar(seats, shares, width=0.5, color=blue, zorder=3)
    ax.axhline(even, color=muted, linewidth=1, zorder=2)
    ax.annotate(f"Even split {even:.0f}%", xy=(0, even), xycoords=("axes fraction", "data"), xytext=(2, 4),
                textcoords="offset points", ha="left", color=muted, fontsize=8)
    for bar, share, count in zip(bars, shares, wins):
        ax.annotate(f"{share:.1f}%", xy=(bar.get_x() + bar.get_width() / 2, share), xytext=(0, 4),
                    textcoords="offset points", ha="center", color=ink, fontsize=10, fontweight="bold", zorder=4,
                    bbox={"facecolor": surface, "edgecolor": "none", "pad": 1.5})
        ax.annotate(f"{count:,} wins", xy=(bar.get_x() + bar.get_width() / 2, 0), xytext=(0, 5),
                    textcoords="offset points", ha="center", color="white", fontsize=8, zorder=4)
    ax.set_ylim(0, max(shares) * 1.18)
    ax.set_ylabel("Share of finished games", color=muted, fontsize=9)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.tick_params(colors=muted, length=0, labelsize=9)
    ax.grid(axis="y", color=grid, linewidth=1)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(grid)
    ax.set_title(title, loc="left", color=ink, fontsize=12, fontweight="bold", pad=14)
    fig.tight_layout()
    fig.savefig(path, facecolor=surface)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Simulate Catan games")
    parser.add_argument("--games", type=int, default=1000)
    parser.add_argument("--players", type=int, default=4, choices=(2, 3, 4))
    parser.add_argument("--bot", default="greedy", choices=sorted(BOTS))
    parser.add_argument("--workers", type=int, default=1, help=f"processes to use (this machine has {os.cpu_count()})")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-turns", type=int, default=2000)
    parser.add_argument("--plot", metavar="PNG", help="save a chart of wins by seat (needs matplotlib)")
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
        print("  wins by seat   " + "  ".join(f"{i + 1}: {wins[i] / len(finished):.1%}" for i in range(args.players)))
        if args.plot:
            title = f"Wins by seat: {len(finished):,} games, {args.players} {args.bot} bots"
            plot_wins(wins, len(finished), args.plot, title)
            print(f"  chart          {args.plot}")


if __name__ == "__main__":
    main()
