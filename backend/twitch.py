"""
twitch.py — Anonymous Twitch IRC with IRCv3 tag + emote parsing.

Key fix: send CAP REQ first, wait for CAP ACK, THEN send NICK/JOIN.
This ensures emote tags are enabled before any messages arrive.
"""

import asyncio
import websockets

TWITCH_WS_URL = "wss://irc-ws.chat.twitch.tv:443"
EMOTE_CDN     = "https://static-cdn.jtvnw.net/emoticons/v2/{id}/default/dark/1.0"


def parse_tags(raw_tags: str) -> dict:
    tags = {}
    for part in raw_tags.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            tags[k] = v
    return tags


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

    # Replace right-to-left to preserve indices
    replacements.sort(key=lambda x: x[0], reverse=True)
    chars = list(text)
    for start, end, emote_id in replacements:
        label = text[start:end + 1]
        img   = f'<img class="emote" src="{EMOTE_CDN.format(id=emote_id)}" alt="{label}" title="{label}">'
        chars[start:end + 1] = list(img)
    return "".join(chars)


async def connect_twitch(channel: str, broadcast_fn):
    channel = channel.lower().strip()

    while True:
        try:
            async with websockets.connect(TWITCH_WS_URL) as ws:

                # Step 1: request IRCv3 tags FIRST, before NICK
                await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")

                # Step 2: Wait for CAP ACK before continuing
                cap_acked = False
                async for raw in ws:
                    if "CAP * ACK" in raw:
                        cap_acked = True
                        break
                    if raw.startswith("PING"):
                        await ws.send("PONG :tmi.twitch.tv")

                # Step 3: Authenticate + join
                await ws.send("PASS SCHMOOPIIE")
                await ws.send("NICK justinfan12345")
                await ws.send(f"JOIN #{channel}")
                print(f"[Twitch] Connected to #{channel} (tags: {'✓' if cap_acked else '✗'})")

                # Step 4: Read messages
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

                        tags      = parse_tags(tags_str)
                        username  = tags.get("display-name") or line.split("!")[0].lstrip(":")
                        text      = line.split("PRIVMSG")[1].split(":", 1)[1].strip()
                        emotes_tag = tags.get("emotes", "")
                        text_html  = apply_emotes(text, emotes_tag)

                        await broadcast_fn({
                            "platform":   "twitch",
                            "channel":    channel,
                            "username":   username,
                            "text":       text_html,
                            "has_emotes": bool(emotes_tag),
                            "color":      tags.get("color") or "#9147FF",
                        })

                    except (IndexError, ValueError):
                        pass

        except Exception as e:
            print(f"[Twitch] Error on #{channel}: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)