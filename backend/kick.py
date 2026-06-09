"""
kick.py — Kick chat with emote rendering + curl_cffi Cloudflare bypass.
Also broadcasts the active Kick channel name so the frontend can
pre-populate the stream embed without user input.
"""

import asyncio
import json
import re
import websockets
from curl_cffi.requests import AsyncSession

KICK_CHANNEL_URL = "https://kick.com/api/v2/channels/{channel}"
KICK_WS_URL      = "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679?protocol=7&client=js&version=7.6.0&flash=false"
KICK_EMOTE_CDN   = "https://files.kick.com/emotes/{id}/fullsize"
INLINE_EMOTE_RE  = re.compile(r'\[emote:(\d+):([^\]]+)\]')


def render_emotes(text: str, emotes: list) -> tuple[str, bool]:
    has_emotes = False

    def replace_inline(m):
        nonlocal has_emotes
        has_emotes = True
        eid, ename = m.group(1), m.group(2)
        return f'<img class="emote" src="{KICK_EMOTE_CDN.format(id=eid)}" alt="{ename}" title="{ename}">'

    text = INLINE_EMOTE_RE.sub(replace_inline, text)

    if emotes:
        replacements = []
        for emote in emotes:
            eid   = emote.get("id")
            ename = emote.get("name", "")
            for pos in emote.get("positions", []):
                if ":" in str(pos):
                    start, end = str(pos).split(":")
                    replacements.append((int(start), int(end), eid, ename))
        if replacements:
            has_emotes = True
            replacements.sort(key=lambda x: x[0], reverse=True)
            chars = list(text)
            for start, end, eid, ename in replacements:
                img = f'<img class="emote" src="{KICK_EMOTE_CDN.format(id=eid)}" alt="{ename}" title="{ename}">'
                chars[start:end + 1] = list(img)
            text = "".join(chars)

    return text, has_emotes


async def get_chatroom_id(channel: str) -> int | None:
    url = KICK_CHANNEL_URL.format(channel=channel)
    try:
        async with AsyncSession(impersonate="chrome120") as session:
            r = await session.get(url)
            print(f"[Kick] {url} → HTTP {r.status_code}")
            if r.status_code != 200:
                return None
            data = r.json()
            if "chatroom" in data and "id" in data["chatroom"]:
                cid = data["chatroom"]["id"]
                print(f"[Kick] Chatroom ID {cid} for #{channel}")
                return cid
            if "id" in data:
                return data["id"]
    except Exception as e:
        print(f"[Kick] Error fetching chatroom ID for {channel}: {e}")
    return None


async def connect_kick(channel: str, broadcast_fn):
    channel = channel.lower().strip()

    # Tell the frontend which channel to embed as soon as we start
    await broadcast_fn({
        "type":    "kick_channel",
        "channel": channel,
    })

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
                            raw_text = inner.get("content", "")
                            emotes   = inner.get("emotes", [])
                            text_html, has_emotes = render_emotes(raw_text, emotes)
                            if raw_text:
                                await broadcast_fn({
                                    "platform":   "kick",
                                    "channel":    channel,
                                    "username":   username,
                                    "text":       text_html,
                                    "has_emotes": has_emotes,
                                    "color":      "#53FC18",
                                })
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass

        except Exception as e:
            print(f"[Kick] WebSocket error on #{channel}: {e}. Reconnecting in 10s...")
            await asyncio.sleep(10)