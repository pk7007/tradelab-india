const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const nodes={};
function element(){return {textContent:'',children:[],append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;}};}
for(const id of ['candidates','research-note','limit-summary'])nodes[id]=element();
nodes.limits={elements:{capital:{},maxLoss:{},dailyLossLimit:{}}};
const ctx={researchVersion:0,settings:{revision:1},$:id=>nodes[id],text:(_tag,value)=>({...element(),textContent:value}),money:String};
vm.createContext(ctx);
const source=fs.readFileSync('web/portal.js','utf8');
vm.runInContext(source.slice(source.indexOf('function showSettings('),source.indexOf("$('limits').onsubmit")),ctx);
nodes.candidates.children=['old sizing'];
ctx.showSettings({capital:500,maxLoss:10,dailyLossLimit:50,revision:2});
assert.match(nodes.candidates.children[0].textContent,/Re-evaluate/);
assert.equal(nodes.limits.elements.maxLoss.value,10);
assert.match(nodes['research-note'].textContent,/invalidated/);
assert.equal(ctx.researchVersion,1,'A changed limit revision must invalidate in-flight research too');
console.log('PASS: saved-limit changes invalidate previous candidate sizing');
