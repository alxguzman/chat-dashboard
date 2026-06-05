# Chat Dashboard
A live multi-platform chat aggregator for Twitch, Kick, and X.

## Stack
- Backend: Python + FastAPI
- Frontend: HTML, CSS, Vanilla JS
- Real-time: WebSockets

## Setup
1. Clone the repo
2. Create a `.env` file with your API keys (see below)
3. Run `pip install -r requirements.txt`
4. Run `uvicorn backend.main:app --reload`

## .env variables needed
TWITCH_TOKEN=
TWITCH_NICK=
X_BEARER_TOKEN=