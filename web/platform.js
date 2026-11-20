'use strict';

const deskPanel = document.createElement('section');
deskPanel.className = 'panel';
deskPanel.append(text('h3', 'Trading desk'));
const deskState = text('p', 'Checking departments…');
const deskDepartments = text('div', '');
deskPanel.append(deskState, deskDepartments);
$('settings').append(deskPanel);
async function refreshDesk() {
  if (document.hidden) return;
  try {
    const desk = await api('/api/desk');
    deskState.textContent = desk.state + ' · Last check ' + (desk.checkedAt || 'pending');
    deskDepartments.replaceChildren();
    for (const department of desk.departments || []) {
      deskDepartments.append(text('p', department.name + ' · ' + department.state));
    }
    if (desk.reviewQueueFull) deskDepartments.append(text('p', 'Review pending agent results to resume new monitoring tasks.'));
    for (const item of desk.pendingIntegrations || []) deskDepartments.append(text('p', item + ' · pending'));
  } catch {
    deskState.textContent = 'Desk health unavailable. Check the local server.';
    deskDepartments.replaceChildren();
  }
}
refreshDesk();
const deskTimer = setInterval(refreshDesk, 10000);
window.addEventListener('pagehide', () => clearInterval(deskTimer));

const selectionPanel = document.createElement('section');
selectionPanel.className = 'session-controls';
selectionPanel.append(text('h3', 'Session controls'));
const selectionState = text('p', 'Checking automatic selection…');
selectionState.setAttribute('role', 'status');
const selectionResults = text('div', '');
const selectionStart = text('button', 'Start paper trading', 'primary');
const selectionPause = text('button', 'Pause new entries');
const selectionResume = text('button', 'Resume new entries');
const selectionEnd = text('button', 'End session and reconcile');
const selectionPermission = document.createElement('input');
selectionPermission.type = 'checkbox';
selectionPermission.id = 'selection-permission';
const selectionLabel = text('label', 'I confirm permission for local price-data storage and the displayed session calendar.');
selectionLabel.className = 'check';
selectionLabel.prepend(selectionPermission);
const selectionButtons = text('div', '', 'controls');
selectionButtons.append(selectionStart, selectionPause, selectionResume, selectionEnd);
selectionPanel.append(selectionState, selectionLabel, selectionButtons, selectionResults);
$('session-overview').append(selectionPanel);
let selectionSnapshot = null, selectionRefreshing = false, selectionMutating = false, selectionVersion = 0;
let sessionSnapshot = null;

function selectionStatusText(snapshot) {
  if (!snapshot) return 'Session health unavailable. Refresh before starting.';
  if (snapshot.closureState === 'unresolved-exposure') {
    if (!snapshot.enabled || snapshot.threadAlive === false || ['ending', 'blocked', 'stopped', 'expired'].includes(snapshot.state)) return 'Unresolved exposure. ' + (snapshot.reason || 'Protective processing and reconciliation remain required.');
    return 'Position open · ' + (snapshot.symbol || 'selected account') + ' · Protective processing remains active.';
  }
  if (snapshot.closureState === 'reconciled-flat' && snapshot.final) return 'Reconciled and flat. No outstanding session exposure.';
  if (snapshot.reason === 'BROKER_LOGIN_REQUIRED') return 'Broker login required. Open Settings and reconnect Zerodha.';
  if (snapshot.enabled && snapshot.threadAlive === false) return 'Session processing unverified. Check service health before continuing.';
  return (snapshot.state || 'Unverified') + ' · ' + (snapshot.reason || (snapshot.symbol ? 'Selected ' + snapshot.symbol : 'No stock selected'));
}

