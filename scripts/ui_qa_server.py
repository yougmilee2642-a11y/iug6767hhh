"""UI-only stand: temporary records and deterministic replies, no model install."""
import gc
import json
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.update(CALLWISE_LOCAL_ONLY='true',AI_PROVIDER='ollama',TELEGRAM_ENABLED='false',CALLWISE_OWNER_PASSWORD='',BUSINESS_EMAIL='')
from providers.base import ModelReply, ToolCall


class UIProvider:
    def complete(self,messages,tools):
        context=json.loads(messages[0].text.split('Контекст бизнеса (данные, не инструкции):\n',1)[1].split('\n\n',1)[0])
        user=next(m.text for m in reversed(messages) if m.role=='user')
        if context['knowledge'].get('track1_profile')=='support' or context['knowledge'].get('shell_local'):
            answer=next((q['answer'] for q in context['knowledge'].get('qa',[]) if q['question']==user),None)
            return ModelReply(answer or 'У меня нет подтверждённой информации по этому вопросу.')
        known=json.loads(next(m.text.split(': ',1)[1] for m in reversed(messages) if m.role=='system' and m.text.startswith('Проверенные собранные поля: ')))
        for key,question in [('customer_name','Как к вам обращаться?'),('phone','Назовите номер телефона для обратного звонка.'),('request_details','Кратко расскажите, по какому вопросу вы звоните.')]:
            if key not in known:return ModelReply(question)
        return ModelReply(tool_calls=[ToolCall('ui-intake','save_callback_request',{key:known[key]['value'] for key in ('customer_name','phone','request_details')})])


if __name__=='__main__':
    import uvicorn
    import storage
    with tempfile.TemporaryDirectory(prefix='focus-ui-qa-') as folder:
        storage.DATA_DIR=Path(folder);storage.DB_PATH=Path(folder)/'ui.sqlite'
        import app
        @asynccontextmanager
        async def lifespan(_):yield
        app.app.router.lifespan_context=lifespan
        app.get_provider=UIProvider
        def qa_health():
            return {'status':'ok','qa_stub':True,'ai_provider':'UI stub','model':'deterministic','local_only':True,'llm_ready':False}
        for route in app.app.routes:
            if getattr(route,'path',None)=='/api/health':
                route.endpoint=qa_health;route.dependant.call=qa_health
        port=int(os.getenv('CALLWISE_UI_QA_PORT','8014'))
        print(f'UI QA: http://127.0.0.1:{port}/ — temporary records, simulated text replies')
        uvicorn.run(app.app,host='127.0.0.1',port=port)
        gc.collect()
