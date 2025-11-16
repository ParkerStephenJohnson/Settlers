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

// Convert axial coordinates to pixel coordinates
const axialToPixel = (q: number, r: number, size: number) => {
  const x = size * (Math.sqrt(3) * q + (Math.sqrt(3) / 2) * r);
  const y = size * ((3 / 2) * r);
  return { x, y };
};

const createHexagonPath = (size: number) => {
  const points = [];
  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 3) * i - Math.PI / 2;
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
      <polygon points={hexPath} fill={color} stroke="#654321" strokeWidth={size * 0.06} />
      {hex.number && (
        <>
          <circle r={size * 0.35} fill="#F5DEB3" stroke="#654321" strokeWidth={size * 0.06} />
          <text
            textAnchor="middle"
            dy="0.35em"
            fontSize={size * 0.4}
            fontWeight="bold"
            fill={hex.number === 6 || hex.number === 8 ? "#DC143C" : "#000"}
          >
            {hex.number}
          </text>
        </>
      )}
      {hex.has_robber && <circle r={size * 0.25} fill="#333" stroke="#000" strokeWidth={size * 0.06} />}
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
  const [hexSize, setHexSize] = useState(35);

  const boardWidth = 450;
  const boardHeight = 500;

  const fetchBoard = async (randomize: boolean = true) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`http://localhost:8000/api/board/new?randomize=${randomize}`);
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

    const handleResize = () => setHexSize(Math.min(window.innerWidth / 20, 50));
    window.addEventListener("resize", handleResize);
    handleResize();

    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return (
    <div
      style={{
        width: "100vw",
        minHeight: "100vh",
        padding: "1rem",
        boxSizing: "border-box",
        fontFamily: "Arial, sans-serif",
        background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <h1 style={{ color: "white", textAlign: "center", fontSize: "clamp(2rem, 5vw, 3rem)", marginBottom: "1rem" }}>
        Catan Board Simulator
      </h1>

      <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", justifyContent: "center", marginBottom: "1rem" }}>
        <button onClick={() => fetchBoard(true)} style={{ padding: "0.5em 1em", fontSize: "clamp(12px, 1.5vw, 16px)", background: "#4CAF50", color: "white", border: "none", borderRadius: "5px", cursor: "pointer" }}>
          New Random Board
        </button>
        <button onClick={() => fetchBoard(false)} style={{ padding: "0.5em 1em", fontSize: "clamp(12px, 1.5vw, 16px)", background: "#2196F3", color: "white", border: "none", borderRadius: "5px", cursor: "pointer" }}>
          New Fixed Board
        </button>
      </div>

      {loading && <div style={{ color: "white", fontSize: "clamp(14px, 2vw, 18px)" }}>Loading board...</div>}

      {error && (
        <div style={{ color: "#ffcccb", background: "rgba(255,0,0,0.2)", padding: "1rem", borderRadius: "10px", textAlign: "center", fontSize: "clamp(12px, 1.5vw, 16px)" }}>
          Error: {error}
          <br />
          <small>Make sure the backend is running on http://localhost:8000</small>
        </div>
      )}

      {boardData && (
        <div
          style={{
            width: "90vw",
            maxWidth: "1200px",
            height: "80vh",
            background: "#2a2a3e",
            borderRadius: "15px",
            padding: "1rem",
            boxShadow: "0 10px 30px rgba(0,0,0,0.3)",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
          }}
        >
          <svg
            width="100%"
            height="100%"
            viewBox={`-80 -80 ${boardWidth} ${boardHeight}`}
            preserveAspectRatio="xMidYMid meet"
            style={{ display: "block" }}
          >
            {boardData.hexagons.map((hex, idx) => (
              <HexTile key={idx} hex={hex} size={hexSize} />
            ))}
          </svg>
        </div>
      )}
    </div>
  );
};

export default App;
