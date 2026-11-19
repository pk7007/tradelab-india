'use strict';
const $=id=>document.getElementById(id);
const money=value=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(value);
let settings=null, paper={accounts:[],events:[]}, busy=false, researchVersion=0, paperVersion=0, watchlistVersion=0;
function text(tag,value,className){const el=document.createElement(tag);el.textContent=String(value??'');if(className)el.className=className;return el;}
async function api(path,body){const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(30000)});let result;try{result=await response.json();}catch{throw Error('The server returned an unreadable response. Refresh or check the connection.');}if(!response.ok)throw Error(result.error||'Request failed.');return result;}
async function run(action){if(busy)return;busy=true;$('message').textContent='Working…';try{const current=await action();$('message').textContent=current===false?'Inputs changed while the request was running. Re-evaluate the current inputs.':'Complete. Review the current state below.';}catch(error){$('message').textContent=error.message;}finally{busy=false;}}
function activate(name,updateHistory=true){if(!['intraday','longterm','auto'].includes(name))name='intraday';for(const tab of document.querySelectorAll('[data-tab]')){const selected=tab.dataset.tab===name;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;$(tab.dataset.tab).hidden=!selected;}if(updateHistory)history.replaceState(null,'',name==='longterm'?'/long-term':name==='auto'?'/auto-trading':'/intraday');}
for(const tab of document.querySelectorAll('[data-tab]')){tab.onclick=()=>activate(tab.dataset.tab);tab.onkeydown=event=>{const tabs=[...document.querySelectorAll('[data-tab]')],index=tabs.indexOf(tab);let next;if(event.key==='ArrowRight')next=(index+1)%tabs.length;else if(event.key==='ArrowLeft')next=(index+tabs.length-1)%tabs.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=tabs.length-1;else return;event.preventDefault();activate(tabs[next].dataset.tab);tabs[next].focus();};}
$('settings-toggle').onclick=()=>{const open=$('settings').hidden;$('settings').hidden=!open;$('settings-toggle').setAttribute('aria-expanded',String(open));};
function showSettings(value){if(settings&&settings.revision!==value.revision){researchVersion++;$('candidates').replaceChildren(text('p','Limits changed. Re-evaluate the snapshot before using previous sizing.'));$('research-note').textContent='Previous research sizing invalidated.';}settings=value;for(const key of ['capital','maxLoss','dailyLossLimit'])$('limits').elements[key].value=value[key];$('limit-summary').replaceChildren();for(const [label,key] of [['Capital','capital'],['Planned loss / trade','maxLoss'],['Daily loss threshold','dailyLossLimit']]){const item=text('div','');item.append(text('span',label),text('strong',money(value[key])));$('limit-summary').append(item);}}
$('limits').onsubmit=event=>{event.preventDefault();run(async()=>{const values=Object.fromEntries(new FormData(event.target));const result=await api('/api/portal/settings',values);showSettings(result.settings||result);});};
function showWatchlist(symbols){$('watchlist-input').value=symbols.join(', ');$('watchlist').replaceChildren();for(const symbol of symbols){const item=text('div','','history-item');item.append(text('strong',symbol),text('small','Insufficient evidence · sector and fundamental research unavailable'));$('watchlist').append(item);}}
$('watchlist-form').onsubmit=event=>{event.preventDefault();run(async()=>{const version=watchlistVersion;const watchlist=$('watchlist-input').value.split(',').map(s=>s.trim().toUpperCase()).filter(Boolean);await api('/api/portal/research',{horizon:'long-term',watchlist});if(version!==watchlistVersion)return false;showWatchlist(watchlist);});};
$('watchlist-input').addEventListener('input',()=>watchlistVersion++);
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
 $('account-note').textContent=account.config.symbol+' · '+account.config.source+' observations · '+account.config.strategy+' · last candle '+(account.lastBar||'none');$('account-status').textContent=account.status+' · entries '+entryState(account);
 const unrealized=account.equity-account.cash-account.basis;for(const [label,value] of [['Cash',money(account.cash)],['Marked equity',money(account.equity)],['Realized P&L',money(account.realized)],['Unrealized P&L',money(unrealized)],['Shares held',String(account.quantity)],['Costs paid',money(account.fees)],['Daily loss used',money(account.dayLoss)+' / '+money(account.config.dailyLossLimit)],['Remaining daily allowance',money(Math.max(0,account.config.dailyLossLimit-account.dayLoss))],['Stop / target',account.protection?money(account.protection.stop)+' / '+money(account.protection.target):'None active'],['Pending order',account.pending?.side||'None']]){const metric=text('div','','metric');metric.append(text('small',label),text('strong',value));$('metrics').append(metric);}
 $('exposure').textContent=(account.quantity?'Exposure remains open: '+account.quantity+' simulated shares. ':'No open simulated shares. ')+(account.pending?'Pending '+account.pending.side+' waits for an accepted candle. ':'')+'This account uses '+money(account.config.capital)+' starting cash and '+money(account.config.dailyLossLimit)+' daily loss threshold. '+paperModelDescription(account.config)+(account.recoveryRequired?' Recovery required: carried exposure blocks new entries.':'');
 $('history').replaceChildren();const events=paper.events.filter(event=>event.account===account.id&&event.type!=='bar');for(const event of events){const row=text('div','','history-item');const detail=event.detail||event.reason||(event.side?event.side+' '+(event.quantity??'')+(Number.isFinite(event.price)?' @ '+money(event.price):''):'Configuration recorded');row.append(text('strong',event.type.replaceAll('_',' ')),text('div',detail),text('small',event.at));$('history').append(row);}if(!events.length)$('history').append(text('p','No recent fills or decisions.'));
}
async function refreshPaper(){const version=++paperVersion;const result=await api('/api/trader/paper-state',{});if(version!==paperVersion)return false;const selected=$('account').value;paper=result;$('account').replaceChildren();if(!paper.accounts.length){const option=text('option','No accounts configured');option.value='';$('account').append(option);}for(const account of paper.accounts){const option=text('option',account.config.symbol+' · '+account.config.source+' · '+account.id.slice(0,8));option.value=account.id;$('account').append(option);}if(paper.accounts.some(account=>account.id===selected))$('account').value=selected;showPaper();}
$('account').onchange=showPaper;$('refresh-paper').onclick=()=>run(refreshPaper);
for(const button of document.querySelectorAll('[data-action]'))button.onclick=()=>run(async()=>{const account=currentAccount();if(!account)throw Error('Select a paper account first.');await api('/api/trader/paper-control',{id:account.id,action:button.dataset.action});await refreshPaper();});
async function load(){activate(location.pathname==='/long-term'?'longterm':location.pathname==='/auto-trading'?'auto':'intraday',false);try{const portal=await api('/api/portal');showSettings(portal.settings);showWatchlist(portal.watchlist||[]);}catch(error){$('message').textContent=error.message;}try{const status=await api('/api/status');$('connection').textContent=(status.connected?'Broker session connected.':'Broker session disconnected.')+' Live execution remains locked; authentication alone does not establish readiness.';}catch{$('connection').textContent='Broker status unavailable. Open advanced connection settings.';}try{await refreshPaper();}catch(error){$('account-note').textContent=error.message;$('account-status').textContent='Unable to load';}}
load();

