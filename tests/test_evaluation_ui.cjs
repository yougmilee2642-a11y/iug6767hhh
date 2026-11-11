const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness(agent, options = {available:true,provider:'Ollama',message:'Локальная проверка'}) {
  const elements = new Map();
  const get = (selector) => {
    if (!elements.has(selector)) elements.set(selector, {textContent: '', innerHTML: '', disabled: false, value: '', selectedOptions: []});
    return elements.get(selector);
  };
  const context = {
    window: { addEventListener() {} },
    localStorage: { setItem() {} },
    $: get,
    $$: () => [],
    showView() {},
    clearTimeout() {},
    setTimeout() { return 1; },
    Date,
    encodeURIComponent,
    JSON,
    Object,
    String,
    Number,
    Error,
    console,
    escapeHtml: value => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])),
  };
  vm.createContext(context);
  const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'evaluation.js'), 'utf8');
  vm.runInContext(source, context, {filename: 'evaluation.js'});
  context.evaluationFetch = async (url) => {
    if (url==='/api/evaluation/options') return options;
    if (url.startsWith('/api/agents/') && !url.endsWith('/evaluations')) return agent;
    if (url.endsWith('/evaluations')) return {items: []};
    throw new Error(`Unexpected URL: ${url}`);
  };
  return {context, get};
}

test('Evaluation is available for a confirmed short-wizard profile', async () => {
  const {context, get} = harness({id: 'track1_test', name: 'Короткий мастер', source: 'track1', candidate_id: 'candidate-1', config: {business: {knowledge: {track1_quick: true, track1_profile: 'secretary'}}}});
  await context.openEvaluation('track1_test');
  assert.equal(get('#evaluationStart').disabled, false);
  assert.match(get('#evaluationStatus').textContent, /ролевая проверка короткого мастера/);
});

test('report opens as a browser page and each failure has a readable explanation', () => {
  const {context, get} = harness({});
  context.renderEvaluation({id:'run-1',status:'completed',progress:1,count:1,requests:2,
    provider_info:{},errors:[],warnings:[],requirements:[],scenarios:[{
      id:'refused',title:'Отказ',scenario_type:'HANDOFF',expected_behavior:'Не сохранять',
      result:{status:'FAIL',failure_reasons:['conversation_loop / turn_limit_exceeded'],
        explanation:{category:'Логика диалога',actual:'<script>bad</script>',next_step:'Исправить обработку отказа.',reasons:['Диалог зациклился.']}}
    }]});
  const html = get('#evaluationReport').innerHTML;
  assert.match(html, /Открыть полный отчёт/);
  assert.match(html, /href="\/api\/evaluations\/run-1\/report" target="_blank"/);
  assert.ok(!html.includes('download='));
  assert.match(html, /Диалог зациклился/);
  assert.ok(!html.includes('<script>bad'));
});

test('Evaluation stays fail-closed for track1 agents without a recognized profile', async () => {
  const {context, get} = harness({id: 'track1_test', name: 'Короткий мастер', source: 'track1', candidate_id: 'candidate-1'});
  await context.openEvaluation('track1_test');
  assert.equal(get('#evaluationStart').disabled, true);
});

test('Builder Evaluation remains available for a saved Builder candidate', async () => {
  const {context, get} = harness({id: 'builder_test', name: 'Builder', source: 'builder', candidate_id: 'candidate-2'});
  await context.openEvaluation('builder_test');
  assert.equal(get('#evaluationStart').disabled, false);
});


test('Unavailable local model disables start with a clear reason', async () => {
  const {context,get}=harness({id:'a',name:'Тест',source:'track1',candidate_id:'c',config:{business:{knowledge:{track1_profile:'support'}}}}, {available:false,message:'Локальная модель недоступна.'});
  await context.openEvaluation('a');
  assert.equal(get('#evaluationStart').disabled,true);
  assert.match(get('#evaluationStatus').textContent,/недоступна/);
});

test('Late response for previous assistant cannot replace the current screen', async () => {
  const {context,get}=harness({});
  let resolveA;
  context.evaluationFetch=async url=>{
    if(url==='/api/evaluation/options')return {available:true,message:'Локально'};
    if(url.endsWith('/evaluations'))return {items:[]};
    if(url==='/api/agents/a')return new Promise(resolve=>resolveA=resolve);
    return {id:'b',name:'Помощник B',source:'builder',candidate_id:'c'};
  };
  const first=context.openEvaluation('a');
  await context.openEvaluation('b');
  resolveA({id:'a',name:'Помощник A',source:'builder',candidate_id:'c'});
  await first;
  assert.equal(get('#evaluationAgentName').textContent,'Помощник B');
});
