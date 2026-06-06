"""
twitch.py — Anonymous Twitch IRC connection (NO token required)

Twitch allows anonymous read-only connections using the username
"justinfan" followed by any random number. No OAuth token needed.
"""

import asyncio
import websockets


TWITCH_WS_URL = "wss://irc-ws.chat.twitch.tv:443"


async def connect_twitch(channel: str, broadcast_fn):
    channel = channel.lower().strip()

    while True:
        try:
            async with websockets.connect(TWITCH_WS_URL) as ws:
                # Anonymous login — justinfan#### requires NO token
                await ws.send("PASS SCHMOOPIIE")
                await ws.send("NICK justinfan12345")
                await ws.send(f"JOIN #{channel}")

                print(f"[Twitch] Anonymous connection to #{channel}")

                async for raw in ws:
                    if raw.startswith("PING"):
                        await ws.send("PONG :tmi.twitch.tv")
                        continue

                    if "PRIVMSG" in raw:
                        try:
                            username = raw.split("!")[0].lstrip(":")
                            text     = raw.split("PRIVMSG")[1].split(":", 1)[1].strip()
                            await broadcast_fn({
                                "platform": "twitch",
                                "channel":  channel,
                                "username": username,
                                "text":     text,
                                "color":    "#9147FF"
                            })
                        except (IndexError, ValueError):
                            pass

        except Exception as e:
            print(f"[Twitch] Error on #{channel}: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)