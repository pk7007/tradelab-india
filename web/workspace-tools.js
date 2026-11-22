'use strict';

// Guided creation uses the existing paused-account API and explicit review.
const setupPanel = outputPanel('Guided intraday paper setup', $('settings'));
$('settings').prepend(setupPanel.panel);
setupPanel.panel.append(text('p', 'Copy a saved profile, review its budget and execution assumptions, then create a paused paper account.'));
const setupForm = document.createElement('form'); setupForm.id = 'guided-paper-setup';
const setupFields = {};
for (const [name, label, type] of [
  ['symbol', 'Template stock symbol', 'text'], ['provider', 'Data provider', 'text'],
  ['adjustment', 'Price adjustment method', 'text'], ['capital', 'Starting paper cash (₹)', 'number'],
  ['maxExposure', 'Maximum position cost (₹)', 'number'], ['maxLoss', 'Planned loss per trade (₹)', 'number'],
  ['dailyLossLimit', 'Daily loss threshold (₹)', 'number'], ['units', 'Maximum whole shares', 'number'],
  ['stopDistancePct', 'Stop distance (%)', 'number'], ['targetMultiple', 'Target / stop multiple', 'number'],
  ['entryEnd', 'Last entry time (IST)', 'time'], ['squareOff', 'Square-off time (IST)', 'time'],
  ['costBps', 'Fees per side (basis points)', 'number'], ['slippageBps', 'Slippage per side (basis points)', 'number'],
  ['participationPct', 'Maximum share of candle volume (%)', 'number']]) {
  const labelNode = text('label', label);
  const input = document.createElement('input'); input.name = name; input.type = type; input.required = true;
  if (type === 'number') { input.min = '0'; input.step = name === 'units' ? '1' : 'any'; }
  if (type === 'time') input.step = '300';
  labelNode.append(input); setupFields[name] = input; setupForm.append(labelNode);
}
const copySetup = text('button', 'Copy selected account settings'); copySetup.type = 'button';
copySetup.onclick = () => {
  const account = currentAccount();
  if (!account || account.config.strategy !== 'intraday-v1') {
    setupPanel.output.replaceChildren(text('p', 'Select an Intraday v1 account to copy its assumptions.'));
    return;
  }
  for (const [name, input] of Object.entries(setupFields)) input.value = account.config[name] ?? '';
  if (settings) for (const name of ['capital', 'maxLoss', 'dailyLossLimit']) setupFields[name].value = settings[name];
  if (settings) setupFields.maxExposure.value = settings.capital;
  invalidateSetup();
};
const setupReview = text('button', 'Review paper profile', 'primary'); setupReview.type = 'submit';
const setupConfirm = text('button', 'Create paused paper account', 'primary'); setupConfirm.type = 'button'; setupConfirm.hidden = true;
let reviewedSetup = null, setupSubmitting = false;
function invalidateSetup() {
  reviewedSetup = null; setupConfirm.hidden = true;
  setupPanel.output.replaceChildren(text('p', 'Review the current fields before creating this new account.'));
}
setupForm.addEventListener('input', invalidateSetup);
setupForm.onsubmit = event => {
  event.preventDefault();
  const values = {strategy: 'intraday-v1', source: 'imported', permitted: true};
  for (const [name, input] of Object.entries(setupFields)) values[name] = input.type === 'number' ? Number(input.value) : input.value.trim();
  values.symbol = values.symbol.toUpperCase();
  reviewedSetup = JSON.stringify(values);
  setupPanel.output.replaceChildren(text('h3', 'Review new paper account'),
    text('p', values.symbol + ' · Intraday v1 · Starting cash ' + money(values.capital)),
    text('p', 'Planned trade loss ' + money(values.maxLoss) + ' · Daily threshold ' + money(values.dailyLossLimit)),
    text('p', 'Share cap ' + values.units + ' · Stop ' + values.stopDistancePct + '% · Target ' + values.targetMultiple + 'R'),
    text('p', 'Entry cutoff ' + values.entryEnd + ' · Square-off ' + values.squareOff + ' IST'),
    text('p', 'Fees ' + values.costBps + ' bps · Slippage ' + values.slippageBps + ' bps · Volume participation ' + values.participationPct + '%'),
    text('p', 'The bot may select a different stock. This creates a separate paused paper profile.'));
  setupConfirm.hidden = false;
};
setupConfirm.onclick = () => run(async () => {
  if (!reviewedSetup || setupSubmitting) return;
  setupSubmitting = true; setupConfirm.disabled = true;
  try {
    const result = await api('/api/trader/paper-create', JSON.parse(reviewedSetup));
    reviewedSetup = null; setupConfirm.hidden = true;
    await refreshPaper();
    if (result.id) { $('account').value = result.id; showPaper(); }
    setupPanel.output.replaceChildren(text('p', 'Paused paper account created. Review its settings before starting a session.'));
  } finally { setupSubmitting = false; setupConfirm.disabled = false; }
});
setupPanel.panel.append(copySetup, setupForm, setupConfirm); setupForm.append(setupReview);

