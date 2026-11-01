/* Private market-data UI. Broker tokens never enter this script. */
let historyJob = null;
let historyTimer = null;
let streamTimer = null;
let streamBusy = false;

function localDate(date) {
  return new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
}
function historyPreset(intraday = false) {
  const end = new Date(), start = new Date(end);
  start.setUTCDate(start.getUTCDate() - (intraday ? 90 : 5*365));
  $('#history-from').value = localDate(start);
  $('#history-to').value = localDate(end);
  $('#history-to').max = localDate(end);
  $('#history-interval').value = intraday ? '5minute' : 'day';
}

function chart(target, input, candles = false) {
  const rows = input.slice(candles ? -200 : -1000);
  if (!rows.length) { target.innerHTML = '<p>No observations returned for this selection.</p>'; return; }
  const width = 900, height = 320, left = 85, right = 25, top = 25, bottom = 42;
  let low = Math.min(...rows.map(r => Number(candles ? r.low : r.close)));
  let high = Math.max(...rows.map(r => Number(candles ? r.high : r.close)));
  const pad = (high-low)*0.06 || Math.max(Math.abs(high)*0.001,1);
  low -= pad; high += pad;
  const x = i => left+(i+0.5)*(width-left-right)/rows.length;
  const y = p => top+(high-Number(p))/(high-low)*(height-top-bottom);
  let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${safe(candles ? 'Historical candlestick chart' : 'Price line chart')}">`;
  for (let i=0;i<5;i++) {
    const p = low+(high-low)*i/4;
    svg += `<line x1="${left}" y1="${y(p)}" x2="${width-right}" y2="${y(p)}" stroke="#e9ebe5"/><text x="${left-8}" y="${y(p)+4}" text-anchor="end" fill="#7b827b" font-size="11">${safe(p.toLocaleString('en-IN',{maximumFractionDigits:2}))}</text>`;
  }
  if (candles) {
    const barWidth = Math.max(1,(width-left-right)/rows.length*0.6);
    rows.forEach((r,i) => {
      const color = Number(r.close)>=Number(r.open) ? '#28794e' : '#b53b39';
      svg += `<line x1="${x(i)}" y1="${y(r.high)}" x2="${x(i)}" y2="${y(r.low)}" stroke="${color}"/><rect x="${x(i)-barWidth/2}" y="${Math.min(y(r.open),y(r.close))}" width="${barWidth}" height="${Math.max(1,Math.abs(y(r.open)-y(r.close)))}" fill="${color}"><title>${safe(r.date)} O ${safe(r.open)} H ${safe(r.high)} L ${safe(r.low)} C ${safe(r.close)}</title></rect>`;
    });
  } else {
    svg += `<polyline points="${rows.map((r,i)=>`${x(i)},${y(r.close)}`).join(' ')}" fill="none" stroke="#28794e" stroke-width="2"/>`;
  }
  const label = value => {
    if (!value.includes('T')) return value;
    return new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date(value));
  };
  svg += `<text x="${left}" y="${height-12}" fill="#7b827b" font-size="11">${safe(label(rows[0].date))}</text><text x="${width-right}" y="${height-12}" text-anchor="end" fill="#7b827b" font-size="11">${safe(label(rows.at(-1).date))}</text></svg>`;
  target.innerHTML = svg;
  target.setAttribute('aria-label',`${rows.length} observations. First ${rows[0].close}, last ${rows.at(-1).close}. Range ${low.toFixed(2)} to ${high.toFixed(2)}.`);
}

$('#instrument-find').addEventListener('click',async () => {
  $('#instrument-results').textContent = 'Searching the current NSE instrument master…';
  try {
    const data = await api('/api/market/instruments?q='+encodeURIComponent($('#instrument-search').value.trim()));
    $('#instrument-results').replaceChildren();
    for (const row of data.instruments) {
      const button = document.createElement('button'); button.type='button'; button.className='text-button';
      button.textContent=`${row.tradingsymbol} · ${row.name}`;
      button.addEventListener('click',()=> { $('#history-symbols').value=row.tradingsymbol; $('#stream-symbol').value=row.tradingsymbol; });
      $('#instrument-results').append(button);
    }
    if (!data.instruments.length) $('#instrument-results').textContent='No matching NSE equity found.';
  } catch(e) { $('#instrument-results').textContent=e.message; }
});

