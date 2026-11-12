"""Демо-наполнение «Фотопринт» для локального запуска: данные, протоколы и задачи.

1. Загружает набор Фотопринт v2 (сотрудники, встречи, стенограммы, документы)
   в отдельную БД — рабочая data/ не трогается.
2. Для встреч со стенограммами строит черновик протокола и подтверждает поручения
   через обычный API, как это сделал бы руководитель.

Модель здесь не вызывается: черновик даёт ScriptedDouble, который возвращает
только эталонные поручения с дословной цитатой из стенограммы. Это демо-данные,
а не измерение качества модели.

    python scripts/track3/seed_fotoprint_demo.py --db D:/projects/Callwise-local/demo-db/fotoprint.db
"""
import argparse
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.track3.paths import explicit_db  # noqa: E402

GOLD = ROOT / 'evaluation/track3/v2/gold.json'
# Встречи, которые ведёт руководитель производства (у неё есть право подтверждать протокол).
DRAFTER = 'prod_head'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db', required=True, help='Абсолютный путь к новой БД вне data/')
    args = parser.parse_args()
    path = explicit_db(args.db)
    os.environ.update(MEETINGS_DB_PATH=str(path), CALLWISE_LOCAL_ONLY='true', AI_PROVIDER='ollama',
                      TELEGRAM_ENABLED='false', MEETINGS_SECRET=secrets.token_hex(32))

    from scripts.track3.seed_fotoprint import seed
    from scripts.track3.evaluate_v2 import ScriptedDouble
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from meetings import llm, store
    from meetings.api import install

    ids = seed(str(path))
    gold = json.loads(GOLD.read_text(encoding='utf-8'))
    app = FastAPI()
    install(app)
    llm.set_llm(ScriptedDouble(gold))
    summary = {}
    try:
        with TestClient(app) as client:
            client.post('/api/meet/login', json={'login': DRAFTER, 'password': DRAFTER + '-demo'}).raise_for_status()
            for control in gold['transcripts']:
                meeting_id = ids['meetings'][control['key']]
                draft = client.post(f'/api/meet/meetings/{meeting_id}/protocol/draft')
                draft.raise_for_status()
                items = [item for item in draft.json()['protocol']['items'] if item['kind'] == 'task']
                confirm = client.post(f'/api/meet/meetings/{meeting_id}/protocol/confirm',
                                      json={'item_ids': [item['id'] for item in items]})
                confirm.raise_for_status()
                result = confirm.json()
                summary[control['key']] = {'created': len(result['created']),
                                           'already_confirmed': len(result['already_confirmed'])}
            with store.db() as connection:
                total = connection.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    finally:
        llm.set_llm(None)
        store.reset_cache()
    print(json.dumps({'db': str(path), 'protocols': summary, 'tasks_total': total}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
