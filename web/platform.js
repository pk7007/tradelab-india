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

// The panel is rebuilt every refresh; keep keyboard focus on the same control afterwards.
const ARMING_NOTICES = ['Connect Zerodha before', 'Confirm approved local market-data retention', 'Today is marked closed', 'The session calendar cannot be used'];
function focusKey(container) {
  const active = document.activeElement;
  if (!active || active === document.body || !container.contains(active)) return null;
  return {tag: active.tagName, text: (active.textContent || '').trim().slice(0, 80),
    index: [...container.querySelectorAll(active.tagName)].indexOf(active)};
}
function restoreFocus(container, key) {
  if (!key) return;
  const same = [...container.querySelectorAll(key.tag)];
  const target = same.find(item => (item.textContent || '').trim().slice(0, 80) === key.text) || same[key.index];
  if (target) target.focus({preventScroll: true});
}
function renderArmingSteps(parent, arming) {
  if (!arming || arming.ready) return;
  parent.append(text('h3', 'Before you start'));
  const list = document.createElement('ol');
  list.id = 'arming-steps';
  list.className = 'arming-steps';
  for (const step of arming.steps || []) {
    const item = document.createElement('li');
    item.append(text('strong', (step.done ? 'Done · ' : 'To do · ') + step.label));
    if (!step.done) item.append(text('span', ' — ' + step.todo, 'muted'));
    list.append(item);
  }
  parent.append(list);
}
const selectionStart = text('button', 'Start paper trading', 'primary');
const selectionPause = text('button', 'Pause new entries');
const selectionResume = text('button', 'Resume new entries');
const selectionEnd = text('button', 'End session and reconcile');
const selectionButtons = text('div', '', 'controls');
selectionButtons.append(selectionStart, selectionPause, selectionResume, selectionEnd);
selectionPanel.append(selectionState, selectionButtons, selectionResults);
$('session-overview').append(selectionPanel);
let selectionSnapshot = null, selectionRefreshing = false, selectionMutating = false, selectionVersion = 0;
let sessionSnapshot = null;

