"""
twitch.py — Anonymous Twitch IRC with IRCv3 tag + emote + badge parsing.
"""

import asyncio
import websockets

TWITCH_WS_URL = "wss://irc-ws.chat.twitch.tv:443"
EMOTE_CDN     = "https://static-cdn.jtvnw.net/emoticons/v2/{id}/default/dark/1.0"

# Global badge image URL cache keyed by "set_id/version"
# Populated lazily – we don't fetch if CLIENT_ID isn't set.
_badge_cache: dict[str, str] = {}

# Well-known fallback badge images for common badge types
# (used when we can't fetch from API)
BADGE_DISPLAY: dict[str, dict] = {
    "broadcaster": {"title": "Broadcaster",  "emoji": "🔴"},
    "moderator":   {"title": "Moderator",    "emoji": "🗡"},
    "vip":         {"title": "VIP",          "emoji": "💎"},
    "subscriber":  {"title": "Subscriber",   "emoji": "⭐"},
    "founder":     {"title": "Founder",      "emoji": "🏅"},
    "partner":     {"title": "Partner",      "emoji": "✓"},
    "staff":       {"title": "Staff",        "emoji": "🔧"},
    "premium":     {"title": "Prime",        "emoji": "👑"},
    "bits":        {"title": "Bits",         "emoji": "💎"},
    "turbo":       {"title": "Turbo",        "emoji": "⚡"},
    "sub-gifter":  {"title": "Sub Gifter",   "emoji": "🎁"},
    "hype-train":  {"title": "Hype Train",   "emoji": "🚂"},
    "predictions": {"title": "Prediction",   "emoji": "🔮"},
    "moments":     {"title": "Moments",      "emoji": "📸"},
    "artist-badge":{"title": "Artist",       "emoji": "🎨"},
    "no_audio":    {"title": "No Audio",     "emoji": "🔇"},
    "no_video":    {"title": "No Video",     "emoji": "📵"},
}


def parse_tags(raw_tags: str) -> dict:
    tags = {}
    for part in raw_tags.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            tags[k] = v
    return tags


def parse_badges(badges_tag: str) -> list[dict]:
    """
    badges_tag looks like: "broadcaster/1,subscriber/12,bits/1000"
    Returns a list of badge dicts with set_id, version, title, and img_url (if cached).
    """
    if not badges_tag:
        return []
    badges = []
    for entry in badges_tag.split(","):
        if "/" not in entry:
            continue
        set_id, version = entry.split("/", 1)
        cache_key = f"{set_id}/{version}"
        info = BADGE_DISPLAY.get(set_id, {"title": set_id.replace("-", " ").title(), "emoji": "🏷"})
        badge = {
            "set_id":  set_id,
            "version": version,
            "title":   info["title"],
            "emoji":   info.get("emoji", "🏷"),
        }
        # If we have a CDN URL from the Helix API, include it
        if cache_key in _badge_cache:
            badge["img_url"] = _badge_cache[cache_key]
        badges.append(badge)
    return badges


def apply_emotes(text: str, emotes_tag: str) -> str:
    """Replace emote positions with <img> tags using Twitch CDN."""
    if not emotes_tag:
        return text

    replacements = []
    for entry in emotes_tag.split("/"):
        if ":" not in entry:
            continue
        emote_id, positions_str = entry.split(":", 1)
        for pos in positions_str.split(","):
            if "-" in pos:
                try:
                    start, end = pos.split("-")
                    replacements.append((int(start), int(end), emote_id))
                except ValueError:
                    pass

    if not replacements:
        return text

    replacements.sort(key=lambda x: x[0], reverse=True)
    chars = list(text)
    for start, end, emote_id in replacements:
        label = text[start:end + 1]
        img   = f'<img class="emote" src="{EMOTE_CDN.format(id=emote_id)}" alt="{label}" title="{label}">'
        chars[start:end + 1] = list(img)
    return "".join(chars)


async def fetch_global_badges(client_id: str, app_token: str):
    """Fetch Twitch global badge image URLs and populate _badge_cache."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.twitch.tv/helix/chat/badges/global",
                headers={"Authorization": f"Bearer {app_token}", "Client-Id": client_id}
            )
            for badge_set in r.json().get("data", []):
                set_id = badge_set["set_id"]
                for v in badge_set.get("versions", []):
                    key = f"{set_id}/{v['id']}"
                    _badge_cache[key] = v.get("image_url_1x", "")
        print(f"[Twitch] Loaded {len(_badge_cache)} badge images")
    except Exception as e:
        print(f"[Twitch] Could not fetch badge images: {e}")


async def connect_twitch(channel: str, broadcast_fn, client_id: str = "", app_token: str = ""):
    channel = channel.lower().strip()

    # Try to pre-load badge CDN URLs once
    if client_id and app_token and not _badge_cache:
        await fetch_global_badges(client_id, app_token)

    while True:
        try:
            async with websockets.connect(TWITCH_WS_URL) as ws:

                await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")

                cap_acked = False
                async for raw in ws:
                    if "CAP * ACK" in raw:
                        cap_acked = True
                        break
                    if raw.startswith("PING"):
                        await ws.send("PONG :tmi.twitch.tv")

                await ws.send("PASS SCHMOOPIIE")
                await ws.send("NICK justinfan12345")
                await ws.send(f"JOIN #{channel}")
                print(f"[Twitch] Connected to #{channel} (tags: {'✓' if cap_acked else '✗'})")

                async for raw in ws:
                    if raw.startswith("PING"):
                        await ws.send("PONG :tmi.twitch.tv")
                        continue

                    if "PRIVMSG" not in raw:
                        continue

                    try:
                        tags_str = ""
                        line     = raw

                        if raw.startswith("@"):
                            tags_str, line = raw[1:].split(" ", 1)

                        tags       = parse_tags(tags_str)
                        username   = tags.get("display-name") or line.split("!")[0].lstrip(":")
                        text       = line.split("PRIVMSG")[1].split(":", 1)[1].strip()
                        emotes_tag = tags.get("emotes", "")
                        text_html  = apply_emotes(text, emotes_tag)
                        badges     = parse_badges(tags.get("badges", ""))

                        await broadcast_fn({
                            "platform":   "twitch",
                            "channel":    channel,
                            "username":   username,
                            "text":       text_html,
                            "has_emotes": bool(emotes_tag),
                            "color":      tags.get("color") or "#9147FF",
                            "badges":     badges,
                        })

                    except (IndexError, ValueError):
                        pass

        except Exception as e:
            print(f"[Twitch] Error on #{channel}: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)