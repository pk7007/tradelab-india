const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/portal.js', 'utf8');
const ctx = {URL}; vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('function groupNews'), source.indexOf('let settings=')), ctx);
const article = (source, id, title, symbols = []) => ({source, id, title, symbols, url: 'https://news.example/' + id, publishedAt: '2026-11-22T06:00:00Z'});
const rows = [article('et', 'one', 'TCS wins deal'), article('google', 'extra', 'TCS wins deal'), article('nse', 'two', 'TCS wins deal', ['TCS']),
  article('moneycontrol', 'three', 'Corporate update', ['INFY']), article('moneycontrol', 'four', 'Corporate update', ['INFY']),
  {...article('et', 'bad', 'Unsafe headline'), url: 'javascript:alert(1)'}];
assert.equal(ctx.groupNews(rows).length, 4, 'Related coverage groups; licensed events remain distinct; unsafe links excluded');
const tcs = ctx.groupNews(rows, '', 'tcs');
assert.equal(tcs.length, 2); assert.equal(tcs[0].items.length, 2);
assert.equal(tcs.find(group => group.items[0].source === 'nse').relevance, 'Mapped stock match');
assert.equal(ctx.groupNews(rows, 'et', 'TCS')[0].relevance, 'Keyword match; stock mapping unverified');
assert.equal(ctx.groupNews(rows, 'moneycontrol', 'TCS').length, 0);
assert.equal(rows.length, 6, 'Filtering preserves the source snapshot');
console.log('PASS: local source/stock filters, related stories, relevance and safe URLs');

const filing = {...rows[0], source:'nse', filings:[{url:'https://nsearchives.nseindia.com/corporate/demo.pdf'}]};
assert.equal(ctx.groupNews([filing,...rows], '', '', 'filings').length,1);
assert.equal(ctx.groupNews([filing,...rows], 'et', '', 'filings').length,0);

const secondFiling = {...filing, id:'separate-filing', filings:[{url:'https://nsearchives.nseindia.com/corporate/second.pdf'}]};
assert.equal(ctx.groupNews([filing,secondFiling], '', '', 'filings').length,2);
