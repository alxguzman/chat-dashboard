"""
kick.py — Kick chat reader using curl_cffi to bypass Cloudflare.

Kick sits behind Cloudflare which blocks httpx/requests based on TLS fingerprint.
curl_cffi impersonates Chrome's TLS signature, bypassing the 403.
"""

import asyncio
import json
import websockets
from curl_cffi.requests import AsyncSession

KICK_CHANNEL_URL = "https://kick.com/api/v2/channels/{channel}"
KICK_WS_URL      = "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679?protocol=7&client=js&version=7.6.0&flash=false"


async def get_chatroom_id(channel: str) -> int | None:
    """Fetch chatroom ID using curl_cffi to impersonate Chrome and bypass Cloudflare."""
    url = KICK_CHANNEL_URL.format(channel=channel)
    try:
        async with AsyncSession(impersonate="chrome120") as session:
            r = await session.get(url)
            print(f"[Kick] {url} → HTTP {r.status_code}")

            if r.status_code != 200:
                print(f"[Kick] Got {r.status_code} for {channel}")
                return None

            data = r.json()

            # Try both response shapes
            if "chatroom" in data and "id" in data["chatroom"]:
                cid = data["chatroom"]["id"]
                print(f"[Kick] Got chatroom ID {cid} for #{channel}")
                return cid

            if "id" in data:
                print(f"[Kick] Got chatroom ID {data['id']} for #{channel}")
                return data["id"]

            print(f"[Kick] Unexpected JSON keys: {list(data.keys())}")
            return None

    except Exception as e:
        print(f"[Kick] Error fetching chatroom ID for {channel}: {e}")
        return None


async def connect_kick(channel: str, broadcast_fn):
    channel = channel.lower().strip()

    while True:
        chatroom_id = await get_chatroom_id(channel)

        if not chatroom_id:
            print(f"[Kick] Retrying {channel} in 60s...")
            await asyncio.sleep(60)
            continue

        try:
            async with websockets.connect(KICK_WS_URL) as ws:
                await ws.send(json.dumps({
                    "event": "pusher:subscribe",
                    "data":  {"auth": "", "channel": f"chatrooms.{chatroom_id}.v2"}
                }))
                print(f"[Kick] Subscribed to #{channel} (chatroom {chatroom_id})")

                async for raw in ws:
                    try:
                        packet = json.loads(raw)

                        if packet.get("event") == "pusher:ping":
                            await ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
                            continue

                        if "ChatMessage" in packet.get("event", ""):
                            inner    = json.loads(packet["data"])
                            sender   = inner.get("sender") or inner.get("user") or {}
                            username = sender.get("username", "unknown")
                            text     = inner.get("content") or inner.get("message", {}).get("content", "")

                            if text:
                                await broadcast_fn({
                                    "platform": "kick",
                                    "channel":  channel,
                                    "username": username,
                                    "text":     text,
                                    "color":    "#53FC18"
                                })

                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass

        except Exception as e:
            print(f"[Kick] WebSocket error on #{channel}: {e}. Reconnecting in 10s...")
            await asyncio.sleep(10)