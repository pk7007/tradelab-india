const assert=require('node:assert/strict');
const {positions}=require('../web/account.js');
const r=positions({day:[{quantity:9,pnl:999}],net:[{quantity:2,pnl:20},{quantity:0,pnl:-5}]});
assert.equal(r.open.length,1);assert.equal(r.open[0].quantity,2);assert.equal(r.pnl,15);
assert.deepEqual(positions({}),{open:[],pnl:0});
console.log('PASS: net positions only, closed P&L included, missing data handled');
