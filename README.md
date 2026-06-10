# Market Bubble — Live Dashboard

A live streaming dashboard that aggregates Twitch/Kick chat, a crypto price ticker, an embedded stream, and a live X posts feed.

## Stack
- **Backend:** Python + FastAPI + WebSockets
- **Frontend:** HTML, CSS, Vanilla JS (no build step)
- **Real-time:** WebSocket chat bridge + REST polling (CoinGecko, Polymarket, Twitter API)

## Setup

```bash
git clone <repo>
cd chats
pip install -r requirements.txt
cp .env.example .env   # then fill in your keys
cd backend
python generate_cert.py   # creates self-signed SSL cert for localhost HTTPS
python main.py
```

Open `https://localhost:8000` (accept the self-signed cert warning).

## .env variables

| Variable | Required | Description |
|---|---|---|
| `TWITCH_CHANNELS` | Yes | Comma-separated channel names, e.g. `fazebanks` |
| `TWITCH_CLIENT_ID` | Yes | From [dev.twitch.tv](https://dev.twitch.tv/console) |
| `TWITCH_CLIENT_SECRET` | Yes | From Twitch developer console |
| `TWITCH_REDIRECT_URI` | Yes | `https://localhost:8000/auth/callback` |
| `KICK_CHANNELS` | No | Comma-separated Kick channel names, e.g. `ansem` |
| `X_BEARER_TOKEN` | No | Twitter API v2 Bearer Token — enables live X posts feed |
| `X_SEARCH_QUERY` | No | Search query when X key is set, e.g. `crypto OR bitcoin lang:en -is:retweet` |

### Getting an X (Twitter) Bearer Token
1. Go to [developer.twitter.com](https://developer.twitter.com)
2. Create a project + app (free developer account)
3. Under **Keys and Tokens** copy the **Bearer Token**
4. Add it to `.env` as `X_BEARER_TOKEN=...`

> **Note:** Live tweet search (`/2/tweets/search/recent`) requires the **Basic plan** ($100/month).
> Without a key the dashboard runs fine with demo X posts shown instead.

## Features
- **Live Chat** — aggregated Twitch + Kick + X chat with per-platform tabs and streamer filter buttons
- **X Posts** — live trending market posts (demo data shown when no API key)
- **Polymarket** — search prediction markets, click any card to open it on Polymarket
- **Price Chart** — TradingView chart for any crypto or stock ticker
- **Crypto Ticker** — top 30 coins by market cap via CoinGecko, scrolls automatically
- **Light/Dark mode** — toggle in header

## Project structure
```
chats/
├── backend/
│   ├── main.py          # FastAPI app, WebSocket hub
│   ├── twitch.py        # Twitch IRC chat reader
│   ├── kick.py          # Kick chat reader
│   ├── x_feed.py        # Twitter API v2 poller
│   ├── viewer_count.py  # Twitch/Kick viewer count poller
│   ├── auth.py          # Twitch OAuth login
│   ├── chat_sender.py   # Send messages to Twitch chat
│   └── generate_cert.py # Self-signed SSL cert generator
├── frontend/
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   └── images/          # Logos and streamer avatars
└── requirements.txt
```
