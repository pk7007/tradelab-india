'use strict';
const $=id=>document.getElementById(id);
const money=value=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(value);
function formatDisplayTime(value, now = new Date()) {
  if (typeof value !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/i.test(value)) return 'Time unavailable';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return 'Time unavailable';
  const day = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit'});
  const time = new Intl.DateTimeFormat('en-IN', {timeZone: 'Asia/Kolkata', hour: 'numeric', minute: '2-digit', hour12: true})
    .format(date).replace(/\s+/g, ' ').toUpperCase();
  const dateKey = day.format(date);
  const label = dateKey === day.format(now) ? 'Today'
    : dateKey === day.format(new Date(now.getTime() - 86400000)) ? 'Yesterday'
    : new Intl.DateTimeFormat('en-IN', {timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', year: 'numeric'}).format(date);
  return label + ', ' + time + ' IST';
}
function groupNews(items, source = '', query = '', kind = 'all') {
  const term = query.trim().toUpperCase();
  const groups = new Map();
  for (const item of items) {
    try { const url = new URL(item.url); if (url.protocol !== 'https:' || url.username || url.password) continue; } catch { continue; }
    if (source && item.source !== source) continue;
    if (kind === 'filings' && (item.source !== 'nse' || !item.filings?.length)) continue;
    const mapped = (item.symbols || []).includes(term);
    if (term && !mapped && !((item.title || '') + ' ' + (item.description || '')).toUpperCase().includes(term)) continue;
    const key = ['moneycontrol', 'nse'].includes(item.source) ? item.id
      : item.storyKey || String(item.title || item.url || item.id || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
    if (!groups.has(key)) groups.set(key, {key, items: [], relevance: term ? (mapped ? 'Mapped stock match' : 'Keyword match; stock mapping unverified') : ''});
    if (term && mapped) groups.get(key).relevance = 'Mapped stock match';
    groups.get(key).items.push(item);
  }
  return [...groups.values()].map(group => ({...group,
    items: group.items.sort((a, b) => (Date.parse(b.publishedAt) || 0) - (Date.parse(a.publishedAt) || 0))}))
    .sort((a, b) => (Date.parse(b.items[0].publishedAt) || 0) - (Date.parse(a.items[0].publishedAt) || 0));
}
let settings=null, paper={accounts:[],events:[]}, busy=false, researchVersion=0, paperVersion=0;
function text(tag,value,className){const el=document.createElement(tag);el.textContent=String(value??'');if(className)el.className=className;return el;}
async function api(path,body){const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(30000)});let result;try{result=await response.json();}catch{throw Error('The server returned an unreadable response. Refresh or check the connection.');}if(!response.ok)throw Error(result.error||'Request failed.');return result;}
async function run(action){if(busy)return;busy=true;$('message').textContent='Working…';try{const current=await action();$('message').textContent=current===false?'Inputs changed while the request was running. Re-evaluate the current inputs.':'Complete. Review the current state below.';}catch(error){$('message').textContent=error.message;}finally{busy=false;}}
function activate(){ $('auto').hidden=false; }
let brokerConnected = null;
let brokerConnecting = false;
function renderBrokerConnection(connected) {
  brokerConnected = connected;
  const button = $('zerodha-connect');
  button.textContent = connected ? 'Zerodha connected' : 'Connect Zerodha';
  button.disabled = brokerConnecting || connected === true;
  button.title = connected ? 'This browser has a Zerodha session.' : 'Sign in securely with Zerodha.';
}
async function connectZerodha() {
  const button = $('zerodha-connect');
  if (button.disabled) return;
  brokerConnecting = true;
  button.disabled = true;
  $('message').textContent = 'Opening Zerodha sign-in…';
  try {
    const result = await api('/api/connect', {});
    const destination = new URL(result.url);
    if (destination.origin !== 'https://kite.zerodha.com' || destination.pathname !== '/connect/login') {
      throw Error('The server returned an unexpected sign-in address. Check your connection settings.');
    }
    window.location.assign(destination.href);
  } catch (error) {
    $('message').textContent = error.message;
    brokerConnecting = false;
    renderBrokerConnection(brokerConnected);
  }
}
$('zerodha-connect').onclick = connectZerodha;
$('settings-toggle').onclick=()=>{const open=$('settings').hidden;$('settings').hidden=!open;$('settings-toggle').setAttribute('aria-expanded',String(open));};
function showSettings(value){if(settings&&settings.revision!==value.revision){researchVersion++;$('candidates').replaceChildren(text('p','Limits changed. Re-evaluate the snapshot before using previous sizing.'));$('research-note').textContent='Previous research sizing invalidated.';}settings=value;for(const key of ['capital','maxLoss','dailyLossLimit'])$('limits').elements[key].value=value[key];$('limit-summary').replaceChildren();for(const [label,key] of [['Capital','capital'],['Planned loss / trade','maxLoss'],['Daily loss threshold','dailyLossLimit']]){const item=text('div','');item.append(text('span',label),text('strong',money(value[key])));$('limit-summary').append(item);}}
$('limits').onsubmit=event=>{event.preventDefault();run(async()=>{const values=Object.fromEntries(new FormData(event.target));const result=await api('/api/portal/settings',values);showSettings(result.settings||result);});};
function candidateCard(candidate){const card=text('article','','empty candidate');card.append(text('p',(candidate.exchange||'NSE')+' · '+candidate.symbol,'eyebrow'),text('h3',candidate.symbol),text('p',candidate.reason||candidate.setup||candidate.status||'Imported research candidate'));
 const details=document.createElement('details');details.append(text('summary','Why this stock?'));const summary=candidate.plan||candidate.risk||candidate;const dl=document.createElement('dl');for(const [label,key,format] of [['Whole shares','quantity',String],['Estimated capital','estimatedCapital',money],['Planned stop loss','estimatedStopLoss',money],['Entry','entry',money],['Stop','stop',money],['Target assumption','target',money]])if(summary[key]!==undefined){dl.append(text('dt',label),text('dd',format(summary[key])));}details.append(dl);for(const [key,label] of [['observationAt','Observed'],['bar','Completed bar'],['dataThrough','Data through'],['setups','Setup'],['entryCondition','Entry condition'],['evidence','Evidence'],['missing','Missing'],['limitations','Limitations'],['blockers','Blocked when']])if(candidate[key])details.append(text('p',label+': '+(Array.isArray(candidate[key])?candidate[key].join('; '):candidate[key])));
 for(const article of candidate.news||[]){const row=text('div','','history-item');try{const url=new URL(article.url);if(url.protocol==='https:'&&!url.username&&!url.password){const link=text('a',article.title);link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';row.append(link);}}catch{}row.append(text('small','Published: '+article.publishedAt+' · Available: '+article.availableAt+' · '+article.freshness));details.append(row);}if(!candidate.news?.length)details.append(text('p','No matching imported news evidence.'));
 details.append(text('p','Imported snapshot, not a live signal. Ranking is descriptive and has no validated probability of profit. News coverage and executable liquidity are unverified.','muted'));card.append(details);return card;}
$('research-form').onsubmit=event=>{event.preventDefault();run(async()=>{const version=researchVersion;const input=JSON.parse($('research-input').value);const result=await api('/api/portal/research',{...input,horizon:'intraday',permitted:$('research-permitted').checked});if(version!==researchVersion)return false;$('candidates').replaceChildren();for(const candidate of result.candidates||[])$('candidates').append(candidateCard(candidate));if(!result.candidates?.length){const empty=text('article','','empty');empty.append(text('h3','No qualifying trade'),text('p',result.status||'No setup meets the supplied evidence and limits.'));$('candidates').append(empty);}$('research-note').textContent=(result.excluded||[]).map(item=>item.symbol+': '+(item.reason||item.reasons?.join('; ')||'Excluded')).join(' · ');});};
function invalidateResearch(){researchVersion++;$('candidates').replaceChildren(text('p','Research inputs changed. Evaluate the current snapshot to calculate candidates.'));$('research-note').textContent='Previous results invalidated.';}
$('research-form').addEventListener('input',invalidateResearch);
$('limits').addEventListener('input',invalidateResearch);
function paperModelDescription(config){return config.strategy==='intraday-v1'?'Intraday v1 uses a planned loss allowance of '+money(config.maxLoss)+', simulated stop/target exits and '+config.squareOff+' IST square-off. Partial or unavailable fills can leave exposure open.':'The portal per-trade planning limit is not enforced by this legacy SMA engine; protective stops are unavailable.';}
function entryState(account){return account.status!=='running'?'processing stopped':account.recoveryRequired?'recovery blocked':account.riskHalted?'daily loss blocked':account.entriesPaused?'paused':'subject to checks';}
function currentAccount(){return paper.accounts.find(account=>account.id===$('account').value);}
function showPaper(){const account=currentAccount();renderWorkerSelection(account);$('metrics').replaceChildren();for(const button of document.querySelectorAll('[data-action]'))button.disabled=!account;
 if(!account){$('account-note').textContent='No paper accounts yet. Open Setup, imports & diagnostics below to create one with explicit assumptions.';$('account-status').textContent='Not configured';$('exposure').textContent='No account selected.';$('history').textContent='No trades recorded in this workspace.';return;}
 renderAccountHealth(account);
 const unrealized=account.equity-account.cash-account.basis;for(const [label,value] of [['Cash',money(account.cash)],['Marked equity',money(account.equity)],['Realized P&L',money(account.realized)],['Unrealized P&L',money(unrealized)],['Shares held',String(account.quantity)],['Costs paid',money(account.fees)],['Daily loss used',money(account.dayLoss)+' / '+money(account.config.dailyLossLimit)],['Remaining daily allowance',money(Math.max(0,account.config.dailyLossLimit-account.dayLoss))],['Stop / target',account.protection?money(account.protection.stop)+' / '+money(account.protection.target):'None active'],['Pending order',account.pending?.side||'None']]){const metric=text('div','','metric');metric.append(text('small',label),text('strong',value));$('metrics').append(metric);}
 $('exposure').textContent=(account.quantity?'Exposure remains open: '+account.quantity+' simulated shares. ':'No open simulated shares. ')+(account.pending?'Pending '+account.pending.side+' waits for an accepted candle. ':'')+'This account uses '+money(account.config.capital)+' starting cash and '+money(account.config.dailyLossLimit)+' daily loss threshold. '+paperModelDescription(account.config)+(account.recoveryRequired?' Recovery required: carried exposure blocks new entries.':'');
 $('history').replaceChildren();const events=paper.events.filter(event=>event.account===account.id&&event.type!=='bar');for(const event of events){const row=text('div','','history-item');const detail=event.detail||event.reason||(event.side?event.side+' '+(event.quantity??'')+(Number.isFinite(event.price)?' @ '+money(event.price):''):'Configuration recorded');row.append(text('strong',event.type.replaceAll('_',' ')),text('div',detail),text('small',formatDisplayTime(event.at)));$('history').append(row);}if(!events.length)$('history').append(text('p','No recent fills or decisions.'));
}
async function refreshPaper(){const version=++paperVersion;const result=await api('/api/trader/paper-state',{});if(version!==paperVersion)return false;const selected=$('account').value;paper=result;$('account').replaceChildren();if(!paper.accounts.length){const option=text('option','No accounts configured');option.value='';$('account').append(option);}for(const account of paper.accounts){const option=text('option',account.config.symbol+' · '+account.config.source+' · '+account.id.slice(0,8));option.value=account.id;$('account').append(option);}if(paper.accounts.some(account=>account.id===selected))$('account').value=selected;showPaper();}
$('account').onchange=()=>{showPaper();if(typeof refreshSelection==='function')refreshSelection();};$('refresh-paper').onclick=()=>run(async()=>{await refreshPaper();if(typeof refreshSelection==='function')await refreshSelection();});
for(const button of document.querySelectorAll('[data-action]'))button.onclick=()=>run(async()=>{const account=currentAccount();if(!account)throw Error('Select a paper account first.');await api('/api/trader/paper-control',{id:account.id,action:button.dataset.action});await refreshPaper();});
async function load(){activate();try{const portal=await api('/api/portal');showSettings(portal.settings);}catch(error){$('message').textContent=error.message;}try{const status=await api('/api/status');renderBrokerConnection(status.connected);$('connection').textContent=(status.connected?'Broker session connected.':'Broker session disconnected.')+' Live execution remains locked; authentication alone does not establish readiness.';}catch{$('connection').textContent='Broker status unavailable. Open advanced connection settings.';}try{await refreshPaper();}catch(error){$('account-note').textContent=error.message;$('account-status').textContent='Unable to load';}}
load();

// News presentation uses IST; publication and collection times stay distinct.
const announcementPanel = text('details', '', 'panel');
announcementPanel.append(text('summary', 'Market news'));
const announcementState = text('p', 'Checking news…');
const announcementRefresh = text('button', 'Refresh news');
announcementRefresh.type = 'button';
const announcementSources = text('details', '', 'news-source-details');
announcementSources.append(text('summary', 'Source health and update times'));
const announcementSourceItems = text('div', '');
announcementSources.append(announcementSourceItems);
const announcementItems = text('div', '', 'history');
const newsFilters = text('div', '', 'news-filters');
const sourceLabel = text('label', 'News source');
const newsSourceFilter = document.createElement('select');
newsSourceFilter.id = 'news-source-filter';
sourceLabel.append(newsSourceFilter);
const searchLabel = text('label', 'Stock or keyword');
const newsSearch = document.createElement('input');
newsSearch.id = 'news-search'; newsSearch.type = 'search'; newsSearch.placeholder = 'For example, TCS or earnings';
searchLabel.append(newsSearch);
const kindLabel = text('label', 'News type');
const newsKindFilter = document.createElement('select'); newsKindFilter.id = 'news-kind-filter';
for (const [value, label] of [['all', 'All news'], ['filings', 'NSE filings']]) {
  const option = text('option', label); option.value = value; newsKindFilter.append(option);
}
kindLabel.append(newsKindFilter); newsFilters.append(sourceLabel, searchLabel, kindLabel);
const newsCount = text('p', '', 'muted');
const newsMore = text('button', 'More headlines'); newsMore.type = 'button'; newsMore.hidden = true;
let newsSnapshot = null, newsVisible = 20;
announcementPanel.append(announcementState, announcementRefresh, newsFilters, newsCount, announcementSources, announcementItems, newsMore);
$('auto').append(announcementPanel);
let announcementBusy = false;
function renderNewsItems(result) {
    const selectedSource = newsSourceFilter.value;
    const sources = new Map((result.sources || []).map(source => [source.source, source.name || source.source]));
    for (const item of result.items || []) if (!sources.has(item.source)) sources.set(item.source, item.sourceName || item.source);
    newsSourceFilter.replaceChildren();
    const all = text('option', 'All sources'); all.value = ''; newsSourceFilter.append(all);
    for (const [value, name] of sources) { const option = text('option', name); option.value = value; newsSourceFilter.append(option); }
    newsSourceFilter.value = sources.has(selectedSource) ? selectedSource : '';
    const groups = groupNews(result.items || [], newsSourceFilter.value, newsSearch.value, newsKindFilter.value);
    newsCount.textContent = groups.length + ' matching stories';
    const openItems = new Set([...announcementItems.querySelectorAll('details[open]')].map(detail => detail.dataset.newsId));
    const focusedItem = document.activeElement?.closest('[data-news-id]');
    const focusInsideNews = announcementItems.contains(document.activeElement);
    const focusId = focusedItem?.dataset.newsId;
    const focusedTag = document.activeElement?.tagName;
    let restoredFocus = false;
    announcementItems.replaceChildren();
    let displayed = 0;
    for (const group of groups.slice(0, newsVisible)) {
      const item = group.items[0];
      let url;
      try { url = new URL(item.url); } catch { continue; }
      if (url.protocol !== 'https:' || url.username || url.password) continue;
      const row = text('article', '', 'history-item'); row.dataset.newsId = group.key;
      const link = text('a', item.title); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
      row.append(link);
      const publisher = item.publisher || item.sourceName || item.source;
      if (publisher) row.append(text('small', publisher));
      if (item.description) row.append(text('p', item.description));
      row.append(text('small', 'Published ' + formatDisplayTime(item.publishedAt)));
      if (group.relevance) row.append(text('small', group.relevance));
      for (const filing of item.source === 'nse' ? (item.filings || []) : []) {
        try {
          const documentUrl = new URL(filing.url);
          if (documentUrl.protocol !== 'https:' || documentUrl.username || documentUrl.password
              || (documentUrl.port && documentUrl.port !== '443')
              || !['nsearchives.nseindia.com', 'archives.nseindia.com', 'www.nseindia.com', 'www.nseindia.in'].includes(documentUrl.hostname)
              || !documentUrl.pathname.toLowerCase().endsWith('.pdf')) continue;
          const documentLink = text('a', 'Open NSE filing - PDF');
          documentLink.href = documentUrl.href; documentLink.target = '_blank'; documentLink.rel = 'noopener noreferrer';
          row.append(text('p', filing.documentType + ' - Original exchange filing'), documentLink);
        } catch {}
      }
      const details = text('details', '', 'news-item-details'); details.dataset.newsId = group.key;
      details.open = openItems.has(group.key);
      details.append(text('summary', 'Research details' + (group.items.length > 1 ? ' · ' + group.items.length + ' related items' : '')),
        text('p', 'Available for research ' + formatDisplayTime(item.availableAt)), text('p', item.mapping || 'Stock mapping unavailable'));
      if (item.categories?.length) details.append(text('p', item.categories.join(' · ')));
      for (const related of group.items.slice(1)) {
        try {
          const address = new URL(related.url);
          if (address.protocol !== 'https:' || address.username || address.password) continue;
          const coverage = text('a', (related.publisher || related.sourceName || related.source) + ' · ' + formatDisplayTime(related.publishedAt));
          coverage.href = address.href; coverage.target = '_blank'; coverage.rel = 'noopener noreferrer'; details.append(coverage);
        } catch {}
      }
      row.append(details); announcementItems.append(row);
      if (focusInsideNews && focusId === group.key) {
        (focusedTag === 'A' ? link : details.querySelector('summary')).focus({preventScroll: true}); restoredFocus = true;
      }
      displayed++;
    }
    if (!displayed) announcementItems.append(text('p', 'No headlines match these filters.'));
    newsMore.hidden = groups.length <= newsVisible;
    if (focusInsideNews && !restoredFocus) announcementRefresh.focus({preventScroll: true});
}
newsSourceFilter.onchange = newsKindFilter.onchange = newsSearch.oninput = () => { newsVisible = 20; if (newsSnapshot) renderNewsItems(newsSnapshot); };
newsMore.onclick = () => { newsVisible += 20; if (newsSnapshot) renderNewsItems(newsSnapshot); };
async function refreshAnnouncements() {
  if (announcementBusy || document.hidden) return;
  announcementBusy = true;
  announcementRefresh.disabled = true;
  let recoverNewsFocus = false;
  try {
    const result = await api('/api/news-agent');
    announcementState.textContent = (result.stale ? 'News unavailable'
      : result.partial ? 'Some news sources are unavailable' : 'News up to date')
      + (result.lastSuccess ? ' · Last checked ' + formatDisplayTime(result.lastSuccess) : '')
      + ' · All times in IST';
    announcementSourceItems.replaceChildren();
    for (const source of result.sources || []) {
      const row = text('p', source.name + ' · ' + (source.staleReason || source.status));
      row.append(text('small', 'Last checked ' + formatDisplayTime(source.lastSuccess)
        + (source.nextRetryAt ? ' · Next check ' + formatDisplayTime(source.nextRetryAt) : '')));
      announcementSourceItems.append(row);
    }
    if (result.staleItems?.length) {
      announcementSourceItems.append(text('p', result.staleItems.length + ' older items are excluded from current research.'));
    }
    newsSnapshot = {...result, items: result.stale ? [] : result.items};
    announcementRefresh.disabled = false;
    renderNewsItems(newsSnapshot);
  } catch (error) {
    recoverNewsFocus = announcementItems.contains(document.activeElement);
    newsSnapshot = null; newsMore.hidden = true; newsCount.textContent = 'News unavailable';
    announcementState.textContent = 'News unavailable. ' + error.message;
    announcementSourceItems.replaceChildren();
    announcementItems.replaceChildren(text('p', 'Current news could not be verified.'));
  } finally {
    announcementBusy = false;
    announcementRefresh.disabled = false;
    if (recoverNewsFocus) announcementRefresh.focus({preventScroll: true});
  }
}
announcementRefresh.onclick = refreshAnnouncements;
const announcementTimer = setInterval(refreshAnnouncements, 5000);
window.addEventListener('pagehide', () => clearInterval(announcementTimer));
document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshAnnouncements(); });
refreshAnnouncements();

// Continuous provider-candle paper worker. Browser polling is health-only;
// strategy ingestion is owned by the server, never this page timer.
let workerState=null,workerVersion=0,workerBusy=false;
function workerEligible(account){return Boolean(account&&account.config?.strategy==='intraday-v1'&&account.config?.source==='imported');}
function workerStatusText(status){
 if(!status||status.live!==false||['unknown','unavailable'].includes(status.state))return 'Worker health unverified. Refresh worker health.';
 if(status.lastErrorCode==='BROKER_LOGIN_REQUIRED')return 'Worker stopped. Reconnect Zerodha in Settings, then review and restart the worker.';
 if(status.state==='expired')return 'Worker heartbeat expired. Check the service and ownership before restarting.';
 if(status.state==='waiting'&&status.enabled)return 'Worker waiting. '+(status.lastError||'Waiting for the next completed candle.');
 if(status.state==='armed'&&status.enabled)return 'Worker armed. Waiting for the first accepted candle.';
 if(status.state==='running'&&status.enabled&&status.threadAlive){
   if(!status.lastAcceptedBar)return 'Worker active. Waiting for the first accepted candle.';
   return 'Worker active. Last accepted candle '+status.lastAcceptedBar+'.';
 }
 if(status.state==='disarmed')return 'Worker idle. No automatic candle collection.';
 if(status.state==='running'&&!status.threadAlive)return 'Worker processing unverified. Refresh worker health and check the service.';
 return 'Worker '+(status.state||'unverified')+'. '+(status.lastError||'Review worker health before starting.');
}
function renderAccountHealth(account){
 if(!account)return;
 let status=account.status+' · entries '+entryState(account);
 let candle=account.lastBar;
 if(workerEligible(account)){
   if(!workerState||['unknown','unavailable'].includes(workerState.state))status=workerStatusText(workerState);
   else if(workerState.accountId===account.id){
     status=workerStatusText(workerState);
     candle=workerState.lastAcceptedBar||account.lastBar;
   }else status=workerState.enabled?'Another account owns the worker.':'No worker is collecting for this account.';
 }
 if(typeof selectionSnapshot !== 'undefined' && selectionSnapshot?.accountId===account.id){
   status=selectionStatusText(selectionSnapshot);
 }
 $('account-status').textContent=status;
 $('account-note').textContent=[account.config.symbol,account.config.strategy,'Account ingestion '+account.status,'Entries '+entryState(account),'Last accepted candle '+(candle||'none')].join(' · ');
}
function renderWorkerSelection(account){
 const eligible=workerEligible(account);
 $('worker-selection').textContent=account?'Selected account: '+account.config.symbol+' · '+account.id.slice(0,8)+' · '+account.config.strategy+' · '+account.config.source+(eligible?' observations. Server will verify mapping, permissions and account history.':' observations. Select an imported Intraday v1 account to start a worker.'):'Select an imported Intraday v1 account above.';
 $('worker-start').disabled=workerBusy||!eligible||!workerState||workerState.enabled||['unknown','unavailable'].includes(workerState.state);
}
function showWorker(status){
 workerState=status;$('worker-state').textContent=workerStatusText(status);$('worker-health').replaceChildren();
 if(status){for(const [label,value] of [['Mode',status.mode||'unverified'],['Worker state',status.state||'unknown'],['Worker account',status.accountId||'none'],['Mapped instrument',status.instrument?status.instrument.exchange+':'+status.instrument.symbol+' · token '+status.instrument.token:'none'],['Strategy version',status.strategy||'none'],['Calendar version',status.calendarVersion||'none'],['Heartbeat',status.heartbeat||'none'],['Latest accepted candle',status.lastAcceptedBar||'none'],['Lease until',status.leaseUntil||'none'],['News context',status.newsContext?status.newsContext.status+' · '+status.newsContext.attached+' matching items · '+status.newsContext.checkedAt:'Not checked yet'],['Last failure',status.lastError||'none reported']]){$('worker-health').append(text('dt',label),text('dd',value));}
 const stamp=Date.parse(status.lastAcceptedBar);if(Number.isFinite(stamp))$('worker-health').append(text('dt','Latest candle age'),text('dd',(stamp>Date.now()?'Future-dated candle; verify clock before use.':Math.round((Date.now()-stamp)/1000)+' seconds since candle start; verify exchange session and receipt metadata.')));
 }
 $('worker-stop').disabled=workerBusy||!status?.accountId;const selected=currentAccount();renderWorkerSelection(selected);renderAccountHealth(selected);
}
async function refreshWorker(){
 if(workerBusy)return false;const version=++workerVersion;
 try{const result=await api('/api/paper-worker');if(version!==workerVersion)return false;showWorker(result.worker||result);return true;}
 catch(error){if(version===workerVersion)showWorker({state:'unavailable',live:false,lastError:'Worker health unavailable. Refresh to retry.'});return false;}
}
function workerStartPayload(account){
 if(!workerEligible(account))throw Error('Select an imported Intraday v1 account first.');
 const symbol=$('worker-symbol').value.trim().toUpperCase(),token=Number($('worker-token').value);
 if(symbol!==account.config.symbol)throw Error('Worker symbol must exactly match the selected account.');
 if(!Number.isSafeInteger(token)||token<1)throw Error('Enter the verified positive whole instrument token.');
 if(!$('worker-retention').checked||!$('worker-calendar-confirmed').checked)throw Error('Confirm provider retention permission and the calendar source.');
 const calendar=JSON.parse($('worker-calendar').value);
 if(!calendar||Array.isArray(calendar)||typeof calendar!=='object')throw Error('Supply an attributed calendar object.');
 return {id:account.id,instrument:{exchange:'NSE',symbol,token},calendar,retentionApproved:true,calendarConfirmed:true};
}
async function workerMutation(path,body){
 if(workerBusy||busy)return false;
 return run(async()=>{workerBusy=true;workerVersion++;const selected=$('account');const oldDisabled=selected.disabled;selected.disabled=true;
 const controls=[...$('worker-form').querySelectorAll('input,textarea,button'),$('worker-stop'),$('worker-refresh')];const prior=controls.map(control=>control.disabled);controls.forEach(control=>control.disabled=true);
 try{const result=await api(path,body);showWorker(result.worker||result);await refreshPaper();}
 catch(error){showWorker({state:'unknown',accountId:body.id||workerState?.accountId,mode:'observed-candle-paper',live:false,lastError:'Request outcome uncertain. Refresh worker health before retrying.'});throw error;}
 finally{workerBusy=false;selected.disabled=oldDisabled;controls.forEach((control,index)=>control.disabled=prior[index]);renderWorkerSelection(currentAccount());$('worker-stop').disabled=!workerState?.accountId;}
 });
}
$('worker-form').onsubmit=event=>{event.preventDefault();let payload;try{payload=workerStartPayload(currentAccount());}catch(error){$('worker-state').textContent=error.message;return;}workerMutation('/api/paper-worker/start',payload);};
$('worker-stop').onclick=()=>workerMutation('/api/paper-worker/stop',{});
$('worker-refresh').onclick=refreshWorker;
const workerHealthTimer=setInterval(()=>{if(!document.hidden)refreshWorker();},15000);
window.addEventListener('pagehide',()=>clearInterval(workerHealthTimer));
refreshWorker();

const agentPanel=document.createElement('details');agentPanel.className='panel';
agentPanel.append(text('summary','Agent tasks and review history'));
const agentButton=text('button','Refresh agent diagnostics');agentButton.type='button';
const agentOutput=text('pre','No tasks checked yet.');agentPanel.append(agentButton,agentOutput);$('settings').append(agentPanel);
agentButton.onclick=async()=>{agentButton.disabled=true;try{const result=await api('/api/agents');agentOutput.textContent=JSON.stringify({mode:result.mode,registered:result.registered,implemented:result.implemented,tasks:result.tasks},null,2);}catch(error){agentOutput.textContent='Agent diagnostics unavailable: '+error.message;}finally{agentButton.disabled=false;}};
