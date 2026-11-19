const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');
const source=fs.readFileSync('web/portal.js','utf8');
function section(start,end){const a=source.indexOf(start),b=source.indexOf(end,a);assert.ok(a>=0&&b>a);return source.slice(a,b);}
const helpers={};vm.createContext(helpers);vm.runInContext(section('function workerEligible','function renderWorkerSelection'),helpers);
assert.equal(helpers.workerEligible({config:{strategy:'intraday-v1',source:'imported'}}),true);
assert.equal(helpers.workerEligible({config:{strategy:'intraday-v1',source:'synthetic'}}),false);
assert.equal(helpers.workerEligible({config:{strategy:'legacy',source:'imported'}}),false);
assert.match(helpers.workerStatusText({state:'running',live:false}),/fresh candles must be checked separately/);
assert.match(helpers.workerStatusText({state:'running',live:true}),/unverified/);
const nodes={'worker-symbol':{value:'INFY'},'worker-token':{value:'408065'},'worker-retention':{checked:true},'worker-calendar-confirmed':{checked:true},'worker-calendar':{value:'{"exchange":"NSE","version":"fixture"}'}};
const ctx={$:id=>nodes[id],workerEligible:helpers.workerEligible};vm.createContext(ctx);vm.runInContext(section('function workerStartPayload','async function workerMutation'),ctx);
const account={id:'paper-1',config:{symbol:'INFY',strategy:'intraday-v1',source:'imported'}};
const payload=ctx.workerStartPayload(account);assert.equal(payload.id,'paper-1');assert.equal(payload.instrument.token,408065);assert.equal(payload.retentionApproved,true);assert.equal(payload.calendarConfirmed,true);
nodes['worker-symbol'].value='TCS';assert.throws(()=>ctx.workerStartPayload(account),/exactly match/);nodes['worker-symbol'].value='INFY';
nodes['worker-retention'].checked=false;assert.throws(()=>ctx.workerStartPayload(account),/Confirm/);nodes['worker-retention'].checked=true;
nodes['worker-token'].value='1.5';assert.throws(()=>ctx.workerStartPayload(account),/whole/);
(async()=>{
 let resolve;const ctx={workerBusy:false,workerVersion:0,api:()=>new Promise(done=>resolve=done),showWorker:()=>{throw Error('Obsolete health rendered');}};vm.createContext(ctx);vm.runInContext(section('async function refreshWorker','function workerStartPayload'),ctx);const pending=ctx.refreshWorker();ctx.workerVersion++;resolve({state:'running',live:false});assert.equal(await pending,false);
 const accountNode={disabled:false};const controls=[{disabled:false},{disabled:true}];const nodes={account:accountNode,'worker-form':{querySelectorAll:()=>controls},'worker-stop':{disabled:false},'worker-refresh':{disabled:false}};
 let finish,calls=0;const mut={workerBusy:false,busy:false,workerVersion:0,workerState:{accountId:'paper-1'},$:id=>nodes[id],api:()=>{calls++;return new Promise(done=>finish=done);},run:async action=>action(),showWorker:()=>{},refreshPaper:async()=>{},renderWorkerSelection:()=>{},currentAccount:()=>account};
 vm.createContext(mut);vm.runInContext(section('async function workerMutation',"$('worker-form').onsubmit"),mut);const first=mut.workerMutation('/api/paper-worker/start',{});assert.equal(accountNode.disabled,true);assert.equal(controls[0].disabled,true);assert.equal(await mut.workerMutation('/api/paper-worker/start',{}),false);assert.equal(calls,1);finish({state:'running',live:false});await first;assert.equal(accountNode.disabled,false);assert.equal(controls[0].disabled,false);assert.equal(controls[1].disabled,true);
 console.log('PASS: worker opt-in, mapping payload, stale health and mutation guards');
})().catch(error=>{console.error(error);process.exitCode=1;});
