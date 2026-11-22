const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('web/portal.js', 'utf8');
const context = {Intl, Date};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function formatDisplayTime('),
  source.indexOf('let settings=')), context);
// The UTC date is still 21 November, while India's date is already the 22nd.
const now = new Date('2026-11-21T20:30:00Z');
assert.equal(context.formatDisplayTime('2026-11-21T19:00:00Z', now), 'Today, 12:30 AM IST');
assert.equal(context.formatDisplayTime('2026-11-21T18:00:00Z', now), 'Yesterday, 11:30 PM IST');
assert.equal(context.formatDisplayTime('2026-11-20T06:40:00Z', now), '20 Nov 2026, 12:10 PM IST');
assert.equal(context.formatDisplayTime('2026-11-22T00:30:00+05:30', now), 'Today, 12:30 AM IST');
for (const value of [null, '', 'invalid', '2026-11-22T12:00:00']) {
  assert.equal(context.formatDisplayTime(value, now), 'Time unavailable');
}
console.log('PASS: news times use IST across midnight, explicit offsets and missing timestamps');
