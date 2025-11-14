import random
from typing import List, Dict, Tuple
from enum import Enum


class TerrainType(Enum):
    HILLS = "hills"
    FOREST = "forest"
    MOUNTAINS = "mountains"
    FIELDS = "fields"
    PASTURE = "pasture"
    DESERT = "desert"


class ResourceType(Enum):
    BRICK = "brick"
    LUMBER = "lumber"
    ORE = "ore"
    GRAIN = "grain"
    WOOL = "wool"
    NONE = "none"


# Classic Catan terrain distribution
CLASSIC_TERRAIN = [
    (TerrainType.HILLS, ResourceType.BRICK, 3),
    (TerrainType.FOREST, ResourceType.LUMBER, 4),
    (TerrainType.MOUNTAINS, ResourceType.ORE, 3),
    (TerrainType.FIELDS, ResourceType.GRAIN, 4),
    (TerrainType.PASTURE, ResourceType.WOOL, 4),
    (TerrainType.DESERT, ResourceType.NONE, 1),
]

# Classic Catan number tokens (excluding 7)
CLASSIC_NUMBERS = [2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12]


class Hexagon:
    def __init__(
        self,
        q: int,
        r: int,
        terrain: TerrainType,
        resource: ResourceType,
        number: int = None,
    ):
        self.q = q  # Axial coordinates
        self.r = r
        self.terrain = terrain
        self.resource = resource
        self.number = number
        self.has_robber = terrain == TerrainType.DESERT

    def to_dict(self) -> Dict:
        return {
            "q": self.q,
            "r": self.r,
            "terrain": self.terrain.value,
            "resource": self.resource.value,
            "number": self.number,
            "has_robber": self.has_robber,
        }


class Board:
    def __init__(self, randomize: bool = True):
        self.hexagons: List[Hexagon] = []
        self.generate_classic_board(randomize)

    def generate_classic_board(self, randomize: bool):
        """Generate a classic Catan board in the proper 3-4-5-4-3 layout using offset coordinates"""

        # Classic Catan uses an offset coordinate system internally
        # We'll generate in offset coords then convert to axial
        # The layout is 3-4-5-4-3 rows (offset coordinates)

        # Offset coordinate positions for Classic Catan (odd-r horizontal layout)
        # Centered layout (3-4-5-4-3):
        # Row 0: 3 hexes (cols 1,2,3) - offset by 1
        # Row 1: 4 hexes (cols 0,1,2,3) - offset by 0
        # Row 2: 5 hexes (cols 0,1,2,3,4) - offset by 0 (widest row)
        # Row 3: 4 hexes (cols 0,1,2,3) - offset by 0
        # Row 4: 3 hexes (cols 1,2,3) - offset by 1

        offset_positions = []
        row_configs = [
            (0, 3, 1),  # row 0: 3 hexes starting at col 1
            (1, 4, 0),  # row 1: 4 hexes starting at col 0
            (2, 5, 0),  # row 2: 5 hexes starting at col 0 (center/widest)
            (3, 4, 0),  # row 3: 4 hexes starting at col 0
            (4, 3, 1),  # row 4: 3 hexes starting at col 1
        ]

        for row, count, start_col in row_configs:
            for col in range(start_col, start_col + count):
                offset_positions.append((col, row))

        # Generate terrain tiles
        terrain_tiles = []
        for terrain, resource, count in CLASSIC_TERRAIN:
            terrain_tiles.extend([(terrain, resource)] * count)

        if randomize:
            random.shuffle(terrain_tiles)
            numbers = CLASSIC_NUMBERS.copy()
            random.shuffle(numbers)
        else:
            # Use a fixed layout for consistency
            numbers = CLASSIC_NUMBERS.copy()

        number_index = 0

        for i, (col, row) in enumerate(offset_positions):
            terrain, resource = terrain_tiles[i]

            # Convert offset coordinates to axial (odd-r horizontal layout)
            # Formula from Red Blob Games: q = col - (row - (row&1)) / 2
            q = col - (row - (row & 1)) // 2
            r = row

            if terrain == TerrainType.DESERT:
                hex_tile = Hexagon(q, r, terrain, resource, None)
            else:
                hex_tile = Hexagon(q, r, terrain, resource, numbers[number_index])
                number_index += 1

            self.hexagons.append(hex_tile)

    def to_dict(self) -> Dict:
        return {"hexagons": [hex.to_dict() for hex in self.hexagons]}


def create_board(randomize: bool = True) -> Board:
    """Factory function to create a new board"""
    return Board(randomize)
