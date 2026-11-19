const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js','utf8');
const section = source.slice(source.indexOf('let orderRevision = 0;'), source.indexOf("$('#confirm-text').addEventListener"));
const handlers = {}, elements = {};
const pending = [], reviews = [];
const context = {
  pendingOrder: {old:true}, orderValues:()=>({symbol:'DEMO'}),
  $: id => elements[id] ||= {addEventListener:(name, fn)=>{handlers[id+':'+name]=fn;}},
  api:()=>new Promise(resolve=>pending.push(resolve)),
  showReview:(...args)=>reviews.push(args),showToast:()=>{},
};
vm.createContext(context); vm.runInContext(section,context);
(async()=>{
  const submit = ()=>handlers['#order-form:submit']({preventDefault(){}});
  const first=submit();
  handlers['#order-form:input']({target:{name:'quantity'}});
  pending.shift()({order:{symbol:'OLD'},confirmationId:'old'}); await first;
  assert.equal(reviews.length,0,'editing during preview must discard stale response');
  assert.equal(context.pendingOrder,null);
  assert.equal(elements['#place-order-button'].disabled,true);
  const approved=submit();
  handlers['#order-form:input']({target:{id:'confirm-text'}});
  pending.shift()({order:{symbol:'DEMO'},confirmationId:'unchanged'}); await approved;
  assert.equal(reviews.length,1,'confirmation text must not invalidate order fields');
  reviews.length=0;
  const older=submit(),newer=submit();
  pending.pop()({order:{symbol:'NEW'},confirmationId:'new'}); await newer;
  pending.shift()({order:{symbol:'OLD'},confirmationId:'old'}); await older;
  assert.equal(reviews.length,1,'only latest requested preview may be rendered');
  assert.equal(reviews[0][1],'new');
  console.log('PASS: stale edited and overlapping order previews are discarded');
})().catch(e=>{console.error(e);process.exitCode=1;});
// Broker text is untrusted; recovery table must escape it and retain uncertainty.
const renderStart=source.indexOf('function renderExecutionJournal(');
const renderEnd=source.indexOf('async function loadExecutionJournal(',renderStart);
const display={};
const renderContext={
  $:id=>display[id]||=( {} ),
  safe:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))
};
vm.createContext(renderContext);vm.runInContext(source.slice(renderStart,renderEnd),renderContext);
renderContext.renderExecutionJournal({positionsReconciled:false,intents:[{order:{exchange:'NSE',tradingsymbol:'<img src=x>',product:'CNC',transaction_type:'BUY',quantity:5},filledQuantity:2,state:'PARTIAL',reason:'<script>bad()</script>'}]});
assert.match(display['#execution-status'].textContent,/1 unresolved.*Positions reconciled: no/);
assert.ok(!display['#execution-rows'].innerHTML.includes('<script>'));
assert.match(display['#execution-rows'].innerHTML,/&lt;img/);
console.log('PASS: recovery display escapes broker text and preserves partial exposure status');
