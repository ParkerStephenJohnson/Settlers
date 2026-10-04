"""Run many games and report speed and results.

    uv run python -m src.engine.simulate --games 10000 --workers 8 --plot ../docs
"""
import argparse
import os
import time
from collections import Counter
from multiprocessing import Pool

from .bots import BOTS
from .game import A_BUY, A_CITY, A_KNIGHT, A_ROAD, A_SETTLE, Game

# What the winner did on the move that took them to 10 points.
WINNING_MOVES = {
    A_CITY: "Built a city",
    A_SETTLE: "Built a settlement",
    A_BUY: "Drew a victory point card",
    A_KNIGHT: "Took Largest Army",
    A_ROAD: "Took Longest Road",
}
OTHER_MOVE = "Other"
POINT_SOURCES = ("Settlements", "Cities", "Victory point cards", "Longest Road", "Largest Army")


def play_game(seed, num_players=4, bot="random", max_turns=2000, dev_before_roll=True, player_trading=True, max_offers=None):
    """Play one full game. Returns (winner, turns, final points per player)."""
    game, _ = _run(seed, num_players, bot, max_turns, dev_before_roll, player_trading, max_offers)
    return game.winner, game.turn, [game.victory_points(p) for p in range(num_players)]


def play_game_stats(seed, num_players=4, bot="random", max_turns=2000, dev_before_roll=True, player_trading=True, max_offers=None):
    """Play one game and describe how it was won.

    Returns (winner, turns, winning move, points by source, player trades),
    where points by source follows POINT_SOURCES. Unfinished games return
    (-1, turns, None, None, player trades).
    """
    game, last = _run(seed, num_players, bot, max_turns, dev_before_roll, player_trading, max_offers)
    w = game.winner
    if w < 0:
        return -1, game.turn, None, None, game.player_trades
    points = (
        5 - game.settlements_left[w],
        2 * (4 - game.cities_left[w]),
        game.vp_cards[w],
        2 if game.longest_road == w else 0,
        2 if game.largest_army == w else 0,
    )
    return w, game.turn, WINNING_MOVES.get((last >> 8) & 255, OTHER_MOVE), points, game.player_trades


def _run(seed, num_players, bot, max_turns, dev_before_roll, player_trading, max_offers):
    game = Game(num_players, seed, max_turns, dev_before_roll, player_trading, max_offers)
    player = BOTS[bot]()
    choose = player.choose
    offers = player.lists_offers
    legal_actions = game.legal_actions
    apply = game.apply
    last = 0
    while not game.done:
        last = choose(game, legal_actions(offers))
        apply(last)
    return game, last


def run_game(bots, seed, max_turns=2000, **game_options):
    """Play one game with a separate bot in each seat. Returns the finished Game."""
    game = Game(len(bots), seed, max_turns, **game_options)
    legal_actions = game.legal_actions
    apply = game.apply
    while not game.done:
        bot = bots[game.to_move]
        apply(bot.choose(game, legal_actions(bot.lists_offers)))
    return game


def _play_batch(args):
    seeds, num_players, bot, max_turns, dev_before_roll, player_trading, max_offers = args
    return [play_game_stats(seed, num_players, bot, max_turns, dev_before_roll, player_trading, max_offers) for seed in seeds]


