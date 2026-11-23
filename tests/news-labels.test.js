const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('web/portal.js', 'utf8');
// Minimal DOM: records textContent only; markup injection would need innerHTML, which is also source-checked.
const document = {createElement: tag => ({tag, textContent: '', className: '', children: [],
  append(...kids) { this.children.push(...kids); }})};
const ctx = {document}; vm.createContext(ctx);
const start = source.indexOf('function newsLabelText');
assert.ok(start > 0, 'newsLabelText must exist');
const end = source.indexOf('async function api');
vm.runInContext(source.slice(source.indexOf('function text('), end), ctx);

const good = {sentiment: 'bullish', eventType: 'earnings', confidence: 0.824, symbols: ['TCS'], executionAllowed: false};
const label = ctx.newsLabelText(good);
assert.match(label, /Automatic research label/);
assert.match(label, /not advice/i);
assert.match(label, /bullish/); assert.match(label, /82%/); assert.match(label, /earnings/);
assert.match(ctx.newsLabelText({...good, eventType: 'corporate action'}), /corporate action/);
assert.match(ctx.newsLabelText({...good, eventType: 'order_win'}), /order win/, 'underscores read as spaces');

// Missing assessment: no label.
for (const bad of [undefined, null, {}, 'x', 5, []]) {
  assert.equal(ctx.newsLabelText(bad), '');
  assert.equal(ctx.buildNewsLabel(bad), null);
}
// Malformed or out-of-range values never show NaN/undefined/Infinity.
for (const confidence of [NaN, Infinity, -0.1, 1.5, '0.5', null, undefined, {}]) {
  const out = ctx.newsLabelText({...good, confidence});
  assert.doesNotMatch(out, /NaN|undefined|null|Infinity|object/);
  assert.doesNotMatch(out, /%/, 'invalid confidence is omitted');
}
assert.match(ctx.newsLabelText({...good, confidence: 0}), /0%/);
assert.match(ctx.newsLabelText({...good, confidence: 1}), /100%/);
assert.equal(ctx.newsLabelText({...good, sentiment: 'to-the-moon'}), '', 'unknown sentiment shows no label');
assert.doesNotMatch(ctx.newsLabelText({...good, eventType: 42}), /42|undefined/);
assert.doesNotMatch(ctx.newsLabelText({...good, eventType: undefined}), /undefined|null/);

// Untrusted strings: stripped of markup characters; rendered through textContent only.
const evil = '<img src=x onerror=alert(1)>';
const evilLabel = ctx.newsLabelText({...good, eventType: evil});
assert.doesNotMatch(evilLabel, /[<>"'=]/);
assert.equal(ctx.newsLabelText({...good, sentiment: evil}), '');
const node = ctx.buildNewsLabel({...good, eventType: evil});
assert.equal(node.tag, 'small'); assert.equal(node.textContent, evilLabel);
assert.equal(node.children.length, 0);
assert.ok(!/innerHTML|insertAdjacentHTML|outerHTML/.test(source.slice(start, end)));

// Intelligence status line.
const on = ctx.newsIntelligenceText({status: 'enabled', usedToday: 12, dailyLimit: 100, assessed: 3, rejected: 1});
assert.match(on, /12 of 100/); assert.match(on, /today/); assert.match(on, /3 assessed/);
assert.equal(ctx.newsIntelligenceText({status: 'disabled'}), 'Model labels off');
assert.match(ctx.newsIntelligenceText({status: 'missing-key'}), /Model labels unavailable.*key/i);
assert.match(ctx.newsIntelligenceText({status: 'missing-package'}), /Model labels unavailable/);
assert.match(ctx.newsIntelligenceText({status: 'unavailable'}), /Model labels unavailable/);
for (const bad of [undefined, null, {}, 'enabled', {status: 'weird'}, {status: evil}]) assert.equal(ctx.newsIntelligenceText(bad), '');
const odd = ctx.newsIntelligenceText({status: 'enabled', usedToday: NaN, dailyLimit: -3, assessed: '4', rejected: Infinity});
assert.doesNotMatch(odd, /NaN|undefined|null|Infinity|-3/);
assert.match(odd, /^Model labels on/);
assert.equal(ctx.buildNewsIntelligence(undefined), null);
assert.equal(ctx.buildNewsIntelligence({status: 'disabled'}).textContent, 'Model labels off');
console.log('PASS: model news labels and intelligence status');
