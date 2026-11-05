const $=s=>document.querySelector(s);
const catalog={
scanner:['Chart Scanner','Scan imported five-minute candles for opening-range breakouts, flag heuristics and oversold bounces.','Batch limit: 2,000 symbols / 100,000 bars. No continuous universe feed connected.'],
news:['News Monitor','Filter imported news records by your watchlist and inspect event keywords.','Live feed disconnected. Headlines cannot prove why a stock moved.'],
entry:['Entry Timer','Evaluate the latest completed setup bar against explicit scanner rules.','Snapshot evaluation only. It does not promise the best entry or place an order.'],
exit:['Exit Planner','Review your chosen entry, stop and target before considering an order.','You choose price levels. Stops cannot guarantee a maximum loss. Long-only calculations.'],
timemachine:['Time Machine','Sample 10,000 bootstrap paths and enumerate past setup matches in your imported history.','Sampled scenarios are not every possible outcome or a forecast. Historical replay is in-sample.'],
risk:['Risk Manager','Check a planned trade against your capital, pending exposure and loss limits.','Uses your entered snapshot, not broker-reconciled exposure. It gates paper drafts only.'],
budget:['Budget Manager','Calculate whole-unit position size from budget and modeled stop loss.','Includes user-entered costs and slippage. Taxes and gap risk are not fully modeled.'],
broker:['Order Executor','Review a risk-checked paper order and approve it explicitly.','Paper only here. Live submission remains in the existing manual order screen.'],
alerts:['Price Alerts','Check a threshold or monitor your existing private Kite stream while this page is open.','No closed-tab delivery. Stale streams are rejected; no automatic exits.'],
analyst:['Earnings Analyst','Compare imported filing metrics, reporting periods and source evidence.','Structured JSON import; automatic PDF reading and filing ingestion are not connected.'],
pelosi:['Congress Disclosure Tracker','Inspect imported U.S. congressional transaction disclosures and filing delays.','No live filing monitor. Filing time differs from trade time; this is separate from Indian market trading.']};
const tool=location.pathname.replace('/trader-','');
const meta=catalog[tool]||catalog.scanner;
$('#tool-title').textContent=meta[0];document.title=meta[0]+' · TradeLab';$('#tool-description').textContent=meta[1];$('#tool-limit').textContent=meta[2];$('#tool-type').textContent='IMPORT-FIRST WORKSPACE / '+tool.toUpperCase();
for(const [key,value] of Object.entries(catalog)){const a=document.createElement('a');a.href='/trader-'+key;a.textContent=value[0];a.className=key===tool?'active':'';if(key===tool)a.setAttribute('aria-current','page');$('#tools').append(a);}
const priceTools=['exit','budget','risk','broker','timemachine'];
const evaluationLink=document.createElement('a');
evaluationLink.href='/trader-evaluate';evaluationLink.textContent='Strategy evaluation';$('#tools').append(evaluationLink);
if(tool==='news'){
  const sources=document.createElement('p');
  sources.append('Research links: ');
  for(const [name,url] of [
    ['NSE filings','https://www.nseindia.com/companies-listing/corporate-filings-announcements'],
    ['Moneycontrol','https://www.moneycontrol.com/news/business/markets/'],
    ['ET Markets','https://economictimes.indiatimes.com/markets'],
    ['Business Standard','https://www.business-standard.com/markets']
  ]){
    const link=document.createElement('a');link.textContent=name;link.href=url;link.target='_blank';link.rel='noopener noreferrer';sources.append(link,' · ');
  }
  sources.append('For manual research. No publisher feed is connected.');$('#tool-limit').after(sources);
}
const fields=[];
if(['scanner','entry','timemachine'].includes(tool))fields.push(['asOf','Analysis cutoff · ISO timestamp','text']);
if(priceTools.includes(tool))fields.push(['entry','Entry price','number'],['stop','Stop price','number'],['target','Target price','number'],['budget','Allocated budget','number'],['maxLoss','Maximum modeled loss per trade','number'],['costBps','Costs per side · basis points','number'],['slippageBps','Slippage per side · basis points','number']);
if(['risk','broker'].includes(tool))fields.push(['exposure','Existing exposure','number'],['pendingExposure','Pending exposure','number'],['maxExposure','Maximum total exposure','number'],['dailyLoss','Loss incurred today','number'],['dailyLossLimit','Daily loss threshold','number']);
if(tool==='broker')fields.unshift(['symbol','Trading symbol','text']);
if(tool==='news')fields.push(['watchlist','Watchlist · exact symbols, comma separated','text']);
if(tool==='news')fields.push(['asOf','Show news available by · ISO timestamp','text']);
if(tool==='timemachine')fields.push(['horizon','Horizon · 1–100 bars','number']);
if(tool==='alerts')fields.push(['price','Observed price for manual check','number'],['threshold','Alert threshold','number']);
for(const [key,label,type] of fields){const l=document.createElement('label');l.textContent=label;const input=document.createElement('input');input.name=key;input.type=type;input.required=true;if(type==='number'){input.step='any';input.min='0';}l.append(input);$('#tool-fields').append(l);}
if(tool==='alerts'){$('#tool-fields').insertAdjacentHTML('beforeend','<label>Trigger direction<select name="direction"><option value="above">At or above</option><option value="below">At or below</option></select></label>');$('#alert-controls').hidden=false;}
const imported=['scanner','entry','timemachine','news','analyst','pelosi'].includes(tool);$('#import-panel').hidden=!imported;
if(tool==='news')$('#tool-form').elements.asOf.value=new Date().toISOString();
let sample=false,draft=null,watchTimer=null,watchBusy=false,triggered=false;
async function api(path,body){const response=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-CSRF-Token':$('meta[name="csrf-token"]').content}:{},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(30000)});const result=await response.json();if(!response.ok)throw Error(result.error||'Request failed');return result;}
function inputs(){const data=Object.fromEntries(new FormData($('#tool-form')));if(imported){const parsed=JSON.parse($('#records').value);if(['scanner','entry','timemachine'].includes(tool))data.candles=parsed;else data.records=parsed;data.permitted=$('#permitted').checked;}return data;}
function invalidate(){draft=null;$('#approval').hidden=true;}
$('#tool-form').addEventListener('input',invalidate);
$('#records').addEventListener('input',()=>{sample=false;$('#source-label').textContent='User-supplied data; provenance not independently verified.';});
$('#tool-form').addEventListener('submit',async e=>{e.preventDefault();invalidate();$('#run').disabled=true;$('#message').textContent='Running…';try{const data=inputs();const result=await api('/api/trader/'+tool,data);$('#result').textContent=JSON.stringify(result,null,2);$('#source-label').textContent=sample?'SYNTHETIC EXAMPLE — not real market or filing evidence.':'User-supplied inputs; no live feed assumed.';$('#summary').textContent=result.status|| (result.allowed===false?'Blocked by risk limits':result.quantity!==undefined?'Calculated units: '+result.quantity:'Analysis complete');if(result.draftId){draft=result.draftId;$('#approval').hidden=false;$('#confirmation').value='';}$('#message').textContent='Complete. Review assumptions and limitations below.';}catch(e){$('#message').textContent=e.message;$('#result').textContent='No successful result for this request.';}finally{$('#run').disabled=false;}});
$('#approve').addEventListener('click',async()=>{if(!draft)return;$('#approve').disabled=true;try{const result=await api('/api/trader/approve',{draftId:draft,confirm:$('#confirmation').value});$('#result').textContent=JSON.stringify(result,null,2);invalidate();$('#message').textContent='Paper order recorded. No broker order submitted.';}catch(e){$('#message').textContent=e.message;}finally{$('#approve').disabled=false;}});
$('#import-file').addEventListener('change',async e=>{const file=e.target.files[0];if(!file)return;if(file.size>7500000){$('#message').textContent='Import limit is 7.5 MB.';return;}try{const text=await file.text();JSON.parse(text);$('#records').value=text;sample=false;invalidate();$('#source-label').textContent='Imported '+file.name+'; not independently verified.';}catch(e){$('#message').textContent='Invalid JSON import: '+e.message;}});
$('#sample').addEventListener('click',()=>{
  let example;
  if(['scanner','entry','timemachine'].includes(tool)){let price=100;const rows=[];const start=Date.parse('2026-10-01T09:15:00+05:30');for(let i=0;i<60;i++){const open=price;price*=1+(i%9<5?.004:-.003);rows.push({date:new Date(start+i*300000).toISOString(),open,high:Math.max(open,price)*1.001,low:Math.min(open,price)*.999,close:price,volume:10000});}example={SYNTHETIC:rows};$('#tool-form').elements.asOf.value='2026-10-01T15:30:00+05:30';}
  else if(tool==='news'){example=[{title:'Synthetic earnings announcement',symbols:['DEMO'],publishedAt:'2026-10-01T10:00:00+05:30',url:'https://example.invalid/synthetic-news'}];$('#tool-form').elements.watchlist.value='DEMO';$('#tool-form').elements.asOf.value='2026-10-01T10:01:00+05:30';}
  else if(tool==='analyst')example=[{metric:'Synthetic revenue',unit:'INR million',period:'Synthetic Q2',priorPeriod:'Synthetic prior Q2',current:110,previous:100,source:'https://example.invalid/synthetic-report',publishedAt:'2026-10-01T10:00:00+05:30'}];
  else example=[{filingId:'SYNTHETIC-1',filer:'Synthetic Member',owner:'Self',asset:'Synthetic asset',transactionDate:'2026-09-01',filedAt:'2026-10-01T10:00:00-04:00',amountRange:'Synthetic range only',source:'https://example.invalid/synthetic-disclosure'}];
  $('#records').value=JSON.stringify(example,null,2);sample=true;$('#permitted').checked=true;invalidate();$('#source-label').textContent='SYNTHETIC EXAMPLE — invented fixtures, no real stocks, reports or disclosures.';
});
const workflow={scanner:'entry',entry:'exit',exit:'budget',budget:'risk',risk:'broker'};
$('#next').hidden=!workflow[tool];$('#next').addEventListener('click',()=>{const data=Object.fromEntries(new FormData($('#tool-form')));sessionStorage.setItem('trader-plan',JSON.stringify(data));location.assign('/trader-'+workflow[tool]);});
try{const saved=JSON.parse(sessionStorage.getItem('trader-plan')||'{}');for(const [k,v] of Object.entries(saved)){const input=$('#tool-form').elements.namedItem(k);if(input)input.value=v;}}catch{}
function stopWatch(){clearInterval(watchTimer);watchTimer=null;$('#watch').disabled=false;}
async function watchTick(){if(watchBusy)return;watchBusy=true;try{const data=await api('/api/market/stream');const age=data.lastTick?(Date.now()-Date.parse(data.lastTick))/1000:Infinity;const last=data.points?.at(-1);if(data.state!=='connected'||!last||age>15){$('#watch-status').textContent='No fresh connected stream. No alert evaluated.';return;}const threshold=Number($('#tool-form').elements.threshold.value);if(!Number.isFinite(threshold)||threshold<=0)throw Error('Enter a positive threshold.');const direction=$('#tool-form').elements.direction.value;const hit=direction==='above'?last.close>=threshold:last.close<=threshold;$('#watch-status').textContent=data.symbol+' · '+last.close+' · '+Math.round(age)+'s old · '+(hit?'THRESHOLD HIT':'Watching');if(hit&&!triggered&&$('#sound').checked){const audio=new AudioContext();const tone=audio.createOscillator();tone.connect(audio.destination);tone.start();tone.stop(audio.currentTime+.15);tone.onended=()=>audio.close();}triggered=hit;}catch(e){$('#watch-status').textContent=e.message;stopWatch();}finally{watchBusy=false;}}
$('#watch').addEventListener('click',()=>{triggered=false;stopWatch();$('#watch').disabled=true;watchTimer=setInterval(watchTick,1500);watchTick();});$('#stop-watch').addEventListener('click',()=>{stopWatch();$('#watch-status').textContent='Watching stopped.';});

if(tool==='entry'){
  const controls=document.createElement('div');
  const start=document.createElement('button');start.type='button';start.textContent='Replay from first completed bar';
  const step=document.createElement('button');step.type='button';step.textContent='Advance one completed bar';
  async function replay(reset){try{const data=inputs();const dates=[...new Set(Object.values(data.candles).flat().map(r=>Date.parse(r.date)+300000))].sort((a,b)=>a-b);const current=Date.parse(data.asOf);const next=reset?dates[0]:dates.find(x=>x>current);if(!Number.isFinite(next))throw Error('No later completed bar in this import.');$('#tool-form').elements.asOf.value=new Date(next).toISOString();data.asOf=new Date(next).toISOString();const result=await api('/api/trader/entry',data);$('#result').textContent=JSON.stringify(result,null,2);$('#message').textContent='Replay cutoff: '+data.asOf+' · no orders submitted.';}catch(e){$('#message').textContent=e.message;}}
  start.addEventListener('click',()=>replay(true));step.addEventListener('click',()=>replay(false));controls.append(start,step);$('#tool-form').append(controls);
}
if(tool==='alerts'){
  const l=document.createElement('label');l.textContent='Optional bell reminder · choose date and time in your browser timezone (no exchange-calendar verification)';
  const input=document.createElement('input');input.type='datetime-local';input.id='bell-time';l.append(input);$('#alert-controls').append(l);
  const button=document.createElement('button');button.textContent='Arm this bell reminder';$('#alert-controls').append(button);
  let bellTimer=null;
  button.addEventListener('click',()=>{clearInterval(bellTimer);const when=Date.parse(input.value);if(!Number.isFinite(when)||when<=Date.now()){ $('#watch-status').textContent='Choose a future date and time.';return;}$('#watch-status').textContent='Bell reminder armed for '+new Date(when).toLocaleString()+'. Keep this page open.';bellTimer=setInterval(()=>{if(Date.now()<when)return;clearInterval(bellTimer);$('#watch-status').textContent='BELL REMINDER — your scheduled time has arrived.';if($('#sound').checked){const a=new AudioContext(),o=a.createOscillator();o.connect(a.destination);o.start();o.stop(a.currentTime+.2);o.onended=()=>a.close();}},1000);});
  $('#stop-watch').addEventListener('click',()=>clearInterval(bellTimer));
}