def simulate(games, num_players=4, bot="random", workers=1, seed=0, max_turns=2000, dev_before_roll=True, player_trading=True, max_offers=None):
    """Play ``games`` games. Returns one play_game_stats tuple per game."""
    seeds = range(seed, seed + games)
    if workers <= 1:
        return _play_batch((seeds, num_players, bot, max_turns, dev_before_roll, player_trading, max_offers))
    chunk = max(1, games // (workers * 4))
    batches = [
        (seeds[i:i + chunk], num_players, bot, max_turns, dev_before_roll, player_trading, max_offers) for i in range(0, games, chunk)
    ]
    with Pool(workers) as pool:
        results = []
        for batch in pool.imap_unordered(_play_batch, batches):
            results.extend(batch)
    return results


def summarize(results, num_players):
    """Aggregate simulate() output into counts and averages."""
    finished = [r for r in results if r[0] >= 0]
    n = len(finished)
    wins = [0] * num_players
    for r in finished:
        wins[r[0]] += 1
    moves = Counter(r[2] for r in finished)
    totals = [sum(r[3][i] for r in finished) for i in range(len(POINT_SOURCES))]
    return {
        "games": len(results),
        "finished": n,
        "avg_turns": sum(r[1] for r in finished) / n if n else 0,
        "avg_player_trades": sum(r[4] for r in finished) / n if n else 0,
        "wins": wins,
        "winning_moves": moves.most_common(),
        "avg_points": [t / n if n else 0 for t in totals],
        "held_longest_road": sum(1 for r in finished if r[3][3]) / n if n else 0,
        "held_largest_army": sum(1 for r in finished if r[3][4]) / n if n else 0,
        "had_vp_card": sum(1 for r in finished if r[3][2]) / n if n else 0,
    }


# ---------------------------------------------------------------------- charts

_SURFACE, _INK, _MUTED, _GRID, _BLUE = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1", "#2a78d6"


def _pyplot():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _style(ax, grid_axis):
    ax.set_facecolor(_SURFACE)
    ax.tick_params(colors=_MUTED, length=0, labelsize=9)
    ax.grid(axis=grid_axis, color=_GRID, linewidth=1)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)


def plot_wins(wins, games, path, title):
    """Save a column chart of wins by seat (seat 1 moves first)."""
    plt = _pyplot()
    seats = [f"Seat {i + 1}" for i in range(len(wins))]
    shares = [100 * w / games for w in wins]
    even = 100 / len(wins)

    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=160, facecolor=_SURFACE)
    _style(ax, "y")
    bars = ax.bar(seats, shares, width=0.5, color=_BLUE, zorder=3)
    ax.axhline(even, color=_MUTED, linewidth=1, zorder=2)
    ax.annotate(f"Even split {even:.0f}%", xy=(0, even), xycoords=("axes fraction", "data"), xytext=(2, 4),
                textcoords="offset points", ha="left", color=_MUTED, fontsize=8)
    for bar, share, count in zip(bars, shares, wins):
        x = bar.get_x() + bar.get_width() / 2
        ax.annotate(f"{share:.1f}%", xy=(x, share), xytext=(0, 4), textcoords="offset points", ha="center",
                    color=_INK, fontsize=10, fontweight="bold", zorder=4,
                    bbox={"facecolor": _SURFACE, "edgecolor": "none", "pad": 1.5})
        ax.annotate(f"{count:,} wins", xy=(x, 0), xytext=(0, 5), textcoords="offset points", ha="center",
                    color="white", fontsize=8, zorder=4)
    ax.set_ylim(0, max(shares) * 1.18)
    ax.set_ylabel("Share of finished games", color=_MUTED, fontsize=9)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.set_title(title, loc="left", color=_INK, fontsize=12, fontweight="bold", pad=14)
    fig.tight_layout()
    fig.savefig(path, facecolor=_SURFACE)
    plt.close(fig)