// Official announcement summaries; refresh only while this document is visible.
const announcementPanel=text('section','','panel');
announcementPanel.append(text('h3','Market news · NSE, ET & Google'));
const announcementState=text('p','Checking official RSS…');
const announcementRefresh=text('button','Refresh announcements');announcementRefresh.type='button';
const announcementItems=text('div','','history');
announcementPanel.append(announcementState,announcementRefresh,announcementItems);
$('intraday').append(announcementPanel);
let announcementBusy=false;
async function refreshAnnouncements(){
 if(announcementBusy||document.hidden)return;announcementBusy=true;announcementRefresh.disabled=true;
 try{const result=await api('/api/news-agent');announcementState.textContent=(result.error||result.status)+(result.partial?' · Some sources unavailable':'')+' · Last success: '+(result.lastSuccess||'none')+' · Refresh interval: 5 minutes. No order triggers.';
 announcementItems.replaceChildren();for(const item of result.items||[]){const row=text('article','','history-item');const link=text('a',item.title);let url;try{url=new URL(item.url);}catch{continue;}if(url.protocol!=='https:'||url.username||url.password)continue;link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';row.append(link,text('p',(item.sourceName||'NSE')+' · '+item.description),text('small','Published: '+item.publishedAt+' · First received: '+item.availableAt+' · '+item.mapping));announcementItems.append(row);}
 if(!result.items?.length)announcementItems.append(text('p','No announcement summaries available. This is not evidence that no events occurred.'));
 }catch(error){announcementState.textContent='Announcements unavailable: '+error.message+' · Previous summaries removed; freshness is not established.';announcementItems.replaceChildren(text('p','No current announcement evidence is available.'));}finally{announcementBusy=false;announcementRefresh.disabled=false;}
}
announcementRefresh.onclick=refreshAnnouncements;
const announcementTimer=setInterval(refreshAnnouncements,300000);
window.addEventListener('pagehide',()=>clearInterval(announcementTimer));
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshAnnouncements();});
refreshAnnouncements();