function selectionStatusText(snapshot) {
  if (!snapshot) return 'Session health unavailable. Refresh before starting.';
  if (snapshot.closureState === 'unresolved-exposure') {
    if (snapshot.quantity === 0 && snapshot.pending?.side === 'BUY') return 'Entry intent pending · No filled shares. ' + (snapshot.reason || 'The next accepted candle must pass entry checks.');
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
  const armingPending = sessionSnapshot?.arming && !sessionSnapshot.arming.ready;
  for (const [button, reason] of [[selectionStart, armingPending ? 'arming-steps' : 'next-action'],
      [selectionPause, 'next-action'], [selectionResume, 'next-action'], [selectionEnd, 'next-action']]) {
    if (button.disabled) button.setAttribute('aria-describedby', reason); else button.removeAttribute('aria-describedby');
  }
}

function renderEntryReview(parent, review) {
  const panel = text('div', '', 'entry-decision');
  panel.append(text('h3', 'Entry decision'));
  if (!review) {
    panel.append(text('p', 'Waiting for a completed signal and its entry checks.'));
    parent.append(panel);
    return;
  }
  const labels = {eligible: 'Eligible', skip: 'Skip', 'temporarily-blocked': 'Temporarily blocked'};
  panel.append(text('strong', labels[review.status] || review.status));
  panel.append(text('p', review.reason));
  panel.append(text('p', 'Maximum whole shares · ' + review.maxQuantity));
  const details = document.createElement('details');
  details.append(text('summary', 'Entry reviewers and evidence'));
  for (const reviewer of review.reviewers || []) {
    details.append(text('p', reviewer.identity + ' · ' + reviewer.status + ' · ' + reviewer.reason));
  }
  if (review.handoffs) {
    details.append(text('h4', 'Entry task handoffs · ' + review.handoffs.state));
    for (const task of review.handoffs.tasks || []) {
      details.append(text('p', task.domain.replaceAll('-', ' ') + ' · ' + task.state
        + (task.reason ? ' · ' + task.reason : ' · independently checked')));
    }
  }
  details.append(text('pre', JSON.stringify(review, null, 2)));
  panel.append(details);
  parent.append(panel);
}

async function refreshSelection() {
  if (document.hidden || selectionRefreshing) return;
  selectionRefreshing = true;
  const version = selectionVersion;
  try {
    const snapshot = await api('/api/intraday-session?templateAccount=' + encodeURIComponent($('account').value));
    if (version !== selectionVersion) return;
    sessionSnapshot = snapshot;
    renderBrokerConnection(snapshot.readiness.connected);
    selectionSnapshot = {...snapshot.selection, final: snapshot.report?.final,
      closureState: snapshot.report?.closureState, quantity: snapshot.report?.quantity,
      pending: snapshot.report?.pending};
    selectionState.textContent = selectionStatusText(selectionSnapshot);
    const expandedDetails = new Set([...selectionResults.querySelectorAll('details[open]')]
      .map(detail => detail.querySelector('summary')?.textContent));
    const focusAt = focusKey(selectionResults);
    selectionResults.replaceChildren();
    selectionState.setAttribute('role', 'status');
    renderArmingSteps(selectionResults, sessionSnapshot.arming);
    const coveredBySteps = sessionSnapshot.arming && !sessionSnapshot.arming.ready;
    for (const notice of sessionSnapshot.attention || []) {
      if (coveredBySteps && ARMING_NOTICES.some(prefix => notice.startsWith(prefix))) continue;
      selectionResults.append(text('p', notice, 'notice'));
    }
    const readiness = sessionSnapshot.readiness || {};
    const sessionDetails = document.createElement('details');
    sessionDetails.append(text('summary', 'Session setup and diagnostics'));
    sessionDetails.append(text('p', 'Broker ' + (readiness.connected ? 'connected' : 'login required') + ' · Local data storage ' + (readiness.storageApproved ? 'approved' : 'approval required') + (readiness.calendarReady === null || readiness.calendarReady === undefined ? '' : ' · Session calendar ' + (readiness.calendarReady ? 'ready for today' : 'not usable today'))));
    if (sessionSnapshot.news?.decisionEffect) sessionDetails.append(text('p', sessionSnapshot.news.decisionEffect, 'muted'));
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
      sessionDetails.append(roles);
    }
    const report = sessionSnapshot.report;
    const latestEntryReview = report?.trace?.events?.findLast(event => event.type === 'entry-review');
    if (latestEntryReview || selectionSnapshot.enabled) renderEntryReview(selectionResults, latestEntryReview);
    if (report) {
      const summary = text('div', '', 'closing-report');
      const heading = report.final ? 'Closing report · reconciled and flat'
        : report.quantity > 0 ? 'Open position and account report'
        : report.pending ? 'Pending entry and account report' : 'Session report · in progress';
      summary.append(text('h3', heading));
      summary.append(text('p', 'Net result ' + money(report.totalPnl) + ' · fees paid ' + money(report.fees) + ' · fills ' + report.fillCount + ' · completed trades ' + report.completedTrades));
      summary.append(text('p', 'Cash ' + money(report.cash) + ' · exposure ' + money(report.exposure) + ' · shares ' + report.quantity + ' · pending ' + (report.pending?.side || 'none')));
      const trace = document.createElement('details');
      trace.append(text('summary', 'Decision and execution evidence'));
      const traceOutput = text('pre', JSON.stringify(report.trace, null, 2));
      trace.append(traceOutput); summary.append(trace); selectionResults.append(summary);
    }
    if (selectionSnapshot.calendar) {
      const calendar = selectionSnapshot.calendar;
      sessionDetails.append(text('p', 'Calendar ' + calendar.version + ' · Planned square-off ' + (sessionSnapshot.savedProfile?.squareOff || 'not configured') + ' IST.', 'muted'));
      if (calendar.scope) sessionDetails.append(text('p', calendar.scope, 'muted'));
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
    selectionResults.append(sessionDetails);
    for (const detail of selectionResults.querySelectorAll('details')) {
      detail.open = expandedDetails.has(detail.querySelector('summary')?.textContent);
    }
    restoreFocus(selectionResults, focusAt);
    $('next-action').textContent = sessionSnapshot.nextAction || selectionSnapshot.reason || (selectionSnapshot.enabled ? 'Waiting for the next completed candle or qualifying stock.' : 'Review the saved account, connection and calendar, then start paper trading.');
    setSelectionButtons();
  } catch (error) {
    if (version !== selectionVersion) return;
    selectionSnapshot = null;
    sessionSnapshot = null;
    selectionState.textContent = 'Session health unavailable. ' + error.message;
    selectionState.setAttribute('role', 'alert');
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
  if (!selectionSnapshot) { $('message').textContent = 'Refresh session health first.'; return; }
  selectionMutation('/api/auto-selection/start', {templateAccount: $('account').value});
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
