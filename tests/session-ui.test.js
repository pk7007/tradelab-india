const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('web/platform.js', 'utf8');
function section(start, end) {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first);
  assert.ok(first >= 0 && last > first);
  return source.slice(first, last);
}
function element(value = '') {
  return {textContent: String(value), children: [], append(...items) { this.children.push(...items); }};
}
function content(node) {
  return [node.textContent, ...node.children.map(content)].join(' ');
}

const context = {
  document: {createElement: () => element()},
  text: (_tag, value) => element(value),
};
vm.createContext(context);
vm.runInContext(section('function renderEntryReview(', 'async function refreshSelection('), context);
for (const [status, label] of [['eligible', 'Eligible'], ['skip', 'Skip'], ['temporarily-blocked', 'Temporarily blocked']]) {
  const output = element();
  context.renderEntryReview(output, {status, reason: 'Source reason', maxQuantity: 0,
    reviewers: [{identity: 'risk-review', status: 'rejected', reason: 'No affordable whole share'}]});
  assert.match(content(output), new RegExp(label));
  assert.match(content(output), /Maximum whole shares · 0/);
  assert.match(content(output), /risk-review · rejected · No affordable whole share/);
}

const calls = [];
Object.assign(context, {selectionStart: {}, selectionSnapshot: {},
  $: () => ({value: 'saved-template'}),
  selectionMutation: (path, body) => calls.push({path, body})});
vm.runInContext(section('selectionStart.onclick =', 'selectionPause.onclick ='), context);
context.selectionStart.onclick();
assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{path: '/api/auto-selection/start', body: {templateAccount: 'saved-template'}}]);

vm.runInContext(section('function selectionStatusText(', 'function setSelectionButtons('), context);
assert.match(context.selectionStatusText({enabled: true, threadAlive: true,
  closureState: 'unresolved-exposure', symbol: 'DEMO'}), /Position open.*DEMO/);
assert.match(context.selectionStatusText({enabled: true, threadAlive: false,
  closureState: 'unresolved-exposure', symbol: 'DEMO'}), /Unresolved exposure/);
assert.match(context.selectionStatusText({enabled: true, threadAlive: true,
  closureState: 'unresolved-exposure', quantity: 0, pending: {side: 'BUY'}}), /Entry intent pending.*No filled shares/);
assert.match(context.selectionStatusText({closureState: 'reconciled-flat', final: true}), /Reconciled and flat/);
console.log('PASS: one-click saved-profile Start, entry review statuses and actual exposure state');

const portalSource = fs.readFileSync('web/portal.js', 'utf8');
const connectionButton = {};
const connectionContext = {$: () => connectionButton};
vm.createContext(connectionContext);
vm.runInContext(portalSource.slice(portalSource.indexOf('let brokerConnected ='),
  portalSource.indexOf('async function connectZerodha()')), connectionContext);
connectionContext.renderBrokerConnection(true);
assert.equal(connectionButton.textContent, 'Zerodha connected');
assert.equal(connectionButton.disabled, true);
connectionContext.renderBrokerConnection(false);
assert.equal(connectionButton.textContent, 'Connect Zerodha');
assert.equal(connectionButton.disabled, false);
vm.runInContext('brokerConnecting = true', connectionContext);
connectionContext.renderBrokerConnection(false);
assert.equal(connectionButton.disabled, true, 'A status refresh must not permit a duplicate login request');
console.log('PASS: home connection label follows broker state and preserves pending login guard');