def plot_win_conditions(summary, path, title):
    """Save two bar charts: the winning move, and where winners' points came from."""
    plt = _pyplot()
    n = summary["finished"]
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.4), dpi=160, facecolor=_SURFACE)

    moves = summary["winning_moves"][::-1]
    labels = [m for m, _ in moves]
    shares = [100 * c / n for _, c in moves]
    _style(left, "x")
    bars = left.barh(labels, shares, height=0.5, color=_BLUE, zorder=3)
    for bar, share in zip(bars, shares):
        left.annotate(f"{share:.1f}%", xy=(share, bar.get_y() + bar.get_height() / 2), xytext=(5, 0),
                      textcoords="offset points", va="center", color=_INK, fontsize=9, fontweight="bold")
    left.set_xlim(0, max(shares) * 1.2)
    left.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    left.set_title("The move that reached 10 points", loc="left", color=_INK, fontsize=11, fontweight="bold", pad=10)
    left.set_xlabel("Share of finished games", color=_MUTED, fontsize=9)

    pairs = sorted(zip(POINT_SOURCES, summary["avg_points"]), key=lambda x: x[1])
    labels = [p for p, _ in pairs]
    values = [v for _, v in pairs]
    _style(right, "x")
    bars = right.barh(labels, values, height=0.5, color=_BLUE, zorder=3)
    for bar, value in zip(bars, values):
        right.annotate(f"{value:.1f}", xy=(value, bar.get_y() + bar.get_height() / 2), xytext=(5, 0),
                       textcoords="offset points", va="center", color=_INK, fontsize=9, fontweight="bold")
    right.set_xlim(0, max(values) * 1.2)
    right.set_title("Where the winner's points came from", loc="left", color=_INK, fontsize=11, fontweight="bold",
                    pad=10)
    right.set_xlabel("Average points per winner", color=_MUTED, fontsize=9)

    fig.suptitle(title, x=0.01, ha="left", color=_INK, fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(path, facecolor=_SURFACE)
    plt.close(fig)


# ---------------------------------------------------------------------- CLI


def main():
    parser = argparse.ArgumentParser(description="Simulate Catan games")
    parser.add_argument("--games", type=int, default=1000)
    parser.add_argument("--players", type=int, default=4, choices=(2, 3, 4))
    parser.add_argument("--bot", default="random", choices=sorted(BOTS),
                        help="random: pure chance (default); greedy: a simple strategy")
    parser.add_argument("--workers", type=int, default=1, help=f"processes to use (this machine has {os.cpu_count()})")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-turns", type=int, default=2000)
    parser.add_argument("--no-dev-before-roll", action="store_true",
                        help="house rule: development cards may only be played after rolling")
    parser.add_argument("--no-player-trading", action="store_true", help="bank and port trades only")
    parser.add_argument("--max-offers", type=int, default=None,
                        help="cap trade offers per turn (default: no limit); a low cap runs faster")
    parser.add_argument("--plot", metavar="DIR",
                        help="save wins_by_seat.png and win_conditions.png here (needs matplotlib)")
    args = parser.parse_args()

    start = time.perf_counter()
    results = simulate(args.games, args.players, args.bot, args.workers, args.seed, args.max_turns,
                       not args.no_dev_before_roll, not args.no_player_trading, args.max_offers)
    elapsed = time.perf_counter() - start
    s = summarize(results, args.players)
    n = s["finished"]

    print(f"{args.games} games, {args.players} {args.bot} bots, {args.workers} worker(s)")
    print(f"  time           {elapsed:.2f} s")
    print(f"  speed          {args.games / elapsed:,.0f} games/s")
    print(f"  finished       {n} ({n / args.games:.1%})")
    if not n:
        return
    print(f"  avg turns      {s['avg_turns']:.0f}")
    print(f"  player trades  {s['avg_player_trades']:.1f} per game")
    print("  wins by seat   " + "  ".join(f"{i + 1}: {w / n:.1%}" for i, w in enumerate(s["wins"])))
    print("\nThe move that reached 10 points")
    for move, count in s["winning_moves"]:
        print(f"  {move:<28}{count / n:6.1%}")
    print("\nWinner's points by source (average)")
    for source, value in sorted(zip(POINT_SOURCES, s["avg_points"]), key=lambda x: -x[1]):
        print(f"  {source:<28}{value:6.2f}")
    print("\nShare of winners who")
    print(f"  {'held Longest Road':<28}{s['held_longest_road']:6.1%}")
    print(f"  {'held Largest Army':<28}{s['held_largest_army']:6.1%}")
    print(f"  {'had a victory point card':<28}{s['had_vp_card']:6.1%}")

    if args.plot:
        os.makedirs(args.plot, exist_ok=True)
        label = f"{n:,} games, {args.players} {args.bot} bots"
        seats = os.path.join(args.plot, "wins_by_seat.png")
        conditions = os.path.join(args.plot, "win_conditions.png")
        plot_wins(s["wins"], n, seats, f"Wins by seat: {label}")
        plot_win_conditions(s, conditions, f"How games were won: {label}")
        print(f"\n  charts         {seats}, {conditions}")


if __name__ == "__main__":
    main()