// Continuous provider-candle paper worker. Browser polling is health-only;
// strategy ingestion is owned by the server, never this page timer.
let workerState=null,workerVersion=0,workerBusy=false;
function workerEligible(account){return Boolean(account&&account.config?.strategy==='intraday-v1'&&account.config?.source==='imported');}
function workerStatusText(status){if(!status||status.live!==false)return 'Worker status is unverified; no live readiness is implied.';return 'Paper worker: '+String(status.state||'unknown')+'. Provider connectivity and fresh candles must be checked separately.';}
function renderWorkerSelection(account){
 const eligible=workerEligible(account);
 $('worker-selection').textContent=account?'Selected account: '+account.config.symbol+' · '+account.id.slice(0,8)+' · '+account.config.strategy+' · '+account.config.source+(eligible?' observations. Server will verify mapping, permissions and account history.':' observations. Select an imported Intraday v1 account to start a worker.'):'Select an imported Intraday v1 account above.';
 $('worker-start').disabled=workerBusy||!eligible||workerState?.state==='unknown';
}
function showWorker(status){
 workerState=status;$('worker-state').textContent=workerStatusText(status);$('worker-health').replaceChildren();
 if(status){for(const [label,value] of [['Mode',status.mode||'unverified'],['Worker state',status.state||'unknown'],['Worker account',status.accountId||'none'],['Mapped instrument',status.instrument?status.instrument.exchange+':'+status.instrument.symbol+' · token '+status.instrument.token:'none'],['Strategy version',status.strategy||'none'],['Calendar version',status.calendarVersion||'none'],['Heartbeat',status.heartbeat||'none'],['Latest accepted candle',status.lastAcceptedBar||'none'],['Lease until',status.leaseUntil||'none'],['News context',status.newsContext?status.newsContext.status+' · '+status.newsContext.attached+' matching items · '+status.newsContext.checkedAt:'Not checked yet'],['Last failure',status.lastError||'none reported']]){$('worker-health').append(text('dt',label),text('dd',value));}
 const stamp=Date.parse(status.lastAcceptedBar);if(Number.isFinite(stamp))$('worker-health').append(text('dt','Latest candle age'),text('dd',(stamp>Date.now()?'Future-dated candle; verify clock before use.':Math.round((Date.now()-stamp)/1000)+' seconds since candle start; verify exchange session and receipt metadata.')));
 }
 $('worker-stop').disabled=workerBusy||!status?.accountId;renderWorkerSelection(currentAccount());
}
async function refreshWorker(){
 if(workerBusy)return false;const version=++workerVersion;
 try{const result=await api('/api/paper-worker');if(version!==workerVersion)return false;showWorker(result.worker||result);return true;}
 catch(error){if(version===workerVersion){$('worker-state').textContent='Worker health unavailable: '+error.message+'. Any displayed health below is last-known, not current.';}return false;}
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
