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
    signal: options.signal || AbortSignal.timeout(20000),
    headers: { ...(options.headers || {}), ...(options.method && options.method !== 'GET' ? { 'Content-Type':'application/json', 'X-CSRF-Token':csrf() } : {}) },
    cache: 'no-store',
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if(response.status===401){connectState({connected:false,liveOrdersEnabled,credentialsConfigured:true,dataStorageEnabled:!$('#history-save').disabled});pendingOrder=null;$('#confirmation').hidden=true;}
    throw new Error(payload.error || `Request failed (${response.status})`);
  }
  return payload;
}

function connectState(status) {
  connected = status.connected;
  liveOrdersEnabled = status.liveOrdersEnabled;
  if(!connected)resetAccount();
  $('.live-indicator').textContent=connected?'BROKER SESSION CONNECTED':'BROKER DISCONNECTED';
  $('#account-button').disabled=!connected;
  $('#account-button').title=connected?'Disconnect Zerodha':'No broker session';
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
  if (!status.liveOrdersEnabled) $('#risk-banner').innerHTML='<div><strong>Manual live orders are locked</strong><span>Order previews only. Automated execution is unavailable.</span></div>';
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
  await loadView(currentView);
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

let accountRequest=0;
async function loadView(view) {
  const request=++accountRequest;
  if (['automation','market','research'].includes(view)) return;
  if (!connected) { $('#table-title').textContent={overview:'Recent orders',orders:'All orders',holdings:'Holdings',positions:'Positions'}[view]; table([], '', 'Connect Zerodha to view this account screen'); return; }
  $('#table-title').textContent='Loading '+view+'…';
  $('#table-body').replaceChildren();
  try {
    const [orders,holdings,positions]=await Promise.all([api('/api/orders'),api('/api/holdings'),api('/api/positions')]);
    if(request!==accountRequest||view!==currentView||!connected)return;
    currentOrders=orders.data||[];
    $('#order-count').textContent=String(currentOrders.length);
    $('#orders-total').textContent=String(currentOrders.length);
    $('#orders-note').textContent='Broker order book · refreshed '+new Date().toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata'})+' IST';
    const rows=holdings.data||[];
    $('#holdings-value').textContent=money(rows.reduce((n,x)=>n+Number(x.last_price||0)*Number(x.quantity||0),0));
    $('#holdings-note').textContent=rows.length+' broker-reported holdings';
    const summary=AccountMath.positions(positions.data);
    $('#position-count').textContent=String(summary.open.length);
    $('#day-pnl').textContent=signedMoney(summary.pnl);
    $('#day-pnl').classList.toggle('positive',summary.pnl>=0);
    $('#day-pnl').classList.toggle('negative',summary.pnl<0);
    $('#pnl-note').textContent='Net position P&L, including closed positions; not account-wide daily P&L';
    if(view==='holdings')renderHoldings(rows);
    else if(view==='positions')renderPositions(summary.open);
    else renderOrders(view==='overview'?currentOrders.slice(-6).reverse():currentOrders);
  } catch(e) {
    if(request!==accountRequest||view!==currentView)return;
    resetAccount();
    table([], '', 'Account data unavailable — reconnect or refresh');
    throw e;
  }
}
function resetAccount(){
  for(const id of ['holdings-value','day-pnl','position-count','orders-total','order-count'])$('#'+id).textContent='—';
  currentOrders=[];
  $('#holdings-note').textContent='No current account snapshot';
  $('#pnl-note').textContent='No current account snapshot';
  $('#orders-note').textContent='No current account snapshot';
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
  if (isEmpty) { empty.querySelector('strong').textContent = emptyTitle; empty.querySelector('p').textContent=connected?'No matching records returned by the broker.':'Use the official broker login to load your account.'; empty.querySelector('[data-connect]').hidden=connected; }
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

function showReview(order, confirmationId) {
  pendingOrder = {...order, confirmation_id:confirmationId};
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
  $('#place-order-button').disabled = true;
  $('#confirmation').scrollIntoView({ behavior:'smooth', block:'nearest' });
}

$('#connect-button').addEventListener('click', startConnect);
document.querySelectorAll('[data-connect]').forEach((button) => button.addEventListener('click', startConnect));
document.querySelectorAll('[data-view]').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
$('#refresh-button').addEventListener('click', async()=>{try{await loadStatus();if(currentView==='automation')await loadAutomation();showToast('Status refreshed.');}catch(e){showNotice(e.message,true);}});
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
    showReview(response.order,response.confirmationId);
  } catch (error) {
    showToast(error.message);
  }
});
$('#confirm-text').addEventListener('input', (event) => { $('#place-order-button').disabled = !liveOrdersEnabled || !pendingOrder || event.target.value !== 'PLACE LIVE ORDER'; });
$('#cancel-confirm').addEventListener('click', () => { pendingOrder = null; $('#confirmation').hidden = true; });
$('#place-order-button').addEventListener('click', async () => {
  if (!pendingOrder || $('#confirm-text').value !== 'PLACE LIVE ORDER') return;
  const button = $('#place-order-button');
  button.disabled = true;
  button.textContent = 'Sending order…';
  try {
    const response = await api('/api/orders/place', { method:'POST', body:JSON.stringify({ ...pendingOrder, confirm_text:$('#confirm-text').value }) });
    showNotice(`${response.message} Order ID: ${response.orderId || 'see order book'}`);
    $('#confirmation').hidden = true;
    $('#order-form').reset();
    $('#price-fields').hidden = true;
    pendingOrder = null;
    await loadStatus();
  } catch (error) {
    pendingOrder=null;$('#confirmation').hidden=true;
    showNotice(error.message+' Check the broker order book before creating another order.', true);
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

const today = new Intl.DateTimeFormat('en-IN', { weekday:'long', day:'numeric', month:'long', timeZone:'Asia/Kolkata' }).format(new Date());
$('#today-label').textContent = today.toUpperCase();
const notice = new URLSearchParams(window.location.search).get('notice');
if (notice === 'connected') showNotice('Zerodha account connected. Account data is loaded from Kite Connect.');
if (notice === 'login_cancelled') showNotice('Zerodha sign-in was cancelled or could not be completed.', true);
if (notice === 'login_failed') showNotice('Zerodha sign-in did not complete. Check your app redirect URL and try again.', true);
if (notice === 'login_state_error') showNotice('The sign-in session expired or could not be verified. Try connecting again.', true);
if (notice) window.history.replaceState({}, '', '/');
setView('automation');
loadStatus().catch((error) => showNotice(error.message, true));

$('#order-form').addEventListener('input',e=>{if(e.target.id==='confirm-text')return;pendingOrder=null;$('#confirmation').hidden=true;$('#quote-result').hidden=true;});
$('#account-button').addEventListener('click',async()=>{if(!connected)return;try{await api('/api/disconnect',{method:'POST',body:'{}'});pendingOrder=null;$('#confirmation').hidden=true;await loadStatus();showNotice('Disconnected from Zerodha.');}catch(e){showNotice(e.message,true);}});
