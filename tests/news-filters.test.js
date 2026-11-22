const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/portal.js', 'utf8');
const ctx = {URL}; vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('function groupNews'), source.indexOf('let settings=')), ctx);
const article = (source, id, title, symbols = []) => ({source, id, title, symbols, url: 'https://news.example/' + id, publishedAt: '2026-11-22T06:00:00Z'});
const rows = [article('et', 'one', 'TCS wins deal'), article('nse', 'two', 'TCS wins deal', ['TCS']),
  article('moneycontrol', 'three', 'Corporate update', ['INFY']), article('moneycontrol', 'four', 'Corporate update', ['INFY']),
  {...article('et', 'bad', 'Unsafe headline'), url: 'javascript:alert(1)'}];
assert.equal(ctx.groupNews(rows).length, 3, 'Related coverage groups; licensed events remain distinct; unsafe links excluded');
const tcs = ctx.groupNews(rows, '', 'tcs');
assert.equal(tcs.length, 1); assert.equal(tcs[0].items.length, 2);
assert.equal(tcs[0].relevance, 'Mapped stock match');
assert.equal(ctx.groupNews(rows, 'et', 'TCS')[0].relevance, 'Keyword match; stock mapping unverified');
assert.equal(ctx.groupNews(rows, 'moneycontrol', 'TCS').length, 0);
assert.equal(rows.length, 5, 'Filtering preserves the source snapshot');
console.log('PASS: local source/stock filters, related stories, relevance and safe URLs');
