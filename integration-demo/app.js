/* Kirana Mart — third-party merchant integration demo.
 *
 * ZERO AI DEPENDENCY. There is no model SDK, no provider key, no prompt and no
 * inference anywhere in this file. Every "intelligent" behaviour on the page is
 * one HTTP call to the merchant platform, authenticated with an EXTERNAL agent
 * credential the buyer issued and pasted above.
 *
 * Endpoints this app talks to, and nothing else:
 *   GET  /api/products?search=&page_size=   public, no auth        (catalog + search)
 *   GET  /api/auth/me                       X-Agent-Key            (identity check)
 *   POST /api/agent/chat                    X-Agent-Key            (the agent)
 *   POST /api/agent/confirm                 X-Agent-Key            (approve / decline)
 *
 * NOT used, deliberately: /api/cart. Those REST endpoints are BUYER-only and
 * return 403 for an agent key (backend/app/routers/cart.py). Cart state arrives
 * inside the chat response instead.
 */
'use strict';

const LS_KEY = 'kiranamart.agentKey';
const FALLBACK_API = 'http://127.0.0.1:8842';

const state = {
  apiBase: '',          // resolved at boot: same-origin (via serve.py) or FALLBACK_API
  key: '',
  identity: null,
  sessionId: newSessionId(),
  busy: false,
  pending: false,
};

const $ = (id) => document.getElementById(id);

/* ------------------------------------------------------------------ */
/* transport                                                           */
/* ------------------------------------------------------------------ */

function newSessionId() {
  return 'kmart-' + Math.random().toString(36).slice(2, 10);
}

async function api(path, { method = 'GET', body = null, auth = false } = {}) {
  const headers = {};
  if (body) headers['Content-Type'] = 'application/json';
  if (auth) {
    if (!state.key) throw new Error('No agent key set.');
    headers['X-Agent-Key'] = state.key;   // <-- the whole integration, one header
  }
  let res;
  try {
    res = await fetch(state.apiBase + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new Error(
      'Network/CORS failure calling ' + state.apiBase + path +
      '. If you are not serving this page through serve.py, the browser origin must be ' +
      'exactly the backend\'s FRONTEND_URL (http://127.0.0.1:3000) — see README.'
    );
  }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_) { /* non-JSON error body */ }
  if (!res.ok) {
    const detail = (data && (data.detail || data.message)) || text || res.statusText;
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    err.status = res.status;
    throw err;
  }
  return data;
}

/** Prefer same-origin (serve.py proxies /api → backend, so CORS never applies).
 *  Fall back to the backend origin directly, which works only when this page is
 *  served from http://127.0.0.1:3000 — the single origin the backend's CORS allows. */
async function resolveApiBase() {
  try {
    const r = await fetch('/health', { method: 'GET' });
    if (r.ok && (await r.text()).includes('ok')) {
      state.apiBase = '';
      $('apiBaseLabel').textContent = 'API: same-origin proxy → ' + location.origin + '/api/*';
      return;
    }
  } catch (_) { /* fall through */ }
  state.apiBase = FALLBACK_API;
  $('apiBaseLabel').textContent = 'API: direct cross-origin → ' + FALLBACK_API +
    ' (requires this page to be served from http://127.0.0.1:3000)';
}

/* ------------------------------------------------------------------ */
/* key bar + identity                                                  */
/* ------------------------------------------------------------------ */

function setStatus(kind, text) {
  const dot = document.querySelector('#keyStatus .dot');
  dot.className = 'dot dot-' + kind;
  $('keyStatusText').textContent = text;
}

function renderIdentity(me) {
  const dl = $('identity');
  const rows = [
    ['principal type', me.type],
    ['credential id', me.credential_id || '—'],
    ['acts for buyer', me.user_id],
    ['human email', me.email || 'n/a (software principal)'],
    ['human role', me.role || 'n/a (software principal)'],
  ];
  dl.innerHTML = rows.map(([k, v]) =>
    `<div><dt>${esc(k)}</dt><dd>${esc(String(v))}</dd></div>`).join('');
  dl.hidden = false;

  const note = $('identityNote');
  note.textContent =
    'Identity comes from GET /api/auth/me — the only endpoint in the platform that accepts ' +
    'AuthRequirement.AGENT and returns who you are. It intentionally exposes only the ' +
    'principal type, credential id and owning buyer. The credential NAME, its scope list and ' +
    'its spend limit are not readable by the agent itself: those live on /api/agents/{id}, ' +
    'which is BUYER-only and rejects this key with 403. The buyer sees them in the platform UI ' +
    'at credential-creation time.';
  note.hidden = false;
}

