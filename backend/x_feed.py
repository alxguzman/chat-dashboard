"""
x_feed.py — Polls X v2 API and forwards tweets to the browser.
Tweets are emitted with type="tweet" so the frontend renders them
in the left panel instead of the chat feed.
"""

import asyncio
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")
X_SEARCH_URL   = "https://api.twitter.com/2/tweets/search/recent"
POLL_INTERVAL  = 15


async def poll_x(query: str, broadcast_fn):
    headers  = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}
    seen_ids : set[str] = set()
    since_id : str | None = None

    print(f"[X] Polling for: {query}")

    while True:
        try:
            params = {
                "query":        query,
                "max_results":  10,
                "tweet.fields": "author_id,created_at,text,public_metrics",
                "expansions":   "author_id",
                "user.fields":  "username,verified"
            }
            if since_id:
                params["since_id"] = since_id

            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(X_SEARCH_URL, headers=headers, params=params)

            if r.status_code == 401:
                print("[X] Invalid Bearer Token. Check your .env file.")
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

            data   = r.json()
            tweets = data.get("data", [])
            users  = {u["id"]: u for u in data.get("includes", {}).get("users", [])}

            for tweet in reversed(tweets):
                tid = tweet["id"]
                if tid in seen_ids:
                    continue
                seen_ids.add(tid)
                since_id = tid

                user     = users.get(tweet["author_id"], {})
                username = user.get("username", "unknown")
                verified = user.get("verified", False)
                metrics  = tweet.get("public_metrics", {})

                await broadcast_fn({
                    "type":      "tweet",        # ← tells frontend to show in left panel
                    "platform":  "x",
                    "username":  username,
                    "text":      tweet["text"],
                    "verified":  verified,
                    "replies":   metrics.get("reply_count", 0),
                    "retweets":  metrics.get("retweet_count", 0),
                    "likes":     metrics.get("like_count", 0),
                    "time_ago":  "just now",
                    "color":     "#ffffff"
                })

        except Exception as e:
            print(f"[X] Error: {e}. Retrying in 15s...")

        await asyncio.sleep(POLL_INTERVAL)