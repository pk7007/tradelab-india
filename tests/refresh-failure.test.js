const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('web/platform.js', 'utf8');
const first = source.indexOf('async function refreshSelection() {');
const last = source.indexOf('\nselectionStart.onclick =', first);
assert.ok(first >= 0 && last > first, 'refreshSelection source');

function node() {
  return {textContent: '', attrs: {}, cleared: 0, replaceChildren() { this.cleared += 1; },
    setAttribute(name, value) { this.attrs[name] = value; }};
}
const nextAction = node();
const context = {
  document: {hidden: false},
  selectionRefreshing: false, selectionVersion: 0, selectionSnapshot: {stale: true}, sessionSnapshot: {stale: true},
  selectionState: node(), selectionResults: node(), buttonsRecomputed: 0,
  $: id => (id === 'next-action' ? nextAction : {value: 'saved-template'}),
  api: async () => { throw new Error('network down'); },
  setSelectionButtons() { context.buttonsRecomputed += 1; },
};
vm.createContext(context);
vm.runInContext(source.slice(first, last) + '\nthis.refreshSelection = refreshSelection;', context);

(async () => {
  await context.refreshSelection();
  assert.equal(context.selectionState.textContent, 'Session health unavailable. network down');
  assert.equal(context.selectionState.attrs.role, 'alert');           // announced to assistive tech
  assert.equal(nextAction.textContent, 'Refresh session health before issuing another control.');
  assert.equal(context.selectionSnapshot, null);                       // stale data is dropped, controls recomputed
  assert.equal(context.sessionSnapshot, null);
  assert.ok(context.selectionResults.cleared >= 1);
  assert.equal(context.buttonsRecomputed, 1);
  assert.equal(context.selectionRefreshing, false);                    // the next poll may run

  // A hidden tab or an overlapping refresh does nothing.
  context.selectionState.textContent = 'unchanged';
  context.document.hidden = true;
  await context.refreshSelection();
  context.document.hidden = false;
  context.selectionRefreshing = true;
  await context.refreshSelection();
  assert.equal(context.selectionState.textContent, 'unchanged');

  // A response that arrives after the version moved on is ignored.
  context.selectionRefreshing = false;
  context.api = async () => { context.selectionVersion += 1; throw new Error('late'); };
  await context.refreshSelection();
  assert.equal(context.selectionState.textContent, 'unchanged');
  console.log('refresh-failure tests passed');
})().catch(error => { console.error(error); process.exit(1); });