function setSelectionButtons() {
  const unavailable = !selectionSnapshot || selectionMutating;
  selectionStart.disabled = unavailable || Boolean(selectionSnapshot?.enabled) || sessionSnapshot?.readiness?.canRequestStart === false;
  selectionPause.disabled = unavailable || !selectionSnapshot?.enabled;
  selectionResume.disabled = unavailable || !selectionSnapshot?.enabled;
  selectionEnd.disabled = unavailable || !(selectionSnapshot?.enabled || selectionSnapshot?.accountId);
}

async function refreshSelection() {
  if (document.hidden || selectionRefreshing) return;
  selectionRefreshing = true;
  const version = selectionVersion;
  try {
    const snapshot = await api('/api/intraday-session?templateAccount=' + encodeURIComponent($('account').value));
    if (version !== selectionVersion) return;
    sessionSnapshot = snapshot;
    selectionSnapshot = {...snapshot.selection, final: snapshot.report?.final, closureState: snapshot.report?.closureState};
    selectionState.textContent = selectionStatusText(selectionSnapshot);
    selectionResults.replaceChildren();
    for (const notice of sessionSnapshot.attention || []) selectionResults.append(text('p', notice, 'notice'));
    const readiness = sessionSnapshot.readiness || {};
    selectionResults.append(text('p', 'Broker ' + (readiness.connected ? 'connected' : 'login required') + ' · Local data storage ' + (readiness.storageApproved ? 'approved' : 'approval required')));
    if (sessionSnapshot.news?.decisionEffect) selectionResults.append(text('p', sessionSnapshot.news.decisionEffect, 'muted'));
    const evidence = sessionSnapshot.agents?.sessionEvidence;
    if (evidence) {
      const roles = document.createElement('details');
      roles.append(text('summary', 'Roles and evidence handoffs'));
      roles.append(text('p', (evidence.rolesRun?.length || 0) + ' roles ran for observed session evidence.'));
      if (evidence.reviewScope) roles.append(text('p', evidence.reviewScope, 'muted'));
      for (const task of evidence.tasks || []) {
        const item = document.createElement('details');
        item.append(text('summary', task.domain + ' · ' + task.state));
        item.append(text('pre', JSON.stringify(task, null, 2)));
        roles.append(item);
      }
      for (const missing of evidence.missingStages || []) roles.append(text('p', 'Pending · ' + missing));
      selectionResults.append(roles);
    }
    const report = sessionSnapshot.report;
    if (report) {
      const summary = text('div', '', 'closing-report');
      summary.append(text('h3', report.final ? 'Closing report · reconciled and flat' : report.closureState === 'unresolved-exposure' ? 'Open position and account report' : 'Session report · in progress'));
      summary.append(text('p', 'Net result ' + money(report.totalPnl) + ' · fees paid ' + money(report.fees) + ' · fills ' + report.fillCount + ' · completed trades ' + report.completedTrades));
      summary.append(text('p', 'Cash ' + money(report.cash) + ' · exposure ' + money(report.exposure) + ' · shares ' + report.quantity + ' · pending ' + (report.pending?.side || 'none')));
      const trace = document.createElement('details');
      trace.append(text('summary', 'Decision and execution evidence'));
      const traceOutput = text('pre', JSON.stringify(report.trace, null, 2));
      trace.append(traceOutput); summary.append(trace); selectionResults.append(summary);
    }
    if (selectionSnapshot.calendar) {
      selectionResults.append(text('p', 'Calendar ' + selectionSnapshot.calendar.version + ' · Planned square-off ' + (sessionSnapshot.savedProfile?.squareOff || 'not configured') + ' IST.', 'muted'));
    }
    if (selectionSnapshot.universeCount !== undefined) {
      selectionResults.append(text('p', selectionSnapshot.universeCount + ' instruments screened · ' +
        selectionSnapshot.quoteCount + ' quotes returned · ' + selectionSnapshot.candleChecks + ' full candle histories checked'));
    }
    if (selectionSnapshot.symbol) selectionResults.append(text('h3', 'Selected stock · ' + selectionSnapshot.symbol));
    for (const candidate of selectionSnapshot.candidates || []) {
      const row = text('div', '', 'history-item');
      row.append(text('strong', candidate.symbol), text('p', 'SMA spread ' + Number(candidate.score).toFixed(2) + '% · estimated whole shares ' + candidate.estimatedQuantity), text('small', 'Completed candle ' + (candidate.bar || 'unavailable')));
      selectionResults.append(row);
    }
    if (selectionSnapshot.excluded?.length) {
      const excluded = document.createElement('details');
      excluded.append(text('summary', 'Why other stocks were excluded'));
      for (const item of selectionSnapshot.excluded) excluded.append(text('p', item.symbol + ' · ' + item.reason));
      selectionResults.append(excluded);
    }
    const managedId = selectionSnapshot.accountId;
    await refreshPaper();
    if (selectionSnapshot.enabled && managedId && paper.accounts.some(account => account.id === managedId)) {
      $('account').value = managedId;
      showPaper();
    }
    const account = currentAccount();
    if (account) {
      const config = sessionSnapshot.savedProfile || account.config;
      selectionResults.append(text('p', 'Saved account limits · capital ' + money(config.capital) + ' · planned loss per trade ' + money(config.maxLoss) + ' · daily threshold ' + money(config.dailyLossLimit)));
      if (config.capital !== 10000 || config.maxLoss !== 250 || config.dailyLossLimit !== 1000) {
        selectionResults.append(text('p', 'This saved account differs from the intended ₹10,000 / ₹250 / ₹1,000 paper profile. Its original limits apply.', 'notice'));
      }
    }
    $('next-action').textContent = sessionSnapshot.nextAction || selectionSnapshot.reason || (selectionSnapshot.enabled ? 'Waiting for the next completed candle or qualifying stock.' : 'Review the saved account, connection and calendar, then start paper trading.');
    setSelectionButtons();
  } catch (error) {
    if (version !== selectionVersion) return;
    selectionSnapshot = null;
    sessionSnapshot = null;
    selectionState.textContent = 'Session health unavailable. ' + error.message;
    $('next-action').textContent = 'Refresh session health before issuing another control.';
    selectionResults.replaceChildren();
    setSelectionButtons();
  } finally {
    selectionRefreshing = false;
  }
}