$('#daily-preset').addEventListener('click',()=>historyPreset(false));
$('#intraday-preset').addEventListener('click',()=>historyPreset(true));
$('#history-form').addEventListener('submit',async event => {
  event.preventDefault();
  clearTimeout(historyTimer);
  $('#history-load').disabled=true;
  $('#history-status').textContent='Starting historical request…';
  try {
    const job=await api('/api/market/history',{method:'POST',body:JSON.stringify({symbols:$('#history-symbols').value,from:$('#history-from').value,to:$('#history-to').value,interval:$('#history-interval').value,save:$('#history-save').checked})});
    historyJob=job.id;
    $('#history-cancel').disabled=false;
    $('#history-chart-symbol').replaceChildren(...job.symbols.map(s => new Option(s,s)));
    await pollHistory();
  } catch(e) { $('#history-status').textContent=e.message; $('#history-load').disabled=false; }
});

async function pollHistory() {
  try {
    const job=await api('/api/market/history?id='+encodeURIComponent(historyJob));
    const count=Object.values(job.counts).reduce((a,b)=>a+b,0);
    $('#history-status').textContent=`${job.state.toUpperCase()} · ${job.completed}/${job.total} date windows · ${count.toLocaleString()} candles · ${job.emptyWindows} empty windows. ${job.error || ''}`;
    if (['complete','failed','cancelled'].includes(job.state)) {
      $('#history-load').disabled=false; $('#history-cancel').disabled=true;
      if (job.save) $('#history-status').textContent += ' Completed symbols saved in your configured local market-data folder, request '+job.id+'.';
      await showHistory();
    } else { historyTimer=setTimeout(pollHistory,1200); }
  } catch(e) {
    $('#history-status').textContent=e.message; $('#history-load').disabled=false; $('#history-cancel').disabled=true;
  }
}
async function showHistory() {
  if (!historyJob) return;
  try {
    const symbol=$('#history-chart-symbol').value;
    const data=await api('/api/market/history?id='+encodeURIComponent(historyJob)+'&symbol='+encodeURIComponent(symbol));
    chart($('#history-chart'),data.candles,true);
    $('#history-chart-caption').textContent=`${symbol} · ${data.interval} · ${data.counts[symbol] || 0} total candles. Chart shows the latest ${Math.min(200,data.candles.length)}. Provider data is not independently adjusted or verified; empty periods are not filled in.`;
    $('#history-rows').innerHTML=data.candles.slice(-10).reverse().map(r=>`<tr><td>${safe(r.date)}</td><td>${money(r.open)}</td><td>${money(r.high)}</td><td>${money(r.low)}</td><td>${money(r.close)}</td><td>${safe(r.volume)}</td></tr>`).join('');
  } catch(e) { $('#history-status').textContent=e.message; }
}
$('#history-chart-symbol').addEventListener('change',showHistory);
$('#history-cancel').addEventListener('click',async()=> {
  try { await api('/api/market/cancel',{method:'POST',body:JSON.stringify({id:historyJob})}); $('#history-status').textContent='Cancellation requested; the in-flight broker request may finish first.'; }
  catch(e) { $('#history-status').textContent=e.message; }
});

