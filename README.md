# Settlers

[![CI](https://github.com/ParkerStephenJohnson/Settlers/actions/workflows/ci.yml/badge.svg)](https://github.com/ParkerStephenJohnson/Settlers/actions/workflows/ci.yml)

A Catan board simulator: a Python API that generates boards and a React app that draws them.

![A generated Catan board](docs/board.png)

## What it does today

- **Game engine:** plays complete games of Catan from setup to a 10-point win, with computer players that trade with each other, at about 130 games per second on one core with unlimited trading
- **Board API:** generates a classic 19-hex board in the 3-4-5-4-3 layout and serves it as JSON from FastAPI
- **Web app:** renders the board as SVG in the browser, with red 6s and 8s and the robber starting on the desert

The engine and the web app are not connected yet: the browser shows boards, and games run from the command line.

## Game engine

The engine lives in `backend/src/engine` and is built to finish many games quickly.

```bash
cd backend
uv run python -m src.engine.simulate --games 100000 --workers 16
```

```
100000 games, 4 greedy bots, 16 worker(s)
  time           68.12 s
  speed          1,468 games/s
  finished       99930 (99.9%)
  avg turns      84
  player trades  12.4 per game
  wins by seat   1: 21.5%  2: 24.0%  3: 26.2%  4: 28.2%
```

That run was on a 16-core Windows desktop, with unlimited trading between players. One core does about 130 games per second. Trading is the main cost, so there are two faster settings:

| Setting | Games per second (16 workers) | Turns per game |
|---|---|---|
| Unlimited offers (default) | 1,468 | 84 |
| `--max-offers 3` | 2,029 | 85 |
| `--no-player-trading` | 3,472 | 101 |

Add `--plot ../docs` to save two charts. Later seats won more often with these bots:

![Wins by seat over 99,924 finished games](docs/wins_by_seat.png)

Cities decided most games, and about a fifth ended on a victory point card:

![How games were won](docs/win_conditions.png)

**Rules covered:** the setup draft, production with bank shortages, the robber and discards on a 7, roads, settlements, cities, all five development cards, ports and bank trades, trades between players, longest road, largest army, and winning at 10 points.

Rules follow the official CATAN base game rulebook (2020 edition), including playing one development card at any time in your turn, before or after the roll, and keeping 6s and 8s apart. Pass `--no-dev-before-roll` for the house rule that cards wait until after the roll.

**Trading between players:** on your turn you can offer any bundle of cards for any other bundle, as many times as you like. Players holding everything you asked for answer in seat order, and if several accept you pick one. An offer that was just turned down cannot be repeated until a trade goes through or the turn ends. Gifts and swaps of the same resource are not allowed.

**Not covered yet:** the official harbour positions (harbours are spaced evenly with shuffled types).

**Players:**

- `greedy` builds the most valuable thing it can afford and trades toward its next purchase, with other players first and the bank second. It asks for everything it is missing in one bundle and adds cards to its offer each time it is turned down. It accepts a trade that brings its own next purchase closer. About one game in a thousand stalls and is stopped at the turn limit.
- `random` picks any legal move. Games take about three times as many turns.

**How it stays fast:** board geometry is computed once at import. Game state is flat lists of integers indexed by player, hex, node and edge. Actions are single integers. Games are seeded, so any game can be replayed exactly.

Using it from Python:

```python
from src.engine import Game, GreedyBot

game = Game(num_players=4, seed=1)
bot = GreedyBot()
while not game.done:
    game.apply(bot.choose(game, game.legal_actions()))
print(game.winner, game.turn)
```

## How it works

For the board API, the backend lays hexes out in offset rows, then converts them to axial coordinates (`q`, `r`) so the frontend can place each hex with one formula. The conversion follows the [Red Blob Games hexagonal grid guide](https://www.redblobgames.com/grids/hexagons/).

```
backend/
  main.py          FastAPI app and routes
  src/board.py     Board generation for the API
  src/engine/      Game engine, computer players and simulator
  tests/           Board, API and engine tests
frontend/
  src/App.tsx      Board rendering
```

## Running it

You need Python 3.9+ with [uv](https://docs.astral.sh/uv/), and Node.js.

Start the API on port 8000:

```bash
cd backend
uv sync
uv run python main.py
```

Start the web app on port 5173, in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173.

## API

| Route | Returns |
|---|---|
| `GET /api/board/new` | A shuffled board |
| `GET /api/board/new?randomize=false` | The same board every time |

Each hex looks like this:

```json
{ "q": 1, "r": 0, "terrain": "hills", "resource": "brick", "number": 6, "has_robber": false }
```

## Tests

```bash
cd backend
uv run pytest
```

## License

[MIT](LICENSE)

## Note

This is a personal project. It is not affiliated with or endorsed by Catan GmbH or Catan Studio.
