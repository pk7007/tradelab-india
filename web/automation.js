const autoFields=[['units','UNITS PER ENTRY'],['capital','ALLOCATED CAPITAL · ₹'],['maxExposure','TOTAL EXPOSURE LIMIT · ₹'],['maxPositionValue','POSITION VALUE LIMIT · ₹'],['maxPositions','MAXIMUM POSITIONS'],['dailyLoss','DAILY LOSS THRESHOLD · ₹'],['ordersPerMinute','ORDER LIMIT PER MINUTE'],['fast','FAST AVERAGE · BARS'],['slow','SLOW AVERAGE · BARS']];
$('#auto-fields').innerHTML=autoFields.map(([name,label])=>`<label class="field"><span>${label}</span><input name="${name}" type="number" min="1" step="${['capital','maxExposure','maxPositionValue','dailyLoss'].includes(name)?'.01':'1'}" placeholder="Your limit" required></label>`).join('');
function renderAutomation(s,fill=false){
  $('#engine-state').textContent=s.state.toUpperCase();
  $('#auto-version').textContent=s.version?'v'+s.version+' · unapproved':'Not configured';
  $('#auto-reconciled').textContent=s.reconciled?'Mock state matched':'Required';
  $('#auto-count').textContent=s.intents.length;
  $('#auto-blockers').innerHTML=s.blockers.map(x=>`<li>${safe(x)}</li>`).join('');
  $('#auto-intents').innerHTML=s.intents.length?s.intents.map(x=>`<tr><td>${safe(x.id)}</td><td>${safe(x.symbol)}</td><td>${safe(x.side)}</td><td>${x.quantity}</td><td>${x.filled}</td><td>${safe(x.state)}</td></tr>`).join(''):'<tr><td colspan="6">No intents recorded. Saving a strategy does not create orders.</td></tr>';
  $('#auto-events').innerHTML=s.events.map(x=>`<article><time>${safe(new Date(x.at).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'}))} IST</time><div><strong>${safe(x.event)}</strong><p>${safe(x.detail)}</p></div></article>`).join('');
  if(fill&&s.config)Object.entries(s.config).forEach(([k,v])=>{const field=$('#auto-config').elements.namedItem(k);if(field)field.value=Array.isArray(v)?v.join(','):v;});
}
async function loadAutomation(fill=false){try{renderAutomation(await api('/api/automation'),fill);}catch(e){$('#auto-message').textContent=e.message;}}
$('#auto-config').addEventListener('submit',async e=>{e.preventDefault();try{const body=Object.fromEntries(new FormData(e.target));const s=await api('/api/automation/config',{method:'POST',body:JSON.stringify(body)});renderAutomation(s);$('#auto-message').textContent='Version '+s.version+' saved. Awaiting review; live automation remains disabled.';}catch(e){$('#auto-message').textContent=e.message;}});
for(const action of ['start','pause','stop'])$('#auto-'+action).addEventListener('click',async()=>{try{const s=await api('/api/automation/'+action,{method:'POST',body:'{}'});renderAutomation(s);$('#auto-message').textContent=action==='start'?'Start blocked: complete production readiness and approve the exact configuration first.':'Engine '+s.state+'. Broker orders and positions were not changed.';}catch(e){$('#auto-message').textContent=e.message;}});
$('#auto-refresh').addEventListener('click',()=>loadAutomation());
loadAutomation(true);
