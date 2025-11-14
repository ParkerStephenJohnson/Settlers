import { useState, useEffect } from "react";

// Types
interface Hexagon {
  q: number;
  r: number;
  terrain: string;
  resource: string;
  number: number | null;
  has_robber: boolean;
}

interface BoardData {
  hexagons: Hexagon[];
}

// Terrain colors
const TERRAIN_COLORS: Record<string, string> = {
  hills: "#D2691E",
  forest: "#228B22",
  mountains: "#708090",
  fields: "#FFD700",
  pasture: "#90EE90",
  desert: "#F4A460",
};

// Convert axial coordinates to pixel coordinates (pointy-top hexagons)
// Using Red Blob Games formulas for pointy-top orientation
// x = size * (sqrt(3) * q + sqrt(3)/2 * r)
// y = size * (3/2 * r)
const axialToPixel = (q: number, r: number, size: number) => {
  const x = size * (Math.sqrt(3) * q + (Math.sqrt(3) / 2) * r);
  const y = size * ((3 / 2) * r);
  return { x, y };
};

// Create hexagon path for pointy-top orientation (vertex at top)
const createHexagonPath = (size: number) => {
  const points = [];
  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 3) * i - Math.PI / 2; // Start at top vertex
    const x = size * Math.cos(angle);
    const y = size * Math.sin(angle);
    points.push(`${x},${y}`);
  }
  return points.join(" ");
};

const HexTile = ({ hex, size }: { hex: Hexagon; size: number }) => {
  const { x, y } = axialToPixel(hex.q, hex.r, size);
  const color = TERRAIN_COLORS[hex.terrain] || "#CCC";
  const hexPath = createHexagonPath(size);

  return (
    <g transform={`translate(${x}, ${y})`}>
      {/* Hexagon */}
      <polygon points={hexPath} fill={color} stroke="#654321" strokeWidth="2" />

      {/* Number token */}
      {hex.number && (
        <>
          <circle
            r={size * 0.35}
            fill="#F5DEB3"
            stroke="#654321"
            strokeWidth="2"
          />
          <text
            textAnchor="middle"
            dy="0.35em"
            fontSize={size * 0.4}
            fontWeight="bold"
            fill={hex.number === 6 || hex.number === 8 ? "#DC143C" : "#000"}
          >
            {hex.number}
          </text>
          <text
            textAnchor="middle"
            dy="1.2em"
            fontSize={size * 0.2}
            fill="#666"
          >
            {"•".repeat(6 - Math.abs(7 - hex.number))}
          </text>
        </>
      )}

      {/* Robber */}
      {hex.has_robber && (
        <circle r={size * 0.25} fill="#333" stroke="#000" strokeWidth="2" />
      )}

      {/* Resource text */}
      {hex.terrain === "desert" && (
        <text
          textAnchor="middle"
          dy="-1em"
          fontSize={size * 0.25}
          fill="#8B4513"
          fontWeight="bold"
        >
          DESERT
        </text>
      )}
    </g>
  );
};

const App = () => {
  const [boardData, setBoardData] = useState<BoardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const hexSize = 60;
  const viewBoxSize = 600;

  const fetchBoard = async (randomize: boolean = true) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `http://localhost:8000/api/board/new?randomize=${randomize}`
      );
      if (!response.ok) throw new Error("Failed to fetch board");
      const data = await response.json();
      setBoardData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBoard();
  }, []);

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
        padding: "20px",
        fontFamily: "Arial, sans-serif",
      }}
    >
      <div style={{ maxWidth: "100%", margin: "0 auto" }}>
        <h1
          style={{
            color: "white",
            textAlign: "center",
            fontSize: "2.5rem",
            marginBottom: "10px",
          }}
        >
          Catan Board Simulator
        </h1>

        <div
          style={{
            display: "flex",
            justifyContent: "center",
            gap: "10px",
            marginBottom: "20px",
          }}
        >
          <button
            onClick={() => fetchBoard(true)}
            style={{
              padding: "10px 20px",
              fontSize: "16px",
              background: "#4CAF50",
              color: "white",
              border: "none",
              borderRadius: "5px",
              cursor: "pointer",
            }}
          >
            New Random Board
          </button>
          <button
            onClick={() => fetchBoard(false)}
            style={{
              padding: "10px 20px",
              fontSize: "16px",
              background: "#2196F3",
              color: "white",
              border: "none",
              borderRadius: "5px",
              cursor: "pointer",
            }}
          >
            New Fixed Board
          </button>
        </div>

        {loading && (
          <div
            style={{ textAlign: "center", color: "white", fontSize: "1.2rem" }}
          >
            Loading board...
          </div>
        )}

        {error && (
          <div
            style={{
              textAlign: "center",
              color: "#ffcccb",
              fontSize: "1.2rem",
              background: "rgba(255,0,0,0.2)",
              padding: "20px",
              borderRadius: "10px",
            }}
          >
            Error: {error}
            <br />
            <small>
              Make sure the backend is running on http://localhost:8000
            </small>
          </div>
        )}

        {boardData && (
          <div
            style={{
              background: "white",
              borderRadius: "15px",
              padding: "20px",
              boxShadow: "0 10px 30px rgba(0,0,0,0.3)",
            }}
          >
            <svg
              width="100%"
              height="100%"
              viewBox={`-${viewBoxSize / 2} -${
                viewBoxSize / 2
              } ${viewBoxSize} ${viewBoxSize}`}
              style={{ width: "100%", height: "auto", display: "block" }}
              preserveAspectRatio="xMidYMid meet"
            >
              {boardData.hexagons.map((hex, idx) => (
                <HexTile key={idx} hex={hex} size={hexSize} />
              ))}
            </svg>

            <div
              style={{
                marginTop: "20px",
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                gap: "10px",
                fontSize: "14px",
              }}
            >
              <div>
                <strong>🧱 Brick (Hills):</strong>{" "}
                {boardData.hexagons.filter((h) => h.terrain === "hills").length}
              </div>
              <div>
                <strong>🪵 Lumber (Forest):</strong>{" "}
                {
                  boardData.hexagons.filter((h) => h.terrain === "forest")
                    .length
                }
              </div>
              <div>
                <strong>⛰️ Ore (Mountains):</strong>{" "}
                {
                  boardData.hexagons.filter((h) => h.terrain === "mountains")
                    .length
                }
              </div>
              <div>
                <strong>🌾 Grain (Fields):</strong>{" "}
                {
                  boardData.hexagons.filter((h) => h.terrain === "fields")
                    .length
                }
              </div>
              <div>
                <strong>🐑 Wool (Pasture):</strong>{" "}
                {
                  boardData.hexagons.filter((h) => h.terrain === "pasture")
                    .length
                }
              </div>
              <div>
                <strong>🏜️ Desert:</strong>{" "}
                {
                  boardData.hexagons.filter((h) => h.terrain === "desert")
                    .length
                }
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default App;
