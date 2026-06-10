"""
chat_sender.py — Sends messages to Twitch IRC using an authenticated connection.

Fix: properly waits for MOTD (376/004) before marking as ready to send,
ensuring the connection is fully established before any PRIVMSG is attempted.
"""

import asyncio
import websockets

TWITCH_WS_URL = "wss://irc-ws.chat.twitch.tv:443"

_senders: dict[str, "TwitchSender"] = {}


class TwitchSender:
    def __init__(self, username: str, token: str):
        self.username  = username.lower()
        self.token     = token
        self._ws       = None
        self._ready    = asyncio.Event()   # set when IRC handshake completes
        self._joined   : set[str] = set()

    async def connect(self):
        """Maintain authenticated IRC connection, set _ready when handshake done."""
        while True:
            self._ready.clear()
            self._ws = None
            try:
                async with websockets.connect(TWITCH_WS_URL) as ws:
                    self._ws = ws
                    await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
                    await ws.send(f"PASS oauth:{self.token}")
                    await ws.send(f"NICK {self.username}")

                    async for raw in ws:
                        # Twitch sends 376 (End of MOTD) when login is complete
                        if "376" in raw or "004" in raw:
                            self._ready.set()
                            print(f"[Sender] ✓ Ready to send as {self.username}")

                        if raw.startswith("PING"):
                            await ws.send("PONG :tmi.twitch.tv")

                        # Auth failure
                        if "Login authentication failed" in raw:
                            print(f"[Sender] ✗ Auth failed for {self.username}. Token may be expired.")
                            self._ready.clear()
                            break

            except Exception as e:
                print(f"[Sender] Connection error for {self.username}: {e}")
            finally:
                self._ready.clear()
                self._ws     = None
                self._joined = set()

            await asyncio.sleep(5)

    async def pre_join(self, channels: list[str]):
        """Pre-join channels after connection is ready. Called during prewarm so the
        first send doesn't stall on the JOIN round-trip."""
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            return
        if not self._ws:
            return
        for ch in channels:
            ch = ch.lower()
            if ch not in self._joined:
                try:
                    await self._ws.send(f"JOIN #{ch}")
                    self._joined.add(ch)
                    await asyncio.sleep(0.1)
                except Exception:
                    pass

    async def send(self, channel: str, text: str) -> bool:
        """Join channel if needed, then send message. Returns True on success."""
        channel = channel.lower()

        try:
            # Wait up to 10s for connection to be ready
            await asyncio.wait_for(self._ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            print(f"[Sender] Timed out waiting for IRC ready state")
            return False

        if not self._ws:
            return False

        try:
            # Join channel first if we haven't
            if channel not in self._joined:
                await self._ws.send(f"JOIN #{channel}")
                self._joined.add(channel)
                await asyncio.sleep(0.3)  # Small delay after join

            await self._ws.send(f"PRIVMSG #{channel} :{text}")
            return True

        except Exception as e:
            print(f"[Sender] Send error: {e}")
            return False


async def get_or_create_sender(session_id: str, username: str, token: str) -> "TwitchSender":
    if session_id not in _senders:
        sender = TwitchSender(username, token)
        _senders[session_id] = sender
        asyncio.create_task(sender.connect())
        # Give connection task a moment to start
        await asyncio.sleep(0.1)
    return _senders[session_id]


def remove_sender(session_id: str):
    _senders.pop(session_id, None)