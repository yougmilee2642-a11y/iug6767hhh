import pytest
import storage
from evaluation.quick import quick_requirements, quick_plan, quick_scenarios
from evaluation.service import EvaluationService
from services.track1_service import Track1Service, QuickInput, FAQInput


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DB_PATH', tmp_path / 'quick-eval.sqlite')
    monkeypatch.setattr(storage, 'DATA_DIR', tmp_path)
    storage.initialize_db()


def saved_quick(role='secretary'):
    service = Track1Service()
    data = QuickInput(business_name='Тестовая компания', business_type='Услуги', city='Минск',
        facts='Компания принимает вопросы клиентов.', qa=[FAQInput(question='Как связаться?', answer='Напишите через доступный канал.')], role=role)
    candidate = service.preview(data)
    agent = service.save(candidate['candidate_id'], candidate['review_token'])
    return agent


@pytest.mark.parametrize('role', ['secretary', 'support'])
def test_prepare_uses_role_specific_quick_suite_without_business_catalog(isolated_db, role):
    agent = saved_quick(role)
    run = EvaluationService().prepare(agent['id'], count=12, seed=7, mode='CORE')
    assert run['evaluation_profile'] == 'quick_role'
    assert run['quick_profile'] == role
    assert run['plan']['suite_kind'] == 'quick_role'
    assert len(run['plan']['scenarios']) == 12
    assert run['plan']['selected_services'] == []
    assert run['plan']['selected_employees'] == []
    assert run['plan']['policy']['schedule'] == 'not_assumed'
    ids = {scenario['id'] for scenario in run['plan']['scenarios']}
    assert 'role_identity' in ids and 'unknown_question' in ids and 'explicit_handoff' in ids
    if role == 'secretary':
        assert {'callback_confirmed', 'callback_refused', 'callback_missing_phone'} <= ids
    else:
        assert {'support_no_contact', 'support_unknown', 'support_no_booking'} <= ids


def test_quick_plan_is_deterministic_and_does_not_invent_catalog(isolated_db):
    agent = saved_quick('support')
    config = __import__('agents.models', fromlist=['AgentConfig']).AgentConfig.model_validate(agent['config'])
    first = quick_plan(config, 20, 41, 'CORE')
    second = quick_plan(config, 20, 41, 'CORE')
    assert first == second
    assert first['selected_services'] == [] and first['selected_employees'] == []
    assert len(first['scenarios']) == 20


def test_quick_requirements_reflect_missing_knowledge(isolated_db):
    agent = saved_quick('support')
    config = __import__('agents.models', fromlist=['AgentConfig']).AgentConfig.model_validate(agent['config'])
    requirement = next(r for r in quick_requirements(config) if r.id == 'quick_knowledge')
    assert requirement.coverage_status == 'COVERED'
    assert all(s.coverage_axes.get('scenario') for s in quick_scenarios(config))


def test_quick_evaluation_execute_stays_in_isolated_simulation_database(isolated_db):
    from providers.base import ModelReply

    class NoopAgent:
        def complete(self, messages, tools):
            return ModelReply(text='У меня нет подтверждённой информации об этом.')

    class Judge:
        def judge(self, case):
            return {'passed': True, 'score': 1.0, 'reasons': [], 'flags': []}

    def components():
        return {'agent_factory': NoopAgent, 'simulator': None, 'generator': None, 'judge': Judge(),
                'provider_info': {'provider': 'deterministic_test_double', 'judge': 'Judge'}}

    agent = saved_quick('secretary')
    service = EvaluationService(components_factory=components)
    run = service.prepare(agent['id'], count=12, seed=2, mode='CORE')
    result = service.execute(run)
    assert result['progress'] == 12
    assert result['status'] in {'completed', 'partial'}
    assert result['plan']['suite_kind'] == 'quick_role'
    # The main application DB is never used for simulated callback records.
    with storage.connect() as db:
        table = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='callback_requests'").fetchone()
        assert table is None or db.execute('SELECT count(*) FROM callback_requests').fetchone()[0] == 0