// Keep existing specialist forms available within a single advanced disclosure.
for (const owner of [taskPanel, labPanel]) {
  const advanced = document.createElement('details'); advanced.append(text('summary', 'Advanced JSON controls'));
  for (const form of [...owner.panel.querySelectorAll('form')]) advanced.append(form);
  owner.panel.append(advanced);
}

function showOperationsHealth(result) {
  const storage = result.storage;
  operationsPanel.output.replaceChildren();
  for (const database of storage.databases || []) operationsPanel.output.append(text('p', database.name + ' · ' + database.integrity));
  const coverage = storage.backupCoverage;
  operationsPanel.output.append(text('p', coverage ? 'Backup coverage ' + coverage.included + '/' + coverage.expected + ' databases · ' + formatDisplayTime(coverage.createdAt) : 'No current backup found.'));
  if (coverage?.missing?.length) operationsPanel.output.append(text('p', 'Missing from backup: ' + coverage.missing.join(', '), 'notice'));
  operationsPanel.output.append(text('p', storage.lastRestoreDrill?.complete ? 'Last restore check passed · ' + formatDisplayTime(storage.lastRestoreDrill.checkedAt) : 'A restore check has not passed yet.'));
  const details = document.createElement('details'); const body = document.createElement('div');
  details.append(text('summary', 'Technical health details'), body);
  showStructured(body, result); operationsPanel.output.append(details);
}
operationsRefresh.onclick = () => run(async () => showOperationsHealth(await api('/api/operations')));
for (const [label, endpoint] of [['Back up current databases', 'backup'], ['Check an isolated restore', 'restore-drill']]) {
  const button = text('button', label); button.type = 'button';
  button.onclick = () => run(async () => {
    button.disabled = true;
    try { await api('/api/operations/' + endpoint, {}); showOperationsHealth(await api('/api/operations')); }
    finally { button.disabled = false; }
  });
  operationsPanel.panel.append(button);
}

const alertPanel = text('details', '', 'panel');
const alertSummary = text('summary', 'Operational alerts');
const alertStatus = text('p', 'Checking alerts…'); alertStatus.setAttribute('role', 'status');
const alertItems = text('div', '');
const enableNotifications = text('button', 'Enable desktop alerts'); enableNotifications.type = 'button';
enableNotifications.onclick = async () => {
  if (!('Notification' in window)) { alertStatus.textContent = 'This browser supports the persistent inbox only.'; return; }
  const permission = await Notification.requestPermission();
  alertStatus.textContent = permission === 'granted' ? 'Desktop alerts enabled while this page is open.' : 'Alerts remain available in this inbox.';
};
alertPanel.append(alertSummary, alertStatus, enableNotifications, text('p', 'The local watcher records outages independently. Desktop delivery needs this page open and browser permission.'), alertItems);
$('auto').prepend(alertPanel);
const notifiedAlerts = new Set();
let alertsBusy = false, connectionAlertShown = false;
function notifyOperationalAlert(id, message) {
  if (notifiedAlerts.has(id)) return;
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification('TradeLab alert', {body: message, tag: id}); notifiedAlerts.add(id);
  }
}
async function refreshOperationalAlerts() {
  if (alertsBusy) return;
  alertsBusy = true;
  try {
    const result = await api('/api/alerts'); connectionAlertShown = false; notifiedAlerts.delete('local-connection');
    alertSummary.textContent = 'Operational alerts · ' + result.unacknowledged + ' unread';
    alertStatus.textContent = result.active ? result.active + ' incidents need attention.' : 'No active incidents.';
    if (!(result.watcherExpires > Date.now() / 1000)) alertStatus.textContent += ' Independent watcher heartbeat is unavailable.';
    alertItems.replaceChildren();
    for (const item of result.items || []) {
      const row = text('article', '', 'history-item');
      row.append(text('strong', (item.resolved_at ? 'Recovered · ' : item.severity + ' · ') + item.message),
        text('small', formatDisplayTime(item.first_seen)));
      if (!item.resolved_at && !item.acknowledged_at) {
        notifyOperationalAlert(item.id, item.message);
        const acknowledge = text('button', 'Acknowledge'); acknowledge.type = 'button';
        acknowledge.onclick = () => run(async () => { await api('/api/alerts/acknowledge', {id: item.id}); await refreshOperationalAlerts(); });
        row.append(acknowledge);
      }
      alertItems.append(row);
    }
  } catch {
    alertStatus.textContent = 'The alerts inbox is unavailable. Check server health and any open paper exposure.';
    if (!connectionAlertShown) { notifyOperationalAlert('local-connection', alertStatus.textContent); connectionAlertShown = true; }
  } finally { alertsBusy = false; }
}
refreshOperationalAlerts();
const operationalAlertsTimer = setInterval(refreshOperationalAlerts, 15000);
window.addEventListener('pagehide', () => clearInterval(operationalAlertsTimer));
