'use strict';
const el = id => document.getElementById(id);
const pct = x => x.toFixed(2) + '%';
const signed = x => (x > 0 ? '+' : '') + x.toFixed(2);
function render(report) {
  el('report-type').textContent = report.source === 'synthetic' ? 'SYNTHETIC DEMONSTRATION' : 'USER-SUPPLIED HISTORICAL SIMULATION';
  el('report-title').textContent = report.symbol + ' · final test window';
  const h = report.holdout;
  el('period').textContent = h.start + ' to ' + h.end + ' · ' + h.bars + ' of ' + report.completedBars + ' bars · ' +
    report.costBps + ' bps fees and ' + report.slippageBps + ' bps slippage per side.';
  el('windows').replaceChildren();
  for (const [label,w] of [['Validation 1',report.validation[0]],['Validation 2',report.validation[1]],['Final holdout',h],['Holdout · doubled costs',report.stressHoldout]]) {
    const row=document.createElement('tr');
    [label,pct(w.strategy.returnPct),pct(w.benchmark.returnPct),signed(w.excessReturnPct)+' pp',pct(w.strategy.maxDrawdownPct),w.strategy.completedTrades].forEach((value,i)=>{
      const cell=document.createElement(i?'td':'th');if(!i)cell.scope='row';cell.textContent=value;row.append(cell);
    });
    el('windows').append(row);
  }
  el('interpretation').textContent = (report.source==='synthetic' ? 'These prices are invented. ' : 'These figures describe this file and these assumptions. ') +
    'The strategy finished '+ (h.excessReturnPct===0?'level with':h.excessReturnPct>0?'ahead of':'behind') +' buy-and-hold on the final window. ' +
    'It completed '+h.strategy.completedTrades+' round trips. This is not a forecast.';
  el('method').textContent=report.method;el('limits').replaceChildren();
  for (const limit of report.limitations) { const li=document.createElement('li');li.textContent=limit;el('limits').append(li); }
  el('payload').textContent=JSON.stringify(report,null,2);el('report').hidden=false;
}
async function run(build) {
  el('report').hidden=true;el('message').textContent='Evaluating…';el('demo').disabled=el('run').disabled=true;
  try {
    const data=JSON.stringify(await build());
    if(new Blob([data]).size>8000000)throw Error('The encoded request exceeds the 8 MB limit. Use a shorter period.');
    const response=await fetch('/api/trader/evaluate',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:data});
    const report=await response.json();if(!response.ok)throw Error(report.error||'Evaluation failed.');
    render(report);el('message').textContent='Evaluation complete.';el('report').scrollIntoView({block:'start'});
  } catch(error) { el('message').textContent=error.message; }
  finally { el('demo').disabled=el('run').disabled=false; }
}
el('demo').addEventListener('click',()=>run(()=>({demo:true})));
el('import-form').addEventListener('submit',event=>{
  event.preventDefault();const fields=new FormData(event.currentTarget);
  run(async()=>{
    const file=fields.get('file');if(!file||file.size>8000000)throw Error('Choose a file smaller than 8 MB.');
    const symbol=fields.get('symbol').trim();
    const data={permitted:fields.has('permitted'),source:'imported'};
    for(const key of ['interval','asOf','capital','costBps','slippageBps'])data[key]=fields.get(key);
    const raw=await file.text();
    if(file.name.toLowerCase().endsWith('.csv')){data.csv=raw;data.symbol=symbol;}
    else {const parsed=JSON.parse(raw);data.candles=Array.isArray(parsed)?{[symbol]:parsed}:parsed;}
    return data;
  });
});
