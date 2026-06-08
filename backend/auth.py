"""
auth.py — Twitch OAuth Authorization Code flow.

SETUP CHECKLIST:
1. Go to dev.twitch.tv/console → your app → Edit
2. Add OAuth Redirect URL: http://localhost:8000/auth/callback
3. Add to your .env:
     TWITCH_CLIENT_ID=your_client_id
     TWITCH_CLIENT_SECRET=your_client_secret
     TWITCH_REDIRECT_URI=http://localhost:8000/auth/callback
"""

import os
import secrets
import httpx
from fastapi import APIRouter
from fastapi.responses import RedirectResponse, HTMLResponse
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID    = os.getenv("TWITCH_CLIENT_ID",    "").strip()
CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "").strip()
REDIRECT_URI  = os.getenv("TWITCH_REDIRECT_URI",  "http://localhost:8000/auth/callback").strip()
SCOPES        = "chat:read chat:edit"

router = APIRouter()

_pending_states: dict[str, bool] = {}
user_sessions:   dict[str, dict] = {}


@router.get("/auth/twitch")
async def login_twitch():
    """Step 1 — redirect browser to Twitch OAuth page."""
    if not CLIENT_ID:
        return HTMLResponse(
            "<h3>TWITCH_CLIENT_ID not set in .env</h3>"
            "<p>Add it and restart the server.</p>",
            status_code=500
        )

    state = secrets.token_urlsafe(16)
    _pending_states[state] = True

    url = (
        "https://id.twitch.tv/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={SCOPES.replace(' ', '+')}"
        f"&state={state}"
        f"&force_verify=false"
    )
    return RedirectResponse(url)


@router.get("/auth/callback")
async def twitch_callback(code: str = "", state: str = "", error: str = ""):
    """Step 2 — Twitch redirects here with auth code."""

    close_script = lambda msg, success, data="{}": HTMLResponse(f"""
        <!DOCTYPE html><html><head>
        <style>body{{font-family:sans-serif;background:#0d0e11;color:#e8eaf0;display:flex;
        align-items:center;justify-content:center;height:100vh;margin:0;flex-direction:column;gap:12px}}</style>
        </head><body>
        <p style="font-size:18px">{"✓ " if success else "✗ "}{msg}</p>
        <p style="color:#555;font-size:13px">This window will close...</p>
        <script>
          window.opener?.postMessage({{type:'{("twitch_auth_success" if success else "twitch_auth_error")}', ...{data}}}, '*');
          setTimeout(() => window.close(), 1500);
        </script>
        </body></html>
    """)

    if error:
        return close_script(f"Login cancelled: {error}", False)

    if state not in _pending_states:
        return close_script("Invalid login state. Please try again.", False)

    del _pending_states[state]

    # Exchange code for token
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post("https://id.twitch.tv/oauth2/token", data={
                "client_id":     CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code":          code,
                "grant_type":    "authorization_code",
                "redirect_uri":  REDIRECT_URI,
            })
        token_data = r.json()
    except Exception as e:
        return close_script(f"Token exchange failed: {e}", False)

    access_token  = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")

    if not access_token:
        return close_script(f"No token returned ({token_data.get('message','unknown error')})", False)

    # Fetch Twitch user info
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get("https://api.twitch.tv/helix/users", headers={
                "Authorization": f"Bearer {access_token}",
                "Client-Id":     CLIENT_ID,
            })
        user = r.json().get("data", [{}])[0]
    except Exception as e:
        return close_script(f"User fetch failed: {e}", False)

    username = user.get("display_name", "")
    user_id  = user.get("id", "")
    avatar   = user.get("profile_image_url", "")

    session_id = secrets.token_urlsafe(24)
    user_sessions[session_id] = {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "username":      username,
        "user_id":       user_id,
        "avatar":        avatar,
    }

    data = f'{{"session_id":"{session_id}","username":"{username}","avatar":"{avatar}"}}'
    return close_script(f"Signed in as {username}", True, data)


def get_session(session_id: str) -> dict | None:
    return user_sessions.get(session_id)