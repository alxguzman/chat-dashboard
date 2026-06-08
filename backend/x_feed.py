"""
x_feed.py — X posts via TwitterAPI.io (pay-as-you-go, free credits on signup)
Skips silently if no API key is configured.
"""

import asyncio
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

API_KEY       = os.getenv("TWITTER_API_IO_KEY", "").strip()
SEARCH_URL    = "https://api.twitterapi.io/twitter/tweet/advanced_search"
POLL_INTERVAL = 15


async def poll_x(query: str, broadcast_fn):
    if not API_KEY:
        print("[X] No TWITTER_API_IO_KEY in .env — X feed disabled. Get a free key at twitterapi.io")
        return  # Exit immediately, no error loop

    headers  = {"X-API-Key": API_KEY}
    seen_ids: set[str] = set()
    print(f"[X] Polling TwitterAPI.io for: {query}")

    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(SEARCH_URL, headers=headers, params={
                    "query":     query,
                    "queryType": "Latest",
                })

            if r.status_code == 401:
                print("[X] Invalid API key — check TWITTER_API_IO_KEY in .env")
                await asyncio.sleep(60)
                continue
            if r.status_code == 429:
                print("[X] Rate limited. Waiting 60s...")
                await asyncio.sleep(60)
                continue
            if r.status_code != 200:
                print(f"[X] HTTP {r.status_code}. Retrying in 30s...")
                await asyncio.sleep(30)
                continue

            for tweet in reversed(r.json().get("tweets", [])):
                tid = tweet.get("id") or tweet.get("id_str", "")
                if not tid or tid in seen_ids:
                    continue
                seen_ids.add(tid)

                user     = tweet.get("author") or tweet.get("user") or {}
                username = user.get("userName") or user.get("screen_name", "unknown")
                verified = user.get("isBlueVerified") or user.get("verified", False)
                text     = tweet.get("text") or tweet.get("full_text", "")
                metrics  = tweet.get("public_metrics") or {}

                await broadcast_fn({
                    "type":     "tweet",
                    "platform": "x",
                    "username": username,
                    "text":     text,
                    "verified": verified,
                    "replies":  metrics.get("reply_count", 0),
                    "retweets": metrics.get("retweet_count", 0),
                    "likes":    metrics.get("like_count", 0),
                    "time_ago": "just now",
                })

        except Exception as e:
            print(f"[X] Error: {e}. Retrying in 15s...")

        await asyncio.sleep(POLL_INTERVAL)