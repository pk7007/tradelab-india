const $ = (selector) => document.querySelector(selector);
const csrf = () => $('meta[name="csrf-token"]').content;
let connected = false;
let liveOrdersEnabled = false;
let currentView = 'automation';
let currentOrders = [];
let pendingOrder = null;
let toastTimer;

const money = (value) => Number.isFinite(Number(value)) ? `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—';
const signedMoney = (value) => {
  const number = Number(value || 0);
  return `${number >= 0 ? '+' : '−'}${money(Math.abs(number))}`;
};
const safe = (value) => String(value ?? '—').replace(/[&<>"']/g, (char) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[char]));

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 4200);
}

function showNotice(message, isError = false) {
  const notice = $('#notice');
  notice.hidden = !message;
  notice.classList.toggle('error', isError);
  notice.textContent = message;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...(options.headers || {}), ...(options.method && options.method !== 'GET' ? { 'Content-Type':'application/json', 'X-CSRF-Token':csrf() } : {}) },
    cache: 'no-store',
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function connectState(status) {
  connected = status.connected;
  liveOrdersEnabled = status.liveOrdersEnabled;
  $('#history-save').disabled = !status.dataStorageEnabled;
  if (status.dataStorageEnabled) $('#storage-note').textContent = 'CSV and provenance files save to Windows Local App Data / TradeLabIndia / market-data by default, outside this OneDrive workspace. Market data is excluded from Git.';
  $('#side-dot').classList.toggle('online', connected);
  $('#side-connection').textContent = connected ? 'Zerodha connected' : 'Not connected';
  $('#mode-pill').classList.toggle('online', connected);
  $('#mode-pill').innerHTML = `<i></i> ${connected ? 'ACCOUNT CONNECTED' : 'CONNECT ACCOUNT'}`;
  $('#connect-button').hidden = connected;
  $('#account-name').textContent = status.profile?.user_shortname || status.profile?.user_name || (connected ? 'Zerodha account' : 'Local session');
  $('#avatar').textContent = (status.profile?.user_shortname || status.profile?.user_name || 'Z').slice(0, 1).toUpperCase();
  $('#order-lock').hidden = connected;
  $('#order-form').hidden = !connected;
  $('#risk-banner').classList.toggle('enabled', status.liveOrdersEnabled);
  if (status.liveOrdersEnabled) {
    $('#risk-banner').innerHTML = '<span class="risk-icon">!</span><div><strong>Manual live orders are enabled</strong><span>Orders you confirm here are sent to Zerodha. Check every detail before continuing.</span></div><span class="lock-tag">MANUAL ORDERS ON</span>';
    $('#place-order-button').textContent = 'Place live order ↗';
  }
  if (!status.credentialsConfigured && !connected) showNotice('Add your Kite developer API key and secret to the local .env file, then restart the app to connect.', true);
}

async function loadStatus() {
  const status = await api('/api/status');
  $('meta[name="csrf-token"]').content = status.csrf;
  connectState(status);
  if (status.connected) await loadView(currentView);
}

function setView(view) {
  currentView = view;
  document.querySelectorAll('[data-view]').forEach((item) => item.classList.toggle('active', item.dataset.view === view));
  const labels = { automation:'Automation', overview:'Overview', orders:'Orders', holdings:'Holdings', positions:'Positions', market:'Market data', research:'Strategy lab' };
  const titles = { automation:'Your automation control room.', overview:'Your market, in focus.', orders:'Your order book.', holdings:'Your holdings.', positions:'Your positions.', market:'Explore the market record.', research:'Make assumptions visible.' };
  const subtitles = { automation:'Configure deliberately. Monitor every intent. Remain in control.', overview:'A clear view of your Zerodha account and open activity.', orders:'Track the status of orders submitted through Zerodha.', holdings:'Your long-term investments, as reported by Zerodha.', positions:'Your current day and carry-forward positions.', market:'Historical candles and private live price charts from your Connect subscription.', research:'An educational strategy simulator using synthetic prices only.' };
  $('.stat-grid').hidden = ['automation','market','research'].includes(view);
  $('.main-grid').hidden = ['automation','market','research'].includes(view);
  $('#automation-workspace').hidden = view !== 'automation';
  $('#market-workspace').hidden = view !== 'market';
  $('#research-workspace').hidden = view !== 'research';
  $('#crumb-view').textContent = labels[view];
  $('#page-title').textContent = titles[view];
  $('#page-subtitle').textContent = subtitles[view];
  loadView(view).catch((error) => showNotice(error.message, true));
}

async function loadView(view) {
  if (['automation','market','research'].includes(view)) return;
  if (!connected) return;
  if (view === 'orders' || view === 'overview') {
    const response = await api('/api/orders');
    currentOrders = response.data || [];
    $('#order-count').textContent = String(currentOrders.length);
    $('#orders-total').textContent = String(currentOrders.length);
    const active = currentOrders.filter((order) => ['OPEN','TRIGGER PENDING','PUT ORDER REQ RECEIVED','MODIFY VALIDATION PENDING'].includes(String(order.status).toUpperCase())).length;
    $('#orders-note').textContent = `${active} pending · broker order book`;
  }
  if (view === 'holdings' || view === 'overview') {
    const response = await api('/api/holdings');
    const rows = response.data || [];
    const value = rows.reduce((sum, row) => sum + Number(row.last_price || 0) * Number(row.quantity || 0), 0);
    $('#holdings-value').textContent = money(value);
    $('#holdings-note').textContent = `${rows.length} instrument${rows.length === 1 ? '' : 's'} · broker-reported holdings`;
    if (view === 'holdings') renderHoldings(rows);
  }
  if (view === 'positions' || view === 'overview') {
    const response = await api('/api/positions');
    const positions = [...(response.data?.day || []), ...(response.data?.net || [])];
    const uniquePositions = positions.filter((position, index, all) => all.findIndex((item) => item.exchange === position.exchange && item.tradingsymbol === position.tradingsymbol && item.product === position.product) === index);
    const open = uniquePositions.filter((item) => Number(item.quantity || 0) !== 0);
    const pnl = open.reduce((sum, item) => sum + Number(item.pnl || 0), 0);
    $('#position-count').textContent = String(open.length);
    $('#day-pnl').textContent = signedMoney(pnl);
    $('#day-pnl').classList.toggle('positive', pnl >= 0);
    $('#day-pnl').classList.toggle('negative', pnl < 0);
    $('#pnl-note').textContent = 'Broker-reported P&L · positions';
    if (view === 'positions') renderPositions(open);
  }
  if (view === 'orders') renderOrders(currentOrders);
  if (view === 'overview') renderOrders(currentOrders.slice(-6).reverse());
}

function statusClass(value) {
  return String(value || '').toLowerCase().replace(/[^a-z-]/g, '-');
}

function table(headers, rows, emptyTitle = 'Nothing to show yet') {
  $('#table-head').innerHTML = `<tr>${headers.map((header) => `<th>${safe(header)}</th>`).join('')}</tr>`;
  $('#table-body').innerHTML = rows;
  const empty = $('#empty-state');
  const isEmpty = !rows;
  empty.hidden = !isEmpty;
  if (isEmpty) empty.querySelector('strong').textContent = emptyTitle;
}

function renderOrders(orders) {
  $('#table-title').textContent = currentView === 'orders' ? 'All orders' : 'Recent orders';
  const rows = orders.map((order) => `<tr><td class="symbol-cell">${safe(order.tradingsymbol)}<span class="sub-cell">${safe(order.exchange)} · ${safe(order.product)}</span></td><td>${safe(order.transaction_type)}</td><td>${safe(order.quantity)}</td><td>${order.order_type === 'MARKET' ? 'Market' : money(order.price)}</td><td><span class="status ${statusClass(order.status)}">${safe(order.status)}</span></td><td>${safe(order.order_id)}</td></tr>`).join('');
  table(['INSTRUMENT','SIDE','QTY','PRICE','STATUS','ORDER ID'], rows, 'No orders in this view');
}

function renderHoldings(rows) {
  $('#table-title').textContent = 'Holdings';
  const html = rows.map((row) => `<tr><td class="symbol-cell">${safe(row.tradingsymbol)}<span class="sub-cell">${safe(row.exchange)} · ${safe(row.product)}</span></td><td>${safe(row.quantity)}</td><td>${money(row.average_price)}</td><td>${money(row.last_price)}</td><td>${money(Number(row.last_price || 0) * Number(row.quantity || 0))}</td></tr>`).join('');
  table(['INSTRUMENT','QTY','AVG. PRICE','LTP','VALUE'], html, 'No holdings returned by Zerodha');
}

function renderPositions(rows) {
  $('#table-title').textContent = 'Positions';
  const html = rows.map((row) => `<tr><td class="symbol-cell">${safe(row.tradingsymbol)}<span class="sub-cell">${safe(row.exchange)} · ${safe(row.product)}</span></td><td>${safe(row.quantity)}</td><td>${money(row.average_price)}</td><td>${money(row.last_price)}</td><td class="${Number(row.pnl || 0) >= 0 ? 'positive' : 'negative'}">${signedMoney(row.pnl)}</td></tr>`).join('');
  table(['INSTRUMENT','QTY','AVG. PRICE','LTP','P&L'], html, 'No open positions returned by Zerodha');
}

async function startConnect() {
  showNotice('Opening the secure Zerodha sign-in…');
  try {
    const response = await api('/api/connect', { method:'POST', body:'{}' });
    window.location.assign(response.url);
  } catch (error) {
    showNotice(error.message, true);
  }
}

function orderValues() {
  return Object.fromEntries(new FormData($('#order-form')).entries());
}

function showReview(order) {
  pendingOrder = order;
  const fields = [
    ['Side', order.transaction_type], ['Instrument', `${order.exchange}:${order.tradingsymbol}`], ['Quantity', order.quantity],
    ['Product', order.product], ['Order type', order.order_type], ['Price', order.order_type === 'MARKET' ? 'Market price' : money(order.price)],
    ...(order.market_protection ? [['Market protection', 'Automatic']] : []),
    ...(order.trigger_price ? [['Trigger', money(order.trigger_price)]] : []), ['Validity', order.validity],
  ];
  $('#confirm-summary').innerHTML = `<strong>Check every order detail</strong><br>${fields.map(([label, value]) => `<span>${safe(label)}:</span> ${safe(value)}`).join('<br>')}<br><em>This order will be sent to your connected Zerodha account.</em>`;
  $('#confirmation').hidden = false;
  $('#confirm-field').hidden = !liveOrdersEnabled;
  $('#confirm-lock').hidden = liveOrdersEnabled;
  $('#confirm-text').value = '';
  $('#place-order-button').disabled = !liveOrdersEnabled;
  $('#confirmation').scrollIntoView({ behavior:'smooth', block:'nearest' });
}

$('#connect-button').addEventListener('click', startConnect);
document.querySelectorAll('[data-connect]').forEach((button) => button.addEventListener('click', startConnect));
document.querySelectorAll('[data-view]').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
$('#refresh-button').addEventListener('click', () => loadStatus().then(() => showToast('Account data refreshed.')).catch((error) => showNotice(error.message, true)));
$('#order-type').addEventListener('change', (event) => {
  const type = event.target.value;
  $('#price-fields').hidden = type === 'MARKET';
  $('#price-field').hidden = type === 'SL-M';
  $('#trigger-field').hidden = !['SL','SL-M'].includes(type);
});
$('#order-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  $('#confirmation').hidden = true;
  try {
    const response = await api('/api/orders/preview', { method:'POST', body:JSON.stringify(orderValues()) });
    showReview(response.order);
  } catch (error) {
    showToast(error.message);
  }
});
$('#confirm-text').addEventListener('input', (event) => { $('#place-order-button').disabled = event.target.value !== 'PLACE LIVE ORDER'; });
$('#cancel-confirm').addEventListener('click', () => { pendingOrder = null; $('#confirmation').hidden = true; });
$('#place-order-button').addEventListener('click', async () => {
  if (!pendingOrder || $('#confirm-text').value !== 'PLACE LIVE ORDER') return;
  const button = $('#place-order-button');
  button.disabled = true;
  button.textContent = 'Sending order…';
  try {
    const response = await api('/api/orders/place', { method:'POST', body:JSON.stringify({ ...pendingOrder, confirm_text:$('#confirm-text').value, confirmation_id:crypto.randomUUID() }) });
    showNotice(`${response.message} Order ID: ${response.orderId || 'see order book'}`);
    $('#confirmation').hidden = true;
    $('#order-form').reset();
    $('#price-fields').hidden = true;
    pendingOrder = null;
    await loadStatus();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    button.textContent = 'Place live order ↗';
    button.disabled = true;
  }
});
$('#quote-button').addEventListener('click', async () => {
  const values = orderValues();
  const instrument = `${values.exchange}:${String(values.tradingsymbol || '').trim().toUpperCase()}`;
  if (!values.tradingsymbol) return showToast('Enter a trading symbol first.');
  try {
    const response = await api(`/api/quote?i=${encodeURIComponent(instrument)}`);
    const item = Object.values(response.data || {})[0];
    $('#quote-result').hidden = false;
    $('#quote-result').textContent = item ? `Last traded price · ${money(item.last_price)}` : 'No quote returned for this symbol.';
  } catch (error) {
    showToast(error.message);
  }
});

const today = new Intl.DateTimeFormat('en-IN', { weekday:'long', day:'numeric', month:'long' }).format(new Date());
$('#today-label').textContent = today.toUpperCase();
const notice = new URLSearchParams(window.location.search).get('notice');
if (notice === 'connected') showNotice('Zerodha account connected. Account data is loaded from Kite Connect.');
if (notice === 'login_cancelled') showNotice('Zerodha sign-in was cancelled or could not be completed.', true);
if (notice === 'login_failed') showNotice('Zerodha sign-in did not complete. Check your app redirect URL and try again.', true);
if (notice === 'login_state_error') showNotice('The sign-in session expired or could not be verified. Try connecting again.', true);
if (notice) window.history.replaceState({}, '', '/');
setView('automation');
loadStatus().catch((error) => showNotice(error.message, true));
