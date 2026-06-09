/**
 * app.js — Market Bubble Dashboard
 *
 * Changes:
 *  - Twitch stream embed instead of Kick
 *  - Kick chat uses real user colors (not forced green)
 *  - Badges shown next to usernames (both Twitch and Kick)
 *  - Draggable divider: slide to expand/minimize chat vs stream
 */

const WS_URL         = `ws${location.protocol === 'https:' ? 's' : ''}://${location.host}/ws`;
// ── CHANGED: top-30 coins by market cap via /coins/markets ───────────────
// (was: 6 hardcoded coins via /simple/price)
const COINGECKO_MARKETS_URL = 'https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=30&page=1&price_change_percentage=24h&sparkline=false';
const TICKER_REFRESH = 60_000;
const MAX_CHAT_MSGS  = 300;
const MAX_TWEETS     = 20;

let coinsData      = [];        // populated by fetchTicker()
const knownSymbols = new Set(); // filled on first fetch; used for $SYMBOL detection in chat

// ── State ─────────────────────────────────────────────────────
let activeTab        = 'all';
const tickerMentions = {}; // { 'BTC': 3, 'ETH': 1, … }
let tickerFilter     = null; // active $SYMBOL filter, or null

// Ticker JS animation (replaces CSS animation for drag + pause control)
const TICKER_SPEED     = 25;    // px per second — slow crawl
let tickerOffset       = 0;     // current scroll position in px
let tickerSingleWidth  = 0;     // width of one copy of items (half of track)
let tickerDragging     = false;
let tickerDragStartX   = 0;
let tickerDragStartOff = 0;
let tickerWasDragged   = false; // suppresses click after a drag gesture
let tickerLastTime     = null;  // last rAF timestamp; null = just resumed
let tickerRafRunning   = false;
let streamStart = Date.now();
let ws          = null;
let sessionId   = localStorage.getItem('twitch_session') || null;
let twitchUser  = JSON.parse(localStorage.getItem('twitch_user') || 'null');
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
const streamLoading  = document.getElementById('stream-loading');
const loadingText    = document.getElementById('loading-text');
const streamChip     = document.getElementById('stream-channel-chip');
const twitchPlayer   = document.getElementById('twitch-player');

// ── Twitch stream embed ───────────────────────────────────────
function loadTwitchStream(channel) {
  channel = channel.trim().toLowerCase();
  if (!channel) return;

  console.log(`[Stream] Embedding Twitch channel: ${channel}`);
  streamChip.textContent = channel;

  const parent = location.hostname || 'localhost';
  twitchPlayer.src = `https://player.twitch.tv/?channel=${channel}&parent=${parent}&autoplay=true&muted=false`;
  twitchPlayer.style.display = 'block';
  streamLoading.style.display = 'none';
}

document.getElementById('fullscreen-btn').addEventListener('click', () => {
  if (twitchPlayer.requestFullscreen) twitchPlayer.requestFullscreen();
});

// ── Crypto ticker (top 30 by market cap) ──────────────────────
// CHANGED: uses /coins/markets; populates knownSymbols for chat highlighting
async function fetchTicker() {
  try {
    const r = await fetch(COINGECKO_MARKETS_URL);
    if (!r.ok) return;
    coinsData = await r.json();
    coinsData.forEach(c => knownSymbols.add(c.symbol.toUpperCase()));
    renderTicker(coinsData);
  } catch {}
}

// CHANGED: renders top-30 with CoinGecko icons, glow classes, and click data-sym
function renderTicker(coins) {
  const items = coins.map(coin => {
    const sym    = coin.symbol.toUpperCase();
    const price  = coin.current_price;
    const change = coin.price_change_percentage_24h ?? 0;
    const up     = change >= 0;
    const fmt    = price >= 1000
      ? '$' + price.toLocaleString('en-US', { maximumFractionDigits: 2 })
      : price >= 1
        ? '$' + price.toLocaleString('en-US', { maximumFractionDigits: 4 })
        : '$' + price.toLocaleString('en-US', { maximumFractionDigits: 6 });
    const mentions  = tickerMentions[sym] || 0;
    const glowLevel = getGlowLevel(mentions);
    const glowClass = glowLevel > 0 ? ` ticker-glow-${glowLevel}` : '';
    const filtClass = tickerFilter === sym ? ' ticker-filtered' : '';
    return `<div class="ticker-item${glowClass}${filtClass}" data-sym="${sym}" title="$${sym}: ${mentions} mention${mentions !== 1 ? 's' : ''}. Click to filter chat.">
      <img class="ticker-coin-icon" src="${esc(coin.image)}" alt="${sym}">
      <span class="ticker-symbol">${sym}</span>
      <span class="ticker-price">${fmt}</span>
      <span class="ticker-change ${up?'up':'down'}">${up?'+':''}${change.toFixed(2)}% ${up?'▲':'▼'}</span>
    </div>`;
  }).join('');
  // Duplicate items: at -tickerSingleWidth the two copies align seamlessly
  tickerTrack.innerHTML = items + items;
  startTickerAnimation(); // re-measure width; starts rAF loop on first call
}

