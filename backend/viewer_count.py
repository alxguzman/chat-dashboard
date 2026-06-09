"""
viewer_count.py — Polls real viewer counts from Twitch and Kick.

Twitch: Uses Helix API with App Access Token (free, no user login needed).
        Get Client ID + Secret at dev.twitch.tv → Your Console → Register App.
Kick:   Reuses curl_cffi to read livestream.viewer_count from channel JSON.
"""

import asyncio
import os
import httpx
from curl_cffi.requests import AsyncSession
from dotenv import load_dotenv

load_dotenv()

TWITCH_CLIENT_ID     = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")
KICK_CHANNEL_URL     = "https://kick.com/api/v2/channels/{channel}"

_twitch_token: str | None = None


async def get_twitch_app_token() -> str | None:
    """Fetch a Twitch App Access Token (OAuth client credentials)."""
    global _twitch_token
    if _twitch_token:
        return _twitch_token
    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        return None
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post("https://id.twitch.tv/oauth2/token", params={
                "client_id":     TWITCH_CLIENT_ID,
                "client_secret": TWITCH_CLIENT_SECRET,
                "grant_type":    "client_credentials"
            })
            _twitch_token = r.json()["access_token"]
            return _twitch_token
    except Exception as e:
        print(f"[Viewers] Twitch token error: {e}")
        return None


async def get_twitch_viewers(channels: list[str]) -> int:
    """Sum live viewer counts across all Twitch channels."""
    token = await get_twitch_app_token()
    if not token or not channels:
        return 0
    try:
        logins = "&".join(f"user_login={c.strip()}" for c in channels if c.strip())
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"https://api.twitch.tv/helix/streams?{logins}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Client-Id":     TWITCH_CLIENT_ID
                }
            )
            data = r.json().get("data", [])
            return sum(s.get("viewer_count", 0) for s in data)
    except Exception as e:
        print(f"[Viewers] Twitch fetch error: {e}")
        return 0


async def get_kick_viewers(channels: list[str]) -> int:
    """Sum live viewer counts across all Kick channels using curl_cffi."""
    total = 0
    async with AsyncSession(impersonate="chrome120") as session:
        for ch in channels:
            ch = ch.strip()
            if not ch:
                continue
            try:
                r    = await session.get(KICK_CHANNEL_URL.format(channel=ch))
                data = r.json()
                stream = data.get("livestream") or {}
                total += stream.get("viewer_count", 0)
            except Exception as e:
                print(f"[Viewers] Kick fetch error for {ch}: {e}")
    return total


async def poll_viewer_counts(twitch_channels: list[str], kick_channels: list[str], broadcast_fn, injected_token: str = ""):
    """Polls combined viewer count every 30s and broadcasts to frontend.
    
    Pass injected_token if you already fetched an app token at startup,
    so we don't invalidate it by requesting a second one.
    """
    global _twitch_token
    if injected_token:
        _twitch_token = injected_token  # seed the cache with the already-fetched token
    while True:
        tw = await get_twitch_viewers(twitch_channels)
        kk = await get_kick_viewers(kick_channels)
        total = tw + kk
        if total > 0:
            await broadcast_fn({
                "type":          "viewer_count",
                "total":         total,
                "twitch":        tw,
                "kick":          kk,
            })
            print(f"[Viewers] Twitch: {tw:,}  Kick: {kk:,}  Total: {total:,}")
        await asyncio.sleep(30)