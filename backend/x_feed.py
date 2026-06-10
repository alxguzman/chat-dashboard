"""
x_feed.py — Live X posts via the official Twitter API v2.
Polls /2/tweets/search/recent every 15 s and broadcasts each new tweet to the
X Posts panel.  Exits cleanly when no X_BEARER_TOKEN is set in .env so the
rest of the app keeps running on demo data.

Required .env variable:
  X_BEARER_TOKEN   — from developer.twitter.com → your app → "Keys and Tokens"
  X_SEARCH_QUERY   — e.g.  crypto OR bitcoin OR $BTC lang:en -is:retweet
"""

import asyncio
import datetime
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

BEARER_TOKEN  = os.getenv("X_BEARER_TOKEN", "").strip()
SEARCH_URL    = "https://api.twitter.com/2/tweets/search/recent"
POLL_INTERVAL = 15  # seconds — safe for Basic tier (1 req/15 s)


def _time_ago(iso: str) -> str:
    try:
        dt   = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        diff = int((datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds())
        if diff < 60:    return f"{diff}s"
        if diff < 3600:  return f"{diff // 60}m"
        if diff < 86400: return f"{diff // 3600}h"
        return f"{diff // 86400}d"
    except Exception:
        return "now"


async def poll_x(query: str, broadcast_fn):
    if not BEARER_TOKEN:
        print("[X] No X_BEARER_TOKEN in .env — X feed disabled.")
        print("[X]   Get one at: https://developer.twitter.com → your app → 'Keys and Tokens'")
        print("[X]   Requires Basic plan ($100/mo) or higher for search access.")
        return  # exits cleanly; demo data in frontend still shows

    headers  = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    since_id = None  # tracks the newest tweet ID seen so far
    print(f"[X] Polling Twitter API v2 for: {query}")

    while True:
        try:
            params = {
                "query":       query,
                "max_results": 10,
                "tweet.fields": "created_at,public_metrics,author_id",
                "expansions":   "author_id",
                "user.fields":  "username,verified,name",
            }
            if since_id:
                params["since_id"] = since_id

            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(SEARCH_URL, headers=headers, params=params)

            if r.status_code == 401:
                print("[X] 401 Unauthorized — check X_BEARER_TOKEN in .env")
                await asyncio.sleep(60)
                continue
            if r.status_code == 403:
                print("[X] 403 Forbidden — your Twitter developer plan may not include search.")
                print("[X]   Basic plan ($100/mo) required for /2/tweets/search/recent")
                await asyncio.sleep(300)
                continue
            if r.status_code == 429:
                reset = int(r.headers.get("x-rate-limit-reset", 0))
                wait  = max(15, reset - int(datetime.datetime.now(datetime.timezone.utc).timestamp()) + 2)
                print(f"[X] Rate limited. Waiting {wait}s...")
                await asyncio.sleep(wait)
                continue
            if r.status_code != 200:
                print(f"[X] HTTP {r.status_code}. Retrying in 30s...")
                await asyncio.sleep(30)
                continue

            body = r.json()

            # Build author_id → user dict from includes
            users = {u["id"]: u for u in body.get("includes", {}).get("users", [])}

            tweets = body.get("data") or []
            if tweets:
                since_id = tweets[0]["id"]  # newest is first in the list

            for tweet in reversed(tweets):  # oldest first so feed reads chronologically
                user     = users.get(tweet.get("author_id", ""), {})
                username = user.get("username", "unknown")
                verified = user.get("verified", False)
                text     = tweet.get("text", "")
                metrics  = tweet.get("public_metrics", {})
                ta       = _time_ago(tweet.get("created_at", ""))

                await broadcast_fn({
                    "type":     "tweet",
                    "platform": "x",
                    "username": username,
                    "text":     text,
                    "verified": verified,
                    "replies":  metrics.get("reply_count",   0),
                    "retweets": metrics.get("retweet_count", 0),
                    "likes":    metrics.get("like_count",    0),
                    "time_ago": ta,
                })

        except Exception as e:
            print(f"[X] Error: {e}. Retrying in 15s...")

        await asyncio.sleep(POLL_INTERVAL)
