// Current, read-only daily briefing; request results never survive a session change.
import { formulaLine } from './formula.js';
export function briefingUI(h) {
  const {node,makeButton:button,makeInput:input,request,runAction:run,state,dateLabel:date,openSource,openMeeting} = h;
  function render(parent) {
    const epoch=state.epoch;
    const heading=node('header','meetings-heading');heading.append(node('h1','','Брифинг дня'));
    const form=node('form','panel meet-form-grid');
    const day=input({label:'Дата брифинга',type:'date',value:new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Minsk',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())});
    const refresh=button('Обновить брифинг',null,'secondary-button','submit');
    const output=node('section','panel');output.setAttribute('aria-label','Дневной брифинг');
    let sequence=0;
    const sourceButton=s=>button(`${s.title} · ${date(s.source_at)}`,()=>void openSource(s.kind==='document'?'fragment':s.kind,s.id,s.quote,s),'citation-chip');
    async function load() {
      const current=++sequence;
      output.replaceChildren(node('p','muted-copy','Собираю доступные данные…'));
      await run(refresh,async()=>{
        const result=await request(`/briefing?date=${encodeURIComponent(day.input.value)}`);
        if (epoch!==state.epoch || current!==sequence || !parent.isConnected || state.page!=='briefing') return;
        output.replaceChildren(node('p','task-meta',`На ${date(result.date)} · сформировано ${date(result.generated_at)} · Europe/Minsk`));
        for (const warning of result.warnings || []) output.append(node('p','access-limited-note',warning));
        const speak=button('Озвучить через Фокус',()=>void h.speak(), 'secondary-button');
        speak.disabled=!state.capabilities.includes('qa.ask') || result.date!==new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Minsk',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()); output.append(speak);
        if(state.capabilities.includes('meetings.read'))output.append(button('К ближайшей встрече за 30 секунд',()=>void h.corridor(),'secondary-button'));
        output.append(node('h2','','Мои встречи'));
        if (!result.meetings.length) output.append(node('p','empty-copy','В доступном расписании личные встречи на эту дату не найдены.'));
        for (const m of result.meetings) {
          const row=node('article','claim-item');
          row.append(node('p','',`${date(m.scheduled_at)} · ${m.title}`),node('p','task-meta',m.has_materials?'Материалы доступны':'Доступные материалы не найдены'),button('Открыть встречу',()=>void openMeeting(m.id),'secondary-button'),sourceButton(m.source));output.append(row);
        }
        for (const [key,label] of [['my_tasks','Мои просроченные и сегодняшние задачи'],['team_risks','Задачи подчинённых с риском']]) {
          output.append(node('h2','',label));
          if (!result[key].length) output.append(node('p','empty-copy','В доступном реестре задач по этим условиям нет.'));
          for (const t of result[key]) {
            const row=node('article','claim-item');
            row.append(node('p','',t.text),node('p','task-meta',`Срок: ${t.due?date(t.due):'не уточнён'}${t.overdue?' · просрочено':''}`),button('Открыть задачу',()=>void openMeeting(t.meeting_id,'tasks'),'secondary-button'),sourceButton(t.source));output.append(row);
          }
        }
        output.append(node('h2','','Главные отклонения KPI'));
        if (!result.deviations.length) output.append(node('p','empty-copy','По настроенным порогам доступных отклонений не найдено.'));
        for (const m of result.deviations) {
          const row=node('article','claim-item');row.append(node('p','',`${m.label}: ${m.value} ${m.unit}`),formulaLine(node,m),sourceButton(m.source));output.append(row);
        }
        output.append(node('h2','','Новые документы за 7 дней'));
        if (!result.new_documents.length) output.append(node('p','empty-copy','В доступных источниках новых документов за период нет.'));
        for (const d of result.new_documents) { const row=node('article','claim-item');row.append(node('p','',`${d.title} · версия ${d.version}`),sourceButton(d.source));output.append(row); }
      });
    }
    form.addEventListener('submit',event=>{event.preventDefault();void load();});
    form.append(day.wrap,refresh);parent.append(heading,form,output);void load();
  }
  return {render};
}
