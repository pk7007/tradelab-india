const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('web/platform.js', 'utf8');
function section(start, end) {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first);
  assert.ok(first >= 0 && last > first, 'section ' + start);
  return source.slice(first, last);
}
function node(tag, value = '') {
  return {tagName: tag.toUpperCase(), textContent: String(value), className: '', children: [], attrs: {}, focused: 0,
    append(...items) { this.children.push(...items); },
    setAttribute(name, val) { this.attrs[name] = val; },
    contains(other) { return other === this || this.children.some(child => child.contains && child.contains(other)); },
    querySelectorAll(selector) {
      const found = [];
      const walk = item => { for (const child of item.children) { if (child.tagName === selector) found.push(child); walk(child); } };
      walk(this);
      return found;
    },
    focus() { this.focused += 1; context.document.activeElement = this; }};
}
function flat(item) { return [item.textContent, ...item.children.map(flat)].join(' | '); }

const context = {
  document: {createElement: tag => node(tag), activeElement: null, body: node('body')},
  text: (tag, value, className) => { const made = node(tag, value); made.className = className || ''; return made; },
};
vm.createContext(context);
vm.runInContext(section('// The panel is rebuilt every refresh', 'const selectionStart = text('), context);

// Focus survives a rebuild: same text first, then same position.
const panel = node('div');
const first = node('button', 'Pause new entries');
const second = node('summary', 'Decision and execution evidence');
panel.append(first, second);
context.document.activeElement = second;
const key = context.focusKey(panel);
assert.deepEqual(JSON.parse(JSON.stringify(key)), {tag: 'SUMMARY', text: 'Decision and execution evidence', index: 0});
const rebuilt = node('div');
const newButton = node('button', 'Pause new entries');
const newSummary = node('summary', 'Decision and execution evidence');
rebuilt.append(newButton, newSummary);
context.restoreFocus(rebuilt, key);
assert.equal(newSummary.focused, 1);
assert.equal(newButton.focused, 0);
// Text changed: fall back to the same position.
const changed = node('div');
const renamed = node('summary', 'Renamed section');
changed.append(renamed);
context.restoreFocus(changed, key);
assert.equal(renamed.focused, 1);
// Focus outside the panel is never captured or stolen.
context.document.activeElement = node('button', 'Elsewhere');
assert.equal(context.focusKey(panel), null);
const untouched = node('div');
const lone = node('button', 'Pause new entries');
untouched.append(lone);
context.restoreFocus(untouched, null);
assert.equal(lone.focused, 0);

// Ordered, text-labelled steps (not colour only); nothing rendered when ready or absent.
const out = node('div');
context.renderArmingSteps(out, {ready: false, steps: [
  {key: 'login', label: 'Connect Zerodha', done: false, todo: 'Click Connect Zerodha and sign in yourself.'},
  {key: 'retention', label: 'Approve local candle retention', done: true, todo: 'x'},
  {key: 'calendar', label: 'Session calendar covers today', done: false, todo: 'Today is a holiday. The next listed open session is 2026-11-25; start then.'}]});
const text = flat(out);
assert.match(text, /Before you start/);
assert.match(text, /To do · Connect Zerodha/);
assert.match(text, /Done · Approve local candle retention/);
assert.match(text, /2026-11-25/);
const list = out.children[1];
assert.equal(list.tagName, 'OL');
assert.equal(list.id, 'arming-steps');
assert.equal(list.children.length, 3);
assert.ok(text.indexOf('Connect Zerodha') < text.indexOf('Approve local') && text.indexOf('Approve local') < text.indexOf('Session calendar'));
const empty = node('div');
context.renderArmingSteps(empty, {ready: true, steps: []});
context.renderArmingSteps(empty, undefined);
assert.equal(empty.children.length, 0);

// Notices already covered by the steps are recognised; others (ledger problems) are not.
const prefixes = vm.runInContext('ARMING_NOTICES', context);
assert.ok(prefixes.some(prefix => 'Connect Zerodha before starting or recovering provider observations.'.startsWith(prefix)));
assert.ok(prefixes.some(prefix => 'Today is marked closed in the session calendar, so a paper session cannot start.'.startsWith(prefix)));
assert.ok(!prefixes.some(prefix => 'Ledger mismatch. Investigate before resuming entries.'.startsWith(prefix)));
assert.ok(!prefixes.some(prefix => 'Unresolved exposure or intent remains. Processing is inactive; review recovery.'.startsWith(prefix)));
console.log('arming-ui tests passed');
