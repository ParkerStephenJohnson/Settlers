# Settlers

A Catan board simulator: a Python API that generates boards and a React app that draws them.

![A generated Catan board](docs/board.png)

## What it does today

- Generates a classic 19-hex board in the 3-4-5-4-3 layout, with the standard terrain mix and number tokens
- Serves boards as JSON from a FastAPI endpoint, either shuffled or in a fixed order
- Renders the board as SVG in the browser, with red 6s and 8s and the robber starting on the desert

This is an early version. Resource production and game simulation come next.

## How it works

The backend lays hexes out in offset rows, then converts them to axial coordinates (`q`, `r`) so the frontend can place each hex with one formula. The conversion follows the [Red Blob Games hexagonal grid guide](https://www.redblobgames.com/grids/hexagons/).

```
backend/
  main.py          FastAPI app and routes
  src/board.py     Board generation
  tests/           Board and API tests
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

## Note

This is a personal project. It is not affiliated with or endorsed by Catan GmbH or Catan Studio.
