const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function readFunction(file,start,end){const source=fs.readFileSync(file,'utf8');const ctx={};vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf(start),source.indexOf(end)),ctx);return ctx;}
const research=readFunction('web/evaluation.js','function researchReviewText','function render(');
assert.match(research.researchReviewText(),/unavailable/);
const repeated=research.researchReviewText({runId:'run-1',previousViews:2,holdoutViewedBefore:true,independentEvidence:false,promotionAllowed:false,reason:'Repeated holdout inspection.'});
assert.match(repeated,/Previous views: 2/);
assert.match(repeated,/viewed before/);
assert.match(repeated,/Independent evidence: not established/);
assert.match(repeated,/Registry promotion: blocked/);
assert.match(research.researchReviewText({previousViews:0,holdoutViewedBefore:false}),/does not establish independent evidence/);
const paper=readFunction('web/paper.js','function eventDetail','function show(');
assert.equal(paper.eventDetail({side:'BUY',reason:'Exposure gate'}),'Exposure gate');
assert.equal(paper.eventDetail({side:'SELL'}),'SELL (no fill price recorded)');
assert.equal(paper.eventDetail({side:'BUY',quantity:2,price:12.5}),'BUY 2 @ 12.5000');
console.log('PASS: research evidence distinctions and incomplete paper event formatting');
