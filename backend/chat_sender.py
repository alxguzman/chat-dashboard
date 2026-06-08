"""
chat_sender.py — Sends messages to Twitch chat using an authenticated IRC connection.

One authenticated sender is kept alive per logged-in user session.
When the frontend sends { type: "send_chat", channel, text, session_id }
over WebSocket, this module picks it up and writes it to Twitch IRC.
"""

import asyncio
import websockets

TWITCH_WS_URL = "wss://irc-ws.chat.twitch.tv:443"

# Active sender connections: session_id → TwitchSender instance
_senders: dict[str, "TwitchSender"] = {}


class TwitchSender:
    def __init__(self, username: str, token: str):
        self.username = username
        self.token    = token
        self._ws      = None
        self._lock    = asyncio.Lock()
        self._task    = None

    async def connect(self):
        """Open and maintain an authenticated IRC connection."""
        while True:
            try:
                async with websockets.connect(TWITCH_WS_URL) as ws:
                    self._ws = ws
                    await ws.send(f"PASS oauth:{self.token}")
                    await ws.send(f"NICK {self.username.lower()}")
                    print(f"[Sender] Authenticated IRC connection for {self.username}")

                    async for raw in ws:
                        if raw.startswith("PING"):
                            await ws.send("PONG :tmi.twitch.tv")

            except Exception as e:
                print(f"[Sender] IRC error for {self.username}: {e}. Reconnecting in 5s...")
                self._ws = None
                await asyncio.sleep(5)

    async def join(self, channel: str):
        """Join a channel so we can send messages to it."""
        if self._ws:
            await self._ws.send(f"JOIN #{channel.lower()}")

    async def send(self, channel: str, text: str) -> bool:
        """Send a chat message. Returns True on success."""
        if not self._ws:
            return False
        try:
            await self._ws.send(f"PRIVMSG #{channel.lower()} :{text}")
            return True
        except Exception as e:
            print(f"[Sender] Send error: {e}")
            return False


async def get_or_create_sender(session_id: str, username: str, token: str) -> TwitchSender:
    """Return existing sender or create a new one for this session."""
    if session_id not in _senders:
        sender = TwitchSender(username, token)
        _senders[session_id] = sender
        # Start connection loop as background task
        asyncio.create_task(sender.connect())
        await asyncio.sleep(1)  # Give it a moment to connect
    return _senders[session_id]


def remove_sender(session_id: str):
    """Clean up sender when user logs out."""
    if session_id in _senders:
        del _senders[session_id]