// ── JS ticker animation engine ────────────────────────────────
// Runs continuously; position only advances when not paused/dragging
function tickerStep(ts) {
  const paused = tickerFilter !== null || tickerDragging;
  if (!paused && tickerSingleWidth > 0) {
    if (tickerLastTime !== null) {
      const dt = Math.min(ts - tickerLastTime, 50); // cap to avoid big jump after tab-switch
      tickerOffset = (tickerOffset + TICKER_SPEED * dt / 1000) % tickerSingleWidth;
    }
    tickerLastTime = ts;
  } else {
    tickerLastTime = null; // reset so we don't jump when resuming
  }
  tickerTrack.style.transform = `translateX(-${tickerOffset}px)`;
  requestAnimationFrame(tickerStep);
}

function startTickerAnimation() {
  const all = tickerTrack.querySelectorAll('.ticker-item');
  if (!all.length) return;
  let w = 0;
  for (let i = 0; i < all.length / 2; i++) w += all[i].offsetWidth;
  if (!w) { requestAnimationFrame(startTickerAnimation); return; } // wait for layout
  tickerSingleWidth = w;
  tickerOffset      = tickerOffset % tickerSingleWidth;
  if (!tickerRafRunning) { tickerRafRunning = true; requestAnimationFrame(tickerStep); }
}

// ── Ticker drag-to-scroll ─────────────────────────────────────
const tickerBarEl = document.getElementById('ticker-bar');

tickerBarEl.addEventListener('mousedown', e => {
  tickerDragging     = true;
  tickerWasDragged   = false;
  tickerDragStartX   = e.clientX;
  tickerDragStartOff = tickerOffset;
  tickerBarEl.classList.add('dragging');
  e.preventDefault(); // prevent text selection during drag
});

document.addEventListener('mousemove', e => {
  if (!tickerDragging) return;
  const dx = e.clientX - tickerDragStartX;
  if (Math.abs(dx) > 5) tickerWasDragged = true;
  // Drag left (dx < 0) advances ticker; drag right reverses — wrap with modulo
  tickerOffset = ((tickerDragStartOff - dx) % tickerSingleWidth + tickerSingleWidth) % tickerSingleWidth;
});

document.addEventListener('mouseup', () => {
  if (!tickerDragging) return;
  tickerDragging = false;
  tickerBarEl.classList.remove('dragging');
});

// Event delegation on tickerTrack — survives innerHTML re-renders
tickerTrack.addEventListener('click', e => {
  if (tickerWasDragged) return; // don't fire filter after a drag gesture
  const item = e.target.closest('.ticker-item[data-sym]');
  if (item) handleTickerClick(item.dataset.sym);
});

// CHANGED: click a ticker to filter chat; click again to clear
function handleTickerClick(sym) {
  tickerFilter = tickerFilter === sym ? null : sym;
  applyTickerFilter();
  updateTickerFilterBar();
  tickerTrack.querySelectorAll('.ticker-item').forEach(el => {
    const s   = el.dataset.sym;
    const lvl = getGlowLevel(tickerMentions[s] || 0);
    el.className = 'ticker-item' +
      (lvl > 0 ? ` ticker-glow-${lvl}` : '') +
      (tickerFilter === s ? ' ticker-filtered' : '');
  });
}

// Glow level: 1 mention = level 1, +1 level every 2 additional mentions, max 6
function getGlowLevel(mentions) {
  if (mentions <= 0)  return 0;
  if (mentions <= 2)  return 1;
  if (mentions <= 4)  return 2;
  if (mentions <= 6)  return 3;
  if (mentions <= 8)  return 4;
  if (mentions <= 10) return 5;
  return 6;
}

