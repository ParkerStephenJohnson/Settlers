# Settlers

[![CI](https://github.com/ParkerStephenJohnson/Settlers/actions/workflows/ci.yml/badge.svg)](https://github.com/ParkerStephenJohnson/Settlers/actions/workflows/ci.yml)

A Catan board simulator: a Python API that generates boards and a React app that draws them.

![A generated Catan board](docs/board.png)

## What it does today

- **Game engine:** plays complete games of Catan from setup to a 10-point win, with computer players, at about 430 games per second on one core
- **Board API:** generates a classic 19-hex board in the 3-4-5-4-3 layout and serves it as JSON from FastAPI
- **Web app:** renders the board as SVG in the browser, with red 6s and 8s and the robber starting on the desert

The engine and the web app are not connected yet: the browser shows boards, and games run from the command line.

## Game engine

The engine lives in `backend/src/engine` and is built to finish many games quickly.

```bash
cd backend
uv run python -m src.engine.simulate --games 20000 --workers 8
```

```
20000 games, 4 greedy bots, 8 worker(s)
  time           7.88 s
  speed          2,539 games/s
  finished       19977 (99.9%)
  avg turns      100
  wins by seat   0: 22.4%  1: 23.8%  2: 26.0%  3: 27.9%
```

That run was on a 16-core Windows desktop. One core does about 430 games per second.

Add `--plot wins.png` to save a chart of wins by seat. Over 100,000 games on 16 workers (3,718 games per second), later seats won more often with these bots:

![Wins by seat over 99,873 finished games](docs/wins_by_seat.png)

**Rules covered:** the setup draft, production with bank shortages, the robber and discards on a 7, roads, settlements, cities, all five development cards, ports and bank trades, longest road, largest army, and winning at 10 points.

**Not covered yet:** trading between players, and the rule against placing 6s and 8s next to each other.

**Players:**

- `greedy` builds the most valuable thing it can afford and trades with the bank toward its next purchase. About one game in a thousand stalls and is stopped at the turn limit.
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
