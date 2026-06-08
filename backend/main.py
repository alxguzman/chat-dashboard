import asyncio
import json
import sys
import os
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

sys.path.insert(0, str(Path(__file__).parent))

from twitch        import connect_twitch
from kick          import connect_kick
from x_feed        import poll_x
from viewer_count  import poll_viewer_counts
from auth          import router as auth_router, get_session
from chat_sender   import get_or_create_sender, remove_sender

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    from dotenv import load_dotenv
    load_dotenv()

    twitch_channels = [c.strip() for c in os.getenv("TWITCH_CHANNELS", "").split(",") if c.strip()]
    kick_channels   = [c.strip() for c in os.getenv("KICK_CHANNELS",   "").split(",") if c.strip()]
    x_query         = os.getenv("X_SEARCH_QUERY", "")

    tasks = []

    for ch in twitch_channels:
        tasks.append(asyncio.create_task(connect_twitch(ch, broadcast)))
    for ch in kick_channels:
        tasks.append(asyncio.create_task(connect_kick(ch, broadcast)))
    if x_query:
        tasks.append(asyncio.create_task(poll_x(x_query, broadcast)))
    if twitch_channels or kick_channels:
        tasks.append(asyncio.create_task(
            poll_viewer_counts(twitch_channels, kick_channels, broadcast)
        ))

    yield

    for t in tasks:
        t.cancel()


app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)

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
            raw = await websocket.receive_text()

            # Handle messages FROM the browser
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            # ── Send chat message to Twitch ──────────────────
            if msg.get("type") == "send_chat":
                session_id = msg.get("session_id", "")
                channel    = msg.get("channel", "")
                text       = msg.get("text", "").strip()

                if not session_id or not channel or not text:
                    continue

                session = get_session(session_id)
                if not session:
                    await websocket.send_text(json.dumps({
                        "type":  "chat_error",
                        "error": "Not logged in. Please sign in with Twitch."
                    }))
                    continue

                sender = await get_or_create_sender(
                    session_id,
                    session["username"],
                    session["access_token"]
                )
                await sender.join(channel)
                ok = await sender.send(channel, text)

                if ok:
                    # Echo the message back so it appears in the feed immediately
                    await broadcast({
                        "platform":   "twitch",
                        "channel":    channel,
                        "username":   session["username"],
                        "text":       text,
                        "has_emotes": False,
                        "color":      "#FFD700",
                        "self_sent":  True,
                    })
                else:
                    await websocket.send_text(json.dumps({
                        "type":  "chat_error",
                        "error": "Failed to send message. Try reconnecting."
                    }))

            # ── Logout ───────────────────────────────────────
            elif msg.get("type") == "logout":
                remove_sender(msg.get("session_id", ""))

    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)