async function selectionMutation(path, body) {
  if (selectionMutating || busy) return;
  return run(async () => {
    selectionMutating = true;
    selectionVersion++;
    $('account').disabled = true;
    setSelectionButtons();
    try {
      await api(path, body);
    } catch (error) {
      selectionSnapshot = null;
      selectionState.textContent = 'Control outcome uncertain. Refresh session health before retrying.';
      throw error;
    } finally {
      selectionMutating = false;
      $('account').disabled = false;
      await refreshSelection();
      setSelectionButtons();
    }
  });
}
selectionStart.onclick = () => {
  if (!selectionPermission.checked) { $('message').textContent = 'Confirm data permission and the displayed calendar before starting.'; return; }
  if (!selectionSnapshot) { $('message').textContent = 'Refresh session health first.'; return; }
  selectionMutation('/api/auto-selection/start', {templateAccount: $('account').value,
    calendar: selectionSnapshot.calendar, permitted: true});
};
selectionPause.onclick = () => selectionMutation('/api/auto-selection/control', {action: 'pause_entries'});
selectionResume.onclick = () => selectionMutation('/api/auto-selection/control', {action: 'resume_entries'});
selectionEnd.onclick = () => selectionMutation('/api/auto-selection/control', {action: 'end_session'});
refreshSelection();
const selectionTimer = setInterval(refreshSelection, 10000);
window.addEventListener('pagehide', () => clearInterval(selectionTimer));
document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshSelection(); });

function outputPanel(title, parent) {
  const panel = document.createElement('details');
  panel.className = 'panel';
  panel.append(text('summary', title));
  const output = text('div', 'No result requested yet.');
  output.setAttribute('aria-live', 'polite');
  panel.append(output);
  parent.append(panel);
  return {panel, output};
}

