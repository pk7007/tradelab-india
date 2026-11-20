'use strict';

const deskPanel = document.createElement('section');
deskPanel.className = 'panel';
deskPanel.append(text('h3', 'Trading desk'));
const deskState = text('p', 'Checking departments…');
const deskDepartments = text('div', '');
deskPanel.append(deskState, deskDepartments);
$('auto').append(deskPanel);
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

const fundamentalPanel = outputPanel('Evaluate dated long-term evidence', $('longterm'));
fundamentalPanel.panel.append(text('p', 'Import permitted dated statements, valuation, actions, governance, sector and benchmark records.'));
jsonForm(fundamentalPanel.panel, 'Dated research request JSON', async values => {
  const result = await api('/api/portal/research', {...values, horizon: 'long-term'});
  showFundamentals(fundamentalPanel.output, result);
});

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