$('#stream-start').addEventListener('click',async()=> {
  $('#stream-start').disabled=true;
  try {
    await api('/api/market/stream/start',{method:'POST',body:JSON.stringify({symbol:$('#stream-symbol').value})});
    clearInterval(streamTimer); streamTimer=setInterval(pollStream,1000); await pollStream();
  } catch(e) { $('#stream-info').textContent=e.message; }
  finally { $('#stream-start').disabled=false; }
});
async function pollStream() {
  if (streamBusy) return;
  streamBusy=true;
  try {
    const data=await api('/api/market/stream');
    $('#stream-state').textContent=data.state.toUpperCase();
    const age=data.lastTick ? Math.max(0,Math.round((Date.now()-Date.parse(data.lastTick))/1000)) : null;
    $('#stream-info').textContent=data.lastTick ? `${data.symbol} · last tick received ${age}s ago${age>15 ? ' · STALE / no recent tick' : ''} · ${money(data.points.at(-1)?.close)}` : 'Waiting for market ticks. No synthetic prices are shown here.';
    chart($('#live-chart'),data.points);
    if (data.state==='stopped') clearInterval(streamTimer);
  } catch(e) { $('#stream-state').textContent='ERROR'; $('#stream-info').textContent=e.message; clearInterval(streamTimer); }
  finally { streamBusy=false; }
}
$('#stream-stop').addEventListener('click',async()=> {
  try { await api('/api/market/stream/stop',{method:'POST',body:'{}'}); clearInterval(streamTimer); $('#stream-state').textContent='STOPPED'; $('#stream-info').textContent='Stream stopped. The chart retains the last received ticks for this page only.'; }
  catch(e) { $('#stream-info').textContent=e.message; }
});
$('#research-form').addEventListener('submit',async event=> {
  event.preventDefault();
  try {
    const result=await api('/api/market/research',{method:'POST',body:JSON.stringify({fast:Number($('#research-fast').value),slow:Number($('#research-slow').value),costBps:Number($('#research-cost').value),slippageBps:Number($('#research-slip').value)})});
    $('#research-result').textContent=`${result.label}. Final synthetic equity ${money(result.finalEquity)}; return ${result.returnPct.toFixed(2)}%; maximum drawdown ${result.maxDrawdownPct.toFixed(2)}%; ${result.fills} fills; modeled fees ${money(result.modeledFees)}. Open units at end: ${result.openQuantity}.`;
    $('#research-assumptions').textContent=result.assumptions;
    chart($('#research-chart'),result.equity);
  } catch(e) { $('#research-result').textContent=e.message; }
});
historyPreset();

const rankingRecords=[];
$('#ranking-form').addEventListener('submit',async event=> {
  event.preventDefault();
  $('#ranking-results').replaceChildren();
  $('#ranking-limitations').textContent='';
  const config={id:historyJob,horizon:$('#ranking-horizon').value,asOf:new Date().toISOString()};
  try {
    if(!historyJob) throw new Error('Load a complete historical request in Market data first.');
    const report=await api('/api/market/rank',{method:'POST',body:JSON.stringify(config)});
    $('#ranking-status').textContent=report.status+'. '+(report.reason||report.formula);
    $('#ranking-results').innerHTML=report.candidates.map((r,i)=>`<details><summary>${i+1}. ${safe(r.symbol)} · momentum score ${r.score.toFixed(2)}</summary><p>Through ${safe(r.dataThrough)}. Contribution: 20-bar momentum ${r.momentumPct.toFixed(2)} percentage points. Per-bar volatility ${r.barVolatilityPct.toFixed(2)}%. Mean turnover proxy ${money(r.meanTurnoverProxy)}.</p><p>${safe(r.support)} ${safe(r.contradictions)}</p><p>Invalidation: ${safe(r.invalidation)}</p><p>${safe(r.quality)}</p></details>`).join('')+report.excluded.map(r=>`<p>${safe(r.symbol)}: ${safe(r.reason)}</p>`).join('');
    $('#ranking-limitations').textContent=report.limitations.join(' ');
    rankingRecords.push({...report.experiment,status:report.status});
  } catch(e) {
    $('#ranking-status').textContent=e.message;
    rankingRecords.push({config,error:e.message,createdAt:new Date().toISOString()});
  }
  if(rankingRecords.length>30) rankingRecords.shift();
  $('#ranking-records').textContent=JSON.stringify(rankingRecords,null,2);
});

$('#stress-run').addEventListener('click',async()=> {
  $('#stress-run').disabled=true;
  try {
    const r=await api('/api/market/stress',{method:'POST',body:'{}'});
    $('#stress-status').textContent=r.label+'. '+r.limitations.join(' ');
    $('#stress-results').innerHTML='<table><thead><tr><th>Scenario</th><th>Variant</th><th>Return</th><th>Drawdown</th><th>Exposure</th><th>Completed trades</th></tr></thead><tbody>'+r.results.map(x=>`<tr><td>${safe(x.scenario)}</td><td>${safe(x.variant)}</td><td>${x.returnPct.toFixed(2)}%</td><td>${x.maxDrawdownPct.toFixed(2)}%</td><td>${x.exposurePct.toFixed(2)}%</td><td>${x.completedTrades}</td></tr>`).join('')+'</tbody></table>';
  } catch(e) { $('#stress-status').textContent=e.message; }
  finally { $('#stress-run').disabled=false; }
});
