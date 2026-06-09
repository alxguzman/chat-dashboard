/**
 * app.js — Market Bubble Dashboard
 *
 * Platform icons (Twitch/Kick badges next to usernames):
 *   To change them, find PLATFORM_ICONS below and swap the SVG markup,
 *   or change the CSS classes .platform-icon.twitch / .platform-icon.kick
 *   in style.css to use a background-image instead of an inline SVG.
 */

const WS_URL         = `ws${location.protocol === 'https:' ? 's' : ''}://${location.host}/ws`;
const COINGECKO_URL  = 'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana,binancecoin,ripple,dogecoin&vs_currencies=usd&include_24hr_change=true';
const TICKER_REFRESH = 60_000;
const MAX_CHAT_MSGS  = 300;
const MAX_TWEETS     = 20;

const COINS = [
  { id: 'bitcoin',      sym: 'BTC',  color: '#F7931A', initial: 'B' },
  { id: 'ethereum',     sym: 'ETH',  color: '#627EEA', initial: 'E' },
  { id: 'solana',       sym: 'SOL',  color: '#9945FF', initial: 'S' },
  { id: 'binancecoin',  sym: 'BNB',  color: '#F3BA2F', initial: 'B' },
  { id: 'ripple',       sym: 'XRP',  color: '#00AAE4', initial: 'X' },
  { id: 'dogecoin',     sym: 'DOGE', color: '#C2A633', initial: 'D' },
];

// ── State ─────────────────────────────────────────────────────
let activeTab   = 'all';
let streamStart = Date.now();
let ws          = null;
let sessionId   = localStorage.getItem('twitch_session') || null;
let twitchUser  = JSON.parse(localStorage.getItem('twitch_user') || 'null');

// Known twitch channels (populated from incoming chat messages)
const twitchChannels = new Set();

// ── DOM ───────────────────────────────────────────────────────
const tickerTrack    = document.getElementById('ticker-track');
const chatFeed       = document.getElementById('chat-feed');
const tweetsFeed     = document.getElementById('tweets-feed');
const wsDot          = document.getElementById('ws-status');
const viewerNum      = document.getElementById('viewer-num');
const viewerCount    = document.getElementById('viewer-count');
const streamTimer    = document.getElementById('stream-timer');
const loginPrompt    = document.getElementById('login-prompt');
const loggedInBar    = document.getElementById('logged-in-bar');
const twitchLoginBtn = document.getElementById('twitch-login-btn');
const logoutBtn      = document.getElementById('logout-btn');
const userAvatar     = document.getElementById('user-avatar');
const userName       = document.getElementById('user-name');
const chatInput      = document.getElementById('chat-input');
const sendBtn        = document.getElementById('send-btn');
const channelSelect  = document.getElementById('chat-channel-select');
const errorToast     = document.getElementById('error-toast');
const kickPlayer     = document.getElementById('kick-player');
const streamLoading  = document.getElementById('stream-loading');
const loadingText    = document.getElementById('loading-text');
const streamChip     = document.getElementById('stream-channel-chip');

// ── Kick stream embed ─────────────────────────────────────────
// The backend sends a "kick_channel" message on startup with the
// channel name from KICK_CHANNELS in .env. No user input needed.
function loadKickStream(channel) {
  channel = channel.trim().toLowerCase();
  if (!channel) return;

  console.log(`[Stream] Embedding Kick channel: ${channel}`);
  streamChip.textContent = channel;

  // Must be HTTPS for Kick embed to load
  if (location.protocol !== 'https:') {
    loadingText.textContent = `⚠ HTTPS required for Kick embed. Run generate_cert.py then open https://localhost:8000`;
    return;
  }

  kickPlayer.src = `https://player.kick.com/${channel}?autoplay=true`;
  kickPlayer.style.display = 'block';
  streamLoading.style.display = 'none';
}

document.getElementById('fullscreen-btn').addEventListener('click', () => {
  if (kickPlayer.requestFullscreen) kickPlayer.requestFullscreen();
});

// ── Crypto ticker ─────────────────────────────────────────────
async function fetchTicker() {
  try {
    const r = await fetch(COINGECKO_URL);
    if (!r.ok) return;
    renderTicker(await r.json());
  } catch {}
}

function renderTicker(data) {
  const items = COINS.map(coin => {
    const d = data[coin.id];
    if (!d) return '';
    const price  = d.usd;
    const change = d.usd_24h_change ?? 0;
    const up     = change >= 0;
    const fmt    = price >= 1000
      ? '$' + price.toLocaleString('en-US', { maximumFractionDigits: 2 })
      : '$' + price.toLocaleString('en-US', { maximumFractionDigits: 4 });
    return `<div class="ticker-item">
      <div class="ticker-icon" style="background:${coin.color}22;color:${coin.color}">${coin.initial}</div>
      <span class="ticker-symbol">${coin.sym}</span>
      <span class="ticker-price">${fmt}</span>
      <span class="ticker-change ${up?'up':'down'}">${up?'+':''}${change.toFixed(2)}% ${up?'▲':'▼'}</span>
    </div>`;
  }).join('');
  tickerTrack.innerHTML = items + items;
}