// Update glow classes on both copies of a ticker item without full re-render
function updateTickerItemGlow(sym) {
  const mentions = tickerMentions[sym] || 0;
  const lvl      = getGlowLevel(mentions);
  tickerTrack.querySelectorAll(`.ticker-item[data-sym="${sym}"]`).forEach(el => {
    el.className = 'ticker-item' +
      (lvl > 0 ? ` ticker-glow-${lvl}` : '') +
      (tickerFilter === sym ? ' ticker-filtered' : '');
    el.title = `$${sym}: ${mentions} mention${mentions !== 1 ? 's' : ''}. Click to filter chat.`;
  });
}

// Apply both platform-tab filter and ticker filter together
function applyTickerFilter() {
  document.querySelectorAll('.chat-msg').forEach(msg => {
    const platform   = ['twitch','kick','x'].find(p => msg.classList.contains(p)) || '';
    const platformOk = activeTab === 'all' || activeTab === platform;
    const filterOk   = !tickerFilter ||
      (msg.querySelector('.chat-text')?.textContent || '').toUpperCase().includes('$' + tickerFilter);
    msg.classList.toggle('hidden', !(platformOk && filterOk));
  });
}

// Show/hide the filter status bar inside the chat panel
function updateTickerFilterBar() {
  const bar   = document.getElementById('ticker-filter-bar');
  const label = document.getElementById('ticker-filter-label');
  if (!bar) return;
  if (tickerFilter) {
    label.textContent = '$' + tickerFilter;
    bar.classList.remove('hidden');
  } else {
    bar.classList.add('hidden');
  }
}

document.getElementById('ticker-filter-clear')?.addEventListener('click', () => {
  tickerFilter = null;
  applyTickerFilter();
  updateTickerFilterBar();
  tickerTrack.querySelectorAll('.ticker-item').forEach(el => {
    const s   = el.dataset.sym;
    const lvl = getGlowLevel(tickerMentions[s] || 0);
    el.className = 'ticker-item' + (lvl > 0 ? ` ticker-glow-${lvl}` : '');
  });
});

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
      if      (msg.type === 'twitch_channels') {
        // Use first Twitch channel for the stream embed
        if (msg.channels && msg.channels.length > 0) {
          loadTwitchStream(msg.channels[0]);
        }
      }
      else if (msg.type === 'kick_channel')  { /* kick channel noted, not used for embed */ }
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
const PLATFORM_ICONS = {
  twitch: `<img src="/static/twitch_logo.webp" width="19" height="19">`
  ,
  kick: `<img src="/static/kick_logo.webp" width="12" height="12">`,

  x: `<svg viewBox="0 0 24 24" fill="currentColor">
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.744l7.737-8.858L1.254 2.25H8.08l4.253 5.622zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
  </svg>`,
};

// ── Badge rendering ───────────────────────────────────────────
function renderBadges(badges) {
  if (!badges || !badges.length) return '';
  return badges.map(b => {
    if (b.img_url) {
      return `<img class="badge-img" src="${esc(b.img_url)}" alt="${esc(b.title)}" title="${esc(b.title)}">`;
    }
    // Fallback to emoji span
    return `<span class="badge-emoji" title="${esc(b.title)}">${b.emoji || '🏷'}</span>`;
  }).join('');
}

// ── Chat messages ─────────────────────────────────────────────
function addChatMsg({ platform, channel, username, text, has_emotes, color, badges, self_sent }) {
  if (platform === 'twitch' && channel && !twitchChannels.has(channel)) {
    twitchChannels.add(channel);
    const opt = document.createElement('option');
    opt.value = channel;
    opt.textContent = '#' + channel;
    channelSelect.appendChild(opt);
    if (twitchChannels.size === 1) channelSelect.value = channel;
  }

  const li = document.createElement('li');
  li.className = `chat-msg ${platform}${self_sent ? ' self-sent' : ''}`;
  if (activeTab !== 'all' && activeTab !== platform) li.classList.add('hidden');
  // CHANGED: hide if ticker filter is active and message doesn't mention the symbol
  if (tickerFilter && !(text || '').toUpperCase().includes('$' + tickerFilter)) {
    li.classList.add('hidden');
  }

  // CHANGED: highlight $SYMBOL with blue glow; safe for emote HTML via text-node-only pass
  let rendered = has_emotes ? text : esc(text);
  rendered     = highlightTickers(rendered);

  const badgeHTML     = renderBadges(badges);
  const usernameColor = color || (platform === 'kick' ? '#53FC18' : '#9147FF');

  li.innerHTML = `
    <div class="platform-icon ${platform}">${PLATFORM_ICONS[platform] || ''}</div>
    <div class="chat-body">
      <span class="chat-badges">${badgeHTML}</span><span class="chat-username" style="color:${usernameColor}">${esc(username)}</span><span class="chat-text">${rendered}</span>
    </div>`;

  // CHANGED: tally $SYMBOL mentions and update ticker glow live
  countChatTickers(text);

  chatFeed.prepend(li);
  while (chatFeed.children.length > MAX_CHAT_MSGS) chatFeed.removeChild(chatFeed.lastChild);
}

// Wrap $SYMBOL in a glow span; operates only on text nodes to preserve emote img tags
function highlightTickers(html) {
  return html.replace(/([^<>]*)(<[^>]*>|$)/g, (_, textNode, tag) => {
    if (!textNode) return tag || '';
    const highlighted = textNode.replace(/\$([A-Za-z]{2,6})/g, (m, sym) =>
      knownSymbols.has(sym.toUpperCase())
        ? `<span class="chat-ticker-mention">${m}</span>`
        : m
    );
    return highlighted + (tag || '');
  });
}

// Count $SYMBOL mentions in raw message text; update ticker glow per mention
function countChatTickers(text) {
  const matches = (text || '').match(/\$([A-Za-z]{2,6})/g) || [];
  matches.forEach(m => {
    const sym = m.slice(1).toUpperCase();
    if (knownSymbols.has(sym)) {
      tickerMentions[sym] = (tickerMentions[sym] || 0) + 1;
      updateTickerItemGlow(sym);
    }
  });
}

// ── Tab filters ───────────────────────────────────────────────
// CHANGED: delegates to applyTickerFilter() so platform + ticker filters compose
document.querySelectorAll('.chat-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    activeTab = btn.dataset.platform;
    document.querySelectorAll('.chat-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyTickerFilter();
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

// ══════════════════════════════════════════════════════════════
// ── SLIDING DIVIDERS (left panel ↔ stream ↔ chat) ────────────
// ══════════════════════════════════════════════════════════════
const appEl        = document.getElementById('app');
const streamPanel  = document.getElementById('stream-panel');
const chatPanel    = document.getElementById('chat-panel');
const divider      = document.getElementById('panel-divider');
const snapBtns     = document.getElementById('snap-buttons');
const snapStream   = document.getElementById('snap-stream');
const snapEqual    = document.getElementById('snap-equal');
const snapChat     = document.getElementById('snap-chat');

const leftDivider      = document.getElementById('left-divider');
const leftSnapHide     = document.getElementById('left-snap-hide');
const leftSnapDefault  = document.getElementById('left-snap-default');
const leftSnapExpand   = document.getElementById('left-snap-expand');

const DEFAULT_LEFT_W = 280;
const MIN_LEFT_W     = 0;
const MIN_STREAM_W   = 200;
const MIN_CHAT_W     = 220;
const DIVIDER_W      = 8; // both dividers are 8px

let leftW = DEFAULT_LEFT_W; // current left panel width (changes on drag / snap)

// stream+chat space = total - leftW - 2 dividers
function getMiddleAvailable() {
  return appEl.offsetWidth - leftW - 2 * DIVIDER_W;
}

function applyColumns(newLeftW, chatPx, allowChatZero = false) {
  const totalAvail  = appEl.offsetWidth - 2 * DIVIDER_W;
  leftW             = Math.max(MIN_LEFT_W, Math.min(newLeftW, totalAvail - MIN_STREAM_W - MIN_CHAT_W));
  const midAvail    = appEl.offsetWidth - leftW - 2 * DIVIDER_W;
  const minChat     = allowChatZero ? 0 : MIN_CHAT_W;
  const clampedChat = Math.max(minChat, Math.min(chatPx, midAvail - MIN_STREAM_W));
  // Grid: leftW | 8px | 1fr(stream) | 8px | chatW
  appEl.style.gridTemplateColumns = `${leftW}px ${DIVIDER_W}px 1fr ${DIVIDER_W}px ${clampedChat}px`;
}

function applyRightW(chatPx) {
  applyColumns(leftW, chatPx);
}

function applyLeftW(newLeftW) {
  const currentChat = chatPanel.offsetWidth || MIN_CHAT_W;
  applyColumns(newLeftW, currentChat);
}

// ── Right divider snap presets ────────────────────────────────
// ◀ = expand chat to ~420px  ⬛ = restore equal split  ▶ = collapse chat
const DEFAULT_CHAT_EXPAND = DEFAULT_LEFT_W * 1.5; // ~420px, mirrors left expand

snapStream.addEventListener('click', () => {
  applyColumns(leftW, DEFAULT_CHAT_EXPAND);
  setActiveRightSnap(snapStream);
});
snapEqual.addEventListener('click', () => {
  applyColumns(leftW, getMiddleAvailable() / 2);
  setActiveRightSnap(snapEqual);
});
snapChat.addEventListener('click', () => {
  applyColumns(leftW, 0, true); // collapse to 0
  setActiveRightSnap(snapChat);
});

function setActiveRightSnap(btn) {
  [snapStream, snapEqual, snapChat].forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

// ── Right divider drag ────────────────────────────────────────
let isDragging     = false;
let dragStartX     = 0;
let dragStartRight = 0;

divider.addEventListener('mousedown', e => {
  isDragging     = true;
  dragStartX     = e.clientX;
  dragStartRight = chatPanel.offsetWidth;
  divider.classList.add('dragging');
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';
  twitchPlayer.style.pointerEvents = 'none';
  e.preventDefault();
});

document.addEventListener('mousemove', e => {
  if (isDragging) {
    const dx = dragStartX - e.clientX;
    applyRightW(dragStartRight + dx);
  }
  if (isLeftDragging) {
    const dx = e.clientX - leftDragStartX;
    applyLeftW(leftDragStartLeft + dx);
  }
});

document.addEventListener('mouseup', () => {
  if (isDragging) {
    isDragging = false;
    divider.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    twitchPlayer.style.pointerEvents = '';
  }
  if (isLeftDragging) {
    isLeftDragging = false;
    leftDivider.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    twitchPlayer.style.pointerEvents = '';
  }
});

divider.addEventListener('touchstart', e => {
  isDragging     = true;
  dragStartX     = e.touches[0].clientX;
  dragStartRight = chatPanel.offsetWidth;
  twitchPlayer.style.pointerEvents = 'none';
  e.preventDefault();
}, { passive: false });

document.addEventListener('touchmove', e => {
  if (isDragging) {
    applyRightW(dragStartRight + (dragStartX - e.touches[0].clientX));
  }
  if (isLeftDragging) {
    applyLeftW(leftDragStartLeft + (e.touches[0].clientX - leftDragStartX));
  }
}, { passive: false });

document.addEventListener('touchend', () => {
  isDragging     = false;
  isLeftDragging = false;
  twitchPlayer.style.pointerEvents = '';
});

divider.addEventListener('dblclick', () => {
  appEl.style.gridTemplateColumns = '';
  leftW = DEFAULT_LEFT_W;
  setActiveRightSnap(snapEqual);
});

// ── Left divider drag ─────────────────────────────────────────
let isLeftDragging  = false;
let leftDragStartX  = 0;
let leftDragStartLeft = 0;

leftDivider.addEventListener('mousedown', e => {
  isLeftDragging    = true;
  leftDragStartX    = e.clientX;
  leftDragStartLeft = leftW;
  leftDivider.classList.add('dragging');
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';
  twitchPlayer.style.pointerEvents = 'none';
  e.preventDefault();
});

leftDivider.addEventListener('touchstart', e => {
  isLeftDragging    = true;
  leftDragStartX    = e.touches[0].clientX;
  leftDragStartLeft = leftW;
  twitchPlayer.style.pointerEvents = 'none';
  e.preventDefault();
}, { passive: false });

leftDivider.addEventListener('dblclick', () => {
  applyLeftW(DEFAULT_LEFT_W);
  setActiveLeftSnap(leftSnapDefault);
});

// ── Left divider snap presets ─────────────────────────────────
leftSnapHide.addEventListener('click', () => {
  applyLeftW(MIN_LEFT_W);
  setActiveLeftSnap(leftSnapHide);
});
leftSnapDefault.addEventListener('click', () => {
  applyLeftW(DEFAULT_LEFT_W);
  setActiveLeftSnap(leftSnapDefault);
});
leftSnapExpand.addEventListener('click', () => {
  applyLeftW(DEFAULT_LEFT_W * 1.5); // ~420px
  setActiveLeftSnap(leftSnapExpand);
});

function setActiveLeftSnap(btn) {
  [leftSnapHide, leftSnapDefault, leftSnapExpand].forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

updateAuthUI();

// ══════════════════════════════════════════════════════════════
// ── LEFT PANEL TABS ───────────────────────────────────────────
// ══════════════════════════════════════════════════════════════
const leftTabBtns  = document.querySelectorAll('.left-tab');
const leftPaneMap  = {
  x:          document.getElementById('left-pane-x'),
  polymarket: document.getElementById('left-pane-polymarket'),
  chart:      document.getElementById('left-pane-chart'),
};

const LEFT_TITLES = {
  x:          { icon: `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.744l7.737-8.858L1.254 2.25H8.08l4.253 5.622zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>`, text: 'Live Posts'  },
  polymarket: { icon: `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M3 3h18v2H3zm0 8h18v2H3zm0 8h18v2H3z"/></svg>`,                                              text: 'Polymarket'   },
  chart:      { icon: `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M3.5 18.49l6-6.01 4 4L22 6.92l-1.41-1.41-7.09 7.97-4-4L2 16.99z"/></svg>`,                  text: 'Price Chart'  },
};

leftTabBtns.forEach(tab => {
  tab.addEventListener('click', () => {
    const target = tab.dataset.leftTab;
    leftTabBtns.forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    Object.values(leftPaneMap).forEach(p => p.classList.add('left-pane-hidden'));
    leftPaneMap[target].classList.remove('left-pane-hidden');

    // Update panel header title
    const cfg = LEFT_TITLES[target];
    document.getElementById('left-panel-title').innerHTML =
      `${cfg.icon}<span id="left-panel-title-text">${cfg.text}</span>`;

    // Lazy-load Polymarket on first open
    if (target === 'polymarket' && !polyAllMarkets.length) {
      loadPolymarkets();
    }
  });
});

// ── Polymarket (Gamma API — client-side search) ───────────────
// The Gamma API ignores text query params; we fetch a large batch up front
// and filter locally so search actually works.
const polySearchInput = document.getElementById('poly-search');
const polySearchBtn   = document.getElementById('poly-search-btn');
const polyResults     = document.getElementById('poly-results');
let polyAllMarkets    = [];  // cached after first load

async function loadPolymarkets() {
  polyResults.innerHTML = '<div class="left-loading">Loading markets…</div>';
  try {
    // Fetch two pages in parallel for broader coverage
    const base = 'https://gamma-api.polymarket.com/markets?active=true&limit=100';
    const [r1, r2] = await Promise.all([
      fetch(`${base}&offset=0&order=volume&ascending=false`),
      fetch(`${base}&offset=100&order=volume&ascending=false`),
    ]);
    const [p1, p2] = await Promise.all([r1.json(), r2.json()]);
    polyAllMarkets = [...(Array.isArray(p1) ? p1 : []), ...(Array.isArray(p2) ? p2 : [])];
    renderPolyResults(polyAllMarkets.slice(0, 25));
  } catch {
    polyResults.innerHTML = '<div class="left-empty">Could not load markets — check your connection.</div>';
  }
}

function searchPolymarket(query) {
  if (!polyAllMarkets.length) {
    loadPolymarkets();
    return;
  }
  if (!query) {
    renderPolyResults(polyAllMarkets.slice(0, 25));
    return;
  }
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const hits  = polyAllMarkets.filter(m => {
    const hay = (m.question || m.title || '').toLowerCase();
    return terms.every(t => hay.includes(t));
  });
  renderPolyResults(hits.slice(0, 25));
  if (!hits.length) {
    polyResults.innerHTML = `<div class="left-empty">No markets matched "${esc(query)}".<br><span style="font-size:11px;opacity:.7">Try a broader term.</span></div>`;
  }
}

function renderPolyResults(markets) {
  if (!markets.length) {
    polyResults.innerHTML = '<div class="left-empty">No markets found.</div>';
    return;
  }
  polyResults.innerHTML = '';
  markets.forEach(m => {
    const card = document.createElement('a');
    card.className = 'poly-card';
    card.href      = `https://polymarket.com/event/${m.slug}`;
    card.target    = '_blank';
    card.rel       = 'noopener noreferrer';

    let yesPrice = 0.5;
    if (m.outcomePrices) {
      try {
        const prices = typeof m.outcomePrices === 'string'
          ? JSON.parse(m.outcomePrices) : m.outcomePrices;
        yesPrice = parseFloat(prices[0]) || 0.5;
      } catch {}
    }
    const yesPct = Math.round(yesPrice * 100);
    const noPct  = 100 - yesPct;
    const vol    = m.volume  ? `$${(parseFloat(m.volume)/1000).toFixed(1)}K vol` : '';
    const end    = m.endDate ? new Date(m.endDate).toLocaleDateString('en-US', { month:'short', day:'numeric', year:'numeric' }) : '';

    card.innerHTML = `
      <div class="poly-card-question">${esc(m.question || m.title || 'Market')}</div>
      <div class="poly-card-bar-wrap"><div class="poly-card-bar-yes" style="width:${yesPct}%"></div></div>
      <div class="poly-card-odds">
        <span class="poly-yes">Yes ${yesPct}%</span>
        <span class="poly-no">No ${noPct}%</span>
      </div>
      <div class="poly-card-meta">
        ${vol ? `<span>${vol}</span>` : ''}
        ${end ? `<span>Ends ${end}</span>` : ''}
      </div>`;
    polyResults.appendChild(card);
  });
}

polySearchBtn.addEventListener('click', () => searchPolymarket(polySearchInput.value.trim()));
polySearchInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') searchPolymarket(polySearchInput.value.trim());
});

// ── Price Chart (TradingView widget) ─────────────────────────
const chartSearchInput = document.getElementById('chart-search');
const chartSearchBtn   = document.getElementById('chart-search-btn');
const chartContainer   = document.getElementById('chart-container');
let tvLibCallbacks     = [];
let tvWidgetSeq        = 0;

function ensureTVLib(cb) {
  if (window.TradingView) { cb(); return; }
  tvLibCallbacks.push(cb);
  if (tvLibCallbacks.length > 1) return;
  const s   = document.createElement('script');
  s.src     = 'https://s3.tradingview.com/tv.js';
  s.async   = true;
  s.onload  = () => { tvLibCallbacks.forEach(f => f()); tvLibCallbacks = []; };
  document.head.appendChild(s);
}

function normalizeTVSymbol(raw) {
  const sym = raw.trim().toUpperCase().replace(/\s+/g, '');
  if (sym.includes(':')) return sym;                        // already exchange:symbol
  if (knownSymbols.has(sym)) return `BINANCE:${sym}USDT`;  // known crypto from CoinGecko
  return sym;                                               // let TradingView resolve as stock
}

function loadTradingViewChart(rawSymbol) {
  if (!rawSymbol.trim()) return;
  const tvSym = normalizeTVSymbol(rawSymbol);
  const id    = `tv_chart_${++tvWidgetSeq}`;
  chartContainer.innerHTML = `<div id="${id}" style="width:100%;height:100%"></div>`;

  ensureTVLib(() => {
    new window.TradingView.widget({
      container_id:      id,
      autosize:          true,
      symbol:            tvSym,
      interval:          'D',
      timezone:          'Etc/UTC',
      theme:             document.documentElement.classList.contains('light') ? 'light' : 'dark',
      style:             '1',
      locale:            'en',
      enable_publishing: false,
      hide_side_toolbar: false,
      withdateranges:    true,
      save_image:        false,
    });
  });
}

chartSearchBtn.addEventListener('click',  () => loadTradingViewChart(chartSearchInput.value.trim()));
chartSearchInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') loadTradingViewChart(chartSearchInput.value.trim());
});

// ── Theme toggle (light / dark) ───────────────────────────────
// Toggle on <html> so CSS vars defined in html.light cascade from :root properly
const themeToggle = document.getElementById('theme-toggle');
if (localStorage.getItem('theme') === 'light') document.documentElement.classList.add('light');

themeToggle.addEventListener('click', () => {
  document.documentElement.classList.toggle('light');
  localStorage.setItem('theme', document.documentElement.classList.contains('light') ? 'light' : 'dark');
});