"""
main.py — FastAPI backend
Run from project root with: uvicorn backend.main:app --reload
"""

import asyncio
import json
import sys
import os
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

# ── Make sure backend/ is on the path so imports work ─────────
sys.path.insert(0, str(Path(__file__).parent))

from twitch import connect_twitch
from kick   import connect_kick
#from x_feed import poll_x

# ── Connected browser clients ──────────────────────────────────
connected_clients: list[WebSocket] = []


async def broadcast(message: dict):
    data = json.dumps(message)
    dead = []
    for ws in connected_clients:
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connected_clients.remove(ws)


# ── Lifespan: start platform readers on boot ──────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    from dotenv import load_dotenv
    load_dotenv()

    twitch_channels = os.getenv("TWITCH_CHANNELS", "").split(",")
    kick_channels   = os.getenv("KICK_CHANNELS",   "").split(",")
    x_query         = os.getenv("X_SEARCH_QUERY",  "")

    tasks = []

    for ch in twitch_channels:
        ch = ch.strip()
        if ch:
            tasks.append(asyncio.create_task(connect_twitch(ch, broadcast)))

    for ch in kick_channels:
        ch = ch.strip()
        if ch:
            tasks.append(asyncio.create_task(connect_kick(ch, broadcast)))

    # if x_query and os.getenv("X_BEARER_TOKEN", ""):
    #     tasks.append(asyncio.create_task(poll_x(x_query, broadcast)))

    yield

    for t in tasks:
        t.cancel()


app = FastAPI(lifespan=lifespan)

# ── Static files & routes ──────────────────────────────────────
FRONTEND = Path(__file__).parent.parent / "frontend"

app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

@app.get("/")
async def serve_frontend():
    return FileResponse(str(FRONTEND / "index.html"))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)