function jsonForm(panel, title, onSubmit) {
  const form = document.createElement('form');
  const label = text('label', title);
  const input = document.createElement('textarea');
  input.rows = 8;
  input.required = true;
  label.append(input);
  const submit = text('button', 'Submit');
  submit.type = 'submit';
  form.append(label, submit);
  panel.append(form);
  form.onsubmit = event => {
    event.preventDefault();
    run(async () => {
      submit.disabled = true;
      try { await onSubmit(JSON.parse(input.value)); }
      finally { submit.disabled = false; }
    });
  };
  return input;
}

function showStructured(output, value) {
  const pre = text('pre', JSON.stringify(value, null, 2));
  pre.style.whiteSpace = 'pre-wrap';
  pre.style.overflowWrap = 'anywhere';
  output.replaceChildren(pre);
}

function showFundamentals(output, report) {
  output.replaceChildren(text('p', report.status));
  for (const candidate of report.candidates || []) {
    const card = text('article', '', 'panel');
    card.append(text('h3', candidate.symbol), text('p', candidate.status));
    if (candidate.financials) showStructured(card, candidate.financials);
    for (const missing of candidate.missing || []) card.append(text('p', 'Missing evidence · ' + missing));
    for (const source of candidate.sources || []) {
      const row = text('p', source.provider || 'Attributed source');
      try {
        const url = new URL(source.url);
        if (url.protocol === 'https:' && !url.username && !url.password) {
          const link = text('a', source.id || 'Source');
          link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; row.append(' ', link);
        }
      } catch {}
      card.append(row);
    }
    const details = document.createElement('details');
    details.append(text('summary', 'Evidence and calculations'));
    const body = document.createElement('div'); showStructured(body, candidate); details.append(body);
    card.append(details); output.append(card);
  }
}

const taskPanel = outputPanel('Agent task submission and controls', $('settings'));
jsonForm(taskPanel.panel, 'Task request JSON', async values => {
  showStructured(taskPanel.output, await api('/api/agents/enqueue', values));
});
const taskHelp = text('p', 'Task results require independent review. Retired agents stop receiving tasks and retain their history.');
taskPanel.panel.append(taskHelp);
jsonForm(taskPanel.panel, 'Task review JSON with id, checks and critical flag', async values => {
  showStructured(taskPanel.output, await api('/api/agents/review', values));
});
jsonForm(taskPanel.panel, 'Agent lifecycle JSON with id, state and reason', async values => {
  showStructured(taskPanel.output, await api('/api/agents/lifecycle', values));
});

const labPanel = outputPanel('Paper strategy improvement and rollback', $('settings'));
labPanel.panel.append(text('p', 'Register hypotheses before evaluation. Promotion uses frozen validation criteria and the selected paper account risk limits.'));
const labRefresh = text('button', 'Refresh strategy history');
labRefresh.type = 'button';
labRefresh.onclick = () => run(async () => showStructured(labPanel.output, await api('/api/strategy-lab')));
labPanel.panel.append(labRefresh);
for (const [action, label] of [['register','Hypothesis registration'], ['candidate','Declarative candidate'], ['evaluate','Evaluation dataset'], ['promote','Paper promotion request'], ['rollback','Paper rollback request']]) {
  jsonForm(labPanel.panel, label + ' JSON', async values => {
    showStructured(labPanel.output, await api('/api/strategy-lab/' + action, values));
  });
}

const operationsPanel = outputPanel('Storage and service health', $('settings'));
const operationsRefresh = text('button', 'Refresh operations health'); operationsRefresh.type = 'button';
operationsRefresh.onclick = () => run(async () => showStructured(operationsPanel.output, await api('/api/operations')));
operationsPanel.panel.append(operationsRefresh);