fetchTicker();
setInterval(fetchTicker, TICKER_REFRESH);

// ── WebSocket ─────────────────────────────────────────────────
function connectWS() {
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    wsDot.className = 'ws-dot connected';
    wsDot.title = 'Connected';
  };

  ws.onmessage = ({ data }) => {
    try {
      const msg = JSON.parse(data);
      if      (msg.type === 'kick_channel')  loadKickStream(msg.channel);
      else if (msg.type === 'tweet')         addTweet(msg);
      else if (msg.type === 'viewer_count')  updateViewers(msg);
      else if (msg.type === 'chat_error')    showToast(msg.error, 'error');
      else                                   addChatMsg(msg);
    } catch {}
  };

  ws.onclose = () => {
    wsDot.className = 'ws-dot disconnected';
    setTimeout(connectWS, 3000);
  };

  ws.onerror = () => { wsDot.className = 'ws-dot error'; };
}

connectWS();

// ── Viewer count ──────────────────────────────────────────────
function updateViewers({ total, twitch, kick }) {
  viewerNum.textContent = total.toLocaleString();
  viewerCount.title = `Twitch: ${twitch.toLocaleString()}  |  Kick: ${kick.toLocaleString()}`;
}

// ── Platform icons ────────────────────────────────────────────
// ✏️ TO CHANGE ICONS: edit the SVG strings here, or replace with
//    <img src="/static/your-icon.png"> tags instead of SVG.
//    The icons appear as small badges left of each chat message.
const PLATFORM_ICONS = {
  twitch: `<svg viewBox="0 0 24 24" fill="currentColor">
    <path d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"/>
  </svg>`,
  
  kick: `<svg viewBox="0 0 24 24" fill="currentColor">
    <text y="16" x="3" font-size="14" font-weight="900" font-family="Arial,sans-serif">K</text>
  </svg>`,
  x: `<svg viewBox="0 0 24 24" fill="currentColor">
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.744l7.737-8.858L1.254 2.25H8.08l4.253 5.622zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
  </svg>`,
};

// ── Chat messages ─────────────────────────────────────────────
function addChatMsg({ platform, channel, username, text, has_emotes, color, self_sent }) {
  // Auto-populate the Twitch channel send dropdown
  if (platform === 'twitch' && channel && !twitchChannels.has(channel)) {
    twitchChannels.add(channel);
    const opt = document.createElement('option');
    opt.value = channel;
    opt.textContent = '#' + channel;
    channelSelect.appendChild(opt);
    if (twitchChannels.size === 1) {
      channelSelect.value = channel;
    }
  }

  const li = document.createElement('li');
  li.className = `chat-msg ${platform}${self_sent ? ' self-sent' : ''}`;
  if (activeTab !== 'all' && activeTab !== platform) li.classList.add('hidden');

  const rendered = has_emotes ? text : esc(text);

  li.innerHTML = `
    <div class="platform-icon ${platform}">${PLATFORM_ICONS[platform] || ''}</div>
    <div class="chat-body">
      <span class="chat-username" style="color:${color||''}">${esc(username)}</span><span class="chat-text">${rendered}</span>
    </div>`;

  chatFeed.prepend(li);
  while (chatFeed.children.length > MAX_CHAT_MSGS) chatFeed.removeChild(chatFeed.lastChild);
}

// ── Tab filters ───────────────────────────────────────────────
document.querySelectorAll('.chat-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    activeTab = btn.dataset.platform;
    document.querySelectorAll('.chat-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.chat-msg').forEach(m => {
      m.classList.toggle('hidden', activeTab !== 'all' && !m.classList.contains(activeTab));
    });
  });
});

// ── Twitch Auth ───────────────────────────────────────────────
function updateAuthUI() {
  if (twitchUser && sessionId) {
    loginPrompt.classList.add('hidden');
    loggedInBar.classList.remove('hidden');
    userAvatar.src = twitchUser.avatar || '';
    userName.textContent = twitchUser.username;
    chatInput.disabled = false;
    chatInput.placeholder = 'Send a message…';
    sendBtn.disabled = false;
    channelSelect.disabled = twitchChannels.size === 0;
  } else {
    loginPrompt.classList.remove('hidden');
    loggedInBar.classList.add('hidden');
    chatInput.disabled = true;
    chatInput.placeholder = 'Sign in to chat…';
    sendBtn.disabled = true;
    channelSelect.disabled = true;
  }
}

