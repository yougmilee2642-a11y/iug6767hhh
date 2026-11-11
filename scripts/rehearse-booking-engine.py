"""Real configured Runtime rehearsal in temporary SQLite; no microphone or cloud changes."""
import json
import os
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
os.environ.update(CALLWISE_LOCAL_ONLY='true',AI_PROVIDER='ollama',CALLWISE_CONVERSATION_SAFETY='true',
                  TELEGRAM_ENABLED='false',CALLWISE_CLOUD_INTEGRATIONS_ENABLED='false')
import storage
from agents.runtime import new_interaction
from agents.factory import create_runtime
from services import customer_safety
from providers.ollama import OllamaProvider
from prompts import load_agent


def main():
    reports=[]
    with tempfile.TemporaryDirectory(prefix='callwise-booking-rehearsal-') as directory:
      with storage.isolated_database(Path(directory)/'synthetic.sqlite'):
        storage.initialize_db()
        for missing in (False,True):
            config=load_agent()
            if missing:
                config.business.knowledge['services']=[s for s in config.business.knowledge['services'] if s['name']!='стрижка']
            state=new_interaction(config)
            customer_safety.consent(state,config,True,state['privacy']['version'])
            provider=OllamaProvider()
            runtime=create_runtime(config,provider)
            transcript=[]
            opening='Я хочу записаться завтра на стрижку в пять часов'
            answer=runtime.turn(state,opening)
            transcript.extend([{'user':opening},{'assistant':answer['text']}])
            assert state['booking_preferences']['date']
            if missing:
                assert 'нет в опубликованном каталоге' in answer['text'] and not state['tool_events']
                assert state['booking_preferences']['time_candidates']==['05:00','17:00']
            else:
                assert state['booking_preferences']['time']=='17:00'
                assert state['tool_events'][0]['name']=='check_slots'
                if 'свободного слота нет' in answer['text']:
                    slot=state['tool_events'][0]['result']['slots'][0]
                    phrase='На '+slot['datetime'][11:16]
                    transcript.extend([{'user':phrase},{'assistant':runtime.turn(state,phrase)['text']}])
                for phrase in ['Алексей','+375290000000','Да, подтверждаю']:
                    transcript.extend([{'user':phrase},{'assistant':runtime.turn(state,phrase)['text']}])
                assert state['status']=='completed'
                with storage.connect() as db:
                    assert db.execute('SELECT COUNT(*) FROM bookings WHERE interaction_id=?',(state['id'],)).fetchone()[0]==1
            reports.append({'case':'unsupported_haircut' if missing else 'pitch_booking',
                            'passed':True,'status':state['status'],'flow':state['booking_flow'],
                            'model_requests':provider.request_count,'transcript':transcript})
    destination=ROOT/'proof/booking-engine-rehearsal.json'
    destination.write_text(json.dumps({'synthetic':True,'temporary_database':True,'cases':reports},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'case':item['case'],'passed':item['passed'],'model_requests':item['model_requests']} for item in reports]))


if __name__=='__main__':main()
