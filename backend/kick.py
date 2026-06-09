"""
kick.py — Kick chat with emote rendering + curl_cffi Cloudflare bypass.
Sends kick_channel to frontend for reference; stream embed now uses Twitch.
Kick badges: sub / mod / founder parsed from sender.identity.
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

# Kick badge metadata
KICK_BADGE_MAP = {
    "broadcaster": {"title": "Broadcaster", "emoji": "🔴"},
    "moderator":   {"title": "Moderator",   "emoji": "🗡"},
    "subscriber":  {"title": "Subscriber",  "emoji": "⭐"},
    "og":          {"title": "OG",          "emoji": "👑"},
    "vip":         {"title": "VIP",         "emoji": "💎"},
    "founder":     {"title": "Founder",     "emoji": "🏅"},
    "verified":    {"title": "Verified",    "emoji": "✓"},
    "staff":       {"title": "Staff",       "emoji": "🔧"},
    "gifter":      {"title": "Gifter",      "emoji": "🎁"},
}


def parse_kick_badges(sender: dict) -> list[dict]:
    """Extract badges from Kick sender object."""
    badges = []
    identity = sender.get("identity", {}) or {}

    # badges field is a list of {type, text, count} objects
    for b in (identity.get("badges") or []):
        badge_type = b.get("type", "")
        meta = KICK_BADGE_MAP.get(badge_type, {
            "title": badge_type.replace("_", " ").title(),
            "emoji": "🏷",
        })
        badges.append({
            "set_id":  badge_type,
            "version": str(b.get("count", "")),
            "title":   meta["title"],
            "emoji":   meta["emoji"],
        })

    return badges


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

    # Tell the frontend which Kick channel we're monitoring (for reference)
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
                            badges   = parse_kick_badges(sender)

                            # Use identity color if available, fallback to Kick green
                            identity = sender.get("identity", {}) or {}
                            color    = identity.get("color") or "#53FC18"

                            if raw_text:
                                await broadcast_fn({
                                    "platform":   "kick",
                                    "channel":    channel,
                                    "username":   username,
                                    "text":       text_html,
                                    "has_emotes": has_emotes,
                                    "color":      color,
                                    "badges":     badges,
                                })
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass

        except Exception as e:
            print(f"[Kick] WebSocket error on #{channel}: {e}. Reconnecting in 10s...")
            await asyncio.sleep(10)