twitchLoginBtn.addEventListener('click', () => {
  const w = 550, h = 700;
  const left = window.screenX + (window.outerWidth  - w) / 2;
  const top  = window.screenY + (window.outerHeight - h) / 2;
  window.open('/auth/twitch', 'TwitchLogin',
    `width=${w},height=${h},left=${left},top=${top},toolbar=no,menubar=no,scrollbars=no`);
});

window.addEventListener('message', (e) => {
  if (e.data?.type === 'twitch_auth_success') {
    sessionId  = e.data.session_id;
    twitchUser = { username: e.data.username, avatar: e.data.avatar };
    localStorage.setItem('twitch_session', sessionId);
    localStorage.setItem('twitch_user', JSON.stringify(twitchUser));
    updateAuthUI();
    showToast(`✓ Signed in as ${twitchUser.username}`, 'success');
  }
  if (e.data?.type === 'twitch_auth_error') {
    showToast('Twitch login failed: ' + e.data.error, 'error');
  }
});

logoutBtn.addEventListener('click', () => {
  if (ws && sessionId) ws.send(JSON.stringify({ type: 'logout', session_id: sessionId }));
  sessionId = null; twitchUser = null;
  localStorage.removeItem('twitch_session');
  localStorage.removeItem('twitch_user');
  updateAuthUI();
});

// ── Send chat ─────────────────────────────────────────────────
function sendMessage() {
  const text    = chatInput.value.trim();
  const channel = channelSelect.value;
  if (!text || !channel || !sessionId) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    showToast('Not connected — please wait', 'error');
    return;
  }
  ws.send(JSON.stringify({ type: 'send_chat', session_id: sessionId, channel, text }));
  chatInput.value = '';
  sendBtn.textContent = 'Chat';
  chatInput.focus();
}

sendBtn.addEventListener('click', sendMessage);
chatInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
chatInput.addEventListener('input', () => {
  const left = 500 - chatInput.value.length;
  sendBtn.textContent = left < 50 ? `Chat (${left})` : 'Chat';
  sendBtn.style.color = left < 20 ? 'var(--danger)' : '';
});

// ── Tweets ────────────────────────────────────────────────────
function addTweet({ username, text, verified, replies, retweets, likes, time_ago }) {
  const card = document.createElement('div');
  card.className = 'tweet-card';
  const formatted = esc(text)
    .replace(/(\$[A-Z]{2,6})/g, '<span class="cashtag">$1</span>')
    .replace(/(#\w+)/g, '<span class="hashtag">$1</span>');
  card.innerHTML = `
    <div class="tweet-header">
      <div class="tweet-avatar">${esc(username).slice(0,2).toUpperCase()}</div>
      <div class="tweet-meta">
        <div class="tweet-handle">@${esc(username)}${verified?' <span class="verified-badge">✓</span>':''}</div>
        <div class="tweet-time">${esc(time_ago||'now')}</div>
      </div>
    </div>
    <div class="tweet-text">${formatted}</div>
    <div class="tweet-actions">
      <span class="tweet-action">💬 ${replies||0}</span>
      <span class="tweet-action">🔁 ${retweets||0}</span>
      <span class="tweet-action">♡ ${likes||0}</span>
    </div>`;
  tweetsFeed.prepend(card);
  while (tweetsFeed.children.length > MAX_TWEETS) tweetsFeed.removeChild(tweetsFeed.lastChild);
}

[
  { username:'CryptoKaleo',  text:'Bitcoin holding strong above $67K. Next leg up? 👀', verified:true,  replies:12, retweets:26, likes:231, time_ago:'2m' },
  { username:'WatcherGuru',  text:"JUST IN: BlackRock's #Bitcoin ETF $IBIT sees $378M in inflows.", verified:true, replies:18, retweets:47, likes:327, time_ago:'4m' },
  { username:'MacroScope17', text:'The liquidity cycle is turning. Altseason signals flashing.', verified:false, replies:7, retweets:15, likes:112, time_ago:'6m' },
  { username:'Defi_Mochi',   text:'Solana ecosystem momentum is insane right now. $SOL', verified:false, replies:9, retweets:22, likes:198, time_ago:'8m' },
].reverse().forEach(t => addTweet(t));

// ── Stream timer ──────────────────────────────────────────────
setInterval(() => {
  const s = Math.floor((Date.now() - streamStart) / 1000);
  streamTimer.textContent =
    `${String(Math.floor(s/3600)).padStart(2,'0')}:${String(Math.floor((s%3600)/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;
}, 1000);

// ── Toast ─────────────────────────────────────────────────────
let toastTimer;
function showToast(msg, type = 'error') {
  errorToast.textContent = msg;
  errorToast.style.background = type === 'success' ? 'var(--green)' : 'var(--danger)';
  errorToast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => errorToast.classList.remove('show'), 3500);
}

// ── Helpers ───────────────────────────────────────────────────
function esc(s) {
  return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

updateAuthUI();