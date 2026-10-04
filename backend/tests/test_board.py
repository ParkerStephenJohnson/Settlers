from collections import Counter

from fastapi.testclient import TestClient

from main import app
from src.board import CLASSIC_NUMBERS, CLASSIC_TERRAIN, TerrainType, create_board


def test_classic_board_has_19_hexes_in_3_4_5_4_3_rows():
    board = create_board()
    assert len(board.hexagons) == 19
    rows = Counter(h.r for h in board.hexagons)
    assert [rows[r] for r in range(5)] == [3, 4, 5, 4, 3]


def test_hex_coordinates_are_unique():
    board = create_board()
    assert len({(h.q, h.r) for h in board.hexagons}) == 19


def test_terrain_counts_match_classic_distribution():
    board = create_board()
    counts = Counter(h.terrain for h in board.hexagons)
    assert counts == {terrain: count for terrain, _, count in CLASSIC_TERRAIN}


def test_every_number_token_is_placed_once_and_desert_gets_none():
    board = create_board()
    numbers = [h.number for h in board.hexagons if h.number is not None]
    assert sorted(numbers) == sorted(CLASSIC_NUMBERS)
    desert = [h for h in board.hexagons if h.terrain == TerrainType.DESERT]
    assert len(desert) == 1
    assert desert[0].number is None
    assert desert[0].has_robber


def test_fixed_board_is_deterministic():
    assert create_board(randomize=False).to_dict() == create_board(randomize=False).to_dict()


def test_new_board_endpoint_returns_19_hexes():
    response = TestClient(app).get("/api/board/new")
    assert response.status_code == 200
    assert len(response.json()["hexagons"]) == 19
