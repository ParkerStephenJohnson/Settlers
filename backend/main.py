from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.board import create_board

app = FastAPI(title="Catan Simulator API")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Catan Simulator API"}

@app.get("/api/board/new")
def get_new_board(randomize: bool = True):
    """Generate a new Catan board"""
    board = create_board(randomize)
    return board.to_dict()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)