async function connect() {
  const raw = $('keyInput').value.trim();
  if (!raw) { setStatus('bad', 'Paste a key first.'); return; }
  setStatus('busy', 'Validating key against GET /api/auth/me …');
  state.key = raw;
  try {
    const me = await api('/api/auth/me', { auth: true });
    if (me.type !== 'agent') {
      setStatus('bad', `That credential resolves to principal type "${me.type}", not "agent". ` +
        'Paste an EXTERNAL agent key, not a user token.');
      state.identity = null;
      $('identity').hidden = true;
      return;
    }
    state.identity = me;
    localStorage.setItem(LS_KEY, raw);
    setStatus('ok', 'Key verified. Authenticated as an agent principal — assistant enabled.');
    renderIdentity(me);
  } catch (e) {
    state.identity = null;
    state.key = '';
    $('identity').hidden = true;
    $('identityNote').hidden = true;
    setStatus('bad', (e.status === 401 ? 'Rejected (401): unknown key. ' : 'Failed: ') + e.message);
  } finally {
    updateEnabled();
  }
}

function forget() {
  localStorage.removeItem(LS_KEY);
  state.key = '';
  state.identity = null;
  $('keyInput').value = '';
  $('identity').hidden = true;
  $('identityNote').hidden = true;
  setStatus('idle', 'Key deleted from this browser. The assistant is disabled.');
  updateEnabled();
}

function updateEnabled() {
  const on = !!state.identity && !state.busy;
  $('chatInput').disabled = !on;
  $('btnSend').disabled = !on;
  $('btnRefreshCart').disabled = !on;
  $('btnApprove').disabled = !on;
  $('btnDecline').disabled = !on;
  $('chatInput').placeholder = state.identity
    ? 'Add 1 Tata Salt to my cart'
    : 'Connect an agent key to chat';
}

/* ------------------------------------------------------------------ */
/* catalog (public endpoints — no key needed)                           */
/* ------------------------------------------------------------------ */

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function productCard(p) {
  const price = p.effective_price_display || p.price_display;
  const cut = p.effective_price_paise < p.price_paise
    ? ` <s style="color:#8790a3">${esc(p.price_display)}</s>` : '';
  return `<article class="product">
    <div>
      <h3>${esc(p.name)}</h3>
      <div class="meta">${esc(p.brand || '')} · ${esc(p.unit || '')} · ${p.stock > 0 ? 'in stock' : 'out of stock'}</div>
      <div class="sku">${esc(p.sku)}</div>
    </div>
    <div class="right">
      <div class="price">${esc(price)}${cut}</div>
      <button class="ghost" type="button" data-ask="Add 1 ${esc(p.name)} to my cart">Ask agent</button>
    </div>
  </article>`;
}

async function loadProducts(search) {
  const hint = $('catalogHint');
  hint.textContent = search ? `Searching for “${search}” …` : 'Loading products…';
  const qs = new URLSearchParams({ page_size: '5' });
  if (search) qs.set('search', search);
  try {
    const data = await api('/api/products?' + qs.toString());
    $('products').innerHTML = data.items.map(productCard).join('') ||
      '<p class="hint">No products matched.</p>';
    hint.textContent = search
      ? `${data.items.length} of ${data.total} match “${search}” · GET /api/products?search=`
      : `5 sample SKUs of ${data.total} in the catalog · GET /api/products (public)`;
  } catch (e) {
    $('products').innerHTML = '';
    hint.textContent = 'Catalog load failed: ' + e.message;
  }
}

/* ------------------------------------------------------------------ */
/* chat                                                                */
/* ------------------------------------------------------------------ */

function addMsg(cls, who, text) {
  const el = document.createElement('div');
  el.className = 'msg ' + cls;
  el.innerHTML = `<span class="who">${esc(who)}</span>${esc(text)}`;
  $('chatLog').appendChild(el);
  $('chatLog').scrollTop = $('chatLog').scrollHeight;
  return el;
}

function renderCart(cart) {
  const box = $('cartBox');
  if (!cart || !cart.items || cart.items.length === 0) {
    box.innerHTML = '<p class="empty">Cart is empty.</p>';
    return;
  }
  box.innerHTML = cart.items.map((i) => `
    <div class="cartline">
      <div><div class="n">${esc(i.name)} × ${esc(i.quantity)}</div><div class="s">${esc(i.sku)}</div></div>
      <div>${esc(i.line_total_display)}</div>
    </div>`).join('') +
    `<div class="carttotal"><span>Total</span><span>${esc(cart.total_display || '')}</span></div>`;
}

function renderPending(pending) {
  const box = $('pendingBox');
  if (!pending) { box.hidden = true; state.pending = false; return; }
  state.pending = true;
  $('pendingDetail').innerHTML = [
    ['tool', pending.tool_name],
    ['arguments', pending.arguments ? JSON.stringify(pending.arguments) : null],
    ['rule', pending.rule_name],
    ['reason', pending.reason],
  ].filter(([, v]) => v).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(String(v))}</dd>`).join('');
  box.hidden = false;
}

function renderExtras(el, r) {
  if (r.product_suggestion) {
    const s = r.product_suggestion;
    const d = document.createElement('div');
    d.className = 'suggestion';
    d.innerHTML = `<span class="t">Suggested: ${esc(s.name)} — ${esc(s.price_display)}</span>` +
      `${esc(s.note || '')} · ${esc(s.unit || '')} · stock ${esc(s.stock)} · ` +
      (s.within_budget ? 'within budget' : 'OVER budget') +
      `<br><button class="ghost" type="button" data-ask="Add 1 ${esc(s.name)} to my cart" ` +
      `style="margin-top:6px">Ask the agent to add it</button>`;
    el.appendChild(d);
  }
  if (r.upsell) {
    const d = document.createElement('div');
    d.className = 'upsell';
    d.innerHTML = `<span class="t">Upsell offer: ${esc(r.upsell.name)} — ` +
      `₹${(r.upsell.price_paise / 100).toFixed(2)}</span>${esc(r.upsell.reason || '')}`;
    el.appendChild(d);
  }
  if (r.payment) {
    const d = document.createElement('div');
    d.className = 'payment';
    d.innerHTML = `<span class="t">Payment initiated — order #${esc(r.payment.order_id)}</span>` +
      `${esc(r.payment.razorpay_order_id)} · ₹${(r.payment.amount_paise / 100).toFixed(2)} ` +
      `${esc(r.payment.currency)} · ${esc(r.payment.status)}`;
    el.appendChild(d);
  }
}

function applyResponse(r) {
  const el = addMsg('agent', 'platform agent · ' + r.status, r.reply);
  renderExtras(el, r);
  renderCart(r.cart);
  renderPending(r.status === 'awaiting_confirmation' ? (r.pending || {}) : null);
  $('chatLog').scrollTop = $('chatLog').scrollHeight;
}

async function withBusy(label, fn) {
  state.busy = true;
  updateEnabled();
  const wait = addMsg('system', 'network', label);
  try {
    await fn();
  } catch (e) {
    addMsg('error', 'error', (e.status ? e.status + ' — ' : '') + e.message);
  } finally {
    wait.remove();
    state.busy = false;
    updateEnabled();
  }
}

async function send(message) {
  if (!message || !state.identity) return;
  addMsg('you', 'merchant shopper', message);
  const rupees = parseFloat($('budgetInput').value);
  const body = { session_id: state.sessionId, message };
  if (!isNaN(rupees) && rupees > 0) body.budget_paise = Math.round(rupees * 100);
  await withBusy('POST /api/agent/chat … (the platform is running the agent; this can take a while)',
    async () => applyResponse(await api('/api/agent/chat', { method: 'POST', body, auth: true })));
}

async function confirm(approve) {
  addMsg('you', 'merchant shopper', approve ? 'Confirm' : 'Decline');
  $('pendingBox').hidden = true;
  await withBusy('POST /api/agent/confirm …', async () =>
    applyResponse(await api('/api/agent/confirm', {
      method: 'POST', auth: true,
      body: { session_id: state.sessionId, approve },
    })));
}

/* ------------------------------------------------------------------ */
/* wiring                                                              */
/* ------------------------------------------------------------------ */

$('btnConnect').addEventListener('click', connect);
$('btnForget').addEventListener('click', forget);
$('btnReveal').addEventListener('click', () => {
  const i = $('keyInput');
  const show = i.type === 'password';
  i.type = show ? 'text' : 'password';
  $('btnReveal').textContent = show ? 'hide' : 'show';
});
$('keyInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') connect(); });

$('searchForm').addEventListener('submit', (e) => {
  e.preventDefault();
  loadProducts($('searchInput').value.trim());
});
$('btnReset').addEventListener('click', () => { $('searchInput').value = ''; loadProducts(''); });

$('chatForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const v = $('chatInput').value.trim();
  $('chatInput').value = '';
  send(v);
});
$('btnApprove').addEventListener('click', () => confirm(true));
$('btnDecline').addEventListener('click', () => confirm(false));
$('btnRefreshCart').addEventListener('click', () => send('Show me what is in my cart right now.'));
$('btnNewSession').addEventListener('click', () => {
  state.sessionId = newSessionId();
  $('sessionId').textContent = state.sessionId;
  $('chatLog').querySelectorAll('.msg:not(.system)').forEach((n) => n.remove());
  $('pendingBox').hidden = true;
  renderCart(null);
});

// "Ask agent" buttons are injected dynamically — one delegated listener.
document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-ask]');
  if (b && state.identity && !state.busy) send(b.getAttribute('data-ask'));
});

(async function boot() {
  $('sessionId').textContent = state.sessionId;
  await resolveApiBase();
  loadProducts('');
  const saved = localStorage.getItem(LS_KEY);
  if (saved) {
    $('keyInput').value = saved;
    setStatus('busy', 'Restoring saved key from localStorage …');
    await connect();
  } else {
    updateEnabled();
  }
})();
