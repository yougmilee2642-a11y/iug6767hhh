let evaluationAgentId=null;
let evaluationPoll=null;
let evaluationCanStart=false;
let evaluationOpenVersion=0;
const evaluationStatuses={pending:'Ожидает запуска',running:'Выполняется',completed:'Завершена',partial:'Частично выполнена',failed:'Не завершена'};
const evaluationCoverage={COVERED:'Покрыто',PARTIALLY_COVERED:'Частично покрыто',MISSING:'Не покрыто',UNSUPPORTED:'Не поддерживается'};
const evaluationLabels={requirement_coverage:'Требования в настройках',scenario_reliability:'Успешность сценариев',tool_correctness:'Корректность инструментов',safety_escalation:'Безопасность / передача человеку'};

async function evaluationFetch(path,body){
  const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await r.json();if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'Не удалось выполнить проверку');return data;
}
async function openEvaluation(agentId){
  const version=++evaluationOpenVersion;
  evaluationAgentId=agentId;clearTimeout(evaluationPoll);
  try{localStorage.setItem('callwiseEvaluationAgent',agentId);}catch(_){}
  evaluationCanStart=false;$('#evaluationStart').disabled=true;
  const [agent,options]=await Promise.all([evaluationFetch('/api/agents/'+encodeURIComponent(agentId)),evaluationFetch('/api/evaluation/options')]);
  if(version!==evaluationOpenVersion)return;
  $('#evaluationAgentName').textContent=agent.name;$('#evaluationReport').innerHTML='';
  evaluationCanStart=options.available && (agent.source==='track1' ? Boolean(agent.candidate_id && ['secretary','support'].includes(agent.config?.business?.knowledge?.track1_profile)) : Boolean(agent.candidate_id));
  $('#evaluationStatus').textContent=evaluationCanStart?(agent.source==='track1'?'Готова ролевая проверка короткого мастера. Каталог услуг, расписание и сотрудники не предполагаются.':'Проверка ещё не запускалась.'):(options.available?'Для этого агента нет поддержанного источника конфигурации Evaluation.':options.message);
  $('#evaluationProviderNote').textContent=[options.provider,options.model].filter(Boolean).join(' · ')+'. '+options.message;
  $('#evaluationMode').value='CORE';
  $('#evaluationStart').disabled=!evaluationCanStart;showView('evaluation');await evaluationHistory();
}
async function evaluationHistory(preferred){
  const version=evaluationOpenVersion;
  const {items}=await evaluationFetch(`/api/agents/${encodeURIComponent(evaluationAgentId)}/evaluations`);
  if(version!==evaluationOpenVersion)return;
  $('#evaluationHistory').innerHTML='<option value="">Выберите проверку</option>'+items.map(r=>`<option value="${escapeHtml(r.id)}">${escapeHtml(new Date(r.started_at).toLocaleString('ru-RU'))} · ${evaluationStatuses[r.status]||r.status}${r.outdated?' · устарела':''}</option>`).join('');
  const id=preferred||items[0]?.id;if(id){$('#evaluationHistory').value=id;await showEvaluation(id);}
}
function renderEvaluation(run){
  const selectedOption=$('#evaluationHistory').selectedOptions[0];
  if(selectedOption?.value===run.id)selectedOption.textContent=`${new Date(run.started_at).toLocaleString('ru-RU')} · ${evaluationStatuses[run.status]||run.status}${run.outdated?' · устарела':''}`;
  $('#evaluationStatus').textContent=`${evaluationStatuses[run.status]||run.status}: ${run.progress} / ${run.plan?run.plan.scenarios.length+run.plan.optional_variants:run.count} сценариев. Обращений к модели: ${run.requests}.`;
  const report=run.readiness;
  let html=run.outdated?'<div class="builder-warning"><b>OUTDATED — устаревший отчёт.</b> Конфигурация или исходные требования изменились. Этот readiness не является текущим.</div>':'';
  html+=`<p><a class="secondary-button" href="/api/evaluations/${encodeURIComponent(run.id)}/report" target="_blank" rel="noopener">Открыть полный отчёт</a></p><p class="muted">Отчёт откроется в браузере: причины, ожидаемый результат и фактический диалог по каждому тесту.</p>`;
  if(run.provider_info.provider==='deterministic_test_double')html+='<div class="builder-warning">Тестовый провайдер: результат доказывает работу контура проверки, а не качество реальной модели.</div>';
  const health=run.provider_health;
  if(health){
    html+=`<details class="builder-warning" data-provider-health><summary>Диагностика модели</summary><p>${escapeHtml(health.provider||'local')} · ${escapeHtml(health.status)}. ${health.status==='NOT_REQUIRED'?'Локальная проверка без облачного провайдера.':'Проверяется доступность сервиса; качество ответов оценивается отдельно.'}</p>`;
    const labels={agent_text:'Agent text',agent_tools:'Tool calling',tool_continuation:'Tool continuation',structured_outputs:'Structured outputs'};
    html+=Object.entries(health.probes||{}).map(([key,p])=>`<p>${labels[key]||escapeHtml(key)}: ${escapeHtml(p.status)}${p.model?' · '+escapeHtml(p.model):''}${p.error?' · '+escapeHtml(p.error.category||p.error.type):''}</p>`).join('');
    html+=`<p>Проверочных запросов: ${health.request_count||0} · повторов: ${health.retry_count||0}</p></details>`;
  }
  const infrastructure=(run.infrastructure_errors||[]).filter(e=>e.category);
  html+=infrastructure.map(e=>`<div class="builder-warning">${escapeHtml(e.provider)} / ${escapeHtml(e.model)} · ${escapeHtml(e.operation)} · ${escapeHtml(e.category)}: ${escapeHtml(e.safe_reason)}</div>`).join('');
  html+=(run.warnings||[]).map(e=>`<div class="builder-warning">${escapeHtml(e)}</div>`).join('');
  html+=run.errors.map(e=>`<div class="builder-warning">${escapeHtml(e.role||'инфраструктура')}: ${escapeHtml(e.message)}</div>`).join('');
  if(!run.plan)html+='<div class="builder-warning">Исторический отчёт: область покрытия не сохранена. Не является сертификатом новой проверки.</div>';
  if(run.plan?.suite_kind==='quick_role')html+=`<h3>Что проверяем</h3><p>${run.quick_profile==='support'?'Ответы по знаниям и границы справочного помощника':'Приём обращения, согласие клиента и границы секретаря'}. Услуги, сотрудники и календарь не предполагаются. ${run.plan.scenarios.length>12?'Включены повторные прогоны базовых сценариев.':''}</p>`;
  else if(run.plan)html+=`<h3>План покрытия · ${escapeHtml(run.mode)}</h3><p>Услуги: ${run.plan.selected_services.length} / ${run.plan.catalog_services} (${escapeHtml(run.plan.policy.services)}). Сотрудники: ${run.plan.selected_employees.length} / ${run.plan.catalog_employees} (${escapeHtml(run.plan.policy.employees)}). Генератор: ${escapeHtml(run.generator_status)}.</p><details><summary>Сохранённый план и область проверки</summary><pre>${escapeHtml(JSON.stringify(run.plan,null,2))}</pre></details>`;
  if(run.plan && run.plan.suite_kind!=='quick_role')html+=`<p>Проверяемые услуги: ${escapeHtml((run.plan.selected_service_names||[]).join(', '))}. Сотрудники: ${escapeHtml((run.plan.selected_employee_names||[]).join(', '))}.</p>`;
  if(report){html+=`<h3>Итог: ${escapeHtml(({READY:'Готов к ограниченной проверке',LIMITED:'Нужна ручная проверка',INCONCLUSIVE:'Недостаточно данных',NOT_READY:'Есть замечания'})[report.status]||report.status)}${run.outdated?' · OUTDATED':''}</h3><p>${escapeHtml(report.recommendation)}</p>`;
    html+='<div class="evaluation-dimensions">'+Object.entries(report.dimensions).map(([key,d])=>`<div><b>${evaluationLabels[key]}</b><p>${d.passed} / ${d.total} · ${d.percent===null?'нет данных':d.percent+'%'}</p></div>`).join('')+'</div>';
    html+=`<p>Критических нарушений: ${report.critical_issues.length}. Ошибок проверки: ${report.errors}. ${report.complete_suite?'Основной набор выполнен.':'Основной набор не завершён.'}</p>`;
    const coverage=report.evaluation_coverage;
    if(coverage)html+=`<h3>Фактическое покрытие</h3><p>Запланировано ${coverage.planned} · запущено ${coverage.executed} · оценено ${coverage.evaluated} · PASS ${coverage.passed} · FAIL ${coverage.failed} · ERROR ${coverage.errors}. Завершённость: ${coverage.completion_percent}%. ${coverage.sufficient?'Заявленная область проверена.':'Покрытия недостаточно.'}</p><details><summary>Область проверки и пропуски</summary><pre>${escapeHtml(JSON.stringify({scope:coverage.scope,missing_axes:coverage.missing_axes},null,2))}</pre></details>`;
    html+=report.missing_critical_requirements.map(s=>`<div class="builder-error">Не покрыто критическое требование: ${escapeHtml(s)}</div>`).join('');
  }
  html+='<h3>Вы просили</h3><ul>'+run.requirements.map(r=>`<li><b>${escapeHtml(r.source_text)}</b> — ${evaluationCoverage[r.coverage_status]}${r.missing.length?`<br><small>${escapeHtml(r.missing.join('; '))}</small>`:''}</li>`).join('')+'</ul>';
  const counts={PASS:0,FAIL:0,ERROR:0};run.scenarios.forEach(s=>{if(s.result)counts[s.result.status]++;});
  html+=`<h3>${run.provider_info.quality_independent===false?'Проверки кодом':'Сценарии'}: PASS ${counts.PASS} · FAIL ${counts.FAIL} · ERROR ${counts.ERROR}</h3>`;
  html+=run.scenarios.map(s=>`<details class="evaluation-case" data-eval-case="${escapeHtml(s.id)}"><summary>${escapeHtml(s.result?.status||'Ожидает')} · ${escapeHtml(s.title)} · ${escapeHtml(s.scenario_type)}</summary><p>Ожидается: ${escapeHtml(s.expected_behavior)}</p>${s.result?`<p>Безопасность: ${escapeHtml(s.result.safety_status||'не сохранено')} · Детерминированные проверки: ${escapeHtml(s.result.deterministic_status||'не сохранено')} · Оценка текста: ${escapeHtml(s.result.judge_status||'не сохранено')}</p>`:''}${s.result?.explanation?`<p><b>${escapeHtml(s.result.explanation.category)}</b></p><p>Фактический ответ: ${escapeHtml(s.result.explanation.actual)}</p><p>${escapeHtml(s.result.explanation.next_step)}</p>`:''}${(s.result?.quality_review_notes||[]).map(v=>`<div class="builder-warning">Предварительная оценка модели — проверьте вручную: ${escapeHtml(v)}</div>`).join('')}${(s.result?.explanation?.reasons||s.result?.failure_reasons||[]).map(v=>`<div class="${s.result?.status==='ERROR'?'builder-warning':s.result?.status==='PASS'?'muted':'builder-error'}">${escapeHtml(v)}</div>`).join('')}<div data-eval-trace>Раскройте для загрузки диалога и инструментов.</div></details>`).join('');
  html+=`<details><summary>Технические данные прогона</summary><p>Модель и оценщик: ${escapeHtml(JSON.stringify(run.provider_info))}. Версия набора: ${escapeHtml(run.plan?.version||run.generator_version)}. Seed: ${run.seed}.</p></details>`;
  $('#evaluationReport').innerHTML=html;
  $$('[data-eval-case]').forEach(d=>d.addEventListener('toggle',async()=>{if(!d.open||d.dataset.loaded||!run.scenarios.find(s=>s.id===d.dataset.evalCase)?.result)return;
    try{const result=await evaluationFetch(`/api/evaluations/${run.id}/scenarios/${d.dataset.evalCase}`);d.dataset.loaded='true';
      d.querySelector('[data-eval-trace]').innerHTML='<h4>Диалог</h4>'+result.trace.transcript.map(m=>`<p><b>${m.role==='user'?'Клиент':'AI'}:</b> ${escapeHtml(m.content)}</p>`).join('')+
        '<h4>Инструменты / подтверждение / provenance</h4><pre>'+escapeHtml(JSON.stringify({tool_events:result.trace.tool_events,steps:result.trace.steps,collected_fields:result.trace.collected_fields,callback_requests:result.trace.callback_requests,bookings:result.trace.bookings,escalations:result.trace.escalations,assertions:result.assertions,judge:result.judge,error:result.error},null,2))+'</pre>';
    }catch(e){d.querySelector('[data-eval-trace]').textContent=e.message;}}));
}
async function showEvaluation(id){
  const version=evaluationOpenVersion;
  clearTimeout(evaluationPoll);const run=await evaluationFetch('/api/evaluations/'+encodeURIComponent(id));
  if(version!==evaluationOpenVersion)return;
  renderEvaluation(run);
  const busy=['pending','running'].includes(run.status);$('#evaluationStart').disabled=busy||!evaluationCanStart;
  if(busy)evaluationPoll=setTimeout(()=>showEvaluation(id).catch(e=>{if(version===evaluationOpenVersion){$('#evaluationStatus').textContent=e.message;$('#evaluationStart').disabled=!evaluationCanStart;}}),1500);
}
window.addEventListener('DOMContentLoaded',()=>{
  $('#evaluationBack').onclick=()=>{++evaluationOpenVersion;clearTimeout(evaluationPoll);evaluationAgentId=null;showView('assistant');};
  $('#evaluationHistory').onchange=e=>{if(e.target.value)showEvaluation(e.target.value).catch(error=>showToast(error.message));};
  $('#evaluationStart').onclick=async()=>{if(!evaluationAgentId||!evaluationCanStart)return;const input=$('#evaluationCount');if(!input.reportValidity())return;
    const version=evaluationOpenVersion;
    $('#evaluationStart').disabled=true;try{const run=await evaluationFetch('/api/evaluations',{agent_id:evaluationAgentId,count:Number(input.value),seed:0,mode:$('#evaluationMode').value});if(version===evaluationOpenVersion)await evaluationHistory(run.id);}
    catch(e){if(version===evaluationOpenVersion){$('#evaluationStatus').textContent=e.message;$('#evaluationStart').disabled=!evaluationCanStart;}